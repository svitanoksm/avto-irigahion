import streamlit as st
import pandas as pd
import time
import logging
import gspread

from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

st.set_page_config(
    page_title="Керування зрошенням",
    page_icon="💧",
    layout="wide",
)

MAX_SCHEDULES = 30
TIMEZONE_ID = "Europe/Kyiv"
SCHEDULER_INTERVAL_SECONDS = 10

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1qF-7THB566lqOyQV0f6xuB052IRHh8s4CHMUpuN82P4/"
    "edit"
)

SCHEDULE_WORKSHEET_NAME = "Розклад для керування Свердловинами"

KYIV_TZ = ZoneInfo(TIMEZONE_ID)

WEEKDAYS = [
    "Понеділок", "Вівторок", "Середа", "Четвер",
    "П'ятниця", "Субота", "Неділя",
]

# Новий аркуш розкладу модулів.
MODULE_SCHEDULE_WORKSHEET_NAME = "Розклад модулів"

MODULE_SCHEDULE_COLUMNS = [
    "час",
    "модуль",
    "дія",
    "тривалість, годин",
    "наступний модуль",
    "активність",
    "дата та час останнього виконання",
]

# У списку немає «Резерв».
NEXT_MODULE_OPTIONS = [
    "Модуль 1-2",
    "Модуль 1-3",
    "Модуль 1-4",
    "Модуль 1-5",
    "Модуль 1-16",
    "Модуль 1-17",
    "Не виключати",
]

# Усі керовані модулі. Резерв навмисно не входить.
MODULE_CONFIG = {
    "Модуль 1-2": {
        "device_id_key": "relay_5",
        "switch_code": "switch",
        "countdown_code": "countdown",
    },
    "Модуль 1-3": {
        "device_id_key": "relay_group",
        "switch_code": "switch_1",
        "countdown_code": "countdown_1",
    },
    "Модуль 1-4": {
        "device_id_key": "relay_group",
        "switch_code": "switch_2",
        "countdown_code": "countdown_2",
    },
    "Модуль 1-5": {
        "device_id_key": "relay_group",
        "switch_code": "switch_3",
        "countdown_code": "countdown_3",
    },
    "Модуль 1-16": {
        "device_id_key": "relay_6",
        "switch_code": "switch",
        "countdown_code": "countdown",
    },
    "Модуль 1-17": {
        "device_id_key": "relay_7",
        "switch_code": "switch",
        "countdown_code": "countdown",
    },
}

# Старий розклад свердловини залишений без зміни.
REQUIRED_SCHEDULE_COLUMNS = [
    "час",
    "дія",
    "дні тижня",
    "активність",
    "дата та час останнього виконання",
    "Свердловина",
]


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
    div[data-testid="stCheckbox"] > label {
        font-size: 1.15rem !important;
    }
    div[data-testid="stCheckbox"] > label > div:first-child {
        transform: scale(2.8);
        transform-origin: left center;
        margin-right: 32px;
    }
    div[data-testid="stCheckbox"] {
        padding-top: 14px;
        padding-bottom: 14px;
        min-height: 65px;
    }
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
# ДОПОМІЖНІ ФУНКЦІЇ
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


def parse_schedule_time(value):
    if isinstance(value, dt_time):
        return value
    if value is None:
        return None

    text = safe_text(value)
    if not text:
        return None

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass

    try:
        parsed = pd.to_datetime(text, errors="coerce")
        if not pd.isna(parsed):
            return parsed.time()
    except Exception:
        pass

    return None


def format_time(value):
    parsed = parse_schedule_time(value)
    return parsed.strftime("%H:%M") if parsed else safe_text(value)


def normalize_action(value):
    text = safe_text(value).lower()

    if text in [
        "увімкнути", "включити", "on", "true", "1",
        "увімкнення",
    ]:
        return "Увімкнути"

    if text in [
        "вимкнути", "виключити", "off", "false", "0",
        "вимкнення",
    ]:
        return "Вимкнути"

    return safe_text(value)


def normalize_activity(value):
    if isinstance(value, bool):
        return value

    text = safe_text(value).lower()
    return text in [
        "true", "1", "так", "yes", "active",
        "активне", "активна", "увімкнено", "включено",
    ]


def parse_days(value):
    text = safe_text(value)
    if not text:
        return []

    if text.lower() in ["одноразово", "one time", "once"]:
        return []

    return [day for day in WEEKDAYS if day in text]


