"""
discover_real_categories.py
-----------------------------
Test 1/2/4/5 revealed that these two metrics don't use the simple age-band scheme
we assumed. Instead of guessing further, this fetches a real page of data with NO
age/sex filter and prints every distinct age and sex value actually present --
the ground truth for how each metric is really categorised.

Run:
    python discover_real_categories.py
"""

import requests

BASE_URL = "https://api.ukhsa-dashboard.data.gov.uk"


def discover(geography, metric, label):
    url = (
        f"{BASE_URL}/themes/infectious_disease/sub_themes/respiratory/"
        f"topics/COVID-19/geography_types/Nation/geographies/{geography}/metrics/{metric}"
    )
    print(f"\n{'='*70}\n{label}\n{'='*70}")

    all_ages = set()
    all_sexes = set()
    all_strata = set()
    total_rows = 0

    params = {"page_size": 365}
    while url:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            print(f"Status {response.status_code}: {response.text[:300]}")
            return
        payload = response.json()
        results = payload.get("results", [])
        total_rows += len(results)
        for r in results:
            all_ages.add(r.get("age"))
            all_sexes.add(r.get("sex"))
            all_strata.add(r.get("stratum"))
        url = payload.get("next")
        params = {}

    print(f"Total rows found (no filter): {total_rows}")
    print(f"Distinct 'age' values actually used:    {sorted(str(a) for a in all_ages)}")
    print(f"Distinct 'sex' values actually used:     {sorted(str(s) for s in all_sexes)}")
    print(f"Distinct 'stratum' values actually used: {sorted(str(s) for s in all_strata)}")


discover("England", "COVID-19_healthcare_admissionByDay",
          "COVID-19_healthcare_admissionByDay -- real categories")

discover("England", "COVID-19_vaccinations_autumn24_uptakeByDay",
          "COVID-19_vaccinations_autumn24_uptakeByDay -- real categories")
