# Agent Context

Last audited: 2026-06-14

## Mission

This project is not a generic weather dashboard. It is a research and live
decision system for Toronto daily high-temperature Polymarket markets. The goal
is to project the final settlement bucket better than Polymarket's live prices,
then prove that edge with settlement-scored backtests.

"Better than Polymarket" should mean more than a plausible forecast. Prefer
objective evidence:

- Lower Brier score and log loss than market yes prices on captured snapshot
  tapes.
- Positive Brier skill score versus the market in
  `weather.backtesting.backtest`.
- Calibrated probabilities by confidence bucket.
- Realized edge/P&L that survives thresholding and avoids one-snapshot
  overfitting.

The current backtest sample is still small, but it is no longer one clean day.
The 2026-06-14 audit found that the settlement ledger was stale: 93 settled
snapshot folders existed, while `market_day_labels.csv` held only 69 labels.
Running `weather.market.market_day_labels finalize` wrote 93 reconciled labels
(`complete=27`, `partial=66`, Polymarket `match=93`). `weather.reporting.promotion_refresh`
then doubled the F-family pinned corpus to 24 market-days and moved the pooled
candidate to `PASS_WITH_SHADOWS / PER_MARKET_ONLY` with Atlanta and Austin
promoted, nine F markets shadowed, and zero blocked. This is real progress, but
the aggregate candidate Brier (`0.0538`) still trails market Brier (`0.0404`).
Treat clean settled market-day volume and daily refresh automation as active
benchmark constraints, not solved problems.

## Settlement Model

The modeled resolution source is the highest whole-degree Celsius value printed
by Wunderground/Weather.com history for Toronto Pearson CYYZ on the target date.
The code uses half-up rounding for Celsius buckets.

Important distinction:

- Wunderground history (`wu_history`) is the settlement proxy and can create a
  hard observed floor.
- ECCC SWOB, METAR, Weather.com current, Open-Meteo, and forecasts are useful
  signals, but they are not the settlement source. Do not let them force a hard
  final bucket unless the code is explicitly modeling a soft support signal.
- SWOB often leads WU history, so it can suppress lower buckets softly through
  `apply_live_observed_floor`, but it should remain hedged because it is a
  non-resolution source.

## How The App Is Wired

- `app/streamlit_app.py` is the Streamlit dashboard. It fetches Polymarket, live weather
  sources, model output, snapshots, source freshness, timeline views, analogs,
  and controls for the background snapshot loop.
- `src/weather/market/polymarket_client.py` reads the daily event from the
  Polymarket Gamma API using the slug from
  `src/weather/market/market_config.py`.
- `src/weather/model/toronto_model.py` composes the model from mixins:
  - `model_sources.py`: live/local source fetching and parsers.
  - `model_climatology.py`: local WU target-season cache, priors, intraday and
    regime distributions.
  - `model_distribution.py`: probability engine, live signals, floors, caps,
    feature/empirical blending.
  - `model_features.py`: HGB/LR feature inference, late-day continuation,
    analog search, bucket transitions.
  - `model_presentation.py`: market-bin parsing and dashboard/snapshot rows.
  - `model_base.py`: shared numeric and source helpers.
- `src/weather/collection/snapshot_tracker.py` writes market/model snapshot tapes and forecast
  tapes under `data/snapshots/<event-slug>/`.
- `src/weather/backtesting/backtest.py` is the main proof harness for model-vs-market performance.

Most modules assume they are run from the repository root, with `src` on
`sys.path` rather than installed as a package.

## Target Date And Market Config

The active market defaults to today's date in `America/Toronto`. Override it
with:

```powershell
$env:TORONTO_MARKET_DATE = "2026-05-31"
```

or pass a target date to `TorontoHighTempModel(target_date=...)` where supported.
Several constants are computed at import time from `config_for_date()`, so
restart long-running processes after changing `TORONTO_MARKET_DATE`.

Event slugs are generated as:

```text
highest-temperature-in-toronto-on-<month>-<day>-<year>
```

