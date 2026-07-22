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
from dotenv import load_dotenv
load_dotenv()  # reads a local .env file if present; harmless if it doesn't exist

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, text
import skfuzzy as fuzz
from skfuzzy import control as ctrl

# Must match AGE_BANDS in fetch_and_load.py -- confirmed via discover_real_categories.py
# that these are the real age-band labels the vaccine uptake metric actually uses
# (hyphenated, and only the groups eligible for the autumn 2024 booster).
AGE_BAND_ORDER = ["65-69", "70-74", "75-79", "80+"]

st.set_page_config(page_title="UK COVID-19 Data Explorer", layout="wide")

st.title("UK COVID-19 Data Explorer")
st.caption(
    "Live case and testing data for England, Scotland, Wales, and Northern Ireland, "
    "sourced from the free UKHSA data dashboard API and served from MySQL."
)

# ---------------------------------------------------------------------------
# MySQL connection -- reads from environment variables locally, or from
# Streamlit's secrets manager when deployed (st.secrets).
#
# NOTE: st.secrets raises an error just from being *checked* when no
# secrets.toml file exists at all (as is normal for local runs that use a
# .env file / environment variables instead) -- so this must be wrapped in
# try/except rather than a plain "in" check.
# ---------------------------------------------------------------------------
def get_engine():
    cfg = os.environ
    try:
        if "DB_HOST" in st.secrets:
            cfg = st.secrets
    except Exception:
        pass  # no secrets.toml present -- fall back to environment variables / .env

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
# TAB 2 -- Demographic Insights: vaccine uptake across older age groups
#
# NOTE ON SCOPE: debugging against the live API confirmed that hospital
# admissions has NO age/sex breakdown at all (only a single national daily
# figure exists) -- so it's shown as a national trend in Tab 1 instead.
# Vaccine uptake genuinely IS age-stratified, but only for the age groups
# eligible for the autumn 2024 booster (65-69, 70-74, 75-79, 80+), which is
# what this tab is built around.
# ===========================================================================
with tab_demographics:
    st.subheader("Vaccine uptake across older age groups")
    st.caption(
        "The autumn 2024 booster was offered to specific eligible groups (65+ and related "
        "bands), so this is the age-stratified data that genuinely exists -- admissions data "
        "is only available as a single national figure, shown in the National Trends tab."
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
        demo_all_sex = demo_df[
            (demo_df["geography"] == demo_nation)
            & (demo_df["sex"] == "all")
            & (demo_df["age"].isin(AGE_BAND_ORDER))  # excludes the "65+" aggregate row
        ]

        age_summary = (
            demo_all_sex.groupby("age")["metric_value"]
            .mean()
            .reindex(AGE_BAND_ORDER)
            .dropna()
        )

        if not age_summary.empty:
            fig2, ax2 = plt.subplots(figsize=(9, 5))
            colors = ["seagreen" if v >= age_summary.median() else "goldenrod" for v in age_summary.values]
            ax2.bar(age_summary.index, age_summary.values, color=colors)
            ax2.set_ylabel("Average vaccine uptake (%)")
            ax2.set_title(f"Autumn 2024 booster uptake by age band — {demo_nation}")
            st.pyplot(fig2)

            st.dataframe(age_summary.round(2).rename("Avg. uptake (%)"), use_container_width=True)

            # -----------------------------------------------------------------
            # Fuzzy Vulnerability Index -- adapted from a Mamdani fuzzy inference
            # approach (triangular membership functions, rule-based inference)
            # used in prior fuzzy-logic research.
            #
            # Inputs: (1) vaccine uptake (real data, inverted -- lower uptake
            # means higher vulnerability), and (2) age-band baseline risk, an
            # ordinal 1-4 encoding reflecting the well-established finding that
            # COVID risk increases with age even within older cohorts. This
            # replaces the original admissions-based design, since admissions
            # data has no age breakdown to combine with.
            # -----------------------------------------------------------------
            st.subheader("Fuzzy Vulnerability Index by age band")
            st.caption(
                "A Mamdani fuzzy inference system combining vaccine uptake with an "
                "age-related baseline risk factor into a single 0-10 vulnerability score, "
                "using triangular membership functions and a rule base."
            )

            age_risk_map = {"65-69": 1, "70-74": 2, "75-79": 3, "80+": 4}

            uptake_max = max(age_summary.max(), 1)
            uptake = ctrl.Antecedent(np.linspace(0, uptake_max, 100), "uptake")
            age_risk = ctrl.Antecedent(np.linspace(1, 4, 100), "age_risk")
            vulnerability = ctrl.Consequent(np.linspace(0, 10, 100), "vulnerability")

            uptake.automf(3, names=["low", "medium", "high"])
            age_risk.automf(3, names=["low", "medium", "high"])

            vulnerability["low"] = fuzz.trimf(vulnerability.universe, [0, 0, 5])
            vulnerability["moderate"] = fuzz.trimf(vulnerability.universe, [2, 5, 8])
            vulnerability["high"] = fuzz.trimf(vulnerability.universe, [5, 10, 10])

            rules = [
                ctrl.Rule(age_risk["high"] & uptake["low"], vulnerability["high"]),
                ctrl.Rule(age_risk["high"] & uptake["medium"], vulnerability["high"]),
                ctrl.Rule(age_risk["medium"] & uptake["low"], vulnerability["high"]),
                ctrl.Rule(age_risk["medium"] & uptake["medium"], vulnerability["moderate"]),
                ctrl.Rule(age_risk["high"] & uptake["high"], vulnerability["moderate"]),
                ctrl.Rule(age_risk["low"] & uptake["low"], vulnerability["moderate"]),
                ctrl.Rule(age_risk["medium"] & uptake["high"], vulnerability["low"]),
                ctrl.Rule(age_risk["low"] & uptake["medium"], vulnerability["low"]),
                ctrl.Rule(age_risk["low"] & uptake["high"], vulnerability["low"]),
            ]

            vulnerability_ctrl = ctrl.ControlSystem(rules)

            scores = {}
            for band, uptake_val in age_summary.items():
                sim = ctrl.ControlSystemSimulation(vulnerability_ctrl)
                # Fuzzy inputs blend real data (uptake) with a domain-informed risk
                # factor (age_risk), inverting uptake so LOW uptake drives HIGH vulnerability
                sim.input["uptake"] = max(uptake_max - uptake_val, 0)
                sim.input["age_risk"] = age_risk_map[band]
                sim.compute()
                scores[band] = sim.output["vulnerability"]

            score_series = pd.Series(scores).reindex(AGE_BAND_ORDER).dropna()
            fig3, ax3 = plt.subplots(figsize=(9, 4))
            colors3 = ["firebrick" if v >= 6 else "goldenrod" if v >= 3.5 else "seagreen" for v in score_series.values]
            ax3.bar(score_series.index, score_series.values, color=colors3)
            ax3.set_ylabel("Fuzzy vulnerability score (0-10)")
            ax3.set_title(f"Fuzzy Vulnerability Index by age band — {demo_nation}")
            ax3.set_ylim(0, 10)
            st.pyplot(fig3)

            highest = score_series.idxmax()
            st.info(
                f"Highest fuzzy vulnerability in this nation: age band **{highest}** "
                f"(score {score_series.max():.1f}/10) — driven by a combination of "
                "relatively lower vaccine uptake and higher age-related baseline risk."
            )
        else:
            st.warning(
                "No vaccine uptake data found for this nation. Confirm fetch_and_load.py "
                "successfully populated covid_demographics -- check console output for "
                "'Loaded X rows into covid_demographics'."
            )

        st.markdown("#### Sex-based comparison: vaccine uptake by age band")
        st.caption(
            "Male vs. female uptake rates for the autumn 2024 booster, by age band -- "
            "real data, directly from the UKHSA API's sex filter."
        )
        sex_df = demo_df[
            (demo_df["geography"] == demo_nation)
            & (demo_df["age"].isin(AGE_BAND_ORDER))
            & (demo_df["sex"].isin(["f", "m"]))
        ]
        if not sex_df.empty:
            sex_summary = (
                sex_df.groupby(["age", "sex"])["metric_value"]
                .mean()
                .unstack("sex")
                .reindex(AGE_BAND_ORDER)
                .dropna(how="all")
            )
            st.bar_chart(sex_summary)
        else:
            st.caption("No sex-disaggregated uptake data available for this nation.")

st.markdown("---")
st.caption(
    "Data: UK Health Security Agency (UKHSA) data dashboard API, free and public. "
    "Pipeline: Python -> MySQL -> Streamlit + Matplotlib + scikit-fuzzy."
)
