import streamlit as st

st.set_page_config(
    page_title="FMS AgronomOk - Управління іригацією",
    page_icon="💧",
    layout="wide",
)

# Налаштування красивого меню з кириличними назвами та іконками
pg = st.navigation([
    st.Page("pages/00_Irrigation.py", title="Зрошення", icon="💧"),
    st.Page("pages/01_Field_Parameters.py", title="Параметри полів", icon="⚙️"),
])

pg.run()
