"""
PantryPulse AI Strategist (v4)
------------------------------
Forecast model (Prophet) -> Python computes every number (per WEEK; food in lbs or kg)
                         -> Claude plans: priorities, owners, deadlines, transfers, outreach
                         -> a person approves -> plan exported as PDF

Design rule: Python does the math, Claude does the strategy and writing.
Everything still works without an API key (rule-based plan and rule-based answers).

API key lookup order (key is never written in code):
  1. Streamlit secrets      .streamlit/secrets.toml  ->  ANTHROPIC_API_KEY = "sk-ant-..."
  2. Environment variable   ANTHROPIC_API_KEY
  3. Reads .streamlit/secrets.toml directly: next to this file, the folder you run from, one
     folder up from either, or your home folder. Any encoding; straight, curly or no quotes.
"""
import io
import json
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

MODEL = "claude-sonnet-5"
API_URL = "https://api.anthropic.com/v1/messages"
MAX_ALERTS_TO_AI = 25
MAX_TRANSFERS_TO_AI = 20
KEY_NAME = "ANTHROPIC_API_KEY"


# ================================================================ 0. API KEY
KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")


def _candidate_files():
    """Every place a secrets.toml might reasonably be (checked in order)."""
    here, cwd = Path(__file__).resolve().parent, Path.cwd()
    folders = [here, cwd, here.parent, cwd.parent, Path.home()]
    seen, out = set(), []
    for d in folders:
        f = (d / ".streamlit" / "secrets.toml").resolve()
        if f not in seen:
            seen.add(f); out.append(f)
    return out


def _read_text(f):
    """Read a text file whatever encoding Windows saved it in (UTF-8, UTF-8 with BOM, UTF-16, ANSI)."""
    raw = f.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if "\x00" not in text:
                return text
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _key_in_text(text):
    """Accepts ANTHROPIC_API_KEY = "sk-ant-..." with straight or curly quotes, or no quotes.
    Falls back to any sk-ant-... key found in the file."""
    for line in text.splitlines():
        if KEY_NAME in line and "=" in line:
            m = KEY_PATTERN.search(line.split("=", 1)[1])
            if m:
                return m.group(0)
    m = KEY_PATTERN.search(text)
    return m.group(0) if m else None


def _key_from_file():
    for f in _candidate_files():
        try:
            if f.exists():
                k = _key_in_text(_read_text(f))
                if k:
                    return k, str(f)
        except Exception:
            continue
    return None, None


def api_key():
    try:
        import streamlit as st
        if KEY_NAME in st.secrets:
            k = KEY_PATTERN.search(str(st.secrets[KEY_NAME]))
            if k:
                return k.group(0)
    except Exception:
        pass
    env = os.environ.get(KEY_NAME, "")
    if KEY_PATTERN.search(env):
        return KEY_PATTERN.search(env).group(0)
    return _key_from_file()[0]


def key_status():
    """Where the key was found, for display (never shows the key)."""
    try:
        import streamlit as st
        if KEY_NAME in st.secrets and KEY_PATTERN.search(str(st.secrets[KEY_NAME])):
            return "Streamlit secrets"
    except Exception:
        pass
    if KEY_PATTERN.search(os.environ.get(KEY_NAME, "")):
        return "environment variable"
    path = _key_from_file()[1]
    return path


def key_diagnostics():
    """Safe troubleshooting info: which files exist and what they contain, WITHOUT revealing the key."""
    rows = []
    for f in _candidate_files():
        row = {"looked in": str(f), "file exists": f.exists(), "other files in .streamlit": "",
               "setting names found": "", "key found": False}
        if f.parent.exists():
            row["other files in .streamlit"] = ", ".join(x.name for x in f.parent.iterdir() if x.name != "secrets.toml")
        if f.exists():
            try:
                text = _read_text(f)
                row["setting names found"] = ", ".join(l.split("=")[0].strip() for l in text.splitlines() if "=" in l) or "(no NAME = value lines)"
                row["key found"] = _key_in_text(text) is not None
                if not row["key found"] and "sk-ant" not in text:
                    row["setting names found"] += "  |  no text starting with sk-ant- in the file"
                elif not row["key found"]:
                    row["setting names found"] += "  |  sk-ant- text is too short: is it the full real key?"
            except Exception as e:
                row["setting names found"] = f"could not read: {e}"
        rows.append(row)
    return {"running from": str(Path.cwd()), "strategist.py location": str(Path(__file__).resolve().parent),
            "env variable set": bool(os.environ.get(KEY_NAME)), "files": rows}


