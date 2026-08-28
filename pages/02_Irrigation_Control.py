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
# КОНСТАНТИ
# ============================================================

SWITCH_CODE = "switch"

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

# Інтервал автоматичної перевірки розкладу.
# 10 секунд достатньо для надійного виконання.
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

KYIV_TZ = ZoneInfo(
    TIMEZONE_ID
)


# ============================================================
# GOOGLE SHEETS
# ============================================================

@st.cache_resource
def init_google_sheets():
    """
    Підключення до Google Sheets
    через service account зі st.secrets.
    """

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

        credentials = (
            Credentials
            .from_service_account_info(
                creds_dict,
                scopes=scope
            )
        )

        client = gspread.authorize(
            credentials
        )

        spreadsheet = client.open_by_url(
            SPREADSHEET_URL
        )

        return spreadsheet

    except Exception as e:

        st.error(
            "❌ Не вдалося підключитися "
            "до Google Таблиці."
        )

        st.code(
            str(e)
        )

        return None


# ============================================================
# ОТРИМАННЯ АРКУША РОЗКЛАДУ
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
            "❌ Не знайдено аркуш "
            f"«{SCHEDULE_WORKSHEET_NAME}»."
        )

        return None

    except Exception as e:

        st.error(
            "❌ Помилка відкриття аркуша "
            "розкладу."
        )

        st.code(
            str(e)
        )

        return None


# ============================================================
# ПУСТИЙ DATAFRAME
# ============================================================

def empty_schedule_dataframe():

    return pd.DataFrame(
        columns=REQUIRED_SCHEDULE_COLUMNS
    )


# ============================================================
# ПІДГОТОВКА DATAFRAME
# ============================================================

