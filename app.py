import streamlit as st
import pandas as pd
import gspread
import altair as alt
from google.oauth2.service_account import Credentials


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="FMS AgronomOk - Моніторинг свердловини",
    page_icon="💧",
    layout="wide"
)


# ============================================================
# НАЛАШТУВАННЯ GOOGLE SHEETS
# ============================================================

SPREADSHEET_NAME = "Автоматизація зрошення"
WORKSHEET_NAME = "Свердловина 1"


# ============================================================
# ФУНКЦІЯ ПЕРЕТВОРЕННЯ ЧИСЕЛ
# ============================================================

def convert_to_number(value):
    """
    Перетворює значення з Google Sheets у число.

    Підтримує:
    123.45
    123,45
    "123,45"
    "123,45 м³/год"
    "1 234,56"
    "1.234,56"
    "1,234.56"
    """

    if value is None:
        return None

    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return float(value)

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() in [
        "none",
        "nan",
        "null",
        "-",
        "—"
    ]:
        return None

    # Прибираємо пробіли
    value = value.replace(" ", "")
    value = value.replace("\xa0", "")

    # --------------------------------------------------------
    # Якщо одночасно є кома та крапка
    # --------------------------------------------------------

    if "," in value and "." in value:

        # 1.234,56
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")

        # 1,234.56
        else:
            value = value.replace(",", "")

    # --------------------------------------------------------
    # Якщо тільки кома
    # --------------------------------------------------------

    elif "," in value:

        value = value.replace(",", ".")

    # --------------------------------------------------------
    # Залишаємо тільки цифри, крапку та мінус
    # --------------------------------------------------------

    cleaned = ""

    for char in value:

        if char.isdigit() or char in ".-":
            cleaned += char

    if cleaned in [
        "",
        "-",
        ".",
        "-."
    ]:
        return None

    try:

        return float(cleaned)

    except ValueError:

        return None


# ============================================================
# ПОШУК СТОВПЦЯ
# ============================================================

def find_column(df, exact_names=None, contains=None):

    exact_names = exact_names or []
    contains = contains or []

    # --------------------------------------------------------
    # 1. ТОЧНА НАЗВА
    # --------------------------------------------------------

    for name in exact_names:

        for col in df.columns:

            if str(col).strip().lower() == name.strip().lower():
                return col

    # --------------------------------------------------------
    # 2. ПОШУК ЗА ФРАГМЕНТОМ
    # --------------------------------------------------------

    for fragment in contains:

        fragment = fragment.lower()

        for col in df.columns:

            if fragment in str(col).lower():
                return col

    return None


# ============================================================
# ЗАВАНТАЖЕННЯ ДАНИХ
# ============================================================

