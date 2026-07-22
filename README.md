# Weather Market Platform

Coding agents should start with [AGENTS.md](AGENTS.md) and load task-specific
context through the [documentation map](docs/README.md).

Research, collection, model validation, and operations tooling for Polymarket
daily high-temperature markets. The platform ingests local Weather Underground
settlement-proxy history, free live observations, forecasts, Polymarket market
data, CLOB order books, and model artifacts, then serves probability
distributions and operator health views in a Streamlit dashboard.

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
configured Weather Underground history source for the market's local target
date. Supporting sources such as METAR/ASOS, ECCC, NWS, Open-Meteo, reanalysis,
and marine context are signals; they are not hard settlement truth unless the
code explicitly labels them as settlement evidence.

Paid-provider weather access is not a supported operating path for this repo.
Do not add credentials, env vars, paid-provider fetch commands, or roadmap
recommendations that depend on paid-provider access. WU settlement labels must
come from existing local `data/wunderground/<station>/` artifacts, the public
Weather Underground page-backed collector, or an explicit manual-override
policy decision.

## Setup

Requires Python 3.11+ on Windows.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip install -e ".[test]"
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

The former root wrapper was retired on 2026-07-20. Use the canonical entrypoint
above for every dashboard launch.

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

The overview route is the read-only paper homepage. Its **Safest bets right
now** shortlist reads persisted paper-taker run evidence and shows only
candidates that clear the current freshness, permission-map, liquidity, and
after-cost-value gates. Each card is bound back to the current permission
record, recomputed calibrated fair value, exact run and strategy lineage,
producer order identity, configured native settlement unit, selected side
token, and coherent paper-fill arithmetic. A market price above 90% is not
excluded when those gates still pass. The page never places orders, never
promotes a release, and fails closed to a named no-bet or unavailable state
when its local `data/` inputs are missing, stale, blocked, malformed, or
mid-copy.

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
| `WEATHER_MARKET_REGISTRY` | Optional path to an external market registry override. |
| `SETTLEMENT_LEDGER_ROOT` | Optional root for settlement ledgers; defaults to `data/settlements/`. |
| `WEATHER_DISABLE_STAY_AWAKE` | Set to `1` to disable Windows stay-awake requests in long-running loops. |
| `WEATHER_ALLOW_CONSOLE_CHILDREN` | Set to `1` to allow visible console child processes on Windows background workers. |
| `WEATHER_RETAIN_RAW_FORECAST_PAYLOADS` | Controls retention of raw forecast payload blobs for live snapshot persistence; defaults to retained. |
| `WEATHER_RETAIN_RAW_OBSERVATION_PAYLOADS` | Controls retention of raw observation payload blobs for live snapshot persistence; defaults to retained. |
| `WEATHER_SOURCE_FAMILY_COOLDOWN_PATH` | Optional shared rate-limit cooldown state for cooperating source processes. |
| `WEATHER_RESIDUAL_DISTRIBUTION_V1_SHADOW_RELEASE_DIR` plus `WEATHER_RESIDUAL_DISTRIBUTION_V1_SHADOW_MANIFEST_SHA256` | Opts capture into an inactive residual-distribution shadow release; both the directory and exact manifest hash are required. |

## Core Commands

Run commands from the repository root with the venv interpreter.

### Registry, History, And Source Data

```powershell
# Weather Underground settlement-proxy history.
# The legacy paid-provider backfill path is disabled. Use public-backfill for
# public WU page-backed collection, then audit/rebuild/recover as needed.
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto public-backfill --start 2026-06-29 --end 2026-06-29 --skip-existing
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
.\venv\Scripts\python.exe -m weather.reporting.promotion.promotion_refresh
.\venv\Scripts\python.exe -m weather.reporting.scorecards.snapshot_evaluation
.\venv\Scripts\python.exe -m weather.reporting.daily.daily_learning
.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-23
.\venv\Scripts\python.exe -m weather.market.exchange_economics accept --target-date 2026-06-23
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-23
.\venv\Scripts\python.exe -m weather.operations.daily_refresh run --continue-on-error --fail-on-variant-evidence-alert
.\venv\Scripts\python.exe -m weather.operations.daily_refresh status
.\venv\Scripts\python.exe -m weather.operations.nightly_retrain run --dry-run
.\venv\Scripts\python.exe -m weather.operations.nightly_retrain status
.\venv\Scripts\python.exe -m weather.operations.release_lifecycle rollback `
  --market-day-boundary <reviewed-boundary-proof.json>
