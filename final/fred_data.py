"""
PantryPulse - FRED (Federal Reserve Economic Data) connector
------------------------------------------------------------
Reads FRED_API_KEY from .streamlit/secrets.toml (or the FRED_API_KEY environment variable),
downloads series from the FRED API, and caches them in outputs/fred_cache/ so the dashboard
still works offline (for example during a demo without wifi).

Add more indicators by adding an entry to INDICATORS.
"""
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://api.stlouisfed.org/fred"
CACHE = Path("outputs/fred_cache")
CACHE_HOURS = 12

# id: display settings. "transform": how the headline number is calculated
#   "yoy_pct" = % change vs one year earlier (for levels like GDP, CPI, spending)
#   "level"   = the value itself (for series already in %)
INDICATORS = {
    "GDPC1": {"name": "Real GDP", "short": "Real GDP growth", "transform": "yoy_pct", "periods_per_year": 4,
              "why": "Overall economy. When growth slows or turns negative (recession), job losses follow "
                     "and food bank demand rises."},
    "CPIAUCSL": {"name": "Consumer Price Index (all items)", "short": "Inflation (CPI, monthly)",
                 "transform": "yoy_pct", "periods_per_year": 12,
                 "why": "Cost of living. Higher inflation squeezes household budgets, pushing more families "
                        "toward food assistance, and raises what food banks pay for food."},
    "FPCPITOTLZGUSA": {"name": "Inflation, consumer prices (annual %)", "short": "Inflation (annual)",
                       "transform": "level", "periods_per_year": 1,
                       "why": "Long-run view of inflation (World Bank, yearly). Useful for comparing this year "
                              "with past years."},
    "PCE": {"name": "Personal Consumption Expenditures", "short": "Consumer spending growth",
            "transform": "yoy_pct", "periods_per_year": 12,
            "why": "Household spending. A slowdown often signals financial stress before it shows up "
                   "at the pantry."},
    "UNRATE": {"name": "Unemployment Rate", "short": "Unemployment",
               "transform": "level", "periods_per_year": 12,
               "why": "Job market health. Higher unemployment increases demand for food assistance."},
}


# ---------------------------------------------------------------- key
def fred_key():
    k = os.environ.get("FRED_API_KEY", "")
    if re.fullmatch(r"[A-Za-z0-9]{32}", k.strip()):
        return k.strip()
    try:
        import streamlit as st
        if "FRED_API_KEY" in st.secrets:
            m = re.search(r"[A-Za-z0-9]{32}", str(st.secrets["FRED_API_KEY"]))
            if m:
                return m.group(0)
    except Exception:
        pass
    for folder in (Path(__file__).resolve().parent, Path.cwd(), Path(__file__).resolve().parent.parent):
        f = folder / ".streamlit" / "secrets.toml"
        if not f.exists():
            continue
        raw, text = f.read_bytes(), ""
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(enc)
                if "\x00" not in text:
                    break
            except UnicodeError:
                continue
        for line in text.splitlines():
            if "FRED_API_KEY" in line and "=" in line:
                m = re.search(r"[A-Za-z0-9]{32}", line.split("=", 1)[1])
                if m:
                    return m.group(0)
    return None


# ---------------------------------------------------------------- data
def _fresh(path):
    return path.exists() and (time.time() - path.stat().st_mtime) < CACHE_HOURS * 3600


