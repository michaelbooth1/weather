# Toronto Weather Market

Projects the settlement of Polymarket **"highest temperature in Toronto on
&lt;date&gt;"** markets for Toronto Pearson (CYYZ). It pulls live weather from
several sources, blends an empirical climatology prior with a feature-based ML
model, and surfaces the model's bucket distribution against live market prices
in a Streamlit dashboard. Market resolution is modeled as the highest
whole-degree Celsius value that Wunderground/Weather.com history prints for
CYYZ on the target date.

## Setup

Requires Python 3.11+.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

`scikit-learn` is pinned exactly because `src/feature_model_hgb.pkl` is a
pickled model and will not unpickle across versions.

## Run the dashboard

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

The dashboard auto-selects today's Toronto market. Override the target date
with the `TORONTO_MARKET_DATE` env var (ISO format, e.g. `2026-05-29`).

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Configuration

| Env var | Purpose |
| --- | --- |
| `TORONTO_MARKET_DATE` | Override the target market date (ISO `YYYY-MM-DD`). Defaults to today in America/Toronto. |
| `WEATHER_COM_API_KEY` | Weather.com API key. Defaults to the public browser key. |

## Command-line tools

All run from the repo root with the venv interpreter:

```powershell
# Wunderground/Weather.com history: collect, rebuild, audit, climatology
.\venv\Scripts\python.exe -m src.wu_history backfill --start 2015-01-01 --end 2026-05-27
.\venv\Scripts\python.exe -m src.wu_history audit

# ECCC SWOB observation layer
.\venv\Scripts\python.exe -m src.eccc_swob_history run

# Forecast archive (migrate schema, backfill ECCC, learn source bias)
.\venv\Scripts\python.exe -m src.forecast_archive analyze <snapshot-folder>

# Capture snapshots: one-shot, or a crash-proof managed loop with heartbeat
.\venv\Scripts\python.exe -m src.snapshot_tracker --force
.\venv\Scripts\python.exe -m src.snapshot_tracker --loop --interval-minutes 10
.\venv\Scripts\python.exe -m src.snapshot_tracker --status   # is the loop alive?
.\venv\Scripts\python.exe -m src.snapshot_tracker --restart  # deploy new code to the loop
.\venv\Scripts\python.exe -m src.snapshot_tracker --stop     # terminate the managed loop
.\venv\Scripts\python.exe -m src.snapshot_tracker --ensure   # supervisor check (Task Scheduler runs this)

# Fast Polymarket CLOB capture: keep this separate from the weather/model loop
.\venv\Scripts\python.exe -m src.market_microstructure capture --market toronto --price-history
.\venv\Scripts\python.exe -m src.market_microstructure loop --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m src.market_microstructure status
.\venv\Scripts\python.exe -m src.market_microstructure restart --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m src.market_microstructure stop
.\venv\Scripts\python.exe -m src.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m src.market_microstructure websocket --market toronto --seconds 300

# Collection health and fleet observability
.\venv\Scripts\python.exe -m src.collection_health
.\venv\Scripts\python.exe -m src.collection_health --fleet --live --strict --json
.\venv\Scripts\python.exe -m src.fleet_observability report --strict
.\venv\Scripts\python.exe -m src.data_layer_audit
.\venv\Scripts\python.exe -m src.source_redundancy report --start 2026-06-01 --end 2026-06-12
.\venv\Scripts\python.exe -m src.metar_history --market toronto backfill --start 2026-06-01 --end 2026-06-12 --skip-existing

# Settlement labels and promotion refresh
.\venv\Scripts\python.exe -m src.market_day_labels finalize
.\venv\Scripts\python.exe -m src.promotion_refresh

# Settlement-scored backtest: model vs market edge on captured days
.\venv\Scripts\python.exe -m src.backtest

# Analytics over a snapshot tape
.\venv\Scripts\python.exe -m src.snapshot_analytics

# Calibrate empirical intraday blend weights
.\venv\Scripts\python.exe -m src.intraday_calibration

# Train the feature model + late-day continuation models (with LOO + calibration)
.\venv\Scripts\python.exe src\feature_model.py

# Data-quality audit (missing/sparse days, duplicates, impossible values)
.\venv\Scripts\python.exe src\data_auditor.py
.\venv\Scripts\python.exe src\data_auditor.py --fleet --json --strict
```

For resilient collection, register the supervisor scheduled tasks once:

```powershell
.\scripts\register_snapshot_supervisor.ps1
.\scripts\register_clob_supervisor.ps1
```

Task Scheduler then runs `snapshot_tracker --ensure` every 10 minutes and at
logon. `--ensure` keeps exactly one healthy detached loop alive: it no-ops on a
fresh heartbeat, starts the loop after a silent death or reboot, and
kills-and-restarts a hung process (live PID, stale heartbeat). To deploy new
code to the loop use `--restart`; to stop collection on purpose, disable the
task and run `--stop` (the pause flag alone keeps the process alive). The loop
survives transient capture errors itself; `--status` (heartbeat-based) shows
its health, `diagnostics.jsonl` records every iteration and supervisor action,
and the loop's console output goes to `data/snapshots/loop_console.log`.
The CLOB task runs `src.market_microstructure ensure` every minute, supervises a
separate fast book loop, writes `clob_loop_status.json` and
`clob_diagnostics.jsonl`, and keeps missing order-book history from becoming a
silent data-loss event.

## Data layout

```text
data/
  wunderground/cyyz/   # settlement-proxy history (raw/, hourly/, daily/, manifest)
  eccc_swob/cyyz/      # official station observations (non-resolution)
  metar/<icao>/        # METAR/ASOS redundant observations (raw/, hourly/, daily/, manifest)
  snapshots/clob_loop_status.json
  snapshots/clob_diagnostics.jsonl
  snapshots/clob_loop_console.log
  snapshots/<slug>/    # per-market odds + forecast tapes and analytics
    clob_tokens.csv/jsonl
    order_books_summary.csv
    order_books_long.csv
    order_books.jsonl
    price_history.csv/jsonl
    market_ws_events.csv
    market_ws.jsonl
```

Raw provider payloads (`data/**/raw/`) are regenerable and git-ignored; the
normalized `hourly/` and `daily/` artifacts are tracked.

## Documentation

- [ROADMAP.md](ROADMAP.md) — feature roadmap and audit history.
- [HISTORY_DATA_DESIGN.md](HISTORY_DATA_DESIGN.md) — the Wunderground history data layer.
