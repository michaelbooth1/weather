# Agent Context

Last audited: 2026-05-31

## Mission

This project is not a generic weather dashboard. It is a research and live
decision system for Toronto daily high-temperature Polymarket markets. The goal
is to project the final settlement bucket better than Polymarket's live prices,
then prove that edge with settlement-scored backtests.

"Better than Polymarket" should mean more than a plausible forecast. Prefer
objective evidence:

- Lower Brier score and log loss than market yes prices on captured snapshot
  tapes.
- Positive Brier skill score versus the market in `src.backtest`.
- Calibrated probabilities by confidence bucket.
- Realized edge/P&L that survives thresholding and avoids one-snapshot
  overfitting.

The current backtest sample is very small. As of
`data/backtest/backtest_report.md` regenerated on 2026-05-31 with the
`complete,manual_override` quality filter, only May 28 is a clean market-day
tape. May 27 starts too late and May 30 has a 74-minute collection gap, so both
are now labeled `partial`. On the one clean day, the uncalibrated model still
underperformed market prices (all-snapshot Brier 0.0583 versus market Brier
0.0394; Brier skill -0.478). The older 3-day probability calibration report is
useful provisional research, but two of those tapes are now partial. Treat
clean settled market-day volume as the key benchmark constraint, not as a
solved problem.

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

- `app.py` is the Streamlit dashboard. It fetches Polymarket, live weather
  sources, model output, snapshots, source freshness, timeline views, analogs,
  and controls for the background snapshot loop.
- `src/polymarket_client.py` reads the daily event from the Polymarket Gamma API
  using the slug from `src/market_config.py`.
- `src/toronto_model.py` composes the model from mixins:
  - `model_sources.py`: live/local source fetching and parsers.
  - `model_climatology.py`: local WU target-season cache, priors, intraday and
    regime distributions.
  - `model_distribution.py`: probability engine, live signals, floors, caps,
    feature/empirical blending.
  - `model_features.py`: HGB/LR feature inference, late-day continuation,
    analog search, bucket transitions.
  - `model_presentation.py`: market-bin parsing and dashboard/snapshot rows.
  - `model_base.py`: shared numeric and source helpers.
- `src/snapshot_tracker.py` writes market/model snapshot tapes and forecast
  tapes under `data/snapshots/<event-slug>/`.
