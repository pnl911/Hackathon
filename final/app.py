"""
PantryPulse - Streamlit app (v3: all US counties, food in lbs or kg)
Run AFTER demand_forecast_us.py. Needs strategist.py in the same folder.
    pip install streamlit altair requests reportlab
    streamlit run app.py
AI strategist (optional, PowerShell):  $env:ANTHROPIC_API_KEY="sk-ant-..."
Without a key, the app uses rule-based plans and templates.

UNITS: demand and capacity = households per week; food = lbs or kg (sidebar toggle); money = USD.
"""
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
import strategist as sg
import fred_data as fd

st.set_page_config(page_title="PantryPulse", page_icon="🥫", layout="wide")
GREEN, YELLOW, RED = "#2E7D5B", "#C99A2E", "#B3392F"
STATUS_COLOR = {"GREEN": GREEN, "YELLOW": YELLOW, "RED": RED}
LBS_PER_KG = 2.20462
# Feeding America standard: 1.2 lb (0.544 kg) per meal. Default visit: 30 lb (13.6 kg).
UNIT_DEFAULTS = {"lbs": {"per_meal": 1.2, "per_visit": 30.0, "step": 1.0, "max": 110.0},
                 "kg": {"per_meal": 0.544, "per_visit": 13.6, "step": 0.5, "max": 50.0}}


@st.cache_data
def load():
    fc = pd.read_csv("outputs/forecast_with_alerts.csv", parse_dates=["ds"])
    hist = pd.read_csv("outputs/synthetic_weekly_visits.csv", parse_dates=["ds"])
    need = pd.read_csv("outputs/county_need.csv")
    acc = pd.read_csv("outputs/backtest_accuracy.csv")
    snap = pd.read_csv("outputs/snap_state_change.csv")
    try:
        outlook = pd.read_csv("outputs/annual_need_outlook_2025_2026.csv")
    except FileNotFoundError:
        outlook = None
    try:
        macro = pd.read_csv("outputs/macro_state_latest.csv")
    except FileNotFoundError:
        macro = None
    return fc, hist, need, acc, snap, outlook, macro


try:
    fc_all, hist_all, need_all, acc_all, snap, outlook, macro_all = load()
except FileNotFoundError:
    st.error("Forecast files not found. Run `python demand_forecast_us.py` in this folder first, then refresh.")
    st.stop()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("🥫 PantryPulse")
view = st.sidebar.radio("View", ["County forecast", "AI action plan", "Economy (FRED)"])
unit = st.sidebar.radio("Food unit", ["lbs", "kg"], horizontal=True,
                        help="Switch between pounds and kilograms. All food numbers update.")
U = UNIT_DEFAULTS[unit]
to_unit = LBS_PER_KG if unit == "lbs" else 1.0          # forecast files store food in kg

state_names = snap.set_index("State")["State Name"].to_dict()
states = sorted(need_all["State"].unique(), key=lambda s: state_names.get(s, s))
state = st.sidebar.selectbox("State", states, index=states.index("TX") if "TX" in states else 0,
                             format_func=lambda s: state_names.get(s, s))
need = need_all[need_all["State"] == state]
fc = fc_all[fc_all["State"] == state]
labels = need.sort_values("county")["county"].tolist()
county_name = st.sidebar.selectbox("County", labels,
                                   index=labels.index("Dallas County") if "Dallas County" in labels else 0)
n = need[need["county"] == county_name].iloc[0]
fips = int(n["FIPS"])
c_fc = fc[fc["FIPS"] == fips].copy()

st.sidebar.subheader("Weekly capacity for this county")
default_shifts = int(c_fc["volunteer_shifts_per_week"].iloc[0])
shifts = st.sidebar.slider("Volunteer shifts per week", 1, max(10, default_shifts * 2), max(1, default_shifts))
hh_per_shift = st.sidebar.slider("Households one shift can serve", 5, 60, 25)
food_per_visit = st.sidebar.number_input(f"Food per household visit ({unit})", min_value=1.0, max_value=U["max"],
                                         value=U["per_visit"], step=U["step"], key=f"visit_{unit}",
                                         help="Food one household receives each time it visits (30 lb = 13.6 kg).")
food_week = st.sidebar.number_input(f"Food available per week ({unit})", min_value=0,
                                    value=int(c_fc["food_capacity_kg_per_week"].iloc[0] * to_unit), step=100,
                                    key=f"food_{unit}_{fips}")

