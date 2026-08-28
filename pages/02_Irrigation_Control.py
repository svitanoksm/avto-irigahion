import streamlit as st
import datetime
import time
import hmac
import hashlib
import requests
import json


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
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
# НАЛАШТУВАННЯ TUYA
# ============================================================

def get_tuya_config():
    """
    Отримання налаштувань Tuya із st.secrets.
    """

    try:
        conf = st.secrets["tuya"]

        client_id = str(conf["access_id"]).strip()
        secret = str(conf["access_key"]).strip()
        base_url = str(conf["endpoint"]).strip().rstrip("/")

        return client_id, secret, base_url

    except Exception as e:

        st.error(
            "❌ Не знайдено або неправильно налаштовано "
            "[tuya] у файлі st.secrets."
        )

        st.error(f"Деталі: {e}")

        return None, None, None


# ============================================================
# ОТРИМАННЯ ACCESS TOKEN
# ============================================================

def get_tuya_token():
    """
    Отримання access_token від Tuya Cloud.

    Для першого запиту без access_token:
        sign = HMAC-SHA256(access_id + timestamp, access_key)

    Результат HMAC переводиться у верхній регістр.
    """

    client_id, secret, base_url = get_tuya_config()

    if not client_id or not secret or not base_url:
        return None

    # --------------------------------------------------------
    # TIMESTAMP
    # --------------------------------------------------------

    timestamp = str(int(time.time() * 1000))

    # --------------------------------------------------------
    # РЯДОК ДЛЯ ПІДПИСУ
    # --------------------------------------------------------

    string_to_sign = client_id + timestamp

    # --------------------------------------------------------
    # HMAC-SHA256
    # --------------------------------------------------------

    sign = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    url = (
        base_url
        + "/v1.0/token?grant_type=1"
    )

    # --------------------------------------------------------
    # HEADERS
    # --------------------------------------------------------

    headers = {
        "client_id": client_id,
        "sign": sign,
        "t": timestamp,
        "sign_method": "HMAC-SHA256",
    }

    # --------------------------------------------------------
    # ДІАГНОСТИКА
    # --------------------------------------------------------

    with st.expander(
        "🔧 Діагностика запиту Access Token",
        expanded=False
    ):

        st.write("**Endpoint:**")
        st.code(base_url)

        st.write("**URL:**")
        st.code(url)

        st.write("**Client ID:**")
        st.code(client_id)

        st.write("**Timestamp:**")
        st.code(timestamp)

        st.write("**Рядок для підпису:**")
        st.code(string_to_sign)

        st.write("**Довжина секретного ключа:**")
        st.write(len(secret))

        st.write("**Sign:**")
        st.code(sign)

        st.write("**Довжина Sign:**")
        st.write(len(sign))

    # --------------------------------------------------------
    # ЗАПИТ
    # --------------------------------------------------------

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

    except requests.exceptions.RequestException as e:

        st.error(
            f"❌ Помилка з'єднання з Tuya Cloud: {e}"
        )

        return None

    # --------------------------------------------------------
    # HTTP STATUS
    # --------------------------------------------------------

    if response.status_code != 200:

        st.error(
            f"❌ Tuya HTTP помилка: "
            f"{response.status_code}"
        )

        st.code(response.text)

        return None

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    try:

        data = response.json()

    except Exception:

        st.error(
            "❌ Tuya повернула відповідь, "
            "яку неможливо прочитати як JSON."
        )

        st.code(response.text)

        return None

    # --------------------------------------------------------
    # ПОМИЛКА TUYA
    # --------------------------------------------------------

    if not data.get("success"):

        st.error(
            "❌ Tuya не видала access token."
        )

        st.json(data)

        return None

    # --------------------------------------------------------
    # ACCESS TOKEN
    # --------------------------------------------------------

    token = (
        data
        .get("result", {})
        .get("access_token")
    )

    if not token:

        st.error(
            "❌ Tuya повідомила про успіх, "
            "але access_token відсутній."
        )

        st.json(data)

        return None

    # --------------------------------------------------------
    # УСПІХ
    # --------------------------------------------------------

    return {
        "base_url": base_url,
        "client_id": client_id,
        "secret": secret,
        "access_token": token,
    }


