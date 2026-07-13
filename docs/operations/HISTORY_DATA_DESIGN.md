# Wunderground CYYZ History Data Layer

Classification: historical Toronto foundation plus a current CYYZ recovery
runbook. It is not the canonical multi-market architecture description; use
[Agent Context](AGENT_CONTEXT.md) for current settlement/unit invariants.

This project treats Wunderground's Toronto Pearson history page as the market's
resolution source. The local history layer stores Weather Underground-derived
raw/hourly/daily artifacts as the closest machine-readable proxy for settlement.

Paid-provider weather access is not a supported path. Do not add credentials,
env vars, paid-provider fetch commands, or recommendations that depend on
paid-provider access. The legacy paid-provider adapter in
`weather.sources.wu_history` is intentionally disabled; WU collection uses the
public Weather Underground page-backed collector with explicit provenance.

## Collection

The current CLI can collect, audit, rebuild, and recover local WU artifacts:

```powershell
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto public-backfill --start 2026-06-29 --end 2026-06-29 --skip-existing
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto audit
```

`public-backfill` fetches the public WU history page first, derives page-backed
history access from that response at runtime, persists source payloads, rebuilds
normalized hourly partitions, and derives daily summaries in the existing
schema.

## Failure Classes And Recovery

The old paid-provider backfill path is disabled before network access. A missing
WU day is a public collection/data-availability problem, not a credential
problem.

Backfill errors are written to `backfill_errors.jsonl` with `failure_class`.
Only `permanent_no_data` rows (`400`/`404`) are allowed to populate
`unavailable_dates()` and skip future `--skip-existing` backfills. Auth,
rate-limit, and transient rows remain re-fetchable.

If an older run poisoned `backfill_errors.jsonl` by treating recoverable rows as
source-unavailable, repair it per market:

```powershell
.\venv\Scripts\python.exe -m weather.sources.wu_history --market toronto recover-unavailable
```

Use `--dry-run` to preview recovered ranges. After repairing public WU
collection, rerun `public-backfill` for the affected window.

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

- `max_temp_c`: highest printed Weather Underground observation for the day.
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
