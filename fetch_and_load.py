"""
fetch_and_load.py
-------------------
Pulls live COVID-19 data for all four UK nations from the free, public UKHSA
data dashboard API, and loads it into a MySQL database. Pulls two kinds of data:

  1. National case/testing trends (covid_metrics table)
  2. Age- and sex-stratified hospital admissions and vaccination uptake
     (covid_demographics table) -- used to answer "who is still affected?"
     rather than just "how many cases were there?"

No signup or API key required for the UKHSA API.
MySQL can be:
  - a local MySQL Community Server install (100% free, https://dev.mysql.com/downloads/mysql/), or
  - a free-forever Aiven for MySQL cloud instance (no credit card, https://aiven.io/free-mysql-database)
    -- use this option if you want the Streamlit app to be deployed and publicly reachable.

Run:
    python fetch_and_load.py
"""

import os
import time
import requests
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()  # reads a local .env file if present; harmless if it doesn't exist

# ---------------------------------------------------------------------------
# MySQL connection — set these as environment variables, never hard-code
# credentials in code you push to GitHub.
#   export DB_HOST=your-host
#   export DB_PORT=3306
#   export DB_USER=your-user
#   export DB_PASSWORD=your-password
#   export DB_NAME=covid_dashboard
# ---------------------------------------------------------------------------
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "covid_dashboard")

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ---------------------------------------------------------------------------
# UKHSA data dashboard API — free, public, no key required.
# Hierarchical endpoint: /themes/{theme}/sub_themes/{sub_theme}/topics/{topic}/
#                         geography_types/{geography_type}/geographies/{geography}/metrics/{metric}
# ---------------------------------------------------------------------------
BASE_URL = "https://api.ukhsa-dashboard.data.gov.uk"

NATIONS = ["England", "Scotland", "Wales", "Northern Ireland"]

# National-level trends (no age/sex breakdown available for these -- confirmed
# via discover_real_categories.py that admissions only has age='all', sex='all').
METRICS = {
    "COVID-19_cases_casesByDay": "cases",
    "COVID-19_testing_PCRcountByDay": "tests",
    "COVID-19_healthcare_admissionByDay": "admissions",
}

# ---------------------------------------------------------------------------
# Demographic (age/sex) data -- vaccine uptake only.
#
# CONFIRMED via discover_real_categories.py that admissions has NO age/sex
# breakdown (only 'all'/'all' exists) -- so it's a national metric above, not
# a demographic one. Vaccine uptake genuinely IS age-stratified, but only for
# the age groups eligible for the autumn 2024 booster (65+ and related bands),
# using real category labels with HYPHENS, not the underscore scheme used
# elsewhere on this API -- confirmed from the live data itself.
# ---------------------------------------------------------------------------
DEMO_METRICS = {
    "COVID-19_vaccinations_autumn24_uptakeByDay": "vaccine_uptake",
}

# Real age categories confirmed present in the vaccine uptake data.
# "65+" is the aggregate across the other four bands -- excluded from the
# per-band loop below to avoid double-counting, but the app can still show
# it separately as an overall reference if useful.
AGE_BANDS = ["65-69", "70-74", "75-79", "80+"]

SEXES = ["all", "f", "m"]


def fetch_metric(geography: str, metric: str) -> pd.DataFrame:
    """Fetch all pages of a single metric for a single UK nation."""
    url = (
        f"{BASE_URL}/themes/infectious_disease/sub_themes/respiratory/"
        f"topics/COVID-19/geography_types/Nation/geographies/{geography}/metrics/{metric}"
    )
    params = {"page_size": 365}
    records = []

    while url:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        records.extend(payload["results"])
        url = payload.get("next")
        params = {}  # page params are already encoded in the "next" URL
        time.sleep(0.2)  # be polite to the free public API

    df = pd.DataFrame(records)
    if df.empty:
        return df
    return df[["geography", "metric", "date", "metric_value"]]


