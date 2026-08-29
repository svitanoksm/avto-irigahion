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
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
]


# ============================================================
# РОЗКЛАД МОДУЛІВ
# ============================================================

MODULE_SCHEDULE_WORKSHEET_NAME = "Розклад модулів"

MODULE_SCHEDULE_COLUMNS = [
    "ID",
    "дата та час створення запису",
    "дата та час початку",
    "модуль",
    "дія",
    "тривалість, годин",
    "активність",
    "статус",
    "дата та час фактичного виконання",
    "помилка",
]


# ============================================================
# СПИСОК НАСТУПНИХ МОДУЛІВ
# ============================================================

NEXT_MODULE_OPTIONS = [
    "Модуль 1-2",
    "Модуль 1-3",
    "Модуль 1-4",
    "Модуль 1-5",
    "Модуль 1-16",
    "Модуль 1-17",
    "Не виключати",
]


# ============================================================
# КОНФІГУРАЦІЯ МОДУЛІВ TUYA
# ============================================================

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


# ============================================================
# СТАРИЙ РОЗКЛАД СВЕРДЛОВИНИ
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
    """
    Безпечно перетворює значення на текст.
    None / NaN -> "".
    """

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip()


def format_duration_text(value):
    """
    Нормалізує тривалість для роботи всередині DataFrame.

    Приклади:
        1       -> "1"
        1.0     -> "1"
        1.05    -> "1,05"
        "1,05"  -> "1,05"
        "1.05"  -> "1,05"

    ВАЖЛИВО:
    Усередині DataFrame тривалість зберігається як ТЕКСТ.
    У Google Sheets save_module_schedule() перетворює її
    на справжнє число.
    """

    text = safe_text(value)

    if not text:
        return ""

    try:
        number = float(
            text
            .replace(" ", "")
            .replace(",", ".")
        )
    except Exception:
        return ""

    if number.is_integer():
        return str(int(number))

    result = f"{number:.6f}".rstrip("0").rstrip(".")

    return result.replace(".", ",")


def duration_to_float(value):
    """
    Перетворює тривалість у float для математичних розрахунків.
    """

    text = safe_text(value)

    if not text:
        return None

    try:
        return float(
            text
            .replace(" ", "")
            .replace(",", ".")
        )
    except Exception:
        return None


def parse_schedule_datetime(value):
    """
    Перетворює значення дати/часу у timezone-aware datetime
    з часовою зоною Europe/Kyiv.
    """

    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()

    elif isinstance(value, datetime):
        parsed = value

    elif value is None:
        return None

    else:
        text = safe_text(value)

        if not text:
            return None

        parsed = pd.to_datetime(
            text,
            errors="coerce",
            dayfirst=False,
        )

        if pd.isna(parsed):
            parsed = pd.to_datetime(
                text,
                errors="coerce",
                dayfirst=True,
            )

        if pd.isna(parsed):
            return None

        parsed = parsed.to_pydatetime()

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KYIV_TZ)

    else:
        parsed = parsed.astimezone(KYIV_TZ)

    return parsed


def format_schedule_datetime(value):
    """
    Формат:
    YYYY-MM-DD HH:MM:SS
    """

    parsed = parse_schedule_datetime(value)

    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    return safe_text(value)


def parse_schedule_time(value):
    parsed = parse_schedule_datetime(value)

    return parsed.time() if parsed else None


def format_time(value):
    parsed = parse_schedule_datetime(value)

    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    return safe_text(value)


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

    return [
        day
        for day in WEEKDAYS
        if day in text
    ]


def already_executed_this_minute(last_execution, now):
    parsed = parse_schedule_datetime(last_execution)

    if parsed is None:
        return False

    if now.tzinfo:
        now = now.astimezone(KYIV_TZ)
    else:
        now = now.replace(tzinfo=KYIV_TZ)

    return (
        parsed.date() == now.date()
        and parsed.hour == now.hour
        and parsed.minute == now.minute
    )


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

        return client.open_by_url(
            SPREADSHEET_URL
        )

    except Exception as e:
        st.error(
            "❌ Не вдалося підключитися до Google Таблиці."
        )
        st.code(str(e))

        return None


def get_worksheet(name):
    try:
        spreadsheet = init_google_sheets()

        if spreadsheet is None:
            return None

        return spreadsheet.worksheet(name)

    except gspread.WorksheetNotFound:
        st.error(
            f"❌ Не знайдено аркуш «{name}»."
        )

        return None

    except Exception as e:
        st.error(
            f"❌ Помилка відкриття аркуша «{name}»."
        )
        st.code(str(e))

        return None


def get_schedule_worksheet():
    return get_worksheet(
        SCHEDULE_WORKSHEET_NAME
    )


def get_module_schedule_worksheet():
    return get_worksheet(
        MODULE_SCHEDULE_WORKSHEET_NAME
    )