```

`daily_refresh` is the morning settlement-to-reporting chain. It can finalize
settlement labels, run taker finalization checks, refresh trading/model evidence,
run promotion and shadow monitors, audit fleet/data health, refresh learning
reports, and write `data/backtest/daily_refresh_status.json` plus
`data/backtest/daily_refresh_report.md`.

The scheduled maker paper-score step is host-bounded: it selects the latest 14
`active_day_live_forward` runs and fails closed before loading more than 512 MiB
of quote inputs. Operators can narrow those limits with
`--maker-paper-latest-active-runs` and `--maker-paper-max-input-bytes`; raising
them requires a separate host-capacity review.

Finalized runs normally provide a source-bound `mm_scoring_projection_v0.1`
base/variant CSV pair containing only current maker-score reader fields.
Preflight validates both members against their canonical tapes and
measures/passes those exact paths; if either member is missing, stale,
malformed, or incompatible, the whole run falls back to both canonical quote
tapes. The score receipt records selected and canonical bytes, their ratio,
and every run's input mode. Existing runs can be projected without rewriting
canonical tapes with:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_scoring_projection backfill
```

High-risk settlement-stage steps run one at a time in isolated child process
trees. Each has a repository-declared timeout plus private-memory and
working-set ceilings, plus an admission working-set expectation that defaults
to the working-set ceiling when unspecified and may never exceed it. Admission
requires host commit below 70%, fresh capture loops, and enough available
physical RAM for that expectation plus a 1.5 GiB capture reserve. Status is
interruption-safe: while a child is live, `daily_refresh_status.json` is already
terminal/resumable and records the step, PID, budget, last progress, parent-
observed process-tree resource peaks, and exact bounded resume command. The
child result envelope records the child's own peak working set and peak commit
when the platform query is available. Completed parent receipts also record
elapsed time, lifetime process-tree read/write bytes, and a bounded set of
result cardinality/byte metrics.
`--stage-a-min-available-reserve-mb` and
`--stage-a-max-commit-percent` may make admission stricter; loosening either
requires host-capacity review.

Exchange-economics snapshots gate paper/shadow taker and maker evidence. The
tracked source template is
`docs/research/exchange_economics_snapshot_template.json`; publish a fresh
runtime snapshot before evidence runs and accept the baseline only after
reviewing drift. The operator workflow is documented in
`docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md`.

`nightly_retrain` is the overnight self-improvement job. It refreshes daily
learning, retrains/validates candidate artifacts, refreshes artifact registries
and promotion decisions, and writes `data/backtest/nightly_retrain_status.json`
plus `data/backtest/nightly_retrain_report.md`. Candidate mode defaults to
`research_only`. Explicit production mode first locks a candidate-independent
14-day evaluation window, then writes four candidate-local point-in-time roles;
it can build only an inactive release and never changes the active pointer. See
the [nightly retrain runbook](docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md).

