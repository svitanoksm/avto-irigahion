import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Параметри полів та систем", page_icon="⚙️", layout="wide")

st.title("⚙️ Параметри полів, модулів та іригаційних систем")
st.markdown("""
Тут ви можете налаштовувати довідкові дані: площі модулів, культури, схеми садіння (кількість дерев на гектар) 
та характеристики крапельної стрічки. Усі зміни автоматично зберігаються у файл та використовуються в розрахунках.
""")

CONFIG_FILE = "modules_config.csv"

# Початкові дані за замовчуванням (якщо файлу ще немає)
default_data = pd.DataFrame([
    {
        "Модуль / Ділянка": "Модуль 1",
        "Культура / Сорт": "Фундук",
        "Площа (га)": 15.0,
        "Кількість дерев / га": 500,
        "Крапельна стрічка (л/год на емітер)": 2.0,
        "Крок емітерів (м)": 0.5,
        "Примітки": "Основна ділянка"
    }
])

# Завантаження збережених даних або створення файлу за замовчуванням
if os.path.exists(CONFIG_FILE):
    try:
        config_df = pd.read_csv(CONFIG_FILE)
    except Exception:
        config_df = default_data
else:
    config_df = default_data

# Інтерактивна таблиця для редагування
st.subheader("📋 Редагування параметрів модулів")
st.markdown("Ви можете змінювати значення клітинок прямо в таблиці, додавати нові рядки або видаляти непотрібні за допомогою галочок зліва.")

edited_df = st.data_editor(
    config_df,
    num_rows="dynamic",
    use_container_width=True,
    key="config_editor"
)

# Кнопка збереження змін
if st.button("💾 Зберегти зміни", type="primary"):
    edited_df.to_csv(CONFIG_FILE, index=False)
    st.success("Параметри успішно збережено у систему!")