def prepare_dataframe(df, columns):
    """
    Формує DataFrame тільки з дозволеними колонками.

    Усі значення приводяться до безпечного текстового
    представлення. Це особливо важливо для Arrow String,
    який використовується новими версіями Pandas.

    Тривалість також залишається текстом.
    """

    if df is None:
        return pd.DataFrame(
            {c: [] for c in columns},
            dtype="object",
        )

    try:
        if df.empty:
            return pd.DataFrame(
                {c: [] for c in columns},
                dtype="object",
            )
    except Exception:
        return pd.DataFrame(
            {c: [] for c in columns},
            dtype="object",
        )

    result = pd.DataFrame(
        index=range(len(df)),
        dtype="object",
    )

    for column in columns:

        if column in df.columns:

            if column == "тривалість, годин":
                result[column] = [
                    format_duration_text(v)
                    for v in df[column].tolist()
                ]

            elif column == "активність":
                result[column] = [
                    normalize_activity(v)
                    for v in df[column].tolist()
                ]

            else:
                result[column] = [
                    safe_text(v)
                    for v in df[column].tolist()
                ]

        else:

            if column == "активність":
                result[column] = [True] * len(df)

            else:
                result[column] = [""] * len(df)

    return result.reset_index(drop=True)


# ============================================================
# СТАРИЙ РОЗКЛАД
# ============================================================

def load_schedule():
    try:
        worksheet = get_schedule_worksheet()

        if worksheet is None:
            return pd.DataFrame(
                {
                    c: []
                    for c in REQUIRED_SCHEDULE_COLUMNS
                }
            )

        records = worksheet.get_all_records()

        return prepare_dataframe(
            pd.DataFrame(records)
            if records
            else None,
            REQUIRED_SCHEDULE_COLUMNS,
        )

    except Exception as e:
        st.error(
            "❌ Помилка завантаження розкладу."
        )
        st.code(str(e))

        return pd.DataFrame(
            {
                c: []
                for c in REQUIRED_SCHEDULE_COLUMNS
            }
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
            st.error(
                f"❌ Максимальна кількість завдань — "
                f"{MAX_SCHEDULES}."
            )
            return False

        values = [
            REQUIRED_SCHEDULE_COLUMNS.copy()
        ]

        for _, row in clean_df.iterrows():

            values.append(
                [
                    safe_text(row[c])
                    for c in REQUIRED_SCHEDULE_COLUMNS
                ]
            )

        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=values,
        )

        return True

    except Exception as e:
        st.error(
            "❌ Помилка збереження розкладу."
        )
        st.code(str(e))

        return False


# ============================================================
# РОЗКЛАД МОДУЛІВ — ЗАВАНТАЖЕННЯ
# ============================================================

def load_module_schedule():
    """
    Завантажує тільки погоджені 10 колонок.
    """

    try:
        worksheet = get_module_schedule_worksheet()

        if worksheet is None:
            return pd.DataFrame(
                {
                    c: []
                    for c in MODULE_SCHEDULE_COLUMNS
                }
            )

        records = worksheet.get_all_records()

        if not records:
            return pd.DataFrame(
                {
                    c: []
                    for c in MODULE_SCHEDULE_COLUMNS
                }
            )

        raw_df = pd.DataFrame(records)

        return prepare_dataframe(
            raw_df,
            MODULE_SCHEDULE_COLUMNS,
        )

    except Exception as e:
        st.error(
            "❌ Помилка завантаження "
            "розкладу модулів."
        )
        st.code(str(e))

        return pd.DataFrame(
            {
                c: []
                for c in MODULE_SCHEDULE_COLUMNS
            }
        )


# ============================================================
# РОЗКЛАД МОДУЛІВ — ЗБЕРЕЖЕННЯ
# ============================================================

def save_module_schedule(df):
    """
    Зберігає РІВНО 10 колонок.

    Ключовий момент:
    --------------------------------------------
    Усередині DataFrame тривалість:
        "1,0"
        "1,05"
        "2,5"

    У Google Sheets:
        1.0
        1.05
        2.5

    Тобто Google Sheets отримує СПРАВЖНЄ ЧИСЛО,
    а не текст.

    Це запобігає проблемі:
        1,0 -> 10
        1,05 -> 105
    """

    try:
        worksheet = get_module_schedule_worksheet()

        if worksheet is None:
            return False

        clean_df = prepare_dataframe(
            df,
            MODULE_SCHEDULE_COLUMNS,
        )

        if len(clean_df) > MAX_SCHEDULES * 3:
            st.error(
                "❌ Максимальна кількість записів "
                f"розкладу — {MAX_SCHEDULES * 3}."
            )
            return False

        values = [
            MODULE_SCHEDULE_COLUMNS.copy()
        ]

        for _, row in clean_df.iterrows():

            out = []

            for column in MODULE_SCHEDULE_COLUMNS:

                value = row.get(
                    column,
                    "",
                )

                # --------------------------------------------
                # ТРИВАЛІСТЬ
                # --------------------------------------------

                if column == "тривалість, годин":

                    text = safe_text(value)

                    if not text:
                        out.append("")

                    else:
                        try:
                            number = float(
                                text
                                .replace(" ", "")
                                .replace(",", ".")
                            )

                            out.append(
                                round(number, 6)
                            )

                        except Exception:
                            out.append("")

                # --------------------------------------------
                # АКТИВНІСТЬ
                # --------------------------------------------

                elif column == "активність":

                    out.append(
                        normalize_activity(value)
                    )

                # --------------------------------------------
                # ВСІ ІНШІ КОЛОНКИ
                # --------------------------------------------

                else:

                    out.append(
                        safe_text(value)
                    )

            values.append(out)

        # --------------------------------------------
        # ПОВНІСТЮ ПЕРЕЗАПИСУЄМО ТІЛЬКИ 10 КОЛОНОК
        # --------------------------------------------

        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=values,
            raw=True,
        )

        # --------------------------------------------
        # ФОРМАТ КОЛОНКИ F
        #
        # 1 -> 1,0
        # 1.05 -> 1,05
        # 2.5 -> 2,5
        # --------------------------------------------

        try:

            worksheet.format(
                "F2:F",
                {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": "0.0#",
                    }
                },
            )

        except Exception as format_error:

            logging.warning(
                "Не вдалося встановити формат "
                f"тривалості: {format_error}"
            )

        return True

    except Exception as e:

        st.error(
            "❌ Помилка збереження "
            "розкладу модулів."
        )
        st.code(str(e))

        return False


