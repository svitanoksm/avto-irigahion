import pandas as pd
import plotly.express as px
import streamlit as st
# Припустимо, що ваш датафрейм називається df і містить колонки:
# 'Date' (або інший період), 'Electricity' (електроенергія), 'Water' (вода)


def plot_resource_usage(df):
  # Перевіряємо наявність необхідних колонок
  required_cols = ['Date', 'Electricity', 'Water']
  if not all(col in df.columns for col in required_cols):
    st.error(
        "У таблиці відсутні необхідні колонки ('Date', 'Electricity', 'Water')."
    )
    return

  # Плануємо зведений стовпчастий графік за допомогою Plotly Express
  # Використовуємо melt, щоб перетворити таблицю у зручний для побудови формат
  df_melted = df.melt(
      id_vars=['Date'],
      value_vars=['Electricity', 'Water'],
      var_name='Resource',
      value_Name='Value',
  )

  # Перейменовуємо для красивого відображення в легенді та на графіку
  df_melted['Resource'] = df_melted['Resource'].map({
      'Electricity': 'Електроенергія',
      'Water': 'Вода',
  })

  # Створюємо графік ізгрупованих стовпців
  fig = px.bar(
      df_melted,
      x='Date',
      y='Value',
      color='Resource',
      barmode='group',  # Групуємо стовпці поруч один з одним
      labels={
          'Date': 'Період',
          'Value': 'Витрати',
          'Resource': 'Ресурс',
      },
      color_discrete_map={
          'Електроенергія': 'red',  # Червоний колір для електроенергії
          'Вода': 'blue',  # Синій колір для води
      },
  )

  # Налаштування зовнішнього вигляду
  fig.update_layout(
      xaxis_title='Період',
      yaxis_title='Витрати (од. виміру)',
      legend_title='Ресурси',
      bargap=0.15,  # Відстань між групами стовпців
      bargroupgap=0.1,  # Відстань між стовпцями всередині групи
  )

  # Виводимо графік у Streamlit
  st.plotly_chart(fig, use_container_width=True)
