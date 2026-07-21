"""
EDA page — visual tour of the Olist dataset.

Draws every analysis from eda.py so you can SEE the data's shape before asking
questions in the chat. Each block: a chart, the table, and an insight that
suggests a good follow-up question. Reuses the same in-memory SQLite the chat uses.

Auto-appears in the Streamlit sidebar (any file in pages/ becomes a page).
"""

import os
import sys

import streamlit as st

# src/ is the parent of this pages/ folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sql_engine as se  # noqa: E402
import eda  # noqa: E402

st.set_page_config(page_title="Olist EDA", page_icon="📊", layout="wide")


@st.cache_resource(show_spinner="Loading Olist CSVs into SQLite…")
def get_db():
    return se.load_database()


conn, _ = get_db()

st.title("📊 Explore the data")
st.caption(
    "A visual tour of the Olist tables — run this first to see the shape of the data, "
    "then ask sharper questions in the chat. Each insight suggests a question to try."
)


def draw(title, insight, df):
    st.subheader(title)
    st.info(insight)
    # Pick a sensible default chart: 2 columns = label + number → bar (or line for time).
    if df.shape[1] == 2:
        label_col, value_col = df.columns[0], df.columns[1]
        chart_df = df.set_index(label_col)
        # Time series (month strings) read better as a line.
        if label_col in ("month",):
            st.line_chart(chart_df)
        else:
            st.bar_chart(chart_df)
    else:
        # Grouped result (e.g. delivery vs avg_score + n): plot the metric column.
        numeric = df.select_dtypes("number").columns.tolist()
        cat = [c for c in df.columns if c not in numeric]
        if cat and numeric:
            st.bar_chart(df.set_index(cat[0])[numeric[0]])
    with st.expander("See the numbers"):
        st.dataframe(df, use_container_width=True, hide_index=True)
    st.divider()


for title, insight, df in eda.run_all(conn):
    draw(title, insight, df)
