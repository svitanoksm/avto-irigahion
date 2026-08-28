import streamlit as st
import datetime
import time
import hmac
import hashlib
import requests

st.set_page_config(
    page_title="Керування приладами та іригацією",
    page_icon="🎛️",
    layout="wide",
)

st.title("🎛️ Панель керування приладами (Свердловина 1)")
st.markdown("""
Тут ви можете здійснювати увімкнення та вимкнення приладів **1 свердловини** через хмару Tuya Cloud API.
""")

# --- ФУНКЦІЇ ПІДКЛЮЧЕННЯ ДО TUYA API ---

def get_tuya_token():
    """Отримання чинного токена доступу до Tuya Cloud API (HMAC-SHA256)"""
    try:
        tuya_conf = st.secrets["tuya"]
        client_id = tuya_conf["access_id"]
        client_secret = tuya_conf["access_key"]
        base_url = tuya_conf["endpoint"]
    except Exception:
        st.error("Не знайдено параметри [tuya] у файлі st.secrets!")
        return None, None, None

    t = str(int(time.time() * 1000))
    
    # Формування підпису за стандартами Tuya OpenAPI
    message = client_id + t
    sign = hmac.new(
        client_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest().upper()

    headers = {
        "client_id": client_id,
        "sign": sign,
        "t": t,
        "sign_method": "HMAC-SHA256"
    }

    try:
        response = requests.get(base_url + "/v1.0/token?grant_type=1", headers=headers)
        res_data = response.json()
        if res_data.get("success"):
            access_token = res_data["result"]["access_token"]
            return base_url, access_token, client_id
        else:
            st.error(f"Помилка авторизації Tuya: {res_data.get('msg')}")
            return None, None, None
    except Exception as e:
        st.error(fльній помилка запиту до Tuya API: {e}")
        return None, None, None

def get_device_status(device_id):
    """Отримання статусу пристрою з Tuya Cloud"""
    base_url, token, client_id = get_tuya_token()
    if not token:
        return []

    t = str(int(time.time() * 1000))
    message = client_id + token + t
    sign = hmac.new(
        st.secrets["tuya"]["access_key"].encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest().upper()

    headers = {
        "client_id": client_id,
        "access_token": token,
        "sign": sign,
        "t": t,
        "sign_method": "HMAC-SHA256"
    }

    try:
        response = requests.get(f"{base_url}/v1.0/iot-03/devices/{device_id}/status", headers=headers)
        res_data = response.json()
        if res_data.get("success"):
            return res_data.get("result", [])
    except Exception:
        pass
    return []

def send_tuya_command(device_id, code, value):
    """Надсилання команди на пристрій через Tuya Cloud API"""
    base_url, token, client_id = get_tuya_token()
    if not token:
        return False

    t = str(int(time.time() * 1000))
    # Для POST запитів підпис формується з урахуванням body
    body = {"commands": [{"code": code, "value": value}]}
    import json
    body_str = json.dumps(body)
    
    content_sha256 = hashlib.sha256(body_str.encode('utf-8')).hexdigest()
    string_to_sign = client_id + token + t + "POST\n" + content_sha256 + "\n\n/v1.0/iot-03/devices/" + device_id + "/commands"
    
    sign = hmac.new(
        st.secrets["tuya"]["access_key"].encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest().upper()

    headers = {
        "client_id": client_id,
        "access_token": token,
        "sign": sign,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(f"{base_url}/v1.0/iot-03/devices/{device_id}/commands", headers=headers, data=body_str)
        res_data = response.json()
        return res_data.get("success", False)
    except Exception as e:
        st.error(f"Помилка надсилання команди: {e}")
        return False

# --- ІНТЕРФЕЙС КОРИСТУВАЧА ---

st.header("1 свердловина")
st.markdown("---")

# Отримуємо реальний Device ID вимикача із секретів
try:
    BREAKER_ID = st.secrets["tuya"]["breaker_device_id"]
except Exception:
    BREAKER_ID = "bf14f332c4049e5d89xot0"

# Отримуємо поточний стан пристрою з хмари
statuses = get_device_status(BREAKER_ID)
current_power_state = False
switch_code = "switch_1"  # Стандартний код для реле/вимикачів Tuya

for item in statuses:
    # Зазвичай для таких автоматів код стану починається зі switch або switch_1
    if "switch" in item.get("code", ""):
        switch_code = item["code"]
        current_power_state = bool(item["value"])
        break

# --- 1. Автоматичний вимикач ---
st.subheader("⚡ Автоматичний вимикач (1 свердловина Автоматичний вимикач)")

col_state, col_sched = st.columns([1, 2])

with col_state:
    st.markdown("##### Керування з хмари")
    
    # Інтерактивний тумблер, стан якого синхронізовано з хмарою Tuya
    new_breaker_state = st.toggle(
        "Стан живлення", 
        value=current_power_state, 
        key="breaker_tuya_toggle"
    )
    
    # Якщо користувач змінив положення тумблера — відправляємо команду на хмару
    if new_breaker_state != current_power_state:
        with st.spinner("Надсилання команди на пристрій..."):
            success = send_tuya_command(BREAKER_ID, switch_code, new_breaker_state)
            if success:
                st.success("Команду успішно виконано!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Не вдалося виконати команду через хмару.")

    if current_power_state:
        st.success("Стан у хмарі: УВІМКНЕНО")
    else:
        st.warning("Стан у хмарі: ВИМКНЕНО")

with col_sched:
    st.markdown("##### Налаштування розкладу")
    with st.form(key="breaker_schedule_form"):
        b_col1, b_col2 = st.columns(2)
        with b_col1:
            b_on_time = st.time_input("Час увімкнення", datetime.time(8, 0), key="b_on")
        with b_col2:
            b_off_time = st.time_input("Час вимкнення", datetime.time(18, 0), key="b_off")
        
        b_days = st.multiselect(
            "Дні тижня",
            ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"],
            default=["Понеділок", "Середа", "П'ятниця"],
            key="b_days"
        )
        
        b_submitted = st.form_submit_button("Зберегти розклад вимикача")
        if b_submitted:
            st.success(f"Розклад для Автоматичного вимикача збережено: з {b_on_time} по {b_off_time}")

st.markdown("---")

# --- 2. Реле свердловини (Чотири вимикачі) ---
st.subheader("🔌 Реле свердловини (Модулі)")
st.info("Наступним кроком підключимо чотири реле («Модуль 1-3», «Модуль 1-4», «Модуль 1-5», «Резерв»). Перевірте роботоздатність автоматичного вимикача вище.")