def already_executed_this_minute(last_execution, now):
    text = safe_text(last_execution)
    if not text:
        return False

    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KYIV_TZ)
        parsed = parsed.astimezone(KYIV_TZ)

        return (
            parsed.date() == now.date()
            and parsed.hour == now.hour
            and parsed.minute == now.minute
        )
    except Exception:
        pass

    try:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return False

        if parsed.tzinfo is None:
            parsed = parsed.tz_localize(KYIV_TZ)
        else:
            parsed = parsed.tz_convert(KYIV_TZ)

        return (
            parsed.date() == now.date()
            and parsed.hour == now.hour
            and parsed.minute == now.minute
        )
    except Exception:
        return False


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

        creds_dict = dict(st.secrets["gcp_service_account"])

        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=scope,
        )

        client = gspread.authorize(credentials)
        return client.open_by_url(SPREADSHEET_URL)

    except Exception as e:
        st.error("❌ Не вдалося підключитися до Google Таблиці.")
        st.code(str(e))
        return None


def get_worksheet(name):
    try:
        spreadsheet = init_google_sheets()
        if spreadsheet is None:
            return None

        return spreadsheet.worksheet(name)

    except gspread.WorksheetNotFound:
        st.error(f"❌ Не знайдено аркуш «{name}».")
        return None

    except Exception as e:
        st.error(f"❌ Помилка відкриття аркуша «{name}».")
        st.code(str(e))
        return None


def get_schedule_worksheet():
    return get_worksheet(SCHEDULE_WORKSHEET_NAME)


def get_module_schedule_worksheet():
    return get_worksheet(MODULE_SCHEDULE_WORKSHEET_NAME)


def prepare_dataframe(df, columns):
    if df is None:
        return pd.DataFrame({c: [] for c in columns}, dtype="object")

    try:
        if df.empty:
            return pd.DataFrame({c: [] for c in columns}, dtype="object")
    except Exception:
        return pd.DataFrame({c: [] for c in columns}, dtype="object")

    result = pd.DataFrame(index=range(len(df)))

    for column in columns:
        if column in df.columns:
            result[column] = [
                safe_text(v) for v in df[column].tolist()
            ]
        else:
            result[column] = [""] * len(df)

    return result.reset_index(drop=True)


def load_schedule():
    try:
        worksheet = get_schedule_worksheet()
        if worksheet is None:
            return pd.DataFrame(
                {c: [] for c in REQUIRED_SCHEDULE_COLUMNS}
            )

        records = worksheet.get_all_records()
        return prepare_dataframe(
            pd.DataFrame(records) if records else None,
            REQUIRED_SCHEDULE_COLUMNS,
        )

    except Exception as e:
        st.error("❌ Помилка завантаження розкладу.")
        st.code(str(e))
        return pd.DataFrame(
            {c: [] for c in REQUIRED_SCHEDULE_COLUMNS}
        )


def save_schedule(df):
    try:
        worksheet = get_schedule_worksheet()
        if worksheet is None:
            return False

        clean_df = prepare_dataframe(
            df,
            REQUIRED_SCHEDULE_COLUMNS,
        )

        if len(clean_df) > MAX_SCHEDULES:
            st.error(f"❌ Максимальна кількість завдань — {MAX_SCHEDULES}.")
            return False

        values = [REQUIRED_SCHEDULE_COLUMNS.copy()]

        for _, row in clean_df.iterrows():
            values.append([
                safe_text(row[c]) for c in REQUIRED_SCHEDULE_COLUMNS
            ])

        worksheet.clear()
        worksheet.update(range_name="A1", values=values)
        return True

    except Exception as e:
        st.error("❌ Помилка збереження розкладу.")
        st.code(str(e))
        return False


def load_module_schedule():
    try:
        worksheet = get_module_schedule_worksheet()
        if worksheet is None:
            return pd.DataFrame(
                {c: [] for c in MODULE_SCHEDULE_COLUMNS}
            )

        records = worksheet.get_all_records()
        return prepare_dataframe(
            pd.DataFrame(records) if records else None,
            MODULE_SCHEDULE_COLUMNS,
        )

    except Exception as e:
        st.error("❌ Помилка завантаження розкладу модулів.")
        st.code(str(e))
        return pd.DataFrame(
            {c: [] for c in MODULE_SCHEDULE_COLUMNS}
        )


def save_module_schedule(df):
    try:
        worksheet = get_module_schedule_worksheet()
        if worksheet is None:
            return False

        clean_df = prepare_dataframe(
            df,
            MODULE_SCHEDULE_COLUMNS,
        )

        if len(clean_df) > MAX_SCHEDULES:
            st.error(f"❌ Максимальна кількість завдань — {MAX_SCHEDULES}.")
            return False

        values = [MODULE_SCHEDULE_COLUMNS.copy()]

        for _, row in clean_df.iterrows():
            values.append([
                safe_text(row[c]) for c in MODULE_SCHEDULE_COLUMNS
            ])

        worksheet.clear()
        worksheet.update(range_name="A1", values=values)
        return True

    except Exception as e:
        st.error("❌ Помилка збереження розкладу модулів.")
        st.code(str(e))
        return False


# ============================================================
# TUYA
# ============================================================

