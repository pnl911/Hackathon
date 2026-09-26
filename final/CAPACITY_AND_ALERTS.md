# Capacity, alerts, and transfers (`strategist.py`)

The forecast says **how many households will come**. Capacity says **how many the food bank can serve**. The sliders change capacity only, which is why the forecast line never moves when you drag them.

## Units (all per week)

| Quantity | Unit |
|---|---|
| Demand and capacity | Households per week |
| Food | lbs or kg (toggle in the sidebar; lbs by default) |
| Food per visit | Default 30 lbs = 13.6 kg |
| Meal | 1.2 lbs = 0.544 kg (Feeding America standard) |
| Money | USD, using each county's real cost per meal |

## Capacity: volunteers and food checked separately

```
Volunteer capacity = shifts per week × households one shift can serve
Food capacity      = food available per week ÷ food per household visit
Capacity           = the smaller of the two   → the bottleneck
```

## Alerts and gaps (function `county_week_table`)

For every county and week, using the **high end** of the forecast:

```
Status        RED    if even the expected value exceeds capacity
              YELLOW if only the high end exceeds capacity
              GREEN  otherwise
Gap (households)  = high end − capacity                        (0 if negative)
Extra shifts      = (high end − volunteer capacity) ÷ households per shift, rounded up
Extra food        = high end × food per visit − food available (0 if negative)
Extra meals       = extra food ÷ food per meal
Funding gap       = extra meals × local cost per meal
Short on          = volunteers | food | volunteers + food | nothing
```

**Why separately?** An early version computed extra food as `gap × food per visit` even when volunteers were the only bottleneck, asking food banks to buy food they already had. For one Dallas test week, that overstated food by about 55,000 lbs and funding by about $160,000. Checking each resource on its own fixes this.

Counties you haven't set in the sidebar use their default capacity, where volunteers and food are balanced.

## Worked example

Forecast high end: **5,000 households**.

| Setting | Can serve |
|---|---|
| Volunteers: 180 shifts × 25 | 4,500 |
| Food: 150,000 lbs ÷ 30 lbs | 5,000 |
| **Capacity (smaller)** | **4,500, limited by volunteers** |

Result: **20 more shifts** ((5,000 − 4,500) ÷ 25), and **no extra food**, because 150,000 lbs already covers 5,000 visits.

What the sliders do here:
- More volunteers (200 shifts = 5,000): gap closes.
- More food only: nothing changes; food wasn't the bottleneck.
- Less food per visit: food covers more, but volunteers still cap capacity at 4,500.

## Transfers before new resources (function `reallocation_plan`)

For each week, counties in the same state with spare capacity (capacity above their forecast high end) offer **half** of that spare capacity (so they keep a safety margin) to counties with gaps, largest gaps first. Each move is reported in households and food.

**Assumption:** counties in the same state can share food and volunteers. In practice a food bank shares within its own service area.

## "Who might we be missing?" (reach)

```
Weekly reach = recent households per week ÷ (food-insecure people ÷ 2.6)
Flag "Possibly underserved" if reach < 80% of the state's median reach
```

Low reach can mean transportation, awareness, language, or stigma barriers: families with need who are not reaching the food bank. These counties are candidates for a mobile pantry or community partner outreach.

**Note:** in the prototype, reach differences partly reflect the simulation's assumption that rural counties have lower reach. With real visit data, this table would reflect real gaps.
