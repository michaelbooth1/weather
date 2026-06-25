# 62. Nearby Station Validation And Promotion Gates [COMPLETE 2026-06-15 - VALIDATION GATE LIVE]

Goal: require empirical validation before a nearby station can be promoted from
"available data" to "usable redundant history."

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
Toronto `CAN06158733` is the reference case: 0.05 km from the canonical station,
537 target-season WU overlap days, 0.247 C MAE, and 99.6% WU bucket match.

Tasks:

- [x] Define validation thresholds by market unit and source role: minimum
  overlap days, target-season MAE, bucket-match rate, max absolute difference,
  missing-day reduction, and maximum distance/elevation mismatch.
- [x] Generate a durable bias report for each candidate nearby source against
  WU settlement history, METAR/ASOS, canonical GHCNh where available, and
  reanalysis as a weak sanity check.
- [x] Split validation by full period, target season, and weather regime so a
  station that works in mild May/June weather is not blindly trusted elsewhere.
- [x] Add promotion states: `candidate`, `validated_supplemental`,
  `shadow_only`, `rejected`, and `retired`.
- [x] Fail closed when a supplemental source lacks a current validation report
  or when its metrics fall outside the configured thresholds.

Acceptance: no nearby station can enter training or source-trust features until
its validation artifact proves acceptable overlap, bias, bucket agreement, and
distance/elevation suitability for the intended market/date window.

Implementation notes:

- Added `weather.sources.supplemental_station_validation` and the top-level
  `src/supplemental_station_validation.py` wrapper. The module writes durable
  JSON/Markdown artifacts, computes source fingerprints, assigns promotion
  states, and exposes `promotion_gate_for_source(...)` for fail-closed training
  and source-trust consumers.
- Added unit/source-role threshold profiles for C and F supplemental stations.
  Target-season WU and METAR overlap/bias/bucket/max-absolute gates are hard;
  canonical GHCNh is checked when available, reanalysis is weak sanity evidence,
  and full-period bias shape remains diagnostic so out-of-season drift is
  visible without blocking target-season use.
- Integrated the validation artifact into `data_layer_audit`: canonical plus
  supplemental coverage now counts only validation-promoted supplemental days,
  and the `supplemental_station_validation` audit gate fails closed when a
  registered source is missing, stale, retired, rejected, or still candidate.
- Generated the local Toronto artifact:
  `data/backtest/supplemental_station_validation.json` and
  `data/backtest/supplemental_station_validation_report.md`. Toronto
  `ghcnh_cyyz_alt_can06158733` is now `validated_supplemental` with 546 added
  target-season days, 537 WU overlap days, 0.247 C WU MAE, 99.6% WU bucket
  match, and validated cool/mild/hot target-season regimes.

Verification:

- `.\venv\Scripts\python.exe -m src.supplemental_station_validation --markets toronto --start 2000-01-01 --end 2026-06-14 --out data\backtest\supplemental_station_validation.json --report data\backtest\supplemental_station_validation_report.md --strict`
- `.\venv\Scripts\python.exe -m pytest tests\sources\test_supplemental_station_validation.py tests\sources\test_historical_sources.py tests\reporting\test_data_layer_audit.py tests\reporting\test_source_redundancy.py tests\calibration\test_pooled_feature_model.py -q`
- `.\venv\Scripts\python.exe -m compileall src\weather\sources\supplemental_station_validation.py src\supplemental_station_validation.py src\weather\reporting\data_layer_audit.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - VALIDATION GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

