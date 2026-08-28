import streamlit as st
import pandas as pd
import logging

from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="Tuya діагностика",
    page_icon="🔎",
    layout="wide",
)


# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

DEVICE_ID = "bf5f66ac9135ce11fbhghn"

TUYA_LOGGER.setLevel(logging.ERROR)


# ============================================================
# ПІДКЛЮЧЕННЯ TUYA
# ============================================================

@st.cache_resource
def create_tuya_api():

    conf = st.secrets["tuya"]

    access_id = str(
        conf["access_id"]
    ).strip()

    access_key = str(
        conf["access_key"]
    ).strip()

    endpoint = str(
        conf["endpoint"]
    ).strip().rstrip("/")

    api = TuyaOpenAPI(
        endpoint,
        access_id,
        access_key,
    )

    api.connect()

    return api


# ============================================================
# ОТРИМАННЯ СТАНІВ ПРИСТРОЮ
# ============================================================

def get_device_status():

    try:

        tuya = create_tuya_api()

        uri = (
            f"/v1.0/iot-03/devices/"
            f"{DEVICE_ID}/status"
        )

        response = tuya.get(uri)

        return response

    except Exception as e:

        st.error(
            "❌ Помилка підключення або "
            "опитування Tuya."
        )

        st.code(str(e))

        return None


# ============================================================
# ЗАГОЛОВОК
# ============================================================

st.title(
    "🔎 Діагностика Tuya"
)

st.caption(
    "Отримання всіх доступних кодів та "
    "поточних значень пристрою."
)


# ============================================================
# DEVICE ID
# ============================================================

st.markdown(
    "### Пристрій"
)

st.code(
    DEVICE_ID
)


# ============================================================
# КНОПКА ОПИТУВАННЯ
# ============================================================

if st.button(
    "🔎 Опитати пристрій",
    use_container_width=True,
    type="primary",
):

    response = get_device_status()

    if response is None:

        st.stop()


    # ========================================================
    # ПОВНА ВІДПОВІДЬ TUYA
    # ========================================================

    with st.expander(
        "📦 Повна відповідь Tuya API",
        expanded=False,
    ):

        st.json(response)


    # ========================================================
    # ПЕРЕВІРКА ВІДПОВІДІ
    # ========================================================

    if not isinstance(
        response,
        dict,
    ):

        st.error(
            "❌ Tuya повернула "
            "некоректну відповідь."
        )

        st.stop()


    if not response.get(
        "success",
        False,
    ):

        st.error(
            "❌ Tuya API повернула помилку."
        )

        st.json(response)

        st.stop()


    # ========================================================
    # РЕЗУЛЬТАТ
    # ========================================================

    statuses = response.get(
        "result",
        [],
    )


    if not isinstance(
        statuses,
        list,
    ):

        st.error(
            "❌ Поле `result` має "
            "неочікуваний формат."
        )

        st.stop()


    st.success(
        f"✅ Отримано {len(statuses)} "
        f"параметрів пристрою."
    )


    # ========================================================
    # ФОРМУЄМО ТАБЛИЦЮ
    # ========================================================

    rows = []


    for item in statuses:

        if not isinstance(
            item,
            dict,
        ):
            continue


        rows.append(
            {
                "code": item.get(
                    "code",
                    "",
                ),
                "value": item.get(
                    "value",
                    "",
                ),
            }
        )


    # ========================================================
    # ВИВЕДЕННЯ
    # ========================================================

    if not rows:

        st.warning(
            "⚠️ Tuya не повернула "
            "параметрів пристрою."
        )

    else:

        df = pd.DataFrame(
            rows,
            columns=[
                "code",
                "value",
            ],
        )


        st.markdown(
            "### 📋 Коди та поточні значення"
        )


        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )


        # ====================================================
        # ТЕКСТОВИЙ СПИСОК
        # ====================================================

        st.markdown(
            "### 🔌 Доступні коди"
        )


        for row in rows:

            code = row["code"]

            value = row["value"]

            st.write(
                f"`{code}` → `{value}`"
            )
