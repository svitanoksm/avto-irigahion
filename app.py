import streamlit as st
import pandas as pd
import gspread
import altair as alt
from google.oauth2.service_account import Credentials
from PIL import Image


# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="FMS AgronomOk - Моніторинг свердловини",
    page_icon="💧",
    layout="wide",
)

# ============================================================
# НАЛАШТУВАННЯ НАВІГАЦІЇ (КИРИЛИЦЯ В МЕНЮ)
# ============================================================

pg = st.navigation([
    st.Page("app.py", title="Зрошення", icon="💧"),
    st.Page("pages/01_Field_Parameters.py", title="Параметри полів", icon="⚙️"),
])

pg.run()


# ============================================================
# НАЛАШТУВАННЯ GOOGLE SHEETS
# ============================================================

SPREADSHEET_NAME = "Автоматизація зрошення"
WORKSHEET_NAME = "Свердловина 1"

# Кількість дерев у модулях
TREES_COUNT_MAP = {
    "Модуль 1-3": 1387,
    "Модуль 1-4": 1430,
    "Модуль 1-5": 1376,
}


# ============================================================
# ФУНКЦІЯ ПЕРЕТВОРЕННЯ ЧИСЕЛ
# ============================================================

def convert_to_number(value):
    """Надійне перетворення значення з Google Sheets у число."""

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

    value = value.replace(" ", "")
    value = value.replace("\xa0", "")

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")

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
    """Надійний пошук стовпця за точною назвою або фрагментом."""

    exact_names = exact_names or []
    contains = contains or []

    for name in exact_names:
        for col in df.columns:
            if str(col).strip().lower() == name.strip().lower():
                return col

    for fragment in contains:
        fragment = fragment.lower()
        for col in df.columns:
            if fragment in str(col).lower():
                return col

    return None


# ============================================================
# ПОШУК ЛІЧИЛЬНИКІВ
# ============================================================

def find_energy_meter_column(df):
    """Знаходить стовпець показників лічильника електроенергії."""

    return next(
        (
            c
            for c in df.columns
            if "показники" in str(c).lower()
            and "лічильника" in str(c).lower()
            and "квт" in str(c).lower()
        ),
        None,
    )


def find_water_meter_column(df):
    """Знаходить стовпець показників лічильника води."""

    return next(
        (
            c
            for c in df.columns
            if "показники" in str(c).lower()
            and "лічильника" in str(c).lower()
            and (
                "м³" in str(c).lower()
                or "куб" in str(c).lower()
                or "м." in str(c).lower()
            )
        ),
        None,
    )


# ============================================================
# ЗАВАНТАЖЕННЯ ДАНИХ
# ============================================================

@st.cache_data(ttl=60)
def load_data():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    creds_dict = dict(st.secrets["gcp_service_account"])

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=scopes,
    )

    client = gspread.authorize(creds)

    spreadsheet = client.open(SPREADSHEET_NAME)
    sheet = spreadsheet.worksheet(WORKSHEET_NAME)

    values = sheet.get_all_values(value_render_option="FORMATTED_VALUE")

    if not values:
        return pd.DataFrame()

    headers = [str(h).strip() for h in values[0]]
    rows = values[1:]

    df = pd.DataFrame(rows, columns=headers)

    # --------------------------------------------------------
    # Дата та час
    # --------------------------------------------------------

    date_col = find_column(
        df,
        exact_names=["Дата та час"],
        contains=["дата"],
    )

    if date_col:
        df["Дата та час"] = pd.to_datetime(
            df[date_col],
            errors="coerce",
            dayfirst=True,
        )

    # --------------------------------------------------------
    # Потужність
    # --------------------------------------------------------

    power_col = find_column(
        df,
        exact_names=["Потужність за період, кВт/год"],
        contains=["потужність"],
    )

    if power_col:
        df["Потужність за період, кВт/год"] = (
            df[power_col].apply(convert_to_number)
        )

    # --------------------------------------------------------
    # Продуктивність
    # --------------------------------------------------------

    flow_col = find_column(
        df,
        exact_names=[
            "Продуктивність, куб. м./год",
            "Продуктивність, куб. м/год",
            "Продуктивність, м³/год",
            "Продуктивність",
        ],
        contains=["продуктивність"],
    )

    if flow_col:
        df["Продуктивність, куб. м./год"] = (
            df[flow_col].apply(convert_to_number)
        )

    # --------------------------------------------------------
    # Показники лічильників
    # --------------------------------------------------------

    energy_col = find_energy_meter_column(df)
    if energy_col:
        df[energy_col] = df[energy_col].apply(convert_to_number)

    water_col = find_water_meter_column(df)
    if water_col:
        df[water_col] = df[water_col].apply(convert_to_number)

    # --------------------------------------------------------
    # Сортування за датою
    # --------------------------------------------------------

    if "Дата та час" in df.columns:
        df = df.sort_values(by="Дата та час")
        df = df.reset_index(drop=True)

    return df


