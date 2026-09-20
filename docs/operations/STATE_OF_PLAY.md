# State of play

**Last updated: 2026-09-20 America/Toronto (after the first adoption night since 09-13).**
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
| Production source | `master` = `dde26c664` (2026-09-20 00:49): the first adoptions since 2026-09-13 - the memory-guard fix, trough-based disk headroom in `status.ps1`, projection-tiering headroom sizing, and the long-CSV switch. About 400 commits still sit off master; 41 enabled scheduled tasks execute from linked worktrees, not this checkout (see OPERATIONS_DESIGN "What actually executes"). |
| Disk | 2026-09-19: duplicate Git LFS model pickles in 152 linked worktrees were replaced by pointers under a dated owner waiver (36.9 -> 89.2 GiB free). `write_order_books_long_csv=false` has been LIVE since 2026-09-20 00:49:06 local; long CSVs for event days open at that moment stop there. Free space is a daily **sawtooth** whose low is ~04:50; judge headroom at the low. |
| Landing path | **Blocked by the pagefile, not by code.** `AutomaticManagedPagefile=True` and the pagefile shrank to 5.9 GB while the disk was full, so the commit limit is ~22 GB (15.7 GB RAM + pagefile; July recorded 63.7 GB). Every commit-percent gate divides by it: the host suite aborted in chunk 5 of 21 at 66.28% vs its 66% ceiling with ~8 GB RAM free (2026-09-20 00:56), exactly as on 09-13/14. **Owner action: set a fixed pagefile (16-32 GB); agents are not permitted to.** Also: master's `bounded_worktree_test_suite.ps1` cannot run on this host (PowerShell 5.1 `.Rows` bug); the fix is inside `codex/reliability-host-qual-20260919` (= PR 61 + audit fixes + fifth host-id fixture), whose chunks 1-4 passed. The merge tool and the lease refuse outside 00:30-09:00 regardless of verdict; pass `-RepoRoot` explicitly to ops scripts launched with `powershell -File`. |
| Memory guard | The kill path of `memory_commit_guard.ps1` was inert 2026-08-23 -> 2026-09-20 00:38 (`$pid` assigned to the constant `$PID`). Fixed on master: the guard now really terminates out-of-window pytest/scan trees. |
| Settlement | Ten dates were backfilled 12/12 on 2026-09-20 (09-01, 09-04..09-10, 09-13, 09-17), ~25 min each, labels file intact; 09-10..09-18 now all grade `complete`. **Still unsettled: 08-17, 08-28, 08-29, 08-30, 08-31**, plus 09-19 until the 09:30 chain runs. The alarm looks back only 14 days, so older holes vanish from the briefing unsettled. Repair is per date: `settlement_backfill_one.ps1 -TargetDate <d> -Refetch -RepoRoot <repo>`, never `chain_recovery_run.ps1` directly. The chain is single-shot and its 70% commit gate is measured against the ~22 GB live limit (see Landing path). |
| Capture | Healthy: three workers, no capture gap on 2026-09-19. Worker health does not prove settled, countable dates. |
| Armed recurring work | Capture/safety supervisors, 05:00 projection and 06:00 raw-tape tiering, configuration/economics refreshes, the maker paper roll, staleness/countability reports and the 09:30 Stage-A chain. **Nightly training and further archive uploads are DISABLED**; the data mirror is PAUSED since 2026-08-12; the taker track is PAUSED. A scheduled time is not completion. The deployed watchdog is newer than `master` (hash-pinned parameters master lacks): never re-register it from master. |
| Maker economics | Configured liquidity-reward pool ~2,800/day same-day, ~4,800/day with T+1/T+2 (31 of 31 sampled days), against the ~$16/day the July verdict used. First desk measurements, 2026-09-20 (item 330): **taker fee is 0 on 377,104 of 377,104 public trades, so treat maker rebates as zero - rewards are the whole thesis**; share-weighted maker markout +0.19 c/share at 5 minutes, -0.43 c to settlement (30 date clusters); modelled reward share from captured books is large because displayed qualifying competition is thin - too good to take at face value. Nothing here is confirmable without one paid reward epoch at minimum size (live; needs the owner, and a band cap of ~25 pUSD instead of 10). Study code: `codex/execution-tape-markout-20260919`, `codex/reward-share-estimate-20260919`. |
| Live record | An owner-attended International Stage 0/1 test ran 2026-09-06 from the portable PC on unmerged branch code: three 0.005 pUSD post-only orders, cancelled, zero fills. It is spent and grants nothing. The code that ran is not on master. |
| Maker candidate | [PR 55](https://github.com/michaelbooth1/weather/pull/55) (`codex/48h-maker-integration-20260912`) is roll-sensitive, conflicts with PR 61 and master, and still carries the five bad host fixtures. It needs a reconciled tip after the reliability stack lands, then its own suite. |
| Settlement source | The venue's declared resolution source moved from Weather Underground to weather.gov timeseries around 2026-08-23 (same stations; measured band agreement 921/921 before, 131/132 after). Master still hard-codes WU and no gate detects a source change. |
| Documentation | Restructured 2026-09-19 for agent use: conditional routing in `AGENTS.md`, `CLAUDE.md` entry point, findings digest, complete operations index, and audit checks for line budgets, index reachability, retired claims and this file's age. |

## Ordered non-live critical path

1. **Owner: fix the pagefile** (Landing path row). Then qualify `codex/reliability-host-qual-20260919`
   with its own runner and adopt it inside 01:00-04:00.
2. Backfill the five remaining settlement dates, one admitted date at a time; keep 04:45-06:45 lease-free.
3. Maker studies are run (item 330). The next informative step is one paid reward epoch at minimum
   size - an owner decision. Freeze `R` from it before any further markout read.
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