def prepare_schedule_dataframe(df):
    """
    Готує DataFrame до роботи.

    ВАЖЛИВО:
    усі колонки переводяться у текстовий формат.
    Це усуває конфлікти типів Pandas при редагуванні
    Google Sheets.
    """

    if df is None:

        return empty_schedule_dataframe()

    if df.empty:

        return empty_schedule_dataframe()

    df = df.copy()

    # Додаємо відсутні колонки
    for column in REQUIRED_SCHEDULE_COLUMNS:

        if column not in df.columns:

            df[column] = ""

    # Залишаємо тільки потрібні колонки
    df = df[
        REQUIRED_SCHEDULE_COLUMNS
    ].copy()

    # Переводимо всі значення у безпечний текстовий формат
    for column in REQUIRED_SCHEDULE_COLUMNS:

        df[column] = df[column].astype(
            object
        )

        df[column] = df[column].map(
            lambda value:
            ""
            if pd.isna(value)
            else str(value)
        )

    return df.reset_index(
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

        df = pd.DataFrame(
            records
        )

        return prepare_schedule_dataframe(
            df
        )

    except Exception as e:

        st.error(
            "❌ Помилка завантаження "
            "розкладу."
        )

        st.code(
            str(e)
        )

        return empty_schedule_dataframe()


# ============================================================
# ЗБЕРЕЖЕННЯ РОЗКЛАДУ
# ============================================================

def save_schedule(df):

    try:

        worksheet = get_schedule_worksheet()

        if worksheet is None:

            return False

        df = prepare_schedule_dataframe(
            df
        )

        if len(df) > MAX_SCHEDULES:

            st.error(
                f"❌ Максимальна кількість "
                f"завдань — {MAX_SCHEDULES}."
            )

            return False

        data_to_write = [
            REQUIRED_SCHEDULE_COLUMNS
        ]

        for _, row in df.iterrows():

            data_to_write.append(
                [
                    str(
                        row.get(
                            "час",
                            ""
                        )
                    ),
                    str(
                        row.get(
                            "дія",
                            ""
                        )
                    ),
                    str(
                        row.get(
                            "дні тижня",
                            ""
                        )
                    ),
                    str(
                        row.get(
                            "активність",
                            ""
                        )
                    ),
                    str(
                        row.get(
                            "дата та час останнього виконання",
                            ""
                        )
                    ),
                    str(
                        row.get(
                            "Свердловина",
                            ""
                        )
                    ),
                ]
            )

        # Очищаємо старий вміст
        worksheet.clear()

        # Записуємо нову таблицю
        worksheet.update(
            range_name="A1",
            values=data_to_write
        )

        return True

    except Exception as e:

        st.error(
            "❌ Помилка збереження "
            "розкладу в Google Sheets."
        )

        st.code(
            str(e)
        )

        return False


# ============================================================
# НОРМАЛІЗАЦІЯ АКТИВНОСТІ
# ============================================================

def normalize_activity(value):
    """
    Перетворює значення з Google Sheets
    у Python bool.
    """

    if isinstance(
        value,
        bool
    ):

        return value

    if value is None:

        return False

    text = str(
        value
    ).strip().lower()

    return text in [
        "true",
        "1",
        "так",
        "yes",
        "active",
        "активне",
        "активна",
    ]


# ============================================================
# НОРМАЛІЗАЦІЯ ДІЇ
# ============================================================

def normalize_action(value):
    """
    Приводить різні варіанти запису дії
    до стандартних значень.
    """

    if value is None:

        return ""

    text = str(
        value
    ).strip().lower()

    if text in [
        "увімкнути",
        "включити",
        "on",
        "true",
        "1",
    ]:

        return "Увімкнути"

    if text in [
        "вимкнути",
        "виключити",
        "off",
        "false",
        "0",
    ]:

        return "Вимкнути"

    return str(
        value
    ).strip()


# ============================================================
# ПАРСИНГ ЧАСУ
# ============================================================

def parse_schedule_time(value):
    """
    Перетворює значення з Google Sheets
    у datetime.time.
    """

    if isinstance(
        value,
        dt_time
    ):

        return value

    if value is None:

        return None

    text = str(
        value
    ).strip()

    if not text:

        return None

    # Варіант HH:MM
    try:

        return datetime.strptime(
            text,
            "%H:%M"
        ).time()

    except Exception:
        pass

    # Варіант HH:MM:SS
    try:

        return datetime.strptime(
            text,
            "%H:%M:%S"
        ).time()

    except Exception:
        pass

    # Якщо Google повернув datetime
    try:

        parsed = pd.to_datetime(
            text,
            errors="coerce"
        )

        if not pd.isna(parsed):

            return parsed.time()

    except Exception:
        pass

    return None


# ============================================================
# ПЕРЕВІРКА ДНЯ
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
    """
    Повертає список активних днів.
    """

    if value is None:

        return []

    text = str(
        value
    ).strip()

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

            result.append(
                day
            )

    return result


# ============================================================
# ДОДАВАННЯ ЗАВДАННЯ
# ============================================================

def add_schedule_task(
    schedule_time,
    action,
    selected_days,
    active,
    well
):

    df = load_schedule()

    df = prepare_schedule_dataframe(
        df
    )

    if len(df) >= MAX_SCHEDULES:

        return (
            False,
            f"Досягнуто максимуму "
            f"{MAX_SCHEDULES} завдань."
        )

    days_text = ", ".join(
        selected_days
    )

    new_row = {
        "час": schedule_time.strftime(
            "%H:%M"
        ),

        "дія": normalize_action(
            action
        ),

        "дні тижня": days_text,

        "активність": (
            "TRUE"
            if active
            else
            "FALSE"
        ),

        "дата та час останнього виконання": "",

        "Свердловина": str(
            well
        ),
    }

    df = pd.concat(
        [
            df,
            pd.DataFrame(
                [new_row]
            )
        ],
        ignore_index=True
    )

    success = save_schedule(
        df
    )

    if success:

        return (
            True,
            "Завдання успішно додано."
        )

    return (
        False,
        "Не вдалося зберегти завдання."
    )


# ============================================================
# ВИДАЛЕННЯ ЗАВДАННЯ
# ============================================================

def delete_schedule_task(
    index
):

    df = load_schedule()

    if index < 0 or index >= len(df):

        return False

    df = df.drop(
        index
    ).reset_index(
        drop=True
    )

    return save_schedule(
        df
    )


# ============================================================
# ЗМІНА АКТИВНОСТІ
# ============================================================

def change_schedule_activity(
    index,
    active
):

    df = load_schedule()

    df = prepare_schedule_dataframe(
        df
    )

    if index < 0 or index >= len(df):

        return False

    df.at[
        index,
        "активність"
    ] = (
        "TRUE"
        if active
        else
        "FALSE"
    )

    return save_schedule(
        df
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
    last_execution
):

    df = load_schedule()

    df = prepare_schedule_dataframe(
        df
    )

    if index < 0 or index >= len(df):

        return False

    # Усі колонки object
    for column in REQUIRED_SCHEDULE_COLUMNS:

        df[column] = df[column].astype(
            object
        )

    # Час
    if isinstance(
        schedule_time,
        dt_time
    ):

        time_value = (
            schedule_time.strftime(
                "%H:%M"
            )
        )

    else:

        time_value = str(
            schedule_time
        )

    df.at[
        index,
        "час"
    ] = time_value

    # Дія
    df.at[
        index,
        "дія"
    ] = normalize_action(
        action
    )

    # Дні
    if selected_days:

        days_value = ", ".join(
            [
                str(day)
                for day in selected_days
            ]
        )

    else:

        days_value = ""

    df.at[
        index,
        "дні тижня"
    ] = days_value

    # Активність
    df.at[
        index,
        "активність"
    ] = (
        "TRUE"
        if bool(active)
        else
        "FALSE"
    )

    # Свердловина
    df.at[
        index,
        "Свердловина"
    ] = str(
        well
    )

    # Останнє виконання
    if last_execution is None:

        last_execution_value = ""

    else:

        last_execution_value = str(
            last_execution
        )

    df.at[
        index,
        "дата та час останнього виконання"
    ] = last_execution_value

    return save_schedule(
        df
    )


# ============================================================
# TUYA — НАЛАШТУВАННЯ
# ============================================================

def get_tuya_settings():

    try:

        conf = st.secrets[
            "tuya"
        ]

        access_id = str(
            conf["access_id"]
        ).strip()

        access_key = str(
            conf["access_key"]
        ).strip()

        endpoint = str(
            conf["endpoint"]
        ).strip().rstrip("/")

        device_id = str(
            conf["breaker_device_id"]
        ).strip()

        return (
            access_id,
            access_key,
            endpoint,
            device_id
        )

    except Exception as e:

        st.error(
            "❌ Не вдалося прочитати "
            "налаштування Tuya."
        )

        st.code(
            str(e)
        )

        st.stop()


# ============================================================
# TUYA — ПІДКЛЮЧЕННЯ
# ============================================================

@st.cache_resource
def create_tuya_api(
    endpoint,
    access_id,
    access_key
):

    TUYA_LOGGER.setLevel(
        logging.ERROR
    )

    api = TuyaOpenAPI(
        endpoint,
        access_id,
        access_key
    )

    api.connect()

    return api


# ============================================================
# TUYA ПАРАМЕТРИ
# ============================================================

(
    ACCESS_ID,
    ACCESS_KEY,
    API_ENDPOINT,
    BREAKER_ID
) = get_tuya_settings()


# ============================================================
# TUYA CONNECTION
# ============================================================

try:

    tuya = create_tuya_api(
        API_ENDPOINT,
        ACCESS_ID,
        ACCESS_KEY
    )

    TUYA_CONNECTED = True

except Exception:

    tuya = None

    TUYA_CONNECTED = False


# ============================================================
# TUYA GET
# ============================================================

def tuya_get(
    uri
):

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
    body
):

    if tuya is None:

        return None

    try:

        return tuya.post(
            uri,
            body
        )

    except Exception as e:

        logging.error(
            f"Tuya POST error: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ ПОТОЧНОГО СТАНУ
# ============================================================

def get_switch_state():

    if not TUYA_CONNECTED:

        return None

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/status"
    )

    response = tuya_get(
        uri
    )

    if not isinstance(
        response,
        dict
    ):

        return None

    if not response.get(
        "success",
        False
    ):

        return None

    statuses = response.get(
        "result",
        []
    )

    if not isinstance(
        statuses,
        list
    ):

        return None

    for item in statuses:

        if item.get(
            "code"
        ) == SWITCH_CODE:

            value = item.get(
                "value"
            )

            if isinstance(
                value,
                bool
            ):

                return value

    return None


