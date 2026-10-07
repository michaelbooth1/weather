# Agent report 2026-09-110v Part 5 — thin ensure entry

**Verdict: PASS on fixtures; host task adoption remains separate.**
`weather.operations.thin_ensure --ensure --loop snapshot|clob` avoids model,
NumPy, pandas and scikit-learn imports when a current healthy worker is proved.
Start/restart and ambiguous cases delegate to the unchanged loop owner.

Branch `codex/thin-ensure-entry-20260927`; authorized integration base
`e3bc4dc88a785e989258ac9e24b286879568d8d1`.
Mission: [110v handoff](workstation-handoff-2026-09-110v-efficiency-fixes.md).

## Scope and verification

The fast path requires a scoped runtime identity matching current source,
fresh heartbeat, live Python PID, matching writer lock, no pause/errors, and
for CLOB a matching process inventory without orphans, automatic target-date
mode, isolated enrichment and healthy book/token discovery. Any uncertainty
imports the old entrypoint and reruns its entire ensure policy. The probe
releases the shared supervisor lock before delegation. Recovery budgets,
debounce, managed stop proofs, launch arguments and exit codes remain owned
by existing routines. Observation-trigger supervision is unchanged.

Both registrar actions now use the thin module; principal/cadence/settings
remain unchanged. No task was registered, started or stopped.

**262 tests and 29 subtests passed** through workstation admission, including
all seven repo-wide audits in the focused run. Tests cover healthy import
avoidance, dead/stale/unknown/changed identity, writer lock failure, pause,
errors, orphan inventory, target-date mismatch, blank discovery, exact
fallback arguments, lock release, nonzero blocked exit, canonical path wiring,
and registrar S4U/Limited preservation. Existing supervisor, CLOB and
collection robustness suites passed. Both PowerShell scripts parsed cleanly;
repo-wide compileall passed.

## Exact later adoption commands

Run only after production authorizes scheduler adoption, from its intended
checkout, preserving any deliberate existing parameter overrides:

```powershell
.\scripts\ops\register_snapshot_supervisor.ps1 -RepoRoot (Get-Location).Path -TaskName WeatherSnapshotLoopSupervisor -EnsureEveryMinutes 2
.\scripts\ops\register_clob_supervisor.ps1 -RepoRoot (Get-Location).Path -TaskName WeatherClobBookLoopSupervisor -EnsureEveryMinutes 1 -Market all -IntervalSeconds 60 -FastIntervalSeconds 15
Get-ScheduledTask -TaskName WeatherSnapshotLoopSupervisor,WeatherClobBookLoopSupervisor | Select-Object TaskName,Actions,Principal,Triggers,Settings
```

Inspect exact executable, working directory, thin-module arguments,
current-user S4U/Limited principal and unchanged triggers/settings. These
commands replace existing tasks; none were executed for this handback.

## Roll classification per file

The authoritative local roll verdict returned **UNDECIDABLE** because all
four production live closure files are absent. Intended classification:

| File | Classification |
| --- | --- |
| `src/weather/operations/thin_ensure.py` | New supervisor-only entry; roll-free for existing capture closures |
| `scripts/ops/register_snapshot_supervisor.ps1` | Roll-free registrar; adoption is separate |
| `scripts/ops/register_clob_supervisor.ps1` | Roll-free registrar; adoption is separate |
| `tests/operations/test_thin_ensure.py` | Test-only |
| Operations design, this report, correspondence index | Roll-free documentation |

Production must still run `roll_verdict.ps1`; no production closure
membership was inferred. No venue, credentials or production evidence used.