def get_tuya_settings():
    try:
        conf = st.secrets["tuya"]

        return {
            "access_id": safe_text(conf["access_id"]),
            "access_key": safe_text(conf["access_key"]),
            "endpoint": safe_text(conf["endpoint"]).rstrip("/"),
            "breaker": safe_text(conf["breaker_device_id"]),
            "relay_group": safe_text(conf["relay_group_device_id"]),
            "relay_5": safe_text(conf.get("relay_5_device_id", "")),
            "relay_6": safe_text(conf.get("relay_6_device_id", "")),
            "relay_7": safe_text(conf.get("relay_7_device_id", "")),
        }

    except Exception as e:
        st.error("❌ Не вдалося прочитати налаштування Tuya.")
        st.code(str(e))
        st.stop()


TUYA_SETTINGS = get_tuya_settings()

ACCESS_ID = TUYA_SETTINGS["access_id"]
ACCESS_KEY = TUYA_SETTINGS["access_key"]
API_ENDPOINT = TUYA_SETTINGS["endpoint"]

BREAKER_ID = TUYA_SETTINGS["breaker"]
RELAY_GROUP_ID = TUYA_SETTINGS["relay_group"]
RELAY_5_ID = TUYA_SETTINGS["relay_5"]
RELAY_6_ID = TUYA_SETTINGS["relay_6"]
RELAY_7_ID = TUYA_SETTINGS["relay_7"]


@st.cache_resource
def create_tuya_api(endpoint, access_id, access_key):
    TUYA_LOGGER.setLevel(logging.ERROR)

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
    logging.error(f"Tuya connection error: {e}")
    tuya = None
    TUYA_CONNECTED = False


def tuya_get(uri):
    if tuya is None:
        return None

    try:
        return tuya.get(uri)
    except Exception as e:
        logging.error(f"Tuya GET error: {e}")
        return None


def tuya_post(uri, body):
    if tuya is None:
        return None

    try:
        return tuya.post(uri, body)
    except Exception as e:
        logging.error(f"Tuya POST error: {e}")
        return None


def get_device_status(device_id):
    if not TUYA_CONNECTED:
        return None

    device_id = safe_text(device_id)
    if not device_id:
        return None

    response = tuya_get(
        f"/v1.0/iot-03/devices/{device_id}/status"
    )

    if not isinstance(response, dict):
        return None

    if not response.get("success", False):
        return None

    result = response.get("result", [])
    return result if isinstance(result, list) else None


def get_code_value(statuses, code):
    if not isinstance(statuses, list):
        return None

    for item in statuses:
        if isinstance(item, dict) and item.get("code") == code:
            return item.get("value")

    return None


def set_switch_state(state):
    if not TUYA_CONNECTED or not BREAKER_ID:
        return False

    response = tuya_post(
        f"/v1.0/iot-03/devices/{BREAKER_ID}/commands",
        {
            "commands": [
                {
                    "code": "switch",
                    "value": bool(state),
                }
            ]
        },
    )

    return (
        isinstance(response, dict)
        and bool(response.get("success", False))
    )


def set_relay_state(
    device_id,
    switch_code,
    state,
    countdown_seconds=0,
):
    if not TUYA_CONNECTED:
        return False

    device_id = safe_text(device_id)
    if not device_id:
        return False

    commands = [
        {
            "code": switch_code,
            "value": bool(state),
        }
    ]

    if countdown_seconds > 0:
        countdown_code = (
            switch_code.replace("switch_", "countdown_")
            if switch_code.startswith("switch_")
            else "countdown"
        )

        commands.append({
            "code": countdown_code,
            "value": int(countdown_seconds),
        })

    response = tuya_post(
        f"/v1.0/iot-03/devices/{device_id}/commands",
        {"commands": commands},
    )

    return (
        isinstance(response, dict)
        and bool(response.get("success", False))
    )


def get_relay_state_by_module(module_name):
    config = MODULE_CONFIG.get(module_name)
    if not config:
        return None

    device_id = TUYA_SETTINGS.get(config["device_id_key"], "")
    if not device_id:
        return None

    value = get_code_value(
        get_device_status(device_id),
        config["switch_code"],
    )

    return value if isinstance(value, bool) else None


def set_module_state(module_name, state, duration_seconds=0):
    config = MODULE_CONFIG.get(module_name)
    if not config:
        return False

    device_id = TUYA_SETTINGS.get(config["device_id_key"], "")
    if not device_id:
        return False

    return set_relay_state(
        device_id=device_id,
        switch_code=config["switch_code"],
        state=state,
        countdown_seconds=duration_seconds if state else 0,
    )


# ============================================================
# ПОБУДОВА НАСТУПНОГО РОЗКЛАДУ
# ============================================================

