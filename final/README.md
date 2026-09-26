# PantryPulse

**Know where hunger is heading before the line forms.**

PantryPulse is an early warning and planning tool for food banks. It forecasts how many households each county will serve every week for the next 8 weeks, compares that forecast to the food bank's volunteers and food on hand, and turns any gap into a concrete, approvable action plan: volunteer shifts, pounds of food, meals, dollars, and where to send them.

Built for **ImpactHacks 2026** in response to the question: *How can AI, technology, and innovation help the not-for-profit sector reach deeper into the communities it serves?*

---

## Why it exists

Food banks usually plan from last week's numbers and discover they are overwhelmed only when the line is already out the door. But demand follows patterns that can be seen in advance: local need, seasons and holidays, school breaks, the end of the month when SNAP benefits run out, SNAP enrollment changes, unemployment, and grocery prices. PantryPulse turns those signals into a forecast and a plan.

## What it does

| Capability | Description |
|---|---|
| **8-week demand forecast** | Households served per week for every US county (3,142), with an uncertainty range |
| **Capacity check** | Volunteers and food checked separately; the tool names the real bottleneck |
| **Gap to action** | Converts gaps into volunteer shifts, pounds (or kg) of food, meals, and dollars at local meal cost |
| **Transfers first** | Finds spare capacity in other counties of the same state before asking for new resources |
| **Who are we missing?** | Flags counties where need is high but visits are low |
| **Economy view** | Live FRED data: state unemployment, grocery prices, GDP, CPI, inflation, consumer spending |
| **AI action plan** | Claude turns the numbers into ranked priorities with owners, deadlines, and drafted outreach |
| **Ask the strategist** | Plain-English questions answered from the model's numbers |
| **Human approval + PDF** | People approve every action; the plan exports as a PDF |

**Design rule:** *Python does the math. Claude does the strategy. People make the decisions.*

---

## Quick start

```bash
# 1. Create and activate a virtual environment (Windows PowerShell shown)
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your API keys (see docs/SETUP_AND_TROUBLESHOOTING.md)
#    copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and fill it in

# 4. Build the forecast (1-3 minutes)
python demand_forecast_us.py

# 5. Launch the dashboard
streamlit run app.py
```

Both API keys are optional. Without them, the app still runs: plans and answers come from built-in rules, and economic factors are turned off.

### Required input files (same folder as the scripts)

| File | Source |
|---|---|
| `MMG2025_2019-2023_Data_To_Share_v2.xlsx` | Feeding America, Map the Meal Gap 2025 (2019-2023 data) |
| `MMG2026_2024_Data_To_Share.xlsx` | Feeding America, Map the Meal Gap 2026 (2024 data) |
| `snap-households-9.xlsx` | USDA FNS, SNAP households by state (June 2025 vs June 2026) |

The script finds these by name prefix (`MMG2025*`, `MMG2026*`, `snap-households*`), so download suffixes like ` (1)` are fine.

---

## Project structure

```
final/
├── demand_forecast_us.py      # Backend 1: data prep, simulation, Prophet forecasts, alerts
├── strategist.py              # Backend 2: capacity logic, transfers, Claude API, fallbacks, PDF
├── fred_data.py               # Backend 3: FRED API connector with offline cache
├── app.py                     # Streamlit dashboard (3 views)
├── requirements.txt
├── .gitignore
├── .streamlit/
│   ├── secrets.toml.example   # template (safe to share)
│   └── secrets.toml           # your real keys (never share or commit)
├── outputs/                   # everything the forecast script writes
│   └── fred_cache/            # downloaded FRED series, for offline use
├── docs/                      # detailed documentation (below)
└── MMG*.xlsx, snap-households*.xlsx   # input data
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit together, data flow, design principles |
| [docs/DATA.md](docs/DATA.md) | Every input and output file, every column, and whether it is real, derived, or simulated |
| [docs/FORECAST_MODEL.md](docs/FORECAST_MODEL.md) | The forecasting pipeline step by step, with the reasoning behind each step |
| [docs/CAPACITY_AND_ALERTS.md](docs/CAPACITY_AND_ALERTS.md) | Capacity formulas, bottlenecks, alerts, transfers, units (lbs/kg), worked examples |
| [docs/AI_STRATEGIST.md](docs/AI_STRATEGIST.md) | How Claude is connected, what it sees, prompts, fallbacks, Q&A, PDF export |
| [docs/FRED_ECONOMIC_DATA.md](docs/FRED_ECONOMIC_DATA.md) | FRED series used, how they enter the forecast vs the AI context, caching |
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | A tour of every view, control, and number in the app |
| [docs/SETUP_AND_TROUBLESHOOTING.md](docs/SETUP_AND_TROUBLESHOOTING.md) | Installation, API keys, and fixes for every issue we hit |
| [docs/LIMITATIONS_AND_ROADMAP.md](docs/LIMITATIONS_AND_ROADMAP.md) | What is real vs simulated, known limitations, next steps |

---

## Honesty note

All **need data is real** (Feeding America Map the Meal Gap for every US county, 2019-2024; USDA SNAP by state; FRED economic data; local cost per meal). **Weekly visit history and current capacity are simulated**, because food bank visit records are private. Accuracy results therefore show that the method works, not yet real-world accuracy. Food banks already export visit data from intake systems such as Link2Feed and Feeding America's Service Insights; plugging that in replaces the simulated history without other changes.

## Data sources and credits

- Feeding America, *Map the Meal Gap* (Ribar et al., 2025 and 2026 releases)
- USDA Food and Nutrition Service, SNAP data tables
- Federal Reserve Bank of St. Louis, FRED
- Forecasting: [Prophet](https://facebook.github.io/prophet/); AI: Claude via the Anthropic API; dashboard: Streamlit

## Team

[Team name] | [Names] | ImpactHacks 2026