# ============================================================
# КЕРУВАННЯ АВТОМАТОМ
# ============================================================

def set_switch_state(
    state
):
    """
    Відправляє команду безпосередньо
    на автомат через Tuya Cloud API.

    Цю функцію використовує:
    1. ручне керування;
    2. автоматичний планувальник.
    """

    if not TUYA_CONNECTED:

        return False

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/commands"
    )

    body = {
        "commands": [
            {
                "code": SWITCH_CODE,
                "value": bool(
                    state
                )
            }
        ]
    }

    response = tuya_post(
        uri,
        body
    )

    if not isinstance(
        response,
        dict
    ):

        return False

    return bool(
        response.get(
            "success",
            False
        )
    )


# ============================================================
# ПЕРЕВІРКА ЧИ ЗАВДАННЯ ВЖЕ ВИКОНУВАЛОСЯ
# ============================================================

def already_executed_this_minute(
    last_execution,
    now
):
    """
    Захист від повторного виконання.

    Якщо завдання вже виконувалось у поточну
    хвилину — вдруге його не запускаємо.
    """

    if not last_execution:

        return False

    text = str(
        last_execution
    ).strip()

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
            parsed.date() == now.date()
            and
            parsed.hour == now.hour
            and
            parsed.minute == now.minute
        )

    except Exception:

        # Якщо старий запис має інший формат,
        # пробуємо просто знайти дату та час.
        try:

            parsed = pd.to_datetime(
                text,
                errors="coerce"
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
                parsed.date() == now.date()
                and
                parsed.hour == now.hour
                and
                parsed.minute == now.minute
            )

        except Exception:

            return False


