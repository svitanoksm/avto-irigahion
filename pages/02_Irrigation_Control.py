import streamlit as st
import datetime
import time
import logging

from tuya_connector import TuyaOpenAPI, TUYA_LOGGER


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="Керування зрошенням",
    page_icon="💧",
    layout="wide",
)


# ============================================================
# КОНСТАНТИ
# ============================================================

SWITCH_CODE = "switch"

MAX_SCHEDULES = 30

# Часова зона України
TIMEZONE_ID = "Europe/Kyiv"

# Поточний UTC+3 у літній період.
# Tuya використовує timezone_id для роботи з часовою зоною.
TIME_ZONE = "+03:00"

# Категорія таймерів
TIMER_CATEGORY = "timer"


# ============================================================
# ЗАГАЛЬНІ ФУНКЦІЇ
# ============================================================

def get_tuya_settings():
    """
    Отримання налаштувань Tuya зі st.secrets.
    """

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

        device_id = str(
            conf["breaker_device_id"]
        ).strip()

        return (
            access_id,
            access_key,
            endpoint,
            device_id
        )

    except Exception as e:

        st.error(
            "❌ Не вдалося прочитати налаштування Tuya."
        )

        st.code(
            str(e)
        )

        st.stop()


@st.cache_resource
def create_tuya_api(
    endpoint,
    access_id,
    access_key
):
    """
    Створення підключення до Tuya Cloud.
    """

    TUYA_LOGGER.setLevel(
        logging.ERROR
    )

    api = TuyaOpenAPI(
        endpoint,
        access_id,
        access_key
    )

    api.connect()

    return api


# ============================================================
# ПІДКЛЮЧЕННЯ TUYA
# ============================================================

(
    ACCESS_ID,
    ACCESS_KEY,
    API_ENDPOINT,
    BREAKER_ID
) = get_tuya_settings()


try:

    tuya = create_tuya_api(
        API_ENDPOINT,
        ACCESS_ID,
        ACCESS_KEY
    )

except Exception as e:

    st.error(
        "❌ Не вдалося підключитися до Tuya Cloud."
    )

    st.code(
        str(e)
    )

    st.stop()


# ============================================================
# API GET
# ============================================================

def tuya_get(
    uri
):
    """
    GET-запит до Tuya.
    """

    try:

        return tuya.get(
            uri
        )

    except Exception as e:

        st.error(
            f"Помилка Tuya GET: {e}"
        )

        return None


# ============================================================
# API POST
# ============================================================

def tuya_post(
    uri,
    body
):
    """
    POST-запит до Tuya.
    """

    try:

        return tuya.post(
            uri,
            body
        )

    except Exception as e:

        st.error(
            f"Помилка Tuya POST: {e}"
        )

        return None


# ============================================================
# API PUT
# ============================================================

def tuya_put(
    uri,
    body
):
    """
    PUT-запит до Tuya.
    """

    try:

        return tuya.put(
            uri,
            body
        )

    except Exception as e:

        st.error(
            f"Помилка Tuya PUT: {e}"
        )

        return None


# ============================================================
# API DELETE
# ============================================================

def tuya_delete(
    uri
):
    """
    DELETE-запит до Tuya.
    """

    try:

        return tuya.delete(
            uri
        )

    except Exception as e:

        st.error(
            f"Помилка Tuya DELETE: {e}"
        )

        return None


# ============================================================
# ОТРИМАННЯ ПОТОЧНОГО СТАНУ АВТОМАТА
# ============================================================

def get_switch_state():
    """
    Отримує реальний стан DP switch.
    """

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/status"
    )

    response = tuya_get(
        uri
    )

    if not isinstance(
        response,
        dict
    ):
        return None

    if not response.get(
        "success"
    ):
        return None

    statuses = response.get(
        "result",
        []
    )

    for item in statuses:

        if item.get(
            "code"
        ) == SWITCH_CODE:

            value = item.get(
                "value"
            )

            if isinstance(
                value,
                bool
            ):

                return value

    return None


