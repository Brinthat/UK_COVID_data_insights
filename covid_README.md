# UK COVID-19 Data Explorer



**Live demo:** *(add your Streamlit Community Cloud link here once deployed)*





## Data source

[UKHSA data dashboard API](https://ukhsa-dashboard.data.gov.uk/access-our-data) — free, public,
no signup or API key required. Pulls daily case counts and PCR testing volumes for England,
Scotland, Wales, and Northern Ireland.

## Tech stack

- **Python** — data pipeline (`requests`, `pandas`)
- **MySQL** —[Aiven for MySQL](https://aiven.io/free-mysql-database) for the deployed version 
- **SQLAlchemy + PyMySQL** — database connectivity
- **Streamlit** — interactive web interface
- **Matplotlib** — visualisation 

## Repo structure

```
├── fetch_and_load.py      # pulls data from UKHSA API, loads into MySQL
├── app.py                 # Streamlit web app
├── requirements.txt
└── README.md
```

## How to run

### 1. Set up MySQL (choose one)
- **Cloud (for deployment):** sign up for [Aiven for MySQL](https://aiven.io/free-mysql-database)
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
