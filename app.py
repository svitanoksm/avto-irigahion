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
# АВТОРИЗАЦІЯ ТА ЗАВАНТАЖЕННЯ ДАНИХ
# ============================================================

@st.cache_data(ttl=60)
def load_data():

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]

    # Отримуємо дані service account зі Streamlit Secrets
    creds_dict = dict(st.secrets["gcp_service_account"])

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES
    )

    # Авторизація Google
    client = gspread.authorize(creds)

    # Відкриваємо Google Таблицю
    spreadsheet = client.open("Автоматизація зрошення")

    # Відкриваємо потрібний аркуш
    sheet = spreadsheet.worksheet("Свердловина 1")

    # Отримуємо всі записи
    data = sheet.get_all_records()

    # Перетворюємо в DataFrame
    df = pd.DataFrame(data)

    # --------------------------------------------------------
    # ПЕРЕВІРКА НАЯВНОСТІ ДАНИХ
    # --------------------------------------------------------

    if df.empty:
        return df

    # --------------------------------------------------------
    # ПЕРЕТВОРЕННЯ ЧИСЛОВИХ СТОВПЧИКІВ
    # --------------------------------------------------------

    numeric_columns = [
        "Потужність за період, кВт/год",
        "Продуктивність, куб. м./год",
        "Витрати, кВт",
        "Витрати, куб. м."
    ]

    for col in numeric_columns:

        if col in df.columns:

            # Перетворюємо значення в текст,
            # щоб однаково обробляти числа і числа з комою
            df[col] = (
                df[col]
                .astype(str)
                .str.strip()
                .str.replace(",", ".", regex=False)
            )

            # Перетворюємо в числовий тип
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    # --------------------------------------------------------
    # ДАТА ТА ЧАС
    # --------------------------------------------------------

    if "Дата та час" in df.columns:

        df["Дата та час"] = pd.to_datetime(
            df["Дата та час"],
            errors="coerce"
        )

    # --------------------------------------------------------
    # СОРТУВАННЯ ЗА ДАТОЮ
    # --------------------------------------------------------

    if "Дата та час" in df.columns:

        df = df.sort_values(
            "Дата та час"
        ).reset_index(drop=True)

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