# ============================================================
# КЕРУВАННЯ АВТОМАТОМ
# ============================================================

def set_switch_state(
    state
):
    """
    Вмикає або вимикає автомат.
    """

    uri = (
        f"/v1.0/iot-03/devices/"
        f"{BREAKER_ID}/commands"
    )

    body = {
        "commands": [
            {
                "code": SWITCH_CODE,
                "value": state
            }
        ]
    }

    response = tuya_post(
        uri,
        body
    )

    if not isinstance(
        response,
        dict
    ):
        return False

    return bool(
        response.get(
            "success",
            False
        )
    )


# ============================================================
# ДОПОМІЖНІ ФУНКЦІЇ ДЛЯ РОЗКЛАДУ
# ============================================================

WEEKDAYS = [
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
]


def days_to_loops(
    selected_days
):
    """
    Перетворює дні тижня у формат Tuya.

    Tuya:
    0000000 = немає повторення
    1000000 = неділя
    0100000 = понеділок
    0010000 = вівторок
    ...
    0000001 = субота

    Тобто порядок:
    Нд Пн Вт Ср Чт Пт Сб
    """

    day_indexes = {
        "Неділя": 0,
        "Понеділок": 1,
        "Вівторок": 2,
        "Середа": 3,
        "Четвер": 4,
        "П'ятниця": 5,
        "Субота": 6,
    }

    loops = [
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
    ]

    for day in selected_days:

        if day in day_indexes:

            index = day_indexes[day]

            loops[index] = "1"

    return "".join(
        loops
    )


def loops_to_days(
    loops
):
    """
    Перетворює Tuya loops у назви днів.
    """

    if not loops:
        return []

    if loops == "0000000":
        return []

    names = [
        "Неділя",
        "Понеділок",
        "Вівторок",
        "Середа",
        "Четвер",
        "П'ятниця",
        "Субота",
    ]

    result = []

    for index, value in enumerate(
        loops
    ):

        if value == "1":

            result.append(
                names[index]
            )

    return result


def format_days(
    loops
):
    """
    Гарно відображає дні.
    """

    days = loops_to_days(
        loops
    )

    if not days:

        return "Одноразово"

    return ", ".join(
        days
    )


# ============================================================
# ОТРИМАННЯ РОЗКЛАДУ TUYA
# ============================================================

def get_schedules():
    """
    Отримує всі таймери пристрою.

    Використовується Tuya Timer API.
    """

    uri = (
        f"/v1.0/devices/"
        f"{BREAKER_ID}/timers"
    )

    response = tuya_get(
        uri
    )

    if not isinstance(
        response,
        dict
    ):
        return []

    if not response.get(
        "success"
    ):
        return []

    result = response.get(
        "result",
        []
    )

    schedules = []

    # У Tuya відповідь може бути
    # вкладена у groups.
    if isinstance(
        result,
        list
    ):

        for group in result:

            if not isinstance(
                group,
                dict
            ):
                continue

            groups = group.get(
                "groups",
                []
            )

            if groups:

                for timer_group in groups:

                    if not isinstance(
                        timer_group,
                        dict
                    ):
                        continue

                    timers = timer_group.get(
                        "timers",
                        []
                    )

                    for timer in timers:

                        timer_copy = dict(
                            timer
                        )

                        timer_copy[
                            "group_id"
                        ] = timer_group.get(
                            "group_id"
                        )

                        timer_copy[
                            "group_alias"
                        ] = timer_group.get(
                            "alias_name",
                            ""
                        )

                        schedules.append(
                            timer_copy
                        )

            else:

                timers = group.get(
                    "timers",
                    []
                )

                for timer in timers:

                    schedules.append(
                        timer
                    )

    return schedules


# ============================================================
# ДОДАВАННЯ РОЗКЛАДУ
# ============================================================

