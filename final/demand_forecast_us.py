"""
PantryPulse - Demand Forecast, ALL US COUNTIES (v3)
===================================================
REAL DATA
  - Feeding America Map the Meal Gap: food-insecure persons for every US county, 2019-2024
      MMG2025_2019-2023 file + MMG2026_2024 file
  - USDA FNS SNAP households by state, June 2025 vs June 2026 (snap-households file)
SIMULATED
  - Weekly households served (follows each county's REAL annual need + known weekly patterns
    + each STATE's REAL SNAP change)
  - Current capacity (replace with the food bank's own numbers in the app)

UNITS (everything is PER WEEK)
  - Demand   = households served per week (one household visit = one household picking up food once)
  - Capacity = households a county's pantries can serve per week
  - Food     = saved in BOTH kilograms (kg) and pounds (lbs). Each household visit receives
               KG_PER_HOUSEHOLD_VISIT kg (13.6 kg = 30 lb). The app has a lbs/kg toggle.
  - Meals    = kg / KG_PER_MEAL  (Feeding America: 1.2 lb = 0.544 kg per meal)
  - Funding  = meals x local cost per meal (real, Map the Meal Gap 2024)

HOW THE FORECAST WORKS (fast enough for 3,100+ counties)
  1. Prophet forecasts each STATE's weekly total (51 models, ~1 minute).
  2. Each state forecast is split to its counties by each county's recent share of visits
     ("top-down" forecasting), and each county's range is widened by its own week-to-week noise.
  3. FOCUS_COUNTIES get their own county-level Prophet model (most accurate, used for the demo region).

Run:   pip install prophet pandas openpyxl matplotlib
       python demand_forecast_us.py
Needs in this folder: MMG2025*.xlsx, MMG2026*.xlsx, snap-households*.xlsx
Outputs: ./outputs/
"""
import glob
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from prophet import Prophet

for _name in ("cmdstanpy", "prophet"):
    logging.getLogger(_name).disabled = True
rng = np.random.default_rng(42)
os.makedirs("outputs", exist_ok=True)
T0 = time.time()

# =================================================================== SETTINGS
FILE_2019_2023 = (glob.glob("MMG2025*.xlsx") or ["MMG2025_2019-2023_Data_To_Share_v2.xlsx"])[0]
FILE_2024 = (glob.glob("MMG2026*.xlsx") or ["MMG2026_2024_Data_To_Share.xlsx"])[0]
FILE_SNAP = (glob.glob("snap-households*.xlsx") or ["snap-households-9.xlsx"])[0]

START, END = "2019-01-07", "2026-09-21"      # weekly history (Mondays)
HOLDOUT_WEEKS = 12                           # backtest length
HORIZON_WEEKS = 8                            # how far ahead we forecast
APP_HISTORY_WEEKS = 104                      # weeks of history saved for the app

# Food and staffing assumptions (all editable in the app)
HH_SIZE = 2.6                    # people per household
KG_PER_HOUSEHOLD_VISIT = 13.6    # kg of food one household receives per visit (about 30 lb)
KG_PER_MEAL = 0.544              # Feeding America standard: 1.2 lb per meal
HOUSEHOLDS_PER_SHIFT = 25        # households one volunteer shift can serve
LBS_PER_KG = 2.20462

# Counties that get their own detailed Prophet model (demo region: North Texas Food Bank)
FOCUS_COUNTIES = {"TX": ["Collin", "Dallas", "Delta", "Denton", "Ellis", "Fannin", "Grayson",
                         "Hopkins", "Hunt", "Kaufman", "Lamar", "Navarro", "Rockwall"]}

REGRESSORS = ["school_out", "month_end_share", "snap_index_lag4"]
Z90 = 1.645

def log(msg):
    print(f"[{time.time() - T0:5.0f}s] {msg}", flush=True)

for f in [FILE_2019_2023, FILE_2024, FILE_SNAP]:
    if not os.path.exists(f):
        sys.exit(f"ERROR: '{f}' not found in {os.getcwd()}\n"
                 f"Excel files here: {glob.glob('*.xlsx') or 'none'}\n"
                 "Need files starting with MMG2025, MMG2026 and snap-households.")
log(f"Using {FILE_2019_2023}, {FILE_2024}, {FILE_SNAP}")

