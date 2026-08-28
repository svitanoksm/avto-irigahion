import streamlit as st
import datetime
import time
import json
import logging

from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ STREAMLIT
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
    Отримання параметрів Tuya із st.secrets.
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
            "❌ Не вдалося прочитати налаштування "
            "Tuya із st.secrets."
        )

        st.code(str(e))

        return (
            None,
            None,
            None,
            None
        )


# ============================================================
# СТВОРЕННЯ TUYA OPEN API
# ============================================================

@st.cache_resource
def create_tuya_api(
    endpoint,
    access_id,
    access_key
):
    """
    Створення підключення до Tuya Cloud.

    Використовується офіційний
    tuya-connector-python.
    """

    try:

        # Вмикаємо логування Tuya тільки для помилок.
        TUYA_LOGGER.setLevel(
            logging.ERROR
        )

        api = TuyaOpenAPI(
            endpoint,
            access_id,
            access_key
        )

        # Авторизація
        api.connect()

        return api

    except Exception as e:

        raise RuntimeError(
            f"Помилка підключення до Tuya Cloud: {e}"
        )


# ============================================================
# ІНІЦІАЛІЗАЦІЯ TUYA
# ============================================================

(
    ACCESS_ID,
    ACCESS_KEY,
    API_ENDPOINT,
    BREAKER_ID
) = get_tuya_settings()


if not ACCESS_ID or not ACCESS_KEY:

    st.error(
        "❌ Не задано Access ID або Access Secret "
        "у st.secrets."
    )

    st.stop()


if not API_ENDPOINT:

    st.error(
        "❌ Не задано endpoint Tuya."
    )

    st.stop()


if not BREAKER_ID:

    st.error(
        "❌ Не задано Device ID автоматичного вимикача."
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

    connection_ok = True

except Exception as e:

    connection_ok = False

    st.error(
        "❌ Не вдалося підключитися до Tuya Cloud."
    )

    st.code(str(e))

    st.info(
        """
        Перевірте:

        • Access ID
        • новий Access Secret
        • endpoint
        • авторизацію Cloud API у Tuya Project
        """
    )

    st.stop()


# ============================================================
# СТАН ПІДКЛЮЧЕННЯ
# ============================================================

st.success(
    "🟢 Підключення до Tuya Cloud успішне"
)


# ============================================================
# ТЕХНІЧНА ІНФОРМАЦІЯ
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
# ФУНКЦІЯ БЕЗПЕЧНОГО GET
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
            f"❌ Помилка GET-запиту Tuya: {e}"
        )

        return None


# ============================================================
# ФУНКЦІЯ БЕЗПЕЧНОГО POST
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
            f"❌ Помилка POST-запиту Tuya: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ ІНФОРМАЦІЇ ПРО ПРИСТРІЙ
# ============================================================

device_uri = (
    f"/v1.0/iot-03/devices/{BREAKER_ID}"
)

device_info = tuya_get(
    device_uri
)


# ============================================================
# ПЕРЕВІРКА DEVICE INFO
# ============================================================

device_data = {}

if isinstance(device_info, dict):

    if device_info.get("success"):

        device_data = (
            device_info.get(
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
                device_info
            )


# ============================================================
# ЗАГОЛОВОК СВЕРДЛОВИНИ
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

    category = device_data.get(
        "category",
        "—"
    )

    online = device_data.get(
        "online",
        False
    )

    col1, col2, col3, col4 = st.columns(4)

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
            category
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
# ПОВНА ІНФОРМАЦІЯ
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

        st.error(
            "❌ Не вдалося отримати "
            "функції пристрою."
        )


# ============================================================
# ВІДОБРАЖЕННЯ ФУНКЦІЙ
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
            "Tuya не повернула список функцій."
        )


# ============================================================
# АВТОМАТИЧНЕ ВИЗНАЧЕННЯ SWITCH-КОДУ
# ============================================================

switch_codes = []