staff_cap = shifts * hh_per_shift
food_cap = food_week / food_per_visit
capacity = int(min(staff_cap, food_cap))
bottleneck = "volunteers" if staff_cap <= food_cap else "food"
st.sidebar.metric("Capacity (households per week)", f"{capacity:,}", help=f"Limited by {bottleneck}")
st.sidebar.caption(f"Volunteers can serve {staff_cap:,}/week; food covers {int(food_cap):,}/week "
                   f"({food_week:,} {unit} ÷ {food_per_visit:g} {unit} per visit).")
settings = {"hh_per_shift": hh_per_shift, "food_per_visit": food_per_visit, "food_per_meal": U["per_meal"],
            "unit": unit}

# region-level table (used by both views)
t = sg.county_week_table(fc, settings, capacity_override={fips: {"staff_hh": staff_cap, "food_available": food_week}})
recent = hist_all[hist_all["FIPS"].isin(need["FIPS"])].sort_values("ds").groupby("FIPS").tail(8) \
    .groupby("FIPS")["households_per_week"].mean()
reach = need.set_index("FIPS").join(recent.rename("recent_hh_per_week"))
reach["fi_households"] = reach["fi_persons"] / 2.6
reach["weekly_reach"] = reach["recent_hh_per_week"] / reach["fi_households"]
reach["reach_flag"] = np.where(reach["weekly_reach"] < 0.8 * reach["weekly_reach"].median(), "Possibly underserved", "")
region_name = state_names.get(state, state)
@st.cache_data(ttl=3600, show_spinner=False)
def live_state_macro(st_code):
    return fd.state_macro(st_code)


macro = None
if macro_all is not None and state in set(macro_all["State"]):
    # saved by demand_forecast_us.py: these values were used inside the forecast
    macro = macro_all.set_index("State").loc[state].to_dict()
    macro = {k: (v.item() if hasattr(v, "item") else v) for k, v in macro.items()}
    macro["in_forecast"] = True
elif fd.fred_key():
    # forecast was run without FRED: fetch live so the dashboard and the AI still see the economy
    macro = live_state_macro(state)


def macro_line():
    if not macro:
        if fd.fred_key():
            return ("Economic factors: FRED key found, but no data could be downloaded. Check your internet "
                    "connection, then run  python demand_forecast_us.py  again.")
        return "Economic factors: off (add FRED_API_KEY to .streamlit/secrets.toml and rerun the forecast)."
    sign = "+" if macro["unemployment_change_1yr"] >= 0 else ""
    used = ("Both are forecast inputs with a 6-week lag." if macro.get("in_forecast") else
            "Shown live from FRED.")
    return (f"Economy (FRED): {region_name} unemployment {macro['unemployment_rate']}% "
            f"({sign}{macro['unemployment_change_1yr']} pts vs a year ago, {macro['unemployment_as_of']}); "
            f"grocery prices {macro['food_price_inflation_yoy']:+}% year over year ({macro['food_prices_as_of']}). "
            + used)

@st.cache_data(ttl=3600, show_spinner="Loading economic data from FRED...")
def fred_summaries():
    return fd.all_summaries()


national = fred_summaries()
ai_macro = dict(macro or {})
if any(national.values()):
    ai_macro["national_indicators"] = fd.facts_for_ai(national)
ai_macro = ai_macro or None