# =================================================================== 1. REAL DATA
log("Loading Map the Meal Gap (all US counties, 2019-2024)...")
RENAME = {"Overall Food Insecurity Rate": "fi_rate", "# of Food Insecure Persons Overall": "fi_persons",
          "% FI > SNAP Threshold": "fi_above_snap", "Cost Per Meal": "cost_per_meal",
          "Rural-Urban Continuum Code (2023)": "rucc", "County, State": "county_label"}
old = pd.read_excel(FILE_2019_2023, sheet_name="County").rename(columns=RENAME)
new = pd.read_excel(FILE_2024, sheet_name="County").rename(columns=RENAME)
states = pd.read_excel(FILE_2024, sheet_name="State")[["State", "State Name"]]

need = new.dropna(subset=["fi_persons", "fi_rate"]).copy()
need["county"] = need["county_label"].str.split(",").str[0].str.strip()
need["rucc"] = need["rucc"].fillna(need["rucc"].median()).astype(int)
need = need[["FIPS", "State", "county", "county_label", "fi_rate", "fi_persons", "fi_above_snap",
             "cost_per_meal", "rucc"]].sort_values("FIPS").reset_index(drop=True)
need.to_csv("outputs/county_need.csv", index=False)

panel = pd.concat([old, new], ignore_index=True)[["FIPS", "State", "county_label", "Year", "fi_rate", "fi_persons"]]
panel = panel.dropna(subset=["fi_persons"])
panel = panel[panel["FIPS"].isin(need["FIPS"])].sort_values(["FIPS", "Year"])
panel.to_csv("outputs/county_need_2019_2024.csv", index=False)
log(f"{len(need):,} counties with 2024 data; {len(panel):,} county-year rows")

# SNAP change by state (REAL, preliminary June 2026)
snap_raw = pd.read_excel(FILE_SNAP, header=2)
snap_raw = snap_raw.iloc[:, [0, 1, 3, 5]]
snap_raw.columns = ["State Name", "hh_jun2025", "hh_jun2026", "yoy_change"]
national = pd.to_numeric(snap_raw.loc[snap_raw["State Name"].astype(str).str.strip() == "TOTAL", "yoy_change"]).iloc[0]
snap = states.merge(snap_raw, on="State Name", how="left")
snap["yoy_change"] = pd.to_numeric(snap["yoy_change"], errors="coerce").fillna(national)
snap["used_national_value"] = snap["hh_jun2025"].isna()
snap.to_csv("outputs/snap_state_change.csv", index=False)
log(f"SNAP change: national {national:.1%}; e.g. TX {snap.set_index('State').loc['TX', 'yoy_change']:.1%}")

# =================================================================== 2. CALENDAR + SNAP FEATURES
n_hist = len(pd.date_range(START, END, freq="W-MON"))
dates = pd.date_range(START, periods=n_hist + HORIZON_WEEKS, freq="W-MON")
cal = pd.DataFrame({"ds": dates})
cal["month_end_share"] = [np.mean([(d + pd.Timedelta(days=i)).day >= 20 for i in range(7)]) for d in dates]
m, day = cal["ds"].dt.month, cal["ds"].dt.day
cal["school_out"] = (((m == 6) | (m == 7) | ((m == 8) & (day < 15))) |
                     ((m == 12) & (day >= 20)) | ((m == 1) & (day <= 5))).astype(int)

# State SNAP index: 1.0 until mid-2025, then moves linearly to (1 + that state's real change) by mid-2026
i0 = np.searchsorted(cal["ds"], pd.Timestamp("2025-06-30"))
i1 = np.searchsorted(cal["ds"], pd.Timestamp("2026-06-29"))
state_list = sorted(need["State"].unique())
snap_idx = {}
for s in state_list:
    end_val = 1 + snap.set_index("State").loc[s, "yoy_change"]
    v = np.ones(len(cal))
    v[i0:i1] = np.linspace(1.0, end_val, i1 - i0)
    v[i1:] = end_val
    snap_idx[s] = pd.Series(v).shift(4).bfill().values        # 4-week lag
snap_lag = np.vstack([snap_idx[s] for s in state_list])      # states x weeks

# =================================================================== 3. SIMULATE WEEKLY VISITS
log("Simulating weekly households served for every county...")
hist_dates = cal["ds"].iloc[:n_hist]
x_week = hist_dates.map(pd.Timestamp.toordinal).values
level = np.zeros((len(need), n_hist))
panel_g = {f: g for f, g in panel.groupby("FIPS")}
for k, fips in enumerate(need["FIPS"]):
    g = panel_g[fips]
    x = pd.to_datetime(g["Year"].astype(int).astype(str) + "-07-01").map(pd.Timestamp.toordinal).values
    level[k] = np.interp(x_week, x, g["fi_persons"].values)

