"""
app.py
-------
COVID-19 Data Visualization Interface -- v2

Web-based rebuild of the original Tkinter desktop app: same underlying skills
(Python + MySQL + Matplotlib), now a live, shareable Streamlit app instead of
a file someone has to download and run locally.

Two tabs:
  1. National Trends       -- case/testing trends by nation (original scope)
  2. Demographic Insights   -- who is still affected: admissions vs vaccine
                                uptake by age band, and a fuzzy-logic
                                "vulnerability index" per age band, adapted
                                from a fuzzy inference approach used in prior
                                agricultural research.

Run locally:    streamlit run app.py
Deploy free:    push this repo to GitHub, connect it at streamlit.io/cloud,
                and set DB_HOST / DB_USER / DB_PASSWORD / DB_NAME / DB_PORT
                as "Secrets" in the Streamlit Cloud dashboard (pointing at
                your free Aiven MySQL instance, so the deployed app can reach it).
"""

import os
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, text
import skfuzzy as fuzz
from skfuzzy import control as ctrl

# Must match AGE_BANDS in fetch_and_load.py, used to keep age bands in natural order
# on charts rather than alphabetical/insertion order.
AGE_BAND_ORDER = ["00-04", "05-14", "15-44", "45-64", "65-74", "75-84", "85+"]

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


@st.cache_data(ttl=3600)
def load_demographics():
    engine = get_connection()
    query = (
        "SELECT geography, metric, age, sex, date, metric_value "
        "FROM covid_demographics ORDER BY date"
    )
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

tab_trends, tab_demographics = st.tabs(["National Trends", "Demographic Insights"])

# ===========================================================================
# TAB 1 -- National Trends (original scope)
# ===========================================================================
with tab_trends:
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

