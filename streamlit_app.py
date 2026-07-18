import streamlit as st
import pandas as pd

st.set_page_config(page_title="Jojo Stock", layout="wide")

# Read with UTF-8 encoding
df = pd.read_csv('inventory.csv', encoding='utf-8')

st.title('📦 Jojo Stock Inventory')
st.dataframe(df.head(10), use_container_width=True)