def get_next_module_schedule_values(df):
    """
    Правило створення нового запису:

    1. Якщо це перший запис:
       - час задає користувач;
       - модуль задає користувач.

    2. Якщо попередній запис існує:
       - час нового запису = час завершення попереднього модуля;
       - модуль нового запису = значення «наступний модуль»
         попереднього запису.

    Користувач НЕ задає активність.
    Активність нового запису завжди TRUE.
    """

    if df.empty:
        return dt_time(8, 0), NEXT_MODULE_OPTIONS[0], False

    previous = df.iloc[-1]

    previous_time = parse_schedule_time(
        previous.get("час", "")
    )

    previous_duration = 0.0
    try:
        previous_duration = float(
            safe_text(previous.get("тривалість, годин", "0")).replace(",", ".")
        )
    except Exception:
        previous_duration = 0.0

    if previous_time is None:
        start_time = dt_time(8, 0)
    else:
        base = datetime.combine(
            datetime.today().date(),
            previous_time,
        )

        finish = base + timedelta(hours=previous_duration)
        start_time = finish.time()

    next_module = safe_text(
        previous.get("наступний модуль", "")
    )

    if next_module not in NEXT_MODULE_OPTIONS:
        next_module = NEXT_MODULE_OPTIONS[0]

    return start_time, next_module, True


# ============================================================
# ДОДАВАННЯ МОДУЛЬНОГО РОЗКЛАДУ
# ============================================================

def add_module_schedule_task(
    schedule_time,
    module_name,
    action,
    duration_hours,
    next_module,
):
    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if len(df) >= MAX_SCHEDULES:
        return False, f"Досягнуто максимуму {MAX_SCHEDULES} завдань."

    new_row = {
        "час": format_time(schedule_time),
        "модуль": safe_text(module_name),
        "дія": normalize_action(action),
        "тривалість, годин": str(duration_hours).replace(".", ","),
        "наступний модуль": safe_text(next_module),
        "активність": "TRUE",
        "дата та час останнього виконання": "",
    }

    rows = df.to_dict(orient="records")
    rows.append(new_row)

    new_df = pd.DataFrame(
        rows,
        columns=MODULE_SCHEDULE_COLUMNS,
    )

    if save_module_schedule(new_df):
        return True, "Розклад модуля успішно додано."

    return False, "Не вдалося зберегти розклад модуля."


def delete_module_schedule_task(index):
    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(orient="records")
    del rows[index]

    return save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )


def change_module_activity(index, active):
    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(orient="records")
    rows[index]["активність"] = "TRUE" if active else "FALSE"

    return save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )


def update_module_schedule_task(
    index,
    schedule_time,
    module_name,
    action,
    duration_hours,
    next_module,
    last_execution,
):
    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(orient="records")

    rows[index] = {
        "час": format_time(schedule_time),
        "модуль": safe_text(module_name),
        "дія": normalize_action(action),
        "тривалість, годин": str(duration_hours).replace(".", ","),
        "наступний модуль": safe_text(next_module),
        "активність": safe_text(
            df.iloc[index]["активність"]
        ),
        "дата та час останнього виконання": safe_text(
            last_execution
        ),
    }

    return save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )


# ============================================================
# ВИКОНАННЯ МОДУЛЬНОГО РОЗКЛАДУ
# ============================================================

def execute_module_schedule_task(index, row, now):
    """
    ВАЖЛИВА ЛОГІКА:

    - У момент «час» вмикається поточний модуль.
    - Тривалість передається Tuya як countdown.
    - Якщо «наступний модуль» НЕ «Не виключати»,
      через 3 хвилини до завершення поточного модуля
      вмикається наступний модуль.
    - У момент завершення поточного модуля він вимикається.
    - Якщо «наступний модуль» = «Не виключати»,
      поточний модуль НЕ вимикається автоматично.
      Тобто він продовжує працювати після завершення заданої
      тривалості. Саме це означає «Не виключати».
    """

    if not normalize_activity(row.get("активність", "")):
        return False, "Запис неактивний."

    schedule_time = parse_schedule_time(row.get("час", ""))
    if schedule_time is None:
        return False, "Некоректний час."

    if now.hour != schedule_time.hour or now.minute != schedule_time.minute:
        return False, "Ще не настав час."

    days = parse_days(row.get("дні тижня", ""))

    # У модульному розкладі поле «дні тижня» більше не використовується.
    # Розклад запускається один раз після створення.
    last_execution = safe_text(
        row.get("дата та час останнього виконання", "")
    )

    if already_executed_this_minute(last_execution, now):
        return False, "Запис вже виконувався."

    module_name = safe_text(row.get("модуль", ""))
    action = normalize_action(row.get("дія", ""))

    try:
        duration_hours = float(
            safe_text(
                row.get("тривалість, годин", "0")
            ).replace(",", ".")
        )
    except Exception:
        return False, "Некоректна тривалість."

    if duration_hours <= 0:
        return False, "Тривалість повинна бути більшою за 0."

    if module_name not in MODULE_CONFIG:
        return False, f"Невідомий модуль «{module_name}»."

    if action != "Увімкнути":
        return False, (
            "Для модульного ланцюжка дія повинна бути "
            "«Увімкнути»."
        )

    next_module = safe_text(row.get("наступний модуль", ""))

    duration_seconds = max(
        1,
        int(round(duration_hours * 3600)),
    )

    # Запускаємо поточний модуль.
    success = set_module_state(
        module_name,
        True,
        duration_seconds,
    )

    if not success:
        return False, f"Tuya не прийняла команду для {module_name}."

    # Записуємо факт старту.
    fresh_df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < len(fresh_df):
        rows = fresh_df.to_dict(orient="records")
        rows[index]["дата та час останнього виконання"] = (
            now.strftime("%Y-%m-%d %H:%M:%S")
        )

        save_module_schedule(
            pd.DataFrame(
                rows,
                columns=MODULE_SCHEDULE_COLUMNS,
            )
        )

    # Перехід до наступного модуля реалізується окремими
    # відкладеними командами нижче. Це важливо, бо Streamlit
    # може заснути.
    #
    # Ми зберігаємо заплановані переходи у Google Sheets,
    # щоб після пробудження сервера їх можна було виконати.
    schedule_transition(
        module_name=module_name,
        next_module=next_module,
        start_time=now,
        duration_seconds=duration_seconds,
    )

    return True, (
        f"🟢 {module_name} увімкнено на "
        f"{duration_hours:g} год."
    )


