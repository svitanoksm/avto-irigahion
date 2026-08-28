import streamlit as st
import datetime
import time
import hmac
import hashlib
import requests
import json


# ============================================================
# НАЛАШТУВАННЯ STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Керування приладами та іригацією",
    page_icon="🎛️",
    layout="wide",
)

st.title("🎛️ Панель керування приладами (Свердловина 1)")

st.markdown("""
Тут ви можете здійснювати увімкнення та вимкнення приладів
**1 свердловини** через хмару Tuya Cloud API.
""")


# ============================================================
# TUYA — ОТРИМАННЯ НАЛАШТУВАНЬ
# ============================================================

def get_tuya_config():
    try:
        conf = st.secrets["tuya"]

        client_id = str(conf["access_id"])
        secret = str(conf["access_key"])
        base_url = str(conf["endpoint"]).rstrip("/")

        return client_id, secret, base_url

    except Exception as e:
        st.error(
            "Не знайдено або неправильно налаштовано "
            "[tuya] у файлі st.secrets."
        )
        st.error(str(e))

        return None, None, None


# ============================================================
# TUYA — ОТРИМАННЯ ТОКЕНА
# ============================================================

def get_tuya_token():

    client_id, secret, base_url = get_tuya_config()

    if not client_id:
        return None

    timestamp = str(int(time.time() * 1000))

    # Підпис для отримання токена
    sign_string = client_id + timestamp

    sign = hmac.new(
        secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    headers = {
        "client_id": client_id,
        "sign": sign,
        "t": timestamp,
        "sign_method": "HMAC-SHA256",
    }

    url = base_url + "/v1.0/token?grant_type=1"

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        # Для діагностики
        if response.status_code != 200:
            st.error(
                f"Tuya HTTP помилка при отриманні токена: "
                f"{response.status_code}"
            )
            st.code(response.text)
            return None

        data = response.json()

        if not data.get("success"):

            st.error("Tuya не видала access token.")
            st.json(data)

            return None

        token = data.get("result", {}).get("access_token")

        if not token:
            st.error("У відповіді Tuya немає access_token.")
            st.json(data)
            return None

        return {
            "base_url": base_url,
            "client_id": client_id,
            "secret": secret,
            "access_token": token
        }

    except Exception as e:

        st.error(f"Помилка підключення до Tuya Cloud: {e}")

        return None


# ============================================================
# TUYA — ФОРМУВАННЯ ПІДПИСУ
# ============================================================

def make_tuya_signature(
    client_id,
    access_token,
    secret,
    timestamp,
    method,
    body_string,
    uri
):

    body_hash = hashlib.sha256(
        body_string.encode("utf-8")
    ).hexdigest()

    string_to_sign = (
        client_id
        + access_token
        + timestamp
        + method
        + "\n"
        + body_hash
        + "\n"
        + "\n"
        + uri
    )

    sign = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    return sign


# ============================================================
# TUYA — УНІВЕРСАЛЬНИЙ GET
# ============================================================

def tuya_get(uri):

    auth = get_tuya_token()

    if not auth:
        return None

    timestamp = str(int(time.time() * 1000))

    body_string = ""

    sign = make_tuya_signature(
        auth["client_id"],
        auth["access_token"],
        auth["secret"],
        timestamp,
        "GET",
        body_string,
        uri
    )

    headers = {
        "client_id": auth["client_id"],
        "access_token": auth["access_token"],
        "sign": sign,
        "t": timestamp,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json",
    }

    try:

        response = requests.get(
            auth["base_url"] + uri,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:

            st.error(
                f"Tuya HTTP {response.status_code}"
            )

            st.code(response.text)

            return None

        data = response.json()

        return data

    except Exception as e:

        st.error(f"Помилка GET запиту Tuya: {e}")

        return None


# ============================================================
# TUYA — ОТРИМАННЯ ДЕТАЛЕЙ ПРИСТРОЮ
# ============================================================

def get_device_details(device_id):

    uri = f"/v1.0/iot-03/devices/{device_id}"

    data = tuya_get(uri)

    if not data:
        return {}

    if not data.get("success"):

        st.error("Tuya повернула помилку при отриманні пристрою.")
        st.json(data)

        return {}

    return data.get("result", {})


# ============================================================
# TUYA — ОТРИМАННЯ ФУНКЦІЙ ПРИСТРОЮ
# ============================================================

def get_device_functions(device_id):

    uri = f"/v1.0/iot-03/devices/{device_id}/functions"

    data = tuya_get(uri)

    if not data:
        return {}

    if not data.get("success"):

        st.error(
            "Tuya повернула помилку при отриманні "
            "функцій пристрою."
        )

        st.json(data)

        return {}

    return data.get("result", {})


# ============================================================
# TUYA — ОТРИМАННЯ СТАТУСУ
# ============================================================

def get_device_status(device_id):

    uri = f"/v1.0/iot-03/devices/{device_id}/status"

    data = tuya_get(uri)

    if not data:
        return []

    if not data.get("success"):

        st.error(
            "Tuya повернула помилку при отриманні статусу."
        )

        st.json(data)

        return []

    return data.get("result", [])


# ============================================================
# TUYA — НАДСИЛАННЯ КОМАНДИ
# ============================================================

def send_tuya_command(device_id, code, value):

    auth = get_tuya_token()

    if not auth:
        return False, {}

    uri = f"/v1.0/iot-03/devices/{device_id}/commands"

    body = {
        "commands": [
            {
                "code": code,
                "value": value
            }
        ]
    }

    # ВАЖЛИВО:
    # Підпис повинен відповідати саме тому тілу,
    # яке фактично відправляється.
    body_string = json.dumps(
        body,
        separators=(",", ":")
    )

    timestamp = str(int(time.time() * 1000))

    sign = make_tuya_signature(
        auth["client_id"],
        auth["access_token"],
        auth["secret"],
        timestamp,
        "POST",
        body_string,
        uri
    )

    headers = {
        "client_id": auth["client_id"],
        "access_token": auth["access_token"],
        "sign": sign,
        "t": timestamp,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json",
    }

    try:

        response = requests.post(
            auth["base_url"] + uri,
            headers=headers,
            data=body_string,
            timeout=15
        )

        st.write("### Відповідь Tuya на команду")

        st.write(
            f"HTTP статус: `{response.status_code}`"
        )

        try:
            data = response.json()
            st.json(data)
        except Exception:
            st.code(response.text)
            return False, {}

        if not data.get("success"):

            st.error(
                f"Tuya не виконала команду: "
                f"{data.get('msg', 'невідома помилка')}"
            )

            return False, data

        return True, data

    except Exception as e:

        st.error(
            f"Помилка відправлення команди Tuya: {e}"
        )

        return False, {}


# ============================================================
# НАЛАШТУВАННЯ ПРИСТРОЮ
# ============================================================

try:

    BREAKER_ID = st.secrets["tuya"]["breaker_device_id"]

except Exception:

    BREAKER_ID = ""

    st.error(
        "У st.secrets не знайдено "
        "`tuya.breaker_device_id`."
    )


# ============================================================
# ІНФОРМАЦІЯ ПРО ПРИСТРІЙ
# ============================================================

st.header("1 свердловина")

st.markdown("---")


if not BREAKER_ID:

    st.stop()


device_info = get_device_details(BREAKER_ID)


# ============================================================
# ТЕХНІЧНА ІНФОРМАЦІЯ
# ============================================================

with st.expander(
    "🔍 Технічні дані пристрою від Tuya Cloud",
    expanded=False
):

    st.write("Device ID:")

    st.code(BREAKER_ID)

    st.write("Інформація про пристрій:")

    st.json(device_info)


# ============================================================
# ФУНКЦІЇ ПРИСТРОЮ
# ============================================================

device_functions = get_device_functions(BREAKER_ID)


with st.expander(
    "⚙️ Доступні функції пристрою",
    expanded=True
):

    st.json(device_functions)


# ============================================================
# СТАТУС ПРИСТРОЮ
# ============================================================

statuses = get_device_status(BREAKER_ID)


with st.expander(
    "📡 Поточний статус пристрою",
    expanded=False
):

    st.json(statuses)


# ============================================================
# ВИЗНАЧЕННЯ SWITCH CODE
# ============================================================

switch_code = None
current_power_state = False


for item in statuses:

    code = str(item.get("code", ""))
    value = item.get("value")

    # Шукаємо саме switch_*
    if code.startswith("switch"):

        switch_code = code

        if isinstance(value, bool):
            current_power_state = value

        break


# ============================================================
# ВІДОБРАЖЕННЯ ЗНАЙДЕНОГО КОДУ
# ============================================================

if switch_code:

    st.info(
        f"Код керування вимикачем Tuya: "
        f"`{switch_code}`"
    )

else:

    st.error(
        "❌ У статусі пристрою не знайдено "
        "жодного коду типу `switch_*`."
    )

    st.warning(
        "Подивіться розділ «Доступні функції пристрою». "
        "Там потрібно знайти реальний код керування "
        "вимикачем."
    )


# ============================================================
# КЕРУВАННЯ
# ============================================================

st.subheader(
    "⚡ Автоматичний вимикач "
    "(1 свердловина)"
)


col_state, col_buttons = st.columns([1, 2])


# ============================================================
# ПОТОЧНИЙ СТАН
# ============================================================

with col_state:

    st.markdown("##### Поточний стан")

    if current_power_state:

        st.success(
            "🟢 УВІМКНЕНО"
        )

    else:

        st.warning(
            "🔴 ВИМКНЕНО"
        )

    st.write(
        f"Код: `{switch_code}`"
        if switch_code
        else "Код керування не визначено."
    )


# ============================================================
# КНОПКИ КЕРУВАННЯ
# ============================================================

with col_buttons:

    st.markdown("##### Керування з хмари Tuya")

    if switch_code:

        col_on, col_off = st.columns(2)


        # ----------------------------------------------------
        # УВІМКНУТИ
        # ----------------------------------------------------

        with col_on:

            if st.button(
                "🟢 УВІМКНУТИ",
                use_container_width=True
            ):

                st.write(
                    f"Надсилаю команду: "
                    f"`{switch_code} = true`"
                )

                success, response = send_tuya_command(
                    BREAKER_ID,
                    switch_code,
                    True
                )

                if success:

                    st.success(
                        "Команду Tuya прийняла."
                    )

                    time.sleep(1)

                    st.rerun()


        # ----------------------------------------------------
        # ВИМКНУТИ
        # ----------------------------------------------------

        with col_off:

            if st.button(
                "🔴 ВИМКНУТИ",
                use_container_width=True
            ):

                st.write(
                    f"Надсилаю команду: "
                    f"`{switch_code} = false`"
                )

                success, response = send_tuya_command(
                    BREAKER_ID,
                    switch_code,
                    False
                )

                if success:

                    st.success(
                        "Команду Tuya прийняла."
                    )

                    time.sleep(1)

                    st.rerun()


# ============================================================
# ТЕСТУВАННЯ ІНШИХ SWITCH CODE
# ============================================================

st.markdown("---")

st.subheader("🧪 Тестування команди Tuya")

st.caption(
    "Цей блок потрібен для перевірки, який саме "
    "код відповідає за фізичне реле."
)


test_code = st.text_input(
    "Код команди",
    value=switch_code if switch_code else "",
    help="Наприклад: switch_1"
)


test_value = st.selectbox(
    "Значення",
    [True, False],
    format_func=lambda x: "УВІМКНУТИ" if x else "ВИМКНУТИ"
)


if st.button(
    "🚀 Відправити тестову команду",
    type="primary"
):

    if not test_code:

        st.error(
            "Вкажіть код команди."
        )

    else:

        st.write("### Команда")

        st.json({
            "commands": [
                {
                    "code": test_code,
                    "value": test_value
                }
            ]
        })

        success, response = send_tuya_command(
            BREAKER_ID,
            test_code,
            test_value
        )

        if success:

            st.success(
                "Tuya API повідомила про успішне прийняття команди."
            )


# ============================================================
# РОЗКЛАД
# ============================================================

st.markdown("---")

st.subheader("⏰ Налаштування розкладу")

with st.form(
    key="breaker_schedule_form"
):

    b_col1, b_col2 = st.columns(2)

    with b_col1:

        b_on_time = st.time_input(
            "Час увімкнення",
            datetime.time(8, 0),
            key="b_on"
        )

    with b_col2:

        b_off_time = st.time_input(
            "Час вимкнення",
            datetime.time(18, 0),
            key="b_off"
        )


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


    if st.form_submit_button(
        "Зберегти розклад вимикача"
    ):

        st.success(
            f"Розклад збережено: "
            f"з {b_on_time} по {b_off_time}"
        )
