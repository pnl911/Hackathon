# Setup and troubleshooting

## Setup

1. **Python 3.10+** and a virtual environment:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. **Input files** in the same folder as the scripts: `MMG2025*.xlsx`, `MMG2026*.xlsx`, `snap-households*.xlsx`.
3. **Keys** (optional): copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   FRED_API_KEY = "your-32-character-key"
   ```
   - Claude key: platform.claude.com → Settings → API keys (the account needs credit; this is separate from a Claude.ai subscription).
   - FRED key: fredaccount.stlouisfed.org → API Keys (free).
   - Safest way to write the file on Windows (avoids hidden characters):
     ```powershell
     New-Item -ItemType Directory -Force .streamlit
     [System.IO.File]::WriteAllText("$PWD\.streamlit\secrets.toml", "ANTHROPIC_API_KEY = `"sk-ant-...`"`nFRED_API_KEY = `"...`"")
     ```
4. **Run:** `python demand_forecast_us.py`, then `streamlit run app.py`, both from the project folder.

## Before a demo
- Run the forecast and open all three views once **while online** (caches FRED data).
- Confirm the AI page says **"Claude is connected"** and generate one plan.
- Keep screenshots and a downloaded PDF as a backup.
- Never display `secrets.toml` on screen.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FileNotFoundError: MMG2025...xlsx` | Input files not in the folder you run from | Move them next to the script; run `dir *.xlsx` to check. The script lists the Excel files it can see |
| Script seems stuck | Fitting ~130 models takes 1-3 minutes | Watch the timestamped progress lines |
| `Importing plotly failed` | Prophet's optional plots | Harmless; `pip install plotly` to hide it |
| Prophet / `cmdstanpy` / Stan errors | Install problem (often Windows) | `pip install --upgrade prophet cmdstanpy` |
| "Forecast files not found" in the app | Forecast not run, or run from another folder | Run `python demand_forecast_us.py` in the app's folder |
| `include_groups` error | Old pandas with an older app version | Use the current `app.py` or upgrade pandas |
| Error mentioning `width` | Old Streamlit | `pip install --upgrade streamlit` |
| "Claude isn't connected" | Key not found or unreadable | Open **"Why isn't Claude connected?"** on the AI page. Check: folder is `.streamlit` (with the dot) next to `app.py`; file is `secrets.toml`, not `secrets.toml.txt`; the key is complete. Restart the app (Ctrl + C, run again) |
| Caption says `rules (AI unavailable: API error 401)` | Wrong or deleted key | Create a new key and update `secrets.toml` |
| `API error 400` mentioning credit/billing | No API credit | Add credit in the Claude Console |
| `API error 404` mentioning model | Model name changed | Update `MODEL` in `strategist.py` |
| "Economic factors: off" | No FRED key, or the forecast wasn't rerun after adding it | Add `FRED_API_KEY`, then rerun the forecast; look for "Economic factors ON" in its log |
| "Shown live from FRED. Run python demand_forecast_us.py..." | Key found but the forecast ran without FRED | Rerun the forecast so the model uses the economic inputs |
| "FRED key found, but no data could be downloaded" | Offline or FRED unreachable, and no cache | Connect to the internet and rerun |
| PDF button shows a reportlab warning | Library missing | `pip install reportlab` and restart |

## Security checklist
- `.streamlit/secrets.toml` is in `.gitignore`; never commit or screenshot it.
- Keys pasted into chats, emails, or screenshots should be deleted and replaced.
- After the event, delete demo keys in the Claude Console and FRED account.
