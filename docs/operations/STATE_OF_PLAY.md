# State of play

**Last updated: 2026-09-21 America/Toronto (the reliability stack qualified on the host and merged; master published; workstation missions 79a, 80a, 80b, 81a, 82a, 83a, 83b, 83c, 83d, 84b and 84c handed back).**
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
testing; **no live trading is authorized except the one item below**. Heavy work stays inside 00:30-09:00 under the shared lease.
Owner, 2026-09-21: the first paid reward test (RE-1, pre-registered) is approved and moved up; it runs from the
workstation as an **attended script the owner starts personally**, worst case 20-30 dollars accepted, at most three
sessions, none after 2026-09-30 (mission `2026-09-84a`; the script must be confirmed by the owner in the workstation
session before it can sign). This is a one-off exception outside the sealed lane and changes nothing in it.
Geographic eligibility is recorded as resolved by owner statement (the 2026-09-06 Ontario geoblock
readings were a file-access tunnel to the owner's home PC; the execution PC is physically eligible
and never moves; the tunnel must be down during any live session) — see
[the live pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md) and item 67.

Owner, 2026-09-21: **model work is unpaused**, and shortening the path to a live test is a priority.
Five workstation missions were handed back and verified on 2026-09-21: `2026-09-79a` (what the
market knows that we do not — complete, descriptive; EF §10h), `2026-09-80a` (place-and-hold Stage 2
build — PARTIAL / NO-GO, stopped correctly on two errors in its handoff; EF §10i) `2026-09-81a` (NO-GO, EF §10j), `2026-09-82a` (the NBM parser reads the wrong period after 13Z; EF §10k) and
`2026-09-83a` (the versioned parser repair, PARTIAL; EF §10l). `2026-09-80b` then finished the inert Stage 2 build (PASS, full suite clean; Maker candidate row).
`2026-09-83c` stacked three integration branches (`-09-83b` built both parts, PARTIAL, EF §10l): layer 1
`codex/integrate-1-research-20260921` @ `c04200081` (the research stack), layer 2 `codex/integrate-2-parser-20260921`
@ `abd648c7c` and layer 3 `codex/integrate-3-reuse-20260921` @ `cee879c45`. After `2026-09-83d` bound the 82a trace
to parser version 1 (396 of 396 retained rows reproduce), all three pass the workstation full suite with zero failures
and are ready for host qualification. `2026-09-84b`/`84c` delivered the attended reward-test script, fit for a six-hour run (per-fact freshness budgets,
heartbeat daemon, SDK-model reply tests, owner-run `preflight` and `reconcile`; `codex/reward-test-attended-20260921`
@ `7e6e1709c`, PR 78, full suite clean, seeded 2%-failure six-hour rehearsal reached its end). 84c also disabled the
pinned SDK's silent API-key creation. **The owner's first real `preflight` runs (2026-09-22) found four defects on that
tip: no `-ExecutionPolicy Bypass` on the host-identity spawn, `python-dotenv` undeclared, Cloudflare 403 on every
plain-urllib public read (no `User-Agent`), and the accrual read paging the whole reward-market universe past the
50-page budget; `84d` (`7010a0b58`) fixes the first two, `84e` the last two. `live` needs a same-day PASS on the tip run.**
None grants live authority.

## Current truth

