# 63. Nearby Station Source-Trust And Redundant-History Features [NEW - AUDIT FOLLOW-UP]

Goal: use validated nearby station history as explicit source-trust and
redundant-history signal, not as a silent replacement label.

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
Validated nearby station roots can increase training depth and source agreement
coverage, but the model must know their provenance and distance.

Tasks:

- [ ] Add feature columns for supplemental source availability, source id,
  distance to canonical station, validation status, historical bias, bucket
  agreement, and same-day agreement/delta where same-day use is permitted.
- [ ] Keep canonical settlement labels unchanged. Supplemental sources may
  inform source-trust, redundancy, climatology, and bias features, but they must
  not overwrite WU/canonical labels.
- [ ] Extend the historical feature builder so supplemental rows are joined by
  market/date with explicit provenance fields.
- [ ] Add train/serve parity checks for any supplemental feature that can exist
  live; otherwise mark it historical-only and keep it out of live serving.
- [ ] Run ablations and settlement-scored replay to decide whether supplemental
  source-trust features improve Brier/log loss or only improve diagnostics.

Acceptance: model training can consume validated nearby history with source id,
distance, and validation fields retained, and ablation reports can isolate the
effect of the supplemental feature family.