## Data Layout

Key tracked data:

```text
data/wunderground/cyyz/
  hourly/               # normalized WU/Weather.com observations
  daily/daily_summary.csv
  manifest.json

data/eccc_swob/cyyz/    # official station SWOB observations and comparison reports
data/metar/cyyz/        # aviation report sanity-check layer
data/forecast_history/  # archived forecast daily features
data/snapshots/<slug>/  # odds/model/forecast tapes for each market day
data/backtest/          # settlement-scored reports
```

Raw provider payloads under `data/**/raw/` are considered regenerable and are
git-ignored. Normalized hourly/daily artifacts are tracked. Snapshot files are
append-only evidence; do not rewrite or delete them casually.
New snapshots can also include `features_long.csv` and `features.jsonl`, which
record the versioned live feature vector used for that snapshot, plus
`components_long.csv` and `components.jsonl`, which record per-component
market-bin probabilities for ensemble and ablation audits.

The repository currently has live snapshot files modified under
`data/snapshots/highest-temperature-in-toronto-on-may-31-2026/` plus
`data/snapshots/diagnostics.jsonl` and `loop_status.json`. Those were present
before this audit; do not revert them unless the user explicitly asks.

## Core Commands

Use the pinned venv interpreter where possible:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app src tests
```

Operational and research commands:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --loop --interval-minutes 10
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.market.market_microstructure capture --market toronto --price-history
.\venv\Scripts\python.exe -m weather.market.market_microstructure loop --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict
.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15
.\venv\Scripts\python.exe -m weather.market.market_microstructure websocket --market toronto --seconds 300
.\venv\Scripts\python.exe -m weather.operations.observation_trigger once --market all
.\venv\Scripts\python.exe -m weather.operations.observation_trigger loop --market all --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.operations.observation_trigger ensure --market all --interval-seconds 60
.\venv\Scripts\python.exe -m weather.operations.observation_trigger replay
.\venv\Scripts\python.exe -m weather.collection.collection_health --fleet --live --strict --json
.\venv\Scripts\python.exe -m weather.reporting.fleet_observability report --strict
.\venv\Scripts\python.exe -m weather.reporting.data_layer_audit
.\venv\Scripts\python.exe -m weather.reporting.source_redundancy report --start 2026-06-01 --end 2026-06-12
.\venv\Scripts\python.exe -m weather.sources.metar_history --market nyc backfill --start 2026-06-01 --end 2026-06-12 --skip-existing
.\venv\Scripts\python.exe -m weather.calibration.pooled_feature_model --objective band --artifact artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl --out data\backtest\f_family_pooled_band_model_v0_3_report.md
.\venv\Scripts\python.exe -m weather.calibration.pooled_candidate_replay --artifact artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl --out data\backtest\pooled_candidate_replay_v0_3_report.md --json-out data\backtest\pooled_candidate_replay_v0_3.json
.\venv\Scripts\python.exe -m weather.reporting.promotion_refresh
.\venv\Scripts\python.exe -m weather.operations.daily_refresh run --continue-on-error --fail-on-variant-evidence-alert
.\venv\Scripts\python.exe -m weather.operations.daily_refresh status
.\venv\Scripts\python.exe -m weather.backtesting.backtest
.\venv\Scripts\python.exe -m weather.calibration.model_ensemble
.\venv\Scripts\python.exe -m weather.calibration.probability_calibration train
.\venv\Scripts\python.exe -m weather.calibration.forecast_error_model train
.\venv\Scripts\python.exe -m weather.calibration.settlement_lag_model train
.\venv\Scripts\python.exe -m weather.market.market_day_labels finalize
.\venv\Scripts\python.exe -m weather.backtesting.snapshot_analytics
.\venv\Scripts\python.exe -m weather.collection.collection_health
.\venv\Scripts\python.exe -m weather.sources.wu_history audit
.\venv\Scripts\python.exe -m weather.reporting.data_auditor
.\venv\Scripts\python.exe -m weather.reporting.data_auditor --fleet --json --strict
.\venv\Scripts\python.exe -m weather.calibration.feature_model
.\venv\Scripts\python.exe -m weather.calibration.intraday_calibration
```

