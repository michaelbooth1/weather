# 199. Daily Learning Rollup Stale-Lock Recovery [COMPLETE 2026-06-21 - STALE LOCKS AND STALE ROLLUPS FAIL CLOSED]

Goal: make the compact daily learning and progress artifacts reliably reflect
the latest completed granular reports, or explicitly fail closed when stale
locks prevent the rollup from finishing.

Source: the June 21 log audit found current granular artifacts for hourly
performance, 10-minute performance, promotion refresh, active variant shadow,
and progress audit, while `daily_learning.json` and `daily_progress_latest.json`
still reflected the June 20 rollup. `data/backtest/daily_refresh.lock` pointed
to PID 37256, but that process was not running, and
`long_job_guard_status.json` still reported the job as active.

Why this matters: the model-improvement loop depends on the compact daily
learning artifact to decide what should feed retraining and what blocks
promotion claims. If the rollup is stale while granular reports are current, the
operator can miss the latest weak slots, regression slices, or blocker changes.

## Design

1. Add stale-lock detection for `daily_refresh.lock` and long-job guard status
   before starting or resuming daily refresh.
2. Record a rollup freshness status comparing `daily_learning`,
   `daily_progress_latest`, and each required granular artifact timestamp.
3. Fail the daily learning/reporting gate when granular artifacts are newer than
   the compact rollup by more than one refresh run.
4. Emit a clear repair command that removes only verified stale locks and then
   resumes from the first incomplete rollup step.
5. Add tests for dead-PID locks, active-PID locks, and current granular reports
   paired with stale daily rollups.

- [x] Add dead-PID stale-lock detection for daily refresh and long-job guard.
- [x] Add daily rollup freshness fields to `daily_refresh_status.json`.
- [x] Block `daily_learning` status when required granular reports are newer
  than the compact learning artifact.
- [x] Add a safe resume/repair command to the daily learning report.
- [x] Cover the June 21 stale-lock pattern with tests.

Acceptance: a stale daily refresh lock cannot leave `daily_learning` and
`daily_progress_latest` silently stale; the next run either refreshes the compact
rollups or emits an actionable failed freshness gate.

Completion note 2026-06-21: `daily_refresh` now removes only verified dead-PID
daily refresh locks, preserves active/unknown-owner locks, records lock preflight
state, and adds `summary.rollup_freshness` to `daily_refresh_status.json`.
Stale compact rollups make the run `critical` and surface a
`repair-stale-locks --run-after-repair --resume-from-step daily_learning`
command. `daily_learning` now turns a blocked rollup freshness gate into a P0
learning blocker and renders the repair command. Focused tests cover dead-PID
lock recovery, active-PID preservation, stale long-job status clearing, stale
rollup status gating, and stale compact rollup learning blockers.
