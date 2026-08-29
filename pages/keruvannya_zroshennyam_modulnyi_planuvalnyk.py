```python
import streamlit as st
import pandas as pd
import time
import logging
import gspread

from datetime import datetime, timedelta
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
MODULE_SCHEDULE_WORKSHEET_NAME = "Розклад модулів"
TRANSITION_WORKSHEET_NAME = "Переходи модулів"

KYIV_TZ = ZoneInfo(TIMEZONE_ID)


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
# КОЛОНКИ СТАРОГО РОЗКЛАДУ СВЕРДЛОВИНИ
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
# КОЛОНКИ РОЗКЛАДУ МОДУЛІВ
# ============================================================

MODULE_SCHEDULE_COLUMNS = [
    "дата та час початку",
    "модуль",
    "дія",
    "тривалість, годин",
    "дата та час завершення",
    "наступний модуль",
    "дата та час запуску наступного модуля",
    "дата та час вимкнення поточного модуля",
    "активність",
    "статус",
    "дата та час фактичного запуску",
    "дата та час фактичного вимкнення",
    "помилка",
]


# ============================================================
# КОЛОНКИ СЛУЖБОВОГО АРКУША ПЕРЕХОДІВ
# ============================================================

TRANSITION_COLUMNS = [
    "поточний модуль",
    "наступний модуль",
    "час завершення",
    "час увімкнення наступного",
    "час вимкнення поточного",
    "стан",
]


# ============================================================
# МОДУЛІ
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


# ============================================================
# НОРМАЛІЗАЦІЯ ТРИВАЛОСТІ
# ============================================================

def parse_duration_hours(value):
    """
    Перетворює значення тривалості на float.

    Підтримує:
        24
        24.0
        24,0
        0.0166667
        0,0166667

    ВАЖЛИВО:
    Ніякого множення на 10 або 100 тут немає.
    """

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)

            if pd.isna(number):
                return None

            return number
        except Exception:
            return None

    text = safe_text(value)

    if not text:
        return None

    text = text.replace("\u00a0", " ")
    text = text.replace(" ", "")
    text = text.replace(",", ".")

    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def format_duration_hours(value):
    """
    Форматування тривалості для Google Sheets.

    Приклади:

        24        -> 24
        24.0      -> 24
        0.0166667 -> 0.0166667
        0.5       -> 0.5
    """

    duration = parse_duration_hours(value)

    if duration is None:
        return ""

    if duration == 0:
        return "0"

    # Максимальна точність 7 знаків після крапки.
    result = f"{duration:.7f}".rstrip("0").rstrip(".")

    return result


def duration_to_seconds(value):
    """
    Перетворює години в секунди.

    Наприклад:

        1 година      = 3600 секунд
        0.5 години    = 1800 секунд
        0.0166667 год = приблизно 60 секунд
    """

    hours = parse_duration_hours(value)

    if hours is None:
        return None

    if hours <= 0:
        return None

    return max(1, int(round(hours * 3600)))


# ============================================================
# DATETIME
# ============================================================

def parse_schedule_datetime(value):
    if value is None:
        return None

    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()

    elif isinstance(value, datetime):
        parsed = value

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
    parsed = parse_schedule_datetime(value)

    if parsed is None:
        return safe_text(value)

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def normalize_datetime_for_storage(value):
    parsed = parse_schedule_datetime(value)

    if parsed is None:
        return ""

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# ДІЇ
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
# АКТИВНІСТЬ
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
# ДНІ
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

    return [
        day
        for day in WEEKDAYS
        if day in text
    ]


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


# ============================================================
# DATAFRAME
# ============================================================

def prepare_dataframe(df, columns):

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
        index=range(len(df))
    )

    for column in columns:

        if column in df.columns:

            result[column] = [
                safe_text(v)
                for v in df[column].tolist()
            ]

        else:

            result[column] = [
                ""
            ] * len(df)

    return result.reset_index(drop=True)


# ============================================================
# СТАРИЙ РОЗКЛАД
# ============================================================

def load_schedule():

    try:

        worksheet = get_schedule_worksheet()

        if worksheet is None:
            return pd.DataFrame(
                {c: [] for c in REQUIRED_SCHEDULE_COLUMNS}
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

            st.error(
                f"❌ Максимальна кількість завдань — "
                f"{MAX_SCHEDULES}."
            )

            return False

        values = [
            REQUIRED_SCHEDULE_COLUMNS.copy()
        ]

        for _, row in clean_df.iterrows():

            values.append([
                safe_text(row[c])
                for c in REQUIRED_SCHEDULE_COLUMNS
            ])

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
# РОЗКЛАД МОДУЛІВ
# ============================================================

def load_module_schedule():

    try:

        worksheet = get_module_schedule_worksheet()

        if worksheet is None:
            return pd.DataFrame(
                {c: [] for c in MODULE_SCHEDULE_COLUMNS}
            )

        records = worksheet.get_all_records()

        if not records:

            return pd.DataFrame(
                {c: [] for c in MODULE_SCHEDULE_COLUMNS}
            )

        raw_df = pd.DataFrame(records)

        # ----------------------------------------------------
        # МІГРАЦІЯ СТАРОЇ СТРУКТУРИ
        # ----------------------------------------------------

        if (
            "дата та час початку" not in raw_df.columns
            and "час" in raw_df.columns
        ):

            migrated = []

            today = datetime.now(
                KYIV_TZ
            ).date()

            for _, old in raw_df.iterrows():

                row = {
                    c: ""
                    for c in MODULE_SCHEDULE_COLUMNS
                }

                old_value = safe_text(
                    old.get("час", "")
                )

                old_dt = parse_schedule_datetime(
                    old_value
                )

                if old_dt:

                    start_dt = datetime.combine(
                        today,
                        old_dt.time(),
                    ).replace(
                        tzinfo=KYIV_TZ
                    )

                    row[
                        "дата та час початку"
                    ] = format_schedule_datetime(
                        start_dt
                    )

                else:

                    row[
                        "дата та час початку"
                    ] = old_value

                row["модуль"] = safe_text(
                    old.get("модуль", "")
                )

                row["дія"] = normalize_action(
                    old.get("дія", "")
                )

                duration = parse_duration_hours(
                    old.get(
                        "тривалість, годин",
                        "",
                    )
                )

                row[
                    "тривалість, годин"
                ] = format_duration_hours(
                    duration
                )

                row[
                    "наступний модуль"
                ] = safe_text(
                    old.get(
                        "наступний модуль",
                        "",
                    )
                )

                row[
                    "активність"
                ] = (
                    safe_text(
                        old.get(
                            "активність",
                            "",
                        )
                    )
                    or "TRUE"
                )

                row["статус"] = (
                    "Заплановано"
                )

                migrated.append(row)

            return pd.DataFrame(
                migrated,
                columns=MODULE_SCHEDULE_COLUMNS,
            )

        result = prepare_dataframe(
            raw_df,
            MODULE_SCHEDULE_COLUMNS,
        )

        # ----------------------------------------------------
        # НОРМАЛІЗУЄМО ТРИВАЛІСТЬ
        # ----------------------------------------------------

        if not result.empty:

            result[
                "тривалість, годин"
            ] = [
                format_duration_hours(
                    parse_duration_hours(value)
                )
                for value in result[
                    "тривалість, годин"
                ]
            ]

        return result

    except Exception as e:

        st.error(
            "❌ Помилка завантаження "
            "розкладу модулів."
        )

        st.code(str(e))

        return pd.DataFrame(
            {c: [] for c in MODULE_SCHEDULE_COLUMNS}
        )


# ============================================================
# ЗБЕРЕЖЕННЯ РОЗКЛАДУ МОДУЛІВ
# ============================================================

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

            st.error(
                f"❌ Максимальна кількість завдань — "
                f"{MAX_SCHEDULES}."
            )

            return False

        values = [
            MODULE_SCHEDULE_COLUMNS.copy()
        ]

        for _, row in clean_df.iterrows():

            duration = parse_duration_hours(
                row.get(
                    "тривалість, годин",
                    "",
                )
            )

            values.append([
                normalize_datetime_for_storage(
                    row.get(
                        "дата та час початку",
                        "",
                    )
                ),

                safe_text(
                    row.get("модуль", "")
                ),

                normalize_action(
                    row.get("дія", "")
                ),

                format_duration_hours(
                    duration
                ),

                normalize_datetime_for_storage(
                    row.get(
                        "дата та час завершення",
                        "",
                    )
                ),

                safe_text(
                    row.get(
                        "наступний модуль",
                        "",
                    )
                ),

                normalize_datetime_for_storage(
                    row.get(
                        "дата та час запуску наступного модуля",
                        "",
                    )
                ),

                normalize_datetime_for_storage(
                    row.get(
                        "дата та час вимкнення поточного модуля",
                        "",
                    )
                ),

                (
                    "TRUE"
                    if normalize_activity(
                        row.get(
                            "активність",
                            "",
                        )
                    )
                    else "FALSE"
                ),

                safe_text(
                    row.get("статус", "")
                ),

                normalize_datetime_for_storage(
                    row.get(
                        "дата та час фактичного запуску",
                        "",
                    )
                ),

                normalize_datetime_for_storage(
                    row.get(
                        "дата та час фактичного вимкнення",
                        "",
                    )
                ),

                safe_text(
                    row.get("помилка", "")
                ),
            ])

        # ----------------------------------------------------
        # ОЧИЩЕННЯ І ЗАПИС
        # ----------------------------------------------------

        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=values,
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
        isinstance(response, dict)
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

        if switch_code.startswith(
            "switch_"
        ):

            countdown_code = (
                switch_code.replace(
                    "switch_",
                    "countdown_",
                )
            )

        else:

            countdown_code = "countdown"

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
        isinstance(response, dict)
        and bool(
            response.get(
                "success",
                False,
            )
        )
    )


def get_relay_state_by_module(
    module_name,
):

    config = MODULE_CONFIG.get(
        module_name
    )

    if not config:
        return None

    device_id = TUYA_SETTINGS.get(
        config["device_id_key"],
        "",
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

    device_id = TUYA_SETTINGS.get(
        config["device_id_key"],
        "",
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
# РОЗРАХУНОК НАСТУПНОГО МОДУЛЯ
# ============================================================

def get_next_module_schedule_values(
    df,
):

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

            False,
        )

    previous = df.iloc[-1]

    previous_start = parse_schedule_datetime(
        previous.get(
            "дата та час початку",
            "",
        )
    )

    previous_finish = parse_schedule_datetime(
        previous.get(
            "дата та час завершення",
            "",
        )
    )

    if previous_finish is not None:

        start_dt = previous_finish

    elif previous_start is not None:

        duration_seconds = duration_to_seconds(
            previous.get(
                "тривалість, годин",
                "0",
            )
        )

        if duration_seconds is None:
            duration_seconds = 0

        start_dt = (
            previous_start
            + timedelta(
                seconds=duration_seconds
            )
        )

    else:

        start_dt = datetime.now(
            KYIV_TZ
        ).replace(
            second=0,
            microsecond=0,
        )

    next_module = safe_text(
        previous.get(
            "наступний модуль",
            "",
        )
    )

    if next_module not in MODULE_CONFIG:

        next_module = list(
            MODULE_CONFIG.keys()
        )[0]

    return (
        start_dt,
        next_module,
        True,
    )


# ============================================================
# РОЗРАХУНОК ЧАСІВ
# ============================================================

def calculate_schedule_times(
    start_dt,
    duration_hours,
    next_module,
):

    start_dt = parse_schedule_datetime(
        start_dt
    )

    if start_dt is None:
        return (
            None,
            None,
            None,
        )

    duration_seconds = duration_to_seconds(
        duration_hours
    )

    if duration_seconds is None:
        return (
            None,
            None,
            None,
        )

    finish_dt = (
        start_dt
        + timedelta(
            seconds=duration_seconds
        )
    )

    if next_module == "Не виключати":

        return (
            finish_dt,
            None,
            None,
        )

    # --------------------------------------------------------
    # Наступний модуль запускаємо за 3 хвилини
    # до завершення поточного.
    #
    # Для короткого тесту, наприклад 1 хвилина,
    # не допускаємо від'ємного часу.
    # --------------------------------------------------------

    overlap_seconds = min(
        180,
        duration_seconds,
    )

    next_start_dt = (
        finish_dt
        - timedelta(
            seconds=overlap_seconds
        )
    )

    current_off_dt = finish_dt

    return (
        finish_dt,
        next_start_dt,
        current_off_dt,
    )


# ============================================================
# ДОДАВАННЯ МОДУЛЯ
# ============================================================

def add_module_schedule_task(
    start_datetime,
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

        return (
            False,
            f"Досягнуто максимуму "
            f"{MAX_SCHEDULES} завдань.",
        )

    duration = parse_duration_hours(
        duration_hours
    )

    if duration is None:

        return (
            False,
            "Некоректна тривалість.",
        )

    if duration <= 0:

        return (
            False,
            "Тривалість повинна бути "
            "більшою за 0.",
        )

    finish_dt, next_start_dt, current_off_dt = (
        calculate_schedule_times(
            start_datetime,
            duration,
            next_module,
        )
    )

    if finish_dt is None:

        return (
            False,
            "Некоректна дата та час "
            "початку або тривалість.",
        )

    new_row = {
        c: ""
        for c in MODULE_SCHEDULE_COLUMNS
    }

    new_row.update({

        "дата та час початку":
            format_schedule_datetime(
                start_datetime
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
            format_duration_hours(
                duration
            ),

        "дата та час завершення":
            format_schedule_datetime(
                finish_dt
            ),

        "наступний модуль":
            safe_text(
                next_module
            ),

        "дата та час запуску наступного модуля":
            (
                format_schedule_datetime(
                    next_start_dt
                )
                if next_start_dt
                else ""
            ),

        "дата та час вимкнення поточного модуля":
            (
                format_schedule_datetime(
                    current_off_dt
                )
                if current_off_dt
                else ""
            ),

        "активність":
            "TRUE",

        "статус":
            "Заплановано",

        "дата та час фактичного запуску":
            "",

        "дата та час фактичного вимкнення":
            "",

        "помилка":
            "",
    })

    rows = df.to_dict(
        orient="records"
    )

    rows.append(
        new_row
    )

    success = save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )

    if success:

        return (
            True,
            "Розклад модуля "
            "успішно додано.",
        )

    return (
        False,
        "Не вдалося зберегти "
        "розклад модуля.",
    )


# ============================================================
# ВИДАЛЕННЯ
# ============================================================

def delete_module_schedule_task(
    index,
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < 0 or index >= len(df):
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
# АКТИВНІСТЬ
# ============================================================

def change_module_activity(
    index,
    active,
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < 0 or index >= len(df):
        return False

    rows = df.to_dict(
        orient="records"
    )

    rows[index][
        "активність"
    ] = (
        "TRUE"
        if active
        else "FALSE"
    )

    if active:

        rows[index][
            "статус"
        ] = "Заплановано"

        rows[index][
            "помилка"
        ] = ""

    else:

        rows[index][
            "статус"
        ] = "Призупинено"

    return save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )


# ============================================================
# РЕДАГУВАННЯ
# ============================================================

def update_module_schedule_task(
    index,
    start_datetime,
    module_name,
    action,
    duration_hours,
    next_module,
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < 0 or index >= len(df):
        return False

    duration = parse_duration_hours(
        duration_hours
    )

    if duration is None or duration <= 0:
        return False

    finish_dt, next_start_dt, current_off_dt = (
        calculate_schedule_times(
            start_datetime,
            duration,
            next_module,
        )
    )

    if finish_dt is None:
        return False

    old = df.iloc[index]

    row = {
        c: safe_text(
            old.get(c, "")
        )
        for c in MODULE_SCHEDULE_COLUMNS
    }

    row.update({

        "дата та час початку":
            format_schedule_datetime(
                start_datetime
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
            format_duration_hours(
                duration
            ),

        "дата та час завершення":
            format_schedule_datetime(
                finish_dt
            ),

        "наступний модуль":
            safe_text(
                next_module
            ),

        "дата та час запуску наступного модуля":
            (
                format_schedule_datetime(
                    next_start_dt
                )
                if next_start_dt
                else ""
            ),

        "дата та час вимкнення поточного модуля":
            (
                format_schedule_datetime(
                    current_off_dt
                )
                if current_off_dt
                else ""
            ),

        "статус":
            "Заплановано",

        "дата та час фактичного запуску":
            "",

        "дата та час фактичного вимкнення":
            "",

        "помилка":
            "",
    })

    rows = df.to_dict(
        orient="records"
    )

    rows[index] = row

    return save_module_schedule(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )


# ============================================================
# ВИКОНАННЯ МОДУЛЯ
# ============================================================

def execute_module_schedule_task(
    index,
    row,
    now,
):

    if not normalize_activity(
        row.get(
            "активність",
            "",
        )
    ):
        return (
            False,
            "Запис неактивний.",
        )

    start_dt = parse_schedule_datetime(
        row.get(
            "дата та час початку",
            "",
        )
    )

    if start_dt is None:

        return (
            False,
            "Некоректна дата та час "
            "початку.",
        )

    now = (
        now.astimezone(KYIV_TZ)
        if now.tzinfo
        else now.replace(
            tzinfo=KYIV_TZ
        )
    )

    # --------------------------------------------------------
    # Вікно запуску — 60 секунд.
    # --------------------------------------------------------

    if now < start_dt:

        return (
            False,
            "Ще не настав час запуску.",
        )

    if now >= (
        start_dt
        + timedelta(
            seconds=60
        )
    ):

        return (
            False,
            "Вікно запуску пропущено.",
        )

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
            "Запис уже обробляється "
            "або виконаний.",
        )

    module_name = safe_text(
        row.get(
            "модуль",
            "",
        )
    )

    action = normalize_action(
        row.get(
            "дія",
            "",
        )
    )

    duration_hours = parse_duration_hours(
        row.get(
            "тривалість, годин",
            "",
        )
    )

    if duration_hours is None:

        return (
            False,
            "Некоректна тривалість.",
        )

    if duration_hours <= 0:

        return (
            False,
            "Тривалість повинна бути "
            "більшою за 0.",
        )

    if module_name not in MODULE_CONFIG:

        return (
            False,
            f"Невідомий модуль "
            f"«{module_name}».",
        )

    if action != "Увімкнути":

        return (
            False,
            "Для модульного ланцюжка "
            "дія повинна бути "
            "«Увімкнути».",
        )

    duration_seconds = duration_to_seconds(
        duration_hours
    )

    if duration_seconds is None:

        return (
            False,
            "Не вдалося визначити "
            "тривалість у секундах.",
        )

    success = set_module_state(
        module_name,
        True,
        duration_seconds,
    )

    if not success:

        return (
            False,
            f"Tuya не прийняла команду "
            f"для {module_name}.",
        )

    fresh_df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    if index < len(fresh_df):

        rows = fresh_df.to_dict(
            orient="records"
        )

        rows[index][
            "статус"
        ] = "Виконується"

        rows[index][
            "дата та час фактичного запуску"
        ] = format_schedule_datetime(
            now
        )

        rows[index][
            "помилка"
        ] = ""

        save_module_schedule(
            pd.DataFrame(
                rows,
                columns=MODULE_SCHEDULE_COLUMNS,
            )
        )

    schedule_transition(
        module_name,
        safe_text(
            row.get(
                "наступний модуль",
                "",
            )
        ),
        now,
        duration_seconds,
    )

    return (
        True,
        f"🟢 {module_name} "
        f"увімкнено на "
        f"{duration_hours:g} год.",
    )


# ============================================================
# ПЕРЕХОДИ
# ============================================================

def ensure_transition_columns():

    spreadsheet = init_google_sheets()

    if spreadsheet is None:
        return None

    try:

        worksheet = spreadsheet.worksheet(
            TRANSITION_WORKSHEET_NAME
        )

        # ----------------------------------------------------
        # Перевіряємо заголовки.
        # ----------------------------------------------------

        try:

            headers = worksheet.row_values(
                1
            )

        except Exception:

            headers = []

        if headers != TRANSITION_COLUMNS:

            worksheet.update(
                range_name="A1",
                values=[
                    TRANSITION_COLUMNS
                ],
            )

        return worksheet

    except gspread.WorksheetNotFound:

        try:

            worksheet = spreadsheet.add_worksheet(
                title=TRANSITION_WORKSHEET_NAME,
                rows=100,
                cols=len(
                    TRANSITION_COLUMNS
                ),
            )

            worksheet.update(
                range_name="A1",
                values=[
                    TRANSITION_COLUMNS
                ],
            )

            return worksheet

        except Exception as e:

            logging.error(
                "Помилка створення "
                "аркуша переходів: %s",
                e,
            )

            return None

    except Exception as e:

        logging.error(
            "Помилка відкриття "
            "аркуша переходів: %s",
            e,
        )

        return None


# ============================================================
# ЗАВАНТАЖЕННЯ ПЕРЕХОДІВ
# ============================================================

def load_transitions():

    worksheet = ensure_transition_columns()

    if worksheet is None:

        return pd.DataFrame(
            {c: [] for c in TRANSITION_COLUMNS}
        )

    try:

        records = worksheet.get_all_records()

        if not records:

            return pd.DataFrame(
                {c: [] for c in TRANSITION_COLUMNS}
            )

        return prepare_dataframe(
            pd.DataFrame(records),
            TRANSITION_COLUMNS,
        )

    except Exception as e:

        logging.error(
            "Помилка завантаження "
            "переходів: %s",
            e,
        )

        return pd.DataFrame(
            {c: [] for c in TRANSITION_COLUMNS}
        )


# ============================================================
# ЗБЕРЕЖЕННЯ ПЕРЕХОДІВ
# ============================================================

def save_transitions(df):

    worksheet = ensure_transition_columns()

    if worksheet is None:
        return False

    clean_df = prepare_dataframe(
        df,
        TRANSITION_COLUMNS,
    )

    values = [
        TRANSITION_COLUMNS.copy()
    ]

    for _, row in clean_df.iterrows():

        values.append([

            safe_text(
                row.get(
                    "поточний модуль",
                    "",
                )
            ),

            safe_text(
                row.get(
                    "наступний модуль",
                    "",
                )
            ),

            normalize_datetime_for_storage(
                row.get(
                    "час завершення",
                    "",
                )
            ),

            normalize_datetime_for_storage(
                row.get(
                    "час увімкнення наступного",
                    "",
                )
            ),

            normalize_datetime_for_storage(
                row.get(
                    "час вимкнення поточного",
                    "",
                )
            ),

            safe_text(
                row.get(
                    "стан",
                    "",
                )
            ),
        ])

    try:

        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=values,
        )

        return True

    except Exception as e:

        logging.error(
            "Помилка збереження "
            "переходів: %s",
            e,
        )

        return False


# ============================================================
# СТВОРЕННЯ ПЕРЕХОДУ
# ============================================================

def schedule_transition(
    module_name,
    next_module,
    start_time,
    duration_seconds,
):

    start_time = (
        start_time.astimezone(
            KYIV_TZ
        )
    )

    finish = (
        start_time
        + timedelta(
            seconds=duration_seconds
        )
    )

    if next_module == "Не виключати":

        next_start = None
        current_off = None

    else:

        overlap_seconds = min(
            180,
            duration_seconds,
        )

        next_start = (
            finish
            - timedelta(
                seconds=overlap_seconds
            )
        )

        current_off = finish

    df = load_transitions()

    row = {

        "поточний модуль":
            module_name,

        "наступний модуль":
            next_module,

        "час завершення":
            format_schedule_datetime(
                finish
            ),

        "час увімкнення наступного":
            (
                format_schedule_datetime(
                    next_start
                )
                if next_start
                else ""
            ),

        "час вимкнення поточного":
            (
                format_schedule_datetime(
                    current_off
                )
                if current_off
                else ""
            ),

        "стан":
            "Заплановано",
    }

    rows = df.to_dict(
        orient="records"
    )

    rows.append(row)

    save_transitions(
        pd.DataFrame(
            rows,
            columns=TRANSITION_COLUMNS,
        )
    )


# ============================================================
# ОНОВЛЕННЯ ФАКТИЧНИХ ДАНИХ
# ============================================================

def update_module_execution_columns(
    module_name,
    actual_on=None,
    actual_off=None,
    status=None,
    error="",
):

    df = prepare_dataframe(
        load_module_schedule(),
        MODULE_SCHEDULE_COLUMNS,
    )

    changed = False

    for i, row in df.iterrows():

        if safe_text(
            row.get(
                "модуль",
                "",
            )
        ) != module_name:
            continue

        if status is not None:

            df.at[
                i,
                "статус"
            ] = status

        if actual_on is not None:

            df.at[
                i,
                "дата та час фактичного запуску"
            ] = format_schedule_datetime(
                actual_on
            )

        if actual_off is not None:

            df.at[
                i,
                "дата та час фактичного вимкнення"
            ] = format_schedule_datetime(
                actual_off
            )

        df.at[
            i,
            "помилка"
        ] = error

        changed = True

        break

    if changed:

        save_module_schedule(
            df
        )


# ============================================================
# ВИКОНАННЯ ВІДКЛАДЕНИХ ПЕРЕХОДІВ
# ============================================================

def execute_pending_transitions():

    now = datetime.now(
        KYIV_TZ
    )

    df = load_transitions()

    if df.empty:
        return []

    rows = df.to_dict(
        orient="records"
    )

    changed = False
    results = []

    for row in rows:

        state = safe_text(
            row.get(
                "стан",
                "",
            )
        )

        if state == "Виконано":
            continue

        current_module = safe_text(
            row.get(
                "поточний модуль",
                "",
            )
        )

        next_module = safe_text(
            row.get(
                "наступний модуль",
                "",
            )
        )

        finish_dt = parse_schedule_datetime(
            row.get(
                "час завершення",
                "",
            )
        )

        if finish_dt is None:
            continue

        # ----------------------------------------------------
        # НЕ ВИКЛЮЧАТИ
        # ----------------------------------------------------

        if next_module == "Не виключати":

            if now >= finish_dt:

                row[
                    "стан"
                ] = "Виконано"

                changed = True

                update_module_execution_columns(
                    current_module,
                    status="Виконано",
                )

            continue

        next_start_dt = parse_schedule_datetime(
            row.get(
                "час увімкнення наступного",
                "",
            )
        )

        if next_start_dt is None:
            continue

        # ----------------------------------------------------
        # 1. ВМИКАЄМО НАСТУПНИЙ МОДУЛЬ
        # ----------------------------------------------------

        if (
            now >= next_start_dt
            and state == "Заплановано"
        ):

            duration_seconds = max(
                1,
                int(
                    (
                        finish_dt
                        - next_start_dt
                    ).total_seconds()
                ),
            )

            success = set_module_state(
                next_module,
                True,
                duration_seconds,
            )

            if success:

                row[
                    "стан"
                ] = "Наступний увімкнено"

                changed = True

                update_module_execution_columns(
                    next_module,
                    actual_on=now,
                    status="Виконується",
                )

                results.append(
                    f"🟢 {next_module} "
                    f"увімкнено."
                )

            else:

                row[
                    "стан"
                ] = "Помилка"

                changed = True

                update_module_execution_columns(
                    next_module,
                    status="Помилка",
                    error=(
                        "Tuya не прийняла "
                        "команду запуску."
                    ),
                )

                results.append(
                    f"❌ Не вдалося "
                    f"увімкнути "
                    f"{next_module}."
                )

        # ----------------------------------------------------
        # 2. ВИМИКАЄМО ПОТОЧНИЙ МОДУЛЬ
        # ----------------------------------------------------

        if (
            now >= finish_dt
            and row.get("стан")
            == "Наступний увімкнено"
        ):

            success = set_module_state(
                current_module,
                False,
            )

            if success:

                row[
                    "стан"
                ] = "Виконано"

                changed = True

                update_module_execution_columns(
                    current_module,
                    actual_off=now,
                    status="Виконано",
                )

                results.append(
                    f"🔴 {current_module} "
                    f"вимкнено."
                )

            else:

                row[
                    "стан"
                ] = "Помилка вимкнення"

                changed = True

                update_module_execution_columns(
                    current_module,
                    status="Помилка",
                    error=(
                        "Tuya не прийняла "
                        "команду вимкнення."
                    ),
                )

                results.append(
                    f"❌ Не вдалося "
                    f"вимкнути "
                    f"{current_module}."
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
# ОСНОВНИЙ ПЛАНУВАЛЬНИК
# ============================================================

def run_module_scheduler():

    results = []

    # Спочатку переходи.
    results.extend(
        execute_pending_transitions()
    )

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

        start_dt = parse_schedule_datetime(
            row.get(
                "дата та час початку",
                "",
            )
        )

        if start_dt is None:
            continue

        if now < start_dt:
            continue

        if now >= (
            start_dt
            + timedelta(
                seconds=60
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


# ============================================================
# FRAGMENT ПЛАНУВАЛЬНИКА
# ============================================================

@st.fragment(
    run_every=SCHEDULER_INTERVAL_SECONDS
)
def scheduler_fragment():

    results = run_module_scheduler()

    for message in results:

        st.success(
            f"⏱️ Планувальник: "
            f"{message}"
        )


# ============================================================
# ЗАПУСК ПЛАНУВАЛЬНИКА
# ============================================================

scheduler_fragment()


# ============================================================
# ІНТЕРФЕЙС
# ============================================================

st.title(
    "💧 Керування зрошенням"
)


if TUYA_CONNECTED:

    st.success(
        "🟢 Система керування "
        "підключена до Tuya Cloud"
    )

else:

    st.error(
        "🔴 Немає зв'язку "
        "з Tuya Cloud"
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
                else
                "🔴 Автомат вимкнено."
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
    "Дата та час першого запуску задаються "
    "користувачем. Для наступних модулів "
    "дата/час і модуль автоматично беруться "
    "з попереднього запису."
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

    (
        default_time,
        default_module,
        has_previous,
    ) = get_next_module_schedule_values(
        module_df
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
                    "Це перший запис. "
                    "Виберіть дату та час "
                    "старту і модуль."
                )

                first_col1, first_col2 = (
                    st.columns(2)
                )

                with first_col1:

                    module_time = (
                        st.datetime_input(
                            "Дата та час старту",
                            value=datetime.now(
                                KYIV_TZ
                            ).replace(
                                second=0,
                                microsecond=0,
                            ),
                        )
                    )

                with first_col2:

                    module_name = (
                        st.selectbox(
                            "Модуль",
                            list(
                                MODULE_CONFIG.keys()
                            ),
                        )
                    )

            else:

                module_time = default_time
                module_name = default_module

                st.info(
                    f"Автоматично: старт "
                    f"**{format_schedule_datetime(module_time)}**, "
                    f"модуль **{module_name}**."
                )

            action = "Увімкнути"

            # ------------------------------------------------
            # ВАЖЛИВО:
            #
            # 1 хвилина = 0.0166667 години.
            #
            # max_value залишаємо великим,
            # щоб старі записи >24 год не ламали форму.
            # ------------------------------------------------

            duration_hours = st.number_input(
                "Тривалість, годин",

                min_value=0.000001,

                max_value=168.0,

                value=1.0,

                step=0.0166667,

                format="%.7f",

                help=(
                    "1 хвилина = 0,0166667 години. "
                    "Наприклад, для тесту на 1 хвилину "
                    "введіть 0,0166667."
                ),
            )

            st.caption(
                f"⏱️ Приблизно "
                f"{duration_hours * 60:.2f} хвилин"
            )

            next_module = st.selectbox(
                "Наступний модуль",

                NEXT_MODULE_OPTIONS,

                index=0,

                help=(
                    "«Не виключати» означає: "
                    "після завершення заданої "
                    "тривалості поточний модуль "
                    "НЕ вимикається і наступний "
                    "модуль НЕ вмикається."
                ),
            )

            st.caption(
                "Активність задається "
                "автоматично."
            )

            submitted = st.form_submit_button(
                "💾 Додати модуль",
                use_container_width=True,
                type="primary",
            )

            if submitted:

                result, message = (
                    add_module_schedule_task(
                        start_datetime=module_time,
                        module_name=module_name,
                        action=action,
                        duration_hours=duration_hours,
                        next_module=next_module,
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


# ============================================================
# СПИСОК РОЗКЛАДУ
# ============================================================

st.markdown("---")

st.subheader(
    "📋 Ланцюжок модулів"
)


if module_df.empty:

    st.info(
        "Модульний розклад "
        "поки порожній."
    )

else:

    for index, row in module_df.iterrows():

        module_name = safe_text(
            row.get(
                "модуль",
                "",
            )
        )

        schedule_time = (
            format_schedule_datetime(
                row.get(
                    "дата та час початку",
                    "",
                )
            )
        )

        duration_value = (
            parse_duration_hours(
                row.get(
                    "тривалість, годин",
                    "",
                )
            )
        )

        duration = (
            format_duration_hours(
                duration_value
            )
            if duration_value is not None
            else ""
        )

        next_module = safe_text(
            row.get(
                "наступний модуль",
                "",
            )
        )

        activity = normalize_activity(
            row.get(
                "активність",
                "",
            )
        )

        last_execution = safe_text(
            row.get(
                "дата та час фактичного запуску",
                "",
            )
        )

        with st.container(
            border=True
        ):

            c1, c2, c3, c4, c5 = (
                st.columns(
                    [
                        0.4,
                        1.3,
                        1.0,
                        1.3,
                        1.3,
                    ]
                )
            )

            with c1:

                st.markdown(
                    f"### {index + 1}"
                )

            with c2:

                st.markdown(
                    f"**{module_name}**"
                )

                st.caption(
                    f"Старт: "
                    f"{schedule_time}"
                )

            with c3:

                st.markdown(
                    f"**{duration} год**"
                )

                st.caption(
                    "Тривалість"
                )

            with c4:

                st.markdown(
                    "**Наступний:**"
                )

                st.caption(
                    next_module or "—"
                )

            with c5:

                if activity:

                    st.success(
                        "🟢 Активний"
                    )

                else:

                    st.warning(
                        "⏸️ Неактивний"
                    )

            finish_display = safe_text(
                row.get(
                    "дата та час завершення",
                    "",
                )
            )

            status_display = safe_text(
                row.get(
                    "статус",
                    "",
                )
            )

            actual_off_display = safe_text(
                row.get(
                    "дата та час фактичного вимкнення",
                    "",
                )
            )

            error_display = safe_text(
                row.get(
                    "помилка",
                    "",
                )
            )

            if finish_display:

                st.caption(
                    f"Планове завершення: "
                    f"{finish_display}"
                )

            if status_display:

                st.caption(
                    f"Статус: "
                    f"{status_display}"
                )

            if last_execution:

                st.caption(
                    f"Фактичний запуск: "
                    f"{last_execution}"
                )

            if actual_off_display:

                st.caption(
                    f"Фактичне вимкнення: "
                    f"{actual_off_display}"
                )

            if error_display:

                st.error(
                    f"Помилка: "
                    f"{error_display}"
                )

            b1, b2, b3 = st.columns(3)

            with b1:

                if activity:

                    if st.button(
                        "⏸️ Вимкнути",
                        key=(
                            f"module_disable_"
                            f"{index}"
                        ),
                        use_container_width=True,
                    ):

                        if change_module_activity(
                            index,
                            False,
                        ):

                            st.rerun()

                else:

                    if st.button(
                        "▶️ Увімкнути",
                        key=(
                            f"module_enable_"
                            f"{index}"
                        ),
                        use_container_width=True,
                    ):

                        if change_module_activity(
                            index,
                            True,
                        ):

                            st.rerun()

            with b2:

                if st.button(
                    "✏️ Редагувати",
                    key=(
                        f"module_edit_"
                        f"{index}"
                    ),
                    use_container_width=True,
                ):

                    st.session_state[
                        f"editing_module_{index}"
                    ] = True

                    st.rerun()

            with b3:

                if st.button(
                    "🗑️ Видалити",
                    key=(
                        f"module_delete_"
                        f"{index}"
                    ),
                    use_container_width=True,
                ):

                    if delete_module_schedule_task(
                        index
                    ):

                        st.rerun()

            # =================================================
            # РЕДАГУВАННЯ
            # =================================================

            if st.session_state.get(
                f"editing_module_{index}",
                False,
            ):

                st.markdown(
                    "#### ✏️ Редагування"
                )

                parsed_datetime = (
                    parse_schedule_datetime(
                        row.get(
                            "дата та час початку",
                            "",
                        )
                    )
                    or datetime.now(
                        KYIV_TZ
                    ).replace(
                        second=0,
                        microsecond=0,
                    )
                )

                current_module = (
                    module_name
                    if module_name
                    in MODULE_CONFIG
                    else list(
                        MODULE_CONFIG.keys()
                    )[0]
                )

                current_next = (
                    next_module
                    if next_module
                    in NEXT_MODULE_OPTIONS
                    else "Не виключати"
                )

                current_duration = (
                    parse_duration_hours(
                        row.get(
                            "тривалість, годин",
                            "",
                        )
                    )
                )

                if (
                    current_duration is None
                    or current_duration <= 0
                ):

                    current_duration = 1.0

                # ------------------------------------------------
                # Streamlit number_input не отримує значення
                # більше max_value.
                #
                # Але саму таблицю ми не обрізаємо.
                # ------------------------------------------------

                edit_duration_value = min(
                    max(
                        current_duration,
                        0.000001,
                    ),
                    168.0,
                )

                if current_duration > 168.0:

                    st.warning(
                        f"У таблиці збережено "
                        f"{current_duration:g} год. "
                        f"Для редагування поле "
                        f"обмежене 168 год."
                    )

                with st.form(
                    key=(
                        f"edit_module_form_"
                        f"{index}"
                    ),
                ):

                    edit_time = (
                        st.datetime_input(
                            "Дата та час",
                            value=parsed_datetime,
                        )
                    )

                    edit_module = (
                        st.selectbox(
                            "Модуль",

                            list(
                                MODULE_CONFIG.keys()
                            ),

                            index=list(
                                MODULE_CONFIG.keys()
                            ).index(
                                current_module
                            ),
                        )
                    )

                    st.info(
                        "Дія автоматично: "
                        "Увімкнути"
                    )

                    edit_duration = (
                        st.number_input(
                            "Тривалість, годин",

                            min_value=0.000001,

                            max_value=168.0,

                            value=edit_duration_value,

                            step=0.0166667,

                            format="%.7f",

                            help=(
                                "1 хвилина = "
                                "0,0166667 години."
                            ),
                        )
                    )

                    st.caption(
                        f"⏱️ Приблизно "
                        f"{edit_duration * 60:.2f} хвилин"
                    )

                    edit_next = (
                        st.selectbox(
                            "Наступний модуль",

                            NEXT_MODULE_OPTIONS,

                            index=(
                                NEXT_MODULE_OPTIONS.index(
                                    current_next
                                )
                            ),
                        )
                    )

                    ec1, ec2 = (
                        st.columns(2)
                    )

                    with ec1:

                        save_edit = (
                            st.form_submit_button(
                                "💾 Зберегти",
                                use_container_width=True,
                                type="primary",
                            )
                        )

                    with ec2:

                        cancel_edit = (
                            st.form_submit_button(
                                "❌ Скасувати",
                                use_container_width=True,
                            )
                        )

                    if save_edit:

                        success = (
                            update_module_schedule_task(
                                index=index,
                                start_datetime=edit_time,
                                module_name=edit_module,
                                action="Увімкнути",
                                duration_hours=edit_duration,
                                next_module=edit_next,
                            )
                        )

                        if success:

                            st.session_state[
                                f"editing_module_{index}"
                            ] = False

                            st.rerun()

                        else:

                            st.error(
                                "❌ Не вдалося "
                                "оновити модуль."
                            )

                    if cancel_edit:

                        st.session_state[
                            f"editing_module_{index}"
                        ] = False

                        st.rerun()


# ============================================================
# ПОТОЧНІ СТАНИ МОДУЛІВ
# ============================================================

st.markdown("---")

st.subheader(
    "🎛️ Керування модулями"
)


for module_name, config in MODULE_CONFIG.items():

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

            key=(
                f"module_manual_toggle_"
                f"{module_name}"
            ),
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
                        else
                        "🔴 Вимкнено"
                    )
                    + f" {module_name}."
                )

                time.sleep(
                    0.4
                )

                st.rerun()

            else:

                st.error(
                    f"❌ Не вдалося "
                    f"змінити стан "
                    f"{module_name}."
                )


# ============================================================
# СТАН ПЕРЕХОДІВ
# ============================================================

st.markdown("---")

st.subheader(
    "🔄 Заплановані переходи"
)


transitions_df = load_transitions()


if transitions_df.empty:

    st.info(
        "Активних переходів немає."
    )

else:

    active_transitions = (
        transitions_df[
            transitions_df["стан"]
            != "Виконано"
        ]
    )

    if active_transitions.empty:

        st.info(
            "Активних переходів немає."
        )

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
```
