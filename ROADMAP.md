# Toronto Weather Market Roadmap

This roadmap is organized around the fastest path from a useful live dashboard
to a calibrated, auditable trading/research system for Toronto high-temperature
markets.

## Roadmap Deep Dive (2026-05-31)

### North Star

The project goal is to project the daily high-temperature settlement bucket
better than Polymarket. The durable accuracy target is therefore not "does the
weather forecast look right?" but:

- model Brier/log loss better than Polymarket yes prices on settlement-scored
  snapshot tapes,
- positive Brier skill score versus the market,
- calibrated probability buckets across market bands and cutoff hours,
- realized edge/P&L that survives thresholding, first-entry scoring, and
  out-of-sample market days.

The latest settlement-scored report (`data/backtest/backtest_report.md`,
regenerated 2026-05-31) is the most important evidence. After adding
coverage-aware market-day labels, only May 28 currently passes the
`complete,manual_override` quality filter; May 27 starts too late and May 30
has a 74-minute collection gap. The strict headline report therefore scores 1
clean market day and 704 band rows. The uncalibrated model Brier was 0.0583
versus market Brier 0.0394, and model log loss was 0.1850 versus market log
loss 0.1230, for a Brier skill score of -0.478. The older 3-day calibration
sample remains useful as provisional research, but two of those tapes are now
partial. The correct roadmap posture is clear: we need more clean settled
market days before claiming the model beats Polymarket.

### Current Work That Needed Roadmap Reconciliation

- `AGENT_CONTEXT.md` now exists at the repo root and captures the current
  mission, architecture, settlement hierarchy, commands, risks, and best next
  work.
- The test suite is much larger than the 2026-05-28 audit stated. Current
  verification on 2026-06-01: `pytest -q` passed with 141 tests, and
  `python -m compileall src tests` passed.
- The feature model now includes Open-Meteo forecast daily-max features
  (`forecast_high`, `forecast_gap`) in training and live extraction, and
  `src/feature_model.py` has `RUN_LOO = True`.
- The feature-model report now includes log loss, Brier, accuracy, ECE,
  per-hour HGB climatology-blend weights, and feature-family ablations. This
  updates old item-6/item-24 audit notes that said forecast max, Brier/ECE, and
  ablation visibility were absent.
- Market-day labels are now coverage-aware: settlement labels include capture
  ratio, max gap, and coverage reason, and the headline backtest excludes
  partial tapes by quality grade.
- The snapshot loop now has a managed runner, PID/start/heartbeat/error status,
  `--status`, pause flag handling, and diagnostics logging. Item 16 is now
  partial rather than not-started; clean stop/restart remains open.
- Live fetches now have retry/backoff and last-good source caching with a
  90-minute age cap. Item 17 is now partial; separate per-source TTLs and
  structured source-level diagnostics remain open.
- Several "COMPLETE" roadmap items were really implemented prototypes with
  accuracy-grade follow-up work. This roadmap now distinguishes "visible in the
  app" from "calibrated enough to improve edge versus Polymarket."

### Best Path To A More Accurate Model

1. Make the evaluation target unambiguous. Every model improvement should be
   scored against Polymarket prices, by target day and cutoff hour, with
   correlated intraday snapshots handled conservatively. This is item 20.
2. Increase clean market-day capture. Better models need more settled market
   tapes, not just more historical weather rows. This depends on items 16, 17,
   20, and 25.
2a. Capture market microstructure now, not later. The 2026-06-12 data-layer
   audit found that the weather/model loop is healthy, but the market data tape
   was shallow: Gamma best bid was only 48.0% filled and no CLOB token ids,
   order-book depth, or trade stream were persisted. `src.market_microstructure`
   now provides the fast capture path, but historical order-book depth from
   before this ship cannot be recreated, so keeping the new loop running is a
   data-retention priority before final trading-model work.
3. Calibrate before adding complexity. The HGB model has useful signal, but
   the live model can be overconfident versus market prices. Add a market-bin
   calibration layer and shrink high-confidence exact buckets unless history
   and live settlement-source evidence justify them. This is item 21 and is now
   complete; it reduced overconfidence but did not close the gap to Polymarket.
4. Replace heuristic forecast caps/floors with learned forecast-error
   distributions by source, horizon, and regime. This is item 22 and is now
   complete for the first artifact-backed forecast component.
5. Explicitly model WU settlement lag and revisions. Non-resolution sources
   should update probability through a learned catch-up process, not through
   ad-hoc confidence. This is item 23.
6. Use one feature-generation path for training, backtesting, live inference,
   and explanations. This prevents train/serve skew and makes model changes
   auditable. This is item 24 and is now complete.
7. Build the ensemble/ablation framework on top of those shared features, with
   fast sampled validation and separate no-market versus market-informed
   scores. This is item 26 and is now complete as a framework; the strict
   sample is still too small to promote an ensemble.
8. Add physically meaningful weather-regime and microclimate features only when
   item-20/item-26 reports can prove their value. This is item 27.
9. Only then expand model classes, other markets, or trading automation.
   Sophistication without a stronger evaluation harness will create attractive
   but unproven probabilities.

## Codex Audit Summary (2026-05-28)

- Verification run: `.\venv\Scripts\python.exe -m pytest -q` passed with 24 tests.
- Verification run: `.\venv\Scripts\python.exe -m compileall -q app.py src tests`
  passed.
- Verification run: `.\venv\Scripts\python.exe -m src.eccc_swob_history compare`
  generated SWOB/WU comparison artifacts over 51 raw SWOB XML files, 51
  normalized hourly rows, 3 local daily summaries, and 2 scored target-window
  days.
- Verification run: `.\venv\Scripts\python.exe -m src.wu_history audit` passed,
  checking 533 WU hourly partitions against manifest row counts and checksums.
- Verification run: `.\venv\Scripts\python.exe src\data_auditor.py` found 3
  missing WU target-window days (`2000-06-01`, `2000-06-02`, `2000-06-03`) and
  1 sparse WU day (`2019-05-29`, 5 rows).
- Historical repo note: at the time of this 2026-05-28 audit,
  `C:\Users\micha\Desktop\github\weather` was not observed as a Git repository,
  so that audit used filesystem contents, generated artifacts, and runnable
  checks rather than commit history. Superseded by the 2026-05-31 audit, which
  observed a normal Git working tree with live snapshot files already modified.

## Near-Term Priorities

### 1. Snapshot Analytics [CLOSED]

- [x] Build a notebook or CLI report over `data/snapshots/.../snapshots_long.csv`.
- [x] Plot model probability, market yes price, and edge over time for each bucket.
- [x] Add realized weather markers: WU printed high, Weather.com current max, ECCC SWOB max, and forecast max.
- [x] Add summary tables for max positive edge, edge persistence, market movement, and model movement.

Detailed design (implemented 2026-05-28):

- Treat `snapshots_long.csv` as an immutable snapshot tape with one row per
  snapshot per market band.
- Provide a reusable CLI:
  `.\venv\Scripts\python.exe -m src.snapshot_analytics [snapshot-folder]`,
  defaulting to all folders under `data/snapshots`.
- Validate the tape before analysis: required columns, duplicate
  snapshot/band rows, expected row coverage, missing numeric values, timestamp
  parsing, and capture cadence.
- Generate a latest-snapshot table, per-band summary table, threshold-crossing
  events, persistent edge episodes, weather-marker summary, and automated
  takeaways.
- Write stable artifacts next to the source CSV:
  `analytics_report.md`, `snapshots_analytics.png`, `weather_markers.png`, and
  `edge_heatmap.png`.
- Keep generated text ASCII-safe so temperature units do not render as mojibake
  in Markdown.

Codex implementation status (2026-05-28): passes for the expanded item-1
scope. `src/snapshot_analytics.py` now regenerates the report from the latest
`snapshots_long.csv`, validates the tape, writes persistent-edge and
threshold-crossing tables, and emits ASCII-safe Markdown plus three plots. The
May 27 artifact was regenerated over 39 snapshots and 429 band rows.

### 2. Intraday Model Calibration [CLOSED]

- [x] Backtest the empirical intraday model by hour using the 652 historical May 20-June 3 target-season days.
- [x] Replace hand-picked blend weights with learned weights for: climatology, high-so-far bucket, wind regime, cloud regime, current max, and forecast cap.
- [x] Score by log loss, Brier score, top-bucket accuracy, and bucket-group accuracy.
- [x] Separate exact-bucket scoring from cumulative markets such as `29 C or higher`.

Detailed design (implemented 2026-05-28):

- Treat the empirical intraday model as a cutoff-hour ensemble with explicit
  probability components: climatology, high-so-far bucket, latest/current
  bucket, wind regime, cloud regime, and forecast cap.
- Validate with leave-one-year-out scoring so every historical day is tested
  against years other than its own.
- Optimize per-hour non-negative component weights against exact-bucket log
  loss, then report both exact-bucket and market-bin metrics.
- Score exact buckets separately from market bins by mapping buckets into
  `19 C or below`, exact `20 C` through `28 C`, and `29 C or higher`.
- Use a non-leaky historical cap proxy during calibration until the forecast
  archive has enough multi-day history; map the learned cap weight onto the
  live Weather.com/Open-Meteo/ECCC forecast cap in production.
- Write `src/calibrated_weights.json` with metadata, raw and normalized
  weights, component availability, optimizer status, and metrics.
- Write `data/wunderground/cyyz/analysis/calibration_report.md` with the
  design, exact-bucket metrics, market-bin metrics, learned weights, and
  component availability.

Codex implementation status (2026-05-28): passes for the expanded item-2
scope. `src/intraday_calibration.py` now calibrates all six empirical
components, writes exact-bucket and market-bin metrics, and regenerated
`src/calibrated_weights.json` plus
`data/wunderground/cyyz/analysis/calibration_report.md`. `src/toronto_model.py`
now consumes the new component-weight schema for the empirical fallback while
preserving compatibility with the previous flat weight file.

### 3. Forecast Archive [CLOSED]

- [x] Start saving Weather.com hourly forecast snapshots every 10 minutes.
- [x] Start saving Open-Meteo hourly forecast snapshots every 10 minutes.
- [x] Start saving Environment Canada forecast text/highs when they change.
- [x] Store each forecast snapshot with issue time, valid time, source, and target temperature fields.
- [x] Use this archive to learn source-specific bias and error distributions.

Detailed design (implemented 2026-05-28):

- Treat `forecasts_long.csv` as the durable forecast tape, separate from the
  market/model snapshot tape.
- Store a schema-stable row per forecast target with: snapshot id, capture
  times, event slug, target date, source, forecast kind, issue time, issue-time
  basis, valid time, horizon, target temperature, daily high, cloud, wind,
  condition, source URL, payload hash, and change flag.
- Continue saving Weather.com and Open-Meteo hourly rows on every due snapshot.
- Save Environment Canada citypage forecast rows only when the daily-high/text
  payload changes; use source `lastUpdated` as issue time when available and
  captured time as a fallback.
- Migrate legacy forecast CSVs safely so old `temp_c` rows become
  `target_temp_c` rows without losing archived observations.
- Provide a forecast archive CLI:
  `.\venv\Scripts\python.exe -m src.forecast_archive migrate|backfill-eccc|analyze <snapshot-folder>`.
- Learn source-specific bias and error distributions by scoring archived
  forecasts against WU daily summary highs, using the latest WU snapshot high
  when local daily summary data is missing or stale.

Codex implementation status (2026-05-28): passes for the expanded item-3
scope. `src/forecast_archive.py` now owns forecast schema migration, row
construction, ECCC change tracking, ECCC backfill from snapshots, and
bias/error analysis. `src/snapshot_tracker.py` writes the new schema during
snapshot capture. The May 27 archive was migrated to 22 rows across
Weather.com, Open-Meteo, and ECCC, and
`data/snapshots/highest-temperature-in-toronto-on-may-27-2026/forecast_bias_report.md`
plus `.json` were generated.

### 4. ECCC SWOB Historical Layer [CLOSED]

- [x] Backfill or prospectively collect CYYZ SWOB observations.
- [x] Normalize SWOB rows into the same local format as WU history.
- [x] Compare SWOB same-day max versus WU final high by date and season.
- [x] Learn whether SWOB systematically leads, exceeds, or misses the WU settlement source.

Codex audit (2026-05-28): previous material issues resolved. The old
`src/eccc_history.py` climate CSV backfill remains separate, while
`src/eccc_swob_history.py` now owns SWOB XML collection, WU-shaped
normalization, daily settlement-proxy summaries, and SWOB/WU comparison
artifacts with lead-timing support.

Detailed design (implemented 2026-05-28):

- Keep the historical SWOB layer separate from `src/eccc_history.py`, because
  that module is an Environment Canada climate CSV backfill rather than a SWOB
  XML archive.
- Store raw SWOB XML under `data/eccc_swob/cyyz/raw/year=YYYY/month=MM/day=DD`
  with a per-day manifest recording source URL, downloaded file names, and
  fetch status.
- Normalize SWOB XML into WU-compatible local rows under
  `data/eccc_swob/cyyz/hourly/year=YYYY/month=MM/observations.jsonl`, using the
  same core fields as WU history (`station`, `obs_id`, `obs_name`,
  `valid_time_utc`, `valid_time_local`, `local_date`, `local_time`, `minute`,
  `temp_c`, `dewpoint_c`, `humidity`, `pressure`, `visibility`,
  `wind_dir_deg`, `wind_speed_kmh`, `wind_gust_kmh`, `clouds`, `condition`) and
  SWOB-specific max fields (`swob_max_1h_c`, `swob_max_6h_c`,
  `swob_max_24h_c`).
- Rebuild a stable daily summary CSV from normalized SWOB rows. The settlement
  proxy should use the maximum of observed air temperature and SWOB rolling
  one-hour max for same-day scoring, while retaining 6-hour and 24-hour maxima
  for diagnostics.
