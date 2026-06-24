# Wunderground CYYZ History Data Layer

This project treats Wunderground's Toronto Pearson history page as the market's
resolution source. The page is backed by Weather.com historical observations for
`CYYZ:9:CA`, so the local history layer stores that data as our closest
machine-readable proxy for settlement.

## Collection

Use the collector CLI:

```powershell
.\venv\Scripts\python.exe -m weather.sources.wu_history backfill --start 2026-05-20 --end 2026-05-27
```

For a larger backfill, use a wider date range and keep the default chunking:

```powershell
.\venv\Scripts\python.exe -m weather.sources.wu_history backfill --start 2015-01-01 --end 2026-05-27 --chunk-days 14
```

The collector fetches historical observations in chunks, writes raw daily
payloads, rebuilds normalized hourly partitions, and derives daily summaries.

## Failure Classes And Recovery

Weather.com/WU history uses the baked-in public Weather.com browser key in
`weather.sources.wu_history`. Treat that key as a known single point of failure
for canonical settlement history: `401`/`403` means auth failure, `429` means
rate limit, and `5xx`/timeouts are transient provider failures.

Backfill errors are written to `backfill_errors.jsonl` with `failure_class`.
Only `permanent_no_data` rows (`400`/`404`) are allowed to populate
`unavailable_dates()` and skip future `--skip-existing` backfills. Auth,
rate-limit, and transient rows remain re-fetchable.

If an older run poisoned `backfill_errors.jsonl` by treating recoverable rows as
source-unavailable, repair it per market:

```powershell
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto recover-unavailable
```

Use `--dry-run` to preview recovered ranges. After repairing the key or provider
outage, rerun the normal `backfill --skip-existing` command for the affected
window.

## Local Layout

```text
data/wunderground/cyyz/
  manifest.json
  raw/
    year=YYYY/month=MM/YYYY-MM-DD.json
  hourly/
    year=YYYY/month=MM/observations.jsonl
  daily/
    daily_summary.csv
```

Raw JSON preserves the source payload for auditability. Normalized JSONL is for
model features. The daily CSV is the fast path for climatology and backtests.

## Core Daily Fields

- `max_temp_c`: highest printed Wunderground/Weather.com observation for the day.
- `max_temp_bucket_c`: whole-degree C bucket using half-up rounding.
- `max_temp_times`: local times where the high appeared.
- `has_non_hourly_rows`: whether WU returned observations away from exact hours.
- `max_on_hour_mark`: whether the high occurred on an exact hourly row.
- `condition_mode` / `cloud_mode`: rough weather regime for same-day analogs.

## Analysis

Run the May 27 climatology window:

```powershell
.\venv\Scripts\python.exe -m weather.sources.wu_history analyze --month 5 --day 27
```

This reports bucket frequencies for a +/-7-day calendar window, plus the rate at
which highs appeared only in non-hourly rows. Once we backfill multiple years,
this becomes the historical prior for the live model.

## Model Integration Plan

1. Use `daily_summary.csv` to build a prior distribution for the target date:
   exact day, +/-3 days, and +/-7 days.
2. Condition the prior on broad weather regime:
   wind direction, cloud mode, and morning temperature.
3. Compare WU printed-high behavior with non-resolution sources:
   ECCC SWOB and METAR.
4. Backtest market-day forecasts:
   at each hour, estimate final bucket and score calibration.
5. Feed the calibrated historical prior into `TorontoHighTempModel` as a
   low-latency local feature instead of relying only on live forecasts.