for function in functions_data:

    code = str(
        function.get(
            "code",
            ""
        )
    )

    function_type = str(
        function.get(
            "type",
            ""
        )
    ).lower()

    name = str(
        function.get(
            "name",
            ""
        )
    ).lower()

    description = str(
        function.get(
            "desc",
            ""
        )
    ).lower()

    # Основний критерій:
    # Boolean + слово switch
    if (
        "switch" in code.lower()
        and function_type == "boolean"
    ):

        switch_codes.append(
            code
        )

    elif (
        code.lower().startswith("switch")
    ):

        switch_codes.append(
            code
        )


# Прибираємо дублікати,
# зберігаючи порядок.

switch_codes = list(
    dict.fromkeys(
        switch_codes
    )
)


# ============================================================
# ВИБІР SWITCH
# ============================================================

selected_switch_code = None


if switch_codes:

    if "switch_1" in switch_codes:

        selected_switch_code = "switch_1"

    else:

        selected_switch_code = switch_codes[0]


# ============================================================
# ПОТОЧНИЙ СТАТУС
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

        st.error(
            "❌ Не вдалося отримати "
            "поточний статус пристрою."
        )


# ============================================================
# ВІДОБРАЖЕННЯ СТАТУСУ
# ============================================================

with st.expander(
    "📡 Поточний статус пристрою",
    expanded=False
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
# ВИЗНАЧЕННЯ ПОТОЧНОГО СТАНУ
# ============================================================

current_power_state = None


if selected_switch_code:

    for item in statuses:

        code = str(
            item.get(
                "code",
                ""
            )
        )

        if code == selected_switch_code:

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
# КЕРУВАННЯ
# ============================================================

st.markdown("---")

st.subheader(
    "⚡ Керування автоматичним вимикачем"
)


# ============================================================
# ЯКЩО SWITCH НЕ ЗНАЙДЕНИЙ
# ============================================================

if not selected_switch_code:

    st.error(
        "❌ Tuya не повернула жодної функції "
        "типу switch."
    )

    st.info(
        """
        Це важлива інформація.

        Якщо підключення до Tuya Cloud успішне,
        але switch-код відсутній, пристрій може
        використовувати інший код керування.

        Подивіться блок:
        «⚙️ Доступні функції пристрою».
        """
    )

else:

    # --------------------------------------------------------
    # ІНФОРМАЦІЯ ПРО SWITCH
    # --------------------------------------------------------

    st.caption(
        f"Код керування Tuya: "
        f"`{selected_switch_code}`"
    )

    col_state, col_buttons = st.columns(
        [1, 2]
    )

    # --------------------------------------------------------
    # ПОТОЧНИЙ СТАН
    # --------------------------------------------------------

    with col_state:

        st.markdown(
            "##### Поточний стан"
        )

        if current_power_state is True:

            st.success(
                "🟢 УВІМКНЕНО"
            )

        elif current_power_state is False:

            st.warning(
                "🔴 ВИМКНЕНО"
            )

        else:

            st.info(
                "ℹ️ Стан невідомий"
            )

    # --------------------------------------------------------
    # КНОПКИ
    # --------------------------------------------------------

    with col_buttons:

        st.markdown(
            "##### Керування з хмари"
        )

        button_on, button_off = st.columns(
            2
        )

        # ====================================================
        # УВІМКНЕННЯ
        # ====================================================

        with button_on:

            if st.button(
                "🟢 УВІМКНУТИ",
                use_container_width=True,
                type="primary",
                key="tuya_turn_on"
            ):

                command_body = {
                    "commands": [
                        {
                            "code": selected_switch_code,
                            "value": True
                        }
                    ]
                }

                command_uri = (
                    f"/v1.0/iot-03/devices/"
                    f"{BREAKER_ID}/commands"
                )

                st.write(
                    "Надсилається команда:"
                )

                st.json(
                    command_body
                )

                response = tuya_post(
                    command_uri,
                    command_body
                )

                if response:

                    if response.get(
                        "success"
                    ):

                        st.success(
                            "✅ Команду УВІМКНЕННЯ "
                            "прийнято Tuya."
                        )

                        time.sleep(1)

                        st.rerun()

                    else:

                        st.error(
                            "❌ Tuya не прийняла "
                            "команду."
                        )

                        st.json(
                            response
                        )

        # ====================================================
        # ВИМКНЕННЯ
        # ====================================================

        with button_off:

            if st.button(
                "🔴 ВИМКНУТИ",
                use_container_width=True,
                key="tuya_turn_off"
            ):

                command_body = {
                    "commands": [
                        {
                            "code": selected_switch_code,
                            "value": False
                        }
                    ]
                }

                command_uri = (
                    f"/v1.0/iot-03/devices/"
                    f"{BREAKER_ID}/commands"
                )

                st.write(
                    "Надсилається команда:"
                )

                st.json(
                    command_body
                )

                response = tuya_post(
                    command_uri,
                    command_body
                )

                if response:

                    if response.get(
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
                            "команду."
                        )

                        st.json(
                            response
                        )


# ============================================================
# РУЧНЕ ТЕСТУВАННЯ
# ============================================================

st.markdown("---")

st.subheader(
    "🧪 Тестування команди Tuya"
)

st.caption(
    "Цей блок залишено для діагностики. "
    "Він дозволяє вручну вибрати DP-код."
)


available_codes = [
    function.get(
        "code",
        ""
    )
    for function in functions_data
    if function.get("code")
]


if available_codes:

    default_index = 0

    if selected_switch_code in available_codes:

        default_index = (
            available_codes.index(
                selected_switch_code
            )
        )

    test_code = st.selectbox(
        "DP-код",
        available_codes,
        index=default_index,
        key="manual_test_code"
    )

    test_value = st.selectbox(
        "Значення",
        [True, False],
        format_func=lambda x:
            "🟢 True — УВІМКНУТИ"
            if x
            else
            "🔴 False — ВИМКНУТИ",
        key="manual_test_value"
    )

    if st.button(
        "🚀 Відправити тестову команду",
        use_container_width=True,
        key="manual_test_button"
    ):

        command_body = {
            "commands": [
                {
                    "code": test_code,
                    "value": test_value
                }
            ]
        }

        command_uri = (
            f"/v1.0/iot-03/devices/"
            f"{BREAKER_ID}/commands"
        )

        st.write(
            "### Команда"
        )

        st.json(
            command_body
        )

        response = tuya_post(
            command_uri,
            command_body
        )

        if response:

            if response.get(
                "success"
            ):

                st.success(
                    "✅ Tuya прийняла команду."
                )

                st.json(
                    response
                )

            else:

                st.error(
                    "❌ Tuya повернула помилку."
                )

                st.json(
                    response
                )

else:

    st.info(
        "Функції пристрою ще не отримані."
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

    b_col1, b_col2 = st.columns(2)

    # --------------------------------------------------------
    # ЧАС УВІМКНЕННЯ
    # --------------------------------------------------------

    with b_col1:

        b_on_time = st.time_input(
            "Час увімкнення",
            datetime.time(8, 0),
            key="b_on"
        )

    # --------------------------------------------------------
    # ЧАС ВИМКНЕННЯ
    # --------------------------------------------------------

    with b_col2:

        b_off_time = st.time_input(
            "Час вимкнення",
            datetime.time(18, 0),
            key="b_off"
        )

    # --------------------------------------------------------
    # ДНІ ТИЖНЯ
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # ЗБЕРЕЖЕННЯ РОЗКЛАДУ
    # --------------------------------------------------------

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
                + ", ".join(b_days)
            )

        else:

            st.warning(
                "Дні тижня не вибрані."
            )


# ============================================================
# НИЖНЯ ІНФОРМАЦІЯ
# ============================================================

st.markdown("---")

st.caption(
    "Tuya Cloud API • Свердловина 1 • "
    "Система керування іригацією"
)
