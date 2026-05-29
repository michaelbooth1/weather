# Toronto Weather Market Roadmap

This roadmap is organized around the fastest path from a useful live dashboard
to a calibrated, auditable trading/research system for Toronto high-temperature
markets.

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
- Repo note: `C:\Users\micha\Desktop\github\weather` is not currently a Git
  repository, so this audit used filesystem contents, generated artifacts, and
  runnable checks rather than commit history.

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

### 5. METAR Historical Layer [COMPLETE]

- [x] Collect historical METAR rows for CYYZ.
- [x] Compare hourly METAR max versus final WU bucket.
- [x] Quantify how often METAR misses the settlement bucket intraday and full-day.
- [x] Use this to calibrate the hourly-report sanity-check role.

Codex audit (2026-05-28): partial. `src/metar_history.py` collects IEM ASOS
METAR data, normalizes local rows, and generates a full-day WU comparison report
over 656 matched days. Issues found: intraday miss rates by cutoff hour are not
computed, and the live model only uses METAR as a small hard-coded sanity-check
signal rather than a calibrated role learned from this layer.

## Model Improvements

### 6. Feature-Based Probability Model [COMPLETE]

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

### 7. Bucket Boundary Logic [COMPLETE]

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

### 8. Late-Day Tail Model [COMPLETE]

- [x] Learn a separate after-3 PM / after-4 PM / after-5 PM continuation model.
- [x] Condition late-day tail on sun/cloud, wind direction, forecast remaining max,
  and whether the current high was first reached recently.
- [x] Make late-day extension risk visible in the dashboard.

Codex audit (2026-05-28): partial. Logistic continuation models are exported
for 15:00, 16:00, and 17:00, and the dashboard has a late-day extension risk
panel. Issues found: the late-day feature set omits forecast remaining max, no
late-day validation report is generated, and the learned continuation risk is
displayed but not clearly blended into the final distribution when the feature
model path is active.

### 9. Analog Search [COMPLETE]

- [x] Add a dashboard panel showing the closest historical analog days.
- [x] Match on:
  date window, high by current hour, 7 AM-noon rise, wind regime, cloud regime,
  dew point, and forecast profile once available.
- [x] Show each analog's final WU high and path through the day.

Codex audit (2026-05-28): mostly passes. The dashboard shows closest analogs,
final WU highs, and temperature paths, using the historical target-date window,
high so far, rise from 7 AM, wind/cloud regime, and dew point. Issue found:
forecast profile is not included in the analog distance.

## Dashboard Improvements

### 10. Odds Timeline View [COMPLETE]

- [x] Add charts for each price band:
  market price, model probability, and edge through time.
- [x] Highlight snapshots where edge crosses configured thresholds.
- [x] Add a compact table of current biggest positive and negative edges.

Codex audit (2026-05-28): mostly passes. The Streamlit dashboard includes per
band timeline tabs, threshold highlighting, and current positive/negative edge
tables. Issues found: the current-edge table rebuilds labels from nonexistent
`groupItemTitle` fields instead of using `bin_data["label"]`, so labels can be
blank; several warning/status strings show mojibake from corrupted emoji text.

### 11. Source Freshness Panel [COMPLETE]

- [x] Show last successful fetch time for each live source.
- [x] Flag stale feeds or failed requests.
- [x] Keep the last good live source value visible with a stale warning.

Codex audit (2026-05-28): mostly passes. `blend_with_last_good()` caches live
sources and the dashboard shows age, stale/failed status, and stale warnings.
Issue found: visible status/warning strings contain mojibake from corrupted
emoji/warning glyphs, which should be cleaned up for users.

### 12. Model Explanation Panel [COMPLETE]

- [x] Show the major probability drivers for the current top buckets.
- [x] Include:
  base climatology, intraday analog set, current max floor, forecast cap,
  wind/cloud analog adjustment, and late-day tail.
- [x] Keep the 25 C deep dive, but make it data-driven rather than fixed text.

Codex audit (2026-05-28): partial. A model explanation panel and data-backed
25 C deep dive exist. Issues found: the explanation is mostly descriptive and
does not expose quantitative driver contributions for base climatology,
intraday analogs, wind/cloud adjustment, or late-day tail; the deep dive is
still hardcoded around the 25 C bucket.

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

### 14. Data Validation Suite [COMPLETE]

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

### 16. Background Process Management

- Replace ad hoc background loops with a small managed runner.
- Track process PID, start time, last heartbeat, last snapshot, and errors.
- Add a command to stop/restart the snapshot loop cleanly.

### 17. Error Handling And Caching

- Add per-source retries with backoff.
- Preserve last-good live payloads when a source fails.
- Separate short TTLs for fast sources from slower/stabler sources.
- Log fetch failures into a local diagnostics file.

## Market Expansion

### 18. Multi-Day Market Support

- Parameterize target date, event slug, station, and data root.
- Allow creating a new market config without code edits.
- Reuse the same history and snapshot machinery for future Toronto markets.

### 19. Other Weather Markets

- Add support for other stations only after Toronto is solid.
- Define each market's resolution source and station mapping explicitly.
- Avoid assuming WU/Weather.com behavior transfers across locations.

## Research Questions

- Does WU final high usually equal Weather.com max-since-7 once history settles?
- How often does WU history revise after the live day ends?
- Which source best predicts WU final high by noon: Weather.com, Open-Meteo,
  Environment Canada, or empirical intraday analogs?
- Are market prices systematically too sticky around psychologically salient
  buckets like 25 C?
- Does edge persistence matter more than one-time edge size?

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