def fetch_demographic_metric(geography: str, metric: str, age: str, sex: str) -> pd.DataFrame:
    """Fetch a single metric filtered by age band and sex for one UK nation."""
    url = (
        f"{BASE_URL}/themes/infectious_disease/sub_themes/respiratory/"
        f"topics/COVID-19/geography_types/Nation/geographies/{geography}/metrics/{metric}"
    )
    params = {"page_size": 365, "age": age, "sex": sex}
    records = []

    while url:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 404:
            return pd.DataFrame()  # this age/sex/metric combination isn't available
        response.raise_for_status()
        payload = response.json()
        records.extend(payload["results"])
        url = payload.get("next")
        params = {}
        time.sleep(0.2)

    df = pd.DataFrame(records)
    if df.empty:
        return df
    return df[["geography", "metric", "age", "sex", "date", "metric_value"]]


def fetch_all_demographics() -> pd.DataFrame:
    """Fetch admissions and vaccine uptake for every nation x age band x sex."""
    frames = []
    for nation in NATIONS:
        for metric in DEMO_METRICS:
            for age in AGE_BANDS:
                for sex in SEXES:
                    try:
                        df = fetch_demographic_metric(nation, metric, age, sex)
                        if not df.empty:
                            frames.append(df)
                    except requests.HTTPError as e:
                        print(f"  Skipped {metric} / {nation} / age={age} / sex={sex} ({e})")

    if not frames:
        print("No demographic data returned -- check DEMO_METRICS / AGE_BANDS against "
              "the current UKHSA API (metric names occasionally change).")
        return pd.DataFrame(columns=["geography", "metric", "age", "sex", "date", "metric_value"])

    print(f"Fetched {len(frames)} non-empty geography/age/sex/metric combinations")
    return pd.concat(frames, ignore_index=True)


def fetch_all() -> pd.DataFrame:
    frames = []
    for nation in NATIONS:
        for metric in METRICS:
            print(f"Fetching {metric} for {nation}...")
            try:
                df = fetch_metric(nation, metric)
                if not df.empty:
                    frames.append(df)
            except requests.HTTPError as e:
                # Not every metric is guaranteed to exist for every geography --
                # the UKHSA docs note this explicitly. Skip and continue.
                print(f"  Skipped ({e})")
    return pd.concat(frames, ignore_index=True)


def load_to_mysql(df: pd.DataFrame):
    df["date"] = pd.to_datetime(df["date"])

    with engine.connect() as conn:
        # Aiven's managed MySQL requires every table to have a primary key
        # (sql_require_primary_key is enabled for replication safety), and
        # pandas' to_sql() does not create one by default -- so the table is
        # created explicitly here first, with an auto-increment id as the key.
        conn.execute(text("DROP TABLE IF EXISTS covid_metrics"))
        conn.execute(text("""
            CREATE TABLE covid_metrics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                geography VARCHAR(64),
                metric VARCHAR(128),
                date DATETIME,
                metric_value DOUBLE
            )
        """))
        conn.commit()

    df.to_sql("covid_metrics", con=engine, if_exists="append", index=False, chunksize=1000)

    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE covid_metrics ADD INDEX idx_geo_metric_date (geography, metric, date)"
        ))
        conn.commit()

    print(f"Loaded {len(df):,} rows into covid_metrics")


def load_demographics_to_mysql(df: pd.DataFrame):
    if df.empty:
        print("No demographic data to load -- skipping covid_demographics table.")
        return

    df["date"] = pd.to_datetime(df["date"])

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS covid_demographics"))
        conn.execute(text("""
            CREATE TABLE covid_demographics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                geography VARCHAR(64),
                metric VARCHAR(128),
                age VARCHAR(16),
                sex VARCHAR(8),
                date DATETIME,
                metric_value DOUBLE
            )
        """))
        conn.commit()

    df.to_sql("covid_demographics", con=engine, if_exists="append", index=False, chunksize=1000)

    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE covid_demographics ADD INDEX idx_geo_metric_age_sex (geography, metric, age, sex)"
        ))
        conn.commit()

    print(f"Loaded {len(df):,} rows into covid_demographics")


if __name__ == "__main__":
    data = fetch_all()
    load_to_mysql(data)

    demo_data = fetch_all_demographics()
    load_demographics_to_mysql(demo_data)
