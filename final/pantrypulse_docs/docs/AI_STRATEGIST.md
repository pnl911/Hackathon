# AI strategist (`strategist.py` + Claude)

Claude acts as an **operations strategist**: it turns the model's numbers into a ranked, dated plan and answers staff questions. It never calculates figures itself.

```
Prophet forecast → Python computes every number → Claude plans and writes → a person approves
```

## 1. Connecting to Claude

- **Endpoint:** `POST https://api.anthropic.com/v1/messages`
- **Model:** set in `MODEL` at the top of `strategist.py` (`claude-sonnet-5`)
- **Headers:** `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`
- **Function:** `call_claude(system, user, max_tokens)` returns Claude's text or raises an error with the status code

### Where the key comes from (never in code)
`api_key()` checks, in order:
1. Streamlit secrets: `.streamlit/secrets.toml` → `ANTHROPIC_API_KEY = "sk-ant-..."`
2. Environment variable `ANTHROPIC_API_KEY`
3. Reading `secrets.toml` directly from: the script's folder, the folder you run from, one folder up from either, or your home folder

The direct read tolerates the ways Windows tends to break the file: UTF-16 encoding (from PowerShell `echo >`), a hidden byte-order mark (Notepad), curly quotes, or missing quotes. A placeholder like `sk-ant-your-key` is rejected (a real key has 20+ characters after `sk-ant-`).

`key_status()` reports where the key was found (shown in the green "connected" box). `key_diagnostics()` powers the "Why isn't Claude connected?" expander: it lists every location checked, whether the file exists, other files in `.streamlit` (catches `secrets.toml.txt`), and setting names found, **without ever showing the key**.

## 2. What Claude sees: the "facts"

`build_facts(...)` creates a compact JSON summary for one state. It is shown in the app under **"What the AI sees"**.

| Key | Contents |
|---|---|
| `region`, `today`, `planning_window` | State name, date, the 8-week window |
| `units` | Households per week; food in lbs or kg; USD |
| `assumptions` | Households per shift, food per visit, food per meal, "alerts use the high end" |
| `totals` | Counties at risk, total gap, shifts, food, meals, funding, households covered by transfers |
| `weekly_totals` | The same totals for each of the 8 weeks |
| `top_alerts` | The 25 largest at-risk county-weeks: forecast, capacity, what volunteers and food each cover, `short_on`, extra shifts/food/meals/dollars, and `start_outreach_by` (14 days before the week, or "ASAP") |
| `suggested_transfers` | Up to 20 same-week moves of spare capacity |
| `counties` | Real need data for the most at-risk and possibly underserved counties (up to ~25), plus reach and the 2026 trend projection |
| `economic_conditions` | State unemployment and grocery prices, plus national GDP, CPI, inflation and consumer spending (from FRED), if available |
| `data_notes` | What's real, what's simulated, and the transfer assumption |

Large states are trimmed to the most urgent items so the prompt stays small (about 20,000 characters for Texas).

## 3. The action plan prompt (`SYSTEM_PLAN`)

Claude is told to:
- use **only** numbers in the facts, never invent or estimate figures
- keep the food unit given in the facts
- use suggested transfers **before** asking for new volunteers, food, or money
- order priorities by urgency ("ASAP" first, then earliest date), then gap size
- ask only for what each county is `short_on`
- consider possibly underserved counties even without an alert
- use economic conditions to judge risk (rising unemployment or food inflation → plan conservatively)
- assign owners by role and phrase everything as recommendations for human approval
- return **only JSON**:

```json
{"summary": "2-3 sentences",
 "priorities": [{"rank": 1, "county": "", "week_of": "", "action": "", "why": "", "owner": "", "deadline": ""}],
 "transfers": [{"week_of": "", "from_county": "", "to_county": "", "households_per_week": 0, "food": 0, "note": ""}],
 "outreach": [{"audience": "Volunteers|Donors|Community partners", "county": "", "channel": "SMS|Email|Social", "message": ""}],
 "watch_list": [{"county": "", "reason": ""}],
 "risks": [""]}
```

`ai_action_plan(facts)` parses the JSON (stripping code fences if present) and fills any missing keys. **If the call or parsing fails, it falls back to `rule_based_plan(facts)`**, and the app shows which one generated the plan.

## 4. Rule-based fallback plan (`rule_based_plan`)

Built from the same facts, no AI needed:
- **Priorities:** each at-risk county's worst week, ordered by urgency then gap, with an action that names only what is short
- **Transfers:** the top suggested moves
- **Outreach:** a volunteer SMS and a donor email for the top priority
- **Watch list:** possibly underserved counties
- **Risks:** economic warnings (unemployment up 0.3+ points in a year, or food inflation of 3%+), forecast range caveat, transfer assumption

## 5. Ask the strategist (`answer_question`)

Always returns an answer and its source:
- **With Claude:** the facts, the current plan (if generated), and the last 3 Q&A turns are sent with `SYSTEM_QA` (answer only from the facts; say so when data is missing).
- **Without Claude:** `rule_based_answer` recognizes common questions: the economy, next week, food, volunteers, funding, underserved counties or mobile pantries, transfers, urgency and deadlines; anything else gets the biggest gaps plus the plan summary.

## 6. Approval and PDF export

Priorities show with an **Approve** checkbox. `plan_to_pdf(...)` builds a landscape PDF (ReportLab): title and generation source, summary, key numbers, priorities with an **Approved** column, transfers, outreach, watch list, risks, data note, and page numbers. `plan_to_markdown(...)` remains available.

## 7. Outreach drafts on the county page

The county view's "Draft outreach messages" uses Claude when connected (short prompt with the week's numbers), otherwise templates. If only food is short, the volunteer message becomes a thank-you instead of asking for shifts nobody needs.

## Cost and safety
- Each plan costs a few cents; $5 of credit covers development and demos.
- Keys live only in `.streamlit/secrets.toml`, listed in `.gitignore`. Never show that file on screen.
- If a key is ever pasted into a chat, email, or screenshot, delete it and create a new one.
