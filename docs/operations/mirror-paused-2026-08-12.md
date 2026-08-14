# Off-host mirror paused — 2026-08-12

**Operator decision: keep the mirror stopped until the project has demonstrated enough economic
value to make maintaining it worthwhile.** The nightly `data\` mirror to the workstation is
intentionally stopped. Mirror age, a failed historical run, or restored host capacity does not
authorize a restart. This records what stopped, what it costs, what it frees, and the checks that
would be required after a new operator decision to restart it.

## What changed

| Task | Was | Now |
| --- | --- | ---: |
| `WeatherDataMirror` (daily 04:30) | Ready | **Disabled** |
| `WeatherMirrorRestoreVerify` (daily 07:00) | Ready | **Disabled** |
| `WeatherOneShotMirror` (spent one-shot) | Ready | **Disabled** |

Nothing was in flight when they were disabled: no `mirror.lock`, no `robocopy` process, no
mounted share. No script, config, credential or exclusion was changed, and **nothing on either
host was deleted.**

**The off-host copy is FROZEN at 2026-08-12 05:03**, the last run's completion. Everything
`data\` has written since then, and everything it writes from now on, exists **only on this
disk**.

## Why the last runs were failing anyway

The mirror was not healthy when it was stopped, which is worth knowing before reading its final
state as a good backup:

| | |
| --- | ---: |
| Last run | 2026-08-12 04:30 → 05:03, **33.8 min** |
| Tree | **569.4 GB**, 3,935,783 files, 75,659 dirs |
| Copied that run | 32.0 GB / 20,325 files |
| Result | **robocopy exit 11 — RETRY LIMIT EXCEEDED**, 2 files FAILED |
| Last restore-verify (07:00) | **ok=false**, 19 checked, 10 identical, **8 problems** |

So the frozen copy is **not proven restorable**. That is not a new regression caused by the
pause — it is the state the pause froze.

## What this costs

- **`data\` has no off-host copy of anything written after 2026-08-12 05:03.** With no tape
  backup since 2026-06-30 and roughly one unexpected power loss every three weeks on this host,
  that is the real exposure. It is accepted under the standing decision that **profitability
  outranks durability** — recorded here so it is a visible choice, not a discovered surprise.
- **The workstation's `data\` is now frozen, not merely lagging.**
  [DELEGATION_CONTRACT.md](DELEGATION_CONTRACT.md) already says the mirror is not evidence and
  lags; while paused it does not advance at all. A workstation mission needing live evidence
  must be handed that evidence as facts in its handoff — which was already the rule.

## What this frees

- **04:30–05:04 on this host.** A `/MIR` pass enumerates 3.9M files with `/MT:16`. It lands
  inside the 02:00–05:15 chain-recovery window, so the two were contending for the same disk
  every night.
- **The `/MIR` purge hazard is suspended.** The mirror lands *inside the workstation's git
  clone*, so `data\` there is the clone's own `data\`, and every nightly run purged anything the
  workstation wrote under it. While paused, the workstation can delete under `data\` to reclaim
  its own disk **without a source-side exclusion first** — which is the two-step rule in
  [workstation-disk-and-mirror-scope.md](workstation-disk-and-mirror-scope.md).
  **This reverses on restart:** the first run after re-enabling re-copies everything deleted
  there and purges everything added. Treat any workstation-side reclaim during the pause as
  temporary relief, not a permanent fix.

## Monitoring: paused must not look either broken or fine

`status.ps1` would otherwise have raised two FLAGS every morning forever — `mirror last run
FAILED (robocopy exit 11)` and `MIRROR RESTORE VERIFY FAILED: 8 problem file(s)` — for a job
that is off on purpose. A monitor that flags a deliberate decision daily trains us to ignore it.

The suppression is deliberately **not** a marker file. `status.ps1` reads the **task state**:

```powershell
$mirrorPaused = ([string](Get-ScheduledTask -TaskName "WeatherDataMirror").State -eq "Disabled")
```

so re-enabling the task restores full alerting automatically and the suppression cannot outlive
the pause. What replaces the flags is one standing WARN carrying the **age of the frozen copy**:

```
OFF-HOST  : mirror PAUSED by operator, frozen 14.3h ago
  - mirror PAUSED by operator 2026-08-12 - the off-host copy of data\ is FROZEN at
    2026-08-12 05:03 (14.3h old and ageing). Everything written since exists ONLY on this
    disk. Re-enable WeatherDataMirror to resume
  - the FROZEN off-host copy is not proven restorable - the last restore-verify (before the
    pause) found 8 problem file(s)
```

The three task names are in `$expDisabled` so they do not each also report "unexpectedly
DISABLED" — one voice for the pause, not four.

## Resume gate

The operator reconfirmed this pause on 2026-08-14. Do not re-enable or manually run any mirror
task until both conditions are true:

1. The project has demonstrated enough economic value to justify the mirror's operational and
   storage cost.
2. The operator makes a new explicit decision to resume it.

The standing age warning is exposure disclosure, not a remediation trigger. Before a future
restart, audit the scheduled-task principal and credential-vault access, inspect both trees for
`/MIR` purge divergence, and require a fresh restore-verification result. The frozen copy remains
neither current nor proven restorable while this gate is closed.

## Restarting the mirror after the gate opens

Re-enable **`WeatherDataMirror`** and **`WeatherMirrorRestoreVerify`**. Nothing else is needed:
the script, the `weathersync` credential, and all three exclusions (`*.claim`,
`backtest\replay_cache`, `taker_runs`) are untouched. `WeatherOneShotMirror` is a spent one-shot
and only exists to kick the daily task by hand; re-enable it only if that is wanted.

Two things to expect on the first run back:

1. **It will be long.** It has to reconcile every day of divergence at once, not one night's
   32 GB.
2. **It will purge the workstation.** Anything written under the workstation's `data\` during
   the pause is deleted by `/MIR` on the first pass. Check before re-enabling.

`status.ps1` returns to real mirror flags the moment the task is Ready — no code change needed.

## Update this file when

The economic-value gate is met, the operator changes the pause decision, or the mirror is
restarted.
