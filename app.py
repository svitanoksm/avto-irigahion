import streamlit as st
import pandas as pd
from PIL import Image

# Припускаємо, що у вас вже є змінні:
# max_date - максимальна дата у датасеті
# df_filtered - відфільтрований DataFrame з даними
# selected_module - обраний зрошувальний модуль
# trees_count - кількість дерев у модулі (наприклад, 1387)
# water_metric_col - назва колонки з лічильником води

st.markdown(f"### 🌳 Аналітика поливу однієї рослини: Модуль {selected_module}")

col_img, col_data = st.columns([1, 1.3], gap="large")

with col_img:
    st.markdown("### 🌿 Фундук")
    try:
        # Відкриваємо зображення та за потреби підрізаємо зайвий низ (землю і табличку)
        img = Image.open("image_693716.jpg")
        width, height = img.size
        img_cropped = img.crop((0, 0, width, int(height * 0.75)))
        
        st.image(img_cropped, use_container_width=True, caption=f"Модуль: {selected_module} ({trees_count} дерев)")
    except Exception:
        st.warning("Не вдалося завантажити зображення 'image_693716.jpg'. Перевірте наявність файлу в папці проєкту.")

with col_data:
    st.markdown("### 📊 Отримано води однією рослиною")
    
    # Функція розрахунку води за період (у днях від початку вибірки)
    def get_water_per_tree_for_period(days_start, days_end):
        start_t = max_date - pd.Timedelta(days=days_end)
        end_t = max_date - pd.Timedelta(days=days_start)

        mask = (df_filtered["Дата та час"] >= start_t) & (df_filtered["Дата та час"] <= end_t)
        sub_df = df_filtered[mask]

        total_m3 = 0.0
        if water_metric_col and not sub_df.empty:
            vals = sub_df[water_metric_col].dropna()
            if len(vals) >= 2:
                total_m3 = float(vals.iloc[-1]) - float(vals.iloc[0])
            elif len(vals) == 1:
                total_m3 = float(vals.iloc[0])

        liters_total = total_m3 * 1000
        per_tree = liters_total / trees_count if trees_count > 0 else 0.0
        return per_tree

    # Виведення показника за добу (останні 24 години)
    daily_water = get_water_per_tree_for_period(0, 1)
    st.markdown(
        f"""
        <div style="background-color: #f0f4f8; padding: 10px 15px; border-radius: 8px; margin-bottom: 20px;">
            <span style="color: #0068c9; font-size: 16px; font-weight: 500;">💧 За добу (24 години):</span> 
            <span style="font-size: 18px; font-weight: bold; color: #111;">{daily_water:.1f} л</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("### 📅 Розподіл по тижнях року")

    # Словник для місяців українською
    months_ua = {
        1: "січ", 2: "лют", 3: "бер", 4: "квіт", 5: "тра", 6: "черв",
        7: "лип", 8: "серп", 9: "вер", 10: "жовт", 11: "лист", 12: "груд"
    }

    table_data = []
    year_start = pd.Timestamp(max_date.year, 1, 1)

    # Формуємо таблицю по тижнях року
    for w in range(1, 53):
        start_d_num = (w - 1) * 7 + 1
        end_d_num = w * 7
        if start_d_num > 365:
            break
        if end_d_num > 365:
            end_d_num = 365

        start_date_obj = year_start + pd.Timedelta(days=start_d_num - 1)
        end_date_obj = year_start + pd.Timedelta(days=end_d_num - 1)

        date_str = (
            f"{start_date_obj.day} {months_ua[start_date_obj.month]} – "
            f"{end_date_obj.day} {months_ua[end_date_obj.month]}"
        )

        val_w = get_water_per_tree_for_period(start_d_num, end_d_num)
        
        table_data.append({
            "Тиждень": f"{w} тиждень року",
            "Дати тижня": date_str,
            "Об'єм води на 1 дерево": f"{val_w:.1f} л"
        })

    df_table = pd.DataFrame(table_data)

    st.dataframe(
        df_table,
        use_container_width=True,
        hide_index=True,
        height=400
    )
