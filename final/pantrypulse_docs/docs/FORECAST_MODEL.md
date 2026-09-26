# Forecast model (`demand_forecast_us.py`)

This script builds everything the dashboard needs. Run it with `python demand_forecast_us.py`; it prints progress with timestamps and a summary at the end.

## Settings (top of the script)

| Setting | Default | Meaning |
|---|---|---|
| `START`, `END` | 2019-01-07, 2026-09-21 | Weekly history range (Mondays) |
| `HOLDOUT_WEEKS` | 12 | Weeks hidden for the accuracy test |
| `HORIZON_WEEKS` | 8 | Weeks forecast ahead |
| `HH_SIZE` | 2.6 | People per household |
| `KG_PER_HOUSEHOLD_VISIT` | 13.6 (≈30 lb) | Food per household visit |
| `KG_PER_MEAL` | 0.544 (1.2 lb) | Feeding America meal standard |
| `HOUSEHOLDS_PER_SHIFT` | 25 | Households one volunteer shift serves |
| `FOCUS_COUNTIES` | 13 NTFB counties in TX | Get their own county-level model |
| `USE_FRED`, `FRED_LAG_WEEKS` | True, 6 | Economic factors and their lag |
| `UNEMP_EFFECT`, `FOOD_CPI_EFFECT` | 0.03, 0.01 | Assumed economic response, used **only** to build the simulated history |

## Step by step, with the reasoning

### Step 1. Load real need data
Map the Meal Gap county sheets for 2019-2023 and 2024 are stacked into one panel (`county_need_2019_2024.csv`), and the 2024 snapshot is saved (`county_need.csv`).
**Why:** everything else is built on this. Real annual need tells us how big each county's problem is and which direction it is moving.

### Step 2. Load each state's SNAP change
From the USDA file: June 2026 vs June 2025 households per state (Texas −16.0%, national −11.5%).
**Why:** SNAP is a federal program, but enrollment changes very differently by state (Arizona fell about 49%, Alaska rose). Using each state's own change keeps the SNAP signal local.

### Step 3. Build the weekly calendar and features
One row per Monday, with:
- `school_out`: school break weeks (kids lose school meals)
- `month_end_share`: how much of the week falls on day 20 or later (benefits running out)
- `snap_index_lag4`: 1.0 until June 30, 2025, then a straight line to (1 + state change) by June 29, 2026, lagged 4 weeks

**Why the lag:** families don't arrive the day they lose benefits; it takes a few weeks for savings and cupboards to run out. The lag also keeps the forecast honest: when predicting next week, a food bank only knows SNAP numbers from a few weeks ago.

### Step 4. Load economic factors from FRED (optional)
State unemployment (`{ST}UR`) and food-at-home prices (`CUSR0000SAF11`, turned into % change vs a year earlier), both lagged 6 weeks. See FRED_ECONOMIC_DATA.md.
**Why:** job losses and rising grocery prices push more families to food banks a few weeks later. The 6-week lag covers publishing delay plus the time families take to respond.

### Step 5. Simulate weekly households served
Real visit data is private, so the weekly history is simulated, with the **long-term level tied to real data**:

```
households = (real food-insecure people ÷ 2.6) × reach
             × seasonal × holiday × school × month_end × snap × economy × noise
```