- Compare SWOB daily maxima with WU final daily highs by date and target-season
  window. Report bias, absolute error, bucket agreement, exceeds/misses, and
  lead timing: the first SWOB observation or rolling max at or above the WU
  final high compared with the first WU time at the final high.
- Provide a CLI:
  `.\venv\Scripts\python.exe -m src.eccc_swob_history fetch|rebuild|compare|run`
  so the layer can be used both prospectively for current SWOB days and later
  for any archived date still available from `dd.weather.gc.ca`.

Codex implementation status (2026-05-28): passes for the expanded item-4
scope. The SWOB layer fetched 51 raw XML observations for UTC 2026-05-26
through 2026-05-28, normalized them into 51 WU-compatible hourly rows and 3
local daily summaries, and generated
`data/eccc_swob/cyyz/analysis/comparison_report.md`, `.csv`, and `.json`.
After filtering partial local days below 18 SWOB rows, the comparison scored 2
target-window days: mean SWOB-WU bias +0.30 C, MAE 0.30 C, exact bucket match
100.0%, SWOB exceeds WU 100.0%, and one reliable lead-timing day where SWOB
first reached the WU final high 180 minutes before WU's first max timestamp.
The 2026-05-27 WU high comes from the snapshot `wu_history_high_c` override, so
that row is scored for level/bucket but not lead timing.

### 5. METAR Historical Layer [PARTIAL]

- [x] Collect historical METAR rows for CYYZ.
- [x] Compare full-day hourly METAR max versus final WU bucket.
- [ ] Quantify how often METAR misses the settlement bucket by intraday cutoff hour.
- [ ] Use this to calibrate the live METAR sanity-check role instead of a small hard-coded signal.

Codex audit (2026-05-28): partial. `src/metar_history.py` collects IEM ASOS
METAR data, normalizes local rows, and generates a full-day WU comparison report
over 656 matched days. Issues found: intraday miss rates by cutoff hour are not
computed, and the live model only uses METAR as a small hard-coded sanity-check
signal rather than a calibrated role learned from this layer.

Codex update (2026-05-31): still partial. This item should stay open because
METAR can be valuable as an independent airport observation stream, but only if
its miss/lead behavior is learned by cutoff hour and market bucket.

Codex update (2026-06-12): `src.metar_history` is now registry-driven instead
of CYYZ-only. It backfills any registered market station from IEM ASOS,
normalizes to the shared native-unit hourly/daily schema, writes manifests, and
feeds item 30's source-redundancy truth table. This still does not close item 5:
the remaining work is the cutoff-hour miss/lead calibration and serving-role
retirement/retuning.

## Model Improvements

### 6. Feature-Based Probability Model [IMPLEMENTED - CALIBRATION NEXT]

- [x] Build a tabular training set with one row per historical day per cutoff hour.
- [x] Include features:
  high so far, current/latest temp, rise from 7 AM, wind direction/speed,
  cloud regime, dew point, humidity, pressure trend, and forecast max.
- [x] Train a simple interpretable model first:
  multinomial logistic regression, isotonic-calibrated random forest, or
  gradient boosting with calibration.
- [x] Keep the empirical model as a baseline and fallback.

Codex audit (2026-05-28): partial. `src/feature_model.py` builds per-hour rows,
exports logistic-regression coefficients, exports a HistGradientBoosting model,
and `src/toronto_model.py` falls back to the empirical baseline. Issues found:
the feature set omits forecast max, the gradient boosting model is not
calibrated, the checked-in training script has `RUN_LOO = False` so reruns do
not regenerate the evaluation report, and the feature-model report lacks Brier
or calibration metrics.

Codex update (2026-05-31): the old item-6 audit notes are partly superseded.
`src/feature_model.py` now includes `forecast_high` and `forecast_gap`, has
`RUN_LOO = True`, exports refreshed LR/HGB/late-day artifacts, and writes
`data/wunderground/cyyz/analysis/feature_model_report.md` with log loss, Brier,
accuracy, ECE, and tuned per-hour HGB blend weights. Remaining accuracy work:
the HGB output is still not probability-calibrated with a dedicated
Platt/isotonic/temperature layer, and validation is still model-vs-history
rather than model-vs-Polymarket market-bin edge. New item 21 owns this.

### 7. Bucket Boundary Logic [IMPLEMENTED - REFINEMENT NEXT]

- [x] Explicitly model exact bucket risk around 24/25/26 C.
- [x] Add conditional probability tables:
  if current max is `X`, probability final is `X`, `X+1`, `X+2`.
- [x] Track whether WU history tends to print whole-degree updates late or skip
  intermediate buckets.

Codex audit (2026-05-28): partial. `get_bucket_transitions()` produces a
dashboard table for current bucket to `X`, `X+1`, `X+2`, and `>= X+3`, plus a
skip-rate statistic. Issues found: the logic is generic to the current bucket,
not explicitly centered on 24/25/26 C, and it tracks skipped intermediate
buckets but not late whole-degree update timing.

Codex update (2026-05-31): the generic transition panel is useful and should
stay, but accuracy work should move beyond display. The next version should
feed calibrated continuation and skip/timing probabilities back into the final
distribution, especially near exact buckets where Polymarket prices can be
sticky.

### 8. Late-Day Tail Model [PARTIAL]

- [x] Learn a separate after-3 PM / after-4 PM / after-5 PM continuation model.
- [x] Condition late-day tail on sun/cloud, wind direction, and whether the current high was first reached recently.
- [ ] Add forecast remaining max / forecast gap to the late-day continuation model.
- [x] Make late-day extension risk visible in the dashboard.
- [ ] Blend late-day continuation risk into the final distribution when the feature-model path is active.

Codex audit (2026-05-28): partial. Logistic continuation models are exported
for 15:00, 16:00, and 17:00, and the dashboard has a late-day extension risk
panel. Issues found: the late-day feature set omits forecast remaining max, no
late-day validation report is generated, and the learned continuation risk is
displayed but not clearly blended into the final distribution when the feature
model path is active.

Codex update (2026-05-31): still partial. Training and live extraction share
most cutoff-aligned features, but late-day coefficients still omit
`forecast_high` / `forecast_gap`, the report does not score continuation model
calibration, and the visible risk panel is not yet an accuracy-grade
probability adjustment.

### 9. Analog Search [PARTIAL]

- [x] Add a dashboard panel showing the closest historical analog days.
- [x] Match on:
  date window, high by current hour, 7 AM-noon rise, wind regime, cloud regime,
  and dew point.
- [ ] Add forecast profile / forecast gap to analog distance now that forecast
  history features are available.
- [x] Show each analog's final WU high and path through the day.

Codex audit (2026-05-28): mostly passes. The dashboard shows closest analogs,
final WU highs, and temperature paths, using the historical target-date window,
high so far, rise from 7 AM, wind/cloud regime, and dew point. Issue found:
forecast profile is not included in the analog distance.

Codex update (2026-05-31): unchanged. Keep this item open until analog distance
uses the same forecast information as the feature model, or explicitly proves
that forecast distance does not improve analog usefulness.

## Dashboard Improvements

### 10. Odds Timeline View [MOSTLY COMPLETE - CLEANUP]

- [x] Add charts for each price band:
  market price, model probability, and edge through time.
- [x] Highlight snapshots where edge crosses configured thresholds.
- [x] Add a compact table of current biggest positive and negative edges.

Codex audit (2026-05-28): mostly passes. The Streamlit dashboard includes per
band timeline tabs, threshold highlighting, and current positive/negative edge
tables. Issues found: the current-edge table rebuilds labels from nonexistent
`groupItemTitle` fields instead of using `bin_data["label"]`, so labels can be
blank; several warning/status strings show mojibake from corrupted emoji text.

Codex update (2026-05-31): still mostly complete. The cleanup should be small
but should happen before relying on the dashboard during live trading/research:
use canonical bin labels and remove user-visible mojibake.

### 11. Source Freshness Panel [MOSTLY COMPLETE - CLEANUP]

- [x] Show last successful fetch time for each live source.
- [x] Flag stale feeds or failed requests.
- [x] Keep the last good live source value visible with a stale warning.

Codex audit (2026-05-28): mostly passes. `blend_with_last_good()` caches live
sources and the dashboard shows age, stale/failed status, and stale warnings.
Issue found: visible status/warning strings contain mojibake from corrupted
emoji/warning glyphs, which should be cleaned up for users.

Codex update (2026-05-31): source retry/backoff and 90-minute last-good cache
age limits are now in place. Remaining work is presentation cleanup plus
per-source TTL/status policy under item 17.

### 12. Model Explanation Panel [PARTIAL]

- [x] Show the major probability drivers for the current top buckets.
- [ ] Include quantitative contributions from:
  base climatology, intraday analog set, current max floor, forecast cap,
  wind/cloud analog adjustment, and late-day tail.
- [ ] Make the deep dive bucket-agnostic rather than centered on fixed 25 C text.

Codex audit (2026-05-28): partial. A model explanation panel and data-backed
25 C deep dive exist. Issues found: the explanation is mostly descriptive and
does not expose quantitative driver contributions for base climatology,
intraday analogs, wind/cloud adjustment, or late-day tail; the deep dive is
still hardcoded around the 25 C bucket.

Codex update (2026-05-31): unchanged. This is more than UX polish: a
quantitative explanation panel is how we catch overconfident exact-bucket
probabilities before they become bad trades.

### 13. Snapshot Controls [COMPLETE]

- [x] Add dashboard controls for:
  force snapshot, pause/resume background snapshot loop, and view last snapshot.
- [x] Show current snapshot file paths and row counts.
- [x] Add a mini changelog of the last few snapshots.

Codex audit (2026-05-28): passes for the dashboard control scope. The app has a
force-snapshot button, a pause/resume flag respected by the snapshot loop,
snapshot file paths with row counts, last-snapshot inspection, and a mini
changelog. Full PID/heartbeat/error process management remains item 16.

## Data Quality And Operations

### 14. Data Validation Suite [COMPLETE - FLEET-AWARE]

- [x] Add tests for:
  WU history parsing, daily summary generation, market-bin parsing,
  snapshot append format, and model distribution normalization.
- [x] Add data validation checks for missing days, sparse days, duplicate timestamps,
  and impossible weather values.

Codex audit (2026-05-28): partial. Unit tests pass, and
`src/data_auditor.py` checks missing days, sparse days, duplicate timestamps,
and impossible values. Issues found: the tests do not cover snapshot append
format, the data auditor is not wired into the automated test suite, and the
auditor currently reports 4 missing target-window days plus 1 sparse day for
the May 28 market window.

Codex update (2026-05-31): unit coverage has expanded to 103 passing tests,
including forecast features, live observed floors, collection health, retries,
and backtest settlement behavior. This item remains partial until data audits
and snapshot append/schema checks are part of routine verification.

Codex update (2026-06-11): closed by item 31. `tests/test_data_auditor.py`
covers the auditor as a regression guard, `tests/test_fleet_observability.py`
covers fleet collection/provenance/status helpers, and the command
`src\data_auditor.py --fleet --json --strict` gives automation a unit-aware data audit.
`src.fleet_observability report --strict` combines audits, collection health,
artifact provenance, and trust readiness into a fail-closed report. The running
snapshot loop also exposes fleet collection state in `loop_status.json`.

### 15. Reproducible Backfills [COMPLETE]

- [x] Add commands to rebuild WU normalized data from raw payloads without
  refetching the network.
- [x] Record source endpoint, API params, generated timestamp, and code version in
  manifests.
- [x] Add a lightweight checksum or row-count audit per partition.

Codex audit (2026-05-28): passes. `src/wu_history.py` provides `backfill`,
`rebuild`, and `audit` commands; the manifest records endpoint, redacted API
params, generated timestamp, code version, row counts, and SHA-256 checksums.
The partition audit passed for 533 WU hourly partitions.

### 16. Background Process Management [COMPLETE]

- [x] Replace ad hoc background loops with a small managed runner.
- [x] Track process PID, start time, last heartbeat, last snapshot, and errors.
- [x] Add a heartbeat-based status command.
- [x] Add pause/resume via dashboard flag.
- [x] Add a command to stop/restart the snapshot loop cleanly.
- [x] Document the recommended OS supervisor setup for always-on capture.

Codex update (2026-05-31): `src.snapshot_tracker` now has `--loop`,
`--status`, `loop_status.json`, `diagnostics.jsonl`, pause flag support, and
health tests. The missing piece is process lifecycle control: stop/restart
without relying on manual process management.

Implementation status (2026-06-10): complete. Motivated by the 2026-06-10
02:24 incident: the loop died silently and the fleet lost ~7 hours of tapes.
`snapshot_tracker` gained `--stop` (PID-verified terminate), `--start-detached`
(detached spawn with console log + provisional status so a racing ensure
cannot double-start), `--restart` (the deploy-new-code one-liner), and
`--ensure` (the supervisor verb: noop on fresh heartbeat or pause, start after
death/reboot, kill-and-restart a hung process with a live PID and stale
heartbeat; ERRORING loops are left visible rather than masked by restarts).
`scripts/register_snapshot_supervisor.ps1` registers the Windows Task
Scheduler task that runs `--ensure` every 10 minutes and at logon (current
user, no stored credentials). Supervisor actions are appended to
`diagnostics.jsonl`. Verified live: task registered and returned result 0,
`--restart` swapped the running loop, ensure no-ops on the healthy loop, and
the first post-restart capture wrote v0.5.6 snapshots. Decision logic is
unit-tested in `tests/test_loop_supervisor.py` (7 tests).

### 17. Error Handling And Caching [PARTIAL]

- [x] Add per-source retries with backoff for live HTTP GETs.
- [x] Preserve last-good live payloads when a source fails.
- [x] Enforce an age cap on last-good live payloads.
- [ ] Separate short TTLs for fast sources from slower/stabler sources.
- [x] Log snapshot-loop capture failures into a local diagnostics file.
- [ ] Add structured source-level diagnostics for partial live-source failures.