# ============================================================
# ЗАВАНТАЖЕННЯ ДАНИХ У ДОДАТОК
# ============================================================

try:
    df = load_data()
except Exception as e:
    st.error(f"Помилка завантаження даних з Google Таблиці: {e}")
    st.stop()


if df.empty:
    st.warning("Google Таблиця не містить даних.")
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
        "Поливні модулі",
        "Полив кожної рослини",
        "Параметри полів та систем",
    ],
)


# ============================================================
# СПИСОК ПОЛИВНИХ МОДУЛІВ
# ============================================================

module_col = None

for col in df.columns:
    col_lower = str(col).lower()

    if "модуль" in col_lower and "зрош" in col_lower:
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
    modules_list = [m for m in modules_list if m != "Вимкнено"]
else:
    modules_list = []


# ============================================================
# 1. ГОЛОВНА ПАНЕЛЬ
# ============================================================

if menu_option == "Головна панель":

    st.title("📊 Загальний моніторинг свердловини")

    latest = df.iloc[-1]

    col1, col2, col3, col4 = st.columns(4)

    # Стан
    state_col = next(
        (c for c in df.columns if "стан" in str(c).lower()),
        None,
    )

    col1.metric(
        "Стан вимикача",
        latest.get(state_col, "Н/Д") if state_col else "Н/Д",
    )

    # Вода
    water_col = find_water_meter_column(df)
    water = latest.get(water_col, 0) if water_col else 0
    water = convert_to_number(water)

    if water is None:
        water = 0

    col2.metric("Загальні витрати води", f"{water:.2f} м³")

    # Електроенергія
    energy_col = find_energy_meter_column(df)
    energy = latest.get(energy_col, 0) if energy_col else 0
    energy = convert_to_number(energy)

    if energy is None:
        energy = 0

    col3.metric("Загальна енергія", f"{energy:.2f} кВт·год")

    # Поточний модуль
    col4.metric(
        "Поточний модуль",
        latest.get(module_col, "Н/Д") if module_col else "Н/Д",
    )

    st.subheader("Останні записи з таблиці")
    st.dataframe(
        df.tail(10),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# 2. ПОЛИВНІ МОДУЛІ
# ============================================================

elif menu_option == "Поливні модулі":

    st.sidebar.markdown("---")
    st.sidebar.subheader("Вибір модуля")

    if not modules_list or not module_col:
        st.warning("Наразі не виявлено активних модулів у базі даних.")
        st.stop()

    selected_module = st.sidebar.selectbox(
        "Оберіть зрошувальний модуль:",
        modules_list,
        key="irrigation_module_select",
    )

    st.title(f"⚙️ Моніторинг модуля: {selected_module}")

    df_filtered = df[
        df[module_col].astype(str).str.strip() == selected_module
    ].copy()

    if "Дата та час" in df_filtered.columns:
        df_filtered = df_filtered.sort_values(by="Дата та час")

    if df_filtered.empty:
        st.warning("Немає даних для обраного модуля.")
        st.stop()

    # ========================================================
    # 2.1 ТРЕНД ПОТУЖНОСТІ
    # ========================================================

    st.subheader("⚡ Потужність за період (кВт/год) — Тренд")

    power_col_name = "Потужність за період, кВт/год"

    if power_col_name in df_filtered.columns:

        power_data = df_filtered[
            ["Дата та час", power_col_name]
        ].copy()

        power_data[power_col_name] = power_data[power_col_name].apply(
            convert_to_number
        )

        power_data = power_data.dropna(
            subset=["Дата та час", power_col_name]
        )

        if not power_data.empty:

            power_data["trend"] = (
                power_data[power_col_name]
                .rolling(window=10, min_periods=1)
                .mean()
            )

            trend_max = power_data["trend"].max()

            if pd.isna(trend_max):
                trend_max = 1

            y_min = 0
            y_max = trend_max * 1.10 if trend_max > 0 else 1

            power_chart = (
                alt.Chart(power_data)
                .mark_line(
                    point=False,
                    interpolate="monotone",
                    color="#ff4b4b",
                )
                .encode(
                    x=alt.X(
                        "Дата та час:T",
                        title="Дата та час",
                        axis=alt.Axis(format="%H:%M"),
                    ),
                    y=alt.Y(
                        "trend:Q",
                        title="кВт·год",
                        scale=alt.Scale(
                            domain=[y_min, y_max],
                            nice=False,
                        ),
                        axis=alt.Axis(format=".1f"),
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "Дата та час:T",
                            title="Дата та час",
                            format="%d.%m.%Y %H:%M:%S",
                        ),
                        alt.Tooltip(
                            "trend:Q",
                            title="Тренд потужності",
                            format=".2f",
                        ),
                    ],
                )
                .properties(height=400)
            )

            st.altair_chart(
                power_chart,
                use_container_width=True,
            )
        else:
            st.info("Недостатньо даних для побудови тренду потужності.")
    else:
        st.info("Стовпець потужності не знайдено.")

    # ========================================================
    # 2.2 СПОЖИТА ЕЛЕКТРОЕНЕРГІЯ ЗА ГОДИНУ
    # ========================================================

    st.subheader(
        "📊 Використана електроенергія за кожну годину "
        "(кВт·год) — Перераховано на 60 хв"
    )

    energy_col_name = find_energy_meter_column(df_filtered)

    if energy_col_name and "Дата та час" in df_filtered.columns:

        en_df = df_filtered[
            ["Дата та час", energy_col_name]
        ].copy()

        en_df[energy_col_name] = en_df[energy_col_name].apply(
            convert_to_number
        )

        en_df = en_df.dropna(
            subset=["Дата та час", energy_col_name]
        )

        if not en_df.empty:
            try:
                en_df["Година"] = en_df["Дата та час"].dt.floor("h")
                hourly_energy_list = []

                for hour_val, group in en_df.groupby("Година"):
                    group = group.sort_values(by="Дата та час")

                    if len(group) >= 2:
                        total_delta_energy = 0.0
                        total_duration_mins = 0.0

                        vals = group[energy_col_name].values
                        times = group["Дата та час"].values

                        for i in range(1, len(vals)):
                            d_en = vals[i] - vals[i - 1]
                            d_time = (
                                pd.Timestamp(times[i])
                                - pd.Timestamp(times[i - 1])
                            )
                            d_mins = d_time.total_seconds() / 60.0

                            if 0 <= d_en < 30 and 0 < d_mins < 60:
                                total_delta_energy += d_en
                                total_duration_mins += d_mins

                        if total_duration_mins > 0:
                            adjusted_energy = (
                                total_delta_energy
                                * (60.0 / total_duration_mins)
                            )

                            if adjusted_energy < 150:
                                hourly_energy_list.append(
                                    {
                                        "Година": hour_val,
                                        "Витрачена електроенергія": adjusted_energy,
                                    }
                                )

                    elif len(group) == 1:
                        val = float(group[energy_col_name].iloc[0])

                        if val < 50:
                            hourly_energy_list.append(
                                {
                                    "Година": hour_val,
                                    "Витрачена електроенергія": val,
                                }
                            )

                hourly_energy = pd.DataFrame(hourly_energy_list)

                if not hourly_energy.empty:
                    energy_bar_chart = (
                        alt.Chart(hourly_energy)
                        .mark_bar(color="#ff9999", size=60)
                        .encode(
                            x=alt.X(
                                "Година:T",
                                title="Година",
                                axis=alt.Axis(
                                    format="%H:%M",
                                    labelAngle=0,
                                ),
                            ),
                            y=alt.Y(
                                "Витрачена електроенергія:Q",
                                title="кВт·год (на 1 год)",
                            ),
                            tooltip=[
                                alt.Tooltip(
                                    "Година:T",
                                    title="Дата та година",
                                    format="%d.%m.%Y %H:00",
                                ),
                                alt.Tooltip(
                                    "Витрачена електроенергія:Q",
                                    title="Прогноз на повну год, кВт·год",
                                    format=".2f",
                                ),
                            ],
                        )
                        .properties(height=350)
                    )

                    st.altair_chart(
                        energy_bar_chart,
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "Недостатньо даних для побудови "
                        "погодинного графіка електроенергії."
                    )

            except Exception as err:
                st.info(
                    "Не вдалося побудувати погодинний графік "
                    f"електроенергії: {err}"
                )
        else:
            st.info(
                "Недостатньо даних для побудови "
                "погодинного графіка електроенергії."
            )
    else:
        st.info(
            "Стовпець показників лічильника електроенергії "
            "не знайдено."
        )

    # ========================================================
    # 2.3 ТРЕНД ПРОДУКТИВНОСТІ
    # ========================================================

    st.subheader("🌊 Продуктивність (куб. м./год) — Тренд")

    flow_col_name = "Продуктивність, куб. м./год"

    if flow_col_name in df_filtered.columns:

        flow_data = df_filtered[
            ["Дата та час", flow_col_name]
        ].copy()

        flow_data[flow_col_name] = flow_data[flow_col_name].apply(
            convert_to_number
        )

        flow_data = flow_data.dropna(
            subset=["Дата та час", flow_col_name]
        )

        if not flow_data.empty:

            flow_chart_data = flow_data[
                flow_data[flow_col_name] <= 200
            ].copy()

            if not flow_chart_data.empty:

                flow_chart_data["trend"] = (
                    flow_chart_data[flow_col_name]
                    .rolling(window=10, min_periods=1)
                    .mean()
                )

                trend_max_flow = flow_chart_data["trend"].max()

                if pd.isna(trend_max_flow):
                    trend_max_flow = 100

                flow_y_min = 0
                flow_y_max = (
                    trend_max_flow * 1.10
                    if trend_max_flow > 0
                    else 100
                )

                flow_chart = (
                    alt.Chart(flow_chart_data)
                    .mark_line(
                        point=False,
                        interpolate="monotone",
                        color="#1f77b4",
                    )
                    .encode(
                        x=alt.X(
                            "Дата та час:T",
                            title="Дата та час",
                            axis=alt.Axis(format="%H:%M"),
                        ),
                        y=alt.Y(
                            "trend:Q",
                            title="м³/год",
                            scale=alt.Scale(
                                domain=[flow_y_min, flow_y_max],
                                nice=False,
                            ),
                            axis=alt.Axis(format=".1f"),
                        ),
                        tooltip=[
                            alt.Tooltip(
                                "Дата та час:T",
                                title="Дата та час",
                                format="%d.%m.%Y %H:%M:%S",
                            ),
                            alt.Tooltip(
                                "trend:Q",
                                title="Тренд продуктивності",
                                format=".2f",
                            ),
                        ],
                    )
                    .properties(height=400)
                )

                st.altair_chart(
                    flow_chart,
                    use_container_width=True,
                )
            else:
                st.info(
                    "Недостатньо коректних даних для побудови "
                    "тренду продуктивності."
                )
        else:
            st.info("Недостатньо даних для побудови тренду продуктивності.")
    else:
        st.info("Стовпець продуктивності не знайдено.")

    # ========================================================
    # 2.4 ВИКОРИСТАНА ВОДА ЗА ГОДИНУ
    # ========================================================

    st.subheader(
        "📊 Використана вода за кожну годину "
        "(м³) — Перераховано на 60 хв"
    )

    water_metric_col = find_water_meter_column(df_filtered)

    if water_metric_col and "Дата та час" in df_filtered.columns:

        wat_df = df_filtered[
            ["Дата та час", water_metric_col]
        ].copy()

        wat_df[water_metric_col] = wat_df[water_metric_col].apply(
            convert_to_number
        )

        wat_df = wat_df.dropna(
            subset=["Дата та час", water_metric_col]
        )

        if not wat_df.empty:
            try:
                wat_df["Година"] = wat_df["Дата та час"].dt.floor("h")
                hourly_water_list = []

                for hour_val, group in wat_df.groupby("Година"):
                    group = group.sort_values(by="Дата та час")

                    if len(group) >= 2:
                        total_delta_water = 0.0
                        total_duration_mins = 0.0

                        vals = group[water_metric_col].values
                        times = group["Дата та час"].values

                        for i in range(1, len(vals)):
                            d_wat = vals[i] - vals[i - 1]
                            d_time = (
                                pd.Timestamp(times[i])
                                - pd.Timestamp(times[i - 1])
                            )
                            d_mins = d_time.total_seconds() / 60.0

                            if 0 <= d_wat < 50 and 0 < d_mins < 60:
                                total_delta_water += d_wat
                                total_duration_mins += d_mins

                        if total_duration_mins > 0:
                            adjusted_water = (
                                total_delta_water
                                * (60.0 / total_duration_mins)
                            )

                            if adjusted_water < 200:
                                hourly_water_list.append(
                                    {
                                        "Година": hour_val,
                                        "Витрачена вода": adjusted_water,
                                    }
                                )

                    elif len(group) == 1:
                        val = float(group[water_metric_col].iloc[0])

                        if val < 100:
                            hourly_water_list.append(
                                {
                                    "Година": hour_val,
                                    "Витрачена вода": val,
                                }
                            )

                hourly_water = pd.DataFrame(hourly_water_list)

                if not hourly_water.empty:
                    water_bar_chart = (
                        alt.Chart(hourly_water)
                        .mark_bar(color="#54a0ff", size=60)
                        .encode(
                            x=alt.X(
                                "Година:T",
                                title="Година",
                                axis=alt.Axis(
                                    format="%H:%M",
                                    labelAngle=0,
                                ),
                            ),
                            y=alt.Y(
                                "Витрачена вода:Q",
                                title="м³ (на 1 год)",
                            ),
                            tooltip=[
                                alt.Tooltip(
                                    "Година:T",
                                    title="Дата та година",
                                    format="%d.%m.%Y %H:00",
                                ),
                                alt.Tooltip(
                                    "Витрачена вода:Q",
                                    title="Прогноз на повну год, м³",
                                    format=".2f",
                                ),
                            ],
                        )
                        .properties(height=350)
                    )

                    st.altair_chart(
                        water_bar_chart,
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "Недостатньо даних для побудови "
                        "погодинного графіка води."
                    )

            except Exception as err:
                st.info(
                    f"Не вдалося побудувати погодинний графік води: {err}"
                )
        else:
            st.info(
                "Недостатньо даних для побудови "
                "погодинного графіка води."
            )
    else:
        st.info("Стовпець показників лічильника води не знайдено.")


