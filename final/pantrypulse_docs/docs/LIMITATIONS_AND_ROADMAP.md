# Limitations and roadmap

## What is real vs simulated

| Real | Simulated (prototype only) |
|---|---|
| Food insecurity for every US county, 2019-2024 (Feeding America) | Weekly household visits |
| SNAP household change by state (USDA, preliminary June 2026) | Each county's current capacity (volunteers, food on hand) |
| State unemployment, grocery prices, GDP, CPI, inflation, consumer spending (FRED) | The size of economic, SNAP, school, and month-end effects in the history |
| Local cost per meal, SNAP eligibility share, rural-urban codes | County "reach" differences |

## Known limitations
1. **Accuracy proves the method, not real-world performance.** The model is tested on simulated weeks containing patterns we designed. A pilot on real visit data is needed.
2. **Map the Meal Gap values are modeled estimates**, and the 2023 county values were revised by Feeding America after release.
3. **SNAP June 2026 figures are preliminary**; the within-year shape of the decline is assumed.
4. **Transfers assume any county in a state can share with any other.** Real sharing happens within a food bank's service area and depends on distance and trucks.
5. **Top-down forecasts** for non-focus counties assume each county keeps its recent share of the state.
6. **Capacity is weekly and aggregate**: no distinction between sites, days, food categories (produce vs shelf-stable), or volunteer skills.
7. **Economic effects** in the simulation are assumed (+3% per unemployment point, +1% per food inflation point above 2%).
8. **The annual need outlook** uses only six data points per county.
9. **Holidays and school calendars** are national approximations, not district-specific.

## Roadmap
1. **Real visit data**: import exports from Link2Feed or Feeding America's Service Insights (date, site, households served) to replace the simulated history.
2. **Real capacity**: import volunteer schedules and inventory instead of manual inputs.
3. **Service areas**: restrict transfers to a food bank's counties and account for distance.
4. **Donation forecasting**: forecast in-kind donations to complete the supply side.
5. **Local calendars**: school district calendars and local SNAP issuance schedules.
6. **Site-level planning**: forecast per pantry site and distribution day.
7. **Pilot** with a North Texas partner to measure real accuracy and time saved.
8. **Deployment**: host on Streamlit Community Cloud with keys in its Secrets settings, and add user accounts.
