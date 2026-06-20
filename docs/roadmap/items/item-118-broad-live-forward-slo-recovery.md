# 118. Broad Live-Forward SLO Recovery [COMPLETE 2026-06-17 - RECOVERY CHECKLIST LIVE]

Goal: restore all-selected live-forward countability so nightly learning can
advance from "partial per-market credit" to broad promotion-grade evidence.

Source: the 2026-06-17 daily learning and nightly retrain reports remain
`BLOCKED` after data-layer P0 gates were cleared. The first blocker is
`live_forward_slo is FAIL: counts_toward_live_forward_gate=False`, and fleet
observability is `CRITICAL`. Item 116 preserves per-market model-review and
paper-trading credit, but it intentionally keeps broad live-forward and
live-trade claims fail-closed.

Why this matters: per-market credit prevents useful evidence from being thrown
away, but the core model still needs full live-forward collection days before
the nightly retrain/promotion loop can make stronger claims. If the broad SLO
stays blocked, daily learning will keep reporting useful learnings without
training or promotion readiness.

## Design

1. Treat broad live-forward SLO recovery as a current operations blocker, not
   as another evidence-accounting change.
2. Split the broad SLO failure into concrete gates: snapshot coverage gaps,
   latest model-row freshness, source-status freshness, CLOB book freshness,
   observation-trigger health, and required afternoon-window coverage.
3. Add an operator-visible recovery checklist that states which market and
   component is preventing `counts_toward_live_forward_gate=True`.
4. Add a bounded same-day recovery path for stale model rows and stale CLOB book
   rows, then rerun the reconciled live-forward gate after repair.
5. Keep broad live-trade permission separate from paper/model-review evidence:
   this item is complete when all selected markets can count for live-forward
   model-review/paper evidence, not when live trading is enabled.

- [x] Add a broad-live-forward recovery table to fleet observability or nightly
  retrain status with first failing market/component, owner, and command.
- [x] Add same-day repair commands for stale model rows and stale CLOB book
  rows, with before/after evidence in the run report.
- [x] Require afternoon-window snapshot coverage and latest-capture freshness
  to pass for every selected market before setting the broad day countable.
- [x] Add regression coverage for the June 17 blocked state after per-market
  credit is already available.
- [x] Make `daily_learning.training_ready` and `promotion_ready` stay false
  until the broad SLO passes or an explicit non-promotion waiver is recorded.

Acceptance: after a healthy active day, `daily_learning_report.md`,
`nightly_retrain_report.md`, and `fleet_observability_report.md` all agree that
the broad live-forward SLO counts, or they identify the one remaining
component, owner, and repair command blocking the count.

## Completion Notes

Implemented the broad live-forward recovery checklist in
`weather.reporting.fleet_observability`. The fail-closed aggregate SLO now keeps
its existing component gates and also emits concrete gates for snapshot coverage
gaps, latest model-row freshness, source-status freshness, CLOB book freshness,
observation-trigger health, and afternoon-window coverage.

`daily_learning` now carries the same broad-SLO object into the retrain plan,
uses the first recovery row as the P0 action, and keeps training/promotion
readiness false while `counts_toward_live_forward_gate=False`. Nightly retrain
relays that same object into its status and markdown report.

Verification:

- `.\venv\Scripts\python.exe -m pytest -q tests\reporting\test_fleet_observability.py tests\reporting\test_daily_learning.py tests\operations\test_nightly_retrain.py`
- `.\venv\Scripts\python.exe -m weather.reporting.fleet_observability report --snapshots-root data\snapshots --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md --provenance-out data\backtest\artifact_provenance_manifest.json`
- `.\venv\Scripts\python.exe -m weather.reporting.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md`
- `.\venv\Scripts\python.exe -m weather.operations.nightly_retrain run --backtest-root data\backtest --snapshots-root data\snapshots --daily-learning-out data\backtest\daily_learning.json --daily-learning-report data\backtest\daily_learning_report.md --status-out data\backtest\nightly_retrain_status.json --report-out data\backtest\nightly_retrain_report.md --skip-family-secondary --skip-pooled-feature --skip-artifact-registry --skip-promotion-refresh --skip-shadow-ab-monitor --disable-long-job-guard`

Live generated reports agree on the current blocker: `BLOCK`, first market
`toronto`, component `snapshot_collection`, gate `snapshot_coverage_gap`, owner
`weather snapshot/model loop`, repair command
`python -m weather.collection.snapshot_tracker --status`.
