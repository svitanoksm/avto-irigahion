import streamlit as st
import datetime

st.set_page_config(
    page_title="Керування приладами та іригацією",
    page_icon="🎛️",
    layout="wide",
)

st.title("🎛️ Панель керування приладами (Свердловина 1)")
st.markdown("""
Тут ви можете здійснювати увімкнення та вимкнення приладів **1 свердловини** в ручному режимі або налаштовувати для них розклад роботи.
""")

# Секція 1: Керування першою свердловиною
st.header("1 свердловина")

st.markdown("---")

# --- 1. Автоматичний вимикач ---
st.subheader("⚡ Автоматичний вимикач (1 свердловина Автоматичний вимикач)")

col_state, col_sched = st.columns([1, 2])

with col_state:
    st.markdown("##### Ручне керування")
    breaker_state = st.toggle("Увімкнути/Ввімкнути вимикач", key="breaker_toggle")
    if breaker_state:
        st.success("Стан: УВІМКНЕНО")
    else:
        st.error("Стан: ВИМКНЕНО")

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

modules = ["Модуль 1-3", "Модуль 1-4", "Модуль 1-5", "Резерв"]

for mod in modules:
    st.markdown(f"#### 📌 {mod}")
    
    r_col1, r_col2 = st.columns([1, 2])
    
    with r_col1:
        st.markdown("##### Стан")
        mod_state = st.toggle(f"Живлення {mod}", key=f"toggle_{mod}")
        if mod_state:
            st.success(f"{mod}: УВІМКНЕНО")
        else:
            st.warning(f"{mod}: ВИМКНЕНО")
            
    with r_col2:
        st.markdown("##### Розклад роботи")
        with st.form(key=f"form_{mod}"):
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                m_on_time = st.time_input("Увімкнути о", datetime.time(6, 0), key=f"on_{mod}")
            with m_col2:
                m_off_time = st.time_input("Вимкнути о", datetime.time(12, 0), key=f"off_{mod}")
            
            m_days = st.multiselect(
                "Дні тижня",
                ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"],
                default=["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"],
                key=f"days_{mod}"
            )
            
            m_submitted = st.form_submit_button(f"Зберегти розклад для {mod}")
            if m_submitted:
                st.success(f"Розклад для {mod} успішно оновлено!")
                
    st.markdown("---")
