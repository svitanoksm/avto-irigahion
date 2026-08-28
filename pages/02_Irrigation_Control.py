import streamlit as st
import pandas as pd
import time
import logging
import gspread

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

# ============================================================
# GOOGLE SHEETS
# ============================================================

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1qF-7THB566lqOyQV0f6xuB052IRHh8s4CHMUpuN82P4/"
    "edit"
)

SCHEDULE_WORKSHEET_NAME = (
    "Розклад для керування Свердловинами"
)


# Обов'язкові колонки розкладу
REQUIRED_SCHEDULE_COLUMNS = [
    "час",
    "дія",
    "дні тижня",
    "активність",
    "дата та час останнього виконання",
    "Свердловина",
]


# ============================================================
# GOOGLE SHEETS — ПІДКЛЮЧЕННЯ
# ============================================================

@st.cache_resource
def init_google_sheets():
    """
    Підключення до Google Sheets
    через service account із st.secrets.
    """

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    try:

        if "gcp_service_account" not in st.secrets:

            st.error(
                "❌ У st.secrets не знайдено "
                "`gcp_service_account`."
            )

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
# GOOGLE SHEETS — ЧИТАННЯ РОЗКЛАДУ
# ============================================================

def load_schedule():

    """
    Завантажує розклад із Google Sheets.

    Аркуш:
    Розклад для керування Свердловинами
    """

    try:

        spreadsheet = init_google_sheets()

        if spreadsheet is None:

            return pd.DataFrame()

        worksheet = spreadsheet.worksheet(
            SCHEDULE_WORKSHEET_NAME
        )

        records = worksheet.get_all_records()

        df = pd.DataFrame(
            records
        )

        return df

    except gspread.WorksheetNotFound:

        st.error(
            "❌ Не знайдено аркуш "
            f"`{SCHEDULE_WORKSHEET_NAME}`."
        )

        return pd.DataFrame()

    except Exception as e:

        st.error(
            "❌ Помилка завантаження "
            "розкладу з Google Таблиці."
        )

        st.code(
            str(e)
        )

        return pd.DataFrame()


# ============================================================
# ПЕРЕВІРКА СТРУКТУРИ РОЗКЛАДУ
# ============================================================

def validate_schedule_columns(
    df
):

    """
    Перевіряє наявність усіх необхідних колонок.
    """

    if df.empty:

        return False

    missing_columns = [
        column
        for column
        in REQUIRED_SCHEDULE_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:

        st.error(
            "❌ У аркуші розкладу "
            "відсутні необхідні колонки:"
        )

        for column in missing_columns:

            st.write(
                f"• `{column}`"
            )

        st.info(
            "Перевірте назви заголовків "
            "у першому рядку Google Таблиці."
        )

        return False

    return True


# ============================================================
# TUYA — НАЛАШТУВАННЯ
# ============================================================

def get_tuya_settings():

    """
    Отримання налаштувань Tuya
    зі st.secrets.
    """

    try:

        conf = st.secrets["tuya"]

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

    """
    Створення підключення
    до Tuya Cloud.
    """

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
# ПАРАМЕТРИ TUYA
# ============================================================

(
    ACCESS_ID,
    ACCESS_KEY,
    API_ENDPOINT,
    BREAKER_ID
) = get_tuya_settings()


# ============================================================
# ПІДКЛЮЧЕННЯ ДО TUYA
# ============================================================

try:

    tuya = create_tuya_api(
        API_ENDPOINT,
        ACCESS_ID,
        ACCESS_KEY
    )

except Exception as e:

    st.error(
        "❌ Не вдалося підключитися "
        "до Tuya Cloud."
    )

    st.code(
        str(e)
    )

    st.stop()


# ============================================================
# TUYA GET
# ============================================================

def tuya_get(
    uri
):

    """
    GET-запит до Tuya.
    """

    try:

        return tuya.get(
            uri
        )

    except Exception as e:

        st.error(
            f"Помилка Tuya GET: {e}"
        )

        return None


# ============================================================
# TUYA POST
# ============================================================

def tuya_post(
    uri,
    body
):

    """
    POST-запит до Tuya.
    """

    try:

        return tuya.post(
            uri,
            body
        )

    except Exception as e:

        st.error(
            f"Помилка Tuya POST: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ ПОТОЧНОГО СТАНУ АВТОМАТА
# ============================================================

def get_switch_state():

    """
    Отримує реальний стан DP switch.
    """

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
        "success"
    ):

        return None

    statuses = response.get(
        "result",
        []
    )

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
    Вмикає або вимикає автомат.

    Саме ця функція буде використана
    планувальником у наступному етапі.
    """

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/commands"
    )

    body = {
        "commands": [
            {
                "code": SWITCH_CODE,
                "value": bool(state)
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
# ДОПОМІЖНА ФУНКЦІЯ
# ============================================================

def normalize_activity(
    value
):

    """
    Перетворює значення активності
    з Google Sheets у True / False.

    Підтримує:
    TRUE
    FALSE
    True
    False
    Так
    Ні
    1
    0
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

    active_values = [
        "true",
        "1",
        "так",
        "активне",
        "активна",
        "активний",
        "yes",
        "on",
    ]

    return text in active_values


# ============================================================
# НОРМАЛІЗАЦІЯ НОМЕРА СВЕРДЛОВИНИ
# ============================================================

def normalize_well_number(
    value
):

    """
    Перетворює значення поля
    'Свердловина' на номер.

    Підтримує:

    1
    "1"
    "Свердловина 1"
    "свердловина 1"
    """

    if value is None:

        return None

    text = str(
        value
    ).strip()

    if not text:

        return None

    if text.isdigit():

        return text

    lower_text = text.lower()

    if (
        lower_text.startswith(
            "свердловина"
        )
    ):

        number = (
            text
            .replace(
                "Свердловина",
                ""
            )
            .replace(
                "свердловина",
                ""
            )
            .strip()
        )

        if number.isdigit():

            return number

    return text


# ============================================================
# ВІДОБРАЖЕННЯ СТАНУ АВТОМАТА
# ============================================================

current_state = get_switch_state()


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
# ПОТОЧНИЙ СТАН
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
                    0.5
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
                    0.5
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
    "Розклад зберігається у Google Таблиці. "
    f"Максимальна кількість завдань: "
    f"{MAX_SCHEDULES}."
)


