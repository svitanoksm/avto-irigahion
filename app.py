import altair as alt
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# ============================================================
# НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="FMS AgronomOk - Моніторинг свердловини", page_icon="💧", layout="wide"
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
  """Перетворює значення з Google Sheets у число."""
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

  # Український / європейський десятковий роздільник
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
  """Надійний пошук стовпця."""
  exact_names = exact_names or []
  contains = contains or []

  # 1. ТОЧНА НАЗВА
  for name in exact_names:
    for col in df.columns:
      if str(col).strip().lower() == name.strip().lower():
        return col

  # 2. ПОШУК ЗА ФРАГМЕНТОМ
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
      "https://www.googleapis.com/auth/drive.readonly",
  ]

  creds_dict = dict(st.secrets["gcp_service_account"])

  creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

  client = gspread.authorize(creds)

  spreadsheet = client.open(SPREADSHEET_NAME)

  sheet = spreadsheet.worksheet(WORKSHEET_NAME)

  values = sheet.get_all_values(value_render_option="FORMATTED_VALUE")

  if not values:
    return pd.DataFrame()

  headers = [str(h).strip() for h in values[0]]
  rows = values[1:]

  df = pd.DataFrame(rows, columns=headers)

  # ДАТА
  date_col = find_column(df, exact_names=["Дата та час"], contains=["дата"])

  if date_col:
    df["Дата та час"] = pd.to_datetime(df[date_col], errors="coerce")

  # Очистка всіх колонок витрат енергії та води автоматично
  for col in list(df.columns):
    col_lower = str(col).lower()
    if (
        "витрати" in col_lower
        and "квт" in col_lower
        or "витрати" in col_lower
        and (
            "м³" in col_lower
            or "куб" in col_lower
            or "м." in col_lower
            or "води" in col_lower
        )
    ):
      df[col] = df[col].apply(convert_to_number)

  # СОРТУВАННЯ
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

menu_option = st.sidebar.radio("Перейти до:", ["Головна панель", "Поливні модулі"])


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
      df[module_col].dropna().astype(str).str.strip().unique().tolist()
  )
  modules_list = [m for m in modules_list if m != "Вимкнено"]
else:
  modules_list = []


# ============================================================
# ГОЛОВНА ПАНЕЛЬ
# ============================================================

if menu_option == "Головна панель":
  st.title("📊 Загальний моніторинг свердловини")

  latest = df.iloc[-1]

  col1, col2, col3, col4 = st.columns(4)

  # СТАН
  state_col = next(
      (c for c in df.columns if "стан" in str(c).lower()),
      None,
  )
  col1.metric("Стан вимикача", latest.get(state_col, "Н/Д") if state_col else "Н/Д")

  # ВИТРАТИ ВОДИ
  water_col = next(
      (
          c
          for c in df.columns
          if "витрати" in str(c).lower()
          and (
              "м³" in str(c).lower()
              or "куб" in str(c).lower()
              or "м." in str(c).lower()
          )
      ),
      None,
  )
  water = convert_to_number(latest.get(water_col, 0) if water_col else 0)
  water = water if water is not None else 0
  col2.metric("Загальні витрати води", f"{water:.2f} м³")

  # ЕНЕРГІЯ
  energy_col = next(
      (
          c
          for c in df.columns
          if "витрати" in str(c).lower() and "квт" in str(c).lower()
      ),
      None,
  )
  energy = convert_to_number(latest.get(energy_col, 0) if energy_col else 0)
  energy = energy if energy is not None else 0
  col3.metric("Загальна енергія", f"{energy:.2f} кВт")

  # МОДУЛЬ
  col4.metric(
      "Поточний модуль",
      latest.get(module_col, "Н/Д") if module_col else "Н/Д",
  )

  st.subheader("Останні записи з таблиці")
  st.dataframe(df.tail(10), use_container_width=True, hide_index=True)


# ============================================================
# ПОЛИВНІ МОДУЛІ
# ============================================================