reach = rng.uniform(0.018, 0.026, len(need)) * (1 - 0.04 * (need["rucc"].values - 1))
doy = hist_dates.dt.dayofyear.values
common = ((1 + 0.06 * np.sin(2 * np.pi * (doy - 80) / 365.25))
          * np.where(hist_dates.dt.month.isin([11, 12]), 1.10, 1.0)
          * (1 + 0.12 * cal["school_out"].values[:n_hist])
          * (1 + 0.15 * cal["month_end_share"].values[:n_hist]))
state_pos = need["State"].map({s: i for i, s in enumerate(state_list)}).values
snap_effect = 1 + 1.2 * (1 - snap_lag[state_pos, :n_hist])
noise = rng.normal(1, 0.05, level.shape)
Y = np.maximum(0, np.round(level / HH_SIZE * reach[:, None] * common[None, :] * snap_effect * noise))

# Save recent county history for the app (long format)
tail = slice(n_hist - APP_HISTORY_WEEKS, n_hist)
hist_long = pd.DataFrame({"FIPS": np.repeat(need["FIPS"].values, APP_HISTORY_WEEKS),
                          "ds": np.tile(hist_dates.values[tail], len(need)),
                          "households_per_week": Y[:, tail].ravel()})
hist_long.to_csv("outputs/synthetic_weekly_visits.csv", index=False)

# State totals = training data for the state models
state_rows = []
for i, s in enumerate(state_list):
    d = cal.iloc[:n_hist][["ds", "school_out", "month_end_share"]].copy()
    d["State"], d["snap_index_lag4"], d["y"] = s, snap_lag[i, :n_hist], Y[state_pos == i].sum(axis=0)
    state_rows.append(d)
state_hist = pd.concat(state_rows, ignore_index=True)
state_hist.to_csv("outputs/state_weekly_visits.csv", index=False)

# =================================================================== 4. PROPHET
def fit_prophet(train):
    mdl = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False,
                  interval_width=0.90, seasonality_mode="multiplicative", changepoint_prior_scale=0.1)
    mdl.add_country_holidays(country_name="US")
    for r in REGRESSORS:
        mdl.add_regressor(r)
    mdl.fit(train[["ds", "y"] + REGRESSORS])
    return mdl

def future_frame(state_i, start_pos, n):
    f = cal.iloc[start_pos:start_pos + n][["ds", "school_out", "month_end_share"]].copy()
    f["snap_index_lag4"] = snap_lag[state_i, start_pos:start_pos + n]
    return f

def top_down(state_pred, member_idx, train_end):
    """Split a state forecast to its counties by recent share; widen ranges by county noise."""
    Ys = Y[member_idx, :train_end]
    tot = Ys.sum(axis=0)
    share = Ys[:, -8:].sum(axis=1) / max(tot[-8:].sum(), 1)
    ratio = Ys[:, -52:] / np.maximum(share[:, None] * tot[None, -52:], 1e-9)
    county_sd = np.nan_to_num(np.std(ratio - 1, axis=1), nan=0.2)
    yhat = state_pred["yhat"].values
    state_rel_sd = (state_pred["yhat_upper"].values - state_pred["yhat_lower"].values) / (2 * Z90) / np.maximum(yhat, 1)
    total_sd = np.sqrt(state_rel_sd[None, :] ** 2 + county_sd[:, None] ** 2)
    c_hat = share[:, None] * yhat[None, :]
    return c_hat, np.maximum(0, c_hat * (1 - Z90 * total_sd)), c_hat * (1 + Z90 * total_sd)