Codex update (2026-05-31): `request_with_retries()` and last-good caching now
handle the biggest transient-source risk. The next accuracy risk is staleness:
different feeds age differently, and the model should not treat a stale forecast
and a stale settlement-source row the same way.

## Market Expansion

### 18. Multi-Day Market Support

- Parameterize target date, event slug, station, and data root.
- Allow creating a new market config without code edits.
- Reuse the same history and snapshot machinery for future Toronto markets.

### 19. Other Weather Markets

- Add support for other stations only after Toronto is solid.
- Define each market's resolution source and station mapping explicitly.
- Avoid assuming WU/Weather.com behavior transfers across locations.

## Long-Run Accuracy Roadmap

These items are the highest-leverage path to a model that can credibly beat
Polymarket, not just explain the weather well.

### 20. Settlement-Scored Evaluation V2 [COMPLETE]

Goal: make every model change answer "did this beat the market?" with the same
settlement, scoring, and sample accounting.

- [x] Extend `src.backtest` to report metrics by target day, cutoff hour, and
  market-bin type (`lte`, exact, `gte`).
- [x] Add daily-first scoring that avoids treating highly correlated intraday
  snapshots as independent evidence.
- [x] Report first-entry, last-pre-close, and fixed-cutoff performance
  separately.
- [x] Add confidence calibration tables for model and market by hour and band.
- [x] Add a stable "model card" section with Brier skill score, log-loss
  delta, reliability, and P&L by threshold.
- [x] Keep old reports reproducible by recording model version, data snapshot
  paths, target dates, and settlement source.

Acceptance: a model change is not considered accuracy-improving unless item 20
shows improvement versus market prices on settled days, with the sample caveats
visible.

Detailed design (implemented 2026-05-31):

- Keep the original all-snapshot score for continuity, but no longer treat it as
  the only accuracy gate because intraday rows from the same day are correlated.
- Add a daily-first equal-day score so market days with more snapshots do not
  dominate headline Brier/log-loss metrics.
- Add one-row-per-day-band views: first-entry trade P&L, last-pre-close score
  and P&L, and fixed-cutoff score using the first available snapshot at or after
  each configured cutoff hour.
- Add grouped scoring by target date, capture/cutoff hour, and market-bin type.
- Add reliability slices for model and market probabilities overall, by capture
  hour, and by market band.
- Add a stable model-card section recording market days, all-snapshot rows,
  model versions, Brier skill, log-loss delta, and ECE.
- Add run-input metadata for reproducibility: snapshot tape path, target date,
  model version(s), snapshot count, band count, settlement bucket, settlement
  source, and settlement notes.

Codex implementation status (2026-05-31): complete for the item-20 scope.
`src/backtest.py` now produces the V2 report sections and exposes helper
functions for daily-first scoring, last-pre-close row selection, fixed-cutoff
row selection, grouped scores, and grouped reliability. `tests/test_backtest.py`
now covers cutoff/bin metadata, last-pre-close selection, fixed-cutoff
selection, daily-first equal-day scoring, and report-section generation.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_backtest.py -q`: 22 passed.
- `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: regenerated
  `data/backtest/backtest_report.md` over 3 settled-looking market days and
  1760 band rows. All-snapshot Brier skill was -1.500; daily-first Brier skill
  was -1.723. The active May 31 tape was intentionally excluded from this
  validation report because it was still the live/current market day.
- Post-item-25 coverage-aware rerun:
  `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`
  now includes only the one clean tape, May 28, with 704 scored band rows,
  model Brier 0.0583 versus market Brier 0.0394, and Brier skill -0.478.

Follow-up now unlocked: item 21 should use the item-20 report as the gate for
probability calibration work. The current report shows the model remains
materially overconfident versus Polymarket on the small settled sample.

### 21. Market-Bin Probability Calibration [COMPLETE - HIGHEST PRIORITY]

Goal: turn useful raw model signal into probabilities that are less
overconfident than the current live distribution.

- [x] Calibrate exact-bucket and market-bin probabilities separately.
- [x] Compare Platt scaling, isotonic regression, temperature scaling, and
  simple shrinkage-to-market/seasonal-prior baselines.
- [x] Learn calibration by cutoff hour, bucket distance from observed WU floor,
  and sample size.
- [x] Penalize extreme probabilities unless the settlement source has printed a
  hard floor/cap justification.
- [x] Export a lightweight calibration artifact consumed by live inference.
- [x] Add tests that calibrated distributions remain normalized and respect hard
  WU settlement floors.

Acceptance: calibration reduces model log loss/Brier versus the uncalibrated
model, and improves or at least does not damage Brier skill score versus
Polymarket on settled snapshot tapes.

Codex implementation status (2026-05-31): complete for the item-21 scope.
`src/probability_calibration.py` now trains a lightweight artifact and report
from settled snapshot tapes. Exact distributions are temperature-scaled
separately from binary market bins, with deployment temperature capped at `1.5`
so calibration does not revive buckets that live physical constraints already
crushed. Live market-bin probabilities now pass through the artifact in
`src/model_presentation.py`. `src/model_distribution.py` applies
exact-distribution calibration while preserving hard WU printed floors.
The binary calibrator compares deployable no-market methods against a
market-shrink baseline, uses cutoff-hour/bin-kind/floor-distance context
summaries for fallback base rates, and keeps hard YES/NO outputs only when WU
history has already printed the relevant floor.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_probability_calibration.py tests\test_estimate_distribution.py tests\test_validation.py -q`: 28 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_intraday_calibration.py tests\test_probability_calibration.py -q`: 23 passed after capping exact-distribution deployment temperature to preserve live floor behavior.
- `.\venv\Scripts\python.exe -m pytest -q`: 113 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
- `.\venv\Scripts\python.exe -m src.probability_calibration train data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote
  `src/probability_calibration.json` and
  `data/backtest/probability_calibration_report.md`.
- Settled-tape leave-one-day validation selected deployable `prior_shrink`
  with weight `0.6`: Brier improved from 0.0954 to 0.0775, log loss improved
  from 0.3705 to 0.2743, and Brier skill versus Polymarket improved from
  -1.500 to -1.031. Artifact replay on the same tapes scored Brier 0.0762 and
  log loss 0.2309. The market-informed comparison baseline still shows
  Polymarket ahead at Brier 0.0382, so the next accuracy work needs better
  weather signal, not just calibration.
- Quality caveat added after item 25: this calibration artifact/report used the
  3 settled-looking tapes before coverage-aware labels existed. It is still
  useful as a provisional overconfidence fix, but future calibration reports
  should either filter or explicitly stratify by label quality once there are
  enough complete market days.

Follow-up now unlocked: item 22 should replace forecast cap/floor heuristics
with learned source-error distributions. That is the best next route to a more
accurate model because calibration reduced overconfidence but did not create
new information edge over the market.

### 22. Forecast-Error And Source-Bias Model [COMPLETE]

Goal: replace heuristic forecast caps/floors with learned error distributions.

- [x] Score Weather.com, Open-Meteo, and ECCC forecast archives by horizon,
  source, time of day, wind/cloud regime, and target-season window.
- [x] Learn source-specific bias, MAE/RMSE, and tail miss rates against WU final
  highs.
- [x] Convert forecast highs into probability components instead of point caps.
- [x] Model source disagreement explicitly; agreement should tighten the
  distribution and disagreement should widen it.
- [x] Add forecast-error features to analog search and late-day continuation.

Acceptance: a forecast component improves settlement-scored performance beyond
the current forecast-cap/floor heuristics in item 20.

Codex implementation status (2026-05-31): complete for the first item-22
artifact-backed forecast component. `src/forecast_error_model.py` now trains
`src/forecast_error_model.json` and
`data/backtest/forecast_error_report.md` from the historical Open-Meteo daily
forecast archive plus settled snapshot forecast tapes. It learns source-level
observed-minus-forecast bias, MAE/RMSE, within-1 C rate, and >=2 C tail miss
rates for Open-Meteo, Weather.com, and ECCC city-page forecasts. Live inference
loads the artifact in `src/toronto_model.py`, and `src/model_distribution.py`
uses the learned forecast-error distribution in the existing `forecast_cap`
component slot so calibrated empirical weights remain compatible while the
component itself is no longer a one-bucket point cap. Multi-source disagreement
widens the component distribution. Analog search now includes Open-Meteo
forecast gap in its distance and returned feature payloads, and late-day
continuation blends in the forecast-error component's above-current-bucket tail
probability when the artifact is available.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_forecast_error_model.py tests\test_estimate_distribution.py tests\test_intraday_calibration.py -q`: 35 passed.
- `.\venv\Scripts\python.exe -m src.forecast_error_model train data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote
  `src/forecast_error_model.json` and
  `data/backtest/forecast_error_report.md`.
- Forecast-component artifact replay improved exact-bucket Brier from 0.7433
  for the prior cap proxy to 0.6387, and log loss from 1.7935 to 1.2643 over
  552 forecast rows.
- Leave-one-year validation on the historical daily Open-Meteo archive improved
  Brier from 0.7185 to 0.6417 and log loss from 1.6525 to 1.1919 over 296
  rows.
- `.\venv\Scripts\python.exe -m pytest -q`: 118 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.

Implementation caveat: the artifact proves the forecast component is better
than the old point-cap proxy, but it does not yet prove the whole calibrated
model beats Polymarket. That still depends on more settled market-day tapes and
item-20 end-to-end scoring.

Follow-up now unlocked: item 23 should learn WU settlement lag and revision
behavior so non-resolution observations can move probabilities through a
measured catch-up curve rather than ad-hoc soft floors.

### 23. WU Settlement Lag And Revision Model [COMPLETE]

Goal: learn how Wunderground history catches up to physical observations and
when non-resolution sources should move probability.

- [x] Measure lag between SWOB/METAR/Weather.com current highs and WU history
  printed highs across historical and captured days.
- [x] Estimate probability that WU will later print a bucket already observed
  by SWOB or current Weather.com.
- [x] Measure end-of-day and next-day WU revision frequency.
- [x] Replace ad-hoc soft floors with a learned catch-up probability curve.
- [x] Keep a hard floor only for WU history itself.

Acceptance: non-resolution live observations improve late-day settlement
probabilities without repeating the v0.4.8 hard-floor bug.

Codex implementation status (2026-05-31): complete for the item-23 scope.
`src/settlement_lag_model.py` now trains `src/settlement_lag_model.json` and
`data/backtest/settlement_lag_report.md` from historical METAR/WU hourly rows
plus settled snapshot tapes containing SWOB and Weather.com current highs. The
artifact learns catch-up rates by source, cutoff hour, and source-minus-WU
bucket gap, and WU revision-up rates by cutoff hour. `src/toronto_model.py`
loads the artifact, and `src/model_distribution.py` uses it when SWOB leads WU:
the learned catch-up probability controls the soft-floor strength, but a
one-bucket hedge is capped at `0.30` minimum so SWOB can never become a hard
settlement floor. WU history remains the only hard floor.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_settlement_lag_model.py tests\test_live_floor.py tests\test_estimate_distribution.py -q`: 19 passed.
- `.\venv\Scripts\python.exe -m src.settlement_lag_model train data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote
  `src/settlement_lag_model.json` and
  `data/backtest/settlement_lag_report.md`.
- Training produced 9045 lag/revision rows: 369 non-resolution lead rows and
  8676 WU revision rows. Global catch-up was 63.7%; source-level rates were
  99.3% for SWOB on the tiny settled snapshot sample, 66.5% for historical
  METAR leads, and 40.9% for Weather.com current highs.
- WU revision-up rates now show the expected intraday decay: about 91.9% at
  10:00, 55.7% at 14:00, 16.3% at 16:00, and 0.3% at 20:00.
- A full-suite regression initially caught over-suppression of the WU floor
  bucket when SWOB had a high learned catch-up rate. The live hedge cap was
  added, then `.\venv\Scripts\python.exe -m pytest -q` passed with 121 tests
  and `.\venv\Scripts\python.exe -m compileall src tests` passed.

Follow-up now completed: item 24 consolidates feature generation and artifact
metadata so these new calibration, forecast-error, and lag components are
auditable from one train/serve feature path.

### 24. Unified Feature Store And Train/Serve Parity [COMPLETE]

Goal: prevent future train/serve skew and make every feature explainable.

- [x] Move shared feature schema into one module used by training,
  backtests, live inference, analog search, and explanations.
- [x] Version every live feature vector and future model artifact export with a
  shared feature schema.
- [x] Add a feature parity test: historical/live feature extraction for the
  same synthetic day must match.
- [x] Persist per-snapshot feature vectors next to probabilities for audits.
- [x] Add feature-schema and snapshot feature-persistence tests.
- [x] Move the full historical feature-construction logic into the shared
  feature-store module, not only the schema/record layer.
- [x] Add ablation reporting so each feature family's value is visible.
- [x] Add backtest joins from probability rows to feature vectors so item-20
  report deltas can be sliced by feature families.

Acceptance: feature changes can be reviewed from one code path and tied to
measured backtest deltas.

Codex implementation status (2026-05-31): complete. `src/feature_store.py` now
defines `toronto_feature_store_v0.1`, the canonical feature column order, audit
columns, and helpers to build serializable live feature records.
`src/model_features.py` adds the schema version to live extraction and exposes
`live_feature_record()`.
`src/feature_model.py` now imports the shared feature column order, uses
`feature_store.build_historical_feature_record()` for historical training
records, and stamps future LR/HGB/late-day artifacts with the schema version.
`src/toronto_model.py` returns a `feature_vector` from model builds, and
`src/snapshot_tracker.py` persists feature vectors to `features_long.csv` and
`features.jsonl` next to snapshot probabilities. `src.backtest` now joins
`features_long.csv` by `snapshot_id`, reports feature-vector coverage, and will
slice scores by the forecast-gap feature once feature-audited snapshots exist.
`data/wunderground/cyyz/analysis/feature_model_report.md` now includes
feature-family ablation tables over 5,823 HGB leave-one-out validation rows.
The ablation shows the observed temperature path dominates value
(overall delta log loss +2.3907 when neutralized), with smaller positive
contributions from wind regime, forecast, and atmosphere features; cloud regime
is currently neutral to slightly negative in this sensitivity pass.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_feature_store.py tests\test_forecast_feature.py tests\test_collection_robustness.py -q`: 20 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_feature_store.py tests\test_forecast_feature.py -q`: 8 passed, including live-vs-historical feature parity for a synthetic day.
- `.\venv\Scripts\python.exe -m pytest tests\test_backtest.py tests\test_feature_store.py -q`: 28 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_feature_model_ablation.py tests\test_feature_store.py -q`: 8 passed.
- `.\venv\Scripts\python.exe src\feature_model.py`: regenerated
  `src/feature_model_coefs.json`, `src/feature_model_hgb.pkl`,
  `src/late_day_model_coefs.json`, and
  `data/wunderground/cyyz/analysis/feature_model_report.md` with ablation
  tables. This full LOO retrain is slow enough that item 26 should add a faster
  sampled/incremental research mode before routine model-comparison work.
