import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Параметри полів та систем", page_icon="⚙️", layout="wide")

st.title("⚙️ Параметри полів, модулів та іригаційних систем")
st.markdown("""
Тут ви можете налаштовувати довідкові дані: площі модулів, культури, схеми садіння та характеристики іригаційних систем. 
Усі зміни автоматично зберігаються **прямо у вашу Google Таблицю** та використовуються в розрахунках.
""")

# --- НАЛАШТУВАННЯ GOOGLE SHEETS ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1qF-7THB566lqOyQV0f6xuB052IRHh8s4CHMUpuN82P4/edit?gid=571418562#gid=571418562"
WORKSHEET_NAME = "Довідник зрошувальних модулів"

@st.cache_resource
def init_google_sheets():
    """Підключення до Google Sheets через секрети Streamlit"""
    # Доступ до ключів безпеки, які ми збережемо в настройках Streamlit Cloud
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Якщо ви використовуєте secrets у Streamlit Cloud
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        return client.open_by_url(SPREADSHEET_URL)
    else:
        return None

# Функція завантаження даних з Google Таблиці
def load_data_from_gsheets():
    try:
        sh = init_google_sheets()
        if not sh:
            st.error("Не знайдено секрети доступу до Google Таблиць у налаштуваннях Streamlit (`st.secrets`).")
            return pd.DataFrame()
        
        worksheet = sh.worksheet(WORKSHEET_NAME)

        # Забираємо "сирі" значення, без форматування під локаль таблиці
        all_values = worksheet.get_all_values(value_render_option="UNFORMATTED_VALUE")

        if not all_values:
            return pd.DataFrame()

        headers = all_values[0]
        rows = all_values[1:]
        df = pd.DataFrame(rows, columns=headers)

        # Явно приводимо числові колонки до float/int, щоб Streamlit не гадав сам
        numeric_cols = [
            "Площа, га",
            "Проектна продуктивність зрошення, куб. м./га",
            "Рік посадки",
            "Кількість Сортових дерев, шт",
            "Кількість запилювача 1, шт",
            "Кількість запилювача 2, шт",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df
    except Exception as e:
        st.error(f"Помилка завантаження даних із Google Таблиці: {e}")
        return pd.DataFrame()

# Функція збереження даних у Google Таблицю
def save_data_to_gsheets(df):
    try:
        sh = init_google_sheets()
        if not sh:
            return False
            
        worksheet = sh.worksheet(WORKSHEET_NAME)
        
        # Очищаємо аркуш і записуємо нові дані разом із заголовками
        worksheet.clear()
        
        # Перетворюємо DataFrame у формат для запису (заголовки + рядки)
        data_to_write = [df.columns.tolist()] + df.fillna("").values.tolist()
        worksheet.update(data_to_write)
        return True
    except Exception as e:
        st.error(f"Помилка збереження даних у Google Таблицю: {e}")
        return False

# Завантажуємо актуальні дані при відкритті сторінки
with st.spinner("Завантаження даних із Google Таблиці..."):
    config_df = load_data_from_gsheets()

# Якщо аркуш порожній, створюємо базову структуру
if config_df.empty:
    config_df = pd.DataFrame([
        {
            "Зрошувальний модуль": "Модуль 1-3",
            "Площа, га": 2.5,
            "Проектна продуктивність зрошення, куб. м./га": 3000,
            "Свердловина для зрошення": "Свердловина 1",
            "Свердловина для зрошення Резервна": "Резерв 2",
            "Рік посадки": 2022,
            "Сорт": "Фундук",
            "Запилювач 1": "Трапезунд",
            "Запилювач 2": "Косфорд",
            "Кількість Сортових дерев, шт": 1250,
            "Кількість запилювача 1, шт": 125,
            "Кількість запилювача 2, шт": 125,
            "Нотатки": "Основна ділянка"
        }
    ])

st.subheader("📋 Редагування параметрів модулів та систем")
st.markdown("Ви можете змінювати значення клітинок прямо в таблиці, додавати нові рядки або видаляти непотрібні.")

edited_df = st.data_editor(
    config_df,
    num_rows="dynamic",
    use_container_width=True,
    key="config_editor"
)

# Кнопка збереження змін у Google Таблицю
if st.button("💾 Зберегти зміни в Google Таблицю", type="primary"):
    with st.spinner("Зберігаємо зміни в Google Таблицю..."):
        success = save_data_to_gsheets(edited_df)
        if success:
            st.success("Параметри успішно збережено безпосередньо у вашу Google Таблицю!")
            # Оновлюємо кеш, щоб бачити свіжі дані
            st.rerun()