# ============================================================
# ФОРМУВАННЯ ПІДПИСУ ДЛЯ API З ACCESS TOKEN
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
    """
    Формування підпису Tuya API для запитів,
    які виконуються після отримання access_token.
    """

    # SHA256 тіла запиту
    body_hash = hashlib.sha256(
        body_string.encode("utf-8")
    ).hexdigest()

    # Строка для підпису
    string_to_sign = (
        client_id
        + access_token
        + timestamp
        + method.upper()
        + "\n"
        + body_hash
        + "\n"
        + "\n"
        + uri
    )

    # HMAC-SHA256
    sign = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    return sign


# ============================================================
# УНІВЕРСАЛЬНИЙ GET ЗАПИТ TUYA
# ============================================================

def tuya_get(uri):
    """
    Виконання GET-запиту до Tuya Cloud API.
    """

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

    url = auth["base_url"] + uri

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

    except requests.exceptions.RequestException as e:

        st.error(
            f"❌ Помилка GET-запиту Tuya: {e}"
        )

        return None

    if response.status_code != 200:

        st.error(
            f"❌ Tuya HTTP {response.status_code}"
        )

        st.code(response.text)

        return None

    try:

        data = response.json()

    except Exception:

        st.error(
            "❌ Tuya повернула некоректний JSON."
        )

        st.code(response.text)

        return None

    return data


# ============================================================
# ОТРИМАННЯ ДЕТАЛЕЙ ПРИСТРОЮ
# ============================================================

def get_device_details(device_id):
    """
    Отримання повної інформації про пристрій.
    """

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{device_id}"
    )

    data = tuya_get(uri)

    if not data:
        return {}

    if not data.get("success"):

        st.error(
            "❌ Tuya повернула помилку "
            "при отриманні інформації про пристрій."
        )

        st.json(data)

        return {}

    return data.get("result", {})


# ============================================================
# ОТРИМАННЯ ФУНКЦІЙ ПРИСТРОЮ
# ============================================================

def get_device_functions(device_id):
    """
    Отримання доступних функцій / DP-кодів пристрою.
    """

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{device_id}/functions"
    )

    data = tuya_get(uri)

    if not data:
        return {}

    if not data.get("success"):

        st.error(
            "❌ Tuya повернула помилку "
            "при отриманні функцій пристрою."
        )

        st.json(data)

        return {}

    return data.get("result", {})


# ============================================================
# ОТРИМАННЯ ПОТОЧНОГО СТАТУСУ
# ============================================================

def get_device_status(device_id):
    """
    Отримання поточного статусу пристрою.
    """

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{device_id}/status"
    )

    data = tuya_get(uri)

    if not data:
        return []

    if not data.get("success"):

        st.error(
            "❌ Tuya повернула помилку "
            "при отриманні статусу пристрою."
        )

        st.json(data)

        return []

    return data.get("result", [])


# ============================================================
# ВІДПРАВЛЕННЯ КОМАНДИ TUYA
# ============================================================

