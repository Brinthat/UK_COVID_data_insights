"""
discover_metrics.py
---------------------
The UKHSA API renames some metrics over time (vaccination campaign metrics especially --
e.g. an "autumn23" uptake metric won't still exist in 2026). Rather than guessing metric
names, this script asks the API directly what's currently available for England, and prints
anything related to COVID-19 healthcare (admissions) and vaccinations, so we can plug the
real, current names into DEMO_METRICS in fetch_and_load.py.

Run:
    python discover_metrics.py
"""

import requests

BASE_URL = "https://api.ukhsa-dashboard.data.gov.uk"
URL = (
    f"{BASE_URL}/themes/infectious_disease/sub_themes/respiratory/"
    f"topics/COVID-19/geography_types/Nation/geographies/England/metrics"
)

response = requests.get(URL, params={"page_size": 365}, timeout=30)
response.raise_for_status()
payload = response.json()

# The response shape can vary slightly (a plain list vs a paginated {"results": [...]})
metrics = payload if isinstance(payload, list) else payload.get("results", payload)

print(f"Found {len(metrics)} metrics for COVID-19 / Nation / England:\n")

healthcare_related = []
vaccination_related = []
other = []

for m in metrics:
    # entries are sometimes plain strings, sometimes dicts with a "metric" key
    name = m if isinstance(m, str) else m.get("metric", str(m))
    lower = name.lower()
    if "admission" in lower or "healthcare" in lower or "hospital" in lower:
        healthcare_related.append(name)
    elif "vaccin" in lower or "uptake" in lower or "dose" in lower:
        vaccination_related.append(name)
    else:
        other.append(name)

print("=== Healthcare / admissions metrics ===")
for name in healthcare_related:
    print(" ", name)

print("\n=== Vaccination / uptake metrics ===")
for name in vaccination_related:
    print(" ", name)

print(f"\n({len(other)} other metrics not shown -- cases/testing/deaths etc.)")