# ============================================================
# TUYA
# ============================================================

def get_tuya_settings():

    try:

        conf = st.secrets["tuya"]

        return {
            "access_id": safe_text(
                conf["access_id"]
            ),

            "access_key": safe_text(
                conf["access_key"]
            ),

            "endpoint": safe_text(
                conf["endpoint"]
            ).rstrip("/"),

            "breaker": safe_text(
                conf["breaker_device_id"]
            ),

            "relay_group": safe_text(
                conf["relay_group_device_id"]
            ),

            "relay_5": safe_text(
                conf.get(
                    "relay_5_device_id",
                    "",
                )
            ),

            "relay_6": safe_text(
                conf.get(
                    "relay_6_device_id",
                    "",
                )
            ),

            "relay_7": safe_text(
                conf.get(
                    "relay_7_device_id",
                    "",
                )
            ),
        }

    except Exception as e:

        st.error(
            "❌ Не вдалося прочитати "
            "налаштування Tuya."
        )
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


def tuya_get(uri):

    if tuya is None:
        return None

    try:
        return tuya.get(uri)

    except Exception as e:

        logging.error(
            f"Tuya GET error: {e}"
        )

        return None


def tuya_post(uri, body):

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


def get_device_status(device_id):

    if not TUYA_CONNECTED:
        return None

    device_id = safe_text(
        device_id
    )

    if not device_id:
        return None

    response = tuya_get(
        f"/v1.0/iot-03/devices/"
        f"{device_id}/status"
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

    return (
        result
        if isinstance(result, list)
        else None
    )


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

        if (
            isinstance(item, dict)
            and item.get("code") == code
        ):
            return item.get("value")

    return None


def set_switch_state(state):

    if (
        not TUYA_CONNECTED
        or not BREAKER_ID
    ):
        return False

    response = tuya_post(
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/commands",

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
        isinstance(
            response,
            dict,
        )
        and bool(
            response.get(
                "success",
                False,
            )
        )
    )


def set_relay_state(
    device_id,
    switch_code,
    state,
    countdown_seconds=0,
):

    if not TUYA_CONNECTED:
        return False

    device_id = safe_text(
        device_id
    )

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
            switch_code.replace(
                "switch_",
                "countdown_",
            )
            if switch_code.startswith(
                "switch_"
            )
            else "countdown"
        )

        commands.append(
            {
                "code": countdown_code,
                "value": int(
                    countdown_seconds
                ),
            }
        )

    response = tuya_post(
        f"/v1.0/iot-03/devices/"
        f"{device_id}/commands",

        {
            "commands": commands
        },
    )

    return (
        isinstance(
            response,
            dict,
        )
        and bool(
            response.get(
                "success",
                False,
            )
        )
    )


def get_relay_state_by_module(
    module_name
):

    config = MODULE_CONFIG.get(
        module_name
    )

    if not config:
        return None

    device_id = safe_text(
        TUYA_SETTINGS.get(
            config["device_id_key"],
            "",
        )
    )

    if not device_id:
        return None

    value = get_code_value(
        get_device_status(
            device_id
        ),
        config["switch_code"],
    )

    return (
        value
        if isinstance(value, bool)
        else None
    )


def set_module_state(
    module_name,
    state,
    duration_seconds=0,
):

    config = MODULE_CONFIG.get(
        module_name
    )

    if not config:
        return False

    device_id = safe_text(
        TUYA_SETTINGS.get(
            config["device_id_key"],
            "",
        )
    )

    if not device_id:
        return False

    return set_relay_state(
        device_id=device_id,
        switch_code=config[
            "switch_code"
        ],
        state=state,
        countdown_seconds=(
            duration_seconds
            if state
            else 0
        ),
    )


# ============================================================
# ПОШУК ОСТАННЬОГО КОРИСТУВАЦЬКОГО ЗАПИСУ
# ============================================================