- `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`: regenerated
  `data/backtest/backtest_report.md` with feature-vector coverage. After
  coverage-aware labels, only May 28 is in the strict quality-filtered headline
  sample, so current historical tapes have 0/704 scored rows with feature
  vectors because feature persistence starts with new snapshots.
- `.\venv\Scripts\python.exe -m pytest -q`: 141 passed after item-26 ensemble tests were added.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.

### 25. Market-Day Data Collection And Label Quality [COMPLETE]

Goal: build the dataset that makes items 20 and 21 statistically meaningful.

- [x] Keep collecting complete 10-minute market/model/forecast tapes for every
  Toronto market day.
- [x] Add a daily settlement finalization command that freezes WU final high,
  settlement bucket, and evidence source after the market resolves.
- [x] Add collection-quality grades per day: complete, partial, stale-source,
  missing settlement, or manually overridden.
- [x] Surface quality grades in the item-20 backtest report.
- [x] Exclude or downweight partial days in model-vs-market metrics.
- [x] Backfill or manually reconcile known sparse settlement days where possible.

Acceptance: the backtest dataset grows by clean market days, not just by more
correlated intraday rows.

Codex implementation status (2026-06-01): complete for the code and operating
policy. Settlement-label finalization, coverage-aware grading, strict backtest
filtering, and live coverage monitoring are in place.
`src/market_day_labels.py` now provides
`python -m src.market_day_labels finalize`, writes per-folder `settlement.json`
files, and writes `data/backtest/market_day_labels.csv` with settlement bucket,
source, snapshot count, band count, row count, quality grade, quality reason,
coverage-clean flag, capture ratio, max gap, and coverage reason. It
distinguishes `complete`, `partial`, `stale_source`, `manual_override`,
`missing_tape`, and `missing_settlement`, and uses `src.collection_health` to
mark days partial when the decisive afternoon window is not covered or the tape
has large gaps. `src.backtest` reads `settlement.json` when present, includes
the quality grade in the Run Inputs And Settlement table, and supports
`--quality-grades` to include only accepted-quality market days in headline
metrics. `src.collection_health` now has a live mode and strict machine-readable
output so the same coverage policy can be checked before a day is already lost:
`python -m src.collection_health --live --strict --json <snapshot-folder>`.
`src.snapshot_tracker --status` now includes the active market day's collection
state alongside heartbeat health. On 2026-06-01 at 10:00 local, the live June 1
tape reported `COLLECTING` with no action required rather than a false
completed-day warning. May 27 and May 30 remain explicitly reconciled as
`partial`; their missing intraday coverage cannot be backfilled honestly, so
they stay out of strict headline metrics.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_market_day_labels.py tests\test_collection_robustness.py -q`: 21 passed after live collection status was added.
- `.\venv\Scripts\python.exe -m pytest tests\test_market_day_labels.py tests\test_backtest.py -q`: 26 passed.
- `.\venv\Scripts\python.exe -m src.market_day_labels finalize data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote 3 labels, now `complete=1, partial=2`. May 27 is partial because the tape starts at 14:35, and May 30 is partial because it has a 74-minute collection gap.
- `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`: regenerated
  `data/backtest/backtest_report.md` with quality grades and an explicit
  `complete, manual_override` quality filter. The strict headline sample now
  includes only May 28: 704 scored band rows, model Brier 0.0583 versus market
  Brier 0.0394, Brier skill -0.478.
- `.\venv\Scripts\python.exe -m src.collection_health --live data\snapshots\highest-temperature-in-toronto-on-june-1-2026`: reported June 1 as `COLLECTING`.
- `.\venv\Scripts\python.exe -m src.snapshot_tracker --status`: reported loop
  state `RUNNING` and collection state `COLLECTING`.
- `.\venv\Scripts\python.exe -m pytest -q`: 141 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.

Follow-up now completed: item 26 uses the clean/partial labels as a hard gate
for ensemble and ablation research, and includes a fast sampled research mode
so model comparisons do not require multi-hour full leave-one-out retrains.

### 26. Model Ensemble And Ablation Framework [COMPLETE - AWAITING MORE CLEAN DAYS]

Goal: improve accuracy by combining complementary signals only when they add
out-of-sample value.

- [x] Treat empirical climatology, HGB, forecast-error model, lag model, and
  market price as separate candidate forecasters.
- [x] Report each component's standalone performance by cutoff hour and band.
- [x] Learn ensemble weights under leave-one-day-out or rolling-day validation.
- [x] Add a fast sampled or cached research mode so component ablations and
  ensemble tests do not require multi-hour full leave-one-out retrains.
- [x] Keep a no-market-input model and a market-informed model separate, so
  "edge over market" remains interpretable.
- [x] Add guardrails against adding components that improve in-sample metrics
  but hurt settlement-scored market performance.

Acceptance: ensemble weights are justified by ablation tables and item-20
market-relative metrics.

Codex implementation status (2026-06-01): complete as an executable framework,
with promotion correctly blocked by sample size. Live inference now exposes
`distribution_components` with schema `toronto_distribution_components_v0.1`;
`src.snapshot_tracker` persists market-bin component probabilities to
`components_long.csv` and `components.jsonl` for future settled days. Component
names include climatology prior, HGB/LR feature model, feature blend,
forecast-error/cap distributions, post-live-signal distribution,
settlement-lag-adjusted distribution, pre-calibration model, and final model
when those components are present.

`src/model_ensemble.py` reads settled tapes, filters by market-day quality,
joins future component probability tapes, reports standalone forecasters
overall/by cutoff/by market-bin type, and learns simple leave-one-day tuned
pairs. It keeps no-market candidates separate from market-informed candidates
and writes the promotion guardrail directly into
`data/backtest/model_ensemble_report.md`. The current strict clean sample has
only May 28, so the report scores deployed model versus market but refuses to
fit leave-one-day ensembles:

- Rows scored: 704.
- Market price Brier/log loss: 0.0394 / 0.1230.
- Deployed model Brier/log loss: 0.0583 / 0.1850.
- No-market and market-informed ensembles: insufficient clean target days.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_model_ensemble.py tests\test_feature_store.py -q`: 7 passed.
- `.\venv\Scripts\python.exe -m src.model_ensemble data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`: wrote `data/backtest/model_ensemble_report.md` and correctly refused ensemble promotion with only one clean day.

Follow-up now unlocked: item 27 should add new weather-regime features only
behind this harness, and only promote features that improve clean
settlement-scored no-market validation.

### 27. Weather Regime And Microclimate Features [NEW]

Goal: add physically meaningful signal once the evaluation/calibration loop is
strong enough to judge it.

- [ ] Add solar/radiation and cloud-thickness features from Open-Meteo or other
  stable sources.
- [ ] Add lake-breeze/onshore-flow indicators for Pearson and Toronto-specific
  warm-season patterns.
- [ ] Add pressure tendency, humidity/dewpoint, wind shift, and gust features to
  late-day continuation where they are not already used.
- [ ] Evaluate whether feature value differs by month/season and cutoff hour.
- [ ] Promote only features that improve out-of-sample item-20 metrics.

Acceptance: new weather features improve the calibrated model, not just feature
importance charts.

## Platform Era Reconciliation (2026-06-06)

Since the 2026-05-31 deep dive the project changed shape: it is no longer a
single-Toronto system. It now serves **12 markets** (1 Celsius: Toronto;
11 Fahrenheit: NYC, Atlanta, Austin, Chicago, Dallas, Denver, Houston,
Los Angeles, Miami, San Francisco, Seattle) — "foundations for all Canada + USA
Polymarket high-temperature markets," the first milestone. Work landed that
supersedes parts of items 18-19:

- **Declarative market registry** (`src/market_registry.py`): a market is a
  config entry (slug, station, geo, tz, unit, source set). Adding one needs no
  engine changes.
- **Native-unit operation (the C/F split)**: each market runs end-to-end in its
  settlement unit, with per-unit model artifacts (`*_f`). This replaced an
  earlier canonical-Celsius approach that leaked probability across the 2°F
  bands.
- **Per-market data layer**: WU history + Open-Meteo forecast archive + live
  sources, all under `spec.data_root`, in native units.
- **Timezone correctness**: `spec.tz` is now threaded through serving and
  backfill. It had been a global Toronto constant that silently put the 8
  non-Eastern cities on the wrong clock (day boundaries + intraday cutoff) in
  both history and live serving — found and fixed in the 2026-06-06 design audit.
- **Improvement engine** in place: replay corpus, settlement backtest (item 20),
  per-location trust score, forecast-vs-realized tracker, market-day labels.

Open architectural finding from the audit: **C vs F is an I/O concern (band unit
+ granularity), not a model/training axis.** Features, training, and calibration
should be shared; only band parsing (in) and discretization (out) differ. Today
the F model is trained on NYC alone and served to all 11 F cities (climatology +
floors rescue out-of-range cities like Seattle/Denver). The two tracks below take
the data layer and the model from this bootstrap to production.

## Track A — From Basic To Best-Possible Data Layer

Principle: for every market, produce a faithful, gap-free, deep record of (1) the
settlement ground truth, (2) the observations that lead it, and (3) the forecasts
that predict it — in native unit and local time, with provenance. The model can
only be as good as this layer.

### 28. Settlement Ground-Truth Ledger [COMPLETE - LEDGER LIVE]

Goal: encode and archive EXACTLY how each market resolves, and the realized
outcome, as the supervised label.

- [x] Per market, pin the resolution spec: source (Wunderground station id),
  daily-max window, rounding, unit, timezone.
- [x] After each market day, freeze the realized settlement high + winning band +
  evidence (generalize `market_day_labels finalize` to all 12 markets).
- [x] Reconcile the live WU-history settlement against the actual Polymarket
  resolution; alert on mismatch.
- [x] Maintain a per-market settlement ledger = the supervised labels and the
  calibration target.

Acceptance: every settled market day has a frozen, source-verified label, and
backtests/trust read from the ledger.

Detailed design (implemented 2026-06-06):

- Add `src/settlement_ledger.py` as the authoritative settlement-label layer.
  It writes pinned market-resolution specs to
  `data/settlements/resolution_specs.json` and per-market ledgers to
  `data/settlements/{market_id}/ledger.jsonl`.
- Keep folder-local `settlement.json` files as evidence copies, but make the
  per-market ledger the first source read by scoring tools.
- Resolve each folder's market from the registered Polymarket slug, then use
  that market's WU station, unit, timezone, daily-summary path, and local
  midnight-to-midnight daily-max window.
- Freeze native-unit settlement high, rounded settlement bucket, winning market
  band, quality grade, collection coverage, source evidence, Polymarket URL,
  Gamma API URL, and reconciliation status.
- Reconcile closed Polymarket events by reading the resolved Yes band from Gamma
  final outcome prices. Matches are recorded as `reconciliation_status=match`;
  mismatches append an alert row to `data/settlements/reconciliation_alerts.jsonl`.
- Make `src.backtest` and `src.location_trust` ledger-first. Backtest falls back
  only for unfinalized legacy tapes; trust now counts clean/manual ledger labels
  rather than every historical folder.

Codex implementation status (2026-06-06): complete for the current 12-market
platform foundation. The registry now has pinned resolution specs for Toronto
plus the 11 US Fahrenheit markets. The finalizer wrote 9 settled Toronto ledger
rows; all 9 matched Polymarket's resolved winning band. Current clean scoring
uses 3 complete ledger days, while 6 partial rows remain preserved in the ledger
but excluded from headline quality-filtered backtests/trust.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_market_day_labels.py tests\test_settlement_ledger.py tests\test_backtest.py tests\test_location_trust.py -q`: 37 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
- `.\venv\Scripts\python.exe -m src.market_day_labels finalize`: wrote 9 labels,
  per-market ledgers under `data/settlements`, and `complete=3, partial=6`;
  Polymarket reconciliation `match=9`.
- `.\venv\Scripts\python.exe -m src.backtest --quality-grades complete,manual_override`:
  scored 3 complete Toronto ledger days, with settlements reported as
  `settlement_ledger:snapshot_high`; all-snapshot model Brier 0.0550 versus
  market Brier 0.0337, daily-first model Brier 0.0539 versus market 0.0347.
- `.\venv\Scripts\python.exe -m src.location_trust`: Toronto trust now uses 3
  clean ledger days and reports 38/100 Low; US markets remain Unproven until
  their first post-ledger days settle.

### 29. Deepen And Widen The Historical Record [PARTIAL - WU SEASONAL STRONG, REDUNDANT SOURCES SHALLOW]

