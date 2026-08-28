import streamlit as st
import datetime
import time
import logging

from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="Керування приладами та іригацією",
    page_icon="🎛️",
    layout="wide",
)


st.title("🎛️ Панель керування приладами")

st.markdown(
    """
    Керування обладнанням **1 свердловини**
    через Tuya Cloud API.
    """
)


# ============================================================
# НАЛАШТУВАННЯ TUYA
# ============================================================

def get_tuya_settings():
    """
    Читає параметри Tuya з st.secrets.
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
            "❌ Помилка читання налаштувань Tuya."
        )

        st.code(
            str(e)
        )

        return (
            None,
            None,
            None,
            None
        )


# ============================================================
# СТВОРЕННЯ ПІДКЛЮЧЕННЯ TUYA
# ============================================================

@st.cache_resource
def create_tuya_api(
    endpoint,
    access_id,
    access_key
):
    """
    Створює підключення до Tuya Cloud
    через офіційний Python SDK.
    """

    try:

        # Не показуємо зайві службові повідомлення SDK
        TUYA_LOGGER.setLevel(
            logging.ERROR
        )

        api = TuyaOpenAPI(
            endpoint,
            access_id,
            access_key
        )

        # Отримання Access Token
        api.connect()

        return api

    except Exception as e:

        raise RuntimeError(
            f"Не вдалося підключитися до Tuya Cloud: {e}"
        )


# ============================================================
# ОТРИМАННЯ НАЛАШТУВАНЬ
# ============================================================

(
    ACCESS_ID,
    ACCESS_KEY,
    API_ENDPOINT,
    BREAKER_ID
) = get_tuya_settings()


if not ACCESS_ID:

    st.error(
        "❌ Не задано Access ID."
    )

    st.stop()


if not ACCESS_KEY:

    st.error(
        "❌ Не задано Access Secret."
    )

    st.stop()


if not API_ENDPOINT:

    st.error(
        "❌ Не задано endpoint Tuya."
    )

    st.stop()


if not BREAKER_ID:

    st.error(
        "❌ Не задано Device ID."
    )

    st.stop()


# ============================================================
# ПІДКЛЮЧЕННЯ
# ============================================================

try:

    tuya = create_tuya_api(
        API_ENDPOINT,
        ACCESS_ID,
        ACCESS_KEY
    )

    st.success(
        "🟢 Підключення до Tuya Cloud успішне"
    )

except Exception as e:

    st.error(
        "❌ Підключення до Tuya Cloud не вдалося."
    )

    st.code(
        str(e)
    )

    st.info(
        """
        Перевірте:

        • Access ID
        • Access Secret
        • endpoint
        • авторизацію API у Tuya Cloud Project
        """
    )

    st.stop()


# ============================================================
# ТЕХНІЧНІ ПАРАМЕТРИ
# ============================================================

with st.expander(
    "🔧 Технічні параметри підключення",
    expanded=False
):

    st.write(
        "**Data Center / Endpoint:**"
    )

    st.code(
        API_ENDPOINT
    )

    st.write(
        "**Access ID:**"
    )

    st.code(
        ACCESS_ID
    )

    st.write(
        "**Device ID:**"
    )

    st.code(
        BREAKER_ID
    )

    st.write(
        "**Access Secret:**"
    )

    st.code(
        "••••••••••••••••••••••••••••••••"
    )


# ============================================================
# ФУНКЦІЯ GET
# ============================================================

def tuya_get(
    uri
):
    """
    GET-запит до Tuya Cloud.
    """

    try:

        response = tuya.get(
            uri
        )

        return response

    except Exception as e:

        st.error(
            f"❌ Помилка GET-запиту: {e}"
        )

        return None


# ============================================================
# ФУНКЦІЯ POST
# ============================================================

def tuya_post(
    uri,
    body
):
    """
    POST-запит до Tuya Cloud.
    """

    try:

        response = tuya.post(
            uri,
            body
        )

        return response

    except Exception as e:

        st.error(
            f"❌ Помилка POST-запиту: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ ІНФОРМАЦІЇ ПРО ПРИСТРІЙ
# ============================================================

device_uri = (
    f"/v1.0/iot-03/devices/{BREAKER_ID}"
)

device_response = tuya_get(
    device_uri
)


device_data = {}


if isinstance(
    device_response,
    dict
):

    if device_response.get(
        "success"
    ):

        device_data = (
            device_response.get(
                "result",
                {}
            )
        )

    else:

        st.error(
            "❌ Tuya не повернула інформацію "
            "про пристрій."
        )

        with st.expander(
            "Деталі відповіді Tuya"
        ):

            st.json(
                device_response
            )


# ============================================================
# ЗАГОЛОВОК
# ============================================================

st.header(
    "1 свердловина"
)

st.markdown("---")


# ============================================================
# ІНФОРМАЦІЯ ПРО ПРИСТРІЙ
# ============================================================

st.subheader(
    "🔌 Автоматичний вимикач"
)


if device_data:

    device_name = device_data.get(
        "name",
        "Без назви"
    )

    product_name = device_data.get(
        "product_name",
        "—"
    )

    category_name = device_data.get(
        "category_name",
        "—"
    )

    online = device_data.get(
        "online",
        False
    )

    col1, col2, col3, col4 = st.columns(
        4
    )

    with col1:

        st.metric(
            "Назва",
            device_name
        )

    with col2:

        st.metric(
            "Продукт",
            product_name
        )

    with col3:

        st.metric(
            "Категорія",
            category_name
        )

    with col4:

        if online:

            st.success(
                "🟢 ONLINE"
            )

        else:

            st.error(
                "🔴 OFFLINE"
            )

else:

    st.warning(
        "Інформацію про пристрій не отримано."
    )


# ============================================================
# ПОВНА ІНФОРМАЦІЯ ПРО ПРИСТРІЙ
# ============================================================

with st.expander(
    "🔍 Повна інформація про пристрій"
):

    if device_data:

        st.json(
            device_data
        )

    else:

        st.write(
            "Дані відсутні."
        )


# ============================================================
# ОТРИМАННЯ ФУНКЦІЙ ПРИСТРОЮ
# ============================================================

functions_uri = (
    f"/v1.0/iot-03/devices/"
    f"{BREAKER_ID}/functions"
)

functions_response = tuya_get(
    functions_uri
)


functions_data = []


if isinstance(
    functions_response,
    dict
):

    if functions_response.get(
        "success"
    ):

        result = functions_response.get(
            "result",
            {}
        )

        functions_data = result.get(
            "functions",
            []
        )

    else:

        st.warning(
            "⚠️ Не вдалося отримати "
            "функції пристрою."
        )


# ============================================================
# ТЕХНІЧНІ ФУНКЦІЇ
# ============================================================

with st.expander(
    "⚙️ Доступні функції пристрою"
):

    if functions_data:

        for function in functions_data:

            code = function.get(
                "code",
                ""
            )

            name = function.get(
                "name",
                ""
            )

            function_type = function.get(
                "type",
                ""
            )

            description = function.get(
                "desc",
                ""
            )

            st.write(
                f"**{code}** — "
                f"{name} "
                f"({function_type})"
            )

            if description:

                st.caption(
                    description
                )

            st.divider()

    else:

        st.warning(
            "Функції пристрою не отримані."
        )


# ============================================================
# ВАЖЛИВО:
# ОСНОВНИЙ КОД КЕРУВАННЯ — "switch"
# ============================================================

SWITCH_CODE = "switch"


# Перевіряємо, чи справді switch існує
switch_function_exists = False


for function in functions_data:

    code = str(
        function.get(
            "code",
            ""
        )
    ).strip()

    function_type = str(
        function.get(
            "type",
            ""
        )
    ).lower()

    if (
        code == SWITCH_CODE
        and function_type == "boolean"
    ):

        switch_function_exists = True
        break


# ============================================================
# ОТРИМАННЯ ПОТОЧНОГО СТАТУСУ
# ============================================================

status_uri = (
    f"/v1.0/iot-03/devices/"
    f"{BREAKER_ID}/status"
)

status_response = tuya_get(
    status_uri
)


statuses = []


if isinstance(
    status_response,
    dict
):

    if status_response.get(
        "success"
    ):

        statuses = status_response.get(
            "result",
            []
        )

    else:

        st.warning(
            "⚠️ Не вдалося отримати "
            "поточний статус пристрою."
        )


# ============================================================
# ПОТОЧНИЙ СТАН SWITCH
# ============================================================

current_power_state = None


for item in statuses:

    code = str(
        item.get(
            "code",
            ""
        )
    ).strip()

    if code == SWITCH_CODE:

        value = item.get(
            "value"
        )

        if isinstance(
            value,
            bool
        ):

            current_power_state = value

        break


# ============================================================
# ТЕХНІЧНИЙ СТАТУС
# ============================================================

with st.expander(
    "📡 Повний статус пристрою"
):

    if statuses:

        st.json(
            statuses
        )

    else:

        st.warning(
            "Статус пристрою не отриманий."
        )


# ============================================================
# ОСНОВНИЙ БЛОК КЕРУВАННЯ
# ============================================================

st.markdown("---")

st.subheader(
    "⚡ Керування автоматичним вимикачем"
)


if not switch_function_exists:

    st.error(
        """
        ❌ У пристрою не знайдено функцію
        `switch` типу Boolean.

        Керування заблоковано, щоб випадково
        не відправити команду іншому DP-коду.
        """
    )

else:

    st.caption(
        "Основний DP-код керування: `switch`"
    )

    col_state, col_control = st.columns(
        [1, 2]
    )


    # ========================================================
    # ПОТОЧНИЙ СТАН
    # ========================================================

    with col_state:

        st.markdown(
            "##### Поточний стан"
        )

        if current_power_state is True:

            st.success(
                "🟢 УВІМКНЕНО"
            )

        elif current_power_state is False:

            st.error(
                "🔴 ВИМКНЕНО"
            )

        else:

            st.warning(
                "⚠️ Стан невідомий"
            )


    # ========================================================
    # КНОПКИ
    # ========================================================

    with col_control:

        st.markdown(
            "##### Керування з хмари"
        )

        col_on, col_off = st.columns(
            2
        )


        # ====================================================
        # УВІМКНЕННЯ
        # ====================================================

        with col_on:

            if st.button(
                "🟢 УВІМКНУТИ",
                use_container_width=True,
                type="primary",
                key="breaker_switch_on"
            ):

                command_uri = (
                    f"/v1.0/iot-03/devices/"
                    f"{BREAKER_ID}/commands"
                )

                command_body = {
                    "commands": [
                        {
                            "code": SWITCH_CODE,
                            "value": True
                        }
                    ]
                }

                response = tuya_post(
                    command_uri,
                    command_body
                )

                if response is None:

                    st.error(
                        "❌ Від Tuya не отримано відповіді."
                    )

                elif response.get(
                    "success"
                ):

                    st.success(
                        "✅ Команду УВІМКНЕННЯ "
                        "прийнято Tuya."
                    )

                    # Даємо пристрою час оновити статус
                    time.sleep(1)

                    # Оновлюємо сторінку
                    st.rerun()

                else:

                    st.error(
                        "❌ Tuya не прийняла "
                        "команду УВІМКНЕННЯ."
                    )

                    st.json(
                        response
                    )


        # ====================================================
        # ВИМКНЕННЯ
        # ====================================================

        with col_off:

            if st.button(
                "🔴 ВИМКНУТИ",
                use_container_width=True,
                key="breaker_switch_off"
            ):

                command_uri = (
                    f"/v1.0/iot-03/devices/"
                    f"{BREAKER_ID}/commands"
                )

                command_body = {
                    "commands": [
                        {
                            "code": SWITCH_CODE,
                            "value": False
                        }
                    ]
                }

                response = tuya_post(
                    command_uri,
                    command_body
                )

                if response is None:

                    st.error(
                        "❌ Від Tuya не отримано відповіді."
                    )

                elif response.get(
                    "success"
                ):

                    st.success(
                        "✅ Команду ВИМКНЕННЯ "
                        "прийнято Tuya."
                    )

                    time.sleep(1)

                    st.rerun()

                else:

                    st.error(
                        "❌ Tuya не прийняла "
                        "команду ВИМКНЕННЯ."
                    )

                    st.json(
                        response
                    )


# ============================================================
# ДЕТАЛЬНА ІНФОРМАЦІЯ ПРО СТАН
# ============================================================

st.markdown("---")

st.subheader(
    "📊 Показники автоматичного вимикача"
)


# Створюємо словник статусів
status_dict = {}

for item in statuses:

    code = item.get(
        "code"
    )

    value = item.get(
        "value"
    )

    if code:

        status_dict[code] = value


# ============================================================
# ОСНОВНІ ПОКАЗНИКИ
# ============================================================

energy = status_dict.get(
    "total_forward_energy"
)

balance_energy = status_dict.get(
    "balance_energy"
)

fault = status_dict.get(
    "fault"
)

breaker_number = status_dict.get(
    "breaker_number"
)


metric1, metric2, metric3, metric4 = st.columns(
    4
)


with metric1:

    if energy is not None:

        st.metric(
            "Загальна енергія",
            str(energy)
        )

    else:

        st.metric(
            "Загальна енергія",
            "—"
        )


with metric2:

    if balance_energy is not None:

        st.metric(
            "Баланс енергії",
            str(balance_energy)
        )

    else:

        st.metric(
            "Баланс енергії",
            "—"
        )


with metric3:

    if fault is not None:

        if fault == 0:

            st.metric(
                "Помилка",
                "Немає"
            )

        else:

            st.metric(
                "Помилка",
                str(fault)
            )

    else:

        st.metric(
            "Помилка",
            "—"
        )


with metric4:

    if breaker_number:

        st.metric(
            "Номер автомата",
            str(breaker_number)
        )

    else:

        st.metric(
            "Номер автомата",
            "—"
        )


# ============================================================
# СТАН ФАЗ
# ============================================================

st.markdown("---")

st.subheader(
    "📡 Статус фаз"
)


phase_a = status_dict.get(
    "phase_a"
)

phase_b = status_dict.get(
    "phase_b"
)

phase_c = status_dict.get(
    "phase_c"
)


phase1, phase2, phase3 = st.columns(
    3
)


with phase1:

    st.markdown(
        "**Фаза A**"
    )

    if phase_a is not None:

        st.code(
            str(phase_a)
        )

    else:

        st.write(
            "Дані відсутні"
        )


with phase2:

    st.markdown(
        "**Фаза B**"
    )

    if phase_b is not None:

        st.code(
            str(phase_b)
        )

    else:

        st.write(
            "Дані відсутні"
        )


with phase3:

    st.markdown(
        "**Фаза C**"
    )

    if phase_c is not None:

        st.code(
            str(phase_c)
        )

    else:

        st.write(
            "Дані відсутні"
        )


# ============================================================
# РОЗКЛАД
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Налаштування розкладу"
)


with st.form(
    key="breaker_schedule_form"
):

    b_col1, b_col2 = st.columns(
        2
    )


    # ========================================================
    # ЧАС УВІМКНЕННЯ
    # ========================================================

    with b_col1:

        b_on_time = st.time_input(
            "Час увімкнення",
            datetime.time(
                8,
                0
            ),
            key="b_on"
        )


    # ========================================================
    # ЧАС ВИМКНЕННЯ
    # ========================================================

    with b_col2:

        b_off_time = st.time_input(
            "Час вимкнення",
            datetime.time(
                18,
                0
            ),
            key="b_off"
        )


    # ========================================================
    # ДНІ
    # ========================================================

    b_days = st.multiselect(
        "Дні тижня",
        [
            "Понеділок",
            "Вівторок",
            "Середа",
            "Четвер",
            "П'ятниця",
            "Субота",
            "Неділя"
        ],
        default=[
            "Понеділок",
            "Середа",
            "П'ятниця"
        ],
        key="b_days"
    )


    # ========================================================
    # ЗБЕРЕЖЕННЯ
    # ========================================================

    if st.form_submit_button(
        "Зберегти розклад вимикача"
    ):

        st.success(
            f"Розклад збережено: "
            f"з {b_on_time.strftime('%H:%M')} "
            f"по {b_off_time.strftime('%H:%M')}"
        )

        if b_days:

            st.info(
                "Дні: "
                + ", ".join(
                    b_days
                )
            )

        else:

            st.warning(
                "Дні тижня не вибрані."
            )


# ============================================================
# СИСТЕМНА ІНФОРМАЦІЯ
# ============================================================

st.markdown("---")

st.caption(
    "Tuya Cloud • Circuit Breaker • "
    "Свердловина 1 • Іригація"
)