# ============================================================
# ВИКОНАННЯ ОДНОГО ЗАВДАННЯ
# ============================================================

def execute_schedule_task(
    index,
    row,
    now
):
    """
    Виконує одне завдання розкладу.

    Повертає:
        success
        message
    """

    activity = normalize_activity(
        row.get(
            "активність",
            ""
        )
    )

    if not activity:

        return (
            False,
            "Завдання неактивне."
        )

    schedule_time = parse_schedule_time(
        row.get(
            "час",
            ""
        )
    )

    if schedule_time is None:

        return (
            False,
            "Некоректний час."
        )

    # --------------------------------------------------------
    # Перевірка часу
    # --------------------------------------------------------

    if (
        now.hour != schedule_time.hour
        or
        now.minute != schedule_time.minute
    ):

        return (
            False,
            "Ще не настав час."
        )

    # --------------------------------------------------------
    # Перевірка днів
    # --------------------------------------------------------

    days = parse_days(
        row.get(
            "дні тижня",
            ""
        )
    )

    today_name = get_today_name()

    # Якщо дні задані — сьогодні має бути серед них
    if days:

        if today_name not in days:

            return (
                False,
                "Сьогодні завдання не заплановане."
            )

    # --------------------------------------------------------
    # Захист від повтору
    # --------------------------------------------------------

    last_execution = str(
        row.get(
            "дата та час останнього виконання",
            ""
        )
    ).strip()

    if already_executed_this_minute(
        last_execution,
        now
    ):

        return (
            False,
            "Завдання вже виконувалось."
        )

    # --------------------------------------------------------
    # Дія
    # --------------------------------------------------------

    action = normalize_action(
        row.get(
            "дія",
            ""
        )
    )

    if action == "Увімкнути":

        target_state = True

    elif action == "Вимкнути":

        target_state = False

    else:

        return (
            False,
            "Невідома дія."
        )

    # --------------------------------------------------------
    # Свердловина
    # --------------------------------------------------------

    well = str(
        row.get(
            "Свердловина",
            ""
        )
    ).strip()

    # На цьому етапі працює свердловина 1.
    # Архітектура вже готова для додавання інших.
    if well not in [
        "1",
        "1.0",
        "Свердловина 1",
        "Свердловина №1",
    ]:

        return (
            False,
            f"Свердловина «{well}» "
            "ще не підключена."
        )

    # --------------------------------------------------------
    # Відправлення команди Tuya
    # --------------------------------------------------------

    success = set_switch_state(
        target_state
    )

    if not success:

        return (
            False,
            "Tuya не прийняла команду."
        )

    # --------------------------------------------------------
    # Запис часу виконання
    # --------------------------------------------------------

    df = load_schedule()

    if index < 0 or index >= len(df):

        return (
            True,
            "Команду Tuya виконано, "
            "але запис розкладу не знайдено."
        )

    execution_time = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    df.at[
        index,
        "дата та час останнього виконання"
    ] = execution_time

    # Одноразове завдання після виконання
    # автоматично вимикаємо.
    if not days:

        df.at[
            index,
            "активність"
        ] = "FALSE"

    saved = save_schedule(
        df
    )

    if not saved:

        return (
            True,
            "Команду Tuya виконано, "
            "але час виконання не вдалося "
            "записати в Google Sheets."
        )

    if target_state:

        action_text = "увімкнення"

    else:

        action_text = "вимкнення"

    return (
        True,
        f"Виконано {action_text} "
        f"свердловини {well}."
    )