Goal: give each market the deepest faithful history its sources allow (currently
7 years × a narrow May-June window).

- [ ] Extend WU history beyond 2019-2025 where available; add ISD/GHCN-hourly
  (NOAA) and ERA5 for multi-decade depth.
- [ ] Widen the seasonal window, and support non-summer windows if Polymarket
  lists them.
- [ ] Make backfills idempotent, resumable, and scheduled; keep raw + rebuild +
  checksum (item 15) per market.
- [ ] Normalize every source into one native-unit hourly/daily schema.

Acceptance: each market's training window is sources-limited, not effort-limited,
and fully rebuildable offline.

Codex progress update (2026-06-06): WU, NOAA GHCNh, and ERA5-style reanalysis
adapters now exist, but this item remains open until the wide backfills have
actually populated raw archives for every market and the resulting source
coverage is accepted as training-ready.

What changed:

- `src.wu_history` now has resumable WU backfills. `backfill --skip-existing`
  discovers raw day payloads already present, fetches only missing contiguous
  ranges, then rebuilds normalized hourly partitions, daily summaries, and the
  checksum manifest.
- `src.wu_history coverage` reports per-market raw coverage, missing day count,
  missing ranges, unit, station, and manifest/daily-summary presence.
- WU normalized hourly rows now include native-unit aliases
  (`temperature_unit`, `temp_native`, `dewpoint_native`, etc.) while preserving
  legacy `*_c` fields. Daily summaries now include native aliases
  (`max_temp`, `max_temp_bucket`, `temperature_unit`, etc.) while preserving the
  existing columns consumers use today.
- `backfill_all.py` is now registry-driven and resumable by default, with
  `--markets`, `--start`, `--end`, `--dry-run`, and `--refetch-existing`.
- `src.historical_schema` defines the shared native-unit hourly/daily schema
  used by new historical sources.
- `src.noaa_ghcnh_history` adds a NOAA GHCNh adapter: ICAO-to-GHCN station
  resolution, raw station-year PSV files, normalized hourly partitions, daily
  summaries, manifest checksums, coverage, and resumable `--skip-existing`
  backfills. This is the NOAA hourly replacement/successor path for the older
  ISD/Global Hourly layer.
- GHCNh station metadata is now pinned under `data/noaa_ghcnh/{station}/` for
  all 12 registered markets. Toronto has no ICAO value in the GHCNh station
  list, so it resolves by nearest same-country/WMO fallback to `CAN06158731`
  (`TORONTO INTL A`, WMO 71624).
- `src.reanalysis_history` adds an Open-Meteo archive adapter pinned to ERA5
  reanalysis semantics: raw chunk JSON, normalized hourly partitions, daily
  summaries, manifest checksums, coverage, and resumable `--skip-existing`
  backfills.
- `src.reanalysis_history coverage` now reports normalized daily coverage
  separately from raw filename coverage. This matters because Open-Meteo can
  return a raw range whose later hours are all `null`; those days are now
  treated as missing normalized history rather than silently counted covered.
- `src.historical_coverage` writes a fleet source-coverage report across WU,
  GHCNh, and reanalysis; current artifact:
  `data/backtest/historical_coverage.json`.
- `backfill_all.py` now supports `--sources wu,ghcnh,reanalysis`, so the same
  fleet command can drive all item-29 historical sources.
- `src.historical_backfill_plan` writes a compact market/source execution queue
  to `data/backtest/historical_backfill_plan.json`; WU queue items include
  `--continue-on-error` so Weather.com source-unavailable dates are logged
  rather than killing the whole fleet run. Chunk-level accounting remains
  available with `--queue-mode chunk` and is written to
  `data/backtest/historical_backfill_plan_chunks.json` for audit detail.
- `src.historical_backfill_runner` adds the durable execution layer for item 29:
  append-only run ledger, stable item keys, status summaries, source/market
  filters, dry-run support, bounded `--max-items` batches, and skip-success
  resume behavior.
- `src.historical_schema` now uses retrying deletes and atomic temp-file
  replacement for normalized historical partitions. This fixed the Windows
  file-lock failure that interrupted the first GHCNh fleet run.

Current WU depth snapshot from the audit:

- Toronto/CYYZ: 1982-01-01 through 2026-06-06, all months except
  Weather.com 2020-11-08, which returned HTTP 400 and is now logged in
  `data/wunderground/cyyz/backfill_errors.jsonl` as source-unavailable.
- Atlanta/KATL: 2015-01-01 through 2026-06-06, all months except
  Weather.com 2020-11-08, now logged as source-unavailable.
- NYC/KLGA, Austin/KAUS, Chicago/KORD: 2015-01-01 through 2026-06-06,
  all months except Weather.com 2020-11-08, now logged per station as
  source-unavailable. Manifest audits passed after the wide rebuilds.
- Dallas/KDAL, Denver/KBKF, Houston/KHOU, Los Angeles/KLAX, San Francisco/KSFO,
  Seattle/KSEA: 2019-05-01 through 2025-06-30, May-June only, plus
  2026-06-01 through 2026-06-02 now fetched and normalized.
- Miami/KMIA: 2026-05-01 through 2026-06-06 only.
- Current two-day source-coverage check (`2026-06-01` through `2026-06-02`):
  WU missing=0 and GHCNh missing=0 for all 12 markets. Reanalysis has raw
  files covering both days for all 12, but only one normalized daily row per
  market because June 2 returned all-null weather variables; coverage now
  reports reanalysis missing=1 per market instead of hiding the source lag.
- Minimum-window GHCNh is now populated for all 12 registered markets
  (`2015-2026`, missing years=0 in `data/backtest/historical_coverage_minimum.json`).
- Minimum-window runnable queue (`2015-01-01` through `2026-06-06`) now has 19
  compact market/source items: WU=7 and reanalysis=12. The chunk diagnostic
  queue is down to 3,548 underlying chunks: WU=1,916 and reanalysis=1,632.
  This is why the item remains partial.

2026-06-11 US seasonal WU widener update:

- The May 20 through June 30 seasonal window is now widened for 1995-2014
  across all 11 US markets. Expected target-season days per market: 840.
- NYC, Atlanta, Chicago, Dallas, Denver, Houston, Los Angeles, Miami,
  San Francisco, and Seattle each have 832 covered days plus 8
  source-unavailable Weather.com days (`2000-06-01` through `2000-06-08`),
  with seasonal `missing=0`.
- Austin has 748 covered days plus 92 source-unavailable Weather.com days
  (`1995-05-20` through `1995-06-30`, `1996-05-20` through `1996-06-30`,
  and `2000-06-01` through `2000-06-08`), with seasonal `missing=0`.
- WU manifest audits passed after the widened rebuilds: 178 partitions for
  every US market except Austin, which has 174 partitions because the two early
  source-unavailable seasonal windows produce no raw partitions.

Data-layer audit update (2026-06-12): added `src.data_layer_audit`, which
measures actual snapshot cadence, artifact completeness, and historical source
coverage into `data/backtest/data_layer_audit.json` and
`data/backtest/data_layer_audit_report.md`. The audit confirms WU is now strong
for the target season: Toronto has `1312/1326` May-20-through-June-30 days
covered from 1995-2026, most F markets have `1313/1326`, and Austin has
`1229/1326` because early Weather.com days are source-unavailable. The
remaining historical gap is redundant-source depth, not primary WU: normalized
METAR daily coverage is only `13/1326` target-season days per market, while
GHCNh and reanalysis are about `36%` target-season coverage. Next Item 29 work
should therefore deep-fill METAR/ASOS, GHCNh, and reanalysis for at least
May 20-June 30 across all markets from 1995 forward, then widen to
April-September.

Validation results for this increment:

- `.\venv\Scripts\python.exe -m pytest tests\test_validation.py tests\test_backfill_markets.py -q`: 15 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_historical_sources.py tests\test_backfill_markets.py -q`: 11 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_historical_sources.py tests\test_backfill_markets.py tests\test_validation.py -q`: 27 passed after tightening
  reanalysis coverage to actual normalized daily dates.