@st.cache_data(ttl=60)
def load_data():

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]

    creds_dict = dict(
        st.secrets["gcp_service_account"]
    )

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES
    )

    client = gspread.authorize(creds)

    spreadsheet = client.open(
        SPREADSHEET_NAME
    )

    sheet = spreadsheet.worksheet(
        WORKSHEET_NAME
    )

    values = sheet.get_all_values(
        value_render_option="FORMATTED_VALUE"
    )

    if not values:
        return pd.DataFrame()

    # --------------------------------------------------------
    # ЗАГОЛОВКИ
    # --------------------------------------------------------

    headers = [
        str(h).strip()
        for h in values[0]
    ]

    rows = values[1:]

    df = pd.DataFrame(
        rows,
        columns=headers
    )

    # ========================================================
    # ДАТА
    # ========================================================

    date_col = find_column(
        df,
        exact_names=[
            "Дата та час"
        ],
        contains=[
            "дата"
        ]
    )

    if date_col:

        df["Дата та час"] = pd.to_datetime(
            df[date_col],
            errors="coerce",
            dayfirst=True
        )

    # ========================================================
    # ПОТУЖНІСТЬ
    # ========================================================

    power_col = find_column(
        df,
        exact_names=[
            "Потужність за період, кВт/год"
        ],
        contains=[
            "потужність"
        ]
    )

    if power_col:

        df["Потужність за період, кВт/год"] = (
            df[power_col]
            .apply(convert_to_number)
        )

    # ========================================================
    # ПРОДУКТИВНІСТЬ
    # ========================================================

    flow_col = find_column(
        df,
        exact_names=[
            "Продуктивність, куб. м./год",
            "Продуктивність, куб. м/год",
            "Продуктивність, м³/год",
            "Продуктивність"
        ],
        contains=[
            "продуктивність"
        ]
    )

    if flow_col:

        df["Продуктивність, куб. м./год"] = (
            df[flow_col]
            .apply(convert_to_number)
        )

    # ========================================================
    # ВИТРАТИ КВТ
    # ========================================================

    for col in list(df.columns):

        col_lower = str(col).lower()

        if (
            "витрати" in col_lower
            and "квт" in col_lower
        ):

            df[col] = (
                df[col]
                .apply(convert_to_number)
            )

    # ========================================================
    # ВИТРАТИ ВОДИ
    # ========================================================

    for col in list(df.columns):

        col_lower = str(col).lower()

        if (
            "витрати" in col_lower
            and (
                "м³" in col_lower
                or "куб" in col_lower
                or "м." in col_lower
            )
        ):

            df[col] = (
                df[col]
                .apply(convert_to_number)
            )

    # ========================================================
    # СОРТУВАННЯ
    # ========================================================

    if "Дата та час" in df.columns:

        df = df.sort_values(
            by="Дата та час"
        )

        df = df.reset_index(
            drop=True
        )

    return df


# ============================================================
# ЗАВАНТАЖЕННЯ ДАНИХ
# ============================================================

try:

    df = load_data()

except Exception as e:

    st.error(
        f"Помилка завантаження даних з Google Таблиці: {e}"
    )

    st.stop()


if df.empty:

    st.warning(
        "Google Таблиця не містить даних."
    )

    st.stop()


# ============================================================
# БОКОВЕ МЕНЮ
# ============================================================

st.sidebar.title(
    "💧 FMS AgronomOk"
)

st.sidebar.subheader(
    "Панель управління"
)

menu_option = st.sidebar.radio(
    "Перейти до:",
    [
        "Головна панель",
        "Поливні модулі"
    ]
)


# ============================================================
# ПОШУК СТОВПЦЯ МОДУЛЯ
# ============================================================

module_col = None

for col in df.columns:

    col_lower = str(col).lower()

    if (
        "модуль" in col_lower
        and "зрош" in col_lower
    ):

        module_col = col

        break


# ============================================================
# СПИСОК МОДУЛІВ
# ============================================================