elif menu_option == "Поливні модулі":
  st.sidebar.markdown("---")
  st.sidebar.subheader("Вибір модуля")

  if len(modules_list) > 0 and module_col:
    selected_module = st.sidebar.selectbox(
        "Оберіть зрошувальний модуль:", modules_list
    )

    st.title(f"⚙️ Моніторинг модуля: {selected_module}")

    df_filtered = df[
        df[module_col].astype(str).str.strip() == selected_module
    ].copy()

    if "Дата та час" in df_filtered.columns:
      df_filtered = df_filtered.sort_values(by="Дата та час")

    if df_filtered.empty:
      st.warning("Немає даних для обраного модуля.")
    else:
      # ============================================================
      # КОМБІНОВАНИЙ СТОВПЧАТИЙ ГРАФІК (ЕЛЕКТРОЕНЕРГІЯ + ВОДА)
      # ============================================================

      st.subheader("📊 Витрати електроенергії та води за період")

      energy_cost_col = next(
          (
              c
              for c in df_filtered.columns
              if "витрати" in str(c).lower() and "квт" in str(c).lower()
          ),
          None,
      )

      water_cost_col = next(
          (
              c
              for c in df_filtered.columns
              if "витрати" in str(c).lower()
              and (
                  "м³" in str(c).lower()
                  or "куб" in str(c).lower()
                  or "м." in str(c).lower()
              )
          ),
          None,
      )

      if energy_cost_col and water_cost_col:
        chart_data = df_filtered[
            ["Дата та час", energy_cost_col, water_cost_col]
        ].copy()

        chart_data[energy_cost_col] = chart_data[energy_cost_col].apply(
            convert_to_number
        )
        chart_data[water_cost_col] = chart_data[water_cost_col].apply(
            convert_to_number
        )

        chart_data = chart_data.dropna(
            subset=["Дата та час", energy_cost_col, water_cost_col]
        )

        if not chart_data.empty:
          melted_data = chart_data.melt(
              id_vars=["Дата та час"],
              value_vars=[energy_cost_col, water_cost_col],
              var_name="Показник",
              value_name="Значення",
          )

          melted_data["Показник"] = melted_data["Показник"].replace({
              energy_cost_col: "Електроенергія",
              water_cost_col: "Вода",
          })

          combined_bar_chart = (
              alt.Chart(melted_data)
              .mark_bar()
              .encode(
                  x=alt.X(
                      "Дата та час:T",
                      title="Дата та час",
                      axis=alt.Axis(format="%H:%M"),
                  ),
                  xOffset="Показник:N",  # Ставить стовпчики поруч
                  y=alt.Y(
                      "Значення:Q",
                      title="Витрати",
                      axis=alt.Axis(format=".1f"),
                  ),
                  color=alt.Color(
                      "Показник:N",
                      scale=alt.Scale(
                          domain=["Електроенергія", "Вода"],
                          range=["red", "blue"],  # Червоний та синій кольори
                      ),
                      legend=alt.Legend(title="Ресурси"),
                  ),
                  tooltip=[
                      alt.Tooltip(
                          "Дата та час:T",
                          title="Дата та час",
                          format="%d.%m.%Y %H:%M:%S",
                      ),
                      alt.Tooltip("Показник:N", title="Ресурс"),
                      alt.Tooltip("Значення:Q", title="Об'єм", format=".2f"),
                  ],
              )
              .properties(height=400)
          )

          st.altair_chart(combined_bar_chart, use_container_width=True)
        else:
          st.info(
              "Немає числових даних для побудови графіка витрат по цьому"
              " модулю."
          )
      else:
        st.warning("Не вдалося знайти необхідні колонки витрат води або енергії.")

      # ============================================================
      # ДЕТАЛЬНІ ДАНІ
      # ============================================================

      with st.expander("📋 Переглянути детальні дані по модулю"):
        st.dataframe(df_filtered, use_container_width=True, hide_index=True)

  else:
    st.warning("Наразі не виявлено активних модулів у базі даних.")
