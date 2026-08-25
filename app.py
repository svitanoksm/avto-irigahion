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

    if value.lower() in ["none", "nan", "null", "-", "—"]:
        return None

    # Прибираємо пробіли
    value = value.replace(" ", "")

    # Український/європейський десятковий роздільник
    value = value.replace(",", ".")

    # Залишаємо тільки цифри, крапку та мінус
    cleaned = ""

    for char in value:
        if char.isdigit() or char in ".-":
            cleaned += char

    if cleaned in ["", "-", ".", "-."]:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


# ============================================================
# ПОШУК СТОВПЦЯ
# ============================================================

def find_column(df, exact_names=None, contains=None):
    """
    Надійний пошук стовпця.

    Спочатку шукає точну назву,
    потім назву, що містить заданий фрагмент.
    """

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

    spreadsheet = client.open(SPREADSHEET_NAME)
    sheet = spreadsheet.worksheet(WORKSHEET_NAME)

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

    # --------------------------------------------------------
    # ДАТА
    # --------------------------------------------------------

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
            errors="coerce"
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
# ЗАВАНТАЖЕННЯ ДАНИХ У ДОДАТОК
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

st.sidebar.title("💧 FMS AgronomOk")
st.sidebar.subheader("Панель управління")

menu_option = st.sidebar.radio(
    "Перейти до:",
    [
        "Головна панель",
        "Поливні модулі"
    ]
)


# ============================================================
# СПИСОК ПОЛИВНИХ МОДУЛІВ
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
        m for m in modules_list
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
        ) if state_col else "Н/Д"
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
        latest.get(water_col, 0)
        if water_col
        else 0
    )

    water = convert_to_number(water)

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
        latest.get(energy_col, 0)
        if energy_col
        else 0
    )

    energy = convert_to_number(energy)

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
        ) if module_col else "Н/Д"
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

    if len(modules_list) > 0 and module_col:

        selected_module = st.sidebar.selectbox(
            "Оберіть зрошувальний модуль:",
            modules_list
        )

        st.title(
            f"⚙️ Моніторинг модуля: {selected_module}"
        )

        # ----------------------------------------------------
        # ФІЛЬТР МОДУЛЯ
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ЯКЩО ДАНИХ НЕМАЄ
        # ----------------------------------------------------

        if df_filtered.empty:

            st.warning(
                "Немає даних для обраного модуля."
            )

        else:

            # =================================================
            # ПОТУЖНІСТЬ
            # =================================================

            st.subheader(
                "⚡ Потужність за період (кВт/год)"
            )

            power_col_name = (
                "Потужність за період, кВт/год"
            )

            if (
                power_col_name
                in df_filtered.columns
            ):

                power_data = df_filtered[
                    [
                        "Дата та час",
                        power_col_name
                    ]
                ].copy()

                power_data[
                    power_col_name
                ] = power_data[
                    power_col_name
                ].apply(convert_to_number)

                power_data = power_data.dropna(
                    subset=[
                        "Дата та час",
                        power_col_name
                    ]
                )

                if not power_data.empty:

                    power_max = power_data[
                        power_col_name
                    ].max()

                    y_min = 0

                    y_max = (
                        power_max * 1.10
                        if power_max > 0
                        else 1
                    )

                    power_chart = (
                        alt.Chart(power_data)
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
                                f"{power_col_name}:Q",
                                title="кВт/год",
                                scale=alt.Scale(
                                    domain=[
                                        y_min,
                                        y_max
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
                                    f"{power_col_name}:Q",
                                    title="Потужність",
                                    format=".2f"
                                )
                            ]
                        )
                        .properties(
                            height=400
                        )
                    )

                    st.altair_chart(
                        power_chart,
                        use_container_width=True
                    )

                else:

                    st.info(
                        "Немає числових даних для побудови графіка потужності."
                    )

            else:

                st.warning(
                    "Стовпчик потужності не знайдено."
                )

            # =================================================
            # ПРОДУКТИВНІСТЬ
            # =================================================

            st.subheader(
                "🌊 Продуктивність (куб. м./год)"
            )

            flow_col_name = (
                "Продуктивність, куб. м./год"
            )
            st.write("DEBUG:", df_filtered["Продуктивність, куб. м./год"].tolist()[-20:])

            # -------------------------------------------------
            # ПЕРЕВІРКА НАЯВНОСТІ СТОВПЦЯ
            # -------------------------------------------------

            if (
                flow_col_name
                in df_filtered.columns
            ):

                flow_data = df_filtered[
                    [
                        "Дата та час",
                        flow_col_name
                    ]
                ].copy()

                # ---------------------------------------------
                # ПЕРЕТВОРЕННЯ В ЧИСЛО
                # ---------------------------------------------

                flow_data[
                    flow_col_name
                ] = flow_data[
                    flow_col_name
                ].apply(convert_to_number)

                # ---------------------------------------------
                # ВИДАЛЕННЯ ПУСТИХ ЗНАЧЕНЬ
                # ---------------------------------------------

                flow_data = flow_data.dropna(
                    subset=[
                        "Дата та час",
                        flow_col_name
                    ]
                )

                # ---------------------------------------------
                # ПОБУДОВА ГРАФІКА
                # ---------------------------------------------

                if not flow_data.empty:

                                        # Відкидаємо явно некоректні значення
                    # продуктивності тільки для побудови графіка.
                    # У таблиці Google Sheets вони залишаються.

                    flow_chart_data = flow_data[
                        flow_data[flow_col_name] <= 200
                    ].copy()

                    if not flow_chart_data.empty:

                        flow_max = flow_chart_data[
                            flow_col_name
                        ].max()

                        flow_y_min = 0

                        flow_y_max = (
                            flow_max * 1.10
                            if flow_max > 0
                            else 1
                        )

                    else:

                        flow_y_min = 0
                        flow_y_max = 100
                   

                    flow_chart = (
                        alt.Chart(flow_chart_data)
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
                                f"{flow_col_name}:Q",
                                title="м³/год",
                                scale=alt.Scale(
                                    domain=[
                                        flow_y_min,
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
                                    f"{flow_col_name}:Q",
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
                        "Немає числових даних для побудови графіка продуктивності."
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