def send_tuya_command(
    device_id,
    code,
    value
):
    """
    Надсилання команди на пристрій Tuya.
    """

    auth = get_tuya_token()

    if not auth:

        return False, {}

    # --------------------------------------------------------
    # URI
    # --------------------------------------------------------

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{device_id}/commands"
    )

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    body = {
        "commands": [
            {
                "code": code,
                "value": value
            }
        ]
    }

    # Важливо:
    # використовуємо компактний JSON,
    # щоб рядок для підпису точно відповідав
    # тілу запиту.

    body_string = json.dumps(
        body,
        separators=(",", ":"),
        ensure_ascii=False
    )

    # --------------------------------------------------------
    # TIMESTAMP
    # --------------------------------------------------------

    timestamp = str(
        int(time.time() * 1000)
    )

    # --------------------------------------------------------
    # SIGN
    # --------------------------------------------------------

    sign = make_tuya_signature(
        auth["client_id"],
        auth["access_token"],
        auth["secret"],
        timestamp,
        "POST",
        body_string,
        uri
    )

    # --------------------------------------------------------
    # HEADERS
    # --------------------------------------------------------

    headers = {
        "client_id": auth["client_id"],
        "access_token": auth["access_token"],
        "sign": sign,
        "t": timestamp,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json",
    }

    # --------------------------------------------------------
    # ДІАГНОСТИКА
    # --------------------------------------------------------

    with st.expander(
        "🔧 Технічні дані команди Tuya",
        expanded=False
    ):

        st.write("URI:")
        st.code(uri)

        st.write("Body:")
        st.json(body)

        st.write("Timestamp:")
        st.code(timestamp)

        st.write("Sign:")
        st.code(sign)

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    try:

        response = requests.post(
            auth["base_url"] + uri,
            headers=headers,
            data=body_string.encode("utf-8"),
            timeout=15
        )

    except requests.exceptions.RequestException as e:

        st.error(
            f"❌ Помилка надсилання команди Tuya: {e}"
        )

        return False, {}

    # --------------------------------------------------------
    # HTTP STATUS
    # --------------------------------------------------------

    st.write("### 📡 Відповідь Tuya на команду")

    st.write(
        f"HTTP статус: `{response.status_code}`"
    )

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    try:

        data = response.json()

    except Exception:

        st.error(
            "Tuya повернула не JSON."
        )

        st.code(response.text)

        return False, {}

    # Показуємо повну відповідь
    st.json(data)

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if not data.get("success"):

        st.error(
            "❌ Tuya не виконала команду."
        )

        st.error(
            f"Код: {data.get('code')}"
        )

        st.error(
            f"Повідомлення: {data.get('msg')}"
        )

        return False, data

    # --------------------------------------------------------
    # УСПІШНО
    # --------------------------------------------------------

    st.success(
        "✅ Tuya прийняла команду."
    )

    return True, data


# ============================================================
# DEVICE ID
# ============================================================

try:

    BREAKER_ID = str(
        st.secrets["tuya"]["breaker_device_id"]
    ).strip()

except Exception:

    BREAKER_ID = ""

    st.error(
        "❌ У st.secrets не знайдено "
        "`tuya.breaker_device_id`."
    )


# ============================================================
# ПЕРЕВІРКА DEVICE ID
# ============================================================

if not BREAKER_ID:

    st.warning(
        "Немає Device ID. Роботу сторінки зупинено."
    )

    st.stop()


# ============================================================
# РОЗДІЛ СВЕРДЛОВИНИ
# ============================================================

st.header("1 свердловина")

st.markdown("---")


# ============================================================
# ОТРИМАННЯ ІНФОРМАЦІЇ ПРО ПРИСТРІЙ
# ============================================================

device_info = get_device_details(
    BREAKER_ID
)


with st.expander(
    "🔍 Технічні дані пристрою від Tuya Cloud",
    expanded=False
):

    st.write("**Device ID:**")

    st.code(BREAKER_ID)

    st.write("**Інформація про пристрій:**")

    if device_info:

        st.json(device_info)

    else:

        st.warning(
            "Інформацію про пристрій отримати не вдалося."
        )


# ============================================================
# ФУНКЦІЇ ПРИСТРОЮ
# ============================================================

device_functions = get_device_functions(
    BREAKER_ID
)


with st.expander(
    "⚙️ Доступні функції пристрою",
    expanded=False
):

    if device_functions:

        st.json(device_functions)

    else:

        st.warning(
            "Функції пристрою не отримані."
        )


# ============================================================
# ПОТОЧНИЙ СТАТУС
# ============================================================

statuses = get_device_status(
    BREAKER_ID
)


with st.expander(
    "📡 Поточний статус пристрою",
    expanded=False
):

    if statuses:

        st.json(statuses)

    else:

        st.warning(
            "Статус пристрою не отриманий."
        )


# ============================================================
# ВИЗНАЧЕННЯ SWITCH CODE
# ============================================================

switch_code = None

current_power_state = False


