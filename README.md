# Weather Market Platform

Research, collection, model validation, and operations tooling for Polymarket
daily high-temperature markets. The platform ingests Weather.com/Wunderground
settlement-proxy history, live observations, forecasts, Polymarket market data,
CLOB order books, and model artifacts, then serves probability distributions and
operator health views in a Streamlit dashboard.

This is no longer a Toronto-only project. Toronto remains the canonical Celsius
market, while the built-in registry also supports eleven Fahrenheit U.S.
markets:

| Market ID | Display name | Unit | Settlement/live station | Timezone |
| --- | --- | --- | --- | --- |
| `toronto` | Toronto | C | `CYYZ` | `America/Toronto` |
| `nyc` | NYC | F | `KLGA` | `America/New_York` |
| `atlanta` | Atlanta | F | `KATL` | `America/New_York` |
| `austin` | Austin | F | `KAUS` | `America/Chicago` |
| `chicago` | Chicago | F | `KORD` | `America/Chicago` |
| `dallas` | Dallas | F | `KDAL` | `America/Chicago` |
| `denver` | Denver | F | `KBKF` | `America/Denver` |
| `houston` | Houston | F | `KHOU` | `America/Chicago` |
| `los-angeles` | Los Angeles | F | `KLAX` | `America/Los_Angeles` |
| `miami` | Miami | F | `KMIA` | `America/New_York` |
| `san-francisco` | San Francisco | F | `KSFO` | `America/Los_Angeles` |
| `seattle` | Seattle | F | `KSEA` | `America/Los_Angeles` |

Market settlement is modeled as the highest whole-degree value printed by the
configured Weather.com/Wunderground history source for the market's local target
date. Supporting sources such as METAR/ASOS, ECCC, NWS, Open-Meteo, reanalysis,
marine context, and current Weather.com observations are signals; they are not
hard settlement truth unless the code explicitly labels them as settlement
evidence.

## Setup

Requires Python 3.11+ on Windows.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip install -e .
```

`requirements.txt` and `pyproject.toml` intentionally pin the same direct
dependencies. `scikit-learn` is pinned exactly because the tracked
HistGradientBoosting artifacts under `artifacts/models/hgb/` are pickled sklearn
models and can fail to unpickle across sklearn versions.

## Run The Dashboard

Canonical Streamlit entrypoint:

```powershell
.\venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

The root `app.py` shim still works for compatibility:

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

The operator launcher starts Streamlit if needed, opens the Operations page, and
writes Streamlit logs under `data/logs/`:

```powershell
.\scripts\launch\start_weather_dashboard.cmd
```

Useful dashboard query targets:

```text
http://localhost:8501/?market=overview
http://localhost:8501/?market=toronto
http://localhost:8501/?market=ops
http://localhost:8501/?market=mm
http://localhost:8501/?history
http://localhost:8501/?roadmap
```

The dashboard views are overview, per-market detail, history, market making,
operations, and roadmap.

## Tests And Local Checks

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app src tests
```

`pytest.ini` sets `pythonpath = src` and limits collection to `tests/`.
Ad-hoc live scripts under `scratch/` are intentionally outside the test suite.

## Configuration

Checked-in configuration lives under `config/`.

| File | Role |
| --- | --- |
| `config/locations.json` | Durable location, station, settlement, source-plan, and Polymarket series facts. |
| `config/location_market_events.json` | Generated Gamma event metadata for configured locations. Refresh it, do not hand-edit it. |
| `config/markets.json` | Deprecated external-override compatibility shell. The built-in `MarketSpec` definitions in `src/weather/market/market_registry.py` are authoritative unless `WEATHER_MARKET_REGISTRY` points elsewhere. |
| `config/model_variant_registry.json` | Model-variant lifecycle, artifact, and promotion registry. |
| `config/supplemental_stations.json` | Supplemental station provenance and validation registry. |
| `config/no_market_extra_locations.json` | Shadow-lane registry for non-market training candidates; active entries require backfilled evidence. |

Refresh generated market-event metadata and audit config freshness:

```powershell
.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json
.\venv\Scripts\python.exe -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

Environment variables used by operator-facing code:

| Env var | Purpose |
| --- | --- |
| `TORONTO_MARKET_DATE` | Legacy-named target-date override, ISO `YYYY-MM-DD`. Applies to registered markets that use the default date resolver; otherwise defaults to today's date in the market timezone. Restart long-running loops after changing it. |
| `WEATHER_COM_API_KEY` | Weather.com API key. Defaults to the public browser key baked into the code. |
| `WEATHER_MARKET_REGISTRY` | Optional path to an external market registry override. |
| `SETTLEMENT_LEDGER_ROOT` | Optional root for settlement ledgers; defaults to `data/settlements/`. |
| `WEATHER_TAPE_BACKUP_ROOT` | Optional tape-backup destination; can also be passed with `--backup-root`. |
| `WEATHER_DISABLE_STAY_AWAKE` | Set to `1` to disable Windows stay-awake requests in long-running loops. |
| `WEATHER_ALLOW_CONSOLE_CHILDREN` | Set to `1` to allow visible console child processes on Windows background workers. |

## Core Commands

Run commands from the repository root with the venv interpreter.

### Registry, History, And Source Data

```powershell
# Wunderground/Weather.com settlement-proxy history.
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto backfill --start 2015-01-01 --end 2026-06-22 --skip-existing --continue-on-error
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto audit

# METAR/ASOS redundant observation history.
.\venv\Scripts\python.exe -m weather.sources.metar_history --market toronto backfill --start 2026-06-01 --end 2026-06-22 --skip-existing

# Open-Meteo ERA5-style reanalysis history.
.\venv\Scripts\python.exe -m weather.sources.reanalysis_history --market toronto backfill --start 2026-06-01 --end 2026-06-22

# Toronto-only ECCC SWOB observation layer.
.\venv\Scripts\python.exe -m weather.sources.eccc_swob_history run

# Build or run a resumable multi-source backfill queue.
.\venv\Scripts\python.exe -m weather.collection.historical_backfill_plan --markets all --scope minimum --dry-run
.\venv\Scripts\python.exe -m weather.collection.historical_backfill_runner run --max-items 0

# Forecast archive utilities.
.\venv\Scripts\python.exe -m weather.collection.forecast_archive analyze <snapshot-folder>
```

### Live Collection Loops

```powershell
# Multi-market model/market snapshots. One-shot defaults to Toronto; loop mode
# captures every registered market each tick and isolates per-market failures.
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --loop --interval-minutes 10
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --restart
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --stop
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --ensure

# Fast Polymarket CLOB capture. Keep this separate from the weather/model loop.
.\venv\Scripts\python.exe -m weather.market.market_microstructure capture --market toronto
.\venv\Scripts\python.exe -m weather.market.market_microstructure loop --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict
.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m weather.market.market_microstructure stop
.\venv\Scripts\python.exe -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m weather.market.market_microstructure websocket --market toronto --seconds 300

# Fast observation-triggered recompute watcher.
.\venv\Scripts\python.exe -m weather.operations.observation_trigger once --market all
.\venv\Scripts\python.exe -m weather.operations.observation_trigger loop --market all --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.operations.observation_trigger restart --market all --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.observation_trigger stop
.\venv\Scripts\python.exe -m weather.operations.observation_trigger ensure --market all --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.observation_trigger replay
```

### Settlement, Reporting, And Promotion

```powershell
.\venv\Scripts\python.exe -m weather.market.market_day_labels finalize
.\venv\Scripts\python.exe -m weather.reporting.promotion_refresh
.\venv\Scripts\python.exe -m weather.reporting.snapshot_evaluation
.\venv\Scripts\python.exe -m weather.reporting.daily_learning
.\venv\Scripts\python.exe -m weather.operations.daily_refresh run --continue-on-error --fail-on-variant-evidence-alert
.\venv\Scripts\python.exe -m weather.operations.daily_refresh status
.\venv\Scripts\python.exe -m weather.operations.nightly_retrain run --dry-run
.\venv\Scripts\python.exe -m weather.operations.nightly_retrain status
```

`daily_refresh` is the morning settlement-to-reporting chain. It can finalize
settlement labels, run taker finalization checks, refresh trading/model evidence,
run promotion and shadow monitors, audit fleet/data health, refresh learning
reports, and write `data/backtest/daily_refresh_status.json` plus
`data/backtest/daily_refresh_report.md`.

`nightly_retrain` is the overnight self-improvement job. It refreshes daily
learning, retrains/validates candidate artifacts, refreshes artifact registries
and promotion decisions, and writes `data/backtest/nightly_retrain_status.json`
plus `data/backtest/nightly_retrain_report.md`.

