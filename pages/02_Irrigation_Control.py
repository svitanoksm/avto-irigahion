import streamlit as st
import logging

from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="Керування приладами",
    page_icon="🎛️",
    layout="wide",
)


# ============================================================
# TUYA
# ============================================================

TUYA_LOGGER.setLevel(logging.ERROR)


# ============================================================
# НАЛАШТУВАННЯ РЕЛЕ
# ============================================================
#
# Перший фізичний прилад:
#
# bf5f66ac9135ce11fbhghn
#
# switch_1 → Модуль 1-3
# switch_2 → Модуль 1-4
# switch_3 → Модуль 1-5
# switch_4 → Резерв
#
# Інші три реле поки не підключені.
#
# Коли з'явиться другий фізичний прилад,
# для відповідних реле просто вкажемо його device_id.
#
# ============================================================

RELAYS = {

    "Модуль 1-3": {
        "device_id": "bf5f66ac9135ce11fbhghn",
        "code": "switch_1",
    },

    "Модуль 1-4": {
        "device_id": "bf5f66ac9135ce11fbhghn",
        "code": "switch_2",
    },

    "Модуль 1-5": {
        "device_id": "bf5f66ac9135ce11fbhghn",
        "code": "switch_3",
    },

    "Модуль 1-2": {
        "device_id": "",
        "code": "",
    },

    "Модуль 1-16": {
        "device_id": "",
        "code": "",
    },

    "Модуль 1-17": {
        "device_id": "",
        "code": "",
    },

    "Резерв": {
        "device_id": "bf5f66ac9135ce11fbhghn",
        "code": "switch_4",
    },

}


# ============================================================
# ПІДКЛЮЧЕННЯ TUYA
# ============================================================

@st.cache_resource
def create_tuya_api():

    try:

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

    except Exception as e:

        logging.error(
            f"Tuya connection error: {e}"
        )

        return None


# ============================================================
# TUYA API
# ============================================================

tuya = create_tuya_api()


# ============================================================
# ОТРИМАННЯ СТАНУ ПРИСТРОЮ
# ============================================================