log(f"Fitting {len(state_list)} state models twice (backtest + final)...")
train_end = n_hist - HOLDOUT_WEEKS
acc_rows, fc_rows = [], []
for i, s in enumerate(state_list):
    members = np.where(state_pos == i)[0]
    sh = state_hist[state_hist["State"] == s]
    # backtest
    p = fit_prophet(sh.iloc[:train_end]).predict(future_frame(i, train_end, HOLDOUT_WEEKS))
    c_hat, c_lo, c_hi = top_down(p, members, train_end)
    actual = Y[members, train_end:n_hist]
    naive = Y[members, train_end - 4:train_end].mean(axis=1, keepdims=True)
    denom = np.maximum(actual, 1)
    for j, k in enumerate(members):
        acc_rows.append({"FIPS": need.at[k, "FIPS"], "method": "state model, top-down",
                         "mape_prophet": np.mean(np.abs(actual[j] - c_hat[j]) / denom[j]),
                         "mape_naive_4wk_avg": np.mean(np.abs(actual[j] - naive[j]) / denom[j]),
                         "range_coverage": np.mean((actual[j] >= c_lo[j]) & (actual[j] <= c_hi[j]))})
    # final
    p = fit_prophet(sh).predict(future_frame(i, n_hist, HORIZON_WEEKS))
    c_hat, c_lo, c_hi = top_down(p, members, n_hist)
    for j, k in enumerate(members):
        fc_rows.append(pd.DataFrame({"FIPS": need.at[k, "FIPS"], "ds": p["ds"].values,
                                     "yhat": c_hat[j], "yhat_lower": c_lo[j], "yhat_upper": c_hi[j],
                                     "method": "state model, top-down"}))
    if (i + 1) % 10 == 0:
        log(f"  {i + 1}/{len(state_list)} states done")

acc = pd.DataFrame(acc_rows)
fc = pd.concat(fc_rows, ignore_index=True)

# Focus counties: their own county-level Prophet
focus_idx = [need.index[(need["State"] == s) & (need["county"] == f"{c} County")][0]
             for s, cs in FOCUS_COUNTIES.items() for c in cs
             if ((need["State"] == s) & (need["county"] == f"{c} County")).any()]
log(f"Fitting detailed county models for {len(focus_idx)} focus counties...")
for k in focus_idx:
    i = state_pos[k]
    d = cal.iloc[:n_hist][["ds", "school_out", "month_end_share"]].copy()
    d["snap_index_lag4"], d["y"] = snap_lag[i, :n_hist], Y[k]
    p = fit_prophet(d.iloc[:train_end]).predict(future_frame(i, train_end, HOLDOUT_WEEKS))
    a = Y[k, train_end:n_hist]
    fips = need.at[k, "FIPS"]
    acc.loc[acc["FIPS"] == fips, ["method", "mape_prophet", "range_coverage"]] = [
        "county model", np.mean(np.abs(a - p["yhat"].values) / np.maximum(a, 1)),
        np.mean((a >= p["yhat_lower"].values) & (a <= p["yhat_upper"].values))]
    p = fit_prophet(d).predict(future_frame(i, n_hist, HORIZON_WEEKS))
    fc = fc[fc["FIPS"] != fips]
    fc = pd.concat([fc, pd.DataFrame({"FIPS": fips, "ds": p["ds"].values, "yhat": p["yhat"].values,
                                      "yhat_lower": np.maximum(0, p["yhat_lower"].values),
                                      "yhat_upper": p["yhat_upper"].values, "method": "county model"})])

acc = acc.merge(need[["FIPS", "State", "county_label"]], on="FIPS")
acc[["mape_prophet", "mape_naive_4wk_avg", "range_coverage"]] = acc[["mape_prophet", "mape_naive_4wk_avg", "range_coverage"]].round(3)
acc.to_csv("outputs/backtest_accuracy.csv", index=False)

# =================================================================== 5. CAPACITY + ALERTS (all per week)
recent = pd.Series(Y[:, -8:].mean(axis=1), index=need["FIPS"])
cap = pd.DataFrame({"FIPS": need["FIPS"],
                    "capacity_hh_per_week": np.round(recent.values * rng.uniform(1.00, 1.25, len(need)))})
cap["volunteer_shifts_per_week"] = np.ceil(cap["capacity_hh_per_week"] / HOUSEHOLDS_PER_SHIFT).astype(int)
cap["food_capacity_kg_per_week"] = (cap["capacity_hh_per_week"] * KG_PER_HOUSEHOLD_VISIT).round().astype(int)
cap["food_capacity_lbs_per_week"] = (cap["food_capacity_kg_per_week"] * LBS_PER_KG).round().astype(int)
cap["recent_hh_per_week"] = recent.values.round(1)