# ============================================================
# 3. ПОЛИВ КОЖНОЇ РОСЛИНИ
# ============================================================

elif menu_option == "Полив кожної рослини":

    st.sidebar.markdown("---")
    st.sidebar.subheader("Вибір модуля")

    if not modules_list or not module_col:
        st.warning("Наразі не виявлено активних модулів у базі даних.")
        st.stop()

    selected_module = st.sidebar.selectbox(
        "Оберіть зрошувальний модуль для аналізу дерева:",
        modules_list,
        key="plant_module_select",
    )

    st.title(f"🌳 Аналітика поливу однієї рослини: {selected_module}")

    trees_count = TREES_COUNT_MAP.get(selected_module, 1000)

    df_filtered = df[
        df[module_col].astype(str).str.strip() == selected_module
    ].copy()

    if "Дата та час" in df_filtered.columns and not df_filtered.empty:
        df_filtered = df_filtered.sort_values(by="Дата та час")
        max_date = df_filtered["Дата та час"].max()

        if pd.isna(max_date):
            max_date = pd.Timestamp.now()
    else:
        max_date = pd.Timestamp.now()

    water_metric_col = find_water_meter_column(df_filtered)

    # --------------------------------------------------------
    # Допоміжна функція: вода на одну рослину за календарний період
    # --------------------------------------------------------

    def get_water_per_tree_for_year_dates(target_year, start_dt, end_dt):
        try:
            s_dt = start_dt.replace(year=target_year)
            e_dt = end_dt.replace(year=target_year)
        except ValueError:
            # Захист для 29 лютого у невисокосному році
            s_dt = pd.Timestamp(
                target_year,
                start_dt.month,
                min(start_dt.day, 28),
            )
            e_dt = pd.Timestamp(
                target_year,
                end_dt.month,
                min(end_dt.day, 28),
            )

        sub_df = pd.DataFrame()

        if "Дата та час" in df_filtered.columns and not df_filtered.empty:
            e_dt_full = e_dt + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

            mask = (
                (df_filtered["Дата та час"] >= s_dt)
                & (df_filtered["Дата та час"] <= e_dt_full)
            )

            sub_df = df_filtered[mask]

        if sub_df.empty:
            return None

        total_m3 = 0.0
        days_count = (e_dt - s_dt).days + 1

        if water_metric_col:
            vals = sub_df[water_metric_col].dropna()

            if len(vals) >= 2:
                vals = vals.astype(float)
                total_m3 = float(vals.iloc[-1]) - float(vals.iloc[0])
            elif len(vals) == 1:
                total_m3 = float(vals.iloc[0])

        elif "Продуктивність, куб. м./год" in df_filtered.columns:
            avg_flow = sub_df["Продуктивність, куб. м./год"].mean()

            if pd.notna(avg_flow) and avg_flow > 0:
                hours = days_count * 24 * 0.3
                total_m3 = avg_flow * hours

        if total_m3 <= 0:
            return None

        return (total_m3 * 1000) / trees_count

    # --------------------------------------------------------
    # Допоміжна функція: вода на одну рослину за останній період
    # --------------------------------------------------------

    def get_water_per_tree_for_period(days_back_start, days_back_end):
        start_t = max_date - pd.Timedelta(days=days_back_end)
        end_t = max_date - pd.Timedelta(days=days_back_start)

        sub_df = pd.DataFrame()

        if "Дата та час" in df_filtered.columns and not df_filtered.empty:
            mask = (
                (df_filtered["Дата та час"] >= start_t)
                & (df_filtered["Дата та час"] <= end_t)
            )
            sub_df = df_filtered[mask]

        total_m3 = 0.0

        if water_metric_col and not sub_df.empty:
            vals = sub_df[water_metric_col].dropna()

            if len(vals) >= 2:
                vals = vals.astype(float)
                total_m3 = float(vals.iloc[-1]) - float(vals.iloc[0])
            elif len(vals) == 1:
                total_m3 = float(vals.iloc[0])

        elif (
            "Продуктивність, куб. м./год" in df_filtered.columns
            and not sub_df.empty
        ):
            avg_flow = sub_df["Продуктивність, куб. м./год"].mean()

            if pd.isna(avg_flow):
                avg_flow = 0

            hours = max(
                (end_t - start_t).total_seconds() / 3600.0,
                0,
            )

            total_m3 = avg_flow * hours * 0.3

        if total_m3 <= 0:
            return 0.0

        return (total_m3 * 1000) / trees_count

    water_24h = get_water_per_tree_for_period(0, 1)

    # ========================================================
    # ЗОБРАЖЕННЯ + ПОКАЗНИКИ
    # ========================================================

    col_img, col_metrics = st.columns([1, 2], gap="large")

    with col_img:
        st.markdown("### 🌿 Фундук")

        try:
            img = Image.open("image_693716.jpg")
            st.image(
                img,
                use_container_width=True,
                caption=(
                    f"Модуль: {selected_module} "
                    f"({trees_count} дерев)"
                ),
            )
        except Exception:
            st.warning(
                "Не вдалося завантажити зображення "
                "'image_693716.jpg'. Перевірте наявність файлу."
            )

    with col_metrics:
        st.markdown("### 📊 Отримано води однією рослиною")
        st.info(
            f"💧 **За добу (24 години):** {water_24h:.1f} л"
        )

        st.markdown(
            "#### 📅 Розподіл по тижнях року "
            "(поточний та 2 попередні роки)"
        )

        months_ua = {
            1: "січ",
            2: "лют",
            3: "бер",
            4: "квіт",
            5: "тра",
            6: "черв",
            7: "лип",
            8: "серп",
            9: "вер",
            10: "жовт",
            11: "лист",
            12: "груд",
        }

        table_data = []

        current_year = (
            max_date.year
            if not pd.isna(max_date)
            else pd.Timestamp.now().year
        )

        y_curr = current_year
        y_prev1 = current_year - 1
        y_prev2 = current_year - 2

        # ----------------------------------------------------
        # 1-й тиждень: 1–4 січня
        # ----------------------------------------------------

        year_start = pd.Timestamp(y_curr, 1, 1)
        w1_start = year_start
        w1_end = pd.Timestamp(y_curr, 1, 4)

        val_w1_curr = get_water_per_tree_for_year_dates(
            y_curr,
            w1_start,
            w1_end,
        )
        val_w1_p1 = get_water_per_tree_for_year_dates(
            y_prev1,
            w1_start,
            w1_end,
        )
        val_w1_p2 = get_water_per_tree_for_year_dates(
            y_prev2,
            w1_start,
            w1_end,
        )

        table_data.append(
            {
                "Тиждень": "1 тиждень року",
                "Дати тижня": "1 січ – 4 січ",
                f"{y_prev2}": (
                    f"{val_w1_p2:.1f} л"
                    if val_w1_p2 is not None
                    else "-"
                ),
                f"{y_prev1}": (
                    f"{val_w1_p1:.1f} л"
                    if val_w1_p1 is not None
                    else "-"
                ),
                f"{y_curr} (поточний)": (
                    f"{val_w1_curr:.1f} л"
                    if val_w1_curr is not None
                    else "-"
                ),
            }
        )

        # ----------------------------------------------------
        # Тижні 2–52
        # ----------------------------------------------------

        current_monday = pd.Timestamp(y_curr, 1, 5)

        for w in range(2, 53):
            current_sunday = current_monday + pd.Timedelta(days=6)

            if current_monday > pd.Timestamp(y_curr, 12, 31):
                break

            if current_sunday > pd.Timestamp(y_curr, 12, 31):
                current_sunday = pd.Timestamp(y_curr, 12, 31)

            date_str = (
                f"{current_monday.day} "
                f"{months_ua[current_monday.month]} – "
                f"{current_sunday.day} "
                f"{months_ua[current_sunday.month]}"
            )

            val_curr = get_water_per_tree_for_year_dates(
                y_curr,
                current_monday,
                current_sunday,
            )
            val_p1 = get_water_per_tree_for_year_dates(
                y_prev1,
                current_monday,
                current_sunday,
            )
            val_p2 = get_water_per_tree_for_year_dates(
                y_prev2,
                current_monday,
                current_sunday,
            )

            table_data.append(
                {
                    "Тиждень": f"{w} тиждень року",
                    "Дати тижня": date_str,
                    f"{y_prev2}": (
                        f"{val_p2:.1f} л"
                        if val_p2 is not None
                        else "-"
                    ),
                    f"{y_prev1}": (
                        f"{val_p1:.1f} л"
                        if val_p1 is not None
                        else "-"
                    ),
                    f"{y_curr} (поточний)": (
                        f"{val_curr:.1f} л"
                        if val_curr is not None
                        else "-"
                    ),
                }
            )

            current_monday = current_sunday + pd.Timedelta(days=1)

        df_table = pd.DataFrame(table_data)

        st.dataframe(
            df_table,
            use_container_width=True,
            hide_index=True,
            height=400,
        )


# ============================================================
# 4. ПАРАМЕТРИ ПОЛІВ ТА СИСТЕМ
# ============================================================

elif menu_option == "Параметри полів та систем":

    st.title("⚙️ Параметри полів та систем")

    st.write(
        "Ви можете перейти до окремої сторінки налаштувань, "
        "створеної у папці pages:"
    )

    st.page_link(
    "pages/01_Field_Parameters.py",
    label="Відкрити сторінку параметрів",
    icon="📁",
)