`pytest.ini` intentionally limits tests to `tests/`; `scratch/` contains
ad-hoc live scripts that may hit the network.

## Model Artifacts

- `src/weather/model/model_constants.py` currently labels the ML model as `v0.5.8` (item-40
  afternoon-ramp extension: training samples wall offsets out to 105 min for
  ramp cutoff hours 12-14 via `feature_model.wall_offset_for`, fixing the
  13-14h winner under-call from WU print-lag; clean control-vs-treatment A/B
  gave hour 14 -0.0088 / hour 13 -0.0020, zero regression elsewhere).
- `artifacts/models/hgb/feature_model_hgb.pkl` is the preferred HistGradientBoosting model.
- `artifacts/models/coefs/feature_model_coefs.json` is the pure-Python logistic-regression
  fallback.
- `artifacts/models/coefs/late_day_model_coefs.json` powers late-day continuation risk.
- `artifacts/calibration/calibrated_weights.json` powers calibrated empirical fallback weights.
- `artifacts/calibration/probability_calibration.json` powers exact-distribution and market-bin
  probability calibration in live inference.
- `artifacts/calibration/forecast_error_model.json` powers the learned forecast-error component
  used by the `forecast_cap` slot, analog forecast-gap distance, and late-day
  forecast-tail adjustment.
- `artifacts/calibration/settlement_lag_model.json` powers learned WU catch-up/revision behavior
  when SWOB leads WU history. WU remains the only hard floor; SWOB suppression
  is capped so it cannot become a hard non-resolution floor.
- `src/weather/model/feature_store.py` defines the live feature schema
  `toronto_feature_store_v0.4` and the audit columns for snapshot feature
  vectors.
- `src/weather/market/market_day_labels.py` finalizes per-market `settlement.json` files and
  `data/backtest/market_day_labels.csv`; labels include settlement, quality,
  capture ratio, max gap, and coverage reason. `weather.backtesting.backtest` displays quality
  grades when those labels exist and can filter scoring with `--quality-grades`.
- `weather.collection.collection_health --fleet --live --strict --json` is the
  operator-friendly fleet collection watchdog. It reports `COLLECTING`,
  `AT_RISK`, `CLEAN`, `PARTIAL`, or `MISSING` for each registered market;
  `weather.collection.snapshot_tracker --status` embeds both the active day's collection state
  and the full fleet collection state next to the loop heartbeat. The running
  loop also writes a compact `fleet_collection` summary into
  `data/snapshots/loop_status.json`.
- `weather.reporting.fleet_observability report --strict` writes
  `data/backtest/fleet_observability.json`,
  `data/backtest/fleet_observability_report.md`, and
  `data/backtest/artifact_provenance_manifest.json`. It combines fleet
  collection health, fleet historical audits, artifact provenance/schema
  status, and location-trust readiness into one red/yellow/green payload.
- `weather.reporting.data_layer_audit` writes `data/backtest/data_layer_audit.json` and
  `data/backtest/data_layer_audit_report.md`. The 2026-06-12 audit found the
  weather/model loop healthy at a 10-minute cadence (`93` snapshot folders,
  `9,368` snapshots, `103,048` band rows) but identified the market data layer
  as too shallow: no persisted CLOB token ids/order-book depth/trade stream,
  Gamma `best_bid` filled only `48.0%`, and redundant historical sources are
  shallow for the May 20-June 30 target season (METAR `13/1326` days per
  market; GHCNh/reanalysis about `36%`). `weather.market.market_microstructure` is now the
  fast CLOB capture path: it writes token maps, raw/order-book summary and level
  tapes, optional price history, and public market WebSocket events under
  `data/snapshots/<event-slug>/`. `weather.market.market_microstructure` now has
  production loop verbs (`status`, `start-detached`, `restart`, `stop`,
  `ensure`) and writes `data/snapshots/clob_loop_status.json`,
  `clob_diagnostics.jsonl`, and `clob_loop_console.log`. Register
  `scripts/ops/register_clob_supervisor.ps1` so Task Scheduler runs the CLOB
  `ensure` check every minute. Keep the weather/model snapshot loop at
  5-10 minutes and run the supervised CLOB book loop separately at 30-60
  seconds, with 10-15 second fast cadence near the thermal/market close or
  after large top-of-book midpoint moves.
  `weather.market.market_microstructure audit --strict` is the book-tape acceptance
  check: per-market active-day cadence (median/max gap, 120s threshold,
  trailing freshness), non-zero exit on any gap. `weather.reporting.fleet_observability`
  includes the CLOB loop and book-gap state as fail-closed alerts, so a dead
  recorder or tape gap surfaces like a snapshot-collection failure.
