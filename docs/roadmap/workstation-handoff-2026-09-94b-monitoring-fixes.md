# Workstation handoff 2026-09-94b — monitoring fixes from the 2026-09-24 host audit

Written 2026-09-24 by the production agent. Serves open question **Q-11** and host-audit findings 3, 9 and 10
(`docs/roadmap/audits/host-and-model-audit-2026-09-24.md`). The failures that went unnoticed this week: the RE-0 reward
logger was dead for two days; `daily_learning` and the model-vs-market scoreboard have been stale since 2026-08-13 while
STALENESS_SWEEP marked them CRITICAL; `status.ps1` kept flagging a merge marker hours after an owner-approved retirement.

## 1. Build (branch `codex/monitoring-fixes-20260924` from `origin/master`; `.ps1` only where possible)

1. **Sweep criticals become flags:** `scripts/ops/status.ps1` imports STALENESS_SWEEP CRITICAL rows as flags that change the
   verdict (exit 2), not warnings.
2. **Reward-capture freshness:** a row in `scripts/ops/staleness_sweep.ps1` for the newest reward-record capture (the 88a
   capture's output once registered; until then report "no producer registered" as CRITICAL, never silent).
3. **Retirement receipts:** `status.ps1`'s quiet-merge "rollback recovery UNPROVEN" check honours a later retirement receipt in
   `data/alerts/quiet_window_merge_reconciliations/` (owner-approved or agent-retire per the fail-forward recovery table) and
   clears once one exists for the same marker hash.
4. **Watchdog log rotation:** bounded, append-time rotation for `data/alerts/host_health_alerts.jsonl` in
   `scripts/ops/health_watchdog.ps1` (non-deleting: rotate to a dated file; never reopen a large file in place — the
   2026-08-09 log-rotation outage).

## 2. Tests and boundaries

Tests with synthetic status/sweep/marker files for each change, run through `scripts/ops/workstation_heavy.ps1` with a short
`--basetemp`. State which files are roll-free (expected: all `.ps1`); the production agent takes the roll verdict and lands
them. No `.env`, no production writes, no task registration. Report:
`docs/roadmap/agent-report-2026-09-94b-monitoring-fixes.md` (verdict first, what each check now catches, the tip). Push is
authorized.
