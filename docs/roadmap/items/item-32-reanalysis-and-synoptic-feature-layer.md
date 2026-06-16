# 32. Reanalysis And Synoptic Feature Layer [PARTIAL 2026-06-16 - TELECONNECTIONS ADDED, GATE BLOCKED]

Goal: add physically meaningful, multi-decade-consistent inputs the obs-only set
lacks.

- [x] ERA5 antecedent-day state sidecar, with future soil/cloud/radiation/VPD/ET0
  archive fields wired into the reanalysis fetch plan.
- [ ] Pressure-level upper-air source for 850 mb temperature, 500 mb height, and
  thickness. Open-Meteo Historical Weather / ERA5 archive did not populate the
  forecast-style pressure-level fields in the 2026-06-16 probe, so these remain
  blocked until a pressure-level reanalysis source is added.
- [x] Teleconnection indices (ENSO/PNA), coastal sea-breeze and continentality
  flags per city.
- [x] Add only behind the model harness (item 36); promote features that improve
  out-of-sample skill.

Acceptance: each new feature family earns its place via settlement-scored
validation, not importance charts (extends item 27 to all markets).

## 2026-06-16 update

- Added `reanalysis_synoptic_features_v0.1` as a gated sidecar instead of
  changing the shared historical hourly schema. The feature-store schema is now
  `toronto_feature_store_v1.4`, and live serving receives null defaults unless
  a validated artifact explicitly uses the sidecar.
- Built the Toronto sidecar:
  `data/backtest/item32_reanalysis_synoptic_toronto_summary.json` and
  `data/backtest/item32_reanalysis_synoptic_toronto_report.md`. Coverage:
  9,658 rows from 2000-01-01 through 2026-06-10, with 9,657 antecedent-day
  rows. Existing archives populate antecedent temperature, dewpoint, wind, gust,
  pressure, heat-anomaly, coastal, and continentality fields; newly requested
  soil/cloud/radiation/VPD/ET0 fields will populate after rich reanalysis
  backfills refresh raw archive chunks.
- Ran the settlement-scored Item 27 gate for Toronto:
  `data/wunderground/cyyz/analysis/item27_feature_value_gate.json`. The broad
  `reanalysis_synoptic` family was blocked on 9,100 held-out rows
  (`delta_logloss=-0.0045`, `delta_brier=-0.0021`), so no feature promotion was
  made.
- Remaining work: add a pressure-level reanalysis source, add ENSO/PNA index
  ingestion, rebuild rich raw reanalysis chunks for soil/cloud/radiation fields,
  and rerun settlement-scored gates market-by-market or with a narrower family
  before promotion.

## 2026-06-16 teleconnection/static-context update

- Bumped the gated sidecar to `reanalysis_synoptic_features_v0.2` and the
  shared feature-store schema to `toronto_feature_store_v1.5`.
- Added sidecar columns for static sea/lake-breeze context from the existing
  marine-context registry: sea-breeze context flag, lake-breeze context flag,
  nearest configured water distance, and marine-context station count. The
  existing coastal and continentality fields remain in the same gated family.
- Added local NOAA CPC teleconnection ingestion for ONI and PNA snapshots:
  `data/backtest/item32_teleconnections/oni.ascii.txt` from
  `https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` and
  `data/backtest/item32_teleconnections/pna.monthly.ascii` from
  `https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.pna.monthly.b5001.current.ascii`.
  Serving/training rows use only the latest completed month or season available
  before the target month, so target-month teleconnection values do not leak
  into historical features.
- Rebuilt the Toronto sidecar at
  `data/reanalysis/cyyz/features/reanalysis_synoptic_features.csv` and wrote
  audit artifacts:
  `data/backtest/item32_reanalysis_synoptic_toronto_v02_summary.json` and
  `data/backtest/item32_reanalysis_synoptic_toronto_v02_report.md`. Coverage is
  9,658 rows from 2000-01-01 through 2026-06-10; the new static and
  teleconnection fields are present on all rows.
- Reran the settlement-scored Item 27 gate for Toronto:
  `python -m src.feature_model --market toronto --item27-report-only --item27-folds 5`.
  The broad `reanalysis_synoptic` family remains blocked on held-out scoring
  (`delta_logloss=-0.0118`, `delta_brier=-0.0047`), so no feature promotion was
  made.
- Remaining work: add a pressure-level reanalysis source for 850 mb
  temperature, 500 mb height, and thickness; backfill rich raw reanalysis chunks
  for the still-empty soil/cloud/radiation/VPD/ET0 fields; and test narrower
  subfamilies before any promotion.