# ============================================================
# ВІДКЛАДЕНІ ПЕРЕХОДИ
# ============================================================

TRANSITION_COLUMNS = [
    "поточний модуль",
    "наступний модуль",
    "час завершення",
    "час увімкнення наступного",
    "час вимкнення поточного",
    "стан",
]


def ensure_transition_columns():
    """
    Додає службовий аркуш переходів, якщо його ще немає.
    """

    spreadsheet = init_google_sheets()
    if spreadsheet is None:
        return None

    try:
        return spreadsheet.worksheet("Переходи модулів")
    except gspread.WorksheetNotFound:
        try:
            worksheet = spreadsheet.add_worksheet(
                title="Переходи модулів",
                rows=100,
                cols=len(TRANSITION_COLUMNS),
            )
            worksheet.update(
                range_name="A1",
                values=[TRANSITION_COLUMNS],
            )
            return worksheet
        except Exception:
            return None


def load_transitions():
    worksheet = ensure_transition_columns()

    if worksheet is None:
        return pd.DataFrame(
            {c: [] for c in TRANSITION_COLUMNS}
        )

    try:
        records = worksheet.get_all_records()
        return prepare_dataframe(
            pd.DataFrame(records) if records else None,
            TRANSITION_COLUMNS,
        )
    except Exception:
        return pd.DataFrame(
            {c: [] for c in TRANSITION_COLUMNS}
        )


def save_transitions(df):
    worksheet = ensure_transition_columns()
    if worksheet is None:
        return False

    clean_df = prepare_dataframe(
        df,
        TRANSITION_COLUMNS,
    )

    values = [TRANSITION_COLUMNS.copy()]

    for _, row in clean_df.iterrows():
        values.append([
            safe_text(row[c]) for c in TRANSITION_COLUMNS
        ])

    try:
        worksheet.clear()
        worksheet.update(
            range_name="A1",
            values=values,
        )
        return True
    except Exception:
        return False


def schedule_transition(
    module_name,
    next_module,
    start_time,
    duration_seconds,
):
    """
    Створює службовий запис.

    Для звичайного переходу:
      - поточний модуль працює до кінця;
      - наступний вмикається за 3 хв до кінця;
      - поточний вимикається в момент кінця.

    Для «Не виключати»:
      - наступний модуль не вмикається;
      - поточний модуль НЕ вимикається.
    """

    start_time = start_time.astimezone(KYIV_TZ)

    finish = start_time + timedelta(seconds=duration_seconds)

    next_start = finish - timedelta(minutes=3)

    if next_module == "Не виключати":
        next_start = None

    df = load_transitions()

    row = {
        "поточний модуль": module_name,
        "наступний модуль": next_module,
        "час завершення": finish.strftime("%Y-%m-%d %H:%M:%S"),
        "час увімкнення наступного": (
            next_start.strftime("%Y-%m-%d %H:%M:%S")
            if next_start
            else ""
        ),
        "час вимкнення поточного": (
            finish.strftime("%Y-%m-%d %H:%M:%S")
            if next_module != "Не виключати"
            else ""
        ),
        "стан": "Заплановано",
    }

    rows = df.to_dict(orient="records")
    rows.append(row)

    save_transitions(
        pd.DataFrame(
            rows,
            columns=TRANSITION_COLUMNS,
        )
    )


