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
# СТРУКТУРА АРКУША "РОЗКЛАД МОДУЛІВ"
# ============================================================

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
# НАСТУПНИЙ МОДУЛЬ
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
# КОНФІГУРАЦІЯ TUYA
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
    Безпечне перетворення значення у текст.

    ВАЖЛИВО:
    Ця функція використовується тільки там, де потрібен текст.
    Для тривалості використовується parse_duration().
    """

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip()


def parse_duration(value):
    """
    Перетворює тривалість у справжнє число float.

    Підтримує:
        1
        1.0
        1,0
        1.05
        1,05
        100,05

    ВАЖЛИВО:
    Ніколи не перетворює 1,0 у 10.
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        try:
            result = float(value)
            if result >= 0:
                return result
            return None
        except Exception:
            return None

    text = str(value).strip()

    if not text:
        return None

    # Прибираємо пробіли.
    text = text.replace(" ", "")

    # Український/європейський запис:
    # 1,05 -> 1.05
    text = text.replace(",", ".")

    try:
        result = float(text)

        if result < 0:
            return None

        return result

    except Exception:
        return None


def format_duration(value):
    """
    Формат для відображення.

    1      -> 1,0
    1.05   -> 1,05
    1.5    -> 1,5
    """

    number = parse_duration(value)

    if number is None:
        return ""

    text = f"{number:.2f}".rstrip("0").rstrip(".")

    if "." not in text:
        text += ".0"

    return text.replace(".", ",")


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

    if isinstance(value, int):
        return value == 1

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
# ПІДГОТОВКА DATAFRAME
# ============================================================

def prepare_module_dataframe(df):
    """
    КРИТИЧНО ВАЖЛИВА ФУНКЦІЯ.

    Не перетворює всю таблицю у string.

    Особливо:
        "тривалість, годин" -> float
        "активність" -> bool

    Саме це виправляє проблему:
        TypeError string_arrow
        1,0 -> 10
        1,05 -> 100,5
    """

    if df is None:
        result = pd.DataFrame(
            columns=MODULE_SCHEDULE_COLUMNS
        )

    else:
        try:

            if df.empty:

                result = pd.DataFrame(
                    columns=MODULE_SCHEDULE_COLUMNS
                )

            else:

                result = df.copy()

        except Exception:

            result = pd.DataFrame(
                columns=MODULE_SCHEDULE_COLUMNS
            )

    # Додаємо відсутні колонки.
    for column in MODULE_SCHEDULE_COLUMNS:

        if column not in result.columns:

            if column == "тривалість, годин":
                result[column] = pd.Series(
                    [None] * len(result),
                    dtype="object",
                )

            elif column == "активність":
                result[column] = pd.Series(
                    [True] * len(result),
                    dtype="object",
                )

            else:
                result[column] = pd.Series(
                    [""] * len(result),
                    dtype="object",
                )

    # Залишаємо тільки 10 погоджених колонок.
    result = result[
        MODULE_SCHEDULE_COLUMNS
    ].copy()

    # ВАЖЛИВО:
    # всі колонки object, а не Arrow string.
    for column in MODULE_SCHEDULE_COLUMNS:

        if column not in [
            "тривалість, годин",
            "активність",
        ]:

            result[column] = result[column].astype(
                object
            )

    # ТРИВАЛІСТЬ — ТІЛЬКИ ЧИСЛО.
    duration_values = []

    for value in result[
        "тривалість, годин"
    ].tolist():

        duration_values.append(
            parse_duration(value)
        )

    result[
        "тривалість, годин"
    ] = pd.Series(
        duration_values,
        dtype="object",
    )

    # АКТИВНІСТЬ — BOOLEAN.
    activity_values = []

    for value in result["активність"].tolist():

        activity_values.append(
            normalize_activity(value)
        )

    result["активність"] = pd.Series(
        activity_values,
        dtype="object",
    )

    # Нормалізуємо дію.
    result["дія"] = [
        normalize_action(value)
        for value in result["дія"].tolist()
    ]

    return result.reset_index(drop=True)


