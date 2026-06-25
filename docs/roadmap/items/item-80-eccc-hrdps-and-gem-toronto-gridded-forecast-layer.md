# 80. ECCC HRDPS And GEM Toronto Gridded Forecast Layer [COMPLETE 2026-06-16 - TORONTO ECCC GRIDDED SCORING LIVE]

Goal: add official Canadian gridded model guidance for Toronto instead of
relying only on ECCC citypage/SWOB plus generic forecast APIs.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The audit confirmed MSC GeoMet collection access and live HRDPS Datamart GRIB2
files for 2026-06-15 00/06/12/18 UTC runs, including 2 m temperature and
10 m gust products.

Why this is missing: Toronto has official ECCC observations and city forecast
data, but no official high-resolution Canadian gridded forecast input. HRDPS is
specifically valuable near shores and local terrain, which matches Toronto's
lake-breeze and microclimate failure modes.

## Implementation Design

Source strategy:

- Add `weather.sources.eccc_gridded` with schema `eccc_gridded_v0.1`.
- Use Open-Meteo `/v1/gem` for the first live-only feature slice because a
  live probe confirmed model-suffixed `gem_seamless`, `gem_global`, and
  `gem_regional` columns for Toronto 2 m temperature, wind/gust, cloud,
  precipitation, RH, surface pressure, 925/850 hPa temperature, and 500 hPa
  height.
- Add raw HRDPS Datamart URL/filename/probe helpers for exact ECCC run
  provenance. These use item 76's GRIB probe helper, but full nearest-grid
  extraction remains explicit until the GRIB tooling/backfill path is ready.
- Register the source only for Toronto in this slice.

Feature strategy:

- Add Toronto live-only ECCC gridded columns to the shared feature schema with
  historical defaults of `None`.
- Derive GEM/HRDPS high forecast, model high spread, deltas versus the existing
  forecast consensus/Open-Meteo/Weather.com/ECCC citypage, remaining gust,
  cloud, precipitation, RH, vertical temperature profile, 500 hPa height, and a
  lake-breeze wind-shift flag.
- Preserve provider generation/runtime metadata when available; leave run age
  `None` when the JSON source does not expose a deterministic ECCC run time.

Verification:

- Test Open-Meteo GEM request/parse behavior with model-suffixed fixture
  columns, Datamart URL/probe helpers, feature derivation, Toronto-only source
  registration, and live feature extraction.

Out of scope for this implementation slice:

- Downloading full HRDPS grids in tests.
- Historical HRDPS/GEM backfills.
- Model promotion before Toronto settlement-scored evidence is reviewed.

Completed implementation slice on 2026-06-15:

- Added `weather.sources.eccc_gridded` with Open-Meteo GEM request/parse
  support for `gem_seamless`, `gem_global`, and `gem_regional`, plus HRDPS
  Datamart URL/filename/probe helpers backed by the item 76 GRIB probe.
- Registered Toronto-only live source `eccc_gem`, added forecast-cache TTL, and
  bumped the feature schema to `toronto_feature_store_v1.2`.
- Added live-only Toronto ECCC gridded diagnostics for GEM high/spread, deltas
  versus existing forecast sources, gust/cloud/precip/RH/vertical fields, and
  lake-breeze wind shift. Historical defaults remain `None`.

Completed implementation slice on 2026-06-16:

- Added row-level archive metadata for Open-Meteo GEM rows: valid time,
  explicit unknown run time/forecast hour status, grid/domain, source URL,
  payload hash, fetched-at time, and fetch-lag status.
- Added HRDPS probe fetch-lag metadata while preserving run time, forecast
  hour, valid time, grid/domain, source URL, and payload hash from item 76's
  GRIB probe foundation.
- Added a Toronto-only feature score report that groups lake-breeze,
  high-spread, post-cutoff-precip, and GEM-vs-consensus cases before Canadian
  expansion review.

- [x] Probe Open-Meteo GEM/HRDPS JSON coverage for Toronto fields that overlap
  item 74, and prefer that path for early feature experiments if provenance is
  adequate.
- [x] Use item 76's GRIB extraction foundation for raw HRDPS Datamart fields
  when exact ECCC run provenance, variables, or domains are required.
- [x] Extract HRDPS/GEM 2 m temperature, gust, cloud, precipitation, RH,
  pressure-level temperature, height, and lake-breeze-relevant wind fields.
- [x] Archive run time, forecast hour, valid time, grid/domain, source URL,
  payload hash, and fetch lag for every HRDPS/GEM row.
- [x] Add Toronto-specific features for HRDPS high forecast, lake-breeze wind
  shift, HRDPS minus Weather.com/Open-Meteo/ECCC citypage forecast deltas, and
  official Canadian model run age.
- [x] Score these features separately for Toronto before considering Canadian
  expansion markets.

Acceptance: Toronto has an official Canadian gridded forecast source with
train/serve parity or explicit live-only gates, and replay proves whether it
reduces forecast over/undercalls in lake-influenced regimes.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - TORONTO ECCC GRIDDED SCORING LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