# ================================================================ 1. FACTS FROM THE MODEL
def county_week_table(fc, settings, capacity_override=None):
    """fc: forecast rows for one region.
    settings: dict with hh_per_shift, food_per_visit, food_per_meal, unit ("lbs" or "kg").
    capacity_override: {FIPS: {"staff_hh": households volunteers can serve per week,
                               "food_available": food on hand per week (in settings unit)}}
                       (a plain number is treated as both volunteers and food covering that many households)

    Volunteers and food are checked SEPARATELY:
      volunteer capacity = shifts x households per shift
      food capacity      = food available / food per visit
      capacity           = the smaller of the two (the bottleneck)
      extra shifts       = only for households volunteers can't cover
      extra food         = only the food actually missing (forecast x food per visit - food on hand)
    All values are PER WEEK."""
    t = fc[["FIPS", "county_label", "ds", "yhat", "yhat_lower", "yhat_upper",
            "capacity_hh_per_week", "cost_per_meal"]].copy()
    fpv, hps = settings["food_per_visit"], settings["hh_per_shift"]
    # default for counties without user input: volunteers and food both cover the current capacity
    t["staff_hh"] = t["capacity_hh_per_week"].astype(float)
    t["food_available"] = t["capacity_hh_per_week"] * fpv
    for fips, ov in (capacity_override or {}).items():
        m = t["FIPS"] == fips
        if isinstance(ov, dict):
            t.loc[m, "staff_hh"] = ov["staff_hh"]
            t.loc[m, "food_available"] = ov["food_available"]
        else:
            t.loc[m, "staff_hh"] = ov
            t.loc[m, "food_available"] = ov * fpv
    t["food_hh"] = t["food_available"] / fpv
    t["capacity_hh_per_week"] = np.floor(np.minimum(t["staff_hh"], t["food_hh"])).astype(int)
    cap, hi = t["capacity_hh_per_week"], t["yhat_upper"]
    t["status"] = np.where(hi > cap, np.where(t["yhat"] > cap, "RED", "YELLOW"), "GREEN")
    t["gap_hh"] = np.maximum(0, hi - cap).astype(int)                       # households that can't be served
    t["surplus_hh"] = np.maximum(0, cap - hi).astype(int)
    t["volunteer_gap_hh"] = np.maximum(0, hi - t["staff_hh"])
    t["extra_shifts"] = np.ceil(t["volunteer_gap_hh"] / hps).astype(int)
    t["extra_food"] = np.maximum(0, hi * fpv - t["food_available"]).round().astype(int)
    t["extra_meals"] = (t["extra_food"] / settings["food_per_meal"]).round().astype(int)
    t["funding_gap_usd"] = (t["extra_meals"] * t["cost_per_meal"]).round().astype(int)
    short_staff, short_food = t["extra_shifts"] > 0, t["extra_food"] > 0
    t["short_on"] = np.select([short_staff & short_food, short_staff, short_food],
                              ["volunteers + food", "volunteers", "food"], "nothing")
    return t


def reallocation_plan(t, food_per_visit, unit="lbs", keep_buffer=0.5):
    """Same-week transfers of spare capacity from counties with room to counties with gaps.
    Only half of a county's spare capacity is offered so it keeps a safety margin."""
    moves = []
    for week, w in t.groupby("ds"):
        donors = w[w["surplus_hh"] > 0].copy()
        donors["available"] = (donors["surplus_hh"] * keep_buffer).astype(int)
        donors = donors.sort_values("available", ascending=False)
        for _, r in w[w["gap_hh"] > 0].sort_values("gap_hh", ascending=False).iterrows():
            remaining = r["gap_hh"]
            for i, d in donors.iterrows():
                if remaining <= 0:
                    break
                give = int(min(remaining, donors.at[i, "available"]))
                if give <= 0:
                    continue
                donors.at[i, "available"] -= give
                remaining -= give
                moves.append({"week_of": pd.Timestamp(week).strftime("%Y-%m-%d"),
                              "from_county": d["county_label"], "to_county": r["county_label"],
                              "households_per_week": give, f"food_{unit}": int(round(give * food_per_visit))})
    return pd.DataFrame(moves, columns=["week_of", "from_county", "to_county", "households_per_week", f"food_{unit}"])


