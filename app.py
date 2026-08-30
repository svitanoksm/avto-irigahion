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
        title="Аналітика зрошення",
        icon="💧",
    ),

     st.Page(
        "pages/02_Irrigation_Control.py",
        title="Керування Свердловинами",
        icon="🎛️",
    ),

    st.Page(
        "pages/keruvannya_zroshennyam_modulnyi_planuvalnyk.py",
        title="Розклад зрошення Свердловина 1",
        icon="🔎",
    ),

    st.Page(
        "pages/01_Field_Parameters.py",
        title="Параметри полів",
        icon="⚙️",
    ),
])

pg.run()
