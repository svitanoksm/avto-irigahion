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

# Кеш читання Google Sheets.
# Планувальник працює кожні 10 секунд, тому немає сенсу
# робити нове читання таблиці частіше.
SHEETS_READ_CACHE_SECONDS = 5


SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1qF-7THB566lqOyQV0f6xuB052IRHh8s4CHMUpuN82P4/"
    "edit"
)

SCHEDULE_WORKSHEET_NAME = (
    "Розклад для керування Свердловинами"
)

MODULE_SCHEDULE_WORKSHEET_NAME = (
    "Розклад модулів"
)

KYIV_TZ = ZoneInfo(TIMEZONE_ID)


# ============================================================
# СТРУКТУРА РОЗКЛАДУ МОДУЛІВ
# ============================================================

MODULE_SCHEDULE_COLUMNS = [
    "ID",
    "ID наступного запису",
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
# TUYA — КОНФІГУРАЦІЯ МОДУЛІВ
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

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip()


def parse_schedule_datetime(value):

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

        parsed = parsed.replace(
            tzinfo=KYIV_TZ
        )

    else:

        parsed = parsed.astimezone(
            KYIV_TZ
        )

    return parsed


def format_schedule_datetime(value):

    parsed = parse_schedule_datetime(value)

    if parsed is None:
        return safe_text(value)

    return parsed.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


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


def normalize_duration(value):

    text = safe_text(value)

    if not text:
        return None

    text = text.replace(",", ".")

    try:
        return float(text)
    except Exception:
        return None


def format_duration(value):

    number = normalize_duration(value)

    if number is None:
        return safe_text(value)

    if number.is_integer():
        return str(int(number))

    return (
        f"{number:.6f}"
        .rstrip("0")
        .rstrip(".")
    )


# ============================================================
# ID
# ============================================================

def generate_unique_id(existing_ids=None):

    existing_ids = existing_ids or set()

    candidate = datetime.now(
        KYIV_TZ
    ).replace(
        microsecond=0
    )

    while (
        candidate.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        in existing_ids
    ):

        candidate += timedelta(
            seconds=1
        )

    return candidate.strftime(
        "%Y-%m-%d %H:%M:%S"
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

            raise RuntimeError(
                "У Secrets відсутній "
                "gcp_service_account."
            )

        creds_dict = dict(
            st.secrets[
                "gcp_service_account"
            ]
        )

        credentials = (
            Credentials
            .from_service_account_info(
                creds_dict,
                scopes=scope,
            )
        )

        client = gspread.authorize(
            credentials
        )

        return client.open_by_url(
            SPREADSHEET_URL
        )

    except Exception as e:

        logging.error(
            f"Google Sheets connection error: {e}"
        )

        return None


@st.cache_resource
def get_schedule_worksheet():

    spreadsheet = init_google_sheets()

    if spreadsheet is None:
        return None

    try:

        return spreadsheet.worksheet(
            SCHEDULE_WORKSHEET_NAME
        )

    except Exception as e:

        logging.error(
            f"Worksheet error: {e}"
        )

        return None


@st.cache_resource
def get_module_schedule_worksheet():

    spreadsheet = init_google_sheets()

    if spreadsheet is None:
        return None

    try:

        return spreadsheet.worksheet(
            MODULE_SCHEDULE_WORKSHEET_NAME
        )

    except Exception as e:

        logging.error(
            f"Module worksheet error: {e}"
        )

        return None


# ============================================================
# DATAFRAME
# ============================================================

def empty_dataframe(columns):

    return pd.DataFrame(
        {c: [] for c in columns}
    )


def prepare_dataframe(
    df,
    columns,
):

    if df is None:
        return empty_dataframe(columns)

    try:

        if df.empty:
            return empty_dataframe(columns)

    except Exception:

        return empty_dataframe(columns)

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

            result[column] = [""] * len(df)

    return result.reset_index(
        drop=True
    )


# ============================================================
# СТАРИЙ РОЗКЛАД СВЕРДЛОВИНИ
# ============================================================

@st.cache_data(
    ttl=SHEETS_READ_CACHE_SECONDS,
    show_spinner=False,
)
def load_schedule_cached():

    worksheet = get_schedule_worksheet()

    if worksheet is None:
        raise RuntimeError(
            "Не вдалося відкрити аркуш "
            f"«{SCHEDULE_WORKSHEET_NAME}»."
        )

    try:

        records = worksheet.get_all_records()

        return prepare_dataframe(
            pd.DataFrame(records)
            if records
            else None,
            REQUIRED_SCHEDULE_COLUMNS,
        )

    except Exception as e:

        logging.error(
            f"Schedule read error: {e}"
        )

        raise RuntimeError(
            f"Помилка читання аркуша "
            f"«{SCHEDULE_WORKSHEET_NAME}»: "
            f"{e}"
        )


def load_schedule():

    try:

        return load_schedule_cached()

    except Exception as e:

        st.error(
            "❌ Не вдалося прочитати "
            "розклад свердловини."
        )

        st.code(str(e))

        return empty_dataframe(
            REQUIRED_SCHEDULE_COLUMNS
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
                f"❌ Максимальна кількість "
                f"завдань — {MAX_SCHEDULES}."
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

        load_schedule_cached.clear()

        return True

    except Exception as e:

        st.error(
            "❌ Помилка збереження "
            "розкладу свердловини."
        )

        st.code(str(e))

        return False


# ============================================================
# ЗАВАНТАЖЕННЯ МОДУЛЬНОГО РОЗКЛАДУ
# ============================================================

@st.cache_data(
    ttl=SHEETS_READ_CACHE_SECONDS,
    show_spinner=False,
)
def load_module_schedule_cached():

    worksheet = get_module_schedule_worksheet()

    if worksheet is None:

        raise RuntimeError(
            "Не вдалося відкрити аркуш "
            f"«{MODULE_SCHEDULE_WORKSHEET_NAME}»."
        )

    try:

        records = worksheet.get_all_records()

        if not records:

            return empty_dataframe(
                MODULE_SCHEDULE_COLUMNS
            )

        raw_df = pd.DataFrame(records)

        # ----------------------------------------------------
        # ПІДТРИМКА СТАРОЇ СТРУКТУРИ
        # ----------------------------------------------------

        if "ID" not in raw_df.columns:

            rows = []

            existing_ids = set()

            for _, old in raw_df.iterrows():

                row = {
                    c: ""
                    for c in MODULE_SCHEDULE_COLUMNS
                }

                new_id = generate_unique_id(
                    existing_ids
                )

                existing_ids.add(
                    new_id
                )

                row["ID"] = new_id

                old_start = safe_text(
                    old.get(
                        "дата та час початку",
                        old.get(
                            "час",
                            "",
                        ),
                    )
                )

                parsed_start = (
                    parse_schedule_datetime(
                        old_start
                    )
                )

                if parsed_start:

                    row[
                        "дата та час початку"
                    ] = format_schedule_datetime(
                        parsed_start
                    )

                else:

                    row[
                        "дата та час початку"
                    ] = old_start

                row["модуль"] = safe_text(
                    old.get(
                        "модуль",
                        "",
                    )
                )

                row["дія"] = normalize_action(
                    old.get(
                        "дія",
                        "",
                    )
                )

                row[
                    "тривалість, годин"
                ] = format_duration(
                    old.get(
                        "тривалість, годин",
                        "",
                    )
                )

                row[
                    "дата та час завершення"
                ] = safe_text(
                    old.get(
                        "дата та час завершення",
                        "",
                    )
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
                    "дата та час запуску наступного модуля"
                ] = safe_text(
                    old.get(
                        "дата та час запуску наступного модуля",
                        "",
                    )
                )

                row[
                    "дата та час вимкнення поточного модуля"
                ] = safe_text(
                    old.get(
                        "дата та час вимкнення поточного модуля",
                        "",
                    )
                )

                row["активність"] = (
                    safe_text(
                        old.get(
                            "активність",
                            "",
                        )
                    )
                    or "TRUE"
                )

                row["статус"] = (
                    safe_text(
                        old.get(
                            "статус",
                            "",
                        )
                    )
                    or "Заплановано"
                )

                row[
                    "дата та час фактичного запуску"
                ] = safe_text(
                    old.get(
                        "дата та час фактичного запуску",
                        "",
                    )
                )

                row[
                    "дата та час фактичного вимкнення"
                ] = safe_text(
                    old.get(
                        "дата та час фактичного вимкнення",
                        "",
                    )
                )

                row["помилка"] = safe_text(
                    old.get(
                        "помилка",
                        "",
                    )
                )

                rows.append(row)

            migrated_df = pd.DataFrame(
                rows,
                columns=MODULE_SCHEDULE_COLUMNS,
            )

            migrated_df = (
                rebuild_next_record_links(
                    migrated_df
                )
            )

            return migrated_df

        # ----------------------------------------------------
        # НОВА СТРУКТУРА
        # ----------------------------------------------------

        result = prepare_dataframe(
            raw_df,
            MODULE_SCHEDULE_COLUMNS,
        )

        result[
            "тривалість, годин"
        ] = result[
            "тривалість, годин"
        ].apply(
            format_duration
        )

        return result

    except Exception as e:

        logging.error(
            f"Module schedule read error: {e}"
        )

        raise RuntimeError(
            f"Помилка читання аркуша "
            f"«{MODULE_SCHEDULE_WORKSHEET_NAME}»: "
            f"{e}"
        )


def load_module_schedule():

    try:

        return load_module_schedule_cached()

    except Exception as e:

        st.error(
            "❌ Не вдалося прочитати "
            "розклад модулів."
        )

        st.code(str(e))

        # КРИТИЧНО:
        # Не видаємо порожній розклад,
        # якщо Google Sheets не відповів.
        return None


# ============================================================
# ЗБЕРЕЖЕННЯ МОДУЛЬНОГО РОЗКЛАДУ
# ============================================================

def save_module_schedule(df):

    try:

        worksheet = (
            get_module_schedule_worksheet()
        )

        if worksheet is None:

            raise RuntimeError(
                "Аркуш "
                f"«{MODULE_SCHEDULE_WORKSHEET_NAME}» "
                "недоступний."
            )

        clean_df = prepare_dataframe(
            df,
            MODULE_SCHEDULE_COLUMNS,
        )

        if len(clean_df) > MAX_SCHEDULES:

            raise RuntimeError(
                f"Максимальна кількість "
                f"завдань — {MAX_SCHEDULES}."
            )

        existing_ids = set()

        for i in range(len(clean_df)):

            current_id = safe_text(
                clean_df.at[
                    i,
                    "ID",
                ]
            )

            if not current_id:

                current_id = (
                    generate_unique_id(
                        existing_ids
                    )
                )

                clean_df.at[
                    i,
                    "ID",
                ] = current_id

            existing_ids.add(
                current_id
            )

        for i in range(len(clean_df)):

            clean_df.at[
                i,
                "тривалість, годин",
            ] = format_duration(
                clean_df.at[
                    i,
                    "тривалість, годин",
                ]
            )

        values = [
            MODULE_SCHEDULE_COLUMNS.copy()
        ]

        for _, row in clean_df.iterrows():

            values.append([
                safe_text(row[c])
                for c in MODULE_SCHEDULE_COLUMNS
            ])

        worksheet.clear()

        worksheet.update(
            range_name="A1",
            values=values,
        )

        # Після запису обов'язково
        # очищаємо кеш.
        load_module_schedule_cached.clear()

        return True

    except Exception as e:

        logging.error(
            f"Module schedule save error: {e}"
        )

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
                conf[
                    "relay_group_device_id"
                ]
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
        if isinstance(
            result,
            list,
        )
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
        return None, None, None

    duration = normalize_duration(
        duration_hours
    )

    if duration is None:
        return None, None, None

    if duration <= 0:
        return None, None, None

    finish_dt = (
        start_dt
        + timedelta(
            hours=duration
        )
    )

    if next_module == "Не виключати":

        return (
            finish_dt,
            None,
            None,
        )

    # --------------------------------------------------------
    # ВАЖЛИВО:
    #
    # Наступний модуль запускається
    # за 3 хвилини ДО завершення поточного.
    #
    # Саме цей час тепер є
    # "дата та час початку"
    # наступного запису.
    # --------------------------------------------------------

    next_start_dt = (
        finish_dt
        - timedelta(
            minutes=3
        )
    )

    current_off_dt = finish_dt

    return (
        finish_dt,
        next_start_dt,
        current_off_dt,
    )


# ============================================================
# НАСТУПНИЙ ЗАПИС
# ============================================================

def get_next_module_schedule_values(
    df,
):

    if df is None:
        return None, None, False

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

    previous_finish = (
        parse_schedule_datetime(
            previous.get(
                "дата та час завершення",
                "",
            )
        )
    )

    previous_next_start = (
        parse_schedule_datetime(
            previous.get(
                "дата та час запуску наступного модуля",
                "",
            )
        )
    )

    previous_next_module = safe_text(
        previous.get(
            "наступний модуль",
            "",
        )
    )

    # --------------------------------------------------------
    # НОВА ЛОГІКА:
    #
    # Для наступного запису беремо
    # саме "дата та час запуску наступного модуля".
    #
    # Тобто:
    #
    # попередній модуль:
    # 10:00 → 11:00
    #
    # наступний:
    # 10:57 → 11:57
    # --------------------------------------------------------

    if (
        previous_next_start is not None
        and previous_next_module
        in MODULE_CONFIG
    ):

        start_dt = (
            previous_next_start
        )

        next_module = (
            previous_next_module
        )

        return (
            start_dt,
            next_module,
            True,
        )

    # --------------------------------------------------------
    # Резервний варіант.
    # --------------------------------------------------------

    if previous_finish is not None:

        start_dt = previous_finish

    else:

        previous_start = (
            parse_schedule_datetime(
                previous.get(
                    "дата та час початку",
                    "",
                )
            )
        )

        duration = normalize_duration(
            previous.get(
                "тривалість, годин",
                "0",
            )
        )

        if (
            previous_start is not None
            and duration is not None
        ):

            start_dt = (
                previous_start
                + timedelta(
                    hours=duration
                )
            )

        else:

            start_dt = datetime.now(
                KYIV_TZ
            ).replace(
                second=0,
                microsecond=0,
            )

    if previous_next_module in MODULE_CONFIG:

        next_module = (
            previous_next_module
        )

    else:

        next_module = list(
            MODULE_CONFIG.keys()
        )[0]

    return (
        start_dt,
        next_module,
        True,
    )


# ============================================================
# ID-ЗВ'ЯЗКИ
# ============================================================

def rebuild_next_record_links(df):

    df = prepare_dataframe(
        df,
        MODULE_SCHEDULE_COLUMNS,
    )

    if df.empty:
        return df

    for i in range(len(df)):

        if i < len(df) - 1:

            df.at[
                i,
                "ID наступного запису",
            ] = safe_text(
                df.at[
                    i + 1,
                    "ID",
                ]
            )

        else:

            df.at[
                i,
                "ID наступного запису",
            ] = ""

    return df


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

    df = load_module_schedule()

    # --------------------------------------------------------
    # Якщо Sheets недоступний — НІКОЛИ
    # не вважаємо розклад порожнім.
    # --------------------------------------------------------

    if df is None:

        return (
            False,
            "Не вдалося прочитати "
            "поточний розклад "
            "із Google Sheets.",
        )

    df = prepare_dataframe(
        df,
        MODULE_SCHEDULE_COLUMNS,
    )

    if len(df) >= MAX_SCHEDULES:

        return (
            False,
            f"Досягнуто максимуму "
            f"{MAX_SCHEDULES} завдань.",
        )

    start_datetime = (
        parse_schedule_datetime(
            start_datetime
        )
    )

    if start_datetime is None:

        return (
            False,
            "Некоректна дата "
            "та час початку.",
        )

    duration = normalize_duration(
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

    if duration > 24:

        return (
            False,
            "Тривалість не може бути "
            "більшою за 24 години.",
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
            "Не вдалося "
            "розрахувати час.",
        )

    existing_ids = set(
        safe_text(v)
        for v in df["ID"].tolist()
        if safe_text(v)
    )

    new_id = generate_unique_id(
        existing_ids
    )

    new_row = {
        c: ""
        for c in MODULE_SCHEDULE_COLUMNS
    }

    new_row.update({

        "ID":
            new_id,

        "ID наступного запису":
            "",

        "дата та час початку":
            format_schedule_datetime(
                start_datetime
            ),

        "модуль":
            safe_text(module_name),

        "дія":
            normalize_action(action),

        "тривалість, годин":
            format_duration(duration),

        "дата та час завершення":
            format_schedule_datetime(
                finish_dt
            ),

        "наступний модуль":
            safe_text(next_module),

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

    new_df = pd.DataFrame(
        rows,
        columns=MODULE_SCHEDULE_COLUMNS,
    )

    new_df = rebuild_next_record_links(
        new_df
    )

    if save_module_schedule(
        new_df
    ):

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

    df = load_module_schedule()

    if df is None:
        return False

    df = prepare_dataframe(
        df,
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

    new_df = pd.DataFrame(
        rows,
        columns=MODULE_SCHEDULE_COLUMNS,
    )

    new_df = rebuild_next_record_links(
        new_df
    )

    return save_module_schedule(
        new_df
    )


# ============================================================
# АКТИВНІСТЬ
# ============================================================

def change_module_activity(
    index,
    active,
):

    df = load_module_schedule()

    if df is None:
        return False

    df = prepare_dataframe(
        df,
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

    new_df = pd.DataFrame(
        rows,
        columns=MODULE_SCHEDULE_COLUMNS,
    )

    return save_module_schedule(
        new_df
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

    df = load_module_schedule()

    if df is None:
        return False

    df = prepare_dataframe(
        df,
        MODULE_SCHEDULE_COLUMNS,
    )

    if (
        index < 0
        or index >= len(df)
    ):
        return False

    start_datetime = (
        parse_schedule_datetime(
            start_datetime
        )
    )

    if start_datetime is None:
        return False

    duration = normalize_duration(
        duration_hours
    )

    if duration is None:
        return False

    if duration <= 0:
        return False

    if duration > 24:
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

    old_id = safe_text(
        old.get(
            "ID",
            "",
        )
    )

    row = {
        c: safe_text(
            old.get(c, "")
        )
        for c in MODULE_SCHEDULE_COLUMNS
    }

    row.update({

        "ID":
            old_id,

        "дата та час початку":
            format_schedule_datetime(
                start_datetime
            ),

        "модуль":
            safe_text(module_name),

        "дія":
            normalize_action(action),

        "тривалість, годин":
            format_duration(duration),

        "дата та час завершення":
            format_schedule_datetime(
                finish_dt
            ),

        "наступний модуль":
            safe_text(next_module),

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

    new_df = pd.DataFrame(
        rows,
        columns=MODULE_SCHEDULE_COLUMNS,
    )

    new_df = rebuild_next_record_links(
        new_df
    )

    return save_module_schedule(
        new_df
    )


# ============================================================
# ПОШУК ЗА ID
# ============================================================

def find_row_by_id(
    df,
    record_id,
):

    if df is None:
        return None

    record_id = safe_text(
        record_id
    )

    if not record_id:
        return None

    for index, row in df.iterrows():

        if safe_text(
            row.get(
                "ID",
                "",
            )
        ) == record_id:

            return index

    return None


# ============================================================
# ОНОВЛЕННЯ ФАКТИЧНИХ ДАНИХ
#
# ВАЖЛИВО:
# Функція приймає вже завантажений df.
# Тому Google Sheets повторно НЕ читається.
# ============================================================

def update_record_execution_by_id(
    df,
    record_id,
    actual_on=None,
    actual_off=None,
    status=None,
    error=None,
):

    if df is None:
        return False

    index = find_row_by_id(
        df,
        record_id,
    )

    if index is None:
        return False

    if status is not None:

        df.at[
            index,
            "статус",
        ] = safe_text(status)

    if actual_on is not None:

        df.at[
            index,
            "дата та час фактичного запуску",
        ] = format_schedule_datetime(
            actual_on
        )

    if actual_off is not None:

        df.at[
            index,
            "дата та час фактичного вимкнення",
        ] = format_schedule_datetime(
            actual_off
        )

    if error is not None:

        df.at[
            index,
            "помилка",
        ] = safe_text(error)

    return save_module_schedule(
        df
    )


# ============================================================
# ВИКОНАННЯ ЗАПЛАНОВАНОГО ЗАПИСУ
# ============================================================

def execute_module_schedule_task(
    df,
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

    record_id = safe_text(
        row.get(
            "ID",
            "",
        )
    )

    if not record_id:

        return (
            False,
            "У запису відсутній ID.",
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
            "Некоректна дата "
            "та час початку.",
        )

    now = now.astimezone(
        KYIV_TZ
    )

    # --------------------------------------------------------
    # КОНТРОЛЬНЕ ВІКНО ЗАПУСКУ
    #
    # Ми дозволяємо запуск у момент старту
    # і протягом 2 хвилин після нього.
    #
    # Це особливо важливо для:
    #
    # 10:57:00 — запланований запуск
    #
    # якщо Streamlit перевірив у:
    # 10:56:58 → ще рано
    # 10:57:08 → запускаємо
    # 10:58:59 → ще дозволено
    #
    # Після 10:59 запис вважаємо пропущеним.
    # --------------------------------------------------------

    if now < start_dt:

        return (
            False,
            "Ще не настав час запуску.",
        )

    if now >= (
        start_dt
        + timedelta(
            minutes=2
        )
    ):

        return (
            False,
            "Час запуску вже минув.",
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

    duration_hours = normalize_duration(
        row.get(
            "тривалість, годин",
            "0",
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

    duration_seconds = max(
        1,
        int(
            round(
                duration_hours
                * 3600
            )
        ),
    )

    success = set_module_state(
        module_name,
        True,
        duration_seconds,
    )

    if not success:

        update_record_execution_by_id(
            df=df,
            record_id=record_id,
            status="Помилка",
            error=(
                f"Tuya не прийняла "
                f"команду для "
                f"{module_name}."
            ),
        )

        return (
            False,
            f"Tuya не прийняла "
            f"команду для "
            f"{module_name}.",
        )

    # --------------------------------------------------------
    # ФАКТИЧНИЙ ЗАПУСК
    # --------------------------------------------------------

    update_record_execution_by_id(
        df=df,
        record_id=record_id,
        actual_on=now,
        status="Виконується",
        error="",
    )

    return (
        True,
        f"🟢 {module_name} "
        f"увімкнено на "
        f"{format_duration(duration_hours)} год.",
    )


# ============================================================
# ВИКОНАННЯ НАСТУПНОГО ЗАПИСУ
#
# Залишено як резервний механізм для зв'язку
# ID наступного запису.
# ============================================================

def execute_next_record_if_needed(
    df,
    current_index,
    current_row,
    now,
):

    current_id = safe_text(
        current_row.get(
            "ID",
            "",
        )
    )

    next_id = safe_text(
        current_row.get(
            "ID наступного запису",
            "",
        )
    )

    if not current_id or not next_id:
        return []

    next_start_text = safe_text(
        current_row.get(
            "дата та час запуску наступного модуля",
            "",
        )
    )

    next_start_dt = parse_schedule_datetime(
        next_start_text
    )

    if next_start_dt is None:
        return []

    # Ще рано.
    if now < next_start_dt:
        return []

    next_index = find_row_by_id(
        df,
        next_id,
    )

    if next_index is None:

        return [
            f"⚠️ Не знайдено "
            f"наступний запис "
            f"ID {next_id}."
        ]

    next_row = df.iloc[
        next_index
    ]

    next_status = safe_text(
        next_row.get(
            "статус",
            "",
        )
    )

    next_activity = normalize_activity(
        next_row.get(
            "активність",
            "",
        )
    )

    if not next_activity:
        return []

    if next_status not in (
        "",
        "Заплановано",
    ):
        return []

    # --------------------------------------------------------
    # ВАЖЛИВО:
    #
    # Використовуємо власну дату початку
    # наступного запису.
    # --------------------------------------------------------

    next_record_start = (
        parse_schedule_datetime(
            next_row.get(
                "дата та час початку",
                "",
            )
        )
    )

    if next_record_start is None:
        return []

    if now < next_record_start:
        return []

    next_module = safe_text(
        next_row.get(
            "модуль",
            "",
        )
    )

    duration_hours = normalize_duration(
        next_row.get(
            "тривалість, годин",
            "0",
        )
    )

    if duration_hours is None:
        return []

    duration_seconds = max(
        1,
        int(
            round(
                duration_hours
                * 3600
            )
        ),
    )

    success = set_module_state(
        next_module,
        True,
        duration_seconds,
    )

    if not success:

        update_record_execution_by_id(
            df=df,
            record_id=next_id,
            status="Помилка",
            error=(
                f"Tuya не прийняла "
                f"команду для "
                f"{next_module}."
            ),
        )

        return [
            f"❌ Не вдалося "
            f"увімкнути "
            f"{next_module}."
        ]

    update_record_execution_by_id(
        df=df,
        record_id=next_id,
        actual_on=now,
        status="Виконується",
        error="",
    )

    return [
        f"🟢 {next_module} "
        f"увімкнено за ID "
        f"{next_id}."
    ]


# ============================================================
# ВИМКНЕННЯ ПОТОЧНОГО МОДУЛЯ
# ============================================================

def execute_current_record_off(
    df,
    row,
    now,
):

    record_id = safe_text(
        row.get(
            "ID",
            "",
        )
    )

    if not record_id:
        return []

    next_module = safe_text(
        row.get(
            "наступний модуль",
            "",
        )
    )

    if next_module == "Не виключати":
        return []

    off_text = safe_text(
        row.get(
            "дата та час вимкнення поточного модуля",
            "",
        )
    )

    off_dt = parse_schedule_datetime(
        off_text
    )

    if off_dt is None:
        return []

    if now < off_dt:
        return []

    status = safe_text(
        row.get(
            "статус",
            "",
        )
    )

    # Вимикаємо тільки реально працюючий запис.
    if status != "Виконується":
        return []

    module_name = safe_text(
        row.get(
            "модуль",
            "",
        )
    )

    success = set_module_state(
        module_name,
        False,
    )

    if not success:

        update_record_execution_by_id(
            df=df,
            record_id=record_id,
            status="Помилка",
            error=(
                f"Не вдалося "
                f"вимкнути "
                f"{module_name}."
            ),
        )

        return [
            f"❌ Не вдалося "
            f"вимкнути "
            f"{module_name}."
        ]

    update_record_execution_by_id(
        df=df,
        record_id=record_id,
        actual_off=now,
        status="Виконано",
        error="",
    )

    return [
        f"🔴 {module_name} "
        f"вимкнено."
    ]


# ============================================================
# ОСНОВНИЙ ПЛАНУВАЛЬНИК
# ============================================================

def run_module_scheduler():

    results = []

    now = datetime.now(
        KYIV_TZ
    )

    # ========================================================
    # КРИТИЧНО:
    #
    # ОДНЕ читання Google Sheets
    # на один цикл планувальника.
    # ========================================================

    df = load_module_schedule()

    # Якщо Sheets недоступний —
    # нічого не робимо.
    if df is None:

        logging.warning(
            "Планувальник: "
            "розклад недоступний. "
            "Жодних команд Tuya не виконуємо."
        )

        return [
            "⚠️ Google Sheets тимчасово "
            "недоступний. Планувальник "
            "не виконував жодних команд."
        ]

    df = prepare_dataframe(
        df,
        MODULE_SCHEDULE_COLUMNS,
    )

    if df.empty:
        return results

    # ========================================================
    # 1. ВИМКНЕННЯ
    # ========================================================

    # Працюємо по копії, щоб зміни
    # статусів не ламали ітерацію.
    rows_for_off = [
        row.copy()
        for _, row in df.iterrows()
    ]

    for row in rows_for_off:

        messages = (
            execute_current_record_off(
                df=df,
                row=row,
                now=now,
            )
        )

        results.extend(
            messages
        )

    # ========================================================
    # 2. ЗАПУСКИ
    # ========================================================

    # Після операцій вимкнення df вже містить
    # оновлені статуси, тому повторно читати
    # Google Sheets НЕ потрібно.
    #
    # Якщо запис має власний час 10:57,
    # саме о 10:57 він буде запущений.
    # ========================================================

    rows_for_start = [
        row.copy()
        for _, row in df.iterrows()
    ]

    for index, row in enumerate(
        rows_for_start
    ):

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
            continue

        # ----------------------------------------------------
        # Запускаємо запис у його власний час.
        # ----------------------------------------------------

        if (
            now >= start_dt
            and now < (
                start_dt
                + timedelta(
                    minutes=2
                )
            )
        ):

            success, message = (
                execute_module_schedule_task(
                    df=df,
                    index=index,
                    row=row,
                    now=now,
                )
            )

            if success:

                results.append(
                    message
                )

    # ========================================================
    # ВАЖЛИВО:
    #
    # Окремий "execute_next_record_if_needed"
    # тут більше НЕ потрібен для нормальної роботи.
    #
    # Наступний запис вже має власну дату:
    #
    # 10:57
    #
    # і буде запущений основним механізмом.
    #
    # Це усуває подвійний механізм запуску.
    # ========================================================

    return results


# ============================================================
# STREAMLIT FRAGMENT
# ============================================================

@st.fragment(
    run_every=SCHEDULER_INTERVAL_SECONDS
)
def scheduler_fragment():

    results = run_module_scheduler()

    for message in results:

        if message.startswith("❌"):

            st.error(
                f"⏱️ Планувальник: "
                f"{message}"
            )

        elif message.startswith("⚠️"):

            st.warning(
                f"⏱️ Планувальник: "
                f"{message}"
            )

        else:

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
                (
                    "🟢 Автомат увімкнено."
                    if new_breaker_state
                    else
                    "🔴 Автомат вимкнено."
                )
            )

            time.sleep(
                0.4
            )

            st.rerun()

        else:

            st.error(
                "❌ Не вдалося "
                "змінити стан автомата."
            )


# ============================================================
# РОЗКЛАД МОДУЛІВ
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Розклад роботи модулів"
)


st.caption(
    "Дата та час першого запуску "
    "задаються користувачем. "
    "Наступний модуль автоматично "
    "отримує час запуску за 3 хвилини "
    "до завершення поточного модуля."
)


module_df = load_module_schedule()


# ------------------------------------------------------------
# ВАЖЛИВО:
# Якщо Google Sheets недоступний,
# НЕ показуємо "це перший запис".
# ------------------------------------------------------------

if module_df is None:

    st.error(
        "❌ Розклад модулів тимчасово "
        "недоступний через помилку "
        "Google Sheets."
    )

    st.warning(
        "Автоматичне керування "
        "модулями в цей момент "
        "не виконується."
    )

    st.stop()


module_df = prepare_dataframe(
    module_df,
    MODULE_SCHEDULE_COLUMNS,
)


st.write(
    f"Створено модулів у ланцюжку: "
    f"**{len(module_df)} / {MAX_SCHEDULES}**"
)


# ============================================================
# ДОДАВАННЯ
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
                    "Виберіть дату, час "
                    "та модуль."
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

                module_time = (
                    default_time
                )

                module_name = (
                    default_module
                )

                st.info(
                    f"Автоматично: старт "
                    f"**{format_schedule_datetime(module_time)}**, "
                    f"модуль "
                    f"**{module_name}**."
                )

            action = "Увімкнути"

            duration_hours = (
                st.number_input(
                    "Тривалість, годин",

                    min_value=0.001,
                    max_value=24.0,
                    value=1.0,
                    step=0.001,

                    format="%.3f",
                )
            )

            next_module = (
                st.selectbox(
                    "Наступний модуль",

                    NEXT_MODULE_OPTIONS,

                    index=0,

                    help=(
                        "Наступний модуль "
                        "запускається автоматично "
                        "за 3 хвилини до завершення "
                        "поточного. "
                        "Наприклад: 10:00–11:00, "
                        "наступний старт о 10:57."
                    ),
                )
            )

            st.caption(
                "Активність задається "
                "автоматично."
            )

            submitted = (
                st.form_submit_button(
                    "💾 Додати модуль",

                    use_container_width=True,

                    type="primary",
                )
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

        record_id = safe_text(
            row.get(
                "ID",
                "",
            )
        )

        next_record_id = safe_text(
            row.get(
                "ID наступного запису",
                "",
            )
        )

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

        duration = format_duration(
            row.get(
                "тривалість, годин",
                "",
            )
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

        actual_off_display = safe_text(
            row.get(
                "дата та час фактичного вимкнення",
                "",
            )
        )

        finish_display = safe_text(
            row.get(
                "дата та час завершення",
                "",
            )
        )

        next_start_display = safe_text(
            row.get(
                "дата та час запуску наступного модуля",
                "",
            )
        )

        status_display = safe_text(
            row.get(
                "статус",
                "",
            )
        )

        error_display = safe_text(
            row.get(
                "помилка",
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

                if next_start_display:

                    st.caption(
                        f"Старт наступного: "
                        f"{next_start_display}"
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

            st.caption(
                f"ID: `{record_id}`"
            )

            if next_record_id:

                st.caption(
                    "ID наступного запису: "
                    f"`{next_record_id}`"
                )

            else:

                st.caption(
                    "ID наступного запису: —"
                )

            if finish_display:

                st.caption(
                    "Планове завершення: "
                    f"{finish_display}"
                )

            if next_start_display:

                st.caption(
                    "Плановий запуск наступного: "
                    f"{next_start_display}"
                )

            if status_display:

                st.caption(
                    f"Статус: "
                    f"{status_display}"
                )

            if last_execution:

                st.caption(
                    "Фактичний запуск: "
                    f"{last_execution}"
                )

            if actual_off_display:

                st.caption(
                    "Фактичне вимкнення: "
                    f"{actual_off_display}"
                )

            if error_display:

                st.error(
                    f"Помилка: "
                    f"{error_display}"
                )

            b1, b2, b3 = st.columns(
                3
            )

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
                    normalize_duration(
                        duration
                    )
                )

                if (
                    current_duration
                    is None
                ):

                    current_duration = 1.0

                edit_duration_value = min(
                    max(
                        current_duration,
                        0.001,
                    ),
                    24.0,
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

                            value=(
                                parsed_datetime
                            ),
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

                            min_value=0.001,
                            max_value=24.0,

                            value=(
                                edit_duration_value
                            ),

                            step=0.001,

                            format="%.3f",
                        )
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

                        if update_module_schedule_task(
                            index=index,
                            start_datetime=edit_time,
                            module_name=edit_module,
                            action="Увімкнути",
                            duration_hours=edit_duration,
                            next_module=edit_next,
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