- `weather.operations.observation_trigger` is the item-42 fast recompute path. It polls only
  low-cost observation sources (`wu_history`, `wu_current`, `metar`, and
  Toronto `eccc_swob`) at 30-60 second cadence, triggers forced snapshots on
  new WU printed highs, live bucket crossings, support above the WU floor, or
  stale-source recovery, and tags evidence with `snapshot_cadence=triggered`
  plus `trigger_context` in `snapshots.jsonl` and `replay_inputs.jsonl`.
  The watcher writes `data/snapshots/observation_trigger_status.json`,
  `data/snapshots/observation_triggers.jsonl`, diagnostics/console logs, and
  exposes a freshness/fail-closed `trade_permission` payload for future quote
  code. Register `scripts/ops/register_observation_trigger_supervisor.ps1` so Task
  Scheduler keeps it alive. `weather.operations.observation_trigger replay` writes
  `data/backtest/observation_trigger_replay.json` and report, scoring triggered
  rows against the casebook's WU lag/catch-up loss cases; the first generated
  report sees 745 WU-lag losses but zero historical triggered rows because the
  watcher did not exist for those tapes.
- `weather.reporting.source_redundancy report` writes
  `data/backtest/source_redundancy.json`,
  `data/backtest/source_redundancy_report.md`,
  `data/backtest/source_truth_daily.csv`, and
  `data/backtest/forecast_ensemble_features.csv`. It compares WU against
  METAR/ASOS, GHCNh, and ERA5-style reanalysis, learns source bias/peak-time
  lead versus WU, emits provenance-safe gap-fill candidates/refetch commands,
  and records forecast ensemble/disagreement features from archived forecast
  tapes. `weather.sources.metar_history` backfills registered market stations from IEM ASOS
  into the same native-unit hourly/daily schema. Live forecast extraction now
  includes Weather.com, Open-Meteo, ECCC where available, NWS hourly for US
  markets, and Open-Meteo GFS global ensemble.
- `src/weather/calibration/model_ensemble.py` is the item-26 research harness. It reads strict
  quality-filtered settled tapes, joins future `components_long.csv` rows,
  reports standalone candidate performance by cutoff/bin type, and keeps
  no-market and market-informed leave-one-day ensembles separate. After the
  2026-06-14 ledger refresh there are more clean labels available, but any
  ensemble promotion still needs a fresh quality-filtered rerun rather than
  relying on the old one-day report.
- `weather.calibration.pooled_feature_model --objective band` is the Item 33 F-family shadow
  path. Current candidate:
  `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl` with
  `pooled_feature_band_hgb_v0.3` / `toronto_feature_store_v0.4`. It trains a
  direct market-band objective with city features and static source-reliability
  priors from WU-vs-METAR/ASOS/GHCNh/reanalysis overlaps. Current pinned replay:
  `data/backtest/pooled_candidate_replay_latest_report.md`, verdict
  `PASS_WITH_SHADOWS / PER_MARKET_ONLY`, aggregate Brier `0.0538` versus
  current replay `0.0687` and market `0.0404`. Atlanta and Austin clear the
  per-market gate; the other nine F markets remain shadow because they have not
  beaten market prices on the pinned rows.
