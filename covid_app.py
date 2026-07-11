"""
app.py
-------
COVID-19 Data Visualization Interface -- v2

Web-based rebuild of the original Tkinter desktop app: same underlying skills
(Python + MySQL + Matplotlib), now a live, shareable Streamlit app instead of
a file someone has to download and run locally.

Run locally:    streamlit run app.py
Deploy free:    push this repo to GitHub, connect it at streamlit.io/cloud,
                and set DB_HOST / DB_USER / DB_PASSWORD / DB_NAME / DB_PORT
                as "Secrets" in the Streamlit Cloud dashboard (pointing at
                your free Aiven MySQL instance, so the deployed app can reach it).
"""

import os
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, text

st.set_page_config(page_title="UK COVID-19 Data Explorer", layout="wide")

st.title("UK COVID-19 Data Explorer")
st.caption(
    "Live case and testing data for England, Scotland, Wales, and Northern Ireland, "
    "sourced from the free UKHSA data dashboard API and served from MySQL."
)

# ---------------------------------------------------------------------------
# MySQL connection -- reads from environment variables locally, or from
# Streamlit's secrets manager when deployed (st.secrets).
# ---------------------------------------------------------------------------
def get_engine():
    if hasattr(st, "secrets") and "DB_HOST" in st.secrets:
        cfg = st.secrets
    else:
        cfg = os.environ

    host = cfg.get("DB_HOST", "localhost")
    port = cfg.get("DB_PORT", "3306")
    user = cfg.get("DB_USER", "root")
    password = cfg.get("DB_PASSWORD", "")
    name = cfg.get("DB_NAME", "covid_dashboard")

    return create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")


@st.cache_resource
def get_connection():
    return get_engine()


@st.cache_data(ttl=3600)
def load_data():
    engine = get_connection()
    query = "SELECT geography, metric, date, metric_value FROM covid_metrics ORDER BY date"
    return pd.read_sql(text(query), con=engine.connect())


try:
    df = load_data()
except Exception as e:
    st.error(
        "Could not connect to the database. Run fetch_and_load.py first to populate MySQL, "
        "and check your DB_HOST / DB_USER / DB_PASSWORD / DB_NAME environment variables "
        f"(or Streamlit secrets). Error: {e}"
    )
    st.stop()

nations = sorted(df["geography"].unique())
metrics = sorted(df["metric"].unique())

col1, col2 = st.columns(2)
with col1:
    selected_nations = st.multiselect("Nations", nations, default=nations)
with col2:
    selected_metric = st.selectbox("Metric", metrics)

filtered = df[(df["geography"].isin(selected_nations)) & (df["metric"] == selected_metric)]

st.subheader(f"{selected_metric} over time")

# Matplotlib chart -- kept deliberately, consistent with the original project's tooling
fig, ax = plt.subplots(figsize=(11, 5))
for nation in selected_nations:
    nation_df = filtered[filtered["geography"] == nation].sort_values("date")
    # 7-day rolling average smooths daily reporting noise -- a real analytical
    # step the original desktop version didn't include
    nation_df = nation_df.set_index("date")
    rolling = nation_df["metric_value"].rolling(7, min_periods=1).mean()
    ax.plot(rolling.index, rolling.values, label=nation)

ax.set_xlabel("Date")
ax.set_ylabel(selected_metric)
ax.set_title(f"{selected_metric} — 7-day rolling average")
ax.legend()
fig.autofmt_xdate()
st.pyplot(fig)

st.subheader("Summary statistics")
summary = (
    filtered.groupby("geography")["metric_value"]
    .agg(["sum", "mean", "max"])
    .rename(columns={"sum": "Total", "mean": "Daily average", "max": "Peak day"})
    .round(1)
)
st.dataframe(summary, use_container_width=True)

st.markdown("---")
st.caption(
    "Data: UK Health Security Agency (UKHSA) data dashboard API, free and public. "
    "Pipeline: Python -> MySQL -> Streamlit + Matplotlib."
)