# ===========================================================================
# TAB 2 -- Demographic Insights: who is still affected, not just how many cases
# ===========================================================================
with tab_demographics:
    st.subheader("Hospital admissions vs. vaccine uptake, by age band")
    st.caption(
        "Age bands where admissions are relatively high and vaccine uptake is relatively "
        "low are the groups with the largest 'protection gap' -- the most actionable finding "
        "from this view."
    )

    try:
        demo_df = load_demographics()
    except Exception as e:
        st.warning(
            "Demographic data not found. Run fetch_and_load.py to populate covid_demographics "
            f"(this table is populated by fetch_all_demographics()). Error: {e}"
        )
        demo_df = pd.DataFrame(columns=["geography", "metric", "age", "sex", "date", "metric_value"])

    if not demo_df.empty:
        demo_nation = st.selectbox("Nation", sorted(demo_df["geography"].unique()), key="demo_nation")
        demo_all_sex = demo_df[(demo_df["geography"] == demo_nation) & (demo_df["sex"] == "all")]

        # Average each metric per age band over the full period pulled -- a simple,
        # interpretable summary rather than a full time series, since the point here
        # is comparing groups, not tracking trend.
        age_summary = (
            demo_all_sex.groupby(["age", "metric"])["metric_value"]
            .mean()
            .unstack("metric")
            .reindex(AGE_BAND_ORDER)
            .dropna(how="all")
        )

        if {"admissions", "vaccine_uptake"}.issubset(age_summary.columns):
            fig2, ax2 = plt.subplots(figsize=(10, 5))
            x = np.arange(len(age_summary.index))
            width = 0.35
            ax2.bar(x - width / 2, age_summary["admissions"], width, label="Avg. admissions", color="firebrick")
            ax2.bar(x + width / 2, age_summary["vaccine_uptake"], width, label="Avg. vaccine uptake (%)", color="steelblue")
            ax2.set_xticks(x)
            ax2.set_xticklabels(age_summary.index, rotation=0)
            ax2.set_title(f"Admissions vs. vaccine uptake by age band — {demo_nation}")
            ax2.legend()
            st.pyplot(fig2)

            st.dataframe(age_summary.round(2), use_container_width=True)

            # -----------------------------------------------------------------
            # Fuzzy Vulnerability Index -- adapted from a Mamdani fuzzy inference
            # approach (triangular membership functions, rule-based inference)
            # used in prior fuzzy-logic research, applied here to combine two
            # imprecise demographic signals into one interpretable score.
            # -----------------------------------------------------------------
            st.subheader("Fuzzy Vulnerability Index by age band")
            st.caption(
                "A Mamdani fuzzy inference system combining admission rate and vaccine "
                "uptake into a single 0-10 vulnerability score per age band, using "
                "triangular membership functions and a 3x3 rule base."
            )

            admission_max = max(age_summary["admissions"].max(), 1)
            uptake_max = max(age_summary["vaccine_uptake"].max(), 1)

            admission = ctrl.Antecedent(np.linspace(0, admission_max, 100), "admission")
            uptake = ctrl.Antecedent(np.linspace(0, uptake_max, 100), "uptake")
            vulnerability = ctrl.Consequent(np.linspace(0, 10, 100), "vulnerability")

            admission.automf(3, names=["low", "medium", "high"])
            uptake.automf(3, names=["low", "medium", "high"])

            vulnerability["low"] = fuzz.trimf(vulnerability.universe, [0, 0, 5])
            vulnerability["moderate"] = fuzz.trimf(vulnerability.universe, [2, 5, 8])
            vulnerability["high"] = fuzz.trimf(vulnerability.universe, [5, 10, 10])

            rules = [
                ctrl.Rule(admission["high"] & uptake["low"], vulnerability["high"]),
                ctrl.Rule(admission["high"] & uptake["medium"], vulnerability["high"]),
                ctrl.Rule(admission["medium"] & uptake["low"], vulnerability["high"]),
                ctrl.Rule(admission["medium"] & uptake["medium"], vulnerability["moderate"]),
                ctrl.Rule(admission["high"] & uptake["high"], vulnerability["moderate"]),
                ctrl.Rule(admission["low"] & uptake["low"], vulnerability["moderate"]),
                ctrl.Rule(admission["medium"] & uptake["high"], vulnerability["low"]),
                ctrl.Rule(admission["low"] & uptake["medium"], vulnerability["low"]),
                ctrl.Rule(admission["low"] & uptake["high"], vulnerability["low"]),
            ]

            vulnerability_ctrl = ctrl.ControlSystem(rules)

            scores = {}
            for age_band, row in age_summary.dropna(subset=["admissions", "vaccine_uptake"]).iterrows():
                sim = ctrl.ControlSystemSimulation(vulnerability_ctrl)
                sim.input["admission"] = row["admissions"]
                sim.input["uptake"] = row["vaccine_uptake"]
                sim.compute()
                scores[age_band] = sim.output["vulnerability"]

            if scores:
                score_series = pd.Series(scores).reindex([a for a in AGE_BAND_ORDER if a in scores])
                fig3, ax3 = plt.subplots(figsize=(10, 4))
                colors = ["firebrick" if v >= 6 else "goldenrod" if v >= 3.5 else "seagreen" for v in score_series.values]
                ax3.bar(score_series.index, score_series.values, color=colors)
                ax3.set_ylabel("Fuzzy vulnerability score (0-10)")
                ax3.set_title(f"Fuzzy Vulnerability Index by age band — {demo_nation}")
                ax3.set_ylim(0, 10)
                st.pyplot(fig3)

                highest = score_series.idxmax()
                st.info(
                    f"Highest fuzzy vulnerability in this nation: age band **{highest}** "
                    f"(score {score_series.max():.1f}/10) — the combination of admission rate "
                    "and vaccine uptake makes this the group where the 'protection gap' is largest."
                )
        else:
            st.warning(
                "Both 'admissions' and 'vaccine_uptake' metrics are needed for this view. "
                "Check that fetch_and_load.py successfully pulled both DEMO_METRICS."
            )

        st.markdown("#### Sex-based comparison (acute outcomes)")
        st.caption(
            "Compares male vs. female rates directly for the selected metric -- global "
            "research shows men have historically had somewhat higher rates of severe "
            "acute outcomes, while women more often report persistent/long-term symptoms "
            "(the latter isn't captured in this acute-outcomes dataset)."
        )
        sex_metric = st.selectbox("Metric", sorted(demo_df["metric"].unique()), key="sex_metric")
        sex_df = demo_df[
            (demo_df["geography"] == demo_nation)
            & (demo_df["metric"] == sex_metric)
            & (demo_df["sex"].isin(["f", "m"]))
        ]
        if not sex_df.empty:
            sex_summary = sex_df.groupby(["age", "sex"])["metric_value"].mean().unstack("sex").reindex(AGE_BAND_ORDER).dropna(how="all")
            st.bar_chart(sex_summary)
        else:
            st.caption("No sex-disaggregated data available for this metric/nation combination.")

st.markdown("---")
st.caption(
    "Data: UK Health Security Agency (UKHSA) data dashboard API, free and public. "
    "Pipeline: Python -> MySQL -> Streamlit + Matplotlib + scikit-fuzzy."
)
