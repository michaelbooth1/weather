# State of play

**Last updated: 2026-09-19 America/Toronto (after the 2026-09-18 full audit; adoption night pending).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. Capped at about 90 lines.** This file owns the current decision and
> current truth. Numbered items and retained receipts own evidence. `status.ps1` flags this file
> when its declared date is more than 3 days old; rewrite or re-attest it then, whatever else stalled.

**Objectives, in order:** (1) protect capture and settlement evidence; (2) reliable unattended
execution, which today means *landing code on master again*; (3) the maker-economics decision in
[item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md), on the way back to an
owner-attended live test. **No market edge or profitable maker opportunity is proved.**

## Current authority

Owner, 2026-09-19: full implementation authority for getting the project back on track to live
testing; **no live trading is authorized**. Heavy work stays inside 00:30-09:00 under the shared lease.
Geographic eligibility is recorded as resolved by owner statement (the 2026-09-06 Ontario geoblock
readings were a file-access tunnel to the owner's home PC; the execution PC is physically eligible
and never moves; the tunnel must be down during any live session) — see
[the live pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md) and item 67.

## Current truth

| Area | Verified state / remaining limit |
| --- | --- |
| Production source | `master` = `3bdba3d15` (2026-09-13). Nothing has merged since. About 400 commits sit off master; 41 enabled scheduled tasks execute from linked worktrees, not this checkout (see OPERATIONS_DESIGN "What actually executes"). |
| Disk | 2026-09-19: duplicate Git LFS model pickles in 152 linked worktrees were replaced by pointers under a dated owner waiver; free space went 36.9 -> 89.2 GiB. Free space is a daily **sawtooth** whose low is ~04:50; judge headroom at the low, never at the evening reading. `write_order_books_long_csv=false` is approved and on a branch, not live. |
| Landing path | The 50 GiB suite floor is no longer the blocker. Pushed and awaiting tonight's window: three audit-fix branches (`claude/audit-rollfree-fixes-20260919`, `claude/audit-python-fixes-20260919`, `claude/activate-long-csv-off-20260919`, all roll-free by `roll_verdict.ps1` or by file type) and `codex/reliability-host-qual-20260919` = PR 61 + those fixes + the fifth host-id fixture. No complete host-suite PASS exists for any PR 61 tip yet. The merge tool refuses outside 00:30-09:00 regardless of verdict. |
| Memory guard | The kill path of `memory_commit_guard.ps1` has been inert since 2026-08-23 (`$pid` assigned to the constant `$PID`). Fix is on the roll-free branch; once merged the guard really terminates out-of-window pytest/scan trees. |
| Settlement | 15 dates unsettled: 08-17, 08-28..09-01, 09-04..09-10, 09-13, 09-17. 09-16 and 09-18 are settled. The alarm looks back only 14 days, so older holes vanish from the briefing unsettled. Repair is per date: `settlement_backfill_one.ps1 -TargetDate <d> -Refetch`, 35-40 min each, never `chain_recovery_run.ps1` directly. The chain is single-shot and its 70% commit gate is measured against a live limit of about 22 GB. |
| Capture | Healthy: three workers, no capture gap on 2026-09-19. Worker health does not prove settled, countable dates. |
| Armed recurring work | Capture/safety supervisors, 05:00 projection and 06:00 raw-tape tiering, configuration/economics refreshes, the maker paper roll, staleness/countability reports and the 09:30 Stage-A chain. **Nightly training and further archive uploads are DISABLED**; the data mirror is PAUSED since 2026-08-12; the taker track is PAUSED. A scheduled time is not completion. The deployed watchdog is newer than `master` (hash-pinned parameters master lacks): never re-register it from master. |
| Maker economics | The configured liquidity-reward pool is ~2,800/day same-day and ~4,800/day including T+1/T+2 (31 of 31 sampled days since 2026-08-15), against the ~$16/day the July verdict used. Pool is not income: our Q-score share, maker markout and whether taker fees (hence rebates) are non-zero are unmeasured. The 10 pUSD band cap makes every two-sided 20-share quote reward-ineligible. Two studies are authored and unexecuted: `codex/execution-tape-markout-20260919` (pre-registered) and `codex/reward-share-estimate-20260919`. |
| Live record | An owner-attended International Stage 0/1 test ran 2026-09-06 from the portable PC on unmerged branch code: three 0.005 pUSD post-only orders, cancelled, zero fills. It is spent and grants nothing. The code that ran is not on master. |
| Maker candidate | [PR 55](https://github.com/michaelbooth1/weather/pull/55) (`codex/48h-maker-integration-20260912`) is roll-sensitive, conflicts with PR 61 and master, and still carries the five bad host fixtures. It needs a reconciled tip after the reliability stack lands, then its own suite. |
| Settlement source | The venue's declared resolution source moved from Weather Underground to weather.gov timeseries around 2026-08-23 (same stations; measured band agreement 921/921 before, 131/132 after). Master still hard-codes WU and no gate detects a source change. |
| Documentation | Restructured 2026-09-19 for agent use: conditional routing in `AGENTS.md`, `CLAUDE.md` entry point, findings digest, complete operations index, and audit checks for line budgets, index reachability, retired claims and this file's age. |

## Ordered non-live critical path

1. Adopt the three audit-fix branches, then qualify and adopt `codex/reliability-host-qual-20260919`
   (suite from master's `bounded_worktree_test_suite.ps1`; merge inside 01:00-04:00).
2. Backfill settlement newest-first, one admitted date at a time; keep 04:45-06:45 lease-free.
3. Run the two maker studies on bounded samples; record results in item 330 and the digest,
   whatever their sign. Verify the taker-fee question before quoting any rebate figure.
4. Reconcile PR 55 onto the new master and qualify it.
5. Owner decisions in item 330: hurdle H and stop rule, band cap versus reward minimums, dedicated
   wallet. Then, and only on explicit owner instruction, a fresh Stage 0/1 followed by Stage 2.
6. Redeploy the hash-pinned watchdog so the briefing uses the trough-based disk arithmetic.

## Standing decisions

- International Polymarket only; no paid weather sources; no new model-alpha work for now.
- Streak contiguity is a diagnostic, not an objective. Backups are deprioritized by the owner.
- Capture-host heavy work is serial, admitted and time-gated. Pushing a branch never rolls capture.
- Create worktrees with `GIT_LFS_SKIP_SMUDGE=1`; pass `--basetemp` to every pytest run and delete it.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay,
  release binding and evidence retention remain mandatory.

## Update this file when

Rewrite after an owner decision, an actual source adoption, a measured storage or settlement outcome,
an economic-feasibility result, or when `status.ps1` flags its age.
