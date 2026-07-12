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

METRICS = {
    "COVID-19_cases_casesByDay": "cases",
    "COVID-19_testing_PCRcountByDay": "tests",
}

# ---------------------------------------------------------------------------
# Demographic (age/sex) data -- healthcare (hospital admissions) and
# vaccination uptake, filtered by age band and sex, so we can ask "who is
# still affected?" rather than just "how many cases were there?"
#
# NOTE: not every metric name below is guaranteed to exist for every
# geography/age/sex combination -- the UKHSA API docs are explicit about
# this. fetch_demographic_metric() skips and logs anything unavailable
# rather than failing, so double check console output after running this
# and adjust DEMO_METRICS / AGE_BANDS if a particular combination is empty.
# ---------------------------------------------------------------------------
DEMO_METRICS = {
    "COVID-19_healthcare_admissionByDay": "admissions",
    "COVID-19_vaccinations_autumn23_uptakeByDay": "vaccine_uptake",
}

AGE_BANDS = [
    "00-04", "05-14", "15-44", "45-64", "65-74", "75-84", "85+",
]

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
    df.to_sql("covid_metrics", con=engine, if_exists="replace", index=False, chunksize=1000)

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
    df.to_sql("covid_demographics", con=engine, if_exists="replace", index=False, chunksize=1000)

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
