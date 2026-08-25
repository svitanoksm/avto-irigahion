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
    Перетворює значення з Google Sheets у нормальне число.

    Підтримує:
    10,75
    10.75
    1 050,25
    1 050.25
    порожні значення
    """

    if value is None:
        return None

    # Якщо вже число
    if isinstance(value, (int, float)):
        return float(value)

    # Перетворюємо в текст
    value = str(value).strip()

    # Порожнє значення
    if value == "":
        return None

    # Прибираємо пробіли
    value = value.replace(" ", "")

    # Український десятковий роздільник
    value = value.replace(",", ".")

    # Якщо залишилися сторонні символи
    # залишаємо тільки цифри, мінус і крапку
    cleaned = ""

    for char in value:

        if char.isdigit() or char in ".-":
            cleaned += char

    try:
        return float(cleaned)

    except ValueError:
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

    # Заголовки (прибираємо зайві пробіли по краях)
    headers = [str(h).strip() for h in values[0]]
    rows = values[1:]

    df = pd.DataFrame(rows, columns=headers)

    # 1. Перетворення дати
    date_col = next((c for c in df.columns if "дата" in c.lower()), "Дата та час")
    if date_col in df.columns:
        df["Дата та час"] = pd.to_datetime(
            df[date_col],
            errors="coerce"
        )

    # 2. Гарантоване перетворення числових стовпчиків за ключовими словами
    for col in df.columns:
        col_lower = col.lower()
        if "потужн" in col_lower:
            df[col] = df[col].apply(convert_to_number)
            # Приводимо до єдиної точної назви для зручності
            if col != "Потужність за період, кВт/год":
                df.rename(columns={col: "Потужність за період, кВт/год"}, inplace=True)
                
        elif "продуктивн" in col_lower:
            df[col] = df[col].apply(convert_to_number)
            if col != "Продуктивність, куб. м./год":
                df.rename(columns={col: "Продуктивність, куб. м./год"}, inplace=True)
                
        elif "витрати" in col_lower and "квт" in col_lower:
            df[col] = df[col].apply(convert_to_number)
            
        elif "витрати" in col_lower and ("м³" in col_lower or "куб" in col_lower or "м." in col_lower):
            df[col] = df[col].apply(convert_to_number)

    # 3. Сортування за датою
    if "Дата та час" in df.columns:
        df = df.sort_values(by="Дата та час")
        df = df.reset_index(drop=True)

    return df

    # --------------------------------------------------------
    # Відкриваємо таблицю
    # --------------------------------------------------------

    spreadsheet = client.open(
        SPREADSHEET_NAME
    )

    # --------------------------------------------------------
    # Відкриваємо аркуш
    # --------------------------------------------------------

    sheet = spreadsheet.worksheet(
        WORKSHEET_NAME
    )

    # ========================================================
    # ОТРИМУЄМО ФОРМАТОВАНІ ЗНАЧЕННЯ
    # ========================================================

    values = sheet.get_all_values(
        value_render_option="FORMATTED_VALUE"
    )

    if not values:
        return pd.DataFrame()

    # --------------------------------------------------------
    # Перший рядок — заголовки (очищаємо від зайвих пробілів)
    # --------------------------------------------------------

    headers = [str(h).strip() for h in values[0]]

    # --------------------------------------------------------
    # Решта — дані
    # --------------------------------------------------------

    rows = values[1:]

    # --------------------------------------------------------
    # Створюємо DataFrame
    # --------------------------------------------------------

    df = pd.DataFrame(
        rows,
        columns=headers
    )

    # ========================================================
    # ПЕРЕТВОРЕННЯ ДАТИ
    # ========================================================

    if "Дата та час" in df.columns:

        df["Дата та час"] = pd.to_datetime(
            df["Дата та час"],
            errors="coerce"
        )

    # ========================================================
    # ГНУЧКИЙ ПОШУК ТА ПЕРЕТВОРЕННЯ ЧИСЛОВИХ СТОВПЧИКІВ
    # ========================================================

    # Шукаємо точні або схожі назви стовпчиків у таблиці
    for col in df.columns:
        col_lower = col.lower()
        
        # Перетворення потужності
        if "потужн" in col_lower:
            df[col] = df[col].apply(convert_to_number)
            # Перейменовуємо для зручності у стандартну назву якщо треба
            if col != "Потужність за період, кВт/год":
                df.rename(columns={col: "Потужність за період, кВт/год"}, inplace=True)

        # Перетворення продуктивності
        elif "продуктивн" in col_lower:
            df[col] = df[col].apply(convert_to_number)
            if col != "Продуктивність, куб. м./год":
                df.rename(columns={col: "Продуктивність, куб. м./год"}, inplace=True)

        # Витрати кВт
        elif "витрати" in col_lower and "квт" in col_lower:
            df[col] = df[col].apply(convert_to_number)

        # Витрати вода (куб. м.)
        elif "витрати" in col_lower and ("м³" in col_lower or "куб" in col_lower):
            df[col] = df[col].apply(convert_to_number)

    # ========================================================
    # СОРТУВАННЯ ЗА ДАТОЮ
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
        "Помилка завантаження даних "
        f"з Google Таблиці: {e}"
    )

    st.stop()


# ============================================================
# ПЕРЕВІРКА ДАНИХ
# ============================================================

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
# СПИСОК ПОЛИВНИХ МОДУЛІВ
# ============================================================

# Знаходимо стовпчик модуля гнучко
module_col = None
for col in df.columns:
    if "модуль" in col.lower() and "зрош" in col.lower():
        module_col = col
        break

if module_col:

    modules_list = (
        df[module_col]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    # Прибираємо "Вимкнено"
    modules_list = [
        module
        for module in modules_list
        if module != "Вимкнено"
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

    # --------------------------------------------------------
    # ПОТОЧНІ ПОКАЗНИКИ
    # --------------------------------------------------------

    latest = df.iloc[-1]

    col1, col2, col3, col4 = st.columns(4)

    # Стан
    state_col = next((c for c in df.columns if "стан" in c.lower()), None)
    col1.metric(
        "Стан вимикача",
        latest.get(state_col, "Н/Д") if state_col else "Н/Д"
    )

    # Витрати води
    water_col = next((c for c in df.columns if "витрати" in c.lower() and ("м³" in c.lower() or "куб" in c.lower())), None)
    water = latest.get(water_col, 0) if water_col else 0
    if pd.isna(water):
        water = 0

    col2.metric(
        "Загальні витрати води",
        f"{water:.2f} м³"
    )

    # Енергія
    energy_col = next((c for c in df.columns if "витрати" in c.lower() and "квт" in c.lower()), None)
    energy = latest.get(energy_col, 0) if energy_col else 0
    if pd.isna(energy):
        energy = 0

    col3.metric(
        "Загальна енергія",
        f"{energy:.2f} кВт"
    )

    # Поточний модуль
    col4.metric(
        "Поточний модуль",
        latest.get(module_col, "Н/Д") if module_col else "Н/Д"
    )

    # Останні записи
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

        # ====================================================
        # ФІЛЬТРУЄМО ДАНІ
        # ====================================================

        df_filtered = df[
            df[module_col].astype(str) == selected_module
        ].copy()

        df_filtered = df_filtered.sort_values(
            by="Дата та час"
        )

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

            power_col_name = "Потужність за період, кВт/год"
            if power_col_name not in df_filtered.columns:
                # Шукаємо альтернативу
                power_col_name = next((c for c in df_filtered.columns if "потужн" in c.lower()), None)

            if power_col_name and power_col_name in df_filtered.columns:

                power_data = df_filtered[
                    [
                        "Дата та час",
                        power_col_name
                    ]
                ].dropna(subset=["Дата та час", power_col_name]).copy()

                if not power_data.empty:

                    power_max = power_data[power_col_name].max()
                    y_min = 0
                    y_max = power_max * 1.10 if power_max > 0 else 1

                    power_chart = (
                        alt.Chart(power_data)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X(
                                "Дата та час:T",
                                title="Дата та час",
                                axis=alt.Axis(format="%H:%M")
                            ),
                            y=alt.Y(
                                f"{power_col_name}:Q",
                                title="кВт/год",
                                scale=alt.Scale(domain=[y_min, y_max], nice=False),
                                axis=alt.Axis(format=".1f")
                            ),
                            tooltip=[
                                alt.Tooltip("Дата та час:T", title="Дата та час", format="%d.%m.%Y %H:%M:%S"),
                                alt.Tooltip(f"{power_col_name}:Q", title="Потужність", format=".2f")
                            ]
                        )
                        .properties(height=400)
                    )

                    st.altair_chart(power_chart, use_container_width=True)
                else:
                    st.info("Немає числових даних для побудови графіка потужності.")
            else:
                st.warning("Стовпчик потужності не знайдено в таблиці.")


            # =================================================
            # ПРОДУКТИВНІСТЬ
            # =================================================

            st.subheader(
                "🌊 Продуктивність (куб. м./год)"
            )

            flow_col_name = "Продуктивність, куб. м./год"
            if flow_col_name not in df_filtered.columns:
                flow_col_name = next((c for c in df_filtered.columns if "продуктивн" in c.lower()), None)

            if flow_col_name and flow_col_name in df_filtered.columns:

                flow_data = df_filtered[
                    [
                        "Дата та час",
                        flow_col_name
                    ]
                ].dropna(subset=["Дата та час", flow_col_name]).copy()

                if not flow_data.empty:

                    flow_max = flow_data[flow_col_name].max()
                    flow_y_min = 0
                    flow_y_max = flow_max * 1.10 if flow_max > 0 else 1

                    flow_chart = (
                        alt.Chart(flow_data)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X(
                                "Дата та час:T",
                                title="Дата та час",
                                axis=alt.Axis(format="%H:%M")
                            ),
                            y=alt.Y(
                                f"{flow_col_name}:Q",
                                title="м³/год",
                                scale=alt.Scale(domain=[flow_y_min, flow_y_max], nice=False),
                                axis=alt.Axis(format=".1f")
                            ),
                            tooltip=[
                                alt.Tooltip("Дата та час:T", title="Дата та час", format="%d.%m.%Y %H:%M:%S"),
                                alt.Tooltip(f"{flow_col_name}:Q", title="Продуктивність", format=".2f")
                            ]
                        )
                        .properties(height=400)
                    )

                    st.altair_chart(flow_chart, use_container_width=True)
                else:
                    st.info("Немає числових даних для побудови графіка продуктивності.")
            else:
                st.warning("Стовпчик продуктивності не знайдено в таблиці.")


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