# ============================================================
# АВТОМАТИЧНИЙ ПЛАНУВАЛЬНИК
# ============================================================

def run_scheduler():
    """
    Перевіряє Google Sheets і, якщо настав час,
    відправляє команду Tuya.

    Важливо:
    планувальник працює тільки тоді,
    коли Streamlit-сесія активна.
    """

    now = datetime.now(
        KYIV_TZ
    )

    df = load_schedule()

    if df.empty:

        return []

    results = []

    for index, row in df.iterrows():

        activity = normalize_activity(
            row.get(
                "активність",
                ""
            )
        )

        if not activity:

            continue

        schedule_time = parse_schedule_time(
            row.get(
                "час",
                ""
            )
        )

        if schedule_time is None:

            continue

        # Перевіряємо тільки поточну хвилину
        if (
            schedule_time.hour != now.hour
            or
            schedule_time.minute != now.minute
        ):

            continue

        success, message = (
            execute_schedule_task(
                index,
                row,
                now
            )
        )

        if success:

            results.append(
                (
                    index,
                    message
                )
            )

    return results


# ============================================================
# ПОТОЧНИЙ СТАН
# ============================================================

current_state = get_switch_state()


# ============================================================
# АВТОМАТИЧНИЙ ПЛАНУВАЛЬНИК
# ============================================================

# Streamlit fragment дозволяє оновлювати
# тільки цей блок без повного перезавантаження сторінки.
#
# Якщо версія Streamlit підтримує run_every,
# перевірка виконується автоматично кожні 10 секунд.

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

st.subheader(
    "1 свердловина"
)


# ============================================================
# СТАН TUYA
# ============================================================

if TUYA_CONNECTED:

    st.success(
        "🟢 Система керування підключена"
    )

else:

    st.error(
        "🔴 Немає зв'язку з Tuya Cloud"
    )


# ============================================================
# ПОТОЧНИЙ СТАН АВТОМАТА
# ============================================================

