# Dashboard (`app.py`)

Start with `streamlit run app.py` (after running the forecast). The app opens at `http://localhost:8501`.

## Sidebar

| Control | What it does |
|---|---|
| **View** | County forecast, AI action plan, or Economy (FRED) |
| **Food unit** | lbs (default) or kg; every food number, input, and AI message follows it |
| **State**, **County** | Pick any of 3,142 US counties |
| **Volunteer shifts per week** | Sets volunteer capacity for the selected county |
| **Households one shift can serve** | Throughput per shift (default 25) |
| **Food per household visit** | Default 30 lbs / 13.6 kg |
| **Food available per week** | Food on hand for the week |
| **Capacity** (read-only) | The smaller of volunteer and food capacity, with the bottleneck and both capacities explained below it |

Sidebar capacity applies to the selected county; other counties keep their default capacity.

## View 1: County forecast

1. **Headline box**: how many of the 8 weeks may exceed capacity, the worst week, peak demand, capacity and its bottleneck, what volunteers and food each cover, and exactly what's needed (or "no extra volunteers" / "no extra food").
2. **Four real metrics** (Map the Meal Gap 2024): food-insecure people, food insecurity rate, share above the SNAP income limit, cost per meal.
3. **Economy line**: state unemployment and grocery prices from FRED, and whether the forecast uses them.
4. **Chart**: black = last 52 weeks (simulated); blue = forecast and its range; red dashed = capacity; dots colored by week status (hover for details).
5. **Weekly plan table**: per week: expected, high end, status, short on, households over capacity, extra shifts, extra food, extra meals, funding gap. The caption shows the formulas with your numbers.
6. **Recommended actions** and **Draft outreach messages** (Claude or template), then **Approve plan**.
7. **Who might we be missing?**: counties in the state ranked by weekly reach, lowest first, with "Possibly underserved" flags (top 15, full list in an expander).
8. **Model accuracy**: this county's backtest error vs the naive baseline, and the state's median.

**Demo move:** lower volunteers (only shifts rise), restore them, lower food (only food and dollars rise). The forecast line never moves: demand comes from the community, capacity from the food bank.

## View 2: AI action plan (whole state)

1. **Metrics**: counties at risk, extra food needed, funding gap, extra volunteer shifts.
2. **Economy line** and how much of the gap transfers can cover.
3. **Connection box**: green "Claude is connected (key found in ...)" or a blue note plus the **"Why isn't Claude connected?"** diagnostics table.
4. **Generate action plan**: summary, **priorities with Approve checkboxes**, transfers, draft outreach, watch list, risks. The caption says whether Claude or the rules generated it.
5. **Approve selected actions** and **Download plan (PDF)** (includes which priorities were approved).
6. **Ask the strategist**: works with or without Claude; each answer says who answered.
7. **What the AI sees**: the exact facts sent to Claude.

## View 3: Economy (FRED)

1. **Cards**: real GDP growth, CPI inflation, annual inflation, consumer spending growth (with change vs the previous period), plus the selected state's unemployment and grocery price inflation. Colors follow meaning: rising inflation or unemployment is shown as bad, rising GDP or spending as good.
2. **Per indicator**: chart since 2015, latest value, raw value with FRED's units, frequency, why it matters for food banks, and a link to the series on FRED.
3. **How PantryPulse uses this**: which indicators feed the forecast and which inform the AI.

## Caching
Forecast files load once per session; FRED data refreshes hourly in the app (and is cached on disk for offline use). After rerunning the forecast, restart the app to load new files.