- `src/backtest.py` is the main proof harness for model-vs-market performance.

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
.\venv\Scripts\python.exe -m streamlit run app.py
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app.py src tests
```

Operational and research commands:

```powershell
.\venv\Scripts\python.exe -m src.snapshot_tracker --force
.\venv\Scripts\python.exe -m src.snapshot_tracker --loop --interval-minutes 10
.\venv\Scripts\python.exe -m src.snapshot_tracker --status
.\venv\Scripts\python.exe -m src.collection_health --live --strict --json
.\venv\Scripts\python.exe -m src.backtest
.\venv\Scripts\python.exe -m src.model_ensemble
.\venv\Scripts\python.exe -m src.probability_calibration train
.\venv\Scripts\python.exe -m src.forecast_error_model train
.\venv\Scripts\python.exe -m src.settlement_lag_model train
.\venv\Scripts\python.exe -m src.market_day_labels finalize
.\venv\Scripts\python.exe -m src.snapshot_analytics
.\venv\Scripts\python.exe -m src.collection_health
.\venv\Scripts\python.exe -m src.wu_history audit
.\venv\Scripts\python.exe src\data_auditor.py
.\venv\Scripts\python.exe src\feature_model.py
.\venv\Scripts\python.exe -m src.intraday_calibration
```

`pytest.ini` intentionally limits tests to `tests/`; `scratch/` contains
ad-hoc live scripts that may hit the network.

## Model Artifacts

- `src/model_constants.py` currently labels the ML model as `v0.4.9`.
- `src/feature_model_hgb.pkl` is the preferred HistGradientBoosting model.
- `src/feature_model_coefs.json` is the pure-Python logistic-regression
  fallback.
- `src/late_day_model_coefs.json` powers late-day continuation risk.
- `src/calibrated_weights.json` powers calibrated empirical fallback weights.
- `src/probability_calibration.json` powers exact-distribution and market-bin
  probability calibration in live inference.
- `src/forecast_error_model.json` powers the learned forecast-error component
  used by the `forecast_cap` slot, analog forecast-gap distance, and late-day
  forecast-tail adjustment.
- `src/settlement_lag_model.json` powers learned WU catch-up/revision behavior
  when SWOB leads WU history. WU remains the only hard floor; SWOB suppression
  is capped so it cannot become a hard non-resolution floor.
- `src/feature_store.py` defines the live feature schema
  `toronto_feature_store_v0.1` and the audit columns for snapshot feature
  vectors.
- `src/market_day_labels.py` finalizes per-market `settlement.json` files and
  `data/backtest/market_day_labels.csv`; labels include settlement, quality,
  capture ratio, max gap, and coverage reason. `src.backtest` displays quality
  grades when those labels exist and can filter scoring with `--quality-grades`.
- `src.collection_health --live --strict --json` is the operator-friendly
  collection watchdog. It reports `COLLECTING`, `AT_RISK`, `CLEAN`, or
  `PARTIAL`; `src.snapshot_tracker --status` embeds the active day's collection
  state next to the loop heartbeat.
- `src/model_ensemble.py` is the item-26 research harness. It reads strict
  quality-filtered settled tapes, joins future `components_long.csv` rows,
  reports standalone candidate performance by cutoff/bin type, and keeps
  no-market and market-informed leave-one-day ensembles separate. The current
  strict sample has only one clean day, so it writes a report but correctly
  refuses ensemble promotion.
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

- Training extraction in `src/feature_model.py`.
- Live extraction in `src/model_features.py::extract_live_features`.

Then regenerate artifacts and reports, and run tests/backtests. Train/serve
skew is one of the easiest ways to create fake edge.

## Current Audit Notes And Risks

- The dashboard has visible mojibake in some status/warning strings
  (`app.py`, `model_constants.py`, `model_distribution.py`, and
  `model_presentation.py` comments/cleanup paths show encoding artifacts).
  Clean user-visible text when touching those areas.
- `app.py` current-edge table should prefer `bin_data["label"]`; it currently
  tries fields that are not the canonical parsed label.
- `src/model_distribution.py` contains a duplicate empty
  `estimate_distribution` definition immediately before the real method. Python
  overwrites it, so behavior is not broken, but it is confusing and should be
  removed in a cleanup pass.
- The model explanation and 25 C deep dive are still partly hardcoded around
  25 C. Future work should make explanations quantitative and bucket-agnostic.
- The HGB model is useful but should not be assumed perfectly calibrated. The
  live path now has a probability calibration artifact, but it improves
  overconfidence rather than creating market-beating signal. Always compare
  against Polymarket prices through `src.backtest` and
  `src.probability_calibration`, not just model-only validation reports.
- Analog search now includes Open-Meteo forecast gap, but it still does not use
  a full hourly forecast-profile distance.
- `data_auditor.py` currently audits years 2000-2025 and follows the configured
  target month/day. Adjust intentionally if the historical window changes.
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
  `src.backtest` after settlement data is available.
- Keep generated reports and Markdown ASCII-safe unless there is a strong reason
  to preserve Unicode; several files already contain encoding artifacts.

## What To Improve Next

The fastest path toward the project goal is likely:

1. Increase the number of clean market-day snapshot tapes.
2. Add item 27 weather-regime and microclimate features behind the item-26
   harness, promoting only changes that improve clean no-market validation.
3. Fix the obvious dashboard/reporting cleanup issues so operators trust what
   they see during the day.
4. Use settlement-scored backtests to find where the calibrated model is still
   wrong versus Polymarket, especially late-day exact buckets.
5. Make the explanation panel show actual probability contributions and edge
   diagnostics for the active top buckets.
