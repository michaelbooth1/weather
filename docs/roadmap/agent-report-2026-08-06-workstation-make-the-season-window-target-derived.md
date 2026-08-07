# Workstation report 2026-08-06 — make the season window target-derived

## Verdict

**PASS — the free archive endpoint serves the declared late-July target window for all 60
market/year units, archive requests are now derived from the caller's training target plus the
trainer's climatology halo, and an archive containing the old May 10–June 30 season can no longer
report healthy for target `2026-07-31`. The repaired workstation gate reports `BLOCK`, 0/12 healthy
markets, against the existing archive. No production collection was performed.**

For target `2026-07-31`, the first-retrain selection radius is 7 days and
`HISTORY_WINDOW_DAYS` is 7 days. The resulting archive radius is therefore 14 days:
`July 17–August 14` in each analog year. Across policy years 2021–2025 this is 29 dates per year,
145 required dates per market, and 1,740 fleet market-dates. The archive target is supplied by the
caller; neither the manifest nor the archive's own dates may select it.

## Branch and basis

- Branch: `codex/workstation-make-the-season-window-target-derived-2026-09-33a`
- Required `-09-20a` basis: `981b1d3a8cfa6b6859e530f180452382e5b4296e`
- Implementation commit: `IMPLEMENTATION_COMMIT_PENDING`
- Current-master refresh: `MASTER_REFRESH_PENDING`
- PR: none
- Integration merge: none

## P0 fleet falsifier

The workstation queried the existing free-tier endpoint
`https://historical-forecast-api.open-meteo.com/v1/forecast` for all 12 built-in markets and every
year 2021–2025. The probe used the handoff's selected-date target window, July 24–August 7, and the
module's complete requested hourly schema.

| Measure | Result |
| --- | ---: |
| Market/year requests | 60 |
| HTTP 200 | 60/60 |
| Expected 360 local hourly timestamps | 60/60 |
| Identical requested schema keys | 60/60 |
| Complete gate-required core fields | 60/60 |
| Network/provider errors | 0 |
| Required-contract failures | 0 |

The source returned all requested keys in every unit. It also reproduced the archive's existing
audit-only availability boundary: `precipitation_probability` was all-null in 2021–2023 (36 units),
and the two soil fields were all-null in 2021–2022 (24 units). All audit fields were populated in
2024–2025. Those are not silently promoted to complete: they remain visible in
`missing_nonnull_fields`. They do not fire the P0 stop condition because
`RICH_CORE_REQUIRED_NON_NULL_FIELDS` is the archive's existing required contract and all seven of
those fields were complete in all 60 units. No field was removed and no response used a different
schema.

This is an exact availability probe over 60 market/year units, not a model-effect estimate. There is
no statistical interval and crossed date × market clustering is not applicable.

## Repair

`src/weather/sources/forecast_history.py` no longer contains `SEASON_START` or `SEASON_END`.

- Backfill and provider fetch helpers require `target_date`.
- `archive_window_for_target()` maps that date into each requested analog year and adds the existing
  first-retrain `+/-7` selected-date radius to the existing `HISTORY_WINDOW_DAYS=7` climatology halo.
- A regression binds the source defaults to
  `base_retrain.FIRST_RETRAIN_SEASON_RADIUS_DAYS` and
  `model_constants.HISTORY_WINDOW_DAYS` without adding a runtime `sources -> operations/model`
  import edge.
- The manifest records the exact target, both radii, the combined radius, and requested/effective
  start/end dates for every fetched year.
- `coverage` and `fleet-coverage` require `--target-date`. `--years` is caller/policy input; when it
  is omitted the policy is 2021 through `target_year - 1`. Neither value is read from the manifest.
- Coverage enumerates the complete required date set and intersects it with actual historical rows.
  It independently requires the manifest target and per-year requested windows to match. Either
  missing dates or identity mismatch blocks the fleet gate.
- The existing per-market `OK`/`FAIL`/`MISSING` status vocabulary remains compatible. Additive
  `target_status` and fleet `status` fields report `PASS`/`BLOCK`, and the CLI exits nonzero on
  `BLOCK`.

The deterministic wrong-season regression builds the production-observed shape: 52 dates per year,
May 10–June 30, for 2021–2025. Against target `2026-07-31`, it covers 0/145 required dates, its
manifest target mismatches, and the fleet report is `BLOCK`. The workstation's ignored archive also
now reports `Forecast history coverage OK markets: 0/12`; before this repair the command reported
12/12 because it had no target standard.

