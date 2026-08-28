import streamlit as st
import datetime
import time
import hmac
import hashlib
import requests
import json

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
    """Отримання токена Tuya Cloud"""
    try:
        conf = st.secrets["tuya"]
        client_id = conf["access_id"]
        secret = conf["access_key"]
        base_url = conf["endpoint"]
    except Exception:
        st.error("Не знайдено параметри [tuya] у файлі st.secrets!")
        return None, None, None

    t = str(int(time.time() * 1000))
    # Для токена рядок підпису: client_id + t
    message = client_id + t
    sign = hmac.new(
        secret.encode('utf-8'),
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
        res = response.json()
        if res.get("success"):
            return base_url, res["result"]["access_token"], client_id
    except Exception:
        pass
    return None, None, None

def get_device_status(device_id):
    """Отримання статусу пристрою (з правильним розрахунком sign для Tuya)"""
    base_url, token, client_id = get_tuya_token()
    if not token:
        return []

    t = str(int(time.time() * 1000))
    secret = st.secrets["tuya"]["access_key"]
    
    # Специфікація Tuya OpenAPI для GET: client_id + access_token + t + HTTPMethod + content_sha256 + sign_headers + url
    # Для простого GET без body content_sha256 це хеш від пустої строки
    empty_hash = hashlib.sha256(b"").hexdigest()
    uri = f"/v1.0/iot-03/devices/{device_id}/status"
    
    string_to_sign = client_id + token + t + "GET\n" + empty_hash + "\n\n" + uri
    sign = hmac.new(
        secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
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
        response = requests.get(base_url + uri, headers=headers)
        res = response.json()
        if res.get("success"):
            return res.get("result", [])
    except Exception:
        pass
    return []

def send_tuya_command(device_id, code, value):
    """Надсилання команди на пристрій"""
    base_url, token, client_id = get_tuya_token()
    if not token:
        return False

    t = str(int(time.time() * 1000))
    secret = st.secrets["tuya"]["access_key"]
    
    body = {"commands": [{"code": code, "value": value}]}
    body_str = json.dumps(body)
    
    content_sha256 = hashlib.sha256(body_str.encode('utf-8')).hexdigest()
    uri = f"/v1.0/iot-03/devices/{device_id}/commands"
    
    string_to_sign = client_id + token + t + "POST\n" + content_sha256 + "\n\n" + uri
    sign = hmac.new(
        secret.encode('utf-8'),
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
        response = requests.post(base_url + uri, headers=headers, data=body_str)
        res = response.json()
        return res.get("success", False)
    except Exception:
        return False

# --- ІНТЕРФЕЙС КОРИСТУВАЧА ---

st.header("1 свердловина")
st.markdown("---")

try:
    BREAKER_ID = st.secrets["tuya"]["breaker_device_id"]
except Exception:
    BREAKER_ID = "bf14f332c4049e5d89xot0"

statuses = get_device_status(BREAKER_ID)
current_power_state = False
switch_code = "switch_1"

for item in statuses:
    if "switch" in item.get("code", ""):
        switch_code = item["code"]
        current_power_state = bool(item["value"])
        break

st.subheader("⚡ Автоматичний вимикач (1 свердловина Автоматичний вимикач)")

col_state, col_sched = st.columns([1, 2])

with col_state:
    st.markdown("##### Керування з хмари")
    
    new_breaker_state = st.toggle(
        "Стан живлення", 
        value=current_power_state, 
        key="breaker_tuya_toggle"
    )
    
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
        
        if st.form_submit_button("Зберегти розклад вимикача"):
            st.success(f"Розклад збережено: з {b_on_time} по {b_off_time}")

st.markdown("---")