def get_device_status(device_id):

    if not tuya:
        return None

    if not device_id:
        return None

    try:

        uri = (
            f"/v1.0/iot-03/devices/"
            f"{device_id}/status"
        )

        response = tuya.get(uri)

        if not isinstance(
            response,
            dict,
        ):
            return None

        if not response.get(
            "success",
            False,
        ):
            logging.error(
                f"Tuya status error: {response}"
            )

            return None

        result = response.get(
            "result",
            [],
        )

        if not isinstance(
            result,
            list,
        ):
            return None

        return result

    except Exception as e:

        logging.error(
            f"Tuya GET status error: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ СТАНУ КОНКРЕТНОГО РЕЛЕ
# ============================================================

def get_relay_state(
    device_id,
    code,
):

    if not device_id or not code:
        return None

    statuses = get_device_status(
        device_id
    )

    if statuses is None:
        return None

    for item in statuses:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if item.get("code") == code:

            value = item.get(
                "value"
            )

            if isinstance(
                value,
                bool,
            ):
                return value

            # Додатковий захист.
            #
            # Деякі пристрої можуть повертати
            # значення як текст.

            if isinstance(
                value,
                str,
            ):

                text = value.strip().lower()

                if text in [
                    "true",
                    "1",
                    "on",
                ]:
                    return True

                if text in [
                    "false",
                    "0",
                    "off",
                ]:
                    return False

            return None

    return None


# ============================================================
# ВІДПРАВЛЕННЯ КОМАНДИ РЕЛЕ
# ============================================================

def set_relay_state(
    device_id,
    code,
    state,
):

    if not tuya:
        return False

    if not device_id or not code:
        return False

    try:

        uri = (
            f"/v1.0/iot-03/devices/"
            f"{device_id}/commands"
        )

        body = {
            "commands": [
                {
                    "code": code,
                    "value": bool(state),
                }
            ]
        }

        response = tuya.post(
            uri,
            body,
        )

        if not isinstance(
            response,
            dict,
        ):
            return False

        if not response.get(
            "success",
            False,
        ):

            logging.error(
                f"Tuya command error: "
                f"{response}"
            )

            return False

        return True

    except Exception as e:

        logging.error(
            f"Tuya POST command error: {e}"
        )

        return False


# ============================================================
# ЗАГОЛОВОК
# ============================================================

st.title(
    "🎛️ Керування приладами"
)

st.caption(
    "Ручне керування реле через Tuya Cloud."
)


# ============================================================
# СТАН ПІДКЛЮЧЕННЯ TUYA
# ============================================================

if tuya:

    st.success(
        "🟢 Tuya Cloud підключена"
    )

else:

    st.error(
        "🔴 Немає зв'язку з Tuya Cloud"
    )


# ============================================================
# КІЛЬКІСТЬ РЕЛЕ
# ============================================================

st.markdown(
    "### 🔌 Реле"
)

st.write(
    f"Всього реле: **{len(RELAYS)}**"
)


# ============================================================
# КНОПКА ОНОВЛЕННЯ
# ============================================================

if st.button(
    "🔄 Оновити стани",
    use_container_width=True,
):

    st.rerun()


# ============================================================
# ОТРИМАННЯ СТАНІВ
# ============================================================

relay_states = {}


for relay_name, config in RELAYS.items():

    device_id = config["device_id"]
    code = config["code"]

    if not device_id or not code:

        relay_states[relay_name] = None

        continue

    relay_states[relay_name] = get_relay_state(
        device_id,
        code,
    )


# ============================================================
# ВИВЕДЕННЯ РЕЛЕ
# ============================================================

for relay_name, config in RELAYS.items():

    device_id = config["device_id"]
    code = config["code"]

    current_state = relay_states.get(
        relay_name
    )


    # ========================================================
    # КАРТКА
    # ========================================================

    with st.container(
        border=True
    ):

        col1, col2 = st.columns(
            [3, 1]
        )


        # ====================================================
        # НАЗВА
        # ====================================================

        with col1:

            st.markdown(
                f"### 🔌 {relay_name}"
            )

            if device_id and code:

                st.caption(
                    f"Код Tuya: `{code}`"
                )

            else:

                st.caption(
                    "Прилад ще не підключений."
                )


        # ====================================================
        # TOGGLE
        # ====================================================

        with col2:

            if not device_id or not code:

                st.warning(
                    "Не підключено"
                )

            elif current_state is None:

                st.warning(
                    "Стан недоступний"
                )

            else:

                new_state = st.toggle(
                    "Включено",
                    value=current_state,
                    key=f"relay_toggle_{relay_name}",
                )

                # --------------------------------------------
                # Якщо користувач змінив стан
                # --------------------------------------------

                if new_state != current_state:

                    success = set_relay_state(
                        device_id=device_id,
                        code=code,
                        state=new_state,
                    )

                    if success:

                        # ------------------------------------
                        # Перевіряємо фактичний стан
                        # ------------------------------------

                        actual_state = get_relay_state(
                            device_id,
                            code,
                        )

                        if actual_state == new_state:

                            if new_state:

                                st.success(
                                    "🟢 Увімкнено"
                                )

                            else:

                                st.success(
                                    "🔴 Вимкнено"
                                )

                        else:

                            st.warning(
                                "Команду відправлено, "
                                "але стан ще не підтверджено."
                            )

                    else:

                        st.error(
                            "❌ Не вдалося "
                            "відправити команду Tuya."
                        )


        # ====================================================
        # СТАТУС
        # ====================================================

        if device_id and code:

            if current_state is True:

                st.success(
                    "🟢 Реле увімкнене"
                )

            elif current_state is False:

                st.error(
                    "🔴 Реле вимкнене"
                )

            else:

                st.warning(
                    "⚠️ Неможливо отримати "
                    "поточний стан"
                )

        else:

            st.info(
                "ℹ️ Для цього реле ще не задано "
                "device_id та code."
            )


# ============================================================
# ІНФОРМАЦІЯ
# ============================================================

st.markdown("---")

st.caption(
    "Керування здійснюється через Tuya Cloud. "
    "Зміна стану перемикача відправляє команду "
    "безпосередньо відповідному каналу реле."
)