if (
    "Зрошувальний основний модуль" in df.columns
):

    modules_list = (
        df["Зрошувальний основний модуль"]
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
    # МЕТРИКИ
    # --------------------------------------------------------

    if not df.empty:

        latest = df.iloc[-1]

        col1, col2, col3, col4 = st.columns(4)

        # Стан
        col1.metric(
            "Стан вимикача",
            latest.get(
                "Стан",
                "Н/Д"
            )
        )

        # Витрати води
        water_value = latest.get(
            "Витрати, куб. м.",
            0
        )

        if pd.isna(water_value):
            water_value = 0

        col2.metric(
            "Загальні витрати води",
            f"{water_value:,.2f} м³".replace(
                ",",
                " "
            )
        )

        # Витрати електроенергії
        energy_value = latest.get(
            "Витрати, кВт",
            0
        )

        if pd.isna(energy_value):
            energy_value = 0

        col3.metric(
            "Загальна енергія",
            f"{energy_value:,.2f} кВт".replace(
                ",",
                " "
            )
        )

        # Поточний модуль
        col4.metric(
            "Поточний модуль",
            latest.get(
                "Зрошувальний основний модуль",
                "Н/Д"
            )
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

    # --------------------------------------------------------
    # ЯКЩО МОДУЛІ Є
    # --------------------------------------------------------

    if len(modules_list) > 0:

        selected_module = st.sidebar.selectbox(
            "Оберіть зрошувальний модуль:",
            modules_list
        )

        st.title(
            f"⚙️ Моніторинг модуля: {selected_module}"
        )

        # ----------------------------------------------------
        # ФІЛЬТРАЦІЯ ПО МОДУЛЮ
        # ----------------------------------------------------

        df_filtered = df[
            df["Зрошувальний основний модуль"]
            == selected_module
        ].copy()

        # Сортуємо за датою
        if "Дата та час" in df_filtered.columns:

            df_filtered = df_filtered.sort_values(
                "Дата та час"
            )

        # ----------------------------------------------------
        # ПЕРЕВІРКА
        # ----------------------------------------------------

        if df_filtered.empty:

            st.warning(
                "Немає даних для обраного модуля."
            )

        else:

            # =================================================
            # ГРАФІК ПОТУЖНОСТІ
            # =================================================

            st.subheader(
                "⚡ Потужність за період (кВт/год)"
            )

            # Вибираємо тільки потрібні колонки
            power_chart_data = df_filtered[
                [
                    "Дата та час",
                    "Потужність за період, кВт/год"
                ]
            ].copy()

            # Явно перетворюємо потужність у число
            power_chart_data[
                "Потужність за період, кВт/год"
            ] = pd.to_numeric(
                power_chart_data[
                    "Потужність за період, кВт/год"
                ],
                errors="coerce"
            )

            # Видаляємо порожні значення
            power_chart_data = power_chart_data.dropna(
                subset=[
                    "Дата та час",
                    "Потужність за період, кВт/год"
                ]
            )

            # Створюємо графік
            power_chart = (
                alt.Chart(power_chart_data)
                .mark_line(
                    point=True
                )
                .encode(

                    # -------------------------------
                    # Вісь X
                    # -------------------------------

                    x=alt.X(
                        "Дата та час:T",
                        title="Дата та час",
                        axis=alt.Axis(
                            format="%H:%M"
                        )
                    ),

                    # -------------------------------
                    # Вісь Y
                    # -------------------------------

                    y=alt.Y(
                        "Потужність за період, кВт/год:Q",
                        title="кВт/год",
                        scale=alt.Scale(
                            zero=True
                        ),
                        axis=alt.Axis(
                            format=".1f"
                        )
                    ),

                    # -------------------------------
                    # Підказка
                    # -------------------------------

                    tooltip=[
                        alt.Tooltip(
                            "Дата та час:T",
                            title="Дата та час",
                            format="%d.%m.%Y %H:%M:%S"
                        ),
                        alt.Tooltip(
                            "Потужність за період, кВт/год:Q",
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


            # =================================================
            # ГРАФІК ПРОДУКТИВНОСТІ
            # =================================================

            st.subheader(
                "🌊 Продуктивність (куб. м./год)"
            )

            flow_chart_data = df_filtered[
                [
                    "Дата та час",
                    "Продуктивність, куб. м./год"
                ]
            ].copy()

            # Перетворення у число
            flow_chart_data[
                "Продуктивність, куб. м./год"
            ] = pd.to_numeric(
                flow_chart_data[
                    "Продуктивність, куб. м./год"
                ],
                errors="coerce"
            )

            # Видаляємо порожні значення
            flow_chart_data = flow_chart_data.dropna(
                subset=[
                    "Дата та час",
                    "Продуктивність, куб. м./год"
                ]
            )

            # Графік продуктивності
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
                        "Продуктивність, куб. м./год:Q",
                        title="м³/год",
                        scale=alt.Scale(
                            zero=True
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
                            "Продуктивність, куб. м./год:Q",
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


            # =================================================
            # ДІАГНОСТИКА ДАНИХ
            # =================================================

            with st.expander(
                "🔧 Діагностика даних"
            ):

                st.write(
                    "Кількість записів:",
                    len(df_filtered)
                )

                st.write(
                    "Тип даних потужності:",
                    df_filtered[
                        "Потужність за період, кВт/год"
                    ].dtype
                )

                st.write(
                    "Мінімальна потужність:",
                    df_filtered[
                        "Потужність за період, кВт/год"
                    ].min()
                )

                st.write(
                    "Максимальна потужність:",
                    df_filtered[
                        "Потужність за період, кВт/год"
                    ].max()
                )

                st.write(
                    "Середня потужність:",
                    df_filtered[
                        "Потужність за період, кВт/год"
                    ].mean()
                )

                st.write(
                    "Останні значення:"
                )

                st.dataframe(
                    df_filtered[
                        [
                            "Дата та час",
                            "Потужність за період, кВт/год"
                        ]
                    ].tail(20),
                    use_container_width=True,
                    hide_index=True
                )

    # --------------------------------------------------------
    # ЯКЩО АКТИВНИХ МОДУЛІВ НЕМАЄ
    # --------------------------------------------------------

    else:

        st.warning(
            "Наразі не виявлено активних модулів у базі даних."
        )
