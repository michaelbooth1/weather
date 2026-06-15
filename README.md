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

`scikit-learn` is pinned exactly because the tracked HGB artifacts under
`artifacts/models/hgb/` are pickled sklearn models and will not unpickle across
versions.

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

# Fast Polymarket CLOB capture: keep this separate from the weather/model loop.
# Price history and short WebSocket event capture are on by default; use
# --no-price-history or --no-websocket-events only for emergency throttling.
.\venv\Scripts\python.exe -m src.market_microstructure capture --market toronto
.\venv\Scripts\python.exe -m src.market_microstructure loop --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m src.market_microstructure status
.\venv\Scripts\python.exe -m src.market_microstructure audit --strict   # book-tape cadence acceptance check
.\venv\Scripts\python.exe -m src.market_microstructure restart --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m src.market_microstructure stop
.\venv\Scripts\python.exe -m src.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m src.market_microstructure websocket --market toronto --seconds 300  # manual long recorder

# Fast observation-triggered recompute: low-cost WU/current/METAR/SWOB watcher
.\venv\Scripts\python.exe -m src.observation_trigger once --market all
.\venv\Scripts\python.exe -m src.observation_trigger loop --market all --interval-seconds 60
.\venv\Scripts\python.exe -m src.observation_trigger status
.\venv\Scripts\python.exe -m src.observation_trigger ensure --market all --interval-seconds 60
.\venv\Scripts\python.exe -m src.observation_trigger replay

# Keyless market-making operator run: target date + total risk budget
.\venv\Scripts\python.exe -m src.market_making_run --date 2026-06-15 --budget-usdc 500 --mode shadow
.\venv\Scripts\python.exe -m src.market_making_run --date 2026-06-15 --budget-usdc 500 --mode paper-live-forward --once
.\venv\Scripts\python.exe -m src.mm_paper

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
.\venv\Scripts\python.exe -m src.daily_refresh run --continue-on-error
.\venv\Scripts\python.exe -m src.daily_refresh status

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
.\scripts\register_observation_trigger_supervisor.ps1
.\scripts\register_daily_refresh.ps1
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
The observation-trigger task runs `src.observation_trigger ensure` every minute,
supervises a low-cost 60-second observation watcher, and forces tagged
`snapshot_cadence=triggered` recomputes when WU current/history, METAR, or SWOB
changes settlement-relevant state. It writes
`data/snapshots/observation_trigger_status.json`,
`data/snapshots/observation_triggers.jsonl`, and the WU-lag scoring artifacts
under `data/backtest/observation_trigger_replay*`.
The daily refresh task runs `src.daily_refresh run --continue-on-error` once per
morning by default. It first retries the recent reanalysis archive-lag window
(`--skip-reanalysis-refresh` disables that), then executes
`market_day_labels finalize`, `promotion_refresh`, `progress_audit`,
`disagreement_casebook`, `fleet_observability`, and `data_layer_audit` in order,
and writes `data/backtest/daily_refresh_status.json`,
`data/backtest/daily_refresh_report.md`, `data/backtest/data_layer_audit.json`,
and `data/backtest/data_layer_audit_report.md`. Use
`--fail-on-data-layer-audit` when failed audit gates should mark the daily run
critical.

For the operator dashboard, use the clickable launcher:

```powershell
.\scripts\start_weather_dashboard.cmd
```

It starts Streamlit if needed and opens `http://localhost:8501/?market=ops`.
The `Operations` page can start/repair, restart, stop, pause, and resume the
managed loops; it also compares each loop's running `runtime_identity` against the
current checkout so stale code is visible before it becomes a data-quality
surprise. The durable design is documented in
[docs/operations/OPERATIONS_DESIGN.md](docs/operations/OPERATIONS_DESIGN.md).

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
    source_status_long.csv/jsonl
    forecasts_long.csv/jsonl
    forecast_payloads_long.csv/jsonl
    forecast_payloads/*.json
    features_long.csv/jsonl
    components_long.csv/jsonl
    replay_input_status_long.csv
    replay_input_status.json
    clob_tokens.csv/jsonl
    order_books_summary.csv
    order_books_long.csv
    order_books.jsonl
    price_history.csv/jsonl
    market_ws_events.csv
    market_ws.jsonl
```

`data/` is local runtime/cache/output state and is git-ignored. Durable model
artifacts are tracked under `artifacts/`; small deterministic smoke fixtures
live under `tests/fixtures/`.

## Source layout

```text
app/                 # Streamlit application implementation
src/weather/         # Packaged source code
artifacts/           # Tracked model and calibration artifacts
tools/               # Reusable local helpers and research scripts
scripts/             # Launch and supervisor wrappers
docs/                # Operations, research, and roadmap docs
tests/fixtures/      # Small deterministic fixture data
```

Historical imports and commands such as `python -m src.snapshot_tracker` still
work through compatibility wrappers in `src/`.

## Documentation

- [docs/roadmap/ROADMAP.md](docs/roadmap/ROADMAP.md) - feature roadmap and audit history.
- [docs/operations/HISTORY_DATA_DESIGN.md](docs/operations/HISTORY_DATA_DESIGN.md) - the Wunderground history data layer.
- [docs/roadmap/codebase-organization-audit.md](docs/roadmap/codebase-organization-audit.md) - file and folder organization audit.