When no release or pointer exists, production mode has one explicit deadlock-
free path: `--bootstrap-first-inactive-release` waives only the impossible
pre-release parity check. It requires an empty release store and exact offline
production qualification, binds a self-hashed receipt into the immutable
manifest, re-verifies every frozen artifact, and leaves the active pointer
absent. It does not authorize promotion, serving, shadow adoption, worker
restart, or live fallback. See the
[first inactive release procedure](docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md#first-inactive-production-release).

Separately, there is one narrow first-serving-identity exception to the
ordinary rule that a `research_only` release cannot be activated. When no
active pointer exists, a reviewed operator may use
`release_lifecycle promote --bootstrap-first-release` with a promotion decision
whose `release_kind` is exactly
`serving_identity_bootstrap`. The pointer records the decision, boundary, and
reviewer as immutable bootstrap-origin provenance. The resulting release can
bind research, shadow, and paper runtimes, but remains non-production and
non-capital: production readiness and `live-pilot` fail closed. The flag does
not authorize another research-only release once a pointer exists. A later
production promotion carries the bootstrap kind and origin proof as its
rollback target, so reviewed rollback restores the same non-capital identity
rather than silently upgrading it. Promotion still requires a coordinated
worker restart; changes to this loop-loaded serving contract also use the
repository's normal fleet-roll budget. See the
[nightly retrain runbook](docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md#separate-serving-identity-bootstrap).

Release rollback is a reviewed, market-day-boundary operation. The command
hash-verifies the prior immutable release, atomically switches the active
pointer, emits the post-rollback release identity, and writes
`data/backtest/release_rollback_drill.json`. A self-hashed reconciliation
journal is durable before the pointer changes, so the same command can safely
finalize the record after an interrupted post-swap write. It does not control
workers: the record remains pending until the required coordinated restart and
health proof are completed.

### Backtests, Audits, And Model Training

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.backtest
.\venv\Scripts\python.exe -m weather.backtesting.snapshot_analytics
.\venv\Scripts\python.exe -m weather.collection.collection_health
.\venv\Scripts\python.exe -m weather.collection.collection_health --fleet --live --strict --json
.\venv\Scripts\python.exe -m weather.reporting.fleet.fleet_observability report --strict
.\venv\Scripts\python.exe -m weather.reporting.data_quality.data_layer_audit
.\venv\Scripts\python.exe -m weather.reporting.source_gates.source_redundancy report --start 2026-06-01 --end 2026-06-22
.\venv\Scripts\python.exe -m weather.reporting.data_quality.data_auditor
.\venv\Scripts\python.exe -m weather.reporting.data_quality.data_auditor --fleet --json --strict
.\venv\Scripts\python.exe -m weather.calibration.feature_model --market toronto
.\venv\Scripts\python.exe -m weather.calibration.feature_model --market nyc --skip-loo
.\venv\Scripts\python.exe -m weather.calibration.intraday_calibration
.\venv\Scripts\python.exe -m weather.artifacts size-audit
```

`weather.calibration.feature_model` trains one market/unit-family at a time.
Use `--market toronto` for Celsius artifacts and an F-market such as `nyc` for
F-family artifacts. For the local multi-market helper, use
`.\tools\train_all_markets.ps1`.

### Trading Simulations

```powershell
# Keyless market-making operator run.
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-22 --budget-usdc 500 --mode shadow --markets all
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-22 --budget-usdc 500 --mode paper-live-forward --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper
.\venv\Scripts\python.exe -m weather.market.mm_scoring_projection backfill

# Paper taker-bot simulator.
.\venv\Scripts\python.exe -m weather.market.taker_bot_cli --date 2026-06-22 --budget-usdc 100 --markets all --loop --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.operations.taker_bot_daily_roll status
```

Live order modes have additional readiness gates and confirmation flags. Keep
normal development and research runs in `shadow` or `paper-live-forward`.

## Scheduled Operations

Windows scheduled-task definitions live under `scripts/ops/`. Registration is
stateful and re-running a script replaces its named task. Read
[the scoped script instructions](scripts/ops/AGENTS.md), the script's `param(...)`
block, and the [operations topology](docs/operations/OPERATIONS_DESIGN.md) before
registration. Some production pipeline scripts require explicit captured-input
and production-readiness evidence paths. A bare registration command is not a
valid substitute for those inputs.

The three core capture supervisors have self-contained defaults:

```powershell
.\scripts\ops\register_snapshot_supervisor.ps1
.\scripts\ops\register_clob_supervisor.ps1
.\scripts\ops\register_observation_trigger_supervisor.ps1
```

Before release #1 has reviewed parity inputs, the two daily-refresh tasks may
be re-registered with only scheduler provenance and release arguments by using
the explicit transitional mode:

```powershell
& .\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly
```

That command replaces both daily tasks. It intentionally omits the FULL
production-evidence contract and does not assert production readiness.

Scheduled settlement/evidence refresh, event-config refresh, exchange-economics
refresh, maker/taker daily rolls and supervisors, analysis, host guards, and
candidate training are separate registrations. Their script parameter blocks
are the source of truth for names, cadence, and required inputs. On a dedicated
single host, use the bounded training-window topology; do not also enable the
direct nightly-retrain task for the same workload.

The Operations dashboard can inspect and control the supervised loops. CLI
status commands are still the fastest sanity checks:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.operations.daily_refresh status
.\venv\Scripts\python.exe -m weather.operations.nightly_retrain status
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
```

Canonical commands run through packaged `weather.*` modules. Retired flat
wrappers and root shims are prohibited by the import/path architecture ratchets;
use `app/streamlit_app.py`, `scripts/ops/*`, `scripts/launch/*`, and `tools/*`
for their non-package command surfaces.

## Documentation

- [Documentation map](docs/README.md) - canonical router and classification.
- [Architecture](docs/architecture.md) - owner boundaries and end-to-end flow.
- [Development and verification](docs/development.md) - change workflow and test matrix.
- [Git workflow SOP](docs/git-workflow.md) - branch, worktree, commit, and pull-request flow.
- [Project operating SOP](docs/operations/PROJECT_OPERATING_SOP.md) - shift-to-release decision flow.
- [Operations index](docs/operations/README.md) - topology, policies, and runbooks.
- [Active backlog](docs/roadmap/active-backlog.md) - generated current-work view.
- [Roadmap index](docs/roadmap/ROADMAP.md) - complete taxonomy and item links.

## Update this file when

Update when product scope, built-in markets, setup/dependencies, dashboard
entrypoints, operator commands, environment variables, scheduled-operation
routing, data/source layout, or the top-level documentation map changes.