- `weather.reporting.promotion_refresh` is the Item 33/37 settlement-to-promotion runner.
  It rebuilds the pinned promotion corpus, refreshes `location_trust.json`,
  reruns the pooled-F candidate replay, runs the current-serving gauntlet, and
  writes machine-readable per-market actions to
  `data/backtest/f_family_promotion_refresh.json` plus
  `data/backtest/f_family_promotion_refresh_report.md`. The 2026-06-14 run
  used a 24-market-day F corpus, promoted Atlanta and Austin, kept the other
  nine F markets in shadow, and left current-serving gauntlet status `BLOCK`
  because the serving replay still regresses versus its baseline.
- `requirements.txt` pins `scikit-learn==1.8.0` because the HGB artifact is a
  pickle. Do not casually bump sklearn without regenerating and verifying the
  model artifact.

`data/wunderground/cyyz/analysis/feature_model_report.md` includes HGB
feature-family ablations over 5,823 leave-one-out rows. The observed
temperature path is by far the largest contributor; wind, forecast, and
atmosphere have smaller positive value; cloud regime is currently neutral to
slightly negative. The full `src\feature_model.py` retrain is slow, so future
ensemble/ablation work should add a sampled or cached research mode.

When changing feature logic, update both sides:

- Training extraction in `src/weather/calibration/feature_model.py`.
- Live extraction in `src/weather/model/model_features.py::extract_live_features`.

Then regenerate artifacts and reports, and run tests/backtests. Train/serve
skew is one of the easiest ways to create fake edge.

## Current Audit Notes And Risks

- Miami's impossible 2005-06-11 WU value (`171 F`) was quarantined during
  normalization and the rebuilt daily row is `86 F`; `data_auditor.py --fleet
  --json --strict` reports zero impossible values and zero duplicate markets.
  CLOB startup gaps are visible as ignored startup gaps in the book-tape audit
  while post-start gaps and stale trailing captures still fail closed. The main
  snapshot loop now measures scheduled cadence separately from triggered
  recomputes, and collection health scopes gap criticals to the 12:00-18:00
  settlement-decisive window. A fresh 2026-06-14
  `weather.reporting.fleet_observability report --strict` run is `WARN` with zero critical
  alerts.
- The settlement ledger can drift stale if `weather.market.market_day_labels finalize` is
  not run after new days settle. The June 11/12 backlog materially changed
  trust and promotion results, so automate finalization plus
  `weather.reporting.promotion_refresh`, `weather.reporting.progress_audit`,
  and `weather.reporting.disagreement_casebook`.
  `weather.operations.daily_refresh run --continue-on-error --fail-on-variant-evidence-alert`
  now executes that chain plus `weather.reporting.fleet_observability`, fails
  closed when variant-learning evidence is missing/stale/blocked, and writes
  `data/backtest/daily_refresh_status.json` /
  `data/backtest/daily_refresh_report.md`; `scripts/ops/register_daily_refresh.ps1`
  is registered as `WeatherDailySettlementPromotionRefresh`.
- The dashboard has visible mojibake in some status/warning strings
  (`app/streamlit_app.py`, `model_constants.py`, `model_distribution.py`, and
  `model_presentation.py` comments/cleanup paths show encoding artifacts).
  Clean user-visible text when touching those areas.
- `app/streamlit_app.py` current-edge table should prefer `bin_data["label"]`; it currently
  tries fields that are not the canonical parsed label.
- `src/weather/model/model_distribution.py` contains a duplicate empty
  `estimate_distribution` definition immediately before the real method. Python
  overwrites it, so behavior is not broken, but it is confusing and should be
  removed in a cleanup pass.
- The model explanation and 25 C deep dive are still partly hardcoded around
  25 C. Future work should make explanations quantitative and bucket-agnostic.
- The HGB model is useful but should not be assumed perfectly calibrated. The
  live path now has a probability calibration artifact, but it improves
  overconfidence rather than creating market-beating signal. Always compare
  against Polymarket prices through `weather.backtesting.backtest` and
  `weather.calibration.probability_calibration`, not just model-only validation
  reports.