| Factor | Value | Why |
|---|---|---|
| Real level | Each county's annual `fi_persons`, placed on July 1 and interpolated weekly | Real trend (e.g. Dallas 364,840 in 2019 → 503,440 in 2024) |
| `reach` | Random 1.8%-2.6% of food-insecure households per week, reduced 4% per rural level | Rural counties face access barriers (assumption) |
| `seasonal` | ±6% sine wave peaking in late June | Mild yearly cycle |
| `holiday` | ×1.10 in November and December | Holiday peak |
| `school` | ×1.12 when school is out | Lost school meals |
| `month_end` | up to ×1.15 | Benefits running out |
| `snap` | 1 + 1.2 × (1 − lagged SNAP index) | Fewer people on SNAP → more pantry visits |
| `economy` | 1 + 0.03 × (unemployment − state's 2019 average) + 0.01 × (food inflation − 2), clipped 0.7-1.8 | Only when FRED is on. Also produces a 2020 surge, matching what food banks experienced |
| `noise` | Random, about ±5% | Real data is never smooth |

All factors multiply, because effects scale with county size: +12% in summer is hundreds of households in Dallas and a handful in a rural county.

### Step 6. Fit Prophet models

**Prophet configuration:**

| Setting | Choice | Why |
|---|---|---|
| Yearly seasonality | On | Demand repeats yearly |
| Weekly, daily seasonality | Off | Data is one number per week |
| Seasonality mode | Multiplicative | Effects scale with size |
| US holidays | Added | Holidays shift demand |
| Regressors | `school_out`, `month_end_share`, `snap_index_lag4` (+ `unemployment_lag`, `food_cpi_yoy_lag` with FRED) | Known drivers used directly |
| `changepoint_prior_scale` | 0.1 | Trend flexible enough to follow real changes, not noise |
| `interval_width` | 0.90 | See step 8 |

**Two ways of forecasting counties:**

1. **State model, top-down (all 3,142 counties).** Prophet forecasts each state's weekly total (51 models). Each county gets its share of recent visits (last 8 weeks). Each county's range is widened by its own week-to-week variation, combining the state's uncertainty with the county's:
   `total_sd = sqrt(state_relative_sd² + county_sd²)`.
   **Why:** fitting 3,142 separate models would take 30+ minutes. Top-down forecasting is a standard method for large hierarchies.
2. **County model (the 13 focus counties).** Each focus county gets its own Prophet model.
   **Why:** the demo region deserves the most accurate forecasts, and a food bank plans within its own service area.

### Step 7. Backtest on unseen weeks
The last 12 weeks are hidden, the models are trained on everything before, and the predictions are compared with what happened. The same weeks are also predicted by a naive rule: "average of the last 4 weeks", which is roughly what a coordinator does today.

Typical results (exact numbers print at the end of every run):

| Method | Counties | Prophet error | Naive error | Actual inside range |
|---|---|---|---|---|
| County model | 13 | ≈4% | ≈10% | ≈77% |
| State model, top-down | 3,129 | ≈4.5% | ≈11% | ≈88% |

**Why:** this answers "why not just use last month's average?" Prophet roughly halves the error.

### Step 8. Honest uncertainty ranges
In an earlier version, the nominal 80% range contained the actual value only about 55% of the time; the ranges were too narrow. Since alerts fire on the **high end**, narrow ranges mean missed alerts. The nominal level was raised and county noise added (top-down) until real coverage was reasonable.

### Step 9. Refit on all history and forecast 8 weeks
Models are refit on the full history. Future calendar features are known exactly; lagged SNAP and FRED values are known because of the lags (the last known value carries forward if needed).

### Step 10. Default capacity and alerts
Capacity is **simulated** as recent 8-week average × random 1.00-1.25 (roughly what each county has been handling). Alerts at this default are saved, but the dashboard recalculates them live from user inputs (CAPACITY_AND_ALERTS.md).

### Step 11. Annual need outlook (real data only)
A straight line fitted to each county's six real yearly values, projected to 2025 and 2026 with an 80% prediction range (t-distribution). Prophet on six points is effectively a straight line, and 3,142 Prophet fits would take much longer.

## Honesty note on accuracy
The simulated history contains the patterns the model learns, so good accuracy proves the **pipeline works**, not real-world accuracy. With a food bank's real visit export, the same code would measure real accuracy and estimate the true size of each effect (including the economic effects, which are assumptions in the simulation).

## Runtime
About 35 seconds on a fast machine; expect 1-3 minutes on a laptop. Progress prints with timestamps.
