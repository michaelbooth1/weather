# 3. Forecast Archive [CLOSED]

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