def get_last_user_record(df):
    """
    Знаходить останній запис Увімкнути,
    який має задану користувачем тривалість.
    """

    if df.empty:
        return None, None

    candidates = []

    for i, row in df.iterrows():

        if normalize_action(
            row.get("дія", "")
        ) != "Увімкнути":
            continue

        duration = safe_text(
            row.get(
                "тривалість, годин",
                "",
            )
        )

        if not duration:
            continue

        start = parse_schedule_datetime(
            row.get(
                "дата та час початку",
                "",
            )
        )

        if start is not None:
            candidates.append(
                (
                    i,
                    start,
                )
            )

    if not candidates:
        return None, None

    return max(
        candidates,
        key=lambda x: x[1],
    )


# ============================================================
# ПОШУК НАСТУПНОГО ЗАПИСУ
# ============================================================

def get_next_user_entry_defaults(df):
    """
    Для наступного користувацького запису
    автоматично визначає:

    - дату/час початку;
    - модуль.

    Початок наступного користувацького модуля =
    кінець останнього користувацького модуля.
    """

    if df.empty:

        return (
            datetime.now(
                KYIV_TZ
            ).replace(
                second=0,
                microsecond=0,
            ),
            list(
                MODULE_CONFIG.keys()
            )[0],
        )

    idx, _ = get_last_user_record(df)

    if idx is None:

        return (
            datetime.now(
                KYIV_TZ
            ).replace(
                second=0,
                microsecond=0,
            ),
            list(
                MODULE_CONFIG.keys()
            )[0],
        )

    row = df.iloc[idx]

    start = parse_schedule_datetime(
        row.get(
            "дата та час початку",
            "",
        )
    )

    duration = duration_to_float(
        row.get(
            "тривалість, годин",
            "",
        )
    )

    if duration is None:
        duration = 0.0

    next_module = ""

    # Шукаємо перший автоматичний ON
    # після користувацького ON.
    for j in range(
        idx + 1,
        len(df),
    ):

        if (
            normalize_action(
                df.iloc[j].get(
                    "дія",
                    "",
                )
            )
            == "Увімкнути"
        ):

            next_module = safe_text(
                df.iloc[j].get(
                    "модуль",
                    "",
                )
            )

            break

    if not next_module:
        next_module = list(
            MODULE_CONFIG.keys()
        )[0]

    if start is not None:

        next_start = (
            start
            + timedelta(
                hours=duration
            )
        )

    else:

        next_start = datetime.now(
            KYIV_TZ
        ).replace(
            second=0,
            microsecond=0,
        )

    return (
        next_start,
        next_module,
    )


# ============================================================
# СТВОРЕННЯ ID
# ============================================================

def make_id():

    return datetime.now(
        KYIV_TZ
    ).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )


# ============================================================
# СТВОРЕННЯ РЯДКА
# ============================================================

def make_row(
    module_name,
    action,
    start_dt,
    duration_hours="",
    status="Заплановано",
    active=True,
    created_at=None,
    error="",
):
    """
    Створює один рядок розкладу.

    Тривалість НАВМИСНО зберігається як текст:
        1,05

    Це усуває конфлікт Pandas Arrow String.
    """

    duration_value = format_duration_text(
        duration_hours
    )

    return {
        "ID": make_id(),

        "дата та час створення запису":
            format_schedule_datetime(
                created_at
                or datetime.now(
                    KYIV_TZ
                )
            ),

        "дата та час початку":
            format_schedule_datetime(
                start_dt
            ),

        "модуль":
            safe_text(
                module_name
            ),

        "дія":
            normalize_action(
                action
            ),

        "тривалість, годин":
            duration_value,

        "активність":
            bool(active),

        "статус":
            safe_text(status),

        "дата та час фактичного виконання":
            "",

        "помилка":
            safe_text(error),
    }


# ============================================================
# ПЕРШИЙ ЗАПИС
# ============================================================

def create_first_module_record(
    start_dt,
    module_name,
    duration_hours,
    next_module,
):
    """
    Перший клік створює:

    1. ON поточного модуля
    2. ON наступного модуля
    3. OFF поточного модуля

    Якщо "Не виключати":
    створюється тільки ON.
    """

    created = datetime.now(
        KYIV_TZ
    )

    duration = duration_to_float(
        duration_hours
    )

    if duration is None:
        duration = 0.0

    finish = (
        start_dt
        + timedelta(
            hours=duration
        )
    )

    rows = [
        make_row(
            module_name,
            "Увімкнути",
            start_dt,
            duration,
            created_at=created,
        )
    ]

    if next_module != "Не виключати":

        next_start = (
            finish
            - timedelta(
                minutes=3
            )
        )

        rows.append(
            make_row(
                next_module,
                "Увімкнути",
                next_start,
                "",
                created_at=created,
            )
        )

        rows.append(
            make_row(
                module_name,
                "Вимкнути",
                finish,
                "",
                created_at=created,
            )
        )

    return rows


# ============================================================
# ПРОДОВЖЕННЯ ЛАНЦЮЖКА
# ============================================================

