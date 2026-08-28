import streamlit as st

st.set_page_config(
    page_title="FMS AgronomOk - Управління іригацією",
    page_icon="💧",
    layout="wide",
)

# ============================================================
# МЕНЮ
# ============================================================

pg = st.navigation([
    st.Page(
        "pages/00_Irrigation.py",
        title="Зрошення",
        icon="💧",
    ),

    st.Page(
        "pages/01_Field_Parameters.py",
        title="Параметри полів",
        icon="⚙️",
    ),

    st.Page(
        "pages/02_Irrigation_Control.py",
        title="Керування приладами",
        icon="🎛️",
    ),

    st.Page(
        "pages/03_Tuya_Diagnostic.py",
        title="Діагностика Tuya",
        icon="🔎",
    ),
])

pg.run()
