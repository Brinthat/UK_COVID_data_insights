"""
fetch_and_load.py
-------------------
Pulls live COVID-19 case and testing data for all four UK nations from the free,
public UKHSA data dashboard API, and loads it into a MySQL database.

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


if __name__ == "__main__":
    data = fetch_all()
    load_to_mysql(data)