def append_user_chain_record(
    df,
    start_dt,
    module_name,
    duration_hours,
    next_module,
):
    """
    Додає наступний користувацький запис.

    Логіка:

    Попередній автоматичний ON
        ↓
    отримує розраховану тривалість
        ↓
    новий модуль працює заданий користувачем час
        ↓
    за 3 хвилини до завершення
    вмикається наступний модуль
        ↓
    у момент завершення
    вимикається поточний модуль.

    Критично:
    тривалість у DataFrame записується ТЕКСТОМ,
    наприклад "1,05", а не float 1.05.
    """

    df = prepare_dataframe(
        df,
        MODULE_SCHEDULE_COLUMNS,
    )

    idx, _ = get_last_user_record(
        df
    )

    if idx is None:
        return (
            False,
            "Немає попереднього запису."
        )

    # --------------------------------------------------------
    # ЧАС НОВОГО КОРИСТУВАЦЬКОГО ЗАПИСУ
    # --------------------------------------------------------

    start_dt = parse_schedule_datetime(
        start_dt
    )

    if start_dt is None:
        return (
            False,
            "Некоректна дата та час "
            "нового запису."
        )

    # --------------------------------------------------------
    # ТРИВАЛІСТЬ НОВОГО ЗАПИСУ
    # --------------------------------------------------------

    duration = duration_to_float(
        duration_hours
    )

    if duration is None:
        return (
            False,
            "Некоректна тривалість "
            "нового запису."
        )

    if duration <= 0:
        return (
            False,
            "Тривалість повинна бути "
            "більшою за 0."
        )

    # --------------------------------------------------------
    # ЗНАХОДИМО АВТОМАТИЧНИЙ ON
    # --------------------------------------------------------

    auto_idx = None

    for j in range(
        idx + 1,
        len(df),
    ):

        action = normalize_action(
            df.iloc[j].get(
                "дія",
                "",
            )
        )

        duration_text = safe_text(
            df.iloc[j].get(
                "тривалість, годин",
                "",
            )
        )

        if (
            action == "Увімкнути"
            and not duration_text
        ):

            auto_idx = j
            break

    if auto_idx is None:

        return (
            False,
            "Не знайдено автоматичний "
            "запис наступного модуля."
        )

    # --------------------------------------------------------
    # ДАНІ АВТОМАТИЧНОГО ON
    # --------------------------------------------------------

    auto_row = df.iloc[
        auto_idx
    ]

    auto_start = parse_schedule_datetime(
        auto_row.get(
            "дата та час початку",
            "",
        )
    )

    auto_module = safe_text(
        auto_row.get(
            "модуль",
            "",
        )
    )

    if auto_start is None:

        return (
            False,
            "Некоректний час запуску "
            "наступного модуля."
        )

    if not auto_module:

        return (
            False,
            "Не визначено наступний модуль."
        )

    # --------------------------------------------------------
    # КІНЕЦЬ НОВОГО МОДУЛЯ
    # --------------------------------------------------------

    finish = (
        start_dt
        + timedelta(
            hours=duration
        )
    )

    # --------------------------------------------------------
    # ТРИВАЛІСТЬ АВТОМАТИЧНОГО ON
    #
    # Наприклад:
    #
    # auto_start = 15:12
    # finish     = 16:15
    #
    # результат = 1,05 год
    # --------------------------------------------------------

    auto_duration = (
        finish - auto_start
    ).total_seconds() / 3600.0

    if auto_duration <= 0:

        return (
            False,
            "Час нового запису повинен "
            "бути пізніше запуску "
            "автоматичного модуля."
        )

    # --------------------------------------------------------
    # ВАЖЛИВО!
    #
    # НЕ записуємо float.
    #
    # Записуємо:
    #     "1,05"
    #
    # Тому Arrow String не видасть TypeError.
    # --------------------------------------------------------

    df.at[
        auto_idx,
        "тривалість, годин",
    ] = format_duration_text(
        auto_duration
    )

    # --------------------------------------------------------
    # ПЕРЕТВОРЮЄМО DATAFRAME У РЯДКИ
    # --------------------------------------------------------

    rows = df.to_dict(
        orient="records"
    )

    # --------------------------------------------------------
    # ДОДАЄМО НАСТУПНИЙ МОДУЛЬ
    # --------------------------------------------------------

    if next_module != "Не виключати":

        created = datetime.now(
            KYIV_TZ
        )

        # Наступний модуль запускається
        # за 3 хвилини до завершення
        # поточного.

        next_start = (
            finish
            - timedelta(
                minutes=3
            )
        )

        # ON наступного модуля

        rows.append(
            make_row(
                next_module,
                "Увімкнути",
                next_start,
                "",
                created_at=created,
            )
        )

        # OFF поточного модуля

        rows.append(
            make_row(
                auto_module,
                "Вимкнути",
                finish,
                "",
                created_at=created,
            )
        )

    return (
        True,
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        ),
    )


# ============================================================
# ДОДАВАННЯ ЗАВДАННЯ
# ============================================================

