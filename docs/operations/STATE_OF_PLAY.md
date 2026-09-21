# State of play

**Last updated: 2026-09-21 America/Toronto (the reliability stack qualified on the host and merged; workstation missions 79a and 80a handed back).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. Capped at about 90 lines.** This file owns the current decision and
> current truth. Numbered items and retained receipts own evidence. `status.ps1` flags this file
> when its declared date is more than 3 days old; rewrite or re-attest it then, whatever else stalled.

**Objectives, in order:** (1) protect capture and settlement evidence; (2) reliable unattended
execution; (3) the maker-economics decision in
[item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md), on the way back to an
owner-attended live test. **No market edge or profitable maker opportunity is proved.**

## Current authority

Owner, 2026-09-19: full implementation authority for getting the project back on track to live
testing; **no live trading is authorized**. Heavy work stays inside 00:30-09:00 under the shared lease.
Geographic eligibility is recorded as resolved by owner statement (the 2026-09-06 Ontario geoblock
readings were a file-access tunnel to the owner's home PC; the execution PC is physically eligible
and never moves; the tunnel must be down during any live session) — see
[the live pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md) and item 67.

Owner, 2026-09-21: **model work is unpaused**, and shortening the path to a live test is a priority.
Both first workstation missions were handed back and verified on 2026-09-21: `2026-09-79a` (what the
market knows that we do not — complete, descriptive; EF §10h) and `2026-09-80a` (place-and-hold Stage 2
build — PARTIAL / NO-GO, stopped correctly on two errors in its handoff; EF §10i). Successors issued:
`2026-09-81a` (pre-register and read two zero-parameter morning guidance candidates) and `2026-09-80b`
(finish the inert Stage 2 build with the corrected rules). None grants live authority.

## Current truth

| Area | Verified state / remaining limit |
| --- | --- |
| Production source | Local `master` = `e28530af6` (2026-09-21 02:31): the reliability stack (`codex/reliability-host-qual-20260919` = PR 61 + audit fixes + host fixtures) merged through the guarded tool with capture and execution-tape recovery proved. **Published by the owner on 2026-09-21 (`origin/master` = `e28530af6`, a fast-forward)** after `WeatherOneShotPush`, an interactive-logon task, did not run and an agent push was refused by the permission layer. **The merge tool's marker is still `documented_unpublished` and blocks every further guarded merge until it is reconciled through the reviewed path** (never delete it; boot recovery preserves this merge across a restart - its conditions were checked against the marker on 2026-09-21). 41 enabled scheduled tasks still execute from linked worktrees, not this checkout (see OPERATIONS_DESIGN "What actually executes"). |
| Disk | 2026-09-19: duplicate Git LFS model pickles in 152 linked worktrees were replaced by pointers under a dated owner waiver (36.9 -> 89.2 GiB free). `write_order_books_long_csv=false` has been LIVE since 2026-09-20 00:49:06 local; long CSVs for event days open at that moment stop there. Free space is a daily **sawtooth** whose low is ~04:50; judge headroom at the low. |
| Landing path | **Open again.** The owner set a fixed 16-32 GB pagefile on 2026-09-20 (commit limit 22.0 -> 32.5 GB; never leave it system-managed on this host - if `commit_total_mb` reads ~22,000 it has reverted). On 2026-09-21 the bounded host suite passed **21 of 21 chunks** for the first time (peak commit ~41% against the 66% ceiling; ~54 min, of which ~40 min is the merge-tool test chunk). Two test-only fixes were needed: lease-acquisition tests now skip when an outer job owns the host-global mutex (the suite runner holds it for its whole run; run directly they pass, 39/0), and one audit-record line carried the paid provider's literal API host. Known defect: `quiet_window_merge.ps1` reads execution-tape status once with no retry, so a read that races the 10 s heartbeat rewrite aborts the merge (it did once; the unchanged retry passed). **Windows Update:** KB5129195 is staged and a restart is pending; active hours were moved to 23:00-17:00 so an automatic restart can only happen 17:00-23:00. **Owner action: one deliberate restart before 17:00 on 2026-09-21** (best 08:50-09:20), then restart the two public-read node loops. The merge tool and the lease refuse outside 00:30-09:00; pass `-RepoRoot` explicitly to ops scripts launched with `powershell -File`. |
| Memory guard | The kill path of `memory_commit_guard.ps1` was inert 2026-08-23 -> 2026-09-20 00:38 (`$pid` assigned to the constant `$PID`). Fixed on master: the guard now really terminates out-of-window pytest/scan trees. |
| Settlement | Fifteen dates have been backfilled 12/12 from the authoritative daily summary: ten on 2026-09-20 and **08-17, 08-28, 08-29, 08-30, 08-31 on 2026-09-21** (~27 min each, labels file intact). **No known unsettled date remains** apart from the current day until the 09:30 chain runs. The alarm looks back only 14 days, so older holes vanish from the briefing unsettled. Repair is per date: `settlement_backfill_one.ps1 -TargetDate <d> -Refetch -RepoRoot <repo>`, never `chain_recovery_run.ps1` directly. The chain is single-shot; its 70% commit gate is measured against the live commit limit (see Landing path). |
| Capture | Healthy: three workers, no capture gap on 2026-09-19. Worker health does not prove settled, countable dates. |
| Armed recurring work | Capture/safety supervisors, 05:00 projection and 06:00 raw-tape tiering, configuration/economics refreshes, the maker paper roll, staleness/countability reports and the 09:30 Stage-A chain. **Nightly training and further archive uploads are DISABLED**; the data mirror is PAUSED since 2026-08-12; the taker track is PAUSED. A scheduled time is not completion. The deployed watchdog is newer than `master` (hash-pinned parameters master lacks): never re-register it from master. |
| Maker economics | Configured liquidity-reward pool ~2,800/day same-day, ~4,800/day with T+1/T+2 (31 of 31 sampled days), against the ~$16/day the July verdict used. First desk measurements, 2026-09-20 (item 330): **taker fee is 0 on 377,104 of 377,104 public trades, so treat maker rebates as zero - rewards are the whole thesis**; share-weighted maker markout +0.19 c/share at 5 minutes, -0.43 c to settlement (30 date clusters); modelled reward share from captured books is large because displayed qualifying competition is thin - too good to take at face value. Nothing here is confirmable without one paid reward epoch at minimum size (live; needs the owner, and a band cap of ~25 pUSD instead of 10). Public reads on 2026-09-20 cut the estimate: same-day bands flip from a 20- to a 100-share minimum during the morning, and next-day 20-share bands are contested (modelled share 0.01-0.10 in ten of twelve cities, 0.18-0.34 only in Los Angeles = roughly 0.5-6 per band per day). **The first paid reward epoch is designed and frozen ([RE-1 pre-registration](../research/liquidity-reward-epoch-preregistration-2026-09-20.md)); RE-1M - the owner places two orders by hand - comes first and needs only owner decisions** (target 2026-09-24, next-day Los Angeles band). Both study tools are on master. |
| Live record | An owner-attended International Stage 0/1 test ran 2026-09-06 from the portable PC on unmerged branch code: three 0.005 pUSD post-only orders, cancelled, zero fills. It is spent and grants nothing. The code that ran is not on master. |
| Maker candidate | PR 55 is reconciled onto the reliability lineage as `codex/maker-reconcile-20260920` @ `0fc25f40b` (roll-sensitive, not yet host-qualified; now carries the two host-suite test fixes). Next: merge the new master into it and run its own suite. Mission 80a delivered a pure reward-aware pricer and an inert hash-bound Stage 2 envelope on `codex/stage2-hold-build-20260921`, and no execution path (EF §10i). Mission `2026-09-80b` finishes it under corrected rules: explicit cancel primary with the 10-15 s dead-man as backstop; a PROPOSED RE-1A addendum counting cumulative two-sided minutes per UTC reward day (120-minute sessions, four a day, three reward days); and default dispositions for the four 09-06 relaxations - fresh dedicated wallet, one typed confirmation per sealed session, receipt age stays unlimited, fee check unchanged. **All of these await the owner's ratification**; the build stays inert until two dated grants exist. |
| Forecast lead | `-09-79a` (EF §10h): the gap to the market is already 1.44-1.48x in the morning, and unfitted NBM-percentile band probabilities beat the served model there by ~0.012-0.015 Brier in both strata while still trailing the market at 1.15-1.22x. It is a lead on the guidance-present rows only (24.6-38.3% fill, none after 10:00). Branch `codex/missing-information-checks-20260921` is ROLL-FREE and unmerged. Mission `2026-09-81a` pre-registers the candidates before any score; nothing is served or trained. |
| Settlement source | The venue's declared resolution source moved from Weather Underground to weather.gov timeseries around 2026-08-23 (same stations; measured band agreement 921/921 before, 131/132 after). Master still hard-codes WU and no gate detects a source change. |
| Documentation | Restructured 2026-09-19 for agent use: conditional routing in `AGENTS.md`, `CLAUDE.md` entry point, findings digest, complete operations index, and audit checks for line budgets, index reachability, retired claims and this file's age. |

