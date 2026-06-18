# 108. Overnight Self-Improvement Run Evidence And Blocker SLA [COMPLETE 2026-06-17 - NIGHTLY SLA LIVE]

Goal: make the nightly self-improvement job prove that it ran, stopped on
blocking evidence, and produced one operator-readable reason when retraining
or promotion should not continue.

Source: 2026-06-16 settled-day audit. The daily refresh ran successfully on
2026-06-17 at 09:30, but the expected `WeatherNightlyRetrainValidatePromote`
scheduled task was not registered and no
`data/backtest/nightly_retrain_status.json` existed. The daily learning report
was `BLOCKED` with 3 blockers, including data-layer failure, snapshot
evaluation failure, and fleet observability critical status.

Why this matters: the model cannot improve overnight if the self-improvement
job is missing or if it runs past known P0 gates. A missing task should be a
first-class alert, and a blocked daily-learning state should short-circuit
expensive retrain/promotion steps until the blocker is repaired.

## Design

1. Register and monitor the nightly retrain task as part of the same operations
   inventory that already checks snapshot, CLOB, observation, daily refresh,
   and market-making roll tasks.
2. Treat `daily_learning.status == BLOCKED` as a retrain and promotion blocker
   by default. The run status should be `blocked`, not `promote_ready`, if
   daily learning says training or promotion is unsafe.
3. Add a missed-run SLA: when the current date is after the scheduled window
   and no fresh nightly status exists, surface a P0 operations alert with the
   expected task name, schedule, and last known status path.
4. Include daily-learning blockers in `nightly_retrain_report.md` so the report
   answers "why did the model not retrain?" without reading several JSON files.
5. Add one smoke command that operators can run after registration to verify
   dry-run planning, task inventory visibility, and blocker short-circuiting.

- [x] Register `WeatherNightlyRetrainValidatePromote` on every production host.
- [x] Add a missed-run freshness check for `nightly_retrain_status.json`.
- [x] Keep daily-learning blocker short-circuit enabled by default for the
  scheduled task.
- [x] Show nightly task registration and last run status in the dashboard.
- [x] Add a documented post-registration smoke test.

Acceptance: a settled-day audit can tell from one report whether the nightly
self-improvement job ran, whether it was blocked, and what exact P0 gate must
be fixed before retraining or promotion resumes.

## Implementation Notes

- `weather.operations.nightly_retrain run` now defaults to
  `--fail-on-daily-learning-blocker`, with
  `--no-fail-on-daily-learning-blocker` available for manual override.
- `nightly_run_sla_status` classifies missed runs after the 03:30 local
  schedule plus a two-hour grace window, missing scheduled-task registration,
  latest run errors, and fresh blocked runs.
- `weather.operations.nightly_retrain status` writes
  `data/backtest/nightly_retrain_sla_status.json` and
  `data/backtest/nightly_retrain_sla_status_report.md`.
- `nightly_retrain_report.md` now includes the nightly SLA state and a
  Daily-Learning Blockers table with the P0 signal and action.
- The Operations dashboard shows the nightly task registration, next run,
  status freshness, daily-learning blocker count, and first P0 gate.
- `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md` documents registration and the
  post-registration smoke checks.

## Verification

- Registered Windows task `WeatherNightlyRetrainValidatePromote`; action is
  `weather.operations.nightly_retrain run --fail-on-daily-learning-blocker`;
  next run is `2026-06-18 03:30` local time.
- Live smoke wrote `data/backtest/nightly_retrain_status.json` with status
  `blocked`, one executed step (`daily_learning`), `promotion.verdict=not_run`,
  and reason `daily_learning_blocked`.
- Live SLA status is `BLOCKED`, fresh for the latest scheduled window, with
  first P0 gate `Data-layer audit failed.` and zero missed-run alerts.
- Operations dashboard helper reports `Task Registered=True`, `Fresh=True`,
  `Daily Learning=BLOCKED`, `Blockers=3`, and
  `P0 Gate=Data-layer audit failed.`
- `python -m pytest -q tests\operations\test_nightly_retrain.py tests\operations\test_runtime_utilities.py tests\operations\test_schema_registry.py`
  passes with `16 passed`.