def execute_pending_transitions():
    """
    Обробляє службовий аркуш переходів.

    Це вирішує проблему «сервер заснув» частково:
    після пробудження сервер читає абсолютні часи з Google Sheets
    і виконує вже прострочені команди.

    Для переходу, який був пропущений повністю через сон,
    наступний модуль буде запущений при першій перевірці,
    якщо його час уже настав, а поточний буде вимкнений.
    """

    now = datetime.now(KYIV_TZ)
    df = load_transitions()

    if df.empty:
        return []

    rows = df.to_dict(orient="records")
    changed = False
    results = []

    for row in rows:
        state = safe_text(row.get("стан", ""))
        if state == "Виконано":
            continue

        current_module = safe_text(row.get("поточний модуль", ""))
        next_module = safe_text(row.get("наступний модуль", ""))

        finish_text = safe_text(row.get("час завершення", ""))
        next_start_text = safe_text(
            row.get("час увімкнення наступного", "")
        )

        try:
            finish_dt = datetime.fromisoformat(finish_text)
            if finish_dt.tzinfo is None:
                finish_dt = finish_dt.replace(tzinfo=KYIV_TZ)
            else:
                finish_dt = finish_dt.astimezone(KYIV_TZ)
        except Exception:
            continue

        # «Не виключати»:
        # нічого не вимикаємо і не вмикаємо.
        if next_module == "Не виключати":
            if now >= finish_dt:
                row["стан"] = "Виконано"
                changed = True
            continue

        try:
            next_start_dt = datetime.fromisoformat(next_start_text)
            if next_start_dt.tzinfo is None:
                next_start_dt = next_start_dt.replace(
                    tzinfo=KYIV_TZ
                )
            else:
                next_start_dt = next_start_dt.astimezone(KYIV_TZ)
        except Exception:
            continue

        # 1. Якщо настав час наступного модуля — вмикаємо його.
        if (
            next_start_dt <= now
            and state == "Заплановано"
        ):
            success = set_module_state(
                next_module,
                True,
                max(
                    1,
                    int(
                        (
                            finish_dt - next_start_dt
                        ).total_seconds()
                    ),
                ),
            )

            if success:
                row["стан"] = "Наступний увімкнено"
                changed = True
                results.append(
                    f"🟢 {next_module} увімкнено."
                )

        # 2. Після завершення вимикаємо поточний.
        if (
            finish_dt <= now
            and row.get("стан") == "Наступний увімкнено"
        ):
            success = set_module_state(
                current_module,
                False,
            )

            if success:
                row["стан"] = "Виконано"
                changed = True
                results.append(
                    f"🔴 {current_module} вимкнено."
                )

    if changed:
        save_transitions(
            pd.DataFrame(
                rows,
                columns=TRANSITION_COLUMNS,
            )
        )

    return results


# ============================================================
# АВТОМАТИЧНИЙ ПЛАНУВАЛЬНИК
# ============================================================

def run_module_scheduler():
    results = []

    # Спочатку обробляємо вже створені переходи.
    results.extend(execute_pending_transitions())

    now = datetime.now(KYIV_TZ)
    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    for index, row in df.iterrows():
        if not normalize_activity(row.get("активність", "")):
            continue

        schedule_time = parse_schedule_time(row.get("час", ""))

        if schedule_time is None:
            continue

        if (
            schedule_time.hour != now.hour
            or schedule_time.minute != now.minute
        ):
            continue

        success, message = execute_module_schedule_task(
            index,
            row,
            now,
        )

        if success:
            results.append(message)

    return results


@st.fragment(run_every=SCHEDULER_INTERVAL_SECONDS)
def scheduler_fragment():
    results = run_module_scheduler()

    for message in results:
        st.success(f"⏱️ Планувальник: {message}")


# ============================================================
# СТАРТ ПЛАНУВАЛЬНИКА
# ============================================================

scheduler_fragment()


# ============================================================
# ІНТЕРФЕЙС
# ============================================================

st.title("💧 Керування зрошенням")

if TUYA_CONNECTED:
    st.success("🟢 Система керування підключена до Tuya Cloud")
else:
    st.error("🔴 Немає зв'язку з Tuya Cloud")


# ============================================================
# СВЕРДЛОВИНА №1
# ============================================================

st.markdown("---")
st.subheader("🚰 Свердловина №1")

current_state = get_code_value(
    get_device_status(BREAKER_ID),
    "switch",
)

state_col, control_col = st.columns([1, 2])

with state_col:
    st.markdown("#### Поточний стан")

    if current_state is True:
        st.success("🟢 УВІМКНЕНО")
    elif current_state is False:
        st.error("🔴 ВИМКНЕНО")
    else:
        st.warning("⚠️ Стан недоступний")