def add_module_schedule_task(
    df,
    start_datetime,
    module_name,
    duration_hours,
    next_module,
):
    """
    Додає перший або наступний запис.
    """

    df = prepare_dataframe(
        df,
        MODULE_SCHEDULE_COLUMNS,
    )

    # --------------------------------------------------------
    # ПЕРШИЙ ЗАПИС
    # --------------------------------------------------------

    if len(df) == 0:

        rows = create_first_module_record(
            start_datetime,
            module_name,
            duration_hours,
            next_module,
        )

        result_df = pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )

        return (
            True,
            result_df,
            (
                "Створено 3 записи."
                if next_module != "Не виключати"
                else "Створено 1 запис."
            ),
        )

    # --------------------------------------------------------
    # НАСТУПНИЙ ЗАПИС
    # --------------------------------------------------------

    ok, result = append_user_chain_record(
        df,
        start_datetime,
        module_name,
        duration_hours,
        next_module,
    )

    if not ok:
        return (
            False,
            None,
            result,
        )

    return (
        True,
        result,
        "Наступний запис додано.",
    )


# ============================================================
# ВИДАЛЕННЯ
# ============================================================

def delete_module_schedule_task(
    index
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if (
        index < 0
        or index >= len(df)
    ):
        return False

    rows = df.to_dict(
        orient="records"
    )

    del rows[index]

    return save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )


# ============================================================
# ЗМІНА АКТИВНОСТІ
# ============================================================