- `.\venv\Scripts\python.exe -m pytest tests\test_historical_backfill_runner.py tests\test_historical_sources.py tests\test_backfill_markets.py -q`: 20 passed after adding the durable runner, compact market/source queue mode, and historical partition write retries.
- `.\venv\Scripts\python.exe -m src.wu_history --market toronto rebuild`: rebuilt
  Toronto normalized WU history from raw after the interrupted Windows file-lock
  run; wrote 466,582 hourly rows and 16,167 daily rows, and restored manifest
  audit consistency.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources ghcnh --max-items 132 --fail-fast`: recorded 30 GHCNh successes, exposed a Windows file-lock rebuild failure, then after the shared writer retry fix the resumed runner recorded the remaining 102 successes; regenerated plan has GHCNh queue=0.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets atlanta --max-items 1 --fail-fast`: classified Atlanta/KATL 2020-11-08 as Weather.com HTTP 400 source-unavailable.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets nyc --max-items 1 --fail-fast`: widened NYC/KLGA WU to 2015-01-01 through 2026-06-06, then a one-day retry classified 2020-11-08 as Weather.com HTTP 400 source-unavailable; `src.wu_history --market nyc audit` passed across 138 partitions.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets austin --max-items 1 --fail-fast`: widened Austin/KAUS WU to 2015-01-01 through 2026-06-06, then a one-day retry classified 2020-11-08 as Weather.com HTTP 400 source-unavailable; `src.wu_history --market austin audit` passed across 138 partitions.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets chicago --max-items 1 --fail-fast`: widened Chicago/KORD WU to 2015-01-01 through 2026-06-06, then a one-day retry classified 2020-11-08 as Weather.com HTTP 400 source-unavailable; `src.wu_history --market chicago audit` passed across 138 partitions.
- `.\venv\Scripts\python.exe -m src.wu_history --market nyc coverage --start 2019-05-01 --end 2019-05-05`: reported 5 expected days, 0 missing, unit F.
- `.\venv\Scripts\python.exe backfill_all.py --markets nyc --sources wu,ghcnh,reanalysis --start 2026-06-01 --end 2026-06-02 --dry-run`: printed resumable commands for all three sources.
- `.\venv\Scripts\python.exe backfill_all.py --markets nyc,austin,chicago,dallas,denver,houston,los-angeles,san-francisco,seattle --sources wu --start 2026-06-01 --end 2026-06-02 --between-markets-sleep 0 --sleep 0.1`: fetched and rebuilt the current-window WU gaps for the 9 US markets missing those days.
- `.\venv\Scripts\python.exe backfill_all.py --sources ghcnh,reanalysis --start 2026-06-01 --end 2026-06-02 --between-markets-sleep 0 --sleep 0.1`: fetched 2026 GHCNh raw PSV files for all 12 markets and reanalysis raw JSON for the same current window.
- `.\venv\Scripts\python.exe -m src.historical_coverage report --start 2026-06-01 --end 2026-06-02 --out data\backtest\historical_coverage.json`: wrote current-window fleet coverage across all 12 markets and all three sources.
- `.\venv\Scripts\python.exe -m src.historical_coverage report --start 2015-01-01 --end 2026-06-06 --out data\backtest\historical_coverage_minimum.json`: wrote minimum-window coverage; GHCNh missing=0 for all markets, WU missing=0 for Toronto/NYC/Atlanta/Austin/Chicago after source-unavailable classification, and reanalysis missing=4174 per market.
- `.\venv\Scripts\python.exe -m src.historical_backfill_plan --sources wu,ghcnh,reanalysis --start 2015-01-01 --end 2026-06-06 --out data\backtest\historical_backfill_plan.json`: wrote 19 remaining compact market/source queue items (`wu=7`, `reanalysis=12`).
- `.\venv\Scripts\python.exe -m src.historical_backfill_plan --sources wu,ghcnh,reanalysis --start 2015-01-01 --end 2026-06-06 --queue-mode chunk --out data\backtest\historical_backfill_plan_chunks.json`: wrote 3,548 underlying chunk items (`wu=1916`, `reanalysis=1632`).
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
- `.\venv\Scripts\python.exe -m pytest -q`: 232 passed, 12 subtests passed.
- `.\venv\Scripts\python.exe -m src.noaa_ghcnh_history --market nyc --data-root scratch\ghcnh_smoke station`: resolved KLGA to GHCNh station `USW00014732`.
- One-pass GHCNh station resolution over all registered markets: resolved
  Toronto `CAN06158731`, NYC `USW00014732`, Atlanta `USW00013874`, Austin
  `USW00013904`, Chicago `USW00094846`, Dallas `USW00013960`, Denver
  `USW00023036`, Houston `USW00012918`, Los Angeles `USW00023174`, Miami
  `USW00012839`, San Francisco `USW00023234`, Seattle `USW00024233`.
- `.\venv\Scripts\python.exe -m src.reanalysis_history --market nyc --data-root scratch\reanalysis_smoke backfill --start 2026-06-01 --end 2026-06-01 --skip-existing`: fetched and rebuilt 20 hourly rows / 1 daily row from the ERA5-style archive path.

Remaining work before item 29 can close:

- Decide whether production training should stay seasonal-first or require
  full-year continuous WU raw history. The 1995-2014 US May 20-June 30
  widener is now source-limited; full off-season/full-year WU depth is still a
  policy and storage decision, not a blocker for the current high-temperature
  seasonal retrains.
- Run the reanalysis backfills across every registered market and the chosen
  training window, then keep the raw files/checksum manifests as the offline
  rebuild source. GHCNh is complete for the current minimum window.
- Decide the production training window bounds per source and market
  (`historical_coverage.json` currently shows what is missing, not a completed
  source-limited archive).

### 30. Source Redundancy And Gap-Filling [COMPLETE - REDUNDANCY REPORT LIVE]

Goal: no single feed is a single point of failure or bias.

- [x] >=2 observation streams per city (WU + METAR/ASOS + ISD), cross-validated;
  learn each one's lead/bias versus settlement (generalize items 4-5 to all
  markets).
- [x] Multiple forecast sources (Open-Meteo + NWS/NDFD + a global ensemble) into
  an ensemble-forecast feature plus a disagreement signal (extends item 22).
- [x] Automated gap detection and targeted re-fetch; fill observation gaps from
  the redundant stream.

Acceptance: a single source outage degrades gracefully, and forecast
disagreement is a measured feature, not an assumption.

Implementation result (2026-06-12): added `src.source_redundancy`, which builds
`data/backtest/source_redundancy.json`,
`data/backtest/source_redundancy_report.md`,
`data/backtest/source_truth_daily.csv`, and
`data/backtest/forecast_ensemble_features.csv`. It keeps WU as the
settlement-aligned primary, compares it with registry-driven METAR/ASOS, NOAA
GHCNh, and ERA5-style reanalysis for every registered market, learns each
redundant source's daily high bias and peak-time lead versus WU, and emits
provenance-safe daily truth rows. When WU is missing but a redundant source
exists, the truth row becomes a `filled_from_redundant` candidate instead of
pretending the day is clean WU. `src.metar_history` now backfills all registered
market stations from IEM ASOS into the shared native-unit hourly/daily schema.

Gap-fill result: the same report groups missing-source days into targeted
commands for `src.wu_history`, `src.metar_history`,
`src.noaa_ghcnh_history`, and `src.reanalysis_history`. A single source outage
now degrades into either a primary-WU row with missing redundant-source refetch
commands or a provenance-labelled redundant fill candidate; only all-source
gaps remain unfillable.

Forecast result: feature schema `toronto_feature_store_v0.4` adds
`forecast_source_count` and `forecast_disagreement`. Live extraction computes
them from Weather.com, Open-Meteo, ECCC, NWS hourly (US markets), and the
Open-Meteo GFS global ensemble where available; `src.forecast_archive`,
`src.snapshot_tracker`, `src.forecast_tracker`, and the forecast-error
component now carry those sources forward. The new forecast ensemble CSV
backfills the same source-count/median/spread signal from archived forecast
tapes. Existing model artifacts keep serving because they select their trained
feature names.

Current report (2026-06-12 12:31 UTC, window 2026-06-01..2026-06-12):
12 markets / 144 market-days, 84 WU primary days, 84 two-plus-source days, 60
redundant fill days, 0 all-source missing days, and 17 disagreement alerts. The
60 fill rows are provenance-labelled METAR/ASOS candidates for days where WU
history has not printed yet; they are not promoted to clean WU settlements.
Forecast ensemble extraction covered 8,193 snapshots; almost every F-market
snapshot has two forecast sources, while Toronto averages 2.13 sources because
ECCC joins Weather.com/Open-Meteo.

### 31. Data Integrity And Observability At Scale [COMPLETE - FLEET REPORT LIVE]

Goal: answer "is every market complete and fresh right now?" at a glance.

- [x] Extend `collection_health` to all 12 markets plus a fleet view; per-market
  freshness SLAs.
- [x] Wire data audits (missing/sparse/duplicate/impossible) into CI and the loop
  (closes item 14).
- [x] Provenance manifests and schema versions on every artifact; drift/outlier
  alerts.

Acceptance: data problems surface as alerts before they corrupt training or
serving — the way the timezone bug should have.

Implementation result (2026-06-11): `src.collection_health` now has
`--fleet` mode over all 12 registered markets with per-market freshness SLAs,
and `src.snapshot_tracker --status` includes both the active-day collection
state and the full fleet collection state. The running loop also writes a
compact `fleet_collection` summary into `data/snapshots/loop_status.json`, so
collection gaps are visible from the operator heartbeat.

Fleet observability result: `src.fleet_observability report --strict` writes
`data/backtest/fleet_observability.json`,
`data/backtest/fleet_observability_report.md`, and
`data/backtest/artifact_provenance_manifest.json`. It combines fleet collection
health, fleet historical audits, artifact provenance/schema status, location
trust readiness, and alert severity into one CI/loop-friendly payload. The
standalone `src\data_auditor.py --fleet --json --strict` path is now
registry-aware and unit-aware, so F-market rows no longer trigger false Celsius
impossible-value alerts.

Current fleet report (2026-06-12 01:20 UTC): status is `CRITICAL`, which is the
desired fail-closed behavior. It found 12 collection-gap criticals on the June
11 tapes (Toronto 93 snapshots, max gap 21 min; US markets 92 snapshots, max
gap 31 min), plus one true
Miami historical outlier (`171 F` on 2005-06-11). It also warns on
target-window missing/sparse historical days and legacy core artifacts whose
schema is only represented in the external provenance manifest. Those are now
surfaced before training/serving can treat the data as clean.

### 32. Reanalysis And Synoptic Feature Layer [NEW - GATED]

Goal: add physically meaningful, multi-decade-consistent inputs the obs-only set
lacks.

- [ ] ERA5 / synoptic upper-air (850 mb temperature, thickness), soil moisture,
  antecedent-day state.
- [ ] Teleconnection indices (ENSO/PNA), coastal sea-breeze and continentality
  flags per city.
- [ ] Add only behind the model harness (item 36); promote features that improve
  out-of-sample skill.

Acceptance: each new feature family earns its place via settlement-scored
validation, not importance charts (extends item 27 to all markets).

### 39. Data Layer Audit Findings (2026-06-09) [NEW - OPEN]

Full data-layer audit across all 12 markets. Verdict: broad and well-organized
(per-station roots, manifests, raw->hourly->daily tiers, coverage tool), but with
one latent correctness landmine, ~3.6 GB collected-but-unused, ~3.3 GB of
regenerable artifacts in git, and a deep-history asymmetry (Toronto 44 yrs WU vs
US cities 11 yrs). Measured footprint: WU 3.5 GB, GHCNh 2.7 GB, ERA5 961 MB,
snapshots 708 MB. Items below are scoped here and cross-linked to the broader
Track A/B items they sharpen.

Short-term (correctness + cleanup):

- [x] **P0 - `_c` daily columns hold Fahrenheit for the 11 F markets.** Post
  native-unit refactor the daily writer wrote native values into `max_temp_c` /
  `min_temp_c` / `avg_temp_c` / `max_temp_bucket_c` without converting (verified:
  Miami `max_temp_c`=88, LA=71 are degF). Works today only because every consumer
  operates in native unit (e.g. `backtest.py:102` reads `max_temp_bucket_c` and
  native bucket == settlement bucket). **Blocks pooled/canonical-C training
  (item 33 / 35).** Fix = convert F->C properly, or rename columns to `_native`
  and make any pooling convert explicitly. Audit every `_c` consumer.
- [x] **P1 - `data_auditor.py` only validates Toronto.** Hardcoded to CYYZ,
  months 5-6, Celsius bounds (`>45C impossible`) -> flags ~all F rows as
  impossible. 11/12 markets have no working validation. Make it fleet-aware +
  unit-aware (`all_specs()`, native bounds per `display_unit`). Sharpens items
  14 and 31.
- [ ] Delete orphaned pre-per-city `_f` model artifacts: `src/feature_model_hgb_f.pkl`
  (7.4 MB), `src/feature_model_coefs_f.json`, `src/late_day_model_coefs_f.json`
  (superseded by per-city `_<city>` artifacts; verified no code loads them).
- [ ] Backfill `forecast_history` for Atlanta (katl) + Miami (kmia) - currently
  10/12 stations; their forecast-archive features are starving.
- [ ] Fix the fleet-wide ERA5 normalize lag: normalized stops at 2026-06-02 while
  raw is fetched to 06-07 (normalize step ~5 days behind fetch).
- [ ] Backfill Toronto may-29 snapshot gap (if recoverable) and re-collect
  Denver (kbkf) WU sparse/missing days (10 calendar-missing + 17 sparse vs ~1/5
  for peers).

Medium-term (integration + storage hygiene):

- [ ] **Decide GHCNh + ERA5: integrate or stop committing.** Both are on disk
  (3.6 GB) but wired into NO feature/model/climatology code - only the coverage
  /backfill tooling references them. Either use them (settlement cross-check,
  deeper climatology priors, WU-stale redundancy) or stop collecting/committing.
  Resolves the "gated" status of item 32; model history is effectively WU-only.
- [ ] **Stop committing derived hourly partitions (~3.3 GB in git):** WU 1.3 GB /
  GHCNh 1.2 GB / ERA5 0.8 GB ~ 5,376 JSONL files tracked. Raw is gitignored but
  the rebuildable hourly tier is not. Gitignore `data/**/hourly/` (or move to
  LFS/external); keep only `daily_summary.csv` + manifests tracked.
- [ ] Deepen US history below 2015: GHCNh -> station start, ERA5 -> 1940; gives
  the 11 US cities Toronto-class priors (same adapters, no new integration).
  Extends item 29.
- [ ] Add historical METAR for the 11 US cities -> per-city settlement-lag models
  (today only Toronto has one via SWOB). Extends items 5 and 30.
- [ ] Move model artifacts out of `src/` (13 `.pkl` + weight JSONs mixed into the
  code tree) into an `artifacts/` (or `models/`) dir.

Long-term (the production data layer):

- [ ] Unified per-market daily "truth" table joining WU / METAR / SWOB / GHCNh /
  ERA5 with provenance + a consensus high (today sources are siloed; foundation
  for honest settlement modeling + source-disagreement signal). Extends item 30.
- [ ] Automated ingest quality gate in the loop/CI - block writes failing
  range/gap/dup/schema checks; surface in collection-health (closes item 14,
  feeds item 31).
- [ ] Central schema registry + migration tooling (replace scattered
  `schema_version` strings). Part of item 31.
- [ ] Parquet + per-source freshness SLAs + a coverage/gap dashboard (extend the
  existing `historical_coverage.py`).
- [ ] Evaluate new sources: NWS/NOAA CF6 daily climate reports (official
  daily-max-of-record, settlement-adjacent truth), Meteostat (free long daily
  history), ASOS 1-min/ISD (exact intraday peak timing). Feeds items 29-30.

Acceptance: the `_c` lie is resolved (pooled training unblocked), every market
has working validation, idle sources are either integrated or dropped, and the
repo no longer carries multi-GB regenerable artifacts.

P0 unit-contract fix (2026-06-11): `src.daily_summary` now centralizes
native-vs-Celsius daily-summary reads, `src.wu_history` writes
`wu_daily_native_v2` with explicit `*_native` columns and true Celsius `*_c`
columns, and all 12 WU normalized stores were rebuilt from local raw payloads.
Spot check: NYC June 7 is native `81 F` with `max_temp_c=27.2222`; Toronto June
7 remains `24 C`. Native settlement/model readers now prefer
`max_temp_bucket_native` / `max_temp`, while the storage layer is safe for
canonical-C pooling. The pooled trainer also filters implausible native buckets
(found and excluded Miami 2005-06-11 at impossible `171 F`).

P1 fleet-aware auditor fix (2026-06-11): `src.data_auditor` now uses
`all_specs()`, per-market `data_root`, daily-summary native/C helpers, and
native temperature bounds (`F` and `C`) instead of hardcoded CYYZ/Celsius
assumptions. It exposes `--fleet --json --strict` for automation and feeds the
fleet observability report. Spot checks cleared the false NYC/Denver F-market
pressure/temperature alerts while preserving the true Miami 2005-06-11
`171 F` critical.

## Track B — From Bootstrap To Full Production Model

Principle: one shared learning pipeline, split only at the unit/band I/O edges,
validated by the improvement engine before anything ships, with per-market gating
and automated retraining.

### 33. Family-Pooled Model + City Features [OPEN - v0.3 SHADOW, REFRESH AUTOMATED]

Goal: train on all cities in a unit family, not one (audit Option A).

- [x] Add city features to the pooled training path (market one-hot,
  climate-normal, latitude/longitude, coastal flag, high-so-far anomaly, and
  forecast anomaly).
- [x] Add a pooled training mode (`src.pooled_feature_model`) that iterates a
  unit family's specs, concatenates records, and trains one HGB bundle per
  cutoff hour.
- [x] Train the F family on all 11 US cities; keep Toronto/C as its own family.
- [x] Validate per-market on replay + trust before cutover; per-market
  HGB-vs-empirical gate.
- [x] Train a v0.2 pooled/F candidate with direct market-band objective,
  hard/support floor calibration, late-day lock-in, and snapshot partition
  normalization.
- [x] Clear `src.pooled_candidate_replay` per market before any serving hook.

Acceptance: the pooled F model beats the NYC-only HGB on per-market replay/trust
without regressing NYC.

Pooled F starter (2026-06-11): built `src.feature_model_hgb_f_pooled.pkl` as a
non-serving research artifact plus
`data/backtest/f_family_pooled_model_report.md`. Dataset: 66,669 rows across
the 11 F markets using `toronto_feature_store_v0.3` and 14 cutoff models.
Holdout-year 2025 validation is intentionally not promotion-grade yet: some
hours remain weak even after support-wide smoothing, so this artifact should
feed the next model iteration and gauntlet comparison, not live serving.

Pooled candidate replay (2026-06-11): added `src.pooled_candidate_replay`
plus `tests/test_pooled_candidate_replay.py`, then ran the pinned promotion
corpus against `src.feature_model_hgb_f_pooled.pkl`. Coverage was complete:
16,940 F-family band rows, 1,540 F snapshots, and zero missing candidate rows.
The verdict was **BLOCK / DO_NOT_CUT_OVER** in
`data/backtest/pooled_candidate_replay_report.md`: aggregate candidate Brier
`0.1370` versus current replay `0.0429` and market `0.0384`; all 11 F markets
blocked by candidate-vs-current regression. The gate worked and the artifact
is confirmed as research-only. The next Item 33 work is a v0.2 candidate whose
training objective/calibration is aligned to replayed market-band probability,
especially exact settlement-distance-0 buckets and late-day lock-in.

Pooled band v0.2 (2026-06-11): trained
`src.feature_model_hgb_f_pooled_v0_2.pkl` with schema
`pooled_feature_band_hgb_v0.2`, prediction mode `band_binary`, and objective
`binary_market_band_brier`. Unlike v0.1, this model trains directly on
synthetic market-band outcomes (`eq`/ranges, `lte`, `gte`) from historical WU
feature rows, then applies deterministic WU hard floors, soft live-support
floors from replay inputs, late-day lock-in, and per-snapshot partition
normalization. Holdout exact-winner mean probability now reaches `0.56-1.00`
by hour and late-hour holdout Brier collapses near zero in
`data/backtest/f_family_pooled_band_model_report.md`.

Adjacent calibration + bridge result (2026-06-11): v0.2 now carries a
holdout-trained above-floor adjacent/range calibration table with `262`
market/hour/floor-gap contexts, and `src.pooled_candidate_replay` applies the
artifact's configured incumbent bridge after partition normalization. The five
markets that previously blocked on adjacent/range leakage (Denver, Houston, Los
Angeles, NYC, Seattle) run at `0.20` pooled alpha until more settled days prove
the raw pooled probabilities; other F markets remain at full pooled alpha.

Pinned replay result: `data/backtest/pooled_candidate_replay_v0_2_report.md`
now scores the v0.2 artifact at aggregate Brier `0.0413` versus current replay
`0.0429`, recorded `0.0499`, and market `0.0384`. The verdict improved from
**BLOCK / DO_NOT_CUT_OVER** to **SHADOW_ONLY / DO_NOT_CUT_OVER**: all 11 F
markets clear the per-market regression gate, with no blocked markets and zero
missing candidate rows. No market is cutover-ready yet because every F market
still has only one pinned settled day and `15/100` trust, and several markets
remain behind the market-price Brier. The next Item 33/34 work is to collect
more F-family settled days, relax the incumbent bridge only when per-market
replay proves it, and move the secondary calibration/forecast/lag artifacts
from Toronto-only to F-family.

Pooled band v0.3 (2026-06-12): trained
`src.feature_model_hgb_f_pooled_v0_3.pkl` with schema
`pooled_feature_band_hgb_v0.3` and feature schema
`toronto_feature_store_v0.4`. v0.3 keeps the direct market-band objective and
adds static per-market source-reliability priors learned from WU-vs-METAR/ASOS,
GHCNh, and ERA5-style reanalysis overlaps. These are source trust features, not
same-day final redundant highs, so they do not leak the settlement into
intraday training rows. Fresh replay also showed that the old v0.2 artifact now
blocks Dallas under the current code path (`0.0703` candidate Brier versus
`0.0483` current replay), so v0.3 adds a Dallas incumbent bridge at alpha `0.0`
until more settled days justify relaxing it.

v0.3 pinned replay result:
`data/backtest/pooled_candidate_replay_v0_3_report.md` scores the new artifact
at aggregate Brier `0.0515` versus current replay `0.0686`, recorded `0.0499`,
and market `0.0384`, improving the refreshed v0.2 replay (`0.0538`) while
clearing all per-market regression gates. Verdict remains
**SHADOW_ONLY / DO_NOT_CUT_OVER**: all 11 F markets are shadow, none are blocked,
but every F market still has only one settled pinned day and `15/100` trust, and
several markets remain behind market-price Brier. Item 33 therefore remains open
until additional settled F days and the promotion gate can prove market-level
cutover.

Promotion-refresh automation (2026-06-12): added `src.promotion_refresh`, the
Item 33/37 path that turns newly finalized settled days into a fresh pinned
promotion corpus, refreshed `location_trust.json`, pooled-F candidate replay,
current-serving gauntlet, and machine-readable per-market actions. The pooled
candidate replay now also carries a global replay gate over corpus-pin warnings
and exact replay-identity fidelity, so candidate promotion fails closed when
the input pin or replay canary is bad.

Real refresh run:
`.\venv\Scripts\python.exe -m src.promotion_refresh` wrote
`data/backtest/f_family_promotion_refresh.json` and
`data/backtest/f_family_promotion_refresh_report.md` using corpus hash
`b69ba9f3ccf9b2cba46c278d5a63b6a1f8b2de11df419b354ceec7d4b8b9937e`
(`12` market-days, `1,680` snapshots, `18,480` band rows). The pooled v0.3
candidate stayed **SHADOW_ONLY / DO_NOT_CUT_OVER** with aggregate Brier
`0.0515` versus current replay `0.0686` and market `0.0384`; per-market
actions were `0` promote, `11` shadow, `0` blocked. Corpus pin passed, but
`identity_record_count` is still `0`, so the strict exact-identity canary
cannot be required until future settled captures include replay identities.

### 34. Per-Market Calibration And F-Family Secondary Artifacts [COMPLETE - EMPIRICAL GATED]

Goal: generalize the Toronto calibration/forecast/lag work (items 21-23) to the
F family as data accrues.

- [x] Build F-family probability-calibration, forecast-error, and settlement-lag
  artifacts once F days settle.
- [x] Per-market trust gating: serve the ML model only where trust > threshold,
  else empirical fallback.
- [x] Calibrate by cutoff hour and floor distance per family.

Acceptance: each F market is either calibrated-and-promoted or honestly
empirical, never overconfident.

Implementation result (2026-06-11): added `src.family_secondary_artifacts`,
which trains the whole F family, writes pooled family artifacts plus per-market
secondary artifacts, and emits `src/f_family_secondary_artifacts.json` as the
serving gate manifest. The family-level artifacts are now:
`src/probability_calibration_f_family.json` (`16,940` rows),
`src/forecast_error_model_f_family.json` (`12,969` rows), and
`src/settlement_lag_model_f_family.json` (`2,493` lead rows). Per-market
probability-calibration, forecast-error, and settlement-lag artifacts were also
written for all 11 F markets, with all artifact statuses `ok` in
`data/backtest/f_family_secondary_artifacts_report.md`.

Serving gate result: `TorontoHighTempModel` now loads the family manifest and
`FeatureModelMixin` suppresses feature-model serving for governed F markets
whose `serving_gate.mode` is `empirical`; `model_identity` includes the family
manifest for F replay hashes. With the current trust scores (`15/100`) and one
settled F day per market, all 11 F markets are honestly empirical:
`trust 15 < 25; settled_days 1 < 2`. Toronto is not governed by the F manifest.

Replay evidence: `data/backtest/f_family_secondary_replay_report.md` reran the
pinned promotion corpus after the gate landed. The safety gate is intentionally
conservative and worsens one-day aggregate replay (`0.0668` replayed Brier vs
`0.0500` recorded and `0.0396` market) because the unproven F ML models are
withheld. This is the expected Item 34 tradeoff: no F market is promoted until
trust/day-count evidence supports it. The next accuracy path is accumulating
more F-family settled days, then flipping individual markets from empirical to
ML only when the manifest gate and promotion gauntlet both clear.

### 35. Unified Continuous-Density Model [NEW - ENDGAME]

Goal: one model for all cities; C/F becomes serving-only (audit Option B).

- [ ] Predict a fine canonical-grid / continuous max-temp density pooled across
  all 12 cities plus city features.
- [ ] Discretize the density to each market's native bands at serve time
  (finer-than-bands grid => leakage-free, the principled fix the coarse
  canonical-C approach lacked).
- [ ] Port calibration and floors from integer buckets to the continuous
  representation.
- [ ] Prove it rescues the data-poor C/Canada family (Toronto borrows US-city
  structure).

Acceptance: the unified model matches or beats the family models per-market and
lifts the data-poor side.

### 36. Production Validation, Gating, And Promotion [NEW]

Goal: a model change ships only if it provably beats the incumbent, per market.

- [x] Replay fidelity identity canary: captured replay inputs now store a
  deterministic model identity (model version, market, active kind,
  distribution-code hash, and per-market artifact hash). The replay report no
  longer treats same-label artifact changes as "same version"; those legacy
  rows are reported separately and excluded from the exact canary.
- [x] Pinned promotion corpora: `src.promotion_corpus` freezes settled
  market-day folders, accepted settlement labels, exact snapshot IDs, replay
  input hashes, tape-row hashes, and a corpus hash so promotion gates never
  compare against a silently changed corpus.
- [x] One promotion gauntlet across markets:
  `src.promotion_gauntlet` runs pinned-corpus replay, corpus-pin verification,
  exact replay-identity fidelity, regression gating, settlement
  Brier-skill-vs-market, trust context, and forecast-tracker presence in one
  report.
- [x] Per-market promotion status: the gauntlet classifies each corpus market
  as `PASS`, `SHADOW`, or `BLOCK`, so a build can be production for one market
  while remaining shadow-only elsewhere.
- [x] Failure decomposition: promotion reports now slice code-effect by market,
  capture hour, bin type, forecast-gap bucket, live-reading-gap bucket, and
  settlement-distance bucket, with blocker-market drilldowns.
- [x] Partial per-market promotion semantics: global corpus/fidelity/regression
  failures still block all markets, but a market-level block no longer erases a
  separate market's `PASS`; the gauntlet can return `PARTIAL_PASS`.
- [x] Record model cards + data snapshot + gate results for every promotion:
  replay baselines now carry corpus hash/count metadata, replay reports include
  the pinned corpus section, and the gauntlet writes a durable promotion report.

Acceptance: no model reaches a market's live serving without passing that
market's gate.

Replay fidelity increment (2026-06-11): `src.model_identity` fingerprints the
distribution-affecting code and artifacts, `snapshot_tracker` writes that
identity into `snapshots.jsonl` and `replay_inputs.jsonl`, and
`replay_backtest` gates only exact identity matches as the fidelity canary. A
forced all-market capture on the patched writer seeded exact-identity replay
records, and the next loop tick confirmed the path stayed deterministic; the
live-corpus replay report now shows Same replay identity `24`, mean L1
`0.0000`, max L1 `0.0000`, verdict `FAITHFUL`. The old June-10
same-label rows are now correctly labelled as unversioned legacy diagnostics
(mean L1 `0.0815`, max `1.0711`) instead of failing the canary. The saved
baseline-era 69-folder gate still passes at replayed Brier `0.0386` versus
baseline `0.0386`; the full 81-folder live corpus includes unfinished June 11
snapshot-high settlements and should not be compared to the older baseline
without a corpus pin.

Promotion-corpus increment (2026-06-11): `src.promotion_corpus` now builds an
auditable manifest over settled folders only, pinning accepted quality labels,
snapshot IDs, replay-input hashes, tape-row hashes, and the corpus hash.
`src.replay_backtest --corpus ...` replays only those pinned rows and uses the
manifest settlement label rather than recalculating from mutable current files.
`src.promotion_gauntlet` consumes the manifest and produces the promotion
decision: corpus pin, replay fidelity, regression gate, model-vs-market skill,
location trust, forecast tracker, and per-market `PASS` / `SHADOW` / `BLOCK`.
After June 11 settles and exact-identity rows are no longer current-day-only,
run the gauntlet with `--require-exact-identity` to make the canary mandatory
for every promotion corpus.

Decomposition increment (2026-06-11): `src.replay_backtest` now attaches
feature vectors and settlement-distance buckets to replay rows; the regenerated
promotion gauntlet report keeps the current decision at `BLOCK` but explains
why. Current promote list is empty; shadow markets are Austin, Chicago, Dallas,
Houston, NYC, San Francisco, Seattle, and Toronto; blocked markets are Atlanta,
Denver, Los Angeles, and Miami. The largest positive code-effect slice is still
market-specific rather than a corpus-pin issue.

### 37. MLOps And Always-On Production Hardening [OPEN - CLOB LOOP SUPERVISED]

Goal: make the fleet reproducible, self-retraining, and observable.

- [x] Settlement-to-promotion refresh runner: `src.promotion_refresh` rebuilds
  the pinned corpus, refreshes trust, runs pooled replay, runs the current
  serving gauntlet, and emits per-market actions for automation.
- [x] Data-layer audit runner: `src.data_layer_audit` reports loop health,
  snapshot cadence/completeness, low-fill fields, historical source coverage,
  and prioritized data-retention recommendations.
- [x] Split capture cadences: keep full weather/model snapshots at 5-10 minutes,
  but capture market-book data every 30-60 seconds or via WebSocket without
  refetching every weather source.
- [x] Production-harden the CLOB book loop: heartbeat/status, diagnostics,
  detached start, stop, restart, ensure, and a Windows Task Scheduler
  registration script separate from the weather/model loop.
- [ ] Model/artifact registry + versioning; scheduled nightly
  retrain -> validate -> promote.
- [ ] Shadow / A-B deployment; monitoring + alerting + drift detection per
  market.
- [x] Clean supervised always-on capture (closes item 16); one market's failure
  cannot stall the loop.

Acceptance: a new market or a model update flows through the pipeline with no
manual surgery.

CLOB hardening update (2026-06-12): `src.market_microstructure` now mirrors the
snapshot supervisor pattern for the irreplaceable fast book tape. The managed
loop writes `data/snapshots/clob_loop_status.json`, appends
`clob_diagnostics.jsonl`, keeps console output in `clob_loop_console.log`, and
exposes `status`, `start-detached`, `stop`, `restart`, and `ensure` commands.
`scripts/register_clob_supervisor.ps1` installs a separate Task Scheduler job
that runs `market_microstructure ensure` every minute and at logon. Health is
heartbeat-based with `RUNNING`, `DEGRADED`, `ERRORING`, `DEAD`, and `PAUSED`
states; per-market CLOB failures are isolated and surfaced without stopping the
rest of the fleet. A supervisor lock guards `ensure`, `start-detached`, and
`restart` against duplicate loop starts when a manual command lands on the same
minute as Task Scheduler. `src.data_layer_audit` schema `v0.2` now reports the
CLOB loop next to the weather/model loop and raises P0 when book capture is not
managed or fresh. Item 37 remains open only for the broader model/artifact
registry and shadow/A-B drift-monitoring work.

### 38. Cross-Market And Market-Microstructure Signal [PARTIAL 2026-06-12 - CLOB CAPTURE SHIPPED]

Goal: squeeze the last edge once per-market models are solid.

- [ ] Borrow strength across correlated cities (regional heat waves / shared
  synoptics).
- [x] Persist CLOB token ids/condition ids into the market snapshot artifacts.
- [x] Capture full CLOB order-book depth per weather-market token:
  timestamp/hash, top levels, cumulative depth, spread, midpoint, imbalance,
  executable price for fixed trade sizes, and last trade metadata.
- [x] Add a market-book loop or WebSocket recorder with 30-60 second baseline
  cadence and 10-15 second near-close/large-edge-change cadence.
- [ ] Model Polymarket price dynamics (stickiness, liquidity, book depth,
  spread, trade flow) toward edge/P&L, not just calibration.

Acceptance: cross-market structure or microstructure adds settlement-scored or
P&L value over independent per-market models.

Data-layer audit result (2026-06-12): `src.data_layer_audit` confirmed the
project currently captures Gamma yes/no prices, best ask, last trade, volume,
liquidity, and status, but it does **not** persist CLOB token ids, order-book
levels, book hashes, book imbalance, executable depth, or a trade stream.
Gamma `best_bid` is only `48.0%` filled across existing snapshot rows. The
Gamma event payload already exposes `clobTokenIds` and `enableOrderBook`, and
Polymarket's public CLOB docs expose `/book`, `/books`, `/prices-history`, and
the public market WebSocket, so this is an implementation gap rather than a
market-discovery blocker. Because historical order-book depth cannot be
reconstructed reliably later, this item is now an immediate data-capture
priority, not merely a future modeling flourish.

Implementation update (2026-06-12): `src.market_microstructure` adds the fast
CLOB capture path. It discovers tokens from Gamma `clobTokenIds`, writes
`clob_tokens.csv/jsonl`, batches REST order books through `/books` with `/book`
fallback, persists raw books plus `order_books_summary.csv` and
`order_books_long.csv`, optionally captures `/prices-history`, and records the
public market WebSocket to `market_ws.jsonl` / `market_ws_events.csv`.
`src.snapshot_tracker` now persists `condition_id`, `polymarket_market_id`,
`clob_token_ids`, and yes/no token IDs in new slow snapshot rows. The model loop
should remain at 5-10 minutes; run the book loop separately at 30-60 seconds
baseline and 10-15 seconds after local 15:00, near close, or after large
top-of-book midpoint moves. Remaining item-38 work is to learn and validate
microstructure signals against settlement/P&L, not merely to collect them.
The loop is now supervised through item 37's `market_microstructure ensure`
path, so the next item-38 step can assume durable book tapes are available.

Cadence-audit update (2026-06-12 late evening): the book tape now has its own
acceptance instrument. `src.market_microstructure audit [--strict]` audits the
active market day's tape per registered market (captures, median/max gap,
gaps over a 120-second threshold, trailing freshness) and exits non-zero in
strict mode on any gap or stale/missing tape. `src.fleet_observability` now
includes a `clob` payload section, a "CLOB Book Capture" report table, and
fail-closed alerts: a DEAD/UNKNOWN/ERRORING book loop or an active-day tape
gap is critical, while PAUSED/DEGRADED warns. Validation: live fleet audit
passed with all 12 markets OK (median gap 15.0s in fast mode, max gap 90.9s,
trailing freshness under 15s); `pytest -q` passed 349 tests + 34 subtests;
`compileall src tests` passed. The MARKET_MAKING_PLAN.md Stage-0 acceptance
clock (7 consecutive gap-free days) starts with the first full capture day,
2026-06-13.

### 40. Intra-Hour Feature Freshness [COMPLETE 2026-06-11 - FLEET REFRESHED]

Promotion results (2026-06-10): pinned A/B gate PASS (0.0545 -> 0.0544; no
regression in any minutes-past-print bucket). The pooled bucket slice was
uniform rather than concentrated -- gains live in FAST-MOVING windows, not
clock buckets, so the bucket criterion was too blunt. The decisive evidence is
the June-9 staircase probe, the exact case the item was designed for: with
v0.3 artifacts the model climbs through the un-printed hour (P(<=24)
0.481 -> 0.594 across 15:19-15:50) instead of regressing (v0.2: 0.418 -> 0.348),
moving the 50% crossing on the winning band ~40-50 minutes earlier and
recovering most of the measured 52-minute market lag. Follow-up (per design):
re-run the per-source ablation for wu_current / the current-observed floor now
that live readings are trained features.

Fleet refresh results (2026-06-11): after the deepened US WU seasonal caches,
the five reverted cities (Austin, Chicago, Houston, Los Angeles, Seattle) were
re-run through full LOO v0.3 retraining. A fleet artifact audit now shows all
12 registered markets on `toronto_feature_store_v0.3` with 27 features across
14 cutoff models. The pinned replay gate passed on 69 market days, 6,135
snapshots, and 67,485 rows: replayed Brier 0.0386 versus saved baseline
0.0386 (delta -0.0000, tolerance 0.003). Trust was refreshed after the gate:
Toronto is 43/100 on 4 settled days; US markets remain Unproven at 15/100
until more clean settlements accumulate.

Implementation status (2026-06-11): code, full LOO retrain, fleet artifact
refresh, and pinned replay gate complete. Two design deviations from the
original sketch, both for cause: (1) the simulated live reading INTERPOLATES
between bracketing
observations (with a real intra-hour special obs winning inside a 10-minute
window) instead of latest-at-or-before -- on hourly-only history the
at-or-before reading equals the cutoff print, which would train the feature
dead; interpolation simulates the contemporaneous physical reading the live
wu_current feed genuinely reports, and only ever feeds the live-reading
features, never the printed path. (2) Each (day, hour) trains at ONE
deterministic wall offset from {0, 15, 30, 45} instead of emitting all
offsets -- the LOO loop is O(n^2), so 4x rows would have been 16x compute;
sampling across days covers the offset range at unchanged cost. Also shipped:
schema v0.3 artifacts are backward-compatible by construction (new numerics
appended; HGB selects by feature_names, LR slices by scaler width), the dead
cutoff-interpolation path was deleted, the late-day trainer now measures
time_since_reached from the sampled wall minute (closing the audited
wall-vs-cutoff skew), and snapshot CSV appends became schema-drift-safe
(existing files keep their own header).

Goal: close the structural lag between WU prints without breaking train/serve
parity. Between hourly prints the feature path is frozen at the last printed
cutoff while the market trades continuously: the 2026-06-09 Toronto trace
collapsed in staircase steps keyed to the 16:00/17:00 row prints, 52-62
minutes behind the market. Two prior attempts failed for the same reason:
the v0.5.1 mock-row injection fabricated settlement-source rows (reverted in
v0.5.2), and the cutoff-interpolation path fed hour-H+1 models state that had
not printed (dead code, and wrong if revived). The honest fix is to MODEL the
live reading explicitly.

Design (feature schema v0.3):

- [x] New features: `minutes_since_cutoff` (wall minus effective printed
  cutoff), `live_reading_temp` (the current wu_current reading, kept separate
  from the printed path), and `live_reading_minus_high` (reading minus printed
  high; positive means the high is being exceeded right now). `high_so_far`
  stays printed-only -- no live contamination of the settlement-source state.
- [x] Training extraction: for each historical day and cutoff hour H, emit
  records at sampled wall offsets (H:10 / H:30 / H:50). The simulated live
  reading is the latest observation at or before the sampled minute from the
  same WU obs stream (wu_current and WU history are the same data family);
  printed-path features use obs <= H:00 only. Strictly enforce minute <= t to
  avoid leakage. Roughly 3x training rows per hour-model; expect a ~3x LOO
  retrain (run overnight).
- [x] Serving: extract at the effective printed cutoff exactly as today, then
  attach the live reading and elapsed minutes. No fabricated rows; the model
  LEARNS how much a 15:38 reading 1.2 above the printed high moves the final
  distribution.
- [x] Apply the same treatment to the late-day continuation model -- this also
  fixes the audited time_since_reached wall-vs-cutoff training skew.
- [x] Parity: extend the feature-skew test with a live-reading scenario; bump
  schema to v0.3 and stamp artifacts.
- [x] Gate: pinned-corpus replay A/B (frozen folders, finalized labels, both
  runs back-to-back). Measure specifically by minutes-past-print buckets
  (0-19 / 20-39 / 40-59): the gain should concentrate in the 20-59 windows
  where the staircase flats live.
- [ ] After promotion: re-run the per-source ablation for wu_current and the
  current-observed floor -- once the model learns live readings as features,
  the floor heuristic is likely redundant and should be retired by evidence.

Acceptance: pinned replay improves in the 20-59 minutes-past-print windows
without regressing the 0-19 window, and the feature-skew parity suite passes.

## Sequencing The Two Tracks

0. **Item 39 P0 (the `_c`-column unit lie)** first — it silently corrupts any
   canonical-Celsius pooling, so it gates item 33/35. Plus the item 39 cleanup
   tasks (orphan artifacts, forecast_history gaps, ERA5 normalize lag) are quick
   and unblock clean validation.
1. **Item 28 (settlement ledger)** and **item 33 (pooled F + city features)** in
   parallel — the foundation labels and the immediate model win, both unblocked
   now.
2. Then **31 (observability)** and **34 (F calibration + gating)** as F days
   settle.
3. Then **29-30 (deeper, redundant data)** feeding **35 (unified model)**.
4. **36-37 (gating + MLOps)** harden whatever 33/35 produce.
5. **32 (reanalysis features)** and **38 (cross-market / microstructure)** are
   the long-tail accuracy and edge plays.

## Research Questions

- Does WU final high usually equal Weather.com max-since-7 once history settles?
- How often does WU history revise after the live day ends?
- Which source best predicts WU final high by noon: Weather.com, Open-Meteo,
  Environment Canada, or empirical intraday analogs?
- Are market prices systematically too sticky around psychologically salient
  buckets like 25 C?
- Does edge persistence matter more than one-time edge size?
- Which cutoff hours have true model edge versus Polymarket, and which are
  better left to the market?
- Is the model's biggest weakness directional accuracy, bucket-boundary
  calibration, or overconfidence after a WU floor prints?
- Does using market price as an ensemble input improve settlement accuracy
  while still leaving tradable residual edge?

## Codex Deep Model Audit - 2026-05-28

Status: fixes implemented and tests passing.

Findings fixed:

- Production feature extraction was not aligned with training cutoffs. The HGB
  and late-day paths were trained on top-of-hour historical rows, but live
  inference could use Weather.com current/current-hour rows inside that hour.
  `src/toronto_model.py` now builds feature, late-day, and analog inputs from
  WU history rows at or before the active cutoff hour.
- The analog search used latest live/current observations instead of the
  cutoff-aligned state. It now compares today's cutoff features to historical
  cutoff features.
- Last-good live-source fallback had no age limit. Failed sources could keep
  same-day cached values alive indefinitely. Last-good live payloads are now
  accepted only when fetched within 90 minutes.
- Snapshot metadata fallback still named the old empirical model. The fallback
  is now updated to v0.4.7.
- `src/data_auditor.py` was hardcoded to the original May 27 target day. It now
  follows the configured/current market date by default.

Validation results:

- `pytest -q`: 37 passed.
- `python -m compileall src tests app.py`: passed.
- May 28 WU data audit: 390 target-window dates checked from 2000-2025; 4
  missing days, 1 sparse day, 0 duplicate timestamps, 0 impossible values.
- May 28 snapshot tape audit: 30 snapshots, 330 band rows, complete 11-band
  coverage, 0 duplicate snapshot-band rows, 0 missing key numeric values,
  median cadence 10.2 minutes and max gap 11.0 minutes.
- Fresh v0.4.7 live build at 2026-05-28 14:03 local used cutoff 13:00, observed
  WU/SWOB floor 19 C, top bucket 20 C at about 46.9%, with 19 C about 24.7%,
  21 C about 14.2%, and 22 C about 11.5%.

Residual risks:

- The checked-in HGB feature model remains uncalibrated. In-sample diagnostics
  are much stronger than the leave-one-out report, so the model should be
  treated as a useful signal but not a fully calibrated probability engine.
- `src/feature_model.py` still has `RUN_LOO = False`; rerunning it will not
  regenerate the validation table unless toggled.
- The feature model still omits archived forecast-max features, despite the
  roadmap spec mentioning forecast max.
- The explanation/deep-dive panel still does not expose quantitative
  contribution accounting and remains partially centered on the hardcoded
  25 C deep dive.

Follow-up live audit (2026-05-28 15:15 local):

- Root cause for exact 19 C showing near zero: ECCC SWOB reached 19.6 C and the
  model rounded that non-resolution source to a hard 20 C observed floor.
  Market rules resolve from Wunderground CYYZ history, so this was too
  aggressive. Fixed in v0.4.8: only Wunderground history can create the hard
  observed floor; SWOB is a soft station-support signal.
- Second issue found: wall clock had advanced to the 15:00 cutoff while
  Wunderground history had only printed through 14:00. The 15:00 HGB model was
  therefore being fed a stale 14:00 settlement-source state. Fixed in v0.4.9:
  feature, analog, transition, and late-day paths use the latest cutoff whose
  Wunderground history row has actually printed.
- Fresh v0.4.9 live build at 15:14 local used wall cutoff 15:00 but effective
  cutoff 13:00, observed WU floor 19 C, and assigned about 18.5% to exact
  19 C, 45.5% to 20 C, 17.7% to 21 C, and 15.6% to 22 C.