### Backtests, Audits, And Model Training

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.backtest
.\venv\Scripts\python.exe -m weather.backtesting.snapshot_analytics
.\venv\Scripts\python.exe -m weather.collection.collection_health
.\venv\Scripts\python.exe -m weather.collection.collection_health --fleet --live --strict --json
.\venv\Scripts\python.exe -m weather.reporting.fleet_observability report --strict
.\venv\Scripts\python.exe -m weather.reporting.data_layer_audit
.\venv\Scripts\python.exe -m weather.reporting.source_redundancy report --start 2026-06-01 --end 2026-06-22
.\venv\Scripts\python.exe -m weather.reporting.data_auditor
.\venv\Scripts\python.exe -m weather.reporting.data_auditor --fleet --json --strict
.\venv\Scripts\python.exe -m weather.calibration.feature_model --market toronto
.\venv\Scripts\python.exe -m weather.calibration.feature_model --market nyc --skip-loo
.\venv\Scripts\python.exe -m weather.calibration.intraday_calibration
.\venv\Scripts\python.exe -m weather.artifacts size-audit
```

`weather.calibration.feature_model` trains one market/unit-family at a time.
Use `--market toronto` for Celsius artifacts and an F-market such as `nyc` for
F-family artifacts. The root `train_all_markets.ps1` helper is a compatibility
wrapper, not the canonical training interface.

### Trading Simulations

```powershell
# Keyless market-making operator run.
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-22 --budget-usdc 500 --mode shadow --markets all
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-22 --budget-usdc 500 --mode paper-live-forward --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper

# Paper taker-bot simulator.
.\venv\Scripts\python.exe -m weather.market.taker_bot_cli --date 2026-06-22 --budget-usdc 100 --markets all --loop --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.operations.taker_bot_daily_roll status
```

Live order modes have additional readiness gates and confirmation flags. Keep
normal development and research runs in `shadow` or `paper-live-forward`.

## Scheduled Operations

Register scheduled tasks from the repository root after setup. Re-running a
registration script replaces the existing task.

```powershell
.\scripts\ops\register_snapshot_supervisor.ps1
.\scripts\ops\register_clob_supervisor.ps1
.\scripts\ops\register_observation_trigger_supervisor.ps1
.\scripts\ops\register_daily_refresh.ps1
.\scripts\ops\register_nightly_retrain.ps1
.\scripts\ops\register_market_making_daily_roll.ps1
.\scripts\ops\register_taker_bot_daily_roll.ps1
.\scripts\ops\register_tape_backup.ps1
```

Default scheduled behavior:

| Task | Registration script | Default cadence |
| --- | --- | --- |
| `WeatherSnapshotLoopSupervisor` | `register_snapshot_supervisor.ps1` | `snapshot_tracker --ensure` every 2 minutes and at logon; managed capture loop defaults to 10-minute ticks. |
| `WeatherClobBookLoopSupervisor` | `register_clob_supervisor.ps1` | `market_microstructure ensure` every minute and at logon. |
| `WeatherObservationTriggerSupervisor` | `register_observation_trigger_supervisor.ps1` | `observation_trigger ensure` every minute and at logon. |
| `WeatherDailySettlementPromotionRefresh` | `register_daily_refresh.ps1` | Daily at 09:30. |
| `WeatherNightlyRetrainValidatePromote` | `register_nightly_retrain.ps1` | Daily at 03:30. |
| `WeatherMarketMakingDailyRoll` | `register_market_making_daily_roll.ps1` | Daily at 19:30 in `America/Toronto`. |
| `WeatherTakerBotDailyRoll` | `register_taker_bot_daily_roll.ps1` | Daily at 00:05 in `America/Toronto`. |
| `WeatherTapeBackupAndRestoreDrill` | `register_tape_backup.ps1` | Daily at 02:15. |

The Operations dashboard can inspect and control the supervised loops. CLI
status commands are still the fastest sanity checks:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.operations.daily_refresh status
.\venv\Scripts\python.exe -m weather.operations.nightly_retrain status
.\venv\Scripts\python.exe -m weather.operations.tape_backup status
```

Tape backup should write to storage outside the working checkout. Example:

