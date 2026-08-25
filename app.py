import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(
    page_title="FMS AgronomOk - Моніторинг свердловини",
    page_icon="💧",
    layout="wide"
)

# --- АВТОРИЗАЦІЯ ТА ОТРИМАННЯ ДАНИХ З GOOGLE SHEETS ---
@st.cache_data(ttl=60) # Кешування даних на 60 секунд для швидкого завантаження
def load_data():
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    
    # Підключення через secrets Streamlit
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    # Відкриваємо таблицю та аркуш
    sheet = client.open("Автоматизація зрошення").worksheet("Свердловина 1")
    data = sheet.get_all_records()
    
    df = pd.DataFrame(data)
    
    # Очистка та приведення типів тільки для числових колонок за їх індексами:
    # 3 - Витрати кВт, 4 - Потужність, 6 - Витрати куб.м., 7 - Продуктивність
    numeric_indexes = [3, 4, 6, 7]
    for idx in numeric_indexes:
        if idx < len(df.columns):
            col_name = df.columns[idx]
            df[col_name] = (
                df[col_name]
                .astype(str)
                .str.replace(',', '.', regex=False)
                .str.replace(r'[^0-9.-]', '', regex=True)
            )
            df[col_name] = pd.to_numeric(df[col_name], errors="coerce")

    # Приведення дати та часу
    df["Дата та час"] = pd.to_datetime(df["Дата та час"], errors="coerce")
    
    return df

try:
    df = load_data()
except Exception as e:
    st.error(f"Помилка завантаження даних з Google Таблиці: {e}")
    st.stop()

# --- БОКОВЕ МЕНЮ ---
st.sidebar.title("💧 FMS AgronomOk")
st.sidebar.subheader("Панель управління")

menu_option = st.sidebar.radio(
    "Перейти до:",
    ["Головна панель", "Поливні модулі"]
)

# Отримуємо список унікальних активних модулів (відкидаємо "Вимкнено", якщо потрібно)
modules_list = df["Зрошувальний основний модуль"].dropna().unique() if "Зрошувальний основний модуль" in df.columns else []
modules_list = [m for m in modules_list if m != "Вимкнено"]

# --- ЛОГІКА СТОРІНОК ---

if menu_option == "Головна панель":
    st.title("📊 Загальний моніторинг свердловини")
    
    # Метрики поточного стану
    if not df.empty:
        latest = df.iloc[-1]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Стан вимикача", latest.get("Стан", "Н/Д"))
        col2.metric("Загальні витрати води", f"{latest.get('Витрати, куб. м.', 0)} м³")
        col3.metric("Загальна енергія", f"{latest.get('Витрати, кВт', 0)} кВт")
        col4.metric("Поточний модуль", latest.get("Зрошувальний основний модуль", "Н/Д"))
    
    st.subheader("Останні записи з таблиці")
    st.dataframe(df.tail(10), use_container_width=True)

elif menu_option == "Поливні модулі":
    st.sidebar.markdown("---")
    st.sidebar.subheader("Вибір модуля")
    
    if len(modules_list) > 0:
        selected_module = st.sidebar.selectbox("Оберіть зрошувальний модуль:", modules_list)
        
        st.title(f"⚙️ Моніторинг модуля: {selected_module}")
        
        # Фільтруємо датасет по обраному модулю
        df_filtered = df[df["Зрошувальний основний модуль"] == selected_module]
        
        if df_filtered.empty:
            st.warning("Немає даних для обраного модуля.")
        else:
            # Виводимо графіки за правильними числовими колонками
            st.subheader("⚡ Потужність за період (кВт/год)")
            st.line_chart(
                df_filtered.set_index("Дата та час").iloc[:, 4], # Потужність
                use_container_width=True
            )
            
            st.subheader("🌊 Продуктивність (куб. м./год)")
            st.line_chart(
                df_filtered.set_index("Дата та час").iloc[:, 7], # Продуктивність
                use_container_width=True
            )
            
            with st.expander("Переглянути детальні дані по модулю"):
                st.dataframe(df_filtered, use_container_width=True)
    else:
        st.warning("Наразі не виявлено активних модулів у базі даних.")
