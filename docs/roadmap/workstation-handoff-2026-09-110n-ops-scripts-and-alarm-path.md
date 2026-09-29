# Workstation handoff 2026-09-110n — ops scripts: alarm path, retired tasks, Stage-A taker decoupling

Written 2026-09-26 by the production agent from the [repo-health audit](audits/repo-health-audit-2026-09-26/README.md)
dimensions D2 and D6. All changes are PowerShell/docs/tests (roll-free), but several scripts are scheduled on production,
so the report must give exact re-registration steps where an action is hash-pinned. Base: `origin/master` after the
2026-09-27 landing (or the integration branch until then). Branch `codex/ops-alarm-path-20260926`.

## Build

1. **Bring the deployed watchdog onto master** (D6-01): `WeatherHostHealthWatchdog` runs tag
   `deployed/health-watchdog-aa99048` (`dcc3ebc97`), not on master. Merge its content into master's scripts and extend
   `register_health_watchdog.ps1` so it can express the same hash pins; master must never be able to downgrade the alarm.
2. **Fix the alarm defects** (D6-03): `health_watchdog.ps1:139` regex must match the settlement-hole flag text emitted at
   `status.ps1:1866` (add a test that pins both sides together); fix `status.ps1:1613-1616` `-f`/`+` precedence (literal `{0}`).
3. **Stage-A without the retired taker** (D2-01): pass the existing `--skip-taker-*` flags in `daily_refresh_contract.ps1`
   (like `--paper-maker-paused`) and update the two tests that pin the flag list; confirm the settled-day barrier treats the
   skipped steps as non-critical.
4. **Retired-bot false alerts** (D2-02): `nightly_health_checks.py` raises daily critical alerts for the retired paper maker
   and taker and suggests `daily_roll start --force`; honour the retired state (state roll classification; it is Python).
5. **Registrars refuse retired tasks** (D2-03, D6-05): taker, paper maker, clob enrichment and model-market disagreement
   registrars require `-AcknowledgeRetired` before `Register-ScheduledTask -Force`; add them to `$expDisabled` where missing.
6. **Operator-as-parameter check over all 76 scripts** including the `-f`/`+` precedence case; run it in
   `windows-qualification.yml` (D6-04). Extend the hard-coded-path check (`C:\Users\micha`, `WeatherOneShotPush` action,
   user name) from `register_*.ps1` to all of `scripts/ops` (D6-06, ps-ops-9).
7. **Tracked scheduled-task inventory** (D6-07/08): one data file of task names, owners, state (active / retired / one-shot)
   and registrar, tested against the registrars, `status.ps1` classification lists and the operations docs; regenerate
   OPERATING_REFERENCE window text so it no longer describes MM quoting or the taker.

## Boundaries and deliverables

No Scheduler changes, credentials or production data on the workstation; fixtures and parse-only tests. Push and a draft PR are
authorized. Report `docs/roadmap/agent-report-2026-09-110n-ops-alarm-path.md`, verdict first, roll classification per file, and
the exact production re-registration commands (production runs them after owner-ops review).