def build_facts(t, moves, need, region_name, settings, reach=None, outlook=None, today=None, macro=None):
    """Compact JSON-ready summary. This is exactly what Claude sees."""
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    u = settings["unit"]
    risky = t[t["status"] != "GREEN"].copy()
    risky["outreach_by"] = risky["ds"] - pd.Timedelta(days=14)
    alerts = [{
        "county": r["county_label"], "week_of": r["ds"].strftime("%Y-%m-%d"), "status": r["status"],
        "expected_households_per_week": int(r["yhat"]), "high_end_households_per_week": int(r["yhat_upper"]),
        "capacity_households_per_week": int(r["capacity_hh_per_week"]), "gap_households": int(r["gap_hh"]),
        "volunteers_can_serve": int(r["staff_hh"]), "food_covers_households": int(r["food_hh"]),
        "short_on": r["short_on"],
        "extra_volunteer_shifts": int(r["extra_shifts"]), f"extra_food_{u}": int(r["extra_food"]),
        "extra_meals": int(r["extra_meals"]), "funding_gap_usd": int(r["funding_gap_usd"]),
        "start_outreach_by": "ASAP" if r["outreach_by"] <= today else r["outreach_by"].strftime("%Y-%m-%d"),
    } for _, r in risky.sort_values("gap_hh", ascending=False).head(MAX_ALERTS_TO_AI).iterrows()]
    alerts.sort(key=lambda a: (a["start_outreach_by"] != "ASAP", a["start_outreach_by"], -a["gap_households"]))

    weekly = t.groupby("ds").agg(counties_at_risk=("status", lambda s: int((s != "GREEN").sum())),
                                 gap_households=("gap_hh", "sum"), extra_shifts=("extra_shifts", "sum"),
                                 extra_food=("extra_food", "sum"), extra_meals=("extra_meals", "sum"),
                                 funding_gap_usd=("funding_gap_usd", "sum")).reset_index()
    weekly_totals = [{"week_of": r["ds"].strftime("%Y-%m-%d"), "counties_at_risk": int(r["counties_at_risk"]),
                      "gap_households": int(r["gap_households"]), "extra_volunteer_shifts": int(r["extra_shifts"]),
                      f"extra_food_{u}": int(r["extra_food"]), "extra_meals": int(r["extra_meals"]),
                      "funding_gap_usd": int(r["funding_gap_usd"])} for _, r in weekly.iterrows()]

    n = need.set_index("FIPS")
    under = list(reach[reach["reach_flag"] != ""].sort_values("weekly_reach").head(10).index) if reach is not None else []
    top_gap = list(risky.groupby("FIPS")["gap_hh"].max().sort_values(ascending=False).head(15).index)
    counties = []
    for fips in dict.fromkeys(top_gap + under):
        r = n.loc[fips]
        row = {"county": r["county_label"], "food_insecure_people_2024": int(r["fi_persons"]),
               "food_insecurity_rate": round(float(r["fi_rate"]), 3),
               "share_above_snap_limit": round(float(r["fi_above_snap"]), 2) if pd.notna(r["fi_above_snap"]) else None,
               "cost_per_meal_usd": round(float(r["cost_per_meal"]), 2), "rural_urban_code": int(r["rucc"])}
        if reach is not None and fips in reach.index:
            row["weekly_reach"] = round(float(reach.loc[fips, "weekly_reach"]), 4)
            row["possibly_underserved"] = bool(reach.loc[fips, "reach_flag"] != "")
        if outlook is not None:
            o = outlook[(outlook["FIPS"] == fips) & (outlook["year"] == 2026)]
            if len(o):
                row["projected_food_insecure_2026"] = int(o["fi_persons_forecast"].iloc[0])
        counties.append(row)

    return {
        "region": region_name,
        "today": today.strftime("%Y-%m-%d"),
        "planning_window": f"{t['ds'].min():%Y-%m-%d} to {t['ds'].max():%Y-%m-%d} (8 weeks)",
        "units": {"demand_and_capacity": "households per week",
                  "food": "pounds (lbs)" if u == "lbs" else "kilograms (kg)", "money": "US dollars"},
        "assumptions": {"households_per_volunteer_shift": settings["hh_per_shift"],
                        f"food_per_household_visit_{u}": settings["food_per_visit"],
                        f"food_per_meal_{u}": settings["food_per_meal"],
                        "alerts_use": "high end of the forecast range",
                        "how_gaps_are_computed": "extra shifts only for households volunteers can't cover; "
                                                 "extra food only for food actually missing"},
        "totals": {"counties_in_region": int(t["FIPS"].nunique()),
                   "counties_at_risk": int(risky["FIPS"].nunique()),
                   "county_weeks_at_risk": int(len(risky)),
                   "total_gap_households": int(t["gap_hh"].sum()),
                   "total_extra_shifts": int(t["extra_shifts"].sum()),
                   f"total_extra_food_{u}": int(t["extra_food"].sum()),
                   "total_extra_meals": int(t["extra_meals"].sum()),
                   "total_funding_gap_usd": int(t["funding_gap_usd"].sum()),
                   "households_covered_by_transfers": int(moves["households_per_week"].sum()) if len(moves) else 0},
        "weekly_totals": weekly_totals,
        "economic_conditions": macro or "not available (no FRED data)",
        "top_alerts": alerts,
        "note_on_alerts": f"Showing the {len(alerts)} largest of {len(risky)} at-risk county-weeks.",
        "suggested_transfers": moves.sort_values("households_per_week", ascending=False)
                                    .head(MAX_TRANSFERS_TO_AI).to_dict("records"),
        "counties": counties,
        "data_notes": "Need data is real (Feeding America Map the Meal Gap; USDA SNAP by state). "
                      "Weekly visits and capacity are simulated. Transfers assume counties in the same "
                      "state can share food and volunteers.",
    }


