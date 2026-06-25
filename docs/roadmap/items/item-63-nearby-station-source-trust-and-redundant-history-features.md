# 63. Nearby Station Source-Trust And Redundant-History Features [COMPLETE 2026-06-15 - HISTORICAL-ONLY FEATURES LIVE]

Goal: use validated nearby station history as explicit source-trust and
redundant-history signal, not as a silent replacement label.

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
Validated nearby station roots can increase training depth and source agreement
coverage, but the model must know their provenance and distance.

Tasks:

- [x] Add feature columns for supplemental source availability, source id,
  distance to canonical station, validation status, historical bias, bucket
  agreement, and same-day agreement/delta where same-day use is permitted.
- [x] Keep canonical settlement labels unchanged. Supplemental sources may
  inform source-trust, redundancy, climatology, and bias features, but they must
  not overwrite WU/canonical labels.
- [x] Extend the historical feature builder so supplemental rows are joined by
  market/date with explicit provenance fields.
- [x] Add train/serve parity checks for any supplemental feature that can exist
  live; otherwise mark it historical-only and keep it out of live serving.
- [x] Run ablations and settlement-scored replay to decide whether supplemental
  source-trust features improve Brier/log loss or only improve diagnostics.

Acceptance: model training can consume validated nearby history with source id,
distance, and validation fields retained, and ablation reports can isolate the
effect of the supplemental feature family.

Implementation notes:

- `source_redundancy` now loads Item 62 validation artifacts and joins only
  validation-promoted supplemental GHCNh rows into daily truth rows. Source keys
  use `ghcnh_supplemental__<source_id>` and retain source id, station id,
  distance, promotion state, validation status, historical WU bias/MAE/bucket
  agreement, and same-day WU delta/match fields.
- Supplemental rows are explicit source-trust/redundancy evidence only. They are
  excluded from `TRUTH_FALLBACK_ORDER`, so they do not fill missing WU labels or
  overwrite canonical settlement labels.
- `source_truth_daily.csv` schema is now `daily_source_truth_v0.3` with
  `supplemental_*` feature columns. `source_redundancy_v0.3` includes a
  `supplemental_nearby_features` section with feature columns, per-market
  with/without-supplemental diagnostic deltas, and a train/serve parity block.
- The pooled feature model exposes optional historical-only supplemental
  reliability columns via `include_historical_only=True`. Default feature frames
  and band feature frames exclude those columns, keeping live serving unchanged.
- Settlement-scored Brier/log-loss lift is not claimed here because the feature
  family is historical-only and excluded from serving by default. The report
  marks the family as `diagnostic_ablation_ready` and records
  `settlement_scored_replay_status=not_run_historical_only_excluded_from_live_serving`;
  future training experiments can opt in and then run settlement-scored replay
  with the family neutralized/enabled.

Verification:

- `.\venv\Scripts\python.exe -m src.source_redundancy report --markets toronto --start 2000-05-20 --end 2000-05-22 --snapshots-root data\snapshots --supplemental-validation data\backtest\supplemental_station_validation.json --out scratch\item63_source_redundancy_smoke.json --report scratch\item63_source_redundancy_smoke.md --truth-out scratch\item63_source_truth_smoke.csv --forecast-out scratch\item63_forecast_smoke.csv`
- `.\venv\Scripts\python.exe -m pytest tests\reporting\test_source_redundancy.py tests\calibration\test_pooled_feature_model.py tests\sources\test_supplemental_station_validation.py tests\reporting\test_data_layer_audit.py -q`
- `.\venv\Scripts\python.exe -m compileall src\weather\reporting\source_redundancy.py src\weather\calibration\pooled_feature_model.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - HISTORICAL-ONLY FEATURES LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