def add_schedule(
    name,
    schedule_time,
    selected_days,
    switch_state
):
    """
    Створює один таймер у Tuya Cloud.
    """

    loops = days_to_loops(
        selected_days
    )

    # Якщо дні не вибрані,
    # це одноразове завдання.
    if not selected_days:

        loops = "0000000"

    body = {
        "category": TIMER_CATEGORY,
        "loops": loops,
        "time_zone": TIME_ZONE,
        "timezone_id": TIMEZONE_ID,
        "alias_name": name,
        "instruct": [
            {
                "functions": [
                    {
                        "code": SWITCH_CODE,
                        "value": switch_state
                    }
                ],
                "date": "",
                "time": (
                    f"{schedule_time.hour}:"
                    f"{schedule_time.minute}"
                )
            }
        ]
    }

    uri = (
        f"/v1.0/devices/"
        f"{BREAKER_ID}/timers"
    )

    response = tuya_post(
        uri,
        body
    )

    return response


# ============================================================
# ВИДАЛЕННЯ РОЗКЛАДУ
# ============================================================

def delete_schedule(
    group_id
):
    """
    Видаляє групу таймера.
    """

    if not group_id:
        return False

    uri = (
        f"/v1.0/devices/"
        f"{BREAKER_ID}/timers/"
        f"categories/{TIMER_CATEGORY}/"
        f"groups/{group_id}"
    )

    response = tuya_delete(
        uri
    )

    if not isinstance(
        response,
        dict
    ):
        return False

    return bool(
        response.get(
            "success",
            False
        )
    )


# ============================================================
# УВІМКНЕННЯ / ВИМКНЕННЯ РОЗКЛАДУ
# ============================================================

def set_schedule_status(
    group_id,
    enabled
):
    """
    Вмикає або вимикає групу таймера.
    """

    if not group_id:
        return False

    uri = (
        f"/v1.0/devices/"
        f"{BREAKER_ID}/timers/"
        f"categories/{TIMER_CATEGORY}/"
        f"groups/{group_id}/status"
    )

    body = {
        "status": bool(
            enabled
        )
    }

    response = tuya_put(
        uri,
        body
    )

    if not isinstance(
        response,
        dict
    ):
        return False

    return bool(
        response.get(
            "success",
            False
        )
    )


# ============================================================
# ОТРИМУЄМО СТАН АВТОМАТА
# ============================================================

current_state = get_switch_state()


# ============================================================
# ЗАГОЛОВОК
# ============================================================

st.title(
    "💧 Керування зрошенням"
)

st.subheader(
    "1 свердловина"
)


# ============================================================
# ПОТОЧНИЙ СТАН
# ============================================================

st.markdown(
    "### ⚡ Автоматичний вимикач"
)


state_col, control_col = st.columns(
    [1, 2]
)


with state_col:

    st.markdown(
        "#### Поточний стан"
    )

    if current_state is True:

        st.success(
            "🟢 УВІМКНЕНО"
        )

    elif current_state is False:

        st.error(
            "🔴 ВИМКНЕНО"
        )

    else:

        st.warning(
            "⚠️ Стан недоступний"
        )


with control_col:

    st.markdown(
        "#### Керування"
    )

    on_col, off_col = st.columns(
        2
    )


    with on_col:

        if st.button(
            "🟢 УВІМКНУТИ",
            use_container_width=True,
            type="primary",
            key="main_switch_on"
        ):

            success = set_switch_state(
                True
            )

            if success:

                st.success(
                    "Автомат увімкнено."
                )

                time.sleep(
                    0.5
                )

                st.rerun()

            else:

                st.error(
                    "Не вдалося увімкнути автомат."
                )


    with off_col:

        if st.button(
            "🔴 ВИМКНУТИ",
            use_container_width=True,
            key="main_switch_off"
        ):

            success = set_switch_state(
                False
            )

            if success:

                st.success(
                    "Автомат вимкнено."
                )

                time.sleep(
                    0.5
                )

                st.rerun()

            else:

                st.error(
                    "Не вдалося вимкнути автомат."
                )


# ============================================================
# РОЗКЛАД
# ============================================================