# ================================================================== ECONOMY (FRED) VIEW
if view == "Economy (FRED)":
    st.title("The economy behind food bank demand")
    st.caption("Live data from FRED (Federal Reserve Bank of St. Louis). When jobs, prices or spending move, "
               "food bank demand follows a few weeks later.")
    have = {k: v for k, v in national.items() if v}
    if fd.fred_key() is None:
        st.warning("No FRED_API_KEY found in .streamlit/secrets.toml, so showing cached data only (if any).")
    if not have:
        st.error("No FRED data yet. Add FRED_API_KEY = \"...\" to .streamlit/secrets.toml, "
                 "make sure you're online, and refresh.")
        st.stop()
    src = sorted({v["source"] for v in have.values() if v["source"]})
    st.caption(f"Source: {', '.join(src)}. Data is cached for offline use in outputs/fred_cache/.")

    cols = st.columns(len(have))
    for col, (sid, s) in zip(cols, have.items()):
        good_when_up = sid in ("GDPC1", "PCE")
        col.metric(s["short"], f"{s['latest_value']:.1f}%",
                   delta=f"{s['change_vs_previous']:+.1f} pts" if s["change_vs_previous"] is not None else None,
                   delta_color="normal" if good_when_up else "inverse",
                   help=f"{s['title']} ({s['frequency']}). Latest: {s['latest_date']}.")

    if macro:
        c1, c2 = st.columns(2)
        c1.metric(f"{region_name} unemployment", f"{macro['unemployment_rate']}%",
                  delta=f"{macro['unemployment_change_1yr']:+} pts vs a year ago", delta_color="inverse",
                  help=f"FRED series {state}UR, as of {macro['unemployment_as_of']}. Used in the forecast.")
        c2.metric("Grocery price inflation", f"{macro['food_price_inflation_yoy']}%",
                  help=f"FRED series CUSR0000SAF11 (food at home), year over year, as of "
                       f"{macro['food_prices_as_of']}. Used in the forecast.")

    st.divider()
    for sid, s in have.items():
        st.subheader(s["title"])
        left, right = st.columns([3, 2])
        d = s["series"][s["series"].index >= "2015-01-01"].rename("value").reset_index()
        d.columns = ["date", "value"]
        label = "% change vs a year earlier" if fd.INDICATORS[sid]["transform"] == "yoy_pct" else "Percent"
        line = alt.Chart(d).mark_line(color="#3A6EA5", strokeWidth=2).encode(
            x=alt.X("date:T", title=None), y=alt.Y("value:Q", title=label),
            tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("value:Q", title=label, format=".2f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#999", strokeDash=[3, 3]).encode(y="y:Q")
        left.altair_chart((line + zero).properties(height=220), width="stretch")
        right.markdown(f"**Latest:** {s['latest_value']:.2f}% ({s['latest_date']})  \n"
                       f"**Raw value:** {s['raw_latest']:,} {s['units']}  \n"
                       f"**Frequency:** {s['frequency']}  \n"
                       f"**Why it matters for food banks:** {s['why']}  \n"
                       f"[View {sid} on FRED]({s['link']})")

    st.divider()
    st.markdown("**How PantryPulse uses this.** The forecast model takes in each state's **unemployment rate** "
                "and **grocery price inflation** from FRED, lagged 6 weeks (families respond with a delay). "
                "The national indicators above (GDP, CPI, inflation, consumer spending) are passed to AI "
                "as context, so the action plan can plan more conservatively when the economy weakens.")
    st.stop()

# ================================================================== AI ACTION PLAN VIEW
if view == "AI action plan":
    st.title(f"AI action plan: {region_name}, next 8 weeks")
    st.caption("The forecast model computes every number. AI turns them into a prioritized, dated plan. "
               f"A person approves before anything happens. Units: households per week, food in {unit}.")
    moves = sg.reallocation_plan(t, food_per_visit, unit)
    facts = sg.build_facts(t, moves, need, region_name, settings, reach=reach, outlook=outlook, macro=ai_macro)
    tot = facts["totals"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Counties at risk", f"{tot['counties_at_risk']} of {tot['counties_in_region']}")
    k2.metric("Extra food needed", f"{tot[f'total_extra_food_{unit}']:,} {unit}",
              help=f"About {tot['total_extra_meals']:,} meals")
    k3.metric("Funding gap", f"${tot['total_funding_gap_usd']:,}")
    k4.metric("Extra volunteer shifts", f"{tot['total_extra_shifts']:,}")
    st.caption("📈 " + macro_line())
    st.caption(f"Moving spare capacity between counties covers {tot['households_covered_by_transfers']:,} "
               f"household-visits. Sidebar capacity applies to {county_name}; other counties use their current plan.")

    key_src = sg.key_status()
    has_key = key_src is not None
    if has_key:
        st.success(f"AI is connected.")
    else:
        st.info("AI isn't connected, so plans and answers come from built-in rules using the same forecast. "
                "Please check the backend.")
        with st.expander("Why isn't Claude connected? (safe: never shows your key)"):
            diag = sg.key_diagnostics()
            st.write(f"**App is running from:** `{diag['running from']}`")
            st.write(f"**strategist.py is in:** `{diag['strategist.py location']}`")
            st.write(f"**Environment variable set:** {diag['env variable set']}")
            st.dataframe(pd.DataFrame(diag["files"]), hide_index=True, width="stretch")
            st.caption("The file should be at <folder with app.py>\\.streamlit\\secrets.toml and contain one line: "
                       'ANTHROPIC_API_KEY = "sk-ant-..."  After fixing it, stop the app (Ctrl + C) and run it again.')

    if st.button("🧭 Generate action plan", type="primary"):
        with st.spinner("AI is reviewing the forecast and building the plan..."):
            st.session_state["plan"], st.session_state["plan_src"] = sg.ai_action_plan(facts)
            st.session_state["plan_region"] = region_name

    if "plan" in st.session_state and st.session_state.get("plan_region") == region_name:
        plan, src = st.session_state["plan"], st.session_state["plan_src"]
        st.subheader("Summary")
        st.write(plan.get("summary", ""))
        st.caption(f"Generated by {src}. Numbers come from the forecast model.")
        st.subheader("Priorities")
        pr = pd.DataFrame(plan.get("priorities", []))
        if len(pr):
            pr.insert(0, "Approve", False)
            edited = st.data_editor(pr, hide_index=True, width="stretch",
                                    disabled=[c for c in pr.columns if c != "Approve"])
        else:
            edited = pr
            st.write("No priority actions: capacity covers the forecast.")
        if plan.get("transfers"):
            st.subheader("Move spare capacity first")
            st.dataframe(pd.DataFrame(plan["transfers"]), hide_index=True, width="stretch")
        if plan.get("outreach"):
            st.subheader("Draft outreach")
            for i, o in enumerate(plan["outreach"]):
                st.text_area(f"{o.get('audience')} | {o.get('county')} | {o.get('channel')}",
                             o.get("message", ""), height=90, key=f"out_{i}")
        if plan.get("watch_list"):
            st.subheader("Watch list")
            for w in plan["watch_list"]:
                st.markdown(f"- **{w.get('county')}**: {w.get('reason')}")
        if plan.get("risks"):
            with st.expander("Risks and caveats"):
                for r in plan["risks"]:
                    st.markdown(f"- {r}")
        c1, c2 = st.columns(2)
        if c1.button("✅ Approve selected actions"):
            n_ok = int(edited["Approve"].sum()) if len(edited) else 0
            st.success(f"{n_ok} action(s) approved. Nothing is sent automatically; owners are notified to act.")
        approved = edited.loc[edited["Approve"], "rank"].tolist() if len(edited) else []
        try:
            pdf = sg.plan_to_pdf(plan, src, region_name, unit, facts=facts, approved=approved)
            c2.download_button("📄 Download plan (PDF)", pdf, file_name=f"pantrypulse_plan_{state}.pdf",
                               mime="application/pdf")
        except ImportError:
            c2.warning("PDF export needs reportlab: run  pip install reportlab  and restart the app.")

    st.divider()
    st.subheader("Ask the strategist")
    st.caption("Examples: Which county should we worry about most? Where should a mobile pantry go? "
               f"How much food in {unit} do we need next week? How is the economy affecting demand?")
    q = st.text_input("Your question")
    if st.button("Ask") and q:
        current_plan = st.session_state.get("plan") if st.session_state.get("plan_region") == region_name else None
        with st.spinner("Thinking..."):
            ans, ans_src = sg.answer_question(facts, q, st.session_state.get("qa", []), plan=current_plan)
        st.session_state.setdefault("qa", []).append((q, ans, ans_src))
    for item in reversed(st.session_state.get("qa", [])):
        qq, aa = item[0], item[1]
        ans_src = item[2] if len(item) > 2 else "Claude"
        st.markdown(f"**Q: {qq}**")
        st.write(aa)
        st.caption(f"Answered by {ans_src} from the forecast model's numbers.")
    with st.expander("What the AI sees (facts from the model)"):
        st.json(facts)
    st.stop()

# ================================================================== COUNTY FORECAST VIEW
c_t = t[t["FIPS"] == fips]
flagged = c_t[c_t["status"] != "GREEN"]
st.title(f"{n['county_label']}: next 8 weeks")

if len(flagged):
    w = flagged.sort_values("gap_hh", ascending=False).iloc[0]
    st.markdown(
        f"<div style='border-left:6px solid {STATUS_COLOR[w['status']]};padding:10px 16px;"
        f"background:rgba(179,57,47,0.06);font-size:1.1rem'>"
        f"<b>{len(flagged)} of 8 weeks</b> may exceed weekly capacity. Worst week: <b>{w['ds']:%b %d}</b>, "
        f"up to <b>{int(w['yhat_upper']):,} households</b> vs capacity of {capacity:,} (limited by {bottleneck}). "
        f"Volunteers can serve {staff_cap:,}; food covers {int(food_cap):,}. That week needs "
        + (f"<b>{w['extra_shifts']} more volunteer shifts</b>" if w['extra_shifts'] else "no extra volunteers")
        + " and "
        + (f"<b>{w['extra_food']:,} {unit}</b> more food (about {w['extra_meals']:,} meals, ${w['funding_gap_usd']:,})"
           if w['extra_food'] else "no extra food")
        + ".</div>", unsafe_allow_html=True)
else:
    st.success(f"Weekly capacity covers the expected range for all 8 weeks (limited by {bottleneck}).")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Food-insecure people (2024)", f"{int(n['fi_persons']):,}")
m2.metric("Food insecurity rate", f"{n['fi_rate']:.1%}")
m3.metric("Above SNAP income limit", f"{n['fi_above_snap']:.0%}" if pd.notna(n["fi_above_snap"]) else "n/a",
          help="Share of food-insecure people who don't qualify for SNAP and rely on charitable food")
m4.metric("Cost per meal", f"${n['cost_per_meal']:.2f}")
st.caption("📈 " + macro_line())

h = hist_all[hist_all["FIPS"] == fips].tail(52)
x = alt.X("ds:T", title=None)
chart = (alt.Chart(c_t).mark_area(opacity=0.25, color="#3A6EA5").encode(x=x, y="yhat_lower:Q", y2="yhat_upper:Q")
         + alt.Chart(h).mark_line(color="#333").encode(x=x, y=alt.Y("households_per_week:Q", title="Households per week"))
         + alt.Chart(c_t).mark_line(color="#3A6EA5", strokeWidth=2.5).encode(x=x, y="yhat:Q")
         + alt.Chart(pd.DataFrame({"cap": [capacity]})).mark_rule(color=RED, strokeDash=[6, 4], size=2).encode(y="cap:Q")
         + alt.Chart(c_t).mark_circle(size=90).encode(
             x=x, y="yhat:Q",
             color=alt.Color("status:N", scale=alt.Scale(domain=list(STATUS_COLOR), range=list(STATUS_COLOR.values())),
                             legend=alt.Legend(title="Week status")),
             tooltip=[alt.Tooltip("ds:T", title="Week of"), alt.Tooltip("yhat:Q", title="Expected households", format=","),
                      alt.Tooltip("yhat_upper:Q", title="High end", format=","), "status:N"]))
st.altair_chart(chart.properties(height=340), width="stretch")
method = c_fc["method"].iloc[0]
st.caption(f"Black: last 52 weeks (simulated). Blue: forecast and its likely range ({method}). "
           f"Red dashed: weekly capacity. Alerts use the high end of the range.")

st.subheader("Weekly plan")
show = c_t[["ds", "yhat", "yhat_upper", "status", "short_on", "gap_hh", "extra_shifts", "extra_food",
            "extra_meals", "funding_gap_usd"]].rename(columns={
    "ds": "Week of", "yhat": "Expected households", "yhat_upper": "High end", "status": "Status", "short_on": "Short on",
    "gap_hh": "Households over capacity", "extra_shifts": "Extra volunteer shifts",
    "extra_food": f"Extra food ({unit})", "extra_meals": "Extra meals", "funding_gap_usd": "Funding gap ($)"})
show["Week of"] = show["Week of"].dt.strftime("%b %d")
st.dataframe(show, hide_index=True, width="stretch")
st.caption(f"All values are for that one week. Extra shifts = (high end − {staff_cap:,} volunteers can serve) ÷ {hh_per_shift}. "
           f"Extra food = high end × {food_per_visit:g} {unit} − {food_week:,} {unit} on hand. "
           f"Meals = {unit} ÷ {U['per_meal']} {unit} per meal. Funding = meals × ${n['cost_per_meal']:.2f} local cost per meal.")

st.subheader("Recommended actions")
if len(flagged):
    w = flagged.sort_values("gap_hh", ascending=False).iloc[0]
    recs = []
    if w["extra_shifts"]:
        recs.append(f"- Add **{w['extra_shifts']} volunteer shifts** the week of {w['ds']:%b %d}")
    else:
        recs.append("- Volunteers are enough for that week: focus on food")
    if w["extra_food"]:
        recs.append(f"- Secure **{w['extra_food']:,} {unit}** of additional food that week "
                    f"(about {w['extra_meals']:,} meals, **${w['funding_gap_usd']:,}** at local meal cost)")
    else:
        recs.append("- Food on hand is enough for that week: focus on volunteers")
    recs.append(f"- Current bottleneck: **{bottleneck}**. Start outreach at least 14 days before that week")
    st.markdown("\n".join(recs))
    if st.button("Draft outreach messages"):
        vol = (f"We need {w['extra_shifts']} more volunteer shifts the week of {w['ds']:%b %d} in "
               f"{n['county_label']}. We're expecting up to {int(w['yhat_upper']):,} families. Reply YES to sign up."
               if w["extra_shifts"] else
               f"Thank you, volunteers! {n['county_label']} is fully staffed for the week of {w['ds']:%b %d}. "
               f"Food donations are our biggest need that week.")
        donor = (f"Demand in {n['county_label']} is expected to climb the week of {w['ds']:%b %d}. "
                 f"${w['funding_gap_usd']:,} provides about {w['extra_meals']:,} meals ({w['extra_food']:,} {unit} of food) "
                 f"at the local cost of ${n['cost_per_meal']:.2f} per meal. Help us be ready before the line forms.")
        src = "template (no API key set)"
        if sg.api_key():
            try:
                txt = sg.call_claude(
                    f"You write short, warm outreach for a food bank. Use only the numbers given. Food is in {unit}.",
                    f"County={n['county_label']}; week={w['ds']:%B %d}; up to {int(w['yhat_upper'])} households; "
                    f"capacity {capacity} households/week; extra volunteer shifts {w['extra_shifts']}; extra food "
                    f"{w['extra_food']} {unit} (~{w['extra_meals']} meals); funding gap ${w['funding_gap_usd']}. "
                    "Write (1) a volunteer SMS under 300 characters and (2) a donor appeal under 80 words, "
                    "separated by a line containing only ---", 500)
                vol, donor = [p.strip() for p in txt.split("---", 1)]
                src = "Claude"
            except Exception:
                pass
        st.session_state["drafts"] = (vol, donor, src)
    if "drafts" in st.session_state:
        vol, donor, src = st.session_state["drafts"]
        st.text_area("Volunteer message", vol, height=90)
        st.text_area("Donor appeal", donor, height=120)
        st.caption(f"Drafted by {src}. Numbers come from the forecast, not the AI.")
        if st.button("✅ Approve plan"):
            st.success("Plan approved. A coordinator makes the final call; nothing is sent automatically.")
else:
    st.info("No actions needed. Try lowering volunteer shifts or food available in the sidebar.")

st.divider()
st.subheader(f"Who might we be missing in {region_name}?")
rt = reach.reset_index().sort_values("weekly_reach")
rt = rt[["county_label", "fi_persons", "fi_rate", "recent_hh_per_week", "weekly_reach", "reach_flag"]]
rt.columns = ["County", "Food-insecure people", "FI rate", "Households per week (recent)", "Weekly reach", "Reach flag"]
fmt = {"Food-insecure people": "{:,.0f}", "FI rate": "{:.1%}", "Households per week (recent)": "{:,.0f}",
       "Weekly reach": "{:.2%}"}
st.dataframe(rt.head(15).style.format(fmt), hide_index=True, width="stretch")
with st.expander(f"All {len(rt)} counties"):
    st.dataframe(rt.style.format(fmt), hide_index=True, width="stretch")
st.caption("Weekly reach = households served per week ÷ estimated food-insecure households (people ÷ 2.6). "
           "Low reach can mean access barriers, not low need. Need data: Feeding America Map the Meal Gap 2026. "
           "Visits and capacity are simulated.")

with st.expander("Model accuracy (12-week backtest)"):
    a = acc_all[acc_all["State"] == state]
    st.write(f"**{n['county_label']}** ({method}): error {float(a.loc[a['FIPS'] == fips, 'mape_prophet'].iloc[0]):.1%} "
             f"vs naive {float(a.loc[a['FIPS'] == fips, 'mape_naive_4wk_avg'].iloc[0]):.1%}")
    st.write(f"**{region_name}, median across {len(a)} counties:** Prophet {a['mape_prophet'].median():.1%} vs "
             f"naive {a['mape_naive_4wk_avg'].median():.1%}; actual value inside the range "
             f"{a['range_coverage'].mean():.0%} of the time.")