def change_module_activity(
    index,
    active,
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if (
        index < 0
        or index >= len(df)
    ):
        return False

    df.at[
        index,
        "активність",
    ] = bool(active)

    if active:

        if safe_text(
            df.at[
                index,
                "статус",
            ]
        ) in (
            "Призупинено",
            "Помилка",
        ):

            df.at[
                index,
                "статус",
            ] = "Заплановано"

        df.at[
            index,
            "помилка",
        ] = ""

    else:

        df.at[
            index,
            "статус",
        ] = "Призупинено"

    return save_module_schedule(
        df
    )


# ============================================================
# РЕДАГУВАННЯ ЗАВДАННЯ
# ============================================================

def update_module_schedule_task(
    index,
    start_datetime,
    module_name,
    duration_hours,
    action,
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if (
        index < 0
        or index >= len(df)
    ):
        return False

    df.at[
        index,
        "дата та час початку",
    ] = format_schedule_datetime(
        start_datetime
    )

    df.at[
        index,
        "модуль",
    ] = safe_text(
        module_name
    )

    df.at[
        index,
        "дія",
    ] = normalize_action(
        action
    )

    # --------------------------------------------------------
    # ВАЖЛИВО:
    # тут також НЕ записуємо float.
    # --------------------------------------------------------

    df.at[
        index,
        "тривалість, годин",
    ] = format_duration_text(
        duration_hours
    )

    df.at[
        index,
        "статус",
    ] = "Заплановано"

    df.at[
        index,
        "дата та час фактичного виконання",
    ] = ""

    df.at[
        index,
        "помилка",
    ] = ""

    return save_module_schedule(
        df
    )


# ============================================================
# ВИКОНАННЯ ОКРЕМОГО ЗАВДАННЯ
# ============================================================

def execute_module_schedule_task(
    index,
    row,
    now,
):

    # --------------------------------------------------------
    # АКТИВНІСТЬ
    # --------------------------------------------------------

    if not normalize_activity(
        row.get(
            "активність",
            "",
        )
    ):

        return (
            False,
            "Запис неактивний."
        )

    # --------------------------------------------------------
    # ЧАС ПОЧАТКУ
    # --------------------------------------------------------

    start_dt = parse_schedule_datetime(
        row.get(
            "дата та час початку",
            "",
        )
    )

    if start_dt is None:

        return (
            False,
            "Некоректна дата та "
            "час початку."
        )

    # Виконуємо тільки протягом
    # першої хвилини після запланованого часу.

    if (
        now < start_dt
        or now >= (
            start_dt
            + timedelta(
                minutes=1
            )
        )
    ):

        return (
            False,
            "Ще не настав час виконання."
        )

    # --------------------------------------------------------
    # СТАТУС
    # --------------------------------------------------------

    status = safe_text(
        row.get(
            "статус",
            "",
        )
    )

    if status not in (
        "",
        "Заплановано",
    ):

        return (
            False,
            "Запис уже оброблений."
        )

    # --------------------------------------------------------
    # МОДУЛЬ
    # --------------------------------------------------------

    module_name = safe_text(
        row.get(
            "модуль",
            "",
        )
    )

    if module_name not in MODULE_CONFIG:

        return (
            False,
            f"Невідомий модуль "
            f"«{module_name}»."
        )

    # --------------------------------------------------------
    # ДІЯ
    # --------------------------------------------------------

    action = normalize_action(
        row.get(
            "дія",
            "",
        )
    )

    # --------------------------------------------------------
    # ТРИВАЛІСТЬ
    # --------------------------------------------------------

    duration_text = safe_text(
        row.get(
            "тривалість, годин",
            "",
        )
    )

    duration_seconds = 0

    if action == "Увімкнути":

        if not duration_text:

            return (
                False,
                "Для увімкнення ще "
                "не визначена тривалість."
            )

        duration = duration_to_float(
            duration_text
        )

        if duration is None:

            return (
                False,
                "Некоректна тривалість."
            )

        duration_seconds = max(
            1,
            int(
                round(
                    duration * 3600
                )
            ),
        )

        success = set_module_state(
            module_name,
            True,
            duration_seconds,
        )

    elif action == "Вимкнути":

        success = set_module_state(
            module_name,
            False,
        )

    else:

        return (
            False,
            f"Невідома дія "
            f"«{action}»."
        )

    # --------------------------------------------------------
    # РЕЗУЛЬТАТ TUYA
    # --------------------------------------------------------

    if not success:

        return (
            False,
            f"Tuya не прийняла "
            f"команду для {module_name}."
        )

    # --------------------------------------------------------
    # ОНОВЛЮЄМО СТАТУС У GOOGLE SHEETS
    # --------------------------------------------------------

    fresh = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < len(fresh):

        fresh.at[
            index,
            "статус",
        ] = "Виконано"

        fresh.at[
            index,
            "дата та час фактичного виконання",
        ] = now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        fresh.at[
            index,
            "помилка",
        ] = ""

        save_module_schedule(
            fresh
        )

    return (
        True,
        f"{module_name}: {action}."
    )


# ============================================================
# ПЛАНУВАЛЬНИК
# ============================================================

def run_module_scheduler():

    results = []

    now = datetime.now(
        KYIV_TZ
    )

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    for index, row in df.iterrows():

        if not normalize_activity(
            row.get(
                "активність",
                "",
            )
        ):
            continue

        success, message = (
            execute_module_schedule_task(
                index,
                row,
                now,
            )
        )

        if success:
            results.append(
                message
            )

    return results


@st.fragment(
    run_every=SCHEDULER_INTERVAL_SECONDS
)
def scheduler_fragment():

    for message in run_module_scheduler():

        st.success(
            f"⏱️ Планувальник: {message}"
        )


# ============================================================
# ІНТЕРФЕЙС
# ============================================================

scheduler_fragment()

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

current_state = get_code_value(
    get_device_status(
        BREAKER_ID
    ),
    "switch",
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

    new_breaker_state = st.toggle(
        "Автоматичний вимикач",

        value=(
            current_state
            if isinstance(
                current_state,
                bool,
            )
            else False
        ),

        key="breaker_toggle",
    )

    if (
        isinstance(
            current_state,
            bool,
        )
        and new_breaker_state
        != current_state
    ):

        if set_switch_state(
            new_breaker_state
        ):

            st.success(
                "🟢 Автомат увімкнено."
                if new_breaker_state
                else "🔴 Автомат вимкнено."
            )

            time.sleep(
                0.4
            )

            st.rerun()

        else:

            st.error(
                "❌ Не вдалося змінити "
                "стан автомата."
            )


# ============================================================
# РОЗКЛАД МОДУЛІВ
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Розклад роботи модулів"
)

st.caption(
    "Перший запис задається користувачем. "
    "Далі дата/час і модуль визначаються "
    "автоматично. Кожне додавання формує "
    "ланцюг увімкнення та вимкнення. "
    "Активність користувач не задає."
)


module_df = prepare_dataframe(
    load_module_schedule(),
    MODULE_SCHEDULE_COLUMNS,
)

user_idx, _ = get_last_user_record(
    module_df
)


# ============================================================
# ВИЗНАЧЕННЯ НАСТУПНОГО ЗАПИСУ
# ============================================================

if module_df.empty:

    next_start = (
        datetime.now(
            KYIV_TZ
        ).replace(
            second=0,
            microsecond=0,
        )
    )

    next_module = list(
        MODULE_CONFIG.keys()
    )[0]

else:

    (
        next_start,
        next_module,
    ) = get_next_user_entry_defaults(
        module_df
    )


# ============================================================
# ФОРМА ДОДАВАННЯ
# ============================================================

with st.expander(
    "➕ Додати запис у планувальник",
    expanded=True,
):

    with st.form(
        "add_module_schedule_form",
        clear_on_submit=True,
    ):

        # ----------------------------------------------------
        # ПЕРШИЙ ЗАПИС
        # ----------------------------------------------------

        if module_df.empty:

            c1, c2 = st.columns(
                2
            )

            with c1:

                module_time = st.datetime_input(
                    "Дата та час початку",
                    value=next_start,
                )

            with c2:

                module_name = st.selectbox(
                    "Модуль",
                    list(
                        MODULE_CONFIG.keys()
                    ),
                )

        # ----------------------------------------------------
        # НАСТУПНІ ЗАПИСИ
        # ----------------------------------------------------

        else:

            module_time = next_start
            module_name = next_module

            st.info(
                f"Автоматично: "
                f"**{format_schedule_datetime(module_time)}** "
                f"— **{module_name}**. "
                "Користувач змінює тільки "
                "тривалість і наступний модуль."
            )

        # ----------------------------------------------------
        # ТРИВАЛІСТЬ
        # ----------------------------------------------------

        duration_hours = st.number_input(
            "Тривалість, годин",

            min_value=0.01,
            max_value=168.0,

            value=1.0,
            step=0.5,
        )

        # ----------------------------------------------------
        # НАСТУПНИЙ МОДУЛЬ
        # ----------------------------------------------------

        next_module_choice = st.selectbox(
            "Наступний модуль",
            NEXT_MODULE_OPTIONS,
            index=0,
        )

        # ----------------------------------------------------
        # КНОПКА
        # ----------------------------------------------------

        submitted = st.form_submit_button(
            "💾 Додати запис",
            use_container_width=True,
            type="primary",
        )

        if submitted:

            ok, result_df, message = (
                add_module_schedule_task(
                    module_df,
                    module_time,
                    module_name,
                    duration_hours,
                    next_module_choice,
                )
            )

            if ok:

                if save_module_schedule(
                    result_df
                ):

                    st.success(
                        f"✅ {message}"
                    )

                    time.sleep(
                        0.3
                    )

                    st.rerun()

                else:

                    st.error(
                        "❌ Не вдалося "
                        "зберегти розклад."
                    )

            else:

                st.error(
                    f"❌ {message}"
                )


# ============================================================
# ТАБЛИЦЯ РОЗКЛАДУ
# ============================================================

st.markdown("---")

st.subheader(
    "📋 Розклад модулів"
)


module_df = prepare_dataframe(
    load_module_schedule(),
    MODULE_SCHEDULE_COLUMNS,
)


if module_df.empty:

    st.info(
        "Розклад модулів поки порожній."
    )

else:

    st.dataframe(
        module_df,
        use_container_width=True,
        hide_index=True,
    )

    # --------------------------------------------------------
    # КЕРУВАННЯ ОКРЕМИМИ РЯДКАМИ
    # --------------------------------------------------------

    for index, row in module_df.iterrows():

        with st.container(
            border=True
        ):

            c1, c2, c3, c4 = st.columns(
                [0.5, 1.5, 1.2, 1.2]
            )

            # ------------------------------------------------
            # НОМЕР
            # ------------------------------------------------

            with c1:

                st.markdown(
                    f"**{index + 1}**"
                )

            # ------------------------------------------------
            # МОДУЛЬ + ДІЯ
            # ------------------------------------------------

            with c2:

                st.markdown(
                    f"**{safe_text(row.get('модуль', ''))}** "
                    f"— "
                    f"{safe_text(row.get('дія', ''))}"
                )

                st.caption(
                    safe_text(
                        row.get(
                            "дата та час початку",
                            "",
                        )
                    )
                )

            # ------------------------------------------------
            # ТРИВАЛІСТЬ + СТАТУС
            # ------------------------------------------------

            with c3:

                duration = safe_text(
                    row.get(
                        "тривалість, годин",
                        "",
                    )
                )

                st.caption(
                    f"Тривалість: "
                    f"{duration or '—'}"
                )

                st.caption(
                    f"Статус: "
                    f"{safe_text(row.get('статус', '')) or '—'}"
                )

            # ------------------------------------------------
            # АКТИВНІСТЬ
            # ------------------------------------------------

            with c4:

                active = normalize_activity(
                    row.get(
                        "активність",
                        "",
                    )
                )

                if active:

                    st.success(
                        "🟢 Активний"
                    )

                else:

                    st.warning(
                        "⏸️ Неактивний"
                    )

            # ------------------------------------------------
            # КНОПКИ
            # ------------------------------------------------

            b1, b2 = st.columns(
                2
            )

            with b1:

                label = (
                    "⏸️ Вимкнути"
                    if active
                    else "▶️ Увімкнути"
                )

                if st.button(
                    label,
                    key=f"activity_{index}",
                    use_container_width=True,
                ):

                    if change_module_activity(
                        index,
                        not active,
                    ):

                        st.rerun()

            with b2:

                if st.button(
                    "🗑️ Видалити",
                    key=f"delete_{index}",
                    use_container_width=True,
                ):

                    if delete_module_schedule_task(
                        index
                    ):

                        st.rerun()


# ============================================================
# ПОТОЧНІ СТАНИ МОДУЛІВ
# ============================================================

st.markdown("---")

st.subheader(
    "🎛️ Керування модулями"
)


for module_name in MODULE_CONFIG:

    state = get_relay_state_by_module(
        module_name
    )

    with st.container(
        border=True
    ):

        st.markdown(
            f'<div class="relay-title">'
            f'🔌 {module_name}'
            f'</div>',
            unsafe_allow_html=True,
        )

        if state is True:

            st.success(
                "🟢 Зараз УВІМКНЕНО"
            )

        elif state is False:

            st.error(
                "🔴 Зараз ВИМКНЕНО"
            )

        else:

            st.warning(
                "⚠️ Стан недоступний"
            )

        desired = st.toggle(
            "Увімкнено",

            value=(
                state
                if isinstance(
                    state,
                    bool,
                )
                else False
            ),

            key=f"manual_{module_name}",
        )

        if (
            isinstance(
                state,
                bool,
            )
            and desired != state
        ):

            if set_module_state(
                module_name,
                desired,
            ):

                st.success(
                    (
                        "🟢 Увімкнено"
                        if desired
                        else "🔴 Вимкнено"
                    )
                    + f" {module_name}."
                )

                time.sleep(
                    0.4
                )

                st.rerun()

            else:

                st.error(
                    f"❌ Не вдалося змінити "
                    f"стан {module_name}."
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