def prepare_dataframe(df, columns):
    """
    Загальна функція для старого розкладу свердловини.
    """

    if df is None:

        return pd.DataFrame(
            columns=columns
        )

    try:

        if df.empty:

            return pd.DataFrame(
                columns=columns
            )

    except Exception:

        return pd.DataFrame(
            columns=columns
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
# СТАРИЙ РОЗКЛАД СВЕРДЛОВИНИ
# ============================================================

def load_schedule():

    try:

        worksheet = get_schedule_worksheet()

        if worksheet is None:

            return pd.DataFrame(
                columns=REQUIRED_SCHEDULE_COLUMNS
            )

        records = worksheet.get_all_records()

        if not records:

            return pd.DataFrame(
                columns=REQUIRED_SCHEDULE_COLUMNS
            )

        return prepare_dataframe(
            pd.DataFrame(records),
            REQUIRED_SCHEDULE_COLUMNS,
        )

    except Exception as e:

        st.error(
            "❌ Помилка завантаження розкладу."
        )

        st.code(str(e))

        return pd.DataFrame(
            columns=REQUIRED_SCHEDULE_COLUMNS
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
                f"❌ Максимальна кількість завдань — {MAX_SCHEDULES}."
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
# РОЗКЛАД МОДУЛІВ — ЗАВАНТАЖЕННЯ
# ============================================================

def load_module_schedule():

    try:

        worksheet = get_module_schedule_worksheet()

        if worksheet is None:

            return pd.DataFrame(
                columns=MODULE_SCHEDULE_COLUMNS
            )

        records = worksheet.get_all_records()

        if not records:

            return pd.DataFrame(
                columns=MODULE_SCHEDULE_COLUMNS
            )

        raw_df = pd.DataFrame(records)

        return prepare_module_dataframe(
            raw_df
        )

    except Exception as e:

        st.error(
            "❌ Помилка завантаження розкладу модулів."
        )

        st.code(str(e))

        return pd.DataFrame(
            columns=MODULE_SCHEDULE_COLUMNS
        )


# ============================================================
# РОЗКЛАД МОДУЛІВ — ЗБЕРЕЖЕННЯ
# ============================================================

def save_module_schedule(df):
    """
    Зберігає рівно 10 колонок.

    КРИТИЧНО:
    тривалість записується в Google Sheets
    як число float, а не текст.
    """

    try:

        worksheet = get_module_schedule_worksheet()

        if worksheet is None:
            return False

        clean_df = prepare_module_dataframe(
            df
        )

        if len(clean_df) > MAX_SCHEDULES * 3:

            st.error(
                f"❌ Максимальна кількість записів розкладу — "
                f"{MAX_SCHEDULES * 3}."
            )

            return False

        values = [
            MODULE_SCHEDULE_COLUMNS.copy()
        ]

        for _, row in clean_df.iterrows():

            out = []

            for column in MODULE_SCHEDULE_COLUMNS:

                value = row[column]

                # ------------------------------------------------
                # ТРИВАЛІСТЬ
                # ------------------------------------------------

                if column == "тривалість, годин":

                    number = parse_duration(
                        value
                    )

                    if number is None:

                        out.append("")

                    else:

                        # ПЕРЕДАЄМО САМЕ ЧИСЛО.
                        out.append(
                            round(number, 6)
                        )

                # ------------------------------------------------
                # АКТИВНІСТЬ
                # ------------------------------------------------

                elif column == "активність":

                    out.append(
                        bool(
                            normalize_activity(value)
                        )
                    )

                # ------------------------------------------------
                # ВСІ ІНШІ ПОЛЯ
                # ------------------------------------------------

                else:

                    out.append(
                        safe_text(value)
                    )

            values.append(out)

        # Повністю переписуємо аркуш.
        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=values,
            raw=True,
        )

        # Колонка F — число.
        #
        # 1 -> 1,0
        # 1.05 -> 1,05
        # 1.5 -> 1,5
        #
        # Відображення залежить від локалі Google Sheets.
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
                "Не вдалося встановити формат тривалості: "
                f"{format_error}"
            )

        return True

    except Exception as e:

        st.error(
            "❌ Помилка збереження розкладу модулів."
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
            "❌ Не вдалося прочитати налаштування Tuya."
        )

        st.code(str(e))

        st.stop()


