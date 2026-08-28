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

REQUIRED_SCHEDULE_COLUMNS = [
    "час",
    "дія",
    "дні тижня",
    "активність",
    "дата та час останнього виконання",
    "Свердловина",
]

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
# ОТРИМАННЯ АРКУША
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
            f"`{SCHEDULE_WORKSHEET_NAME}`."
        )

        return None

    except Exception as e:

        st.error(
            "❌ Помилка відкриття аркуша."
        )

        st.code(
            str(e)
        )

        return None


# ============================================================
# СТВОРЕННЯ ПУСТОЇ СТРУКТУРИ
# ============================================================

def empty_schedule_dataframe():

    return pd.DataFrame(
        columns=REQUIRED_SCHEDULE_COLUMNS
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

        return df

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
# ПІДГОТОВКА DATAFRAME
# ============================================================

def prepare_schedule_dataframe(
    df
):

    """
    Гарантує наявність усіх необхідних колонок.
    """

    if df is None or df.empty:

        return empty_schedule_dataframe()

    df = df.copy()

    for column in REQUIRED_SCHEDULE_COLUMNS:

        if column not in df.columns:

            df[column] = ""

    # Правильний порядок колонок
    df = df[
        REQUIRED_SCHEDULE_COLUMNS
    ]

    return df


# ============================================================
# ЗБЕРЕЖЕННЯ РОЗКЛАДУ
# ============================================================

def save_schedule(
    df
):

    try:

        worksheet = get_schedule_worksheet()

        if worksheet is None:

            return False

        df = prepare_schedule_dataframe(
            df
        )

        # Максимум 30 завдань
        if len(df) > MAX_SCHEDULES:

            st.error(
                f"❌ Не можна зберегти більше "
                f"{MAX_SCHEDULES} завдань."
            )

            return False

        # Дані для Google Sheets
        data_to_write = [
            REQUIRED_SCHEDULE_COLUMNS
        ]

        for _, row in df.iterrows():

            data_to_write.append(
                [
                    row.get(
                        "час",
                        ""
                    ),
                    row.get(
                        "дія",
                        ""
                    ),
                    row.get(
                        "дні тижня",
                        ""
                    ),
                    row.get(
                        "активність",
                        ""
                    ),
                    row.get(
                        "дата та час останнього виконання",
                        ""
                    ),
                    row.get(
                        "Свердловина",
                        ""
                    ),
                ]
            )

        # Очищення старого вмісту
        worksheet.clear()

        # Запис нового
        worksheet.update(
            data_to_write,
            "A1"
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

        return False, (
            f"Досягнуто максимуму "
            f"{MAX_SCHEDULES} завдань."
        )

    # Дні записуємо одним текстом
    days_text = ", ".join(
        selected_days
    )

    new_row = {
        "час": schedule_time.strftime(
            "%H:%M"
        ),
        "дія": action,
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

        return True, (
            "Завдання успішно додано."
        )

    return False, (
        "Не вдалося зберегти "
        "завдання."
    )


# ============================================================
# ВИДАЛЕННЯ ЗАВДАННЯ
# ============================================================

def delete_schedule_task(
    index
):

    df = load_schedule()

    df = prepare_schedule_dataframe(
        df
    )

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

    df.at[
        index,
        "час"
    ] = schedule_time.strftime(
        "%H:%M"
    )

    df.at[
        index,
        "дія"
    ] = action

    df.at[
        index,
        "дні тижня"
    ] = ", ".join(
        selected_days
    )

    df.at[
        index,
        "активність"
    ] = (
        "TRUE"
        if active
        else
        "FALSE"
    )

    df.at[
        index,
        "Свердловина"
    ] = str(
        well
    )

    df.at[
        index,
        "дата та час останнього виконання"
    ] = last_execution

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
# ПІДКЛЮЧЕННЯ TUYA
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
# ПОТОЧНИЙ СТАН АВТОМАТА
# ============================================================

def get_switch_state():

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

    Ця функція використовується
    і ручним керуванням,
    і майбутнім планувальником.
    """

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
# ПОТОЧНИЙ СТАН
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
    "Розклад зберігається у Google Таблиці."
)


# ============================================================
# ЗАВАНТАЖУЄМО РОЗКЛАД
# ============================================================

schedule_df = load_schedule()

schedule_df = prepare_schedule_dataframe(
    schedule_df
)


# ============================================================
# КІЛЬКІСТЬ
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

            name_placeholder = (
                "Наприклад: Ранковий полив"
            )

            st.caption(
                "Назва завдання не зберігається "
                "окремою колонкою, тому зараз "
                "вона використовується лише "
                "для зручності під час створення."
            )

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
                        "Вимкнути"
                    ],
                    key="new_schedule_action"
                )

            selected_days = st.multiselect(
                "Дні тижня",
                WEEKDAYS,
                key="new_schedule_days",
                help=(
                    "Якщо не вибрати жодного дня, "
                    "завдання буде виконуватись "
                    "як одноразове."
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

        schedule_time = str(
            row.get(
                "час",
                ""
            )
        )

        action = str(
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

            action_text = (
                "🟢 Увімкнути"
            )

        elif action == "Вимкнути":

            action_text = (
                "🔴 Вимкнути"
            )

        else:

            action_text = action

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
                    f"### {schedule_time}"
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

                edit_key = (
                    f"edit_schedule_"
                    f"{index}"
                )

                if st.button(
                    "✏️ Редагувати",
                    key=edit_key,
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
            # ФОРМА РЕДАГУВАННЯ
            # ------------------------------------------------

            if st.session_state.get(
                f"editing_schedule_{index}",
                False
            ):

                st.markdown(
                    "#### ✏️ Редагування завдання"
                )

                # Час
                try:

                    parsed_time = (
                        datetime.strptime(
                            schedule_time,
                            "%H:%M"
                        ).time()
                    )

                except Exception:

                    parsed_time = dt_time(
                        8,
                        0
                    )

                # Дні
                current_days = []

                if days and days != "Одноразово":

                    for day in WEEKDAYS:

                        if day in days:

                            current_days.append(
                                day
                            )

                # Активність
                edit_active = activity

                # Свердловина
                edit_well = well

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
                            "Вимкнути"
                        ],
                        index=(
                            0
                            if action
                            == "Увімкнути"
                            else
                            1
                        ),
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

                    edit_active_checkbox = (
                        st.checkbox(
                            "Активне",
                            value=edit_active,
                            key=(
                                f"edit_active_"
                                f"{index}"
                            )
                        )
                    )

                    edit_well_select = (
                        st.selectbox(
                            "Свердловина",
                            ["1"],
                            index=0,
                            key=(
                                f"edit_well_"
                                f"{index}"
                            )
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
                                edit_active_checkbox,
                                edit_well_select,
                                last_execution
                            )
                        )

                        if success:

                            st.success(
                                "Зміни збережено."
                            )

                            st.session_state[
                                f"editing_schedule_{index}"
                            ] = False

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