| Area | Verified state / remaining limit |
| --- | --- |
| Production source | Local `master` = `origin/master` = `29e161e7d` (2026-09-22 01:16). The reliability-stack marker (`documented_unpublished`, 2026-09-21) was retired at 00:47 by `scripts/ops/reconcile_ordinary_quiet_merge.ps1` after its five tests, a dry run and Git-proved publication (receipt `data/alerts/quiet_window_merge_reconciliations/ordinary-64d8f787…json`, history row `reconciled_published`). Four guarded merges then landed and were published by `WeatherOneShotPush` under an interactive logon: docs-night results `08f0fe8de`, the ordinary-merge reconciler `6cf037514`, the roll-verdict merge-tree fix `3ed12bacf` (a branch with several merge bases made `git` warn on stderr, which the Stop preference turned into an abort before any merge; the changed set is now the diff to the `merge-tree` result), and integration layer 1 `29e161e7d` (190 files, no importable source). No marker exists. 41 enabled scheduled tasks still execute from linked worktrees, not this checkout (see OPERATIONS_DESIGN "What actually executes"). |
| Disk | 2026-09-19: duplicate Git LFS model pickles in 152 linked worktrees were replaced by pointers under a dated owner waiver (36.9 -> 89.2 GiB free). `write_order_books_long_csv=false` has been LIVE since 2026-09-20 00:49:06 local; long CSVs for event days open at that moment stop there. Free space is a daily **sawtooth** whose low is ~04:50; judge headroom at the low. |
| Landing path | **Open again.** The owner set a fixed 16-32 GB pagefile on 2026-09-20 (commit limit 22.0 -> 32.5 GB; never leave it system-managed on this host - if `commit_total_mb` reads ~22,000 it has reverted). On 2026-09-21 the bounded host suite passed **21 of 21 chunks** for the first time (peak commit ~41% against the 66% ceiling; ~54 min, of which ~40 min is the merge-tool test chunk). Two test-only fixes were needed: lease-acquisition tests now skip when an outer job owns the host-global mutex (the suite runner holds it for its whole run; run directly they pass, 39/0), and one audit-record line carried the paid provider's literal API host. Known defect: `quiet_window_merge.ps1` reads execution-tape status once with no retry, so a read that races the 10 s heartbeat rewrite aborts the merge (it did once; the unchanged retry passed). **Windows Update:** KB5129195 is staged and a restart is pending; active hours were moved to 23:00-17:00 so an automatic restart can only happen 17:00-23:00. **Owner action: one deliberate restart before 17:00 on 2026-09-21** (best 08:50-09:20), then restart the two public-read node loops. The merge tool and the lease refuse outside 00:30-09:00; pass `-RepoRoot` explicitly to ops scripts launched with `powershell -File`. |
| Memory guard | The kill path of `memory_commit_guard.ps1` was inert 2026-08-23 -> 2026-09-20 00:38 (`$pid` assigned to the constant `$PID`). Fixed on master: the guard now really terminates out-of-window pytest/scan trees. |
| Settlement | Fifteen dates have been backfilled 12/12 from the authoritative daily summary: ten on 2026-09-20 and **08-17, 08-28, 08-29, 08-30, 08-31 on 2026-09-21** (~27 min each, labels file intact). **No known unsettled date remains** apart from the current day until the 09:30 chain runs. The alarm looks back only 14 days, so older holes vanish from the briefing unsettled. Repair is per date: `settlement_backfill_one.ps1 -TargetDate <d> -Refetch -RepoRoot <repo>`, never `chain_recovery_run.ps1` directly. The chain is single-shot; its 70% commit gate is measured against the live commit limit (see Landing path). |
| Capture | Healthy: three workers, no capture gap on 2026-09-19. Worker health does not prove settled, countable dates. |
| Armed recurring work | Capture/safety supervisors, 05:00 projection and 06:00 raw-tape tiering, configuration/economics refreshes, the maker paper roll, staleness/countability reports and the 09:30 Stage-A chain. **Nightly training and further archive uploads are DISABLED**; the data mirror is PAUSED since 2026-08-12; the taker track is PAUSED. A scheduled time is not completion. The deployed watchdog is newer than `master` (hash-pinned parameters master lacks): never re-register it from master. |
| Maker economics | Configured liquidity-reward pool ~2,800/day same-day, ~4,800/day with T+1/T+2 (31 of 31 sampled days), against the ~$16/day the July verdict used. First desk measurements, 2026-09-20 (item 330): **taker fee is 0 on 377,104 of 377,104 public trades, so treat maker rebates as zero - rewards are the whole thesis**; share-weighted maker markout +0.19 c/share at 5 minutes, -0.43 c to settlement (30 date clusters); modelled reward share from captured books is large because displayed qualifying competition is thin - too good to take at face value. Nothing here is confirmable without one paid reward epoch at minimum size (live; needs the owner, and a band cap of ~25 pUSD instead of 10). Public reads on 2026-09-20 cut the estimate: same-day bands flip from a 20- to a 100-share minimum during the morning, and next-day 20-share bands are contested (modelled share 0.01-0.10 in ten of twelve cities, 0.18-0.34 only in Los Angeles = roughly 0.5-6 per band per day). **The first paid reward epoch is designed and frozen ([RE-1 pre-registration](../research/liquidity-reward-epoch-preregistration-2026-09-20.md)); RE-1M - the owner places two orders by hand - comes first and needs only owner decisions** (target 2026-09-24, next-day Los Angeles band). Both study tools are on master. |
| Live record | An owner-attended International Stage 0/1 test ran 2026-09-06 from the portable PC on unmerged branch code: three 0.005 pUSD post-only orders, cancelled, zero fills. It is spent and grants nothing. The code that ran is not on master. |
| Maker candidate | PR 55 is reconciled onto the reliability lineage as `codex/maker-reconcile-20260920` @ `0fc25f40b` (roll-sensitive, not yet host-qualified; now carries the two host-suite test fixes). Mission 80a delivered a pure reward-aware pricer and an inert hash-bound Stage 2 envelope, and no execution path (EF §10i). **Mission `2026-09-80b` finished the inert build on `codex/stage2-hold-build-20260921` @ `88aa7e43a`, which contains the maker-reconcile branch, so production qualifies that one branch** (workstation full suite zero failures; trial merges with master and the three forecast branches are conflict-free; roll-sensitive, production verdict owed). It is built to the corrected rules: explicit cancel primary with the 10-15 s dead-man as backstop; a PROPOSED RE-1A addendum counting cumulative two-sided minutes per UTC reward day (120-minute sessions, four a day, three reward days); and default dispositions for the four 09-06 relaxations - fresh dedicated wallet, one typed confirmation per sealed session, receipt age stays unlimited, fee check unchanged. **All of these await the owner's ratification**; the build stays inert until two dated grants exist (owner draft: `docs/operations/stage2-hold-owner-authorization-draft.md` on that branch). Open owner question: a grant commit changes the bound Git tip, so the four attended Stage 0/1 predecessor runs must be repeated after it unless the owner approves granting before the first set. |
| Forecast lead | `-09-79a` (EF §10h): the gap to the market is already 1.44-1.48x in the morning, and unfitted NBM-percentile band probabilities beat the served model there by ~0.012-0.015 Brier in both strata while still trailing the market at 1.15-1.22x. It is a lead on the guidance-present rows only (24.6-38.3% fill, none after 10:00). Mission `2026-09-81a` (EF §10j, pre-registration frozen before scoring): on every morning row the gain halves to about -0.0067 Brier and fails the frozen minimum-effect rule; **NO-GO for a confirmation this season**, and none is possible at this effect size because 11 market clusters cap power near 40%. Most guidance is discarded as below the observed floor (fill 73% at 06:00, ~7% at 09:00). **`-09-82a` (EF §10k) found why: 13Z and 19Z NBM bulletins hold no maximum for the current local date, and the parser took their first value - tomorrow morning's minimum - so the floor rightly discarded it; confirmed live on production.** A live, promotion-blocked shadow variant consumes those columns (the served model does not), so mission `2026-09-83a` built a versioned repair with replay parity on `codex/nbm-target-fix-20260921` (PARTIAL, EF §10l; roll-sensitive, needs a quiet window). After 12Z the newest bulletin holding today's maximum is 07Z, so later guidance is old by construction. **Production downloads the ~35 MB national bulletin on almost every market pass (24.9 GB in 15 hours on 2026-09-21); `-09-83b` built the finished repair and fail-open reuse (unlanded); mission `2026-09-83c` stacked them as three integration branches (all three ready for host qualification after `-09-83d`), which production qualifies and lands one layer per quiet window.** No candidate is scored until dates exist that were captured after the fix. Branches `codex/missing-information-checks-20260921`, `codex/morning-guidance-candidate-20260921` and `codex/nbm-target-trace-20260921` are ROLL-FREE and unmerged. Nothing is served or trained. |
| Settlement source | The venue's declared resolution source moved from Weather Underground to weather.gov timeseries around 2026-08-23 (same stations; measured band agreement 921/921 before, 131/132 after). Master still hard-codes WU and no gate detects a source change. |
| Documentation | Restructured 2026-09-19 for agent use: conditional routing in `AGENTS.md`, `CLAUDE.md` entry point, findings digest, complete operations index, and audit checks for line budgets, index reachability, retired claims and this file's age. |

