# FRED economic data

FRED (Federal Reserve Economic Data, St. Louis Fed) provides free economic time series through an API. Get a key at fredaccount.stlouisfed.org and add `FRED_API_KEY = "..."` to `.streamlit/secrets.toml`.

## Series used

| Series | What it is | Frequency | Used in |
|---|---|---|---|
| `{ST}UR` (e.g. `TXUR`) | State unemployment rate | Monthly | **Forecast** (lagged 6 weeks) + dashboard + AI |
| `CUSR0000SAF11` | CPI: food at home (grocery prices), turned into % change vs a year earlier | Monthly | **Forecast** (lagged 6 weeks) + dashboard + AI |
| `GDPC1` | Real GDP, shown as % growth vs a year earlier | Quarterly | Dashboard + AI context |
| `CPIAUCSL` | CPI, all items (inflation, % vs a year earlier) | Monthly | Dashboard + AI context |
| `FPCPITOTLZGUSA` | Inflation, consumer prices (annual %, World Bank) | Annual | Dashboard + AI context |
| `PCE` | Personal consumption expenditures, % growth vs a year earlier | Monthly | Dashboard + AI context |

## Why some are in the forecast and some are context

The forecast needs signals that **vary by place and over time**. State unemployment and grocery prices do (grocery prices vary over time). GDP, CPI, and PCE are national, so every county would get the same value, and GDP updates only quarterly; as model inputs they would add little and risk misleading correlations. They give the planning team and Claude the bigger picture instead.

## Two code paths

1. **`demand_forecast_us.py`** (forecast inputs). Loads `{ST}UR` for every state and `CUSR0000SAF11`, aligns them to weeks with a 6-week lag, adds them as Prophet regressors, and uses them in the simulated history. Writes `outputs/macro_state_latest.csv`. States without data use the average of the others. Without a key or cache: prints "Economic factors OFF" and runs without them.
2. **`fred_data.py`** (dashboard). `get_series()` downloads a series or falls back to the cache; `get_info()` gets FRED's official title, units, and frequency; `summary()` computes the headline number and change; `facts_for_ai()` compacts them for Claude; `state_macro()` fetches a state's unemployment and grocery prices live if the forecast file is missing.

Add a new indicator by adding an entry to `INDICATORS` in `fred_data.py` (series ID, name, transform `yoy_pct` or `level`, periods per year, and why it matters).

## Caching (offline demos)
Every series is saved in `outputs/fred_cache/`. The forecast script refreshes after 7 days, the dashboard after 12 hours. **Open the app once while online before a demo**; it then works without internet.

## The economic effect in the simulation
The simulated history assumes +3% visits per point of unemployment above the state's 2019 average and +1% per point of food inflation above 2%. These are assumptions based on the known link between unemployment and food insecurity. With real visit data, Prophet would estimate the actual effect for each community.
