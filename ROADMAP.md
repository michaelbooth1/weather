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

### 14. Data Validation Suite [PARTIAL]

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

### 16. Background Process Management [PARTIAL]

- [x] Replace ad hoc background loops with a small managed runner.
- [x] Track process PID, start time, last heartbeat, last snapshot, and errors.
- [x] Add a heartbeat-based status command.
- [x] Add pause/resume via dashboard flag.
- [ ] Add a command to stop/restart the snapshot loop cleanly.
- [ ] Document the recommended OS supervisor setup for always-on capture.

Codex update (2026-05-31): `src.snapshot_tracker` now has `--loop`,
`--status`, `loop_status.json`, `diagnostics.jsonl`, pause flag support, and
health tests. The missing piece is process lifecycle control: stop/restart
without relying on manual process management.

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

### 29. Deepen And Widen The Historical Record [PARTIAL - GHCNH COMPLETE, WU WIDENING]

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

- Run or schedule the resumable WU widener so each registered market reaches
  the deepest WU window available, not only the current mixed coverage. Dallas,
  Denver, Houston, Los Angeles, Miami, San Francisco, and Seattle are still open.
- Run the reanalysis backfills across every registered market and the chosen
  training window, then keep the raw files/checksum manifests as the offline
  rebuild source. GHCNh is complete for the current minimum window.
- Decide the production training window bounds per source and market
  (`historical_coverage.json` currently shows what is missing, not a completed
  source-limited archive).

### 30. Source Redundancy And Gap-Filling [NEW]

Goal: no single feed is a single point of failure or bias.

- [ ] >=2 observation streams per city (WU + METAR/ASOS + ISD), cross-validated;
  learn each one's lead/bias versus settlement (generalize items 4-5 to all
  markets).
- [ ] Multiple forecast sources (Open-Meteo + NWS/NDFD + a global ensemble) into
  an ensemble-forecast feature plus a disagreement signal (extends item 22).
- [ ] Automated gap detection and targeted re-fetch; fill observation gaps from
  the redundant stream.

Acceptance: a single source outage degrades gracefully, and forecast
disagreement is a measured feature, not an assumption.

### 31. Data Integrity And Observability At Scale [NEW]

Goal: answer "is every market complete and fresh right now?" at a glance.

- [ ] Extend `collection_health` to all 12 markets plus a fleet view; per-market
  freshness SLAs.
- [ ] Wire data audits (missing/sparse/duplicate/impossible) into CI and the loop
  (closes item 14).
- [ ] Provenance manifests and schema versions on every artifact; drift/outlier
  alerts.

Acceptance: data problems surface as alerts before they corrupt training or
serving — the way the timezone bug should have.

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

## Track B — From Bootstrap To Full Production Model

Principle: one shared learning pipeline, split only at the unit/band I/O edges,
validated by the improvement engine before anything ships, with per-market gating
and automated retraining.

### 33. Family-Pooled Model + City Features [NEXT - UNBLOCKED]

Goal: train on all cities in a unit family, not one (audit Option A).

- [ ] Add city features to `feature_store` (city one-hot, climate-normal, lat,
  coastal, continentality).
- [ ] Add a pooled training mode to `feature_model` (iterate a family's specs,
  concatenate records, train one HGB).
- [ ] Train the F family on all 11 US cities (~1,150 window-days); keep Toronto/C
  as its own family.
- [ ] Validate per-market on replay + trust before cutover; per-market
  HGB-vs-empirical gate.

Acceptance: the pooled F model beats the NYC-only HGB on per-market replay/trust
without regressing NYC.

### 34. Per-Market Calibration And F-Family Secondary Artifacts [NEW]

Goal: generalize the Toronto calibration/forecast/lag work (items 21-23) to the
F family as data accrues.

- [ ] Build F-family probability-calibration, forecast-error, and settlement-lag
  artifacts once F days settle.
- [ ] Per-market trust gating: serve the ML model only where trust > threshold,
  else empirical fallback.
- [ ] Calibrate by cutoff hour and floor distance per family.

Acceptance: each F market is either calibrated-and-promoted or honestly
empirical, never overconfident.

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

- [ ] One promotion gauntlet across markets: replay fidelity + settlement
  Brier-skill-vs-market + trust + forecast tracker.
- [ ] Per-market promotion (a build can be production in NYC and shadow in
  Seattle).
- [ ] Record model cards + data snapshot + gate results for every promotion
  (extends item 20).

Acceptance: no model reaches a market's live serving without passing that
market's gate.

### 37. MLOps And Always-On Production Hardening [NEW]

Goal: make the fleet reproducible, self-retraining, and observable.

- [ ] Model/artifact registry + versioning; scheduled nightly
  retrain -> validate -> promote.
- [ ] Shadow / A-B deployment; monitoring + alerting + drift detection per
  market.
- [ ] Clean supervised always-on capture (closes item 16); one market's failure
  cannot stall the loop.

Acceptance: a new market or a model update flows through the pipeline with no
manual surgery.

### 38. Cross-Market And Market-Microstructure Signal [NEW - FURTHEST OUT]

Goal: squeeze the last edge once per-market models are solid.

- [ ] Borrow strength across correlated cities (regional heat waves / shared
  synoptics).
- [ ] Model Polymarket price dynamics (stickiness, liquidity) toward edge/P&L,
  not just calibration.

Acceptance: cross-market structure or microstructure adds settlement-scored or
P&L value over independent per-market models.

## Sequencing The Two Tracks

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