fc = fc.merge(cap, on="FIPS").merge(need[["FIPS", "State", "county", "county_label", "cost_per_meal"]], on="FIPS")
fc[["yhat", "yhat_lower", "yhat_upper"]] = fc[["yhat", "yhat_lower", "yhat_upper"]].round()
c = fc["capacity_hh_per_week"]
fc["status"] = np.where(fc["yhat_upper"] > c, np.where(fc["yhat"] > c, "RED", "YELLOW"), "GREEN")
fc["gap_hh"] = np.maximum(0, fc["yhat_upper"] - c).astype(int)
fc["extra_shifts_needed"] = np.ceil(fc["gap_hh"] / HOUSEHOLDS_PER_SHIFT).astype(int)
fc["extra_food_kg"] = (fc["gap_hh"] * KG_PER_HOUSEHOLD_VISIT).round().astype(int)
fc["extra_food_lbs"] = (fc["gap_hh"] * KG_PER_HOUSEHOLD_VISIT * LBS_PER_KG).round().astype(int)
fc["extra_meals"] = (fc["extra_food_kg"] / KG_PER_MEAL).round().astype(int)
fc["funding_gap_usd"] = (fc["extra_meals"] * fc["cost_per_meal"]).round().astype(int)
fc = fc.sort_values(["State", "county_label", "ds"])
fc.to_csv("outputs/forecast_with_alerts.csv", index=False)

# =================================================================== 6. ANNUAL NEED OUTLOOK (real data only)
# Straight-line trend per county on the 6 real yearly values, with an 80% prediction range.
# (Prophet on 6 points is effectively a straight line; fitting 3,100+ Prophet models would take ~30 min.)
log("Annual need outlook (linear trend on real 2019-2024 data)...")
T80 = {2: 1.886, 3: 1.638, 4: 1.533}
out = []
for fips, g in panel_g.items():
    if fips not in set(need["FIPS"]) or len(g) < 4:
        continue
    x, yv = g["Year"].values.astype(float), g["fi_persons"].values.astype(float)
    b, a = np.polyfit(x, yv, 1)
    resid = yv - (a + b * x)
    n = len(x); s = np.sqrt(np.sum(resid ** 2) / (n - 2)); sxx = np.sum((x - x.mean()) ** 2)
    for yr in (2025, 2026):
        pred = a + b * yr
        se = s * np.sqrt(1 + 1 / n + (yr - x.mean()) ** 2 / sxx)
        out.append({"FIPS": fips, "year": yr, "fi_persons_forecast": max(0, round(pred)),
                    "low": max(0, round(pred - T80.get(n - 2, 1.533) * se)),
                    "high": round(pred + T80.get(n - 2, 1.533) * se),
                    "fi_persons_2024_actual": int(g.loc[g["Year"] == 2024, "fi_persons"].iloc[0])})
pd.DataFrame(out).to_csv("outputs/annual_need_outlook_2025_2026.csv", index=False)

# =================================================================== 7. SUMMARY
log("Done.")
print("\nBacktest, last 12 weeks (lower MAPE is better):")
summ = acc.groupby("method").agg(counties=("FIPS", "size"), mape_prophet=("mape_prophet", "median"),
                                 mape_naive=("mape_naive_4wk_avg", "median"),
                                 range_coverage=("range_coverage", "mean"))
print(summ.round(3).to_string())
flag = fc[fc["status"] != "GREEN"]
print(f"\nNext 8 weeks: {flag['FIPS'].nunique():,} of {fc['FIPS'].nunique():,} counties have at least one at-risk week.")
print(f"Total extra food needed: {flag['extra_food_lbs'].sum():,.0f} lbs / {flag['extra_food_kg'].sum():,.0f} kg "
      f"({flag['extra_meals'].sum():,.0f} meals, about ${flag['funding_gap_usd'].sum():,.0f}).")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    k = focus_idx[1] if len(focus_idx) > 1 else 0
    fips, label = need.at[k, "FIPS"], need.at[k, "county_label"]
    h, f = hist_long[hist_long["FIPS"] == fips], fc[fc["FIPS"] == fips]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(h["ds"], h["households_per_week"], color="#555", lw=1, label="Households per week (simulated)")
    ax.plot(f["ds"], f["yhat"], color="#1f77b4", lw=2, label="Forecast")
    ax.fill_between(f["ds"], f["yhat_lower"], f["yhat_upper"], color="#1f77b4", alpha=0.25, label="Forecast range")
    ax.axhline(f["capacity_hh_per_week"].iloc[0], color="#d62728", ls="--", label="Capacity per week")
    ax.set_title(f"{label}: households served per week"); ax.legend(loc="upper left")
    fig.tight_layout(); fig.savefig("outputs/example_forecast.png", dpi=150)
    print("Chart saved: outputs/example_forecast.png")
except Exception as e:
    print("Chart skipped:", e)