if module_col:

    modules_list = (
        df[module_col]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    modules_list = [
        m
        for m in modules_list
        if m != "Вимкнено"
    ]

else:

    modules_list = []


# ============================================================
# ГОЛОВНА ПАНЕЛЬ
# ============================================================

if menu_option == "Головна панель":

    st.title(
        "📊 Загальний моніторинг свердловини"
    )

    latest = df.iloc[-1]

    col1, col2, col3, col4 = st.columns(4)

    # --------------------------------------------------------
    # СТАН
    # --------------------------------------------------------

    state_col = next(
        (
            c
            for c in df.columns
            if "стан" in str(c).lower()
        ),
        None
    )

    col1.metric(
        "Стан вимикача",
        latest.get(
            state_col,
            "Н/Д"
        )
        if state_col
        else "Н/Д"
    )

    # --------------------------------------------------------
    # ВИТРАТИ ВОДИ
    # --------------------------------------------------------

    water_col = next(
        (
            c
            for c in df.columns
            if (
                "витрати" in str(c).lower()
                and (
                    "м³" in str(c).lower()
                    or "куб" in str(c).lower()
                    or "м." in str(c).lower()
                )
            )
        ),
        None
    )

    water = (
        latest.get(
            water_col,
            0
        )
        if water_col
        else 0
    )

    water = convert_to_number(
        water
    )

    if water is None:
        water = 0

    col2.metric(
        "Загальні витрати води",
        f"{water:.2f} м³"
    )

    # --------------------------------------------------------
    # ЕНЕРГІЯ
    # --------------------------------------------------------

    energy_col = next(
        (
            c
            for c in df.columns
            if (
                "витрати" in str(c).lower()
                and "квт" in str(c).lower()
            )
        ),
        None
    )

    energy = (
        latest.get(
            energy_col,
            0
        )
        if energy_col
        else 0
    )

    energy = convert_to_number(
        energy
    )

    if energy is None:
        energy = 0

    col3.metric(
        "Загальна енергія",
        f"{energy:.2f} кВт"
    )

    # --------------------------------------------------------
    # МОДУЛЬ
    # --------------------------------------------------------

    col4.metric(
        "Поточний модуль",
        latest.get(
            module_col,
            "Н/Д"
        )
        if module_col
        else "Н/Д"
    )

    # --------------------------------------------------------
    # ОСТАННІ ЗАПИСИ
    # --------------------------------------------------------

    st.subheader(
        "Останні записи з таблиці"
    )

    st.dataframe(
        df.tail(10),
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# ПОЛИВНІ МОДУЛІ
# ============================================================

elif menu_option == "Поливні модулі":

    st.sidebar.markdown("---")

    st.sidebar.subheader(
        "Вибір модуля"
    )

    if (
        len(modules_list) > 0
        and module_col
    ):

        selected_module = st.sidebar.selectbox(
            "Оберіть зрошувальний модуль:",
            modules_list
        )

        st.title(
            f"⚙️ Моніторинг модуля: {selected_module}"
        )

        # ====================================================
        # ФІЛЬТР МОДУЛЯ
        # ====================================================

        df_filtered = df[
            df[module_col]
            .astype(str)
            .str.strip()
            == selected_module
        ].copy()

        if "Дата та час" in df_filtered.columns:

            df_filtered = df_filtered.sort_values(
                by="Дата та час"
            )

        # ====================================================
        # ЯКЩО ДАНИХ НЕМАЄ
        # ====================================================

        if df_filtered.empty:

            st.warning(
                "Немає даних для обраного модуля."
            )

        else:

            # =================================================
            # ПОШУК СТОВПЦЯ ВИТРАТ ЕЛЕКТРОЕНЕРГІЇ
            # =================================================

            energy_col = next(
                (
                    c
                    for c in df_filtered.columns
                    if (
                        "витрати" in str(c).lower()
                        and (
                            "квт" in str(c).lower()
                            or "квт/год" in str(c).lower()
                            or "квт·год" in str(c).lower()
                        )
                    )
                ),
                None
            )

            # =================================================
            # ПОШУК СТОВПЦЯ ВИТРАТ ВОДИ
            # =================================================

            water_col = next(
                (
                    c
                    for c in df_filtered.columns
                    if (
                        "витрати" in str(c).lower()
                        and (
                            "м³" in str(c).lower()
                            or "куб" in str(c).lower()
                            or "м." in str(c).lower()
                        )
                    )
                ),
                None
            )

            # =================================================
            # ГРАФІК ВИТРАТ ВОДИ ТА ЕЛЕКТРОЕНЕРГІЇ
            # =================================================

            st.subheader(
                "📊 Витрати електроенергії та води"
            )

            if (
                energy_col is not None
                and water_col is not None
                and "Дата та час" in df_filtered.columns
            ):

                # ------------------------------------------------
                # Створюємо окремий DataFrame для графіка
                # ------------------------------------------------

                chart_data = df_filtered[
                    [
                        "Дата та час",
                        energy_col,
                        water_col
                    ]
                ].copy()

                # ------------------------------------------------
                # Перетворюємо значення в числа
                # ------------------------------------------------

                chart_data["energy"] = (
                    chart_data[energy_col]
                    .apply(convert_to_number)
                )

                chart_data["water"] = (
                    chart_data[water_col]
                    .apply(convert_to_number)
                )

                # ------------------------------------------------
                # Видаляємо рядки без дати
                # ------------------------------------------------

                chart_data = chart_data.dropna(
                    subset=[
                        "Дата та час"
                    ]
                )

                # ------------------------------------------------
                # Формуємо дані у довгому форматі
                # ------------------------------------------------

                energy_chart = chart_data[
                    [
                        "Дата та час",
                        "energy"
                    ]
                ].copy()

                energy_chart["Тип"] = (
                    "Електроенергія"
                )

                energy_chart = energy_chart.rename(
                    columns={
                        "energy": "Значення"
                    }
                )

                water_chart = chart_data[
                    [
                        "Дата та час",
                        "water"
                    ]
                ].copy()

                water_chart["Тип"] = (
                    "Вода"
                )

                water_chart = water_chart.rename(
                    columns={
                        "water": "Значення"
                    }
                )

                chart_long = pd.concat(
                    [
                        energy_chart,
                        water_chart
                    ],
                    ignore_index=True
                )

                # ------------------------------------------------
                # Видаляємо порожні числові значення
                # ------------------------------------------------

                chart_long = chart_long.dropna(
                    subset=[
                        "Значення"
                    ]
                )

                # ------------------------------------------------
                # Якщо є дані — будуємо графік
                # ------------------------------------------------

                if not chart_long.empty:

                    chart_long["Дата"] = (
                        chart_long["Дата та час"]
                        .dt.strftime(
                            "%d.%m %H:%M"
                        )
                    )

                    # ------------------------------------------------
                    # Визначаємо максимальне значення
                    # ------------------------------------------------

                    chart_max = chart_long[
                        "Значення"
                    ].max()

                    if pd.isna(chart_max) or chart_max <= 0:
                        chart_max = 1

                    chart_y_max = chart_max * 1.10

                    # ------------------------------------------------
                    # ЗГРУПОВАНИЙ СТОВПЧАСТИЙ ГРАФІК
                    # ------------------------------------------------

                    chart = (
                        alt.Chart(
                            chart_long
                        )
                        .mark_bar(
                            size=14
                        )
                        .encode(

                            # ----------------------------------------
                            # ЧАС
                            # ----------------------------------------

                            x=alt.X(
                                "Дата та час:T",
                                title="Дата та час",
                                axis=alt.Axis(
                                    format="%H:%M",
                                    labelAngle=-45
                                )
                            ),

                            # ----------------------------------------
                            # ЗНАЧЕННЯ
                            # ----------------------------------------

                            y=alt.Y(
                                "Значення:Q",
                                title="Витрати",
                                scale=alt.Scale(
                                    domain=[
                                        0,
                                        chart_y_max
                                    ],
                                    nice=False
                                ),
                                axis=alt.Axis(
                                    format=".1f"
                                )
                            ),

                            # ----------------------------------------
                            # КОЛІР
                            # ----------------------------------------

                            color=alt.Color(
                                "Тип:N",
                                title="Показник",
                                scale=alt.Scale(
                                    domain=[
                                        "Електроенергія",
                                        "Вода"
                                    ],
                                    range=[
                                        "#E53935",
                                        "#1E88E5"
                                    ]
                                )
                            ),

                            # ----------------------------------------
                            # ЗСУВ СТОВПЦІВ
                            # ----------------------------------------

                            xOffset=alt.XOffset(
                                "Тип:N"
                            ),

                            # ----------------------------------------
                            # ПІДКАЗКА
                            # ----------------------------------------

                            tooltip=[
                                alt.Tooltip(
                                    "Дата та час:T",
                                    title="Дата та час",
                                    format="%d.%m.%Y %H:%M:%S"
                                ),

                                alt.Tooltip(
                                    "Тип:N",
                                    title="Показник"
                                ),

                                alt.Tooltip(
                                    "Значення:Q",
                                    title="Значення",
                                    format=".2f"
                                )
                            ]
                        )
                        .properties(
                            height=450
                        )
                    )

                    st.altair_chart(
                        chart,
                        use_container_width=True
                    )

                else:

                    st.info(
                        "Немає числових даних "
                        "для побудови графіка."
                    )

            elif energy_col is None:

                st.warning(
                    "Стовпчик витрат електроенергії не знайдено."
                )

            elif water_col is None:

                st.warning(
                    "Стовпчик витрат води не знайдено."
                )

            # =================================================
            # ПОКАЗНИКИ ПРОДУКТИВНОСТІ
            # =================================================

            st.subheader(
                "🌊 Продуктивність"
            )

            flow_col_name = (
                "Продуктивність, куб. м./год"
            )

            if flow_col_name in df_filtered.columns:

                flow_data = df_filtered[
                    [
                        "Дата та час",
                        flow_col_name
                    ]
                ].copy()

                flow_data[flow_col_name] = (
                    flow_data[flow_col_name]
                    .apply(convert_to_number)
                )

                flow_data = flow_data.dropna(
                    subset=[
                        "Дата та час",
                        flow_col_name
                    ]
                )

                if not flow_data.empty:

                    # ------------------------------------------------
                    # Аномальні значення не видаляємо з таблиці.
                    # Для графіка використовуємо тільки <= 200.
                    # ------------------------------------------------

                    flow_chart_data = flow_data[
                        flow_data[flow_col_name] <= 200
                    ].copy()

                    if not flow_chart_data.empty:

                        flow_chart_data = (
                            flow_chart_data
                            .rename(
                                columns={
                                    flow_col_name: "flow"
                                }
                            )
                        )

                        flow_max = (
                            flow_chart_data["flow"]
                            .max()
                        )

                        if (
                            pd.isna(flow_max)
                            or flow_max <= 0
                        ):
                            flow_max = 100

                        flow_y_max = (
                            flow_max * 1.10
                        )

                        flow_chart = (
                            alt.Chart(
                                flow_chart_data
                            )
                            .mark_line(
                                point=True
                            )
                            .encode(

                                x=alt.X(
                                    "Дата та час:T",
                                    title="Дата та час",
                                    axis=alt.Axis(
                                        format="%H:%M"
                                    )
                                ),

                                y=alt.Y(
                                    "flow:Q",
                                    title="м³/год",
                                    scale=alt.Scale(
                                        domain=[
                                            0,
                                            flow_y_max
                                        ],
                                        nice=False
                                    ),
                                    axis=alt.Axis(
                                        format=".1f"
                                    )
                                ),

                                tooltip=[
                                    alt.Tooltip(
                                        "Дата та час:T",
                                        title="Дата та час",
                                        format="%d.%m.%Y %H:%M:%S"
                                    ),

                                    alt.Tooltip(
                                        "flow:Q",
                                        title="Продуктивність",
                                        format=".2f"
                                    )
                                ]
                            )
                            .properties(
                                height=400
                            )
                        )

                        st.altair_chart(
                            flow_chart,
                            use_container_width=True
                        )

                    else:

                        st.info(
                            "Немає нормальних числових даних "
                            "для побудови графіка продуктивності."
                        )

                else:

                    st.info(
                        "Немає числових даних "
                        "для побудови графіка продуктивності."
                    )

            else:

                st.warning(
                    "Стовпчик продуктивності не знайдено."
                )

            # =================================================
            # ДЕТАЛЬНІ ДАНІ
            # =================================================

            with st.expander(
                "📋 Переглянути детальні дані по модулю"
            ):

                st.dataframe(
                    df_filtered,
                    use_container_width=True,
                    hide_index=True
                )

    else:

        st.warning(
            "Наразі не виявлено активних модулів у базі даних."
        )
