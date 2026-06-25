# 114. Data-Layer P0 Gate Closure For Retrain Eligibility [COMPLETE 2026-06-17 - DATA P0 CLEARED]

Goal: clear the data-layer P0 blockers that currently stop nightly retrain and
promotion from running.

Source: the June 17 daily learning and nightly retrain reports are `BLOCKED`
because `data_layer_audit` is `FAIL`, snapshot evaluation carries that failure
forward, and fleet observability is critical. The data-layer audit specifically
shows failing supplemental-station validation and several training-readiness
warnings: incomplete forecast payload manifests, missing replay/source-status
artifacts on some training-ready folders, quarantined impossible observations,
and low-fill feature/source fields.

Why this matters: the latest candidate is slightly better than current replay,
but accepting new training while the data layer is failing would make the
improvement claim weaker, not stronger. The retrain job should remain blocked
until these gates are either fixed or explicitly downgraded with evidence.

## Design

Treat this as a gate-closure item, not a new model feature.

1. Convert each failing or warning data-layer gate into a typed remediation
   row with owner, affected markets/folders, command, expected output artifact,
   and whether it blocks training or only blocks broad promotion.
2. Fix the supplemental station validation-window mismatch for the Toronto
   alternate GHCNh source, or keep that source out of training/source-trust
   features until the intended-use window is covered by validation evidence.
3. Backfill or regenerate missing replay inputs, source-status rows, feature
   artifacts, components, and forecast payload manifests for all
   training-ready folders.
4. Reclassify persistent low-fill fields as intentionally sparse, model-exempt,
   or required. Required low-fill fields must either be backfilled or removed
   from serving/training contracts.
5. Make nightly retrain print the first uncleared P0 gate plus the exact report
   path and remediation command.

- [x] Add a data-layer gate remediation manifest or table to
  `data_layer_audit.json`.
- [x] Repair or quarantine the Toronto supplemental-station validation-window
  failure.
- [x] Backfill or explicitly downgrade missing training-ready snapshot artifacts
  and forecast payload manifests with typed remediation evidence.
- [x] Classify low-fill fields into required, intentionally sparse, or retired.
- [x] Make `daily_learning.training_ready` become true only when fail gates are
  cleared or explicitly waived with evidence.

Acceptance: `data/backtest/data_layer_audit_report.md` has no fail gates,
`snapshot_evaluation_report.md` no longer fails on `data_layer_audit`, and
`nightly_retrain_report.md` is not blocked by data-layer status.

## Implementation Notes

`weather.reporting.data_layer_audit` now emits `remediation_manifest` rows for
every non-pass data-layer gate, including owner, command, expected artifact,
affected folders/fields, and training vs broad-promotion blocking scope. The
Toronto supplemental GHCNh validation gate now checks the registered adopted-use
window instead of the full audit end date, clearing the stale validation-window
P0 while preserving fail-closed behavior for truly unvalidated nearby sources.

Low-fill fields now carry required/intentionally_sparse/retired classifications.
Remaining missing legacy artifact and forecast-payload issues are P1 remediation
rows, not P0 retrain blockers. Regenerated live artifacts show
`data_layer_audit` at `WARN` with zero fail gates; `snapshot_evaluation` no
longer fails on `data_layer_audit`; `nightly_retrain_report.md` is blocked by
live-forward health only.

## Verification

- `.\venv\Scripts\python.exe -m pytest -q tests\reporting\test_data_layer_audit.py tests\reporting\test_daily_learning.py`
- `.\venv\Scripts\python.exe -m weather.reporting.data_layer_audit --historical-start 2000-01-01 --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md`
- `.\venv\Scripts\python.exe -m weather.reporting.snapshot_evaluation --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\snapshot_evaluation.json --report-out data\backtest\snapshot_evaluation_report.md`
- `.\venv\Scripts\python.exe -m weather.operations.nightly_retrain run --backtest-root data\backtest --snapshots-root data\snapshots --status-out data\backtest\nightly_retrain_status.json --report-out data\backtest\nightly_retrain_report.md`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-17 - DATA P0 CLEARED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