st.markdown(
    "### ⚡ Автоматичний вимикач"
)

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

    on_col, off_col = st.columns(
        2
    )

    with on_col:

        if st.button(
            "🟢 УВІМКНУТИ",
            use_container_width=True,
            type="primary",
            key="main_switch_on"
        ):

            success = set_switch_state(
                True
            )

            if success:

                st.success(
                    "Автомат увімкнено."
                )

                time.sleep(
                    0.4
                )

                st.rerun()

            else:

                st.error(
                    "Не вдалося увімкнути "
                    "автомат."
                )

    with off_col:

        if st.button(
            "🔴 ВИМКНУТИ",
            use_container_width=True,
            key="main_switch_off"
        ):

            success = set_switch_state(
                False
            )

            if success:

                st.success(
                    "Автомат вимкнено."
                )

                time.sleep(
                    0.4
                )

                st.rerun()

            else:

                st.error(
                    "Не вдалося вимкнути "
                    "автомат."
                )


# ============================================================
# РОЗКЛАД
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Розклад роботи"
)

st.caption(
    "Планувальник автоматично перевіряє "
    "час і відправляє команди через Tuya Cloud."
)


# ============================================================
# ЗАВАНТАЖЕННЯ РОЗКЛАДУ
# ============================================================

schedule_df = load_schedule()

schedule_df = prepare_schedule_dataframe(
    schedule_df
)