st.markdown("---")

st.subheader(
    "⏰ Розклад роботи"
)

st.caption(
    f"Можна створити до {MAX_SCHEDULES} завдань."
)


# ============================================================
# ЗАВАНТАЖУЄМО ІСНУЮЧІ ЗАВДАННЯ
# ============================================================

schedules = get_schedules()


# Обмежуємо кількість показаних завдань
schedules = schedules[
    :MAX_SCHEDULES
]


# ============================================================
# КІЛЬКІСТЬ
# ============================================================

st.write(
    f"Створено завдань: "
    f"**{len(schedules)} / {MAX_SCHEDULES}**"
)


# ============================================================
# ДОДАВАННЯ НОВОГО ЗАВДАННЯ
# ============================================================

if len(schedules) < MAX_SCHEDULES:

    with st.expander(
        "➕ Додати завдання",
        expanded=True
    ):

        with st.form(
            key="add_schedule_form",
            clear_on_submit=True
        ):

            name = st.text_input(
                "Назва завдання",
                placeholder=(
                    "Наприклад: Ранковий полив"
                )
            )

            col1, col2 = st.columns(
                2
            )

            with col1:

                schedule_time = st.time_input(
                    "Час виконання",
                    value=datetime.time(
                        8,
                        0
                    )
                )

            with col2:

                switch_state = st.selectbox(
                    "Дія",
                    [
                        True,
                        False
                    ],
                    format_func=lambda x:
                        "🟢 Увімкнути"
                        if x
                        else
                        "🔴 Вимкнути"
                )

            selected_days = st.multiselect(
                "Дні виконання",
                WEEKDAYS,
                help=(
                    "Якщо не вибрати жодного дня, "
                    "завдання буде одноразовим."
                )
            )

            submitted = st.form_submit_button(
                "💾 Додати завдання",
                use_container_width=True,
                type="primary"
            )


            if submitted:

                if not name.strip():

                    st.error(
                        "Введіть назву завдання."
                    )

                elif selected_days:

                    response = add_schedule(
                        name.strip(),
                        schedule_time,
                        selected_days,
                        switch_state
                    )

                    if (
                        isinstance(
                            response,
                            dict
                        )
                        and response.get(
                            "success"
                        )
                    ):

                        st.success(
                            "✅ Завдання успішно "
                            "додано до Tuya Cloud."
                        )

                        time.sleep(
                            0.5
                        )

                        st.rerun()

                    else:

                        st.error(
                            "❌ Tuya не змогла "
                            "створити завдання."
                        )

                        if response:

                            st.json(
                                response
                            )

                else:

                    response = add_schedule(
                        name.strip(),
                        schedule_time,
                        selected_days,
                        switch_state
                    )

                    if (
                        isinstance(
                            response,
                            dict
                        )
                        and response.get(
                            "success"
                        )
                    ):

                        st.success(
                            "✅ Одноразове завдання "
                            "успішно додано."
                        )

                        time.sleep(
                            0.5
                        )

                        st.rerun()

                    else:

                        st.error(
                            "❌ Tuya не змогла "
                            "створити завдання."
                        )

                        if response:

                            st.json(
                                response
                            )

else:

    st.warning(
        "Досягнуто максимальну кількість "
        f"завдань: {MAX_SCHEDULES}."
    )


# ============================================================
# СПИСОК ЗАВДАНЬ
# ============================================================

st.markdown("---")

st.subheader(
    "📋 Заплановані завдання"
)


if not schedules:

    st.info(
        "Завдань поки немає."
    )