- Analog search now includes Open-Meteo forecast gap, but it still does not use
  a full hourly forecast-profile distance.
- Feature schema `toronto_feature_store_v0.4` adds
  `forecast_source_count` and `forecast_disagreement`; existing artifacts keep
  serving because they select trained feature names.
- `data_auditor.py` currently audits years 2000-2025 and follows the configured
  target month/day. It is registry-aware and unit-aware; use
  `python -m weather.reporting.data_auditor --fleet --json --strict` for
  automation. Adjust
  intentionally if the historical window changes.
- Network source fetchers use last-good caching for live sources with a
  90-minute max age. Keep stale-source behavior visible in the dashboard and
  avoid silently using old live data.

## Development Guidance

- Preserve the settlement-source hierarchy. WU history is primary; all other
  sources are support, forecast, or sanity checks.
- Align live feature, analog, transition, and late-day inputs to the effective
  WU printed cutoff hour. Wall-clock time can advance before WU history prints a
  row; using the wall cutoff directly caused prior bugs.
- Treat snapshots and forecast archives as evidence. Prefer appending or
  migrating with explicit code over manual edits.
- Add focused tests for probability mass, floors/caps, market-bin parsing,
  cutoff alignment, and archive schema changes.
- For any model change claiming to improve edge, include at least:
  `pytest -q`, `compileall`, a model validation report if retrained, and
  `weather.backtesting.backtest` after settlement data is available.
- Keep generated reports and Markdown ASCII-safe unless there is a strong reason
  to preserve Unicode; several files already contain encoding artifacts.

## What To Improve Next

The fastest path toward the project goal is likely:

1. Keep daily settlement finalization and promotion refresh scheduled. Item 1 is
   implemented and registered as `WeatherDailySettlementPromotionRefresh`; inspect
   `data/backtest/daily_refresh_status.json` after each morning run.
2. Keep item 42's observation-trigger watcher supervised and accumulate settled
   triggered rows. `WeatherObservationTriggerSupervisor` is registered, the
   watcher status counter is fixed, and live triggered rows are being written;
   `data/backtest/observation_trigger_replay_report.md` becomes acceptance
   evidence once those rows settle.
3. Keep fleet observability free of criticals. Miami quarantine, CLOB startup
   gap handling, scheduled-vs-triggered snapshot cadence, and settlement-window
   collection health are shipped; current status is `WARN` with zero critical
   alerts.
4. Item 38's CLOB overlay is now taxonomy-gated behind the promotion path.
   `weather.calibration.pooled_candidate_replay` trains a non-serving CLOB overlay on fresh book
   rows, scores it out-of-fold by target date, writes
   `artifacts/models/hgb/feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl`,
   and reports both raw and gated Item 38 metrics in
   `pooled_candidate_replay_latest_report.md` plus
   `f_family_promotion_refresh_report.md`. Current evidence: 19,668 OOF CLOB
   rows, raw overlay Brier `0.0303` vs base candidate `0.0486` and market
   `0.0299`; the gate allows `book_liquidity_artifact` and `market_lead`, blocks
   `market_overreaction`, changes 437 rows, and leaves 66,993 rows on the base
   candidate. Gated aggregate Brier is `0.0502` vs base `0.0508`.
5. Item 43's keyless shadow quote policy is live. `weather.market.mm_policy` consumes
   promotion state, latest snapshot/CLOB rows, and observation-trigger health,
   then writes `data/backtest/quotes_long.csv` plus
   `data/backtest/mm_policy_shadow.json` with one quote/no-quote reason per
   latest eligible band and `live_trade_permission=false` for every row. The
   first run emitted 132 decisions: 3 harvest quote intents, 129 no-quote rows,
   and zero live-trade-permission rows. Paper fills and markouts remain Item 44.
6. Use item 27 weather-regime features only behind replay/casebook gates, and
   postpone the item 35 continuous-density model until more clean market days
   prove the current candidate path.