# ============================================================
# КІЛЬКІСТЬ ЗАВДАНЬ
# ============================================================

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
        expanded=True
    ):

        with st.form(
            "add_schedule_form",
            clear_on_submit=True
        ):

            col1, col2 = st.columns(
                2
            )

            with col1:

                schedule_time = st.time_input(
                    "Час виконання",
                    value=dt_time(
                        8,
                        0
                    ),
                    key="new_schedule_time"
                )

            with col2:

                action = st.selectbox(
                    "Дія",
                    [
                        "Увімкнути",
                        "Вимкнути",
                    ],
                    key="new_schedule_action"
                )

            selected_days = st.multiselect(
                "Дні тижня",
                WEEKDAYS,
                key="new_schedule_days",
                help=(
                    "Якщо не вибрати жодного дня, "
                    "завдання буде одноразовим."
                )
            )

            col3, col4 = st.columns(
                2
            )

            with col3:

                active = st.checkbox(
                    "Активне завдання",
                    value=True,
                    key="new_schedule_active"
                )

            with col4:

                well = st.selectbox(
                    "Свердловина",
                    [
                        "1"
                    ],
                    key="new_schedule_well"
                )

            submitted = st.form_submit_button(
                "💾 Додати завдання",
                use_container_width=True,
                type="primary"
            )

            if submitted:

                result, message = (
                    add_schedule_task(
                        schedule_time,
                        action,
                        selected_days,
                        active,
                        well
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

        # ----------------------------------------------------
        # ДАНІ
        # ----------------------------------------------------

        schedule_time_text = str(
            row.get(
                "час",
                ""
            )
        ).strip()

        action = normalize_action(
            row.get(
                "дія",
                ""
            )
        )

        days = str(
            row.get(
                "дні тижня",
                ""
            )
        ).strip()

        activity = normalize_activity(
            row.get(
                "активність",
                ""
            )
        )

        well = str(
            row.get(
                "Свердловина",
                ""
            )
        ).strip()

        last_execution = str(
            row.get(
                "дата та час останнього виконання",
                ""
            )
        ).strip()

        # ----------------------------------------------------
        # ТЕКСТ ДІЇ
        # ----------------------------------------------------

        if action == "Увімкнути":

            action_text = "🟢 Увімкнути"

        elif action == "Вимкнути":

            action_text = "🔴 Вимкнути"

        else:

            action_text = action or "—"

        # ----------------------------------------------------
        # ДНІ
        # ----------------------------------------------------

        if days:

            days_text = days

        else:

            days_text = "Одноразово"

        # ----------------------------------------------------
        # КАРТКА
        # ----------------------------------------------------

        with st.container(
            border=True
        ):

            col1, col2, col3, col4 = (
                st.columns(
                    [0.5, 1.5, 1.5, 1.5]
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

            # ------------------------------------------------
            # КНОПКИ
            # ------------------------------------------------

            button1, button2, button3 = (
                st.columns(
                    3
                )
            )

            # ------------------------------------------------
            # АКТИВНІСТЬ
            # ------------------------------------------------

            with button1:

                if activity:

                    if st.button(
                        "⏸️ Вимкнути",
                        key=(
                            f"disable_schedule_"
                            f"{index}"
                        ),
                        use_container_width=True
                    ):

                        success = (
                            change_schedule_activity(
                                index,
                                False
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
                            f"enable_schedule_"
                            f"{index}"
                        ),
                        use_container_width=True
                    ):

                        success = (
                            change_schedule_activity(
                                index,
                                True
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

            # ------------------------------------------------
            # РЕДАГУВАННЯ
            # ------------------------------------------------

            with button2:

                if st.button(
                    "✏️ Редагувати",
                    key=(
                        f"edit_schedule_"
                        f"{index}"
                    ),
                    use_container_width=True
                ):

                    st.session_state[
                        f"editing_schedule_{index}"
                    ] = True

                    st.rerun()

            # ------------------------------------------------
            # ВИДАЛЕННЯ
            # ------------------------------------------------

            with button3:

                if st.button(
                    "🗑️ Видалити",
                    key=(
                        f"delete_schedule_"
                        f"{index}"
                    ),
                    use_container_width=True
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

            # ------------------------------------------------
            # РЕДАГУВАННЯ
            # ------------------------------------------------

            if st.session_state.get(
                f"editing_schedule_{index}",
                False
            ):

                st.markdown(
                    "#### ✏️ Редагування завдання"
                )

                # --------------------------------------------
                # ЧАС
                # --------------------------------------------

                parsed_time = parse_schedule_time(
                    schedule_time_text
                )

                if parsed_time is None:

                    parsed_time = dt_time(
                        8,
                        0
                    )

                # --------------------------------------------
                # ДНІ
                # --------------------------------------------

                current_days = parse_days(
                    days
                )

                # --------------------------------------------
                # ДІЯ
                # --------------------------------------------

                action_index = (
                    0
                    if action == "Увімкнути"
                    else
                    1
                )

                # --------------------------------------------
                # СВЕРДЛОВИНА
                # --------------------------------------------

                well_index = 0

                # --------------------------------------------
                # ФОРМА
                # --------------------------------------------

                with st.form(
                    key=(
                        f"edit_form_{index}"
                    )
                ):

                    edit_time = st.time_input(
                        "Час",
                        value=parsed_time,
                        key=(
                            f"edit_time_{index}"
                        )
                    )

                    edit_action = st.selectbox(
                        "Дія",
                        [
                            "Увімкнути",
                            "Вимкнути",
                        ],
                        index=action_index,
                        key=(
                            f"edit_action_{index}"
                        )
                    )

                    edit_days = st.multiselect(
                        "Дні тижня",
                        WEEKDAYS,
                        default=current_days,
                        key=(
                            f"edit_days_{index}"
                        )
                    )

                    edit_active = st.checkbox(
                        "Активне",
                        value=activity,
                        key=(
                            f"edit_active_"
                            f"{index}"
                        )
                    )

                    edit_well = st.selectbox(
                        "Свердловина",
                        [
                            "1"
                        ],
                        index=well_index,
                        key=(
                            f"edit_well_"
                            f"{index}"
                        )
                    )

                    edit_col1, edit_col2 = (
                        st.columns(2)
                    )

                    with edit_col1:

                        save_edit = (
                            st.form_submit_button(
                                "💾 Зберегти",
                                use_container_width=True,
                                type="primary"
                            )
                        )

                    with edit_col2:

                        cancel_edit = (
                            st.form_submit_button(
                                "❌ Скасувати",
                                use_container_width=True
                            )
                        )

                    if save_edit:

                        success = (
                            update_schedule_task(
                                index,
                                edit_time,
                                edit_action,
                                edit_days,
                                edit_active,
                                edit_well,
                                last_execution
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
    use_container_width=True
):

    st.rerun()
```