TUYA_SETTINGS = get_tuya_settings()

ACCESS_ID = TUYA_SETTINGS["access_id"]
ACCESS_KEY = TUYA_SETTINGS["access_key"]
API_ENDPOINT = TUYA_SETTINGS["endpoint"]

BREAKER_ID = TUYA_SETTINGS["breaker"]

RELAY_GROUP_ID = TUYA_SETTINGS[
    "relay_group"
]

RELAY_5_ID = TUYA_SETTINGS[
    "relay_5"
]

RELAY_6_ID = TUYA_SETTINGS[
    "relay_6"
]

RELAY_7_ID = TUYA_SETTINGS[
    "relay_7"
]


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
        isinstance(response, dict)
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

    device_id = TUYA_SETTINGS.get(
        config["device_id_key"],
        "",
    )

    if not device_id:
        return None

    value = get_code_value(
        get_device_status(device_id),
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
        switch_code=config["switch_code"],
        state=state,
        countdown_seconds=(
            duration_seconds
            if state
            else 0
        ),
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
    duration_hours=None,
    status="Заплановано",
    active=True,
    created_at=None,
    error="",
):

    duration = parse_duration(
        duration_hours
    )

    return {
        "ID": make_id(),

        "дата та час створення запису":
            format_schedule_datetime(
                created_at
                or datetime.now(KYIV_TZ)
            ),

        "дата та час початку":
            format_schedule_datetime(
                start_dt
            ),

        "модуль":
            safe_text(module_name),

        "дія":
            normalize_action(action),

        # ВАЖЛИВО:
        # справжній float, не string.
        "тривалість, годин":
            duration,

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
# ПОШУК ОСТАННЬОГО КОРИСТУВАЦЬКОГО ЗАПИСУ
# ============================================================

def get_last_user_record(df):
    """
    Шукає останній запис:
        дія = Увімкнути
        тривалість задана.

    Саме цей запис вважаємо останнім
    користувацьким модулем.
    """

    df = prepare_module_dataframe(df)

    if df.empty:
        return None, None

    candidates = []

    for i, row in df.iterrows():

        action = normalize_action(
            row["дія"]
        )

        if action != "Увімкнути":
            continue

        duration = parse_duration(
            row["тривалість, годин"]
        )

        if duration is None:
            continue

        start = parse_schedule_datetime(
            row["дата та час початку"]
        )

        if start is None:
            continue

        candidates.append(
            (i, start)
        )

    if not candidates:
        return None, None

    return max(
        candidates,
        key=lambda x: x[1],
    )


# ============================================================
# ВИЗНАЧЕННЯ НАСТУПНОГО ЗАПИСУ
# ============================================================

def get_next_user_entry_defaults(df):
    """
    Після першого запису:

        старт + тривалість = час
        завершення користувацького модуля.

    Наступний користувацький запис
    починається саме в цей момент.

    Модуль беремо з першого автоматичного
    ON після останнього користувацького ON.
    """

    df = prepare_module_dataframe(
        df
    )

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

    idx, _ = get_last_user_record(
        df
    )

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
        row["дата та час початку"]
    )

    duration = parse_duration(
        row["тривалість, годин"]
    )

    if start is None:
        start = datetime.now(
            KYIV_TZ
        )

    if duration is None:
        duration = 0.0

    next_module = ""

    # Перший ON після користувацького ON
    # — це автоматичний запуск наступного модуля.
    for j in range(
        idx + 1,
        len(df),
    ):

        if (
            normalize_action(
                df.iloc[j]["дія"]
            )
            == "Увімкнути"
        ):

            candidate_module = safe_text(
                df.iloc[j]["модуль"]
            )

            if candidate_module:
                next_module = (
                    candidate_module
                )

            break

    if not next_module:

        next_module = list(
            MODULE_CONFIG.keys()
        )[0]

    next_start = (
        start
        + timedelta(
            hours=duration
        )
    )

    return (
        next_start,
        next_module,
    )


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
    Перший запис:

    1. ON поточного модуля
    2. ON наступного модуля за 3 хв до завершення
    3. OFF поточного модуля

    Приклад:

    Модуль 1-2 ON   10:00
    Модуль 1-3 ON   10:57
    Модуль 1-2 OFF  11:00

    якщо тривалість = 1,0 год.
    """

    start_dt = parse_schedule_datetime(
        start_dt
    )

    duration = parse_duration(
        duration_hours
    )

    if start_dt is None:
        raise ValueError(
            "Некоректна дата та час."
        )

    if duration is None or duration <= 0:
        raise ValueError(
            "Тривалість повинна бути більшою за 0."
        )

    finish = (
        start_dt
        + timedelta(
            hours=duration
        )
    )

    created = datetime.now(
        KYIV_TZ
    )

    rows = []

    # --------------------------------------------------------
    # 1. Поточний модуль — УВІМКНУТИ
    # --------------------------------------------------------

    rows.append(
        make_row(
            module_name,
            "Увімкнути",
            start_dt,
            duration,
            created_at=created,
        )
    )

    # --------------------------------------------------------
    # 2-3. Наступний модуль + OFF поточного
    # --------------------------------------------------------

    if (
        next_module
        and next_module != "Не виключати"
    ):

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
                None,
                created_at=created,
            )
        )

        rows.append(
            make_row(
                module_name,
                "Вимкнути",
                finish,
                None,
                created_at=created,
            )
        )

    return rows


# ============================================================
# ДОДАВАННЯ НАСТУПНОГО ЗАПИСУ
# ============================================================

def append_user_chain_record(
    df,
    start_datetime,
    module_name,
    duration_hours,
    next_module,
):
    """
    Додає наступне завдання.

    Вхід:

        start_datetime
            = автоматично визначений час
              початку нового користувацького модуля.

        module_name
            = автоматично визначений модуль.

        duration_hours
            = тривалість нового модуля,
              задана користувачем.

        next_module
            = модуль, який повинен бути
              запущений наступним.

    Логіка:

    Попередній автоматичний ON
    вже працював з моменту:

        auto_start

    до моменту:

        finish нового модуля.

    Тому його тривалість:

        finish - auto_start

    Наприклад:

        автоматичний ON Модуль 1-3:
        10:57

        новий модуль:
        11:00

        тривалість нового:
        1,05 год

        завершення:
        12:03

        тоді автоматичний Модуль 1-3:

        10:57 -> 12:03
        = 1,10 год

    Ніяких множень на 10 / 100 / 1000.
    """

    df = prepare_module_dataframe(
        df
    )

    if df.empty:
        return (
            False,
            "Немає попереднього запису."
        )

    # --------------------------------------------------------
    # Останній користувацький запис
    # --------------------------------------------------------

    idx, _ = get_last_user_record(
        df
    )

    if idx is None:
        return (
            False,
            "Немає попереднього користувацького запису."
        )

    # --------------------------------------------------------
    # Час нового користувацького запису
    # --------------------------------------------------------

    start_dt = parse_schedule_datetime(
        start_datetime
    )

    if start_dt is None:
        return (
            False,
            "Некоректна дата та час нового запису."
        )

    # --------------------------------------------------------
    # Тривалість нового користувацького запису
    # --------------------------------------------------------

    duration = parse_duration(
        duration_hours
    )

    if duration is None:
        return (
            False,
            "Некоректна тривалість нового запису."
        )

    if duration <= 0:
        return (
            False,
            "Тривалість повинна бути більшою за 0."
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
            df.iloc[j]["дія"]
        )

        duration_value = parse_duration(
            df.iloc[j][
                "тривалість, годин"
            ]
        )

        if (
            action == "Увімкнути"
            and duration_value is None
        ):

            auto_idx = j
            break

    if auto_idx is None:

        return (
            False,
            "Не знайдено автоматичний запис наступного модуля."
        )

    # --------------------------------------------------------
    # ПАРАМЕТРИ АВТОМАТИЧНОГО ON
    # --------------------------------------------------------

    auto_row = df.iloc[
        auto_idx
    ]

    auto_start = parse_schedule_datetime(
        auto_row[
            "дата та час початку"
        ]
    )

    auto_module = safe_text(
        auto_row["модуль"]
    )

    if auto_start is None:

        return (
            False,
            "Некоректний час запуску автоматичного модуля."
        )

    if not auto_module:

        return (
            False,
            "Не визначено автоматичний модуль."
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
    # ТРИВАЛІСТЬ ПОПЕРЕДНЬОГО АВТОМАТИЧНОГО ON
    # --------------------------------------------------------

    auto_duration = (
        finish - auto_start
    ).total_seconds() / 3600.0

    if auto_duration <= 0:

        return (
            False,
            "Час нового запису повинен бути пізніше "
            "запуску автоматичного модуля."
        )

    # ========================================================
    # КЛЮЧОВИЙ МОМЕНТ
    #
    # Записуємо FLOAT, НЕ STRING.
    #
    # Саме тут раніше виникала:
    #
    # TypeError string_arrow
    #
    # і подальша проблема:
    #
    # 1,0 -> 10
    # 1,05 -> 100,5
    # ========================================================

    df.at[
        auto_idx,
        "тривалість, годин"
    ] = float(
        round(
            auto_duration,
            6,
        )
    )

    # --------------------------------------------------------
    # Перевіряємо, що значення дійсно число
    # --------------------------------------------------------

    check_duration = parse_duration(
        df.at[
            auto_idx,
            "тривалість, годин"
        ]
    )

    if check_duration is None:

        return (
            False,
            "Не вдалося правильно записати тривалість "
            "автоматичного модуля."
        )

    # --------------------------------------------------------
    # Перетворення назад у список записів
    # --------------------------------------------------------

    rows = df.to_dict(
        orient="records"
    )

    # --------------------------------------------------------
    # Якщо наступний модуль заданий
    # --------------------------------------------------------

    if (
        next_module
        and next_module != "Не виключати"
    ):

        created = datetime.now(
            KYIV_TZ
        )

        # Наступний модуль вмикаємо
        # за 3 хв до завершення.
        next_start = (
            finish
            - timedelta(
                minutes=3
            )
        )

        # ----------------------------------------------------
        # НОВИЙ АВТОМАТИЧНИЙ ON
        # ----------------------------------------------------

        rows.append(
            make_row(
                next_module,
                "Увімкнути",
                next_start,
                None,
                created_at=created,
            )
        )

        # ----------------------------------------------------
        # OFF ПОТОЧНОГО МОДУЛЯ
        # ----------------------------------------------------

        rows.append(
            make_row(
                auto_module,
                "Вимкнути",
                finish,
                None,
                created_at=created,
            )
        )

    return (
        True,
        prepare_module_dataframe(
            pd.DataFrame(
                rows,
                columns=MODULE_SCHEDULE_COLUMNS,
            )
        ),
    )


# ============================================================
# ОСНОВНА ФУНКЦІЯ ДОДАВАННЯ
# ============================================================

def add_module_schedule_task(
    df,
    start_datetime,
    module_name,
    duration_hours,
    next_module,
):
    """
    Якщо розклад порожній:

        створюємо 3 записи.

    Якщо розклад вже існує:

        змінюємо тривалість попереднього
        автоматичного ON

        + додаємо 2 нові записи.
    """

    df = prepare_module_dataframe(
        df
    )

    # ========================================================
    # ПЕРШИЙ ЗАПИС
    # ========================================================

    if df.empty:

        try:

            rows = create_first_module_record(
                start_datetime,
                module_name,
                duration_hours,
                next_module,
            )

        except ValueError as e:

            return (
                False,
                None,
                str(e),
            )

        result_df = prepare_module_dataframe(
            pd.DataFrame(
                rows,
                columns=MODULE_SCHEDULE_COLUMNS,
            )
        )

        if next_module == "Не виключати":

            message = (
                "Створено 1 запис."
            )

        else:

            message = (
                "Створено 3 записи."
            )

        return (
            True,
            result_df,
            message,
        )

    # ========================================================
    # НАСТУПНИЙ ЗАПИС
    # ========================================================

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

    df = prepare_module_dataframe(
        load_module_schedule()
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

    result_df = prepare_module_dataframe(
        pd.DataFrame(
            rows,
            columns=MODULE_SCHEDULE_COLUMNS,
        )
    )

    return save_module_schedule(
        result_df
    )


# ============================================================
# АКТИВНІСТЬ
# ============================================================

def change_module_activity(
    index,
    active,
):

    df = prepare_module_dataframe(
        load_module_schedule()
    )

    if (
        index < 0
        or index >= len(df)
    ):
        return False

    df.at[
        index,
        "активність"
    ] = bool(active)

    if active:

        if safe_text(
            df.at[
                index,
                "статус"
            ]
        ) in (
            "Призупинено",
            "Помилка",
        ):

            df.at[
                index,
                "статус"
            ] = "Заплановано"

        df.at[
            index,
            "помилка"
        ] = ""

    else:

        df.at[
            index,
            "статус"
        ] = "Призупинено"

    return save_module_schedule(
        df
    )


# ============================================================
# ОНОВЛЕННЯ ЗАПИСУ
# ============================================================

def update_module_schedule_task(
    index,
    start_datetime,
    module_name,
    duration_hours,
    action,
):

    df = prepare_module_dataframe(
        load_module_schedule()
    )

    if (
        index < 0
        or index >= len(df)
    ):
        return False

    duration = parse_duration(
        duration_hours
    )

    if duration is None:

        return False

    df.at[
        index,
        "дата та час початку"
    ] = format_schedule_datetime(
        start_datetime
    )

    df.at[
        index,
        "модуль"
    ] = safe_text(
        module_name
    )

    df.at[
        index,
        "дія"
    ] = normalize_action(
        action
    )

    df.at[
        index,
        "тривалість, годин"
    ] = duration

    df.at[
        index,
        "статус"
    ] = "Заплановано"

    df.at[
        index,
        "дата та час фактичного виконання"
    ] = ""

    df.at[
        index,
        "помилка"
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

    if not normalize_activity(
        row["активність"]
    ):

        return (
            False,
            "Запис неактивний."
        )

    start_dt = parse_schedule_datetime(
        row["дата та час початку"]
    )

    if start_dt is None:

        return (
            False,
            "Некоректна дата та час початку."
        )

    # Виконання тільки в межах
    # першої хвилини від запланованого часу.
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

    status = safe_text(
        row["статус"]
    )

    if status not in (
        "",
        "Заплановано",
    ):

        return (
            False,
            "Запис уже оброблений."
        )

    module_name = safe_text(
        row["модуль"]
    )

    action = normalize_action(
        row["дія"]
    )

    if module_name not in MODULE_CONFIG:

        return (
            False,
            f"Невідомий модуль «{module_name}»."
        )

    # ========================================================
    # УВІМКНЕННЯ
    # ========================================================

    if action == "Увімкнути":

        duration = parse_duration(
            row["тривалість, годин"]
        )

        if duration is None:

            return (
                False,
                "Для увімкнення ще не визначена тривалість."
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

    # ========================================================
    # ВИМКНЕННЯ
    # ========================================================

    elif action == "Вимкнути":

        success = set_module_state(
            module_name,
            False,
        )

    else:

        return (
            False,
            f"Невідома дія «{action}»."
        )

    if not success:

        return (
            False,
            f"Tuya не прийняла команду для {module_name}."
        )

    # ========================================================
    # ЗАПИС РЕЗУЛЬТАТУ
    # ========================================================

    fresh = prepare_module_dataframe(
        load_module_schedule()
    )

    if index < len(fresh):

        fresh.at[
            index,
            "статус"
        ] = "Виконано"

        fresh.at[
            index,
            "дата та час фактичного виконання"
        ] = now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        fresh.at[
            index,
            "помилка"
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

    df = prepare_module_dataframe(
        load_module_schedule()
    )

    for index, row in df.iterrows():

        if not normalize_activity(
            row["активність"]
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
# TUYA СТАН
# ============================================================

if TUYA_CONNECTED:

    st.success(
        "🟢 Система керування підключена до Tuya Cloud"
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
                else
                "🔴 Автомат вимкнено."
            )

            time.sleep(
                0.4
            )

            st.rerun()

        else:

            st.error(
                "❌ Не вдалося змінити стан автомата."
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
    "Далі дата/час і модуль визначаються автоматично. "
    "Користувач змінює тільки тривалість "
    "і наступний модуль."
)


module_df = prepare_module_dataframe(
    load_module_schedule()
)


# ============================================================
# ВИЗНАЧЕННЯ НАСТУПНОГО ЧАСУ
# ============================================================

if module_df.empty:

    next_start = datetime.now(
        KYIV_TZ
    ).replace(
        second=0,
        microsecond=0,
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

        # ====================================================
        # ПЕРШИЙ ЗАПИС
        # ====================================================

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

        # ====================================================
        # НАСТУПНІ ЗАПИСИ
        # ====================================================

        else:

            module_time = next_start

            module_name = next_module

            st.info(
                f"Автоматично: "
                f"**{format_schedule_datetime(module_time)}** "
                f"— **{module_name}**. "
                f"Користувач змінює тільки "
                f"тривалість і наступний модуль."
            )

        # ====================================================
        # ТРИВАЛІСТЬ
        # ====================================================

        duration_hours = st.number_input(
            "Тривалість, годин",
            min_value=0.01,
            max_value=168.0,
            value=1.0,
            step=0.05,
            format="%.2f",
        )

        # ====================================================
        # НАСТУПНИЙ МОДУЛЬ
        # ====================================================

        next_module_choice = st.selectbox(
            "Наступний модуль",
            NEXT_MODULE_OPTIONS,
            index=0,
        )

        # ====================================================
        # КНОПКА
        # ====================================================

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
                        "❌ Не вдалося зберегти розклад."
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


module_df = prepare_module_dataframe(
    load_module_schedule()
)


if module_df.empty:

    st.info(
        "Розклад модулів поки порожній."
    )

else:

    # ========================================================
    # ПІДГОТОВКА КОПІЇ ДЛЯ ВІДОБРАЖЕННЯ
    # ========================================================

    display_df = module_df.copy()

    # Для таблиці показуємо українську кому.
    display_df[
        "тривалість, годин"
    ] = [
        format_duration(value)
        for value in display_df[
            "тривалість, годин"
        ]
    ]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

    # ========================================================
    # КЕРУВАННЯ ОКРЕМИМИ ЗАПИСАМИ
    # ========================================================

    for index, row in module_df.iterrows():

        with st.container(
            border=True
        ):

            c1, c2, c3, c4 = st.columns(
                [
                    0.5,
                    1.5,
                    1.2,
                    1.2,
                ]
            )

            with c1:

                st.markdown(
                    f"**{index + 1}**"
                )

            with c2:

                st.markdown(
                    f"**{safe_text(row['модуль'])}** "
                    f"— "
                    f"{safe_text(row['дія'])}"
                )

                st.caption(
                    safe_text(
                        row[
                            "дата та час початку"
                        ]
                    )
                )

            with c3:

                duration = format_duration(
                    row[
                        "тривалість, годин"
                    ]
                )

                st.caption(
                    f"Тривалість: "
                    f"{duration or '—'}"
                )

                st.caption(
                    f"Статус: "
                    f"{safe_text(row['статус']) or '—'}"
                )

            with c4:

                active = normalize_activity(
                    row["активність"]
                )

                if active:

                    st.success(
                        "🟢 Активний"
                    )

                else:

                    st.warning(
                        "⏸️ Неактивний"
                    )

            # =================================================
            # КНОПКИ
            # =================================================

            b1, b2 = st.columns(
                2
            )

            with b1:

                label = (
                    "⏸️ Вимкнути"
                    if active
                    else
                    "▶️ Увімкнути"
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
            f"🔌 {module_name}"
            f"</div>",
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
                        "🟢 Увімкнено "
                        f"{module_name}."
                    )
                    if desired
                    else
                    (
                        "🔴 Вимкнено "
                        f"{module_name}."
                    )
                )

                time.sleep(
                    0.4
                )

                st.rerun()

            else:

                st.error(
                    f"❌ Не вдалося змінити стан "
                    f"{module_name}."
                )


# ============================================================
# ОНОВИТИ
# ============================================================

st.markdown("---")

if st.button(
    "🔄 Оновити стан і розклад",
    use_container_width=True,
):

    st.rerun()