## Ordered non-live critical path

1. **RE-1 session 1 moved to 2026-09-23 (no session on 09-22: two code defects, see above).** Order: `84e` handed
   back and accepted -> production agent names the session tip -> owner makes a fresh worktree at that tip, tunnel down,
   runs `preflight`, and on PASS starts `live` by 13:59 Eastern; a `NO QUALIFYING BAND` line means retry every quarter
   hour, not a defect (bands flickered hour to hour on 09-22). `84a`-`85b` are accepted on their branches (85b's
   exact-amount payout rule is roll-sensitive to adopt). Verdict earliest D+3 (09-26 for a 09-23 session). Still the
   owner's: the account, hurdle `H` and the stop date (before earnings are read). Freeze `R` before any markout read.
2. `codex/stage2-hold-build-20260921` merges cleanly with the new master (local trial `dbf2f065f`, 2026-09-22) and is
   **ROLL-SENSITIVE** by the production tool (66 importable, 7 roll incl. `time.py`, `units.py` across all four
   closures): qualify on the host in a quiet window; adopt only after the owner disposes of the four control relaxations.
3. After that: an owner-attended Stage 0/1 re-run on landed code and a dated owner Stage 2 authorization. **Owner:
   ratify or change the 80b defaults** (Maker candidate row). Earliest repository-run live session about 2026-10-01.
4. NBM census done (EF §10k: 27,473 rows over 14 days, **every** 12Z/13Z/19Z pick is a 12Z minimum); layer 1 landed. Land
   layer 2 (`codex/integrate-2-parser-20260921` @ `abd648c7c`, ROLL-SENSITIVE: `feature_store`, `model_features`,
   `model_sources`, `nbm_probabilistic_tmax`, `schema_registry_data`) then 3, one per 01:00-04:00 window, host-qualified.
5. Redeploy the hash-pinned watchdog so the briefing uses the trough-based disk arithmetic; give the
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