def _unit(facts):
    return "lbs" if "lbs" in facts["units"]["food"] else "kg"


# ================================================================ 2. CLAUDE
SYSTEM_PLAN = """You are the operations strategist for a food bank network.
You receive facts computed by a demand-forecasting model for one region. Turn them into a proactive action plan.

Rules:
- Use ONLY numbers that appear in the facts. Never invent or estimate new figures.
- Units: demand and capacity are households PER WEEK; food uses the unit in facts.units.food (keep that unit); money is USD.
- Use suggested_transfers before asking for new volunteers, food or money (use what exists first).
- Each alert says what the county is short_on (volunteers, food, or both). Only ask for what is short.
- Use economic_conditions (FRED: state unemployment, food price inflation) to judge risk: rising unemployment or
  food inflation means demand may run toward the high end, so plan conservatively. Mention it in the summary or risks.
- Order priorities by urgency (start_outreach_by "ASAP" first, then earliest date), then by gap size.
- Consider counties flagged possibly_underserved even if they have no capacity alert.
- Be concrete: who does what, by when. Owners are roles (Volunteer coordinator, Warehouse lead,
  Development team, Agency relations, Executive director).
- A person approves everything; phrase actions as recommendations.

Return ONLY valid JSON, no markdown, with exactly these keys:
{"summary": "2-3 sentences",
 "priorities": [{"rank": 1, "county": "", "week_of": "", "action": "", "why": "", "owner": "", "deadline": ""}],
 "transfers": [{"week_of": "", "from_county": "", "to_county": "", "households_per_week": 0, "food": 0, "note": ""}],
 "outreach": [{"audience": "Volunteers|Donors|Community partners", "county": "", "channel": "SMS|Email|Social", "message": ""}],
 "watch_list": [{"county": "", "reason": ""}],
 "risks": [""]}
At most 6 priorities, 8 transfers, 4 outreach messages."""

SYSTEM_QA = """You are the operations strategist for a food bank network.
Answer using ONLY the facts and the current action plan provided (from a forecasting model).
Units: households per week, food in the unit given in facts.units.food, USD.
If the facts don't contain the answer, say so and say what data would be needed.
Be concise and practical: specific counties, weeks and numbers from the facts."""


