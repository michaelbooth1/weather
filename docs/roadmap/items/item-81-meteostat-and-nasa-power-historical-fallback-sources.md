# 81. Meteostat And NASA POWER Historical Fallback Sources [COMPLETE 2026-06-16 - SUPPLEMENTAL FALLBACK GATES LIVE]

Goal: use free global historical sources for station discovery, source
redundancy, and energy-budget backfills without mistaking model-filled data for
settlement truth.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The audit confirmed Meteostat bulk hourly CSV/GZIP access with source columns,
and NASA POWER hourly meteorology/solar data for older dates with recent
near-real-time lag and fill-value caveats.

Why this is missing: the project has strong official sources for current
12-market coverage, but global expansion and older backfills still need cheap
station discovery, weather-regime context, and solar/energy-budget fallbacks
where local station or forecast archives are incomplete.

## Implementation Design

Source strategy:

- Add `weather.sources.historical_fallbacks` with schema
  `historical_fallbacks_v0.1`.
- Add Meteostat bulk URL builders, station metadata parsing, nearest-station
  discovery reporting, and hourly CSV normalization that preserves every source
  column and classifies rows as observed, model-filled, mixed, or unknown.
- Add NASA POWER hourly request builders and payload normalization for solar,
  clear-sky solar, pressure, wind, dewpoint, humidity, temperature, and
  precipitation, including per-parameter fill-value rates.
- Keep all normalized rows explicitly marked as supplemental context, never
  settlement labels or canonical observation replacements.

Feature/research strategy:

- Emit source-trust and energy-budget research rows only. Do not add trained
  feature columns in this slice.
- Provide a policy helper that makes allowed and disallowed uses machine
  readable for reports and downstream gates.

Verification:

- Test Meteostat station discovery, hourly source preservation/model-filled
  classification, NASA POWER request/normalization/fill rates, and the
  supplemental-only policy.

Out of scope for this implementation slice:

- Fleet-scale Meteostat/NASA downloads.
- Promotion into trained features before replay evidence is reviewed.

Completed implementation slice on 2026-06-15:

- Added `weather.sources.historical_fallbacks` with Meteostat bulk URL builders,
  station metadata parsing, nearest-station discovery reports, and hourly row
  normalization that preserves source columns and flags model-filled/mixed rows.
- Added NASA POWER hourly request builders and normalization for solar,
  clear-sky solar, temperature, dewpoint, RH, precipitation, pressure, wind
  speed, and wind direction with per-parameter fill-value rates.
- Registered schema `historical_fallbacks_v0.1` and added a machine-readable
  supplemental-only policy disallowing settlement-label or canonical-truth use.

Completed implementation slice on 2026-06-16:

- Added a coverage/bias report comparing Meteostat and NASA POWER rows against
  WU, METAR, GHCNh, reanalysis, and validated supplemental stations by market
  and regime.
- Added markdown rendering for the fallback coverage/bias report so source
  trust findings can be reviewed without promoting the data to truth labels.
- Added a fallback-feature promotion gate that requires settlement replay lift
  beyond existing Open-Meteo/reanalysis/history features and blocks settlement
  label or canonical-observation replacement roles.

- [x] Add a source-discovery report that compares Meteostat station metadata and
  hourly bulk coverage against configured market stations and potential global
  expansion markets.
- [x] Preserve Meteostat `_source` columns and classify model-filled values
  separately from observed station values in every normalized row.
- [x] Add NASA POWER backfill probes for historical solar, clear-sky solar,
  pressure, wind, dewpoint, humidity, and precipitation over target-season
  windows, recording fill-value rates and publication lag.
- [x] Use Meteostat and NASA POWER only as supplemental source-trust,
  weather-regime, or energy-budget features, never as settlement labels or
  canonical observation replacements.
- [x] Add coverage/bias reports comparing these sources against WU, METAR,
  GHCNh, reanalysis, and validated supplemental stations by market and regime.
- [x] Promote any resulting features only after replay proves they add value
  beyond existing Open-Meteo/reanalysis/history features.

Acceptance: Meteostat and NASA POWER become documented supplemental inputs for
global expansion and historical feature research, with source/fill provenance
strong enough to keep model-filled or lagged data out of canonical truth paths.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - SUPPLEMENTAL FALLBACK GATES LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