for item in statuses:

    code = str(
        item.get("code", "")
    )

    value = item.get("value")

    # Шукаємо switch_*
    if code.startswith("switch"):

        switch_code = code

        if isinstance(value, bool):

            current_power_state = value

        break


# ============================================================
# ЯКЩО SWITCH НЕ ЗНАЙДЕНИЙ
# ============================================================

if not switch_code:

    st.error(
        "❌ У статусі пристрою не знайдено "
        "код керування типу `switch_*`."
    )

    st.info(
        "Це не обов'язково означає проблему з кодом. "
        "Спочатку потрібно успішно отримати access_token."
    )


# ============================================================
# КЕРУВАННЯ АВТОМАТИЧНИМ ВИМИКАЧЕМ
# ============================================================

st.subheader(
    "⚡ Автоматичний вимикач "
    "(1 свердловина)"
)


col_state, col_control = st.columns(
    [1, 2]
)


# ============================================================
# ПОТОЧНИЙ СТАН
# ============================================================

with col_state:

    st.markdown(
        "##### Поточний стан"
    )

    if current_power_state:

        st.success(
            "🟢 УВІМКНЕНО"
        )

    else:

        st.warning(
            "🔴 ВИМКНЕНО"
        )

    if switch_code:

        st.caption(
            f"Код Tuya: `{switch_code}`"
        )

    else:

        st.caption(
            "Код Tuya не визначено"
        )


# ============================================================
# КНОПКИ УВІМКНЕННЯ / ВИМКНЕННЯ
# ============================================================

with col_control:

    st.markdown(
        "##### Керування з хмари Tuya"
    )

    if switch_code:

        col_on, col_off = st.columns(2)

        # ----------------------------------------------------
        # УВІМКНЕННЯ
        # ----------------------------------------------------

        with col_on:

            if st.button(
                "🟢 УВІМКНУТИ",
                use_container_width=True,
                type="primary"
            ):

                st.write(
                    f"Надсилається команда:"
                )

                st.code(
                    f"{switch_code} = true"
                )

                success, response = send_tuya_command(
                    BREAKER_ID,
                    switch_code,
                    True
                )

                if success:

                    time.sleep(1)

                    st.rerun()


        # ----------------------------------------------------
        # ВИМКНЕННЯ
        # ----------------------------------------------------

        with col_off:

            if st.button(
                "🔴 ВИМКНУТИ",
                use_container_width=True
            ):

                st.write(
                    f"Надсилається команда:"
                )

                st.code(
                    f"{switch_code} = false"
                )

                success, response = send_tuya_command(
                    BREAKER_ID,
                    switch_code,
                    False
                )

                if success:

                    time.sleep(1)

                    st.rerun()


# ============================================================
# РУЧНИЙ ТЕСТ КОДУ
# ============================================================

st.markdown("---")

st.subheader(
    "🧪 Ручне тестування команди Tuya"
)

st.caption(
    "Цей блок дозволяє вручну вказати DP-код "
    "і перевірити команду."
)


test_code = st.text_input(
    "Код команди",
    value=switch_code if switch_code else "",
    help="Наприклад: switch_1"
)


test_value = st.selectbox(
    "Значення",
    [True, False],
    format_func=lambda x:
        "🟢 УВІМКНУТИ"
        if x
        else
        "🔴 ВИМКНУТИ"
)


if st.button(
    "🚀 Відправити тестову команду",
    use_container_width=True
):

    if not test_code:

        st.error(
            "❌ Вкажіть код команди."
        )

    else:

        st.write(
            "### Команда, яка буде відправлена"
        )

        st.json(
            {
                "commands": [
                    {
                        "code": test_code,
                        "value": test_value
                    }
                ]
            }
        )

        success, response = send_tuya_command(
            BREAKER_ID,
            test_code,
            test_value
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
    # ДНІ
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
    # ЗБЕРЕЖЕННЯ
    # --------------------------------------------------------

    if st.form_submit_button(
        "Зберегти розклад вимикача"
    ):

        st.success(
            f"Розклад збережено: "
            f"з {b_on_time} по {b_off_time}"
        )

st.markdown("---")

st.caption(
    "Tuya Cloud API • Керування свердловиною 1"
)