# ============================================================
# ЗАВАНТАЖЕННЯ РОЗКЛАДУ
# ============================================================

with st.spinner(
    "Завантаження розкладу..."
):

    schedule_df = load_schedule()


# ============================================================
# ПЕРЕВІРКА РОЗКЛАДУ
# ============================================================

if schedule_df.empty:

    st.info(
        "📋 У аркуші розкладу поки немає "
        "жодного завдання."
    )

else:

    columns_are_valid = (
        validate_schedule_columns(
            schedule_df
        )
    )

    if columns_are_valid:

        # ----------------------------------------------------
        # ОБМЕЖЕННЯ 30 ЗАВДАНЬ
        # ----------------------------------------------------

        if len(schedule_df) > MAX_SCHEDULES:

            st.warning(
                f"У таблиці знайдено "
                f"{len(schedule_df)} рядків. "
                f"Планувальник використовуватиме "
                f"максимум перші "
                f"{MAX_SCHEDULES}."
            )

            schedule_df = schedule_df.head(
                MAX_SCHEDULES
            )

        # ----------------------------------------------------
        # КІЛЬКІСТЬ
        # ----------------------------------------------------

        st.write(
            f"Завдань: "
            f"**{len(schedule_df)} / "
            f"{MAX_SCHEDULES}**"
        )

        # ----------------------------------------------------
        # ПЕРЕВІРКА СВЕРДЛОВИН
        # ----------------------------------------------------

        schedule_df["_well_number"] = (
            schedule_df[
                "Свердловина"
            ].apply(
                normalize_well_number
            )
        )

        # ----------------------------------------------------
        # ПЕРЕВІРКА АКТИВНОСТІ
        # ----------------------------------------------------

        schedule_df["_active"] = (
            schedule_df[
                "активність"
            ].apply(
                normalize_activity
            )
        )

        # ----------------------------------------------------
        # ПОКАЗУЄМО ТАБЛИЦЮ
        # ----------------------------------------------------

        display_columns = [
            "час",
            "дія",
            "дні тижня",
            "активність",
            "дата та час останнього виконання",
            "Свердловина",
        ]

        display_df = schedule_df[
            display_columns
        ].copy()

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        # ----------------------------------------------------
        # ІНФОРМАЦІЯ ПРО СВЕРДЛОВИНИ
        # ----------------------------------------------------

        st.markdown(
            "#### 🔎 Перевірка завдань"
        )

        for index, row in schedule_df.iterrows():

            well_number = row[
                "_well_number"
            ]

            active = row[
                "_active"
            ]

            schedule_time = row[
                "час"
            ]

            action = row[
                "дія"
            ]

            days = row[
                "дні тижня"
            ]

            last_execution = row[
                "дата та час останнього виконання"
            ]

            if active:

                status_icon = "🟢"

            else:

                status_icon = "⏸️"

            st.write(
                f"{status_icon} "
                f"**Завдання {index + 1}** — "
                f"Свердловина {well_number} — "
                f"{schedule_time} — "
                f"{action} — "
                f"{days}"
            )

            if last_execution:

                st.caption(
                    "Останнє виконання: "
                    f"{last_execution}"
                )

        # ----------------------------------------------------
        # ДЛЯ ДІАГНОСТИКИ
        # ----------------------------------------------------

        with st.expander(
            "🔧 Технічна інформація про розклад"
        ):

            st.write(
                "Назва аркуша:"
            )

            st.code(
                SCHEDULE_WORKSHEET_NAME
            )

            st.write(
                "Знайдені колонки:"
            )

            st.code(
                "\n".join(
                    schedule_df.columns.tolist()
                )
            )

            st.write(
                "Розпізнані номери свердловин:"
            )

            st.write(
                schedule_df[
                    "_well_number"
                ].tolist()
            )

            st.write(
                "Розпізнана активність:"
            )

            st.write(
                schedule_df[
                    "_active"
                ].tolist()
            )


# ============================================================
# ОНОВЛЕННЯ
# ============================================================

st.markdown("---")

if st.button(
    "🔄 Оновити стан і розклад",
    use_container_width=True
):

    st.rerun()
