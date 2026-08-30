import streamlit as st
import pandas as pd
import time
import logging
import gspread

from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="Керування зрошенням",
    page_icon="💧",
    layout="wide",
)


# ============================================================
# CSS — ВЕЛИКІ ТУМБЛЕРИ
# ============================================================

st.markdown(
    """
    <style>

    /* =====================================================
       ВЕЛИКИЙ ТУМБЛЕР
       ===================================================== */

    div[data-testid="stCheckbox"] > label {
        font-size: 1.15rem !important;
    }

    div[data-testid="stCheckbox"] {
        zoom: 1.8;
        margin-top: -10px;
    }

    /* Великі кнопки */
    .relay-title {
        font-size: 1.35rem;
        font-weight: 700;
    }

    .relay-code {
        font-size: 0.85rem;
        color: #777;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# КОНСТАНТИ
# ============================================================

MAX_SCHEDULES = 30

TIMEZONE_ID = "Europe/Kyiv"

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1qF-7THB566lqOyQV0f6xuB052IRHh8s4CHMUpuN82P4/"
    "edit"
)

SCHEDULE_WORKSHEET_NAME = (
    "Розклад для керування Свердловинами"
)

SCHEDULER_INTERVAL_SECONDS = 10


# ============================================================
# КОЛОНКИ GOOGLE SHEETS
# ============================================================

REQUIRED_SCHEDULE_COLUMNS = [
    "час",
    "дія",
    "дні тижня",
    "активність",
    "дата та час останнього виконання",
    "Свердловина",
]


# ============================================================
# ДНІ ТИЖНЯ
# ============================================================

WEEKDAYS = [
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
]


# ============================================================
# ЧАСОВА ЗОНА
# ============================================================

KYIV_TZ = ZoneInfo(TIMEZONE_ID)


# ============================================================
# GOOGLE SHEETS
# ============================================================

@st.cache_resource
def init_google_sheets():

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    try:

        if "gcp_service_account" not in st.secrets:
            return None

        creds_dict = dict(
            st.secrets["gcp_service_account"]
        )

        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=scope,
        )

        client = gspread.authorize(credentials)

        spreadsheet = client.open_by_url(
            SPREADSHEET_URL
        )

        return spreadsheet

    except Exception as e:

        st.error(
            "❌ Не вдалося підключитися "
            "до Google Таблиці."
        )

        st.code(str(e))

        return None


# ============================================================
# АРКУШ РОЗКЛАДУ
# ============================================================

def get_schedule_worksheet():

    try:

        spreadsheet = init_google_sheets()

        if spreadsheet is None:
            return None

        return spreadsheet.worksheet(
            SCHEDULE_WORKSHEET_NAME
        )

    except gspread.WorksheetNotFound:

        st.error(
            f"❌ Не знайдено аркуш "
            f"«{SCHEDULE_WORKSHEET_NAME}»."
        )

        return None

    except Exception as e:

        st.error(
            "❌ Помилка відкриття "
            "аркуша розкладу."
        )

        st.code(str(e))

        return None


# ============================================================
# БЕЗПЕЧНИЙ ТЕКСТ
# ============================================================

def safe_text(value):

    if value is None:
        return ""

    try:

        if pd.isna(value):
            return ""

    except Exception:
        pass

    return str(value).strip()


# ============================================================
# ПУСТИЙ DATAFRAME
# ============================================================

def empty_schedule_dataframe():

    data = {
        column: []
        for column in REQUIRED_SCHEDULE_COLUMNS
    }

    return pd.DataFrame(
        data,
        dtype="object",
    )


# ============================================================
# ПІДГОТОВКА DATAFRAME
# ============================================================

def prepare_schedule_dataframe(df):

    if df is None:
        return empty_schedule_dataframe()

    try:

        if df.empty:
            return empty_schedule_dataframe()

    except Exception:

        return empty_schedule_dataframe()

    result = pd.DataFrame()

    for column in REQUIRED_SCHEDULE_COLUMNS:

        if column in df.columns:

            source = df[column]

        else:

            source = pd.Series(
                [""] * len(df),
                index=df.index,
            )

        values = []

        for value in source.tolist():

            values.append(
                safe_text(value)
            )

        result[column] = pd.Series(
            values,
            dtype="object",
        )

    return result.reset_index(
        drop=True
    )


# ============================================================
# ЗАВАНТАЖЕННЯ РОЗКЛАДУ
# ============================================================

def load_schedule():

    try:

        worksheet = get_schedule_worksheet()

        if worksheet is None:
            return empty_schedule_dataframe()

        records = worksheet.get_all_records()

        if not records:
            return empty_schedule_dataframe()

        df = pd.DataFrame(records)

        return prepare_schedule_dataframe(df)

    except Exception as e:

        st.error(
            "❌ Помилка завантаження "
            "розкладу."
        )

        st.code(str(e))

        return empty_schedule_dataframe()


# ============================================================
# ЗБЕРЕЖЕННЯ РОЗКЛАДУ
# ============================================================

def save_schedule(df):

    try:

        worksheet = get_schedule_worksheet()

        if worksheet is None:
            return False

        clean_df = prepare_schedule_dataframe(
            df
        )

        if len(clean_df) > MAX_SCHEDULES:

            st.error(
                f"❌ Максимальна кількість "
                f"завдань — {MAX_SCHEDULES}."
            )

            return False

        data_to_write = [
            REQUIRED_SCHEDULE_COLUMNS.copy()
        ]

        for row_number in range(
            len(clean_df)
        ):

            row_values = []

            for column in REQUIRED_SCHEDULE_COLUMNS:

                value = clean_df.iloc[
                    row_number
                ][column]

                row_values.append(
                    safe_text(value)
                )

            data_to_write.append(
                row_values
            )

        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=data_to_write,
        )

        return True

    except Exception as e:

        st.error(
            "❌ Помилка збереження "
            "розкладу в Google Sheets."
        )

        st.code(str(e))

        return False


# ============================================================
# НОРМАЛІЗАЦІЯ АКТИВНОСТІ
# ============================================================

def normalize_activity(value):

    if isinstance(value, bool):
        return value

    text = safe_text(value).lower()

    return text in [
        "true",
        "1",
        "так",
        "yes",
        "active",
        "активне",
        "активна",
        "увімкнено",
        "включено",
    ]


# ============================================================
# НОРМАЛІЗАЦІЯ ДІЇ
# ============================================================

def normalize_action(value):

    text = safe_text(value).lower()

    if text in [
        "увімкнути",
        "включити",
        "on",
        "true",
        "1",
        "увімкнення",
    ]:

        return "Увімкнути"

    if text in [
        "вимкнути",
        "виключити",
        "off",
        "false",
        "0",
        "вимкнення",
    ]:

        return "Вимкнути"

    return safe_text(value)


# ============================================================
# ПАРСИНГ ЧАСУ
# ============================================================

def parse_schedule_time(value):

    if isinstance(value, dt_time):
        return value

    if value is None:
        return None

    text = safe_text(value)

    if not text:
        return None

    try:

        return datetime.strptime(
            text,
            "%H:%M",
        ).time()

    except ValueError:
        pass

    try:

        return datetime.strptime(
            text,
            "%H:%M:%S",
        ).time()

    except ValueError:
        pass

    try:

        parsed = pd.to_datetime(
            text,
            errors="coerce",
        )

        if not pd.isna(parsed):
            return parsed.time()

    except Exception:
        pass

    return None


# ============================================================
# ДЕНЬ ТИЖНЯ
# ============================================================

def get_today_name():

    now = datetime.now(
        KYIV_TZ
    )

    return WEEKDAYS[
        now.weekday()
    ]


# ============================================================
# РОЗБІР ДНІВ
# ============================================================

def parse_days(value):

    text = safe_text(value)

    if not text:
        return []

    if text.lower() in [
        "одноразово",
        "one time",
        "once",
    ]:

        return []

    result = []

    for day in WEEKDAYS:

        if day in text:
            result.append(day)

    return result


# ============================================================
# ПОБУДОВА НОВОГО РЯДКА
# ============================================================

def build_schedule_row(
    schedule_time,
    action,
    selected_days,
    active,
    well,
    last_execution="",
):

    if isinstance(
        schedule_time,
        dt_time,
    ):

        time_value = (
            schedule_time.strftime(
                "%H:%M"
            )
        )

    else:

        time_value = safe_text(
            schedule_time
        )

    if selected_days:

        days_value = ", ".join(
            [
                safe_text(day)
                for day in selected_days
            ]
        )

    else:

        days_value = ""

    return {

        "час": time_value,

        "дія": normalize_action(
            action
        ),

        "дні тижня": days_value,

        "активність": (
            "TRUE"
            if bool(active)
            else "FALSE"
        ),

        "дата та час останнього виконання":
            safe_text(
                last_execution
            ),

        "Свердловина":
            safe_text(well),
    }


# ============================================================
# ДОДАВАННЯ ЗАВДАННЯ
# ============================================================

def add_schedule_task(
    schedule_time,
    action,
    selected_days,
    active,
    well,
):

    df = prepare_schedule_dataframe(
        load_schedule()
    )

    if len(df) >= MAX_SCHEDULES:

        return (
            False,
            f"Досягнуто максимуму "
            f"{MAX_SCHEDULES} завдань.",
        )

    new_row = build_schedule_row(
        schedule_time=schedule_time,
        action=action,
        selected_days=selected_days,
        active=active,
        well=well,
        last_execution="",
    )

    rows = df.to_dict(
        orient="records"
    )

    rows.append(
        new_row
    )

    new_df = pd.DataFrame(
        rows,
        columns=REQUIRED_SCHEDULE_COLUMNS,
    )

    new_df = prepare_schedule_dataframe(
        new_df
    )

    if save_schedule(new_df):

        return (
            True,
            "Завдання успішно додано.",
        )

    return (
        False,
        "Не вдалося зберегти завдання.",
    )


# ============================================================
# ВИДАЛЕННЯ ЗАВДАННЯ
# ============================================================

def delete_schedule_task(index):

    df = prepare_schedule_dataframe(
        load_schedule()
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(
        orient="records"
    )

    del rows[index]

    new_df = pd.DataFrame(
        rows,
        columns=REQUIRED_SCHEDULE_COLUMNS,
    )

    new_df = prepare_schedule_dataframe(
        new_df
    )

    return save_schedule(
        new_df
    )


# ============================================================
# ЗМІНА АКТИВНОСТІ
# ============================================================

def change_schedule_activity(
    index,
    active,
):

    df = prepare_schedule_dataframe(
        load_schedule()
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(
        orient="records"
    )

    row = dict(
        rows[index]
    )

    row["активність"] = (
        "TRUE"
        if bool(active)
        else "FALSE"
    )

    rows[index] = row

    new_df = pd.DataFrame(
        rows,
        columns=REQUIRED_SCHEDULE_COLUMNS,
    )

    new_df = prepare_schedule_dataframe(
        new_df
    )

    return save_schedule(
        new_df
    )


# ============================================================
# РЕДАГУВАННЯ ЗАВДАННЯ
# ============================================================

def update_schedule_task(
    index,
    schedule_time,
    action,
    selected_days,
    active,
    well,
    last_execution,
):

    df = prepare_schedule_dataframe(
        load_schedule()
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(
        orient="records"
    )

    updated_row = build_schedule_row(
        schedule_time=schedule_time,
        action=action,
        selected_days=selected_days,
        active=active,
        well=well,
        last_execution=last_execution,
    )

    rows[index] = updated_row

    new_df = pd.DataFrame(
        rows,
        columns=REQUIRED_SCHEDULE_COLUMNS,
    )

    new_df = prepare_schedule_dataframe(
        new_df
    )

    return save_schedule(
        new_df
    )


# ============================================================
# TUYA — НАЛАШТУВАННЯ
# ============================================================
#
# ВИДАЛЕНО: керування реле більше не потрібне, тому тут
# лишається тільки те, що дійсно використовується —
# access_id / access_key / endpoint / breaker_device_id
# (автомат свердловини №1). relay_group_device_id,
# relay_5/6/7_device_id більше не читаються.
# ============================================================

def get_tuya_settings():

    try:

        conf = st.secrets["tuya"]

        access_id = safe_text(
            conf["access_id"]
        )

        access_key = safe_text(
            conf["access_key"]
        )

        endpoint = (
            safe_text(
                conf["endpoint"]
            )
            .rstrip("/")
        )

        # ----------------------------------------------------
        # АВТОМАТ СВЕРДЛОВИНИ №1
        # ----------------------------------------------------

        breaker_device_id = safe_text(
            conf["breaker_device_id"]
        )

        return {

            "access_id":
                access_id,

            "access_key":
                access_key,

            "endpoint":
                endpoint,

            "breaker":
                breaker_device_id,
        }

    except Exception as e:

        st.error(
            "❌ Не вдалося прочитати "
            "налаштування Tuya."
        )

        st.code(str(e))

        st.stop()


# ============================================================
# TUYA CONNECTION
# ============================================================

TUYA_SETTINGS = get_tuya_settings()

ACCESS_ID = TUYA_SETTINGS[
    "access_id"
]

ACCESS_KEY = TUYA_SETTINGS[
    "access_key"
]

API_ENDPOINT = TUYA_SETTINGS[
    "endpoint"
]

BREAKER_ID = TUYA_SETTINGS[
    "breaker"
]


# ============================================================
# TUYA — ПІДКЛЮЧЕННЯ
# ============================================================

@st.cache_resource
def create_tuya_api(
    endpoint,
    access_id,
    access_key,
):

    TUYA_LOGGER.setLevel(
        logging.ERROR
    )

    api = TuyaOpenAPI(
        endpoint,
        access_id,
        access_key,
    )

    api.connect()

    return api


try:

    tuya = create_tuya_api(
        API_ENDPOINT,
        ACCESS_ID,
        ACCESS_KEY,
    )

    TUYA_CONNECTED = True

except Exception as e:

    logging.error(
        f"Tuya connection error: {e}"
    )

    tuya = None

    TUYA_CONNECTED = False


# ============================================================
# TUYA GET
# ============================================================

def tuya_get(uri):

    if tuya is None:
        return None

    try:

        return tuya.get(
            uri
        )

    except Exception as e:

        logging.error(
            f"Tuya GET error: {e}"
        )

        return None


# ============================================================
# TUYA POST
# ============================================================

def tuya_post(
    uri,
    body,
):

    if tuya is None:
        return None

    try:

        return tuya.post(
            uri,
            body,
        )

    except Exception as e:

        logging.error(
            f"Tuya POST error: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ СТАНУ БУДЬ-ЯКОГО ПРИСТРОЮ
# ============================================================

def get_device_status(
    device_id
):

    if not TUYA_CONNECTED:
        return None

    device_id = safe_text(
        device_id
    )

    if not device_id:
        return None

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{device_id}/status"
    )

    response = tuya_get(
        uri
    )

    if not isinstance(
        response,
        dict,
    ):
        return None

    if not response.get(
        "success",
        False,
    ):
        return None

    result = response.get(
        "result",
        [],
    )

    if not isinstance(
        result,
        list,
    ):
        return None

    return result


# ============================================================
# ПОШУК КОДУ В СТАНІ
# ============================================================

def get_code_value(
    statuses,
    code,
):

    if not isinstance(
        statuses,
        list,
    ):
        return None

    for item in statuses:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if item.get(
            "code"
        ) == code:

            return item.get(
                "value"
            )

    return None


# ============================================================
# ПОТОЧНИЙ СТАН АВТОМАТА
# ============================================================

def get_switch_state():

    value = get_code_value(
        get_device_status(
            BREAKER_ID
        ),
        "switch",
    )

    if isinstance(
        value,
        bool,
    ):

        return value

    return None


# ============================================================
# КЕРУВАННЯ АВТОМАТОМ
# ============================================================

def set_switch_state(
    state
):

    if not TUYA_CONNECTED:
        return False

    if not BREAKER_ID:
        return False

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/commands"
    )

    body = {

        "commands": [

            {
                "code": "switch",
                "value": bool(state),
            }

        ]

    }

    response = tuya_post(
        uri,
        body,
    )

    if not isinstance(
        response,
        dict,
    ):
        return False

    return bool(
        response.get(
            "success",
            False,
        )
    )


# ============================================================
# ПЕРЕВІРКА ПОВТОРНОГО ВИКОНАННЯ
# ============================================================

def already_executed_this_minute(
    last_execution,
    now,
):

    text = safe_text(
        last_execution
    )

    if not text:
        return False

    try:

        parsed = datetime.fromisoformat(
            text
        )

        if parsed.tzinfo is None:

            parsed = parsed.replace(
                tzinfo=KYIV_TZ
            )

        parsed = parsed.astimezone(
            KYIV_TZ
        )

        return (
            parsed.date()
            == now.date()
            and
            parsed.hour
            == now.hour
            and
            parsed.minute
            == now.minute
        )

    except Exception:
        pass

    try:

        parsed = pd.to_datetime(
            text,
            errors="coerce",
        )

        if pd.isna(parsed):
            return False

        if parsed.tzinfo is None:

            parsed = parsed.tz_localize(
                KYIV_TZ
            )

        else:

            parsed = parsed.tz_convert(
                KYIV_TZ
            )

        return (
            parsed.date()
            == now.date()
            and
            parsed.hour
            == now.hour
            and
            parsed.minute
            == now.minute
        )

    except Exception:

        return False


# ============================================================
# ВИКОНАННЯ ОДНОГО ЗАВДАННЯ
# ============================================================

def execute_schedule_task(
    index,
    row,
    now,
):

    activity = normalize_activity(
        row.get(
            "активність",
            "",
        )
    )

    if not activity:

        return (
            False,
            "Завдання неактивне.",
        )

    schedule_time = parse_schedule_time(
        row.get(
            "час",
            "",
        )
    )

    if schedule_time is None:

        return (
            False,
            "Некоректний час.",
        )

    if (
        now.hour
        != schedule_time.hour
        or
        now.minute
        != schedule_time.minute
    ):

        return (
            False,
            "Ще не настав час.",
        )

    days = parse_days(
        row.get(
            "дні тижня",
            "",
        )
    )

    today_name = get_today_name()

    if days:

        if today_name not in days:

            return (
                False,
                "Сьогодні завдання "
                "не заплановане.",
            )

    last_execution = safe_text(
        row.get(
            "дата та час "
            "останнього виконання",
            "",
        )
    )

    if already_executed_this_minute(
        last_execution,
        now,
    ):

        return (
            False,
            "Завдання вже виконувалось.",
        )

    action = normalize_action(
        row.get(
            "дія",
            "",
        )
    )

    if action == "Увімкнути":

        target_state = True

    elif action == "Вимкнути":

        target_state = False

    else:

        return (
            False,
            "Невідома дія.",
        )

    well = safe_text(
        row.get(
            "Свердловина",
            "",
        )
    )

    supported_wells = [
        "1",
        "1.0",
        "Свердловина 1",
        "Свердловина №1",
    ]

    if well not in supported_wells:

        return (
            False,
            f"Свердловина «{well}» "
            "ще не підключена.",
        )

    success = set_switch_state(
        target_state
    )

    if not success:

        return (
            False,
            "Tuya не прийняла команду.",
        )

    fresh_df = prepare_schedule_dataframe(
        load_schedule()
    )

    if (
        index < 0
        or
        index >= len(fresh_df)
    ):

        return (
            True,
            "Команду Tuya виконано, "
            "але запис розкладу "
            "не знайдено.",
        )

    rows = fresh_df.to_dict(
        orient="records"
    )

    updated_row = dict(
        rows[index]
    )

    execution_time = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    updated_row[
        "дата та час останнього виконання"
    ] = execution_time

    if not days:

        updated_row[
            "активність"
        ] = "FALSE"

    rows[index] = updated_row

    updated_df = pd.DataFrame(
        rows,
        columns=REQUIRED_SCHEDULE_COLUMNS,
    )

    updated_df = prepare_schedule_dataframe(
        updated_df
    )

    saved = save_schedule(
        updated_df
    )

    if not saved:

        return (
            True,
            "Команду Tuya виконано, "
            "але час виконання не вдалося "
            "записати в Google Sheets.",
        )

    if target_state:

        action_text = "увімкнення"

    else:

        action_text = "вимкнення"

    return (
        True,
        f"Виконано {action_text} "
        f"свердловини {well}.",
    )


# ============================================================
# АВТОМАТИЧНИЙ ПЛАНУВАЛЬНИК
# ============================================================

def run_scheduler():

    now = datetime.now(
        KYIV_TZ
    )

    df = prepare_schedule_dataframe(
        load_schedule()
    )

    if df.empty:
        return []

    results = []

    for index, row in df.iterrows():

        if not normalize_activity(
            row.get(
                "активність",
                "",
            )
        ):

            continue

        schedule_time = parse_schedule_time(
            row.get(
                "час",
                "",
            )
        )

        if schedule_time is None:
            continue

        if (
            schedule_time.hour
            != now.hour
            or
            schedule_time.minute
            != now.minute
        ):

            continue

        success, message = (
            execute_schedule_task(
                index,
                row,
                now,
            )
        )

        if success:

            results.append(
                (
                    index,
                    message,
                )
            )

    return results


# ============================================================
# ПЛАНУВАЛЬНИК
# ============================================================

@st.fragment(
    run_every=SCHEDULER_INTERVAL_SECONDS
)
def scheduler_fragment():

    results = run_scheduler()

    if results:

        for _, message in results:

            st.success(
                f"⏱️ Планувальник: {message}"
            )


scheduler_fragment()


# ============================================================
# ЗАГОЛОВОК
# ============================================================

st.title(
    "💧 Керування зрошенням"
)


# ============================================================
# СТАН TUYA
# ============================================================

if TUYA_CONNECTED:

    st.success(
        "🟢 Система керування "
        "підключена до Tuya Cloud"
    )

else:

    st.error(
        "🔴 Немає зв'язку з Tuya Cloud"
    )


# ============================================================
# СВЕРДЛОВИНА №1
# ============================================================

st.markdown("---")

st.subheader(
    "🚰 Свердловина №1"
)

st.caption(
    "Автоматичний вимикач свердловини "
    "та його розклад."
)


# ============================================================
# ПОТОЧНИЙ СТАН АВТОМАТА
# ============================================================

current_state = get_switch_state()

state_col, control_col = st.columns(
    [1, 2]
)


with state_col:

    st.markdown(
        "#### Поточний стан"
    )

    if current_state is True:

        st.success(
            "🟢 УВІМКНЕНО"
        )

    elif current_state is False:

        st.error(
            "🔴 ВИМКНЕНО"
        )

    else:

        st.warning(
            "⚠️ Стан недоступний"
        )


with control_col:

    st.markdown(
        "#### Керування"
    )

    new_breaker_state = st.toggle(
        "Автоматичний вимикач",
        value=(
            current_state
            if current_state is not None
            else False
        ),
        key="breaker_toggle",
    )

    if (
        current_state is not None
        and
        new_breaker_state
        != current_state
    ):

        success = set_switch_state(
            new_breaker_state
        )

        if success:

            if new_breaker_state:

                st.success(
                    "🟢 Автомат увімкнено."
                )

            else:

                st.success(
                    "🔴 Автомат вимкнено."
                )

            time.sleep(0.4)

            st.rerun()

        else:

            st.error(
                "❌ Не вдалося змінити "
                "стан автомата."
            )


# ============================================================
# РОЗКЛАД
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Розклад роботи свердловини №1"
)

st.caption(
    "Планувальник автоматично перевіряє "
    "час і відправляє команди через Tuya Cloud."
)


# ============================================================
# ЗАВАНТАЖЕННЯ РОЗКЛАДУ
# ============================================================

schedule_df = prepare_schedule_dataframe(
    load_schedule()
)


st.write(
    f"Створено завдань: "
    f"**{len(schedule_df)} / {MAX_SCHEDULES}**"
)


# ============================================================
# ДОДАВАННЯ ЗАВДАННЯ
# ============================================================

if len(schedule_df) < MAX_SCHEDULES:

    with st.expander(
        "➕ Додати завдання",
        expanded=True,
    ):

        with st.form(
            "add_schedule_form",
            clear_on_submit=True,
        ):

            col1, col2 = st.columns(2)

            with col1:

                schedule_time = st.time_input(
                    "Час виконання",
                    value=dt_time(
                        8,
                        0,
                    ),
                )

            with col2:

                action = st.selectbox(
                    "Дія",
                    [
                        "Увімкнути",
                        "Вимкнути",
                    ],
                )

            selected_days = st.multiselect(
                "Дні тижня",
                WEEKDAYS,
                help=(
                    "Якщо не вибрати жодного дня, "
                    "завдання буде одноразовим."
                ),
            )

            col3, col4 = st.columns(2)

            with col3:

                active = st.checkbox(
                    "Активне завдання",
                    value=True,
                )

            with col4:

                well = st.selectbox(
                    "Свердловина",
                    ["1"],
                )

            submitted = st.form_submit_button(
                "💾 Додати завдання",
                use_container_width=True,
                type="primary",
            )

            if submitted:

                result, message = (
                    add_schedule_task(
                        schedule_time,
                        action,
                        selected_days,
                        active,
                        well,
                    )
                )

                if result:

                    st.success(
                        f"✅ {message}"
                    )

                    time.sleep(
                        0.5
                    )

                    st.rerun()

                else:

                    st.error(
                        f"❌ {message}"
                    )

else:

    st.warning(
        f"Досягнуто максимальну кількість "
        f"завдань: {MAX_SCHEDULES}."
    )


# ============================================================
# СПИСОК ЗАВДАНЬ
# ============================================================

st.markdown("---")

st.subheader(
    "📋 Заплановані завдання"
)


if schedule_df.empty:

    st.info(
        "Завдань поки немає. "
        "Натисніть «➕ Додати завдання» "
        "вище, щоб створити перше."
    )

else:

    for index, row in schedule_df.iterrows():

        schedule_time_text = safe_text(
            row.get(
                "час",
                "",
            )
        )

        action = normalize_action(
            row.get(
                "дія",
                "",
            )
        )

        days = safe_text(
            row.get(
                "дні тижня",
                "",
            )
        )

        activity = normalize_activity(
            row.get(
                "активність",
                "",
            )
        )

        well = safe_text(
            row.get(
                "Свердловина",
                "",
            )
        )

        last_execution = safe_text(
            row.get(
                "дата та час "
                "останнього виконання",
                "",
            )
        )

        if action == "Увімкнути":

            action_text = "🟢 Увімкнути"

        elif action == "Вимкнути":

            action_text = "🔴 Вимкнути"

        else:

            action_text = action or "—"

        if days:

            days_text = days

        else:

            days_text = "Одноразово"

        with st.container(
            border=True
        ):

            col1, col2, col3, col4 = (
                st.columns(
                    [
                        0.5,
                        1.5,
                        1.5,
                        1.5,
                    ]
                )
            )

            with col1:

                st.markdown(
                    f"### {index + 1}"
                )

            with col2:

                st.markdown(
                    f"**Свердловина {well}**"
                )

                st.caption(
                    days_text
                )

            with col3:

                st.markdown(
                    f"### {schedule_time_text}"
                )

                st.caption(
                    action_text
                )

            with col4:

                if activity:

                    st.success(
                        "🟢 Активне"
                    )

                else:

                    st.warning(
                        "⏸️ Вимкнене"
                    )

            if last_execution:

                st.caption(
                    "Останнє виконання: "
                    f"{last_execution}"
                )

            button1, button2, button3 = (
                st.columns(3)
            )

            with button1:

                if activity:

                    if st.button(
                        "⏸️ Вимкнути",
                        key=(
                            f"disable_schedule_{index}"
                        ),
                        use_container_width=True,
                    ):

                        success = (
                            change_schedule_activity(
                                index,
                                False,
                            )
                        )

                        if success:

                            st.success(
                                "Завдання вимкнено."
                            )

                            time.sleep(
                                0.4
                            )

                            st.rerun()

                        else:

                            st.error(
                                "Не вдалося змінити "
                                "активність."
                            )

                else:

                    if st.button(
                        "▶️ Увімкнути",
                        key=(
                            f"enable_schedule_{index}"
                        ),
                        use_container_width=True,
                    ):

                        success = (
                            change_schedule_activity(
                                index,
                                True,
                            )
                        )

                        if success:

                            st.success(
                                "Завдання увімкнено."
                            )

                            time.sleep(
                                0.4
                            )

                            st.rerun()

                        else:

                            st.error(
                                "Не вдалося змінити "
                                "активність."
                            )

            with button2:

                if st.button(
                    "✏️ Редагувати",
                    key=(
                        f"edit_schedule_{index}"
                    ),
                    use_container_width=True,
                ):

                    st.session_state[
                        f"editing_schedule_{index}"
                    ] = True

                    st.rerun()

            with button3:

                if st.button(
                    "🗑️ Видалити",
                    key=(
                        f"delete_schedule_{index}"
                    ),
                    use_container_width=True,
                ):

                    success = (
                        delete_schedule_task(
                            index
                        )
                    )

                    if success:

                        st.success(
                            "Завдання видалено."
                        )

                        time.sleep(
                            0.4
                        )

                        st.rerun()

                    else:

                        st.error(
                            "Не вдалося видалити "
                            "завдання."
                        )

            if st.session_state.get(
                f"editing_schedule_{index}",
                False,
            ):

                st.markdown(
                    "#### ✏️ Редагування завдання"
                )

                parsed_time = parse_schedule_time(
                    schedule_time_text
                )

                if parsed_time is None:

                    parsed_time = dt_time(
                        8,
                        0,
                    )

                current_days = parse_days(
                    days
                )

                if action == "Вимкнути":

                    action_index = 1

                else:

                    action_index = 0

                supported_wells = ["1"]

                if well in supported_wells:

                    well_index = (
                        supported_wells.index(
                            well
                        )
                    )

                else:

                    well_index = 0

                with st.form(
                    key=f"edit_form_{index}",
                ):

                    edit_time = st.time_input(
                        "Час",
                        value=parsed_time,
                    )

                    edit_action = st.selectbox(
                        "Дія",
                        [
                            "Увімкнути",
                            "Вимкнути",
                        ],
                        index=action_index,
                    )

                    edit_days = st.multiselect(
                        "Дні тижня",
                        WEEKDAYS,
                        default=current_days,
                    )

                    edit_active = st.checkbox(
                        "Активне",
                        value=activity,
                    )

                    edit_well = st.selectbox(
                        "Свердловина",
                        supported_wells,
                        index=well_index,
                    )

                    edit_col1, edit_col2 = (
                        st.columns(2)
                    )

                    with edit_col1:

                        save_edit = (
                            st.form_submit_button(
                                "💾 Зберегти",
                                use_container_width=True,
                                type="primary",
                            )
                        )

                    with edit_col2:

                        cancel_edit = (
                            st.form_submit_button(
                                "❌ Скасувати",
                                use_container_width=True,
                            )
                        )

                    if save_edit:

                        success = (
                            update_schedule_task(
                                index=index,
                                schedule_time=edit_time,
                                action=edit_action,
                                selected_days=edit_days,
                                active=edit_active,
                                well=edit_well,
                                last_execution=last_execution,
                            )
                        )

                        if success:

                            st.session_state[
                                f"editing_schedule_{index}"
                            ] = False

                            st.success(
                                "Зміни збережено."
                            )

                            time.sleep(
                                0.4
                            )

                            st.rerun()

                        else:

                            st.error(
                                "Не вдалося зберегти "
                                "зміни."
                            )

                    if cancel_edit:

                        st.session_state[
                            f"editing_schedule_{index}"
                        ] = False

                        st.rerun()


# ============================================================
# ОНОВЛЕННЯ
# ============================================================

st.markdown("---")

if st.button(
    "🔄 Оновити стан і розклад",
    use_container_width=True,
):

    st.rerun()