with control_col:
    st.markdown("#### Керування")

    new_breaker_state = st.toggle(
        "Автоматичний вимикач",
        value=(
            current_state
            if isinstance(current_state, bool)
            else False
        ),
        key="breaker_toggle",
    )

    if (
        isinstance(current_state, bool)
        and new_breaker_state != current_state
    ):
        if set_switch_state(new_breaker_state):
            st.success(
                "🟢 Автомат увімкнено."
                if new_breaker_state
                else "🔴 Автомат вимкнено."
            )
            time.sleep(0.4)
            st.rerun()
        else:
            st.error("❌ Не вдалося змінити стан автомата.")


# ============================================================
# НОВИЙ РОЗКЛАД МОДУЛІВ
# ============================================================

st.markdown("---")
st.subheader("⏰ Розклад роботи модулів")

st.caption(
    "Час і модуль нового запису автоматично беруться "
    "з попереднього запису. Користувач задає лише "
    "тривалість та наступний модуль."
)

module_df = prepare_dataframe(
    load_module_schedule(),
    MODULE_SCHEDULE_COLUMNS,
)

st.write(
    f"Створено модулів у ланцюжку: "
    f"**{len(module_df)} / {MAX_SCHEDULES}**"
)


# ============================================================
# ДОДАВАННЯ МОДУЛЯ
# ============================================================

if len(module_df) < MAX_SCHEDULES:

    default_time, default_module, has_previous = (
        get_next_module_schedule_values(module_df)
    )

    with st.expander(
        "➕ Додати модуль у розклад",
        expanded=True,
    ):

        with st.form(
            "add_module_schedule_form",
            clear_on_submit=True,
        ):

            if module_df.empty:
                st.info(
                    "Це перший запис. Виберіть час старту "
                    "та модуль."
                )

                first_col1, first_col2 = st.columns(2)

                with first_col1:
                    module_time = st.time_input(
                        "Час старту",
                        value=dt_time(8, 0),
                    )

                with first_col2:
                    module_name = st.selectbox(
                        "Модуль",
                        list(MODULE_CONFIG.keys()),
                    )

            else:
                module_time = default_time
                module_name = default_module

                st.info(
                    f"Автоматично: старт **{format_time(module_time)}**, "
                    f"модуль **{module_name}**."
                )

            action = "Увімкнути"

            duration_hours = st.number_input(
                "Тривалість, годин",
                min_value=0.01,
                max_value=24.0,
                value=1.0,
                step=0.5,
            )

            next_module = st.selectbox(
                "Наступний модуль",
                NEXT_MODULE_OPTIONS,
                index=0,
                help=(
                    "«Не виключати» означає: після завершення "
                    "заданої тривалості поточний модуль "
                    "НЕ вимикається і наступний модуль "
                    "НЕ вмикається."
                ),
            )

            st.caption(
                "Активність задається автоматично — користувач "
                "її не встановлює."
            )

            submitted = st.form_submit_button(
                "💾 Додати модуль",
                use_container_width=True,
                type="primary",
            )

            if submitted:
                result, message = add_module_schedule_task(
                    schedule_time=module_time,
                    module_name=module_name,
                    action=action,
                    duration_hours=duration_hours,
                    next_module=next_module,
                )

                if result:
                    st.success(f"✅ {message}")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"❌ {message}")


# ============================================================
# СПИСОК МОДУЛЬНОГО РОЗКЛАДУ
# ============================================================

st.markdown("---")
st.subheader("📋 Ланцюжок модулів")

if module_df.empty:
    st.info("Модульний розклад поки порожній.")
