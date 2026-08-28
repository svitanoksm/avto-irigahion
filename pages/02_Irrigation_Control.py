```python
import streamlit as st
import pandas as pd
import gspread
import datetime
import time
import logging

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

SCHEDULE_SHEET_NAME = "Розклад для керування Свердловинами"

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1qF-7THB566lqOyQV0f6xuB052IRHh8s4CHMUpuN82P4/"
    "edit"
)


WEEKDAYS = [
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
]


REQUIRED_COLUMNS = [
    "час",
    "дія",
    "дні тижня",
    "активність",
    "дата та час останнього виконання",
    "Свердловина",
]


# ============================================================
# TUYA — НАЛАШТУВАННЯ
# ============================================================

def get_tuya_settings():

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
            "❌ Не вдалося прочитати налаштування Tuya."
        )

        st.code(str(e))

        st.stop()


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


(
    ACCESS_ID,
    ACCESS_KEY,
    API_ENDPOINT,
    BREAKER_ID
) = get_tuya_settings()


try:

    tuya = create_tuya_api(
        API_ENDPOINT,
        ACCESS_ID,
        ACCESS_KEY
    )

except Exception as e:

    st.error(
        "❌ Не вдалося підключитися до Tuya Cloud."
    )

    st.code(str(e))

    st.stop()


# ============================================================
# TUYA GET
# ============================================================

def tuya_get(uri):

    try:

        return tuya.get(uri)

    except Exception as e:

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
            f"Помилка надсилання команди Tuya: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ ПОТОЧНОГО СТАНУ
# ============================================================

def get_switch_state():

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/status"
    )

    response = tuya_get(uri)

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

        if not isinstance(
            item,
            dict
        ):
            continue

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
# КОМАНДА УВІМКНУТИ / ВИМКНУТИ
# ============================================================

def set_switch_state(
    state
):

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
# GOOGLE SHEETS
# ============================================================

@st.cache_resource
def init_google_sheets():

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if "gcp_service_account" not in st.secrets:

        return None

    creds_dict = dict(
        st.secrets["gcp_service_account"]
    )

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=scope
    )

    client = gspread.authorize(
        creds
    )

    return client.open_by_url(
        SPREADSHEET_URL
    )


# ============================================================
# ОТРИМАННЯ АРКУША РОЗКЛАДУ
# ============================================================

def get_schedule_worksheet():

    try:

        sh = init_google_sheets()

        if not sh:

            return None

        try:

            worksheet = sh.worksheet(
                SCHEDULE_SHEET_NAME
            )

        except Exception:

            worksheet = sh.add_worksheet(
                title=SCHEDULE_SHEET_NAME,
                rows=100,
                cols=len(REQUIRED_COLUMNS)
            )

            worksheet.update(
                "A1",
                [REQUIRED_COLUMNS]
            )

        return worksheet

    except Exception as e:

        st.error(
            "❌ Не вдалося підключитися "
            "до аркуша розкладу."
        )

        st.code(str(e))

        return None


# ============================================================
# ЗАВАНТАЖЕННЯ РОЗКЛАДУ
# ============================================================

def load_schedule():

    worksheet = get_schedule_worksheet()

    if worksheet is None:

        return pd.DataFrame(
            columns=REQUIRED_COLUMNS
        )

    try:

        values = worksheet.get_all_values()

        if not values:

            worksheet.update(
                "A1",
                [REQUIRED_COLUMNS]
            )

            return pd.DataFrame(
                columns=REQUIRED_COLUMNS
            )

        headers = values[0]

        # ----------------------------------------------------
        # Якщо якихось колонок немає — додаємо їх
        # ----------------------------------------------------

        changed = False

        for column in REQUIRED_COLUMNS:

            if column not in headers:

                headers.append(column)

                changed = True

        if changed:

            worksheet.update(
                "A1",
                [headers]
            )

            values = worksheet.get_all_values()

        if len(values) <= 1:

            return pd.DataFrame(
                columns=headers
            )

        df = pd.DataFrame(
            values[1:],
            columns=headers
        )

        # ----------------------------------------------------
        # Залишаємо тільки перші 30 завдань
        # ----------------------------------------------------

        df = df.head(
            MAX_SCHEDULES
        )

        return df

    except Exception as e:

        st.error(
            "❌ Помилка читання розкладу."
        )

        st.code(str(e))

        return pd.DataFrame(
            columns=REQUIRED_COLUMNS
        )


# ============================================================
# ЗБЕРЕЖЕННЯ РОЗКЛАДУ
# ============================================================

def save_schedule(df):

    worksheet = get_schedule_worksheet()

    if worksheet is None:

        return False

    try:

        # ----------------------------------------------------
        # Гарантуємо наявність усіх колонок
        # ----------------------------------------------------

        for column in REQUIRED_COLUMNS:

            if column not in df.columns:

                df[column] = ""

        df = df[
            REQUIRED_COLUMNS
        ]

        df = df.fillna("")

        data = [
            REQUIRED_COLUMNS
        ]

        for _, row in df.iterrows():

            data.append(
                [
                    str(row[column])
                    for column in REQUIRED_COLUMNS
                ]
            )

        worksheet.clear()

        worksheet.update(
            "A1",
            data
        )

        return True

    except Exception as e:

        st.error(
            "❌ Помилка збереження розкладу."
        )

        st.code(str(e))

        return False


# ============================================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ============================================================

def normalize_action(value):

    text = str(
        value
    ).strip().lower()

    if text in [
        "увімкнути",
        "включити",
        "on",
        "true",
        "1",
        "🟢 увімкнути",
        "🟢 увімкнути",
    ]:

        return "Увімкнути"

    if text in [
        "вимкнути",
        "відключити",
        "off",
        "false",
        "0",
        "🔴 вимкнути",
        "🔴 вимкнути",
    ]:

        return "Вимкнути"

    return text.capitalize()


def normalize_activity(value):

    text = str(
        value
    ).strip().lower()

    if text in [
        "",
        "true",
        "1",
        "так",
        "активне",
        "активна",
        "active",
        "yes",
        "🟢 активне",
    ]:

        return True

    if text in [
        "false",
        "0",
        "ні",
        "неактивне",
        "неактивна",
        "inactive",
        "no",
        "⏸️ вимкнене",
    ]:

        return False

    return True


def normalize_days(value):

    if value is None:

        return []

    text = str(
        value
    ).strip()

    if not text:

        return []

    if text.lower() in [
        "одноразово",
        "разово",
    ]:

        return []

    result = []

    for day in WEEKDAYS:

        if day in text:

            result.append(day)

    return result


def days_to_text(days):

    if not days:

        return "Одноразово"

    return ", ".join(days)


def parse_time(value):

    if isinstance(
        value,
        datetime.time
    ):

        return value

    text = str(
        value
    ).strip()

    if not text:

        return None

    formats = [
        "%H:%M",
        "%H:%M:%S",
    ]

    for fmt in formats:

        try:

            return datetime.datetime.strptime(
                text,
                fmt
            ).time()

        except ValueError:

            pass

    return None


def current_weekday_name():

    return WEEKDAYS[
        datetime.datetime.now().weekday()
    ]


# ============================================================
# ПЕРЕВІРКА — ЧИ ТРЕБА ВИКОНАТИ ЗАВДАННЯ
# ============================================================

def should_execute_schedule(
    row
):

    activity = normalize_activity(
        row.get(
            "активність",
            ""
        )
    )

    if not activity:

        return False

    task_time = parse_time(
        row.get(
            "час",
            ""
        )
    )

    if task_time is None:

        return False

    now = datetime.datetime.now()

    # --------------------------------------------------------
    # Перевіряємо годину та хвилину
    # --------------------------------------------------------

    if now.hour != task_time.hour:

        return False

    if now.minute != task_time.minute:

        return False

    # --------------------------------------------------------
    # Перевіряємо день
    # --------------------------------------------------------

    selected_days = normalize_days(
        row.get(
            "дні тижня",
            ""
        )
    )

    today_name = current_weekday_name()

    # --------------------------------------------------------
    # Повторюване завдання
    # --------------------------------------------------------

    if selected_days:

        if today_name not in selected_days:

            return False

    # --------------------------------------------------------
    # Одноразове завдання
    # --------------------------------------------------------

    else:

        last_execution = str(
            row.get(
                "дата та час останнього виконання",
                ""
            )
        ).strip()

        # Якщо вже виконувалося —
        # вдруге не виконуємо.
        if last_execution:

            try:

                last_dt = datetime.datetime.fromisoformat(
                    last_execution
                )

                if (
                    last_dt.date()
                    == now.date()
                ):

                    return False

            except Exception:

                pass

    # --------------------------------------------------------
    # Захист від повторного виконання
    # --------------------------------------------------------

    last_execution = str(
        row.get(
            "дата та час останнього виконання",
            ""
        )
    ).strip()

    if last_execution:

        try:

            last_dt = datetime.datetime.fromisoformat(
                last_execution
            )

            difference = (
                now - last_dt
            ).total_seconds()

            # Не дозволяємо повторно
            # виконувати завдання протягом
            # 60 секунд.
            if difference < 60:

                return False

        except Exception:

            pass

    return True


# ============================================================
# ВИКОНАННЯ РОЗКЛАДУ
# ============================================================

def execute_schedules(
    df
):

    if df.empty:

        return df, False

    changed = False

    now = datetime.datetime.now()

    for index in range(
        len(df)
    ):

        row = df.iloc[
            index
        ]

        if not should_execute_schedule(
            row
        ):

            continue

        action = normalize_action(
            row.get(
                "дія",
                ""
            )
        )

        # ----------------------------------------------------
        # Визначаємо команду
        # ----------------------------------------------------

        if action == "Увімкнути":

            target_state = True

        elif action == "Вимкнути":

            target_state = False

        else:

            continue

        # ----------------------------------------------------
        # Виконуємо команду Tuya
        # ----------------------------------------------------

        success = set_switch_state(
            target_state
        )

        if success:

            timestamp = now.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            df.at[
                index,
                "дата та час останнього виконання"
            ] = timestamp

            changed = True

    return df, changed


# ============================================================
# ЗАВАНТАЖЕННЯ РОЗКЛАДУ
# ============================================================

schedule_df = load_schedule()


# ============================================================
# АВТОМАТИЧНИЙ ЗАПУСК РОЗКЛАДУ
# ============================================================

schedule_df, schedule_changed = execute_schedules(
    schedule_df
)

if schedule_changed:

    save_schedule(
        schedule_df
    )


# ============================================================
# ІНТЕРФЕЙС
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

current_state = get_switch_state()

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

            if set_switch_state(
                True
            ):

                st.success(
                    "Автомат увімкнено."
                )

                time.sleep(
                    0.5
                )

                st.rerun()

            else:

                st.error(
                    "Не вдалося увімкнути автомат."
                )

    with off_col:

        if st.button(
            "🔴 ВИМКНУТИ",
            use_container_width=True,
            key="main_switch_off"
        ):

            if set_switch_state(
                False
            ):

                st.success(
                    "Автомат вимкнено."
                )

                time.sleep(
                    0.5
                )

                st.rerun()

            else:

                st.error(
                    "Не вдалося вимкнути автомат."
                )


# ============================================================
# РОЗКЛАД
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Розклад роботи"
)

st.caption(
    f"Максимальна кількість завдань: {MAX_SCHEDULES}"
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
                    "Час",
                    value=datetime.time(
                        8,
                        0
                    )
                )

            with col2:

                action = st.selectbox(
                    "Дія",
                    [
                        "Увімкнути",
                        "Вимкнути"
                    ]
                )

            selected_days = st.multiselect(
                "Дні тижня",
                WEEKDAYS,
                help=(
                    "Якщо не вибрати день, "
                    "завдання буде одноразовим."
                )
            )

            active = st.checkbox(
                "Завдання активне",
                value=True
            )

            well = st.selectbox(
                "Свердловина",
                [
                    "Свердловина 1",
                    "Свердловина 2",
                    "Свердловина 3",
                    "Інша"
                ]
            )

            submitted = st.form_submit_button(
                "💾 Додати завдання",
                use_container_width=True,
                type="primary"
            )

            if submitted:

                new_row = {
                    "час": schedule_time.strftime(
                        "%H:%M"
                    ),

                    "дія": action,

                    "дні тижня": days_to_text(
                        selected_days
                    ),

                    "активність": (
                        "Так"
                        if active
                        else
                        "Ні"
                    ),

                    "дата та час останнього виконання": "",

                    "Свердловина": well,
                }

                schedule_df = pd.concat(
                    [
                        schedule_df,
                        pd.DataFrame(
                            [new_row]
                        )
                    ],
                    ignore_index=True
                )

                if save_schedule(
                    schedule_df
                ):

                    st.success(
                        "✅ Завдання додано до розкладу."
                    )

                    time.sleep(
                        0.5
                    )

                    st.rerun()

                else:

                    st.error(
                        "❌ Не вдалося зберегти завдання."
                    )

else:

    st.warning(
        f"Досягнуто ліміт у {MAX_SCHEDULES} завдань."
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
        "У розкладі поки немає жодного завдання."
    )

else:

    for index in range(
        len(schedule_df)
    ):

        row = schedule_df.iloc[
            index
        ]

        task_time = str(
            row.get(
                "час",
                ""
            )
        )

        action = normalize_action(
            row.get(
                "дія",
                ""
            )
        )

        days = normalize_days(
            row.get(
                "дні тижня",
                ""
            )
        )

        activity = normalize_activity(
            row.get(
                "активність",
                ""
            )
        )

        last_execution = str(
            row.get(
                "дата та час останнього виконання",
                ""
            )
        ).strip()

        well = str(
            row.get(
                "Свердловина",
                "Свердловина 1"
            )
        ).strip()

        if not well:

            well = "Свердловина 1"

        # ----------------------------------------------------
        # Контейнер завдання
        # ----------------------------------------------------

        with st.container(
            border=True
        ):

            c1, c2, c3, c4 = st.columns(
                [0.7, 1.4, 2.2, 1.4]
            )

            with c1:

                st.markdown(
                    f"### {index + 1}"
                )

            with c2:

                st.markdown(
                    f"### {task_time}"
                )

                if action == "Увімкнути":

                    st.caption(
                        "🟢 Увімкнути"
                    )

                elif action == "Вимкнути":

                    st.caption(
                        "🔴 Вимкнути"
                    )

            with c3:

                st.markdown(
                    f"**{well}**"
                )

                if days:

                    st.caption(
                        ", ".join(days)
                    )

                else:

                    st.caption(
                        "Одноразове завдання"
                    )

            with c4:

                if activity:

                    st.success(
                        "🟢 Активне"
                    )

                else:

                    st.warning(
                        "⏸️ Вимкнене"
                    )

            # ------------------------------------------------
            # Останнє виконання
            # ------------------------------------------------

            if last_execution:

                st.caption(
                    "Останнє виконання: "
                    f"{last_execution}"
                )

            else:

                st.caption(
                    "Останнє виконання: ще не виконувалось"
                )

            # ------------------------------------------------
            # Кнопки
            # ------------------------------------------------

            b1, b2, b3 = st.columns(
                3
            )

            with b1:

                if st.button(
                    (
                        "⏸️ Вимкнути"
                        if activity
                        else
                        "▶️ Увімкнути"
                    ),
                    key=f"activity_{index}",
                    use_container_width=True
                ):

                    schedule_df.at[
                        index,
                        "активність"
                    ] = (
                        "Ні"
                        if activity
                        else
                        "Так"
                    )

                    if save_schedule(
                        schedule_df
                    ):

                        st.rerun()

            with b2:

                if st.button(
                    "▶️ Виконати зараз",
                    key=f"execute_{index}",
                    use_container_width=True
                ):

                    if action == "Увімкнути":

                        target_state = True

                    elif action == "Вимкнути":

                        target_state = False

                    else:

                        target_state = None

                    if target_state is None:

                        st.error(
                            "Невідома дія."
                        )

                    else:

                        success = set_switch_state(
                            target_state
                        )

                        if success:

                            timestamp = (
                                datetime.datetime.now()
                                .strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )
                            )

                            schedule_df.at[
                                index,
                                "дата та час останнього виконання"
                            ] = timestamp

                            save_schedule(
                                schedule_df
                            )

                            st.success(
                                "Команду виконано."
                            )

                            time.sleep(
                                0.5
                            )

                            st.rerun()

                        else:

                            st.error(
                                "Не вдалося виконати команду."
                            )

            with b3:

                if st.button(
                    "🗑️ Видалити",
                    key=f"delete_{index}",
                    use_container_width=True
                ):

                    schedule_df = schedule_df.drop(
                        index
                    ).reset_index(
                        drop=True
                    )

                    if save_schedule(
                        schedule_df
                    ):

                        st.success(
                            "Завдання видалено."
                        )

                        time.sleep(
                            0.5
                        )

                        st.rerun()


# ============================================================
# РУЧНЕ ОНОВЛЕННЯ
# ============================================================

st.markdown("---")

if st.button(
    "🔄 Оновити стан і перевірити розклад",
    use_container_width=True
):

    st.rerun()
```