def call_claude(system, user, max_tokens=3000):
    key = api_key()
    if not key:
        raise RuntimeError(f"No {KEY_NAME} set")
    r = requests.post(API_URL, timeout=120,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": max_tokens, "system": system,
                            "messages": [{"role": "user", "content": user}]})
    if r.status_code != 200:
        raise RuntimeError(f"API error {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


def parse_json(text):
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def ai_action_plan(facts):
    """Returns (plan, source). Uses rules if Claude is unavailable or returns invalid output."""
    try:
        plan = parse_json(call_claude(SYSTEM_PLAN, "Facts from the forecasting model:\n" + json.dumps(facts, default=str)))
        for k in ["priorities", "transfers", "outreach", "watch_list", "risks"]:
            plan.setdefault(k, [])
        plan.setdefault("summary", "")
        return plan, "Claude"
    except Exception as e:
        return rule_based_plan(facts), f"rules (AI unavailable: {str(e)[:120]})"


def answer_question(facts, question, history=None, plan=None):
    """Always returns (answer, source). Claude if available, otherwise rule-based from the facts."""
    try:
        convo = "".join(f"\nEarlier question: {q}\nEarlier answer: {a}\n" for q, a, *_ in (history or [])[-3:])
        plan_txt = f"\nCurrent action plan:\n{json.dumps(plan, default=str)}\n" if plan else ""
        ans = call_claude(SYSTEM_QA, f"Facts:\n{json.dumps(facts, default=str)}\n{plan_txt}{convo}\nQuestion: {question}", 800)
        return ans, "Claude"
    except Exception:
        return rule_based_answer(facts, question, plan), "rules"


# kept for compatibility with older app versions
def ai_answer(facts, question, history=None):
    return answer_question(facts, question, history)[0]


# ================================================================ 3. RULE-BASED FALLBACKS
def _action_text(a, u):
    parts = []
    if a["extra_volunteer_shifts"]:
        parts.append(f"Add {a['extra_volunteer_shifts']} volunteer shifts")
    if a[f"extra_food_{u}"]:
        parts.append(f"source {a[f'extra_food_{u}']:,} {u} of food (about {a['extra_meals']:,} meals, "
                     f"${a['funding_gap_usd']:,})")
    txt = " and ".join(parts) if parts else "Monitor"
    return txt[0].upper() + txt[1:] + f" (short on: {a['short_on']})"


def _macro_risks(facts):
    m = facts.get("economic_conditions")
    if not isinstance(m, dict) or "unemployment_rate" not in m:
        return []
    out = []
    if m.get("unemployment_change_1yr", 0) >= 0.3:
        out.append(f"Unemployment in {facts['region']} is {m['unemployment_rate']}%, up "
                   f"{m['unemployment_change_1yr']} points in a year (FRED, {m['unemployment_as_of']}): "
                   f"demand may run toward the high end of the forecast.")
    if m.get("food_price_inflation_yoy", 0) >= 3:
        out.append(f"Grocery prices are up {m['food_price_inflation_yoy']}% from a year ago "
                   f"(FRED, {m['food_prices_as_of']}): buying food will cost more and more families may need help.")
    return out


def rule_based_plan(facts):
    u = _unit(facts)
    worst = {}
    for a in facts["top_alerts"]:
        if a["county"] not in worst or a["gap_households"] > worst[a["county"]]["gap_households"]:
            worst[a["county"]] = a
    ranked = sorted(worst.values(), key=lambda a: (a["start_outreach_by"] != "ASAP", a["start_outreach_by"],
                                                 -a["gap_households"]))
    priorities = [{
        "rank": i, "county": a["county"], "week_of": a["week_of"],
        "action": _action_text(a, u),
        "why": f"Up to {a['high_end_households_per_week']:,} households/week expected vs capacity "
               f"{a['capacity_households_per_week']:,}",
        "owner": "Volunteer coordinator + Warehouse lead", "deadline": a["start_outreach_by"]}
        for i, a in enumerate(ranked[:6], 1)]
    transfers = [{"week_of": m["week_of"], "from_county": m["from_county"], "to_county": m["to_county"],
                  "households_per_week": m["households_per_week"], "food": m.get(f"food_{u}", 0),
                  "note": "Spare capacity, same week"} for m in facts["suggested_transfers"][:8]]
    watch = [{"county": c["county"], "reason": "Low weekly reach relative to need: possible access barriers"}
             for c in facts["counties"] if c.get("possibly_underserved")][:6]
    outreach = []
    if ranked:
        a = ranked[0]
        outreach = [
            {"audience": "Volunteers", "county": a["county"], "channel": "SMS",
             "message": f"We need {a['extra_volunteer_shifts']} more volunteer shifts the week of {a['week_of']} "
                        f"in {a['county']}. Can you help? Reply YES to sign up."},
            {"audience": "Donors", "county": a["county"], "channel": "Email",
             "message": f"Demand in {a['county']} is expected to rise the week of {a['week_of']}. "
                        f"${a['funding_gap_usd']:,} provides about {a['extra_meals']:,} meals "
                        f"({a[f'extra_food_{u}']:,} {u} of food). Help us be ready before the line forms."}]
    tot = facts["totals"]
    return {"summary": f"{tot['counties_at_risk']} of {tot['counties_in_region']} counties in {facts['region']} "
                       f"may exceed weekly capacity in the next 8 weeks. Move spare capacity first "
                       f"({tot['households_covered_by_transfers']:,} household-visits can be covered), then recruit "
                       f"volunteers and source food for the rest.",
            "priorities": priorities, "transfers": transfers, "outreach": outreach, "watch_list": watch,
            "risks": _macro_risks(facts) + [
                "Forecast ranges can be too narrow in unusual weeks; review the plan weekly.",
                "Transfers assume counties in the same state can share food and volunteers."]}


def rule_based_answer(facts, question, plan=None):
    """Answers common planning questions directly from the model's facts (no AI needed)."""
    q = question.lower()
    u, tot = _unit(facts), facts["totals"]
    alerts, weekly = facts["top_alerts"], facts["weekly_totals"]
    by_gap = sorted(alerts, key=lambda a: -a["gap_households"])
    next_week = weekly[0] if weekly else None

    def top(n=3):
        seen, out = set(), []
        for a in by_gap:
            if a["county"] not in seen:
                seen.add(a["county"]); out.append(a)
            if len(out) == n:
                break
        return out

    m = facts.get("economic_conditions")
    if any(w in q for w in ["econom", "unemploy", "inflation", "price", "jobs", "fred", "macro"]):
        if not isinstance(m, dict):
            return "Economic data isn't loaded. Add FRED_API_KEY to .streamlit/secrets.toml and rerun the forecast."
        nat = m.get("national_indicators", {})
        nat_txt = " National: " + "; ".join(f"{k} {v['value_percent']}% ({v['as_of']})" for k, v in nat.items()) + "." if nat else ""
        if "unemployment_rate" not in m:
            return "State unemployment isn't loaded (rerun the forecast with FRED_API_KEY)." + nat_txt
        return (f"{facts['region']} unemployment is {m['unemployment_rate']}% ({m['unemployment_as_of']}), "
                f"{'+' if m['unemployment_change_1yr'] >= 0 else ''}{m['unemployment_change_1yr']} points versus a year ago. "
                f"Grocery prices are up {m['food_price_inflation_yoy']}% year over year ({m['food_prices_as_of']}). "
                f"Both feed into the forecast with a 6-week lag. "
                + (" ".join(_macro_risks(facts)) or "Neither signal is raising risk right now.") + nat_txt)
    if any(w in q for w in ["next week", "this week"]) and next_week:
        return (f"Week of {next_week['week_of']}: {next_week['counties_at_risk']} counties at risk, "
                f"{next_week['gap_households']:,} households over capacity. That needs "
                f"{next_week['extra_volunteer_shifts']:,} extra volunteer shifts, {next_week[f'extra_food_{u}']:,} {u} of food "
                f"(about {next_week['extra_meals']:,} meals, ${next_week['funding_gap_usd']:,}).")
    if any(w in q for w in ["food", "lbs", "pound", "kg", "kilo", "meal"]):
        lines = [f"Across the next 8 weeks: {tot[f'total_extra_food_{u}']:,} {u} of extra food "
                 f"(about {tot['total_extra_meals']:,} meals). By week:"]
        lines += [f"- {w['week_of']}: {w[f'extra_food_{u}']:,} {u}" for w in weekly]
        return "\n".join(lines)
    if any(w in q for w in ["volunteer", "shift", "staff"]):
        lines = [f"Across the next 8 weeks: {tot['total_extra_shifts']:,} extra volunteer shifts. Largest needs:"]
        lines += [f"- {a['county']}, week of {a['week_of']}: {a['extra_volunteer_shifts']} shifts "
                  f"(start by {a['start_outreach_by']})" for a in top(5)]
        return "\n".join(lines)
    if any(w in q for w in ["money", "fund", "donat", "dollar", "$", "cost", "budget"]):
        lines = [f"Total funding gap over 8 weeks: ${tot['total_funding_gap_usd']:,}. Largest county-weeks:"]
        lines += [f"- {a['county']}, week of {a['week_of']}: ${a['funding_gap_usd']:,}" for a in top(5)]
        return "\n".join(lines)
    if any(w in q for w in ["mobile", "underserved", "missing", "reach", "access", "rural"]):
        under = [c for c in facts["counties"] if c.get("possibly_underserved")]
        if not under:
            return "No counties in this region are flagged as possibly underserved right now."
        lines = ["Counties where need is high but visits are low (possible access barriers), good candidates "
                 "for a mobile pantry or partner outreach:"]
        lines += [f"- {c['county']}: {c['food_insecure_people_2024']:,} food-insecure people, "
                  f"weekly reach {c.get('weekly_reach', 0):.2%}" for c in under[:6]]
        return "\n".join(lines)
    if any(w in q for w in ["transfer", "move", "spare", "reallocat", "share"]):
        moves = facts["suggested_transfers"]
        if not moves:
            return "No same-week transfers are available: no county has enough spare capacity."
        lines = [f"Moving spare capacity covers {tot['households_covered_by_transfers']:,} household-visits. Largest moves:"]
        lines += [f"- {m['week_of']}: {m['from_county']} to {m['to_county']}, {m['households_per_week']} households "
                  f"({m.get(f'food_{u}', 0):,} {u})" for m in moves[:6]]
        return "\n".join(lines)
    if any(w in q for w in ["when", "urgent", "deadline", "first", "asap", "start"]):
        asap = [a for a in alerts if a["start_outreach_by"] == "ASAP"]
        pick = asap[:5] if asap else alerts[:5]
        lines = ["Most urgent (outreach should start now):" if asap else "Earliest deadlines:"]
        lines += [f"- {a['county']}, week of {a['week_of']}: start by {a['start_outreach_by']}" for a in pick]
        return "\n".join(lines)
    # default: which counties need attention most
    if True:
        lines = [f"{tot['counties_at_risk']} of {tot['counties_in_region']} counties may exceed capacity. "
                 f"Biggest gaps:"]
        lines += [f"- {a['county']}, week of {a['week_of']}: up to {a['high_end_households_per_week']:,} households "
                  f"vs capacity {a['capacity_households_per_week']:,} ({a['gap_households']:,} over)" for a in top(3)]
        if plan and plan.get("summary"):
            lines += ["", f"Plan summary: {plan['summary']}"]
        return "\n".join(lines)


# ================================================================ 4. EXPORT
def plan_to_markdown(plan, source, region, unit="lbs"):
    L = [f"# PantryPulse action plan: {region}", f"_Generated by {source}. Requires human approval._",
         f"_Units: households per week; food in {unit}; USD._", "", plan.get("summary", ""), "", "## Priorities"]
    for p in plan.get("priorities", []):
        L.append(f"{p.get('rank')}. **{p.get('county')}**, week of {p.get('week_of')}: {p.get('action')} "
                 f"(owner: {p.get('owner')}; by {p.get('deadline')}). Why: {p.get('why')}")
    if plan.get("transfers"):
        L += ["", "## Transfers"] + [f"- {m.get('week_of')}: {m.get('from_county')} to {m.get('to_county')}, "
                                     f"{m.get('households_per_week')} households/week ({m.get('food', m.get(f'food_{unit}'))} {unit}). "
                                     f"{m.get('note', '')}" for m in plan["transfers"]]
    if plan.get("outreach"):
        L += ["", "## Outreach"] + [f"- {o.get('audience')} ({o.get('county')}, {o.get('channel')}): {o.get('message')}"
                                    for o in plan["outreach"]]
    if plan.get("watch_list"):
        L += ["", "## Watch list"] + [f"- {w.get('county')}: {w.get('reason')}" for w in plan["watch_list"]]
    if plan.get("risks"):
        L += ["", "## Risks"] + [f"- {r}" for r in plan["risks"]]
    return "\n".join(L)


def plan_to_pdf(plan, source, region, unit="lbs", facts=None, approved=None):
    """Build the action plan as a PDF and return its bytes (for st.download_button).
    approved: optional list of priority ranks the user ticked."""
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=f"PantryPulse action plan: {region}", author="PantryPulse")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, alignment=0, spaceAfter=4, textColor=colors.HexColor("#1F3A5F"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1F3A5F"))
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.5, leading=11)
    head = ParagraphStyle("head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    P = lambda x, s=cell: Paragraph(escape(str(x if x is not None else "")), s)

    def table(header, rows, widths):
        data = [[P(h, head) for h in header]] + [[P(v) for v in r] for r in rows]
        tb = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F9")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D0DA")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return tb

    story = [P(f"PantryPulse action plan: {region}", h1),
             P(f"Generated {date.today():%B %d, %Y} by {source}. Requires human approval before any action. "
               f"Units: households per week; food in {unit}; money in USD.", small),
             Spacer(1, 10), P("Summary", h2), P(plan.get("summary", ""), body)]

    if facts:
        t = facts["totals"]
        story += [P("Key numbers (next 8 weeks)", h2), table(
            ["Counties at risk", "Households over capacity", f"Extra food ({unit})", "Extra meals",
             "Funding gap", "Extra volunteer shifts", "Covered by transfers"],
            [[f"{t['counties_at_risk']} of {t['counties_in_region']}", f"{t['total_gap_households']:,}",
              f"{t.get(f'total_extra_food_{unit}', 0):,}", f"{t['total_extra_meals']:,}",
              f"${t['total_funding_gap_usd']:,}", f"{t['total_extra_shifts']:,}",
              f"{t['households_covered_by_transfers']:,}"]],
            [1.3, 1.5, 1.3, 1.2, 1.3, 1.5, 1.6])]

    pr = plan.get("priorities", [])
    if pr:
        ok = set(approved or [])
        story += [P("Priorities", h2), table(
            ["#", "County", "Week of", "Recommended action", "Why", "Owner", "Deadline", "Approved"],
            [[p.get("rank"), p.get("county"), p.get("week_of"), p.get("action"), p.get("why"), p.get("owner"),
              p.get("deadline"), "Yes" if p.get("rank") in ok else ""] for p in pr],
            [0.3, 1.3, 0.8, 2.6, 2.0, 1.2, 0.8, 0.7])]
    if plan.get("transfers"):
        story += [P("Move spare capacity first", h2), table(
            ["Week of", "From", "To", "Households/week", f"Food ({unit})", "Note"],
            [[m.get("week_of"), m.get("from_county"), m.get("to_county"), m.get("households_per_week"),
              m.get("food", m.get(f"food_{unit}", "")), m.get("note", "")] for m in plan["transfers"]],
            [0.9, 2.0, 2.0, 1.1, 1.0, 2.7])]
    if plan.get("outreach"):
        story += [P("Draft outreach", h2), table(
            ["Audience", "County", "Channel", "Message"],
            [[o.get("audience"), o.get("county"), o.get("channel"), o.get("message")] for o in plan["outreach"]],
            [1.1, 1.6, 0.8, 6.2])]
    if plan.get("watch_list"):
        story += [P("Watch list", h2)] + [P(f"• {w.get('county')}: {w.get('reason')}", body) for w in plan["watch_list"]]
    if plan.get("risks"):
        story += [P("Risks and caveats", h2)] + [P(f"• {r}", body) for r in plan["risks"]]
    story += [Spacer(1, 14), P("Need data: Feeding America Map the Meal Gap (2019-2024) and USDA SNAP households by state. "
                               "Weekly visits and capacity are simulated for this prototype. Numbers are computed by the "
                               "forecasting model; the AI writes the plan but does not calculate figures.", small)]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(0.6 * inch, 0.35 * inch, f"PantryPulse | {region}")
        canvas.drawRightString(landscape(letter)[0] - 0.6 * inch, 0.35 * inch, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