else:

    for index, row in module_df.iterrows():

        module_name = safe_text(row.get("модуль", ""))
        schedule_time = format_time(row.get("час", ""))
        duration = safe_text(row.get("тривалість, годин", ""))
        next_module = safe_text(row.get("наступний модуль", ""))
        activity = normalize_activity(row.get("активність", ""))
        last_execution = safe_text(
            row.get("дата та час останнього виконання", "")
        )

        with st.container(border=True):

            c1, c2, c3, c4, c5 = st.columns(
                [0.4, 1.3, 1.0, 1.3, 1.3]
            )

            with c1:
                st.markdown(f"### {index + 1}")

            with c2:
                st.markdown(f"**{module_name}**")
                st.caption(f"Старт: {schedule_time}")

            with c3:
                st.markdown(f"**{duration} год**")
                st.caption("Тривалість")

            with c4:
                st.markdown("**Наступний:**")
                st.caption(next_module or "—")

            with c5:
                if activity:
                    st.success("🟢 Активний")
                else:
                    st.warning("⏸️ Неактивний")

            if last_execution:
                st.caption(
                    f"Останній запуск: {last_execution}"
                )

            b1, b2, b3 = st.columns(3)

            with b1:
                if activity:
                    if st.button(
                        "⏸️ Вимкнути",
                        key=f"module_disable_{index}",
                        use_container_width=True,
                    ):
                        if change_module_activity(index, False):
                            st.rerun()
                else:
                    if st.button(
                        "▶️ Увімкнути",
                        key=f"module_enable_{index}",
                        use_container_width=True,
                    ):
                        if change_module_activity(index, True):
                            st.rerun()

            with b2:
                if st.button(
                    "✏️ Редагувати",
                    key=f"module_edit_{index}",
                    use_container_width=True,
                ):
                    st.session_state[
                        f"editing_module_{index}"
                    ] = True
                    st.rerun()

            with b3:
                if st.button(
                    "🗑️ Видалити",
                    key=f"module_delete_{index}",
                    use_container_width=True,
                ):
                    if delete_module_schedule_task(index):
                        st.rerun()

            if st.session_state.get(
                f"editing_module_{index}",
                False,
            ):

                st.markdown("#### ✏️ Редагування")

                parsed_time = parse_schedule_time(
                    row.get("час", "")
                ) or dt_time(8, 0)

                current_module = (
                    module_name
                    if module_name in MODULE_CONFIG
                    else list(MODULE_CONFIG.keys())[0]
                )

                current_next = (
                    next_module
                    if next_module in NEXT_MODULE_OPTIONS
                    else "Не виключати"
                )

                try:
                    current_duration = float(
                        duration.replace(",", ".")
                    )
                except Exception:
                    current_duration = 1.0

                with st.form(
                    key=f"edit_module_form_{index}",
                ):

                    edit_time = st.time_input(
                        "Час",
                        value=parsed_time,
                    )

                    edit_module = st.selectbox(
                        "Модуль",
                        list(MODULE_CONFIG.keys()),
                        index=list(
                            MODULE_CONFIG.keys()
                        ).index(current_module),
                    )

                    st.info(
                        "Дія автоматично: Увімкнути"
                    )

                    edit_duration = st.number_input(
                        "Тривалість, годин",
                        min_value=0.01,
                        max_value=24.0,
                        value=current_duration,
                        step=0.5,
                    )

                    edit_next = st.selectbox(
                        "Наступний модуль",
                        NEXT_MODULE_OPTIONS,
                        index=NEXT_MODULE_OPTIONS.index(
                            current_next
                        ),
                    )

                    ec1, ec2 = st.columns(2)

                    with ec1:
                        save_edit = st.form_submit_button(
                            "💾 Зберегти",
                            use_container_width=True,
                            type="primary",
                        )

                    with ec2:
                        cancel_edit = st.form_submit_button(
                            "❌ Скасувати",
                            use_container_width=True,
                        )

                    if save_edit:
                        if update_module_schedule_task(
                            index=index,
                            schedule_time=edit_time,
                            module_name=edit_module,
                            action="Увімкнути",
                            duration_hours=edit_duration,
                            next_module=edit_next,
                            last_execution=last_execution,
                        ):
                            st.session_state[
                                f"editing_module_{index}"
                            ] = False
                            st.rerun()

                    if cancel_edit:
                        st.session_state[
                            f"editing_module_{index}"
                        ] = False
                        st.rerun()


# ============================================================
# ПОТОЧНІ СТАНИ МОДУЛІВ
# ============================================================

st.markdown("---")
st.subheader("🎛️ Керування модулями")

for module_name, config in MODULE_CONFIG.items():

    state = get_relay_state_by_module(module_name)

    with st.container(border=True):

        st.markdown(
            f'<div class="relay-title">🔌 {module_name}</div>',
            unsafe_allow_html=True,
        )

        if state is True:
            st.success("🟢 Зараз УВІМКНЕНО")
        elif state is False:
            st.error("🔴 Зараз ВИМКНЕНО")
        else:
            st.warning("⚠️ Стан недоступний")

        desired = st.toggle(
            "Увімкнено",
            value=state if isinstance(state, bool) else False,
            key=f"module_manual_toggle_{module_name}",
        )

        if isinstance(state, bool) and desired != state:
            if set_module_state(module_name, desired):
                st.success(
                    f"{'🟢 Увімкнено' if desired else '🔴 Вимкнено'} "
                    f"{module_name}."
                )
                time.sleep(0.4)
                st.rerun()
            else:
                st.error(
                    f"❌ Не вдалося змінити стан {module_name}."
                )


# ============================================================
# СТАН ПЕРЕХОДІВ
# ============================================================

st.markdown("---")
st.subheader("🔄 Заплановані переходи")

transitions_df = load_transitions()

if transitions_df.empty:
    st.info("Активних переходів немає.")
else:
    active_transitions = transitions_df[
        transitions_df["стан"] != "Виконано"
    ]

    if active_transitions.empty:
        st.info("Активних переходів немає.")
    else:
        st.dataframe(
            active_transitions,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# ОНОВЛЕННЯ
# ============================================================

st.markdown("---")

if st.button(
    "🔄 Оновити стан і розклад",
    use_container_width=True,
):
    st.rerun()