def get_series(series_id, start="2010-01-01"):
    """Returns (pandas Series indexed by date, source) where source is 'FRED (live)', 'cache' or None."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{series_id}.csv"
    key = fred_key()
    if key and not _fresh(cache):
        try:
            r = requests.get(f"{API}/series/observations", timeout=20,
                             params={"series_id": series_id, "api_key": key, "file_type": "json",
                                     "observation_start": start})
            r.raise_for_status()
            obs = pd.DataFrame(r.json()["observations"])[["date", "value"]]
            obs["value"] = pd.to_numeric(obs["value"], errors="coerce")
            obs.dropna().to_csv(cache, index=False)
            src = "FRED (live)"
        except Exception:
            src = "cache" if cache.exists() else None
    else:
        src = "FRED (live)" if cache.exists() and key else ("cache" if cache.exists() else None)
    if not cache.exists():
        return None, None
    s = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["value"].sort_index()
    return s[s.index >= pd.Timestamp(start)], src


def get_info(series_id):
    """Official title, units, frequency and last update from FRED (cached). Falls back to our labels."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{series_id}_info.json"
    key = fred_key()
    if key and not _fresh(cache):
        try:
            r = requests.get(f"{API}/series", timeout=20,
                             params={"series_id": series_id, "api_key": key, "file_type": "json"})
            r.raise_for_status()
            cache.write_text(pd.Series(r.json()["seriess"][0]).to_json())
        except Exception:
            pass
    if cache.exists():
        return pd.read_json(cache, typ="series").to_dict()
    return {"title": INDICATORS.get(series_id, {}).get("name", series_id), "units": "", "frequency": ""}


def transformed(series_id, s):
    cfg = INDICATORS[series_id]
    if cfg["transform"] == "yoy_pct":
        return (s.pct_change(cfg["periods_per_year"]) * 100).dropna()
    return s.dropna()


def summary(series_id):
    """Headline numbers for one indicator (None if no data)."""
    raw, src = get_series(series_id)
    if raw is None or raw.empty:
        return None
    cfg, info = INDICATORS[series_id], get_info(series_id)
    t = transformed(series_id, raw)
    if t.empty:
        return None
    latest, prev = t.iloc[-1], (t.iloc[-2] if len(t) > 1 else None)
    return {"id": series_id, "name": cfg["name"], "short": cfg["short"], "why": cfg["why"],
            "title": info.get("title", cfg["name"]), "units": info.get("units", ""),
            "frequency": info.get("frequency", ""), "last_updated": str(info.get("last_updated", ""))[:10],
            "latest_value": round(float(latest), 2), "latest_date": t.index[-1].strftime("%Y-%m-%d"),
            "change_vs_previous": round(float(latest - prev), 2) if prev is not None else None,
            "raw_latest": round(float(raw.iloc[-1]), 2), "is_percent": True,
            "link": f"https://fred.stlouisfed.org/series/{series_id}", "source": src,
            "series": t, "raw_series": raw}


def all_summaries():
    return {sid: summary(sid) for sid in INDICATORS}


def facts_for_ai(summaries):
    """Compact version for Claude (no long series)."""
    out = {}
    for sid, s in summaries.items():
        if s:
            out[s["short"]] = {"value_percent": s["latest_value"], "as_of": s["latest_date"],
                               "change_vs_previous_period": s["change_vs_previous"], "fred_series": sid}
    return out


def state_macro(state):
    """Live state unemployment + grocery price inflation (same format the forecast script saves).
    Used by the dashboard when outputs/macro_state_latest.csv doesn't exist yet."""
    u, _ = get_series(f"{state}UR", start="2015-01-01")
    f, _ = get_series("CUSR0000SAF11", start="2015-01-01")
    if u is None or u.empty or f is None or f.empty:
        return None
    food_yoy = (f.pct_change(12) * 100).dropna()
    year_ago = u.asof(u.index[-1] - pd.DateOffset(years=1))
    return {"unemployment_rate": round(float(u.iloc[-1]), 1),
            "unemployment_as_of": u.index[-1].strftime("%Y-%m"),
            "unemployment_change_1yr": round(float(u.iloc[-1] - year_ago), 1),
            "food_price_inflation_yoy": round(float(food_yoy.iloc[-1]), 1),
            "food_prices_as_of": food_yoy.index[-1].strftime("%Y-%m"),
            "used_national_unemployment": False,
            "in_forecast": False}