## Serving boundary

The legacy archive remains an active serving input and this mission does not separate that coupling.
No serving loader, `model_features.py`, source adapter, serving pointer, or data path changed. The
change is limited to archive construction and archive coverage. Merely checking coverage does not
alter what serving reads. Any later collection into the active archive remains an explicit operator
decision because it will replace rows consumed by the existing serving compatibility path.

## Per-file roll verdict

Verdict derived from retained `runtime_identity.source_scope_files` in the workstation's four
capture status files:

| File | Snapshot | Raw CLOB | Observation trigger | CLOB enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `src/weather/sources/forecast_history.py` | in closure | not in closure | in closure | not in closure | **Roll-sensitive; merge only 01:00–04:00** |
| `tests/sources/test_historical_sources.py` | not in closure | not in closure | not in closure | not in closure | Roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-make-the-season-window-target-derived.md` | not in closure | not in closure | not in closure | not in closure | Roll-free |

This branch requires a quiet-window merge. Do not merge it during the 12:00–18:00 graded window.

## Verification

```text
5 forecast-history tests passed
166 source-owner tests passed (one pre-existing NumPy binary-compatibility warning)
21 import-architecture tests passed
compileall src/weather passed
full-suite pytest: inconclusive; the command hit the 603.6-second tool bound without a pytest summary
```

The wrong-season regression is
`test_forecast_history_fleet_coverage_blocks_archive_for_wrong_season`. The positive controls prove
the target-derived bounds, manifest binding, and a matching manifest/date set that remains `OK`.

## Production-host reproduction

Run from the production repository root shown in retained status evidence:
`C:\Users\micha\Desktop\github\weather`.

```powershell
.\venv\Scripts\python.exe -m pytest tests\sources\test_historical_sources.py -q -k "forecast_history"
.\venv\Scripts\python.exe -m pytest tests\sources -q
.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q
.\venv\Scripts\python.exe -m compileall -q src\weather
```

The current archive must fail closed for the declared target; exit code 2 is expected until an
operator-authorized rebuild writes a matching target window:

```powershell
.\venv\Scripts\python.exe -m weather.sources.forecast_history fleet-coverage --target-date 2026-07-31 --years 2021,2022,2023,2024,2025
```

Safe read-only reproduction of the 60-unit provider probe (no file write):

```powershell
@'
import time
from weather.market.market_registry import all_specs
from weather.sources.forecast_history import (
    OPEN_METEO_HOURLY_FIELDS,
    RICH_CORE_REQUIRED_NON_NULL_FIELDS,
    fetch_historical_forecast_payload,
)

failures = []
audit_nulls = {}
for spec in all_specs():
    for year in range(2021, 2026):
        payload = fetch_historical_forecast_payload(
            year,
            spec,
            target_date="2026-07-31",
            target_window_days=7,
            history_window_days=0,
        )
        hourly = payload.get("hourly") or {}
        required = {
            "cloud_cover": "cloud_cover",
            "low_cloud": "cloud_cover_low",
            "mid_cloud": "cloud_cover_mid",
            "high_cloud": "cloud_cover_high",
            "shortwave_radiation": "shortwave_radiation",
            "direct_radiation": "direct_radiation",
            "diffuse_radiation": "diffuse_radiation",
        }
        missing = [
            field for field, source in required.items()
            if len(hourly.get(source) or []) != 360
            or any(value is None for value in (hourly.get(source) or []))
        ]
        if len(hourly.get("time") or []) != 360 or missing:
            failures.append((spec.id, year, len(hourly.get("time") or []), missing))
        for field in OPEN_METEO_HOURLY_FIELDS:
            values = hourly.get(field) or []
            if values and not any(value is not None for value in values):
                audit_nulls[field] = audit_nulls.get(field, 0) + 1
        time.sleep(0.4)
print({"requests": 60, "required_failures": failures, "audit_null_units": audit_nulls})
'@ | .\venv\Scripts\python.exe -
```

Expected required failures: `[]`. Expected audit-null unit counts:
`precipitation_probability=36`, `soil_temperature_0cm=24`,
`soil_moisture_0_to_1cm=24`.

## What was not done

- No write to production or workstation `data/`; no archive rebuild or corpus staging.
- No retrain, fit, candidate, release, promotion, or reservation.
- No scheduled-task registration, loop start, restart, or process mutation.
- No production fetch and no paid provider/API.
- No serving-loader, model-feature, reporting lane, operations refresh, WU, or market-stack change.
- No merge and no PR.