```powershell
$env:WEATHER_TAPE_BACKUP_ROOT = "E:\weather-tape-backups"
.\venv\Scripts\python.exe -m weather.operations.tape_backup run --backup-root $env:WEATHER_TAPE_BACKUP_ROOT --verify-checksums
.\venv\Scripts\python.exe -m weather.operations.tape_backup restore-drill --backup-root $env:WEATHER_TAPE_BACKUP_ROOT
```

## Data Layout

`data/` is local runtime/cache/output state and is git-ignored.

```text
data/
  wunderground/<station>/       # settlement-proxy raw/hourly/daily history
  metar/<station>/              # METAR/ASOS redundant observations
  eccc_swob/cyyz/               # Toronto official SWOB observations
  forecast_history/             # archived forecast daily features
  snapshots/
    loop_status.json
    diagnostics.jsonl
    clob_loop_status.json
    clob_diagnostics.jsonl
    observation_trigger_status.json
    observation_triggers.jsonl
    <event-slug>/
      snapshots_long.csv
      snapshots.jsonl
      replay_inputs.jsonl
      source_status_long.csv
      forecasts_long.csv
      forecast_payloads_long.csv
      forecast_payloads/*.json
      features_long.csv
      components_long.csv
      clob_tokens.csv
      order_books_summary.csv
      order_books_long.csv
      order_books.jsonl
      price_history.csv
      market_ws_events.csv
      market_ws.jsonl
  backtest/                     # reports, scoring outputs, promotion payloads
  settlements/<market-id>/      # settlement ledgers
  mm_runs/                      # market-making run folders
  taker_runs/                   # taker-bot run folders
  tape_backups/                 # default local tape-backup root if not overridden
```

Durable model artifacts are tracked under `artifacts/`. Small deterministic
fixtures live under `tests/fixtures/`. Runtime outputs should graduate out of
`data/` only by explicit decision:

- trained model state, calibration artifacts, and artifact manifests go to
  `artifacts/`;
- small deterministic test inputs go to `tests/fixtures/`;
- human-readable reports that should become project history go to `docs/`;
- caches, raw provider payloads, live tapes, loop status, regenerated reports,
  and local backtest outputs stay under `data/`.

Artifact growth is guarded by:

```powershell
.\venv\Scripts\python.exe -m weather.artifacts size-audit
```

See [docs/operations/artifact-storage-policy.md](docs/operations/artifact-storage-policy.md).

## Source Layout

```text
app/                  # Streamlit router, views, and table helpers
src/weather/          # Packaged source code and canonical module entrypoints
config/               # checked-in registries and generated event metadata
artifacts/            # tracked model, calibration, and artifact manifests
scripts/launch/       # human dashboard launchers
scripts/ops/          # Windows Task Scheduler registration scripts
tools/                # local helpers and research scripts
docs/                 # operations, research, roadmap, and audit docs
tests/                # unit, reporting, operations, market, model, source tests
tests/fixtures/       # small deterministic fixture data
weather/__init__.py   # repo-root import compatibility shim
app.py                # Streamlit compatibility shim
```

Canonical commands run through packaged `weather.*` modules. Legacy flat
wrappers and root shims remain available for compatibility, but active runbooks
and new docs should use `python -m weather...`.

## Documentation

- [docs/operations/OPERATIONS_DESIGN.md](docs/operations/OPERATIONS_DESIGN.md) -
  durable loop, dashboard, and Task Scheduler design.
- [docs/operations/HISTORY_DATA_DESIGN.md](docs/operations/HISTORY_DATA_DESIGN.md) -
  Wunderground/Weather.com history data layer.
- [docs/operations/config-inventory.md](docs/operations/config-inventory.md) -
  config ownership and freshness policy.
- [docs/operations/path-policy.md](docs/operations/path-policy.md) -
  repository path and import policy.
- [docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md](docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md) -
  nightly retrain/validate/promote runbook.
- [docs/operations/TAPE_BACKUP_RUNBOOK.md](docs/operations/TAPE_BACKUP_RUNBOOK.md) -
  irreplaceable tape backup and restore drill runbook.
- [docs/roadmap/ROADMAP.md](docs/roadmap/ROADMAP.md) - roadmap index, item
  links, and maintenance conventions.
- [docs/roadmap/project-structure-audit-2026-06-22.md](docs/roadmap/project-structure-audit-2026-06-22.md) -
  current source-layout and project-structure audit.
