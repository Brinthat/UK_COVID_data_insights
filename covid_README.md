# UK COVID-19 Data Explorer

A web-based rebuild of an earlier Tkinter desktop COVID data visualization tool: same core
skills (Python + MySQL + Matplotlib), now delivered as a live, shareable Streamlit app fed by
a live public data source instead of a static historical dataset.

**Live demo:** *(add your Streamlit Community Cloud link here once deployed)*

## What changed from the original version

| Original | This version |
|---|---|
| Tkinter desktop GUI (must download and run locally) | Streamlit web app (live public URL) |
| Static/historical dataset | Live UKHSA data dashboard API |
| Single-view charts | Filterable by nation and metric, 7-day rolling average |
| No deployment | Deployed free on Streamlit Community Cloud, MySQL hosted free on Aiven |

## Data source

[UKHSA data dashboard API](https://ukhsa-dashboard.data.gov.uk/access-our-data) — free, public,
no signup or API key required. Pulls daily case counts and PCR testing volumes for England,
Scotland, Wales, and Northern Ireland.

## Tech stack

- **Python** — data pipeline (`requests`, `pandas`)
- **MySQL** — storage layer (local MySQL Community Server for development; free-forever
  [Aiven for MySQL](https://aiven.io/free-mysql-database) for the deployed version — no credit
  card required)
- **SQLAlchemy + PyMySQL** — database connectivity
- **Streamlit** — interactive web interface
- **Matplotlib** — visualisation (kept from the original project, now embedded in a web app
  instead of a Tkinter window)

## Repo structure

```
├── fetch_and_load.py      # pulls data from UKHSA API, loads into MySQL
├── app.py                 # Streamlit web app (was: Tkinter desktop app)
├── requirements.txt
└── README.md
```

## How to run

### 1. Set up MySQL (choose one)
- **Local (for development):** install [MySQL Community Server](https://dev.mysql.com/downloads/mysql/) (free), create a database called `covid_dashboard`
- **Cloud (for deployment):** sign up for [Aiven for MySQL](https://aiven.io/free-mysql-database) — free forever, no credit card

### 2. Set your database credentials as environment variables
```bash
export DB_HOST=your-host
export DB_PORT=3306
export DB_USER=your-user
export DB_PASSWORD=your-password
export DB_NAME=covid_dashboard
```

### 3. Fetch the data
```bash
pip install -r requirements.txt
python fetch_and_load.py
```

### 4. Run the app
```bash
streamlit run app.py
```

### 5. Deploy free (optional)
Push this repo to GitHub, connect it at [streamlit.io/cloud](https://streamlit.io/cloud), and
add your DB credentials under the app's **Secrets** in the Streamlit Cloud dashboard.

## Notes

- The UKHSA API is hierarchical and not every metric is guaranteed to exist for every geography —
  `fetch_and_load.py` skips and logs any unavailable combinations rather than failing.
- Never commit database credentials to GitHub — this project reads them from environment
  variables / Streamlit secrets, not hard-coded values.