else:

    for index, schedule in enumerate(
        schedules,
        start=1
    ):

        # ----------------------------------------------------
        # ID
        # ----------------------------------------------------

        group_id = schedule.get(
            "group_id"
        )

        timer_id = schedule.get(
            "id"
        )

        # ----------------------------------------------------
        # НАЗВА
        # ----------------------------------------------------

        name = schedule.get(
            "alias_name",
            ""
        )

        if not name:

            name = schedule.get(
                "group_alias",
                ""
            )

        if not name:

            name = (
                f"Завдання {index}"
            )

        # ----------------------------------------------------
        # ЧАС
        # ----------------------------------------------------

        task_time = schedule.get(
            "time",
            "—"
        )

        # ----------------------------------------------------
        # ДНІ
        # ----------------------------------------------------

        loops = schedule.get(
            "loops",
            "0000000"
        )

        days_text = format_days(
            loops
        )

        # ----------------------------------------------------
        # СТАН
        # ----------------------------------------------------

        status = schedule.get(
            "status",
            1
        )

        enabled = (
            status == 1
            or status is True
        )

        # ----------------------------------------------------
        # ДІЯ
        # ----------------------------------------------------

        action_text = "—"

        # У старому API інформація про
        # функції може бути у timer/group.
        functions = schedule.get(
            "functions",
            []
        )

        if functions:

            for function in functions:

                if function.get(
                    "code"
                ) == SWITCH_CODE:

                    value = function.get(
                        "value"
                    )

                    if value is True:

                        action_text = (
                            "🟢 Увімкнути"
                        )

                    elif value is False:

                        action_text = (
                            "🔴 Вимкнути"
                        )

        # ----------------------------------------------------
        # ВІДОБРАЖЕННЯ
        # ----------------------------------------------------

        with st.container(
            border=True
        ):

            top1, top2, top3, top4 = st.columns(
                [0.6, 2.2, 1.3, 1.5]
            )

            with top1:

                st.markdown(
                    f"### {index}"
                )

            with top2:

                st.markdown(
                    f"**{name}**"
                )

                st.caption(
                    days_text
                )

            with top3:

                st.markdown(
                    f"### {task_time}"
                )

                st.caption(
                    action_text
                )

            with top4:

                if enabled:

                    st.success(
                        "🟢 Активне"
                    )

                else:

                    st.warning(
                        "⏸️ Вимкнене"
                    )


            action1, action2 = st.columns(
                2
            )


            # ------------------------------------------------
            # УВІМКНЕННЯ / ВИМКНЕННЯ ЗАВДАННЯ
            # ------------------------------------------------

            with action1:

                if enabled:

                    if st.button(
                        "⏸️ Вимкнути завдання",
                        key=(
                            f"disable_{group_id}_"
                            f"{timer_id}"
                        ),
                        use_container_width=True
                    ):

                        if set_schedule_status(
                            group_id,
                            False
                        ):

                            st.success(
                                "Завдання вимкнено."
                            )

                            time.sleep(
                                0.4
                            )

                            st.rerun()

                        else:

                            st.error(
                                "Не вдалося "
                                "вимкнути завдання."
                            )

                else:

                    if st.button(
                        "▶️ Увімкнути завдання",
                        key=(
                            f"enable_{group_id}_"
                            f"{timer_id}"
                        ),
                        use_container_width=True
                    ):

                        if set_schedule_status(
                            group_id,
                            True
                        ):

                            st.success(
                                "Завдання увімкнено."
                            )

                            time.sleep(
                                0.4
                            )

                            st.rerun()

                        else:

                            st.error(
                                "Не вдалося "
                                "увімкнути завдання."
                            )


            # ------------------------------------------------
            # ВИДАЛЕННЯ
            # ------------------------------------------------

            with action2:

                if st.button(
                    "🗑️ Видалити",
                    key=(
                        f"delete_{group_id}_"
                        f"{timer_id}"
                    ),
                    use_container_width=True
                ):

                    if delete_schedule(
                        group_id
                    ):

                        st.success(
                            "Завдання видалено."
                        )

                        time.sleep(
                            0.4
                        )

                        st.rerun()

                    else:

                        st.error(
                            "Не вдалося "
                            "видалити завдання."
                        )


# ============================================================
# ОНОВЛЕННЯ
# ============================================================

st.markdown("---")

if st.button(
    "🔄 Оновити стан і розклад",
    use_container_width=True
):

    st.rerun()