## Ordered non-live critical path

1. **Owner today:** restart the host before 17:00 (Landing path row). Next quiet window: reconcile
   the merge marker (Production source row), then land the waiting roll-free branches.
2. **Owner decisions for RE-1M** (item 330, RE-1 pre-registration): authorize or not, date, wallet,
   hurdle `H` and the stop date. It is the fastest live evidence and needs no code. Freeze `R` from
   it before any further markout read.
3. Merge the new master into `codex/maker-reconcile-20260920` and qualify it on the host; adopt only
   after the owner disposes of the four control relaxations.
4. Workstation: mission `2026-09-80b` (finish the inert place-and-hold Stage 2 build), then two host
   qualification nights, an owner-attended Stage 0/1 re-run on landed code, and a dated owner Stage 2
   authorization. **Owner: ratify or change the 80b defaults** (Maker candidate row). Earliest
   repository-run live session is still about 2026-10-01 (estimate; 80a used one night, not five days).
5. Workstation: mission `2026-09-81a` (Forecast lead row). Verify both handbacks per the delegation
   contract; land `codex/missing-information-checks-20260921` (roll-free) once master is published.
6. Redeploy the hash-pinned watchdog so the briefing uses the trough-based disk arithmetic; give the
   merge tool's execution-tape pre-check a bounded retry.

## Standing decisions

- International Polymarket only; no paid weather sources. Model work is unpaused (owner, 2026-09-21): measurement first, and any candidate needs a pre-registration before it is scored.
- Streak contiguity is a diagnostic, not an objective. Backups are deprioritized by the owner.
- Capture-host heavy work is serial, admitted and time-gated. Pushing a branch never rolls capture.
- Create worktrees with `GIT_LFS_SKIP_SMUDGE=1`; pass `--basetemp` to every pytest run and delete it.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay,
  release binding and evidence retention remain mandatory.

## Update this file when

Rewrite after an owner decision, an actual source adoption, a measured storage or settlement outcome,
an economic-feasibility result, or when `status.ps1` flags its age.
