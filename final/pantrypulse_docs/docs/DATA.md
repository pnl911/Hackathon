# Data

Every column is tagged:
- **Real**: copied from a public source
- **Derived**: calculated from real data with a simple rule
- **Simulated**: created by us (weekly visits and capacity only)
- **Model output**: produced by Prophet or the trend model

## Inputs

| File | Source | Used for |
|---|---|---|
| `MMG2025_2019-2023_Data_To_Share_v2.xlsx` | Feeding America, Map the Meal Gap 2025 | County food insecurity 2019-2023 (sheet `County`) |
| `MMG2026_2024_Data_To_Share.xlsx` | Feeding America, Map the Meal Gap 2026 | County food insecurity 2024, cost per meal, SNAP eligibility, rural-urban code; state names (sheet `State`) |
| `snap-households-9.xlsx` | USDA FNS | SNAP households by state, June 2025 vs June 2026 (preliminary) |
| FRED API | Federal Reserve Bank of St. Louis | State unemployment (`{ST}UR`), food-at-home CPI (`CUSR0000SAF11`), GDP (`GDPC1`), CPI (`CPIAUCSL`), inflation (`FPCPITOTLZGUSA`), consumer spending (`PCE`) |

Notes on the inputs:
- Map the Meal Gap values are **modeled estimates** by Feeding America and should be read as approximations.
- Feeding America revised the 2023 county estimates after the 2025 release (their 2026 Read Me explains the error). If you have the revised 2023 file, swap it in.
- Meal cost methodology changed in 2023, so earlier meal costs are not used; only the 2024 cost per meal is used.
- USDA's May and June 2026 SNAP numbers are preliminary. States missing from the file use the national change (flagged in `snap_state_change.csv`).

## Outputs (`outputs/`)

### `county_need.csv`: one row per county (2024)
| Column | Tag | Meaning |
|---|---|---|
| `FIPS` | Real | County ID |
| `State` | Real | Two-letter state code |
| `county` | Derived | e.g. "Dallas County" |
| `county_label` | Real | e.g. "Dallas County, Texas" |
| `fi_rate` | Real | Overall food insecurity rate |
| `fi_persons` | Real | Number of food-insecure people |
| `fi_above_snap` | Real | Share of food-insecure people above the SNAP income limit |
| `cost_per_meal` | Real | Local cost per meal, USD |
| `rucc` | Real | Rural-Urban Continuum Code 2023 (1 = large metro, 9 = most rural) |

### `county_need_2019_2024.csv`: one row per county per year
`FIPS`, `State`, `county_label`, `Year`, `fi_rate`, `fi_persons`. All **real**. This is the historical backbone of the simulation.

### `snap_state_change.csv`: one row per state
| Column | Tag | Meaning |
|---|---|---|
| `hh_jun2025`, `hh_jun2026` | Real | SNAP households |
| `yoy_change` | Real | June 2026 vs June 2025 (e.g. Texas −16.0%) |
| `used_national_value` | Derived | True if the state was missing and the national change (−11.5%) was used |

### `synthetic_weekly_visits.csv`: last 104 weeks, every county
| Column | Tag | Meaning |
|---|---|---|
| `FIPS`, `ds` | | County and week (Monday) |
| `households_per_week` | **Simulated** | Households served that week (see FORECAST_MODEL.md for the formula) |

### `state_weekly_visits.csv`: full history per state (training data for state models)
| Column | Tag | Meaning |
|---|---|---|
| `ds` | | Week (Monday), Jan 2019 onward |
| `school_out` | Derived (calendar) | 1 in June, July, Aug 1-14, Dec 20-31, Jan 1-5 |
| `month_end_share` | Derived (calendar) | Share of the week's days on day 20 or later of the month |
| `snap_index_lag4` | Derived | State SNAP index (1.0 until mid-2025, then moving to 1 + the state's real change), 4 weeks earlier |
| `unemployment_lag` | Real (FRED), lagged | State unemployment rate known 6 weeks earlier (only if FRED is on) |
| `food_cpi_yoy_lag` | Derived from FRED | Food-at-home price inflation, % year over year, 6 weeks earlier (only if FRED is on) |
| `y` | **Simulated** | Sum of the state's county visits |

### `forecast_with_alerts.csv`: 8 future weeks × every county
| Column | Tag | Meaning |
|---|---|---|
| `yhat`, `yhat_lower`, `yhat_upper` | Model output | Expected households per week and range |
| `method` | | "county model" (focus counties) or "state model, top-down" |
| `capacity_hh_per_week` | **Simulated** | Default capacity = recent 8-week average × random 1.00-1.25 |
| `volunteer_shifts_per_week` | Derived | capacity ÷ 25, rounded up |
| `food_capacity_kg_per_week`, `food_capacity_lbs_per_week` | Derived | capacity × 13.6 kg (30 lbs) |
| `recent_hh_per_week` | Derived | Average of the last 8 simulated weeks |
| `cost_per_meal` | Real | 2024 |
| `status`, `gap_hh`, `extra_shifts_needed`, `extra_food_kg`, `extra_food_lbs`, `extra_meals`, `funding_gap_usd` | Derived | Alerts at the default capacity. **The app recalculates all of these live** from the sliders (see CAPACITY_AND_ALERTS.md). |

### `backtest_accuracy.csv`: one row per county
| Column | Meaning |
|---|---|
| `method` | Which model the county used |
| `mape_prophet` | Average % error on the last 12 weeks (never seen in training) |
| `mape_naive_4wk_avg` | Error of "next weeks = average of last 4 weeks" |
| `range_coverage` | Share of those 12 weeks where the actual fell inside the forecast range |

### `annual_need_outlook_2025_2026.csv`
`fi_persons_forecast`, `low`, `high` for 2025 and 2026 per county: a straight-line trend with an 80% prediction range, fitted on the **real** 2019-2024 values only. Six points per county, so treat it as a trend projection.

### `macro_state_latest.csv` (only when FRED is on)
Latest state unemployment rate, its 1-year change, food price inflation, and as-of dates. Written by the forecast script; the dashboard fetches the same values live if this file is missing.

### `fred_cache/`
Raw FRED series as CSV (and `*_info.json` metadata), refreshed after 7 days (forecast script) or 12 hours (dashboard). Lets the demo run offline.

### `example_forecast.png`
One example county chart (a focus county) for quick inspection.
