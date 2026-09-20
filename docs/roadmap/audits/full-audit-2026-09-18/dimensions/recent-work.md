# Audit dimension: Recent work - attempted versus delivered (git history)

Auditor key: `recent-work`. Date: 2026-09-18. Host: 16 GB production capture host, protected window.
Read-only. No project file was modified; this report is the only write.

## 1. Scope and method

Scope: what the last ~60 days of git history attempted, what reached production `master`, where the
work is looping, the state of branches / worktrees / merge queue, the automated drift commits, and
whether velocity is converging on the project's goal.

Method (whitelisted commands only, one at a time, all piped through `head`):
`git log` (paged, `--all`, `--merges --first-parent`, `--name-only`, `--shortstat`, path-limited),
`git shortlog -sn`, `git branch` (`--merged/--no-merged/--contains/--format`), `git worktree list`,
`git show --stat`, `git show <rev>:<path>`, `git diff --stat/--shortstat A...B`, non-recursive `ls`
of single directories. Read/Grep/Glob only under `docs/`, `scripts/`, `src/`. `data/` was not read
(my brief did not allow it); live-state figures (disk 21 GB, settlement hole 10/14, streak 2/14,
a1..a11 failed) are the lead auditor's and are labelled as such.

Classification of the last 300 master commits was done by hand from subject lines; treat the counts
as +/-5. Every structural claim below was traced to at least one concrete line or object.

Basis labels: `verified_in_code` (I read the lines/objects), `live_state` (I listed the live
filesystem/ref state), `doc_claimed` (a project doc says so), `inferred`.

## 2. Headline

Work has not stopped - 80 commits were written in the five days since the last merge - but
**delivery into production has**. `master` has not moved since 2026-09-13 04:09. In the last 30 days
**360 of 626 commits (58%) never reached master**, and the share is rising (W36 120 unmerged vs 50
merged; W37 157 vs 71; W38 65 vs 0). What did land was overwhelmingly storage, merge/qualification
machinery and live-pilot machinery; **zero** file-touches went to `src/weather/model`,
`src/weather/sources` or `src/weather/backtesting`, one each to `collection` and `calibration`.
Meanwhile small, product-critical fixes (capture hang detection, settlement retry, model identity)
have sat unmerged for 17-38 days, and the development process itself now occupies an estimated
~70-80 GiB of the production disk (199 linked worktrees, each with ~363 MiB of smudged LFS model
pickles) on a volume reported to be ~4 days from full.

## 3. Answers to the brief

### 3.1 Theme split of the last 300 master commits (2026-08-15 .. 2026-09-13)

| Theme | Commits | Share |
| --- | ---: | ---: |
| Merge commits | 65 | 21.7% |
| Automated drift commits | 11 | 3.7% |
| Archive / storage (code + archive status docs) | 64 | 21.3% |
| Qualification / integration / host-load / CI / reconciliation machinery | 63 | 21.0% |
| Live-pilot machinery (Stage 0/1, sealer, SDK overlay, credentials, portable host) | 53 | 17.7% |
| Status / monitor tooling (`status.ps1`, receipts) | 11 | 3.7% |
| Maker economics, non-live (incl. docs) | 7 | 2.3% |
| Capture / settlement data path | 4 | 1.3% |
| Generic docs / state / backlog | 22 | 7.3% |
| Model / forecast / sources / collection features | 0 | 0% |

Of the 224 non-merge, non-drift commits: product (maker + capture/settlement + model) = 11 (~5%);
live-pilot machinery = 53 (~24%); storage = 64 (~29%); process machinery + status = 74 (~33%);
docs = 22 (~10%).

Cross-check by file touches, last 30 days, non-merge (`git log --since=30.days --no-merges
--name-only`): `src/weather` 280 (of which `operations` 165, `market` 69, schema registries 34,
`reporting` 6, `collection` 1, `calibration` 1, `model` 0, `sources` 0), `tests/operations` 260,
`docs/operations` 247, `scripts/ops` 218, `docs/roadmap` 140, `tests/market` 63. Of the 69 `market`
touches, 47 are live-pilot files (`mm_live_pilot_cli.py` 12, `mm_live_lifecycle_probe.py` 5,
`mm_credential_import_cli.py` 5, ...). Most-edited file in the repo: `docs/operations/STATE_OF_PLAY.md`,
86 edits in 30 days.

Commit cadence on master by ISO week: W29 102, W30 89, W31 171, W32 291, W33 335, W34 107, W35 57,
W36 50, W37 71, **W38 0**. Total history is 1,454 commits since 2026-05-29; 1,160 (80%) are in the
last 60 days.

### 3.2 Loops

- **Merge-gate machinery auditing itself.** `docs/roadmap/items/item-329-...md:124-212` records five
  successive adversarial reviews of the integration-attempt scripts (2f911f6f -> af5e8f9bd ->
  e41d30232 -> 7bfdb6fd4 -> 08-21 deep audit), each finding new defects in the previous repair
  (a `-split` parsed as a parameter so "the full suite could never start"; a merge that committed
  before its recovery proof; ...). Marked COMPLETE 08-22, it failed again on 09-13
  (`item-329:3-35`, attempt namespace `overnight-20260913-complete-a9`, review rounds `b2`, `e5`,
  `g7`, `h8`), and on 09-14 a replacement ("split qualification v2") was designed and built:
  46 commits in ~10 hours, 143 files, +16,673 lines (`codex/split-qualification-20260914`),
  then a probe adapter and a "guarded first-landing installer" (PR 70) to land it
  (`codex/qualification-bootstrap-probe-20260915`: 161 files, +20,203). None of it is on master.
- **`quiet_window_merge.ps1`**: 142 lines at creation (156362b9c, 07-25) -> 4,093 lines / 215 KB
  today (+1,920 in ac1882f3e on 09-01, +1,167 in a4619c67a on 09-02). The PowerShell needed to merge
  one branch (quiet merge + integration_attempt_* + reconcile + suite + roll verdict) is ~540 KB;
  `settlement_backfill_one.ps1`, the tool that repairs the settlement hole, is 13 KB.
- **Attempt suffixes in live refs/worktrees**: `capacity-day-20260909-a1/-a2`,
  `capacity-night-20260909/-a2`, `archive-immediate-20260913-a1`, `archive-reserve-20260914-a1`,
  `archive-next50-20260914-a1`, `capacity-150gb-20260916-a2`, `capacity-150gb-20260917-a1`;
  lead-reported qualification attempts a1..a11 on 09-13/14 all FAILED.
- **Workstation mission letter chains**: `-09-100c -> 100e -> 100f -> 100g -> 100i` (WU outcome
  exporter: build, portable repair, request-scope repair, gap spec, publication repair, all on
  09-04); `-09-99c`, `-09-99f`; baseline reconciliation `-09-83a/84a/85a/96a` (no-go, prototype,
  harden, no-go).
- **Same-day fix chains merged one at a time to production**: 08-15 five consecutive
  "tolerate sparse X in strict mode" fixes to `status.ps1`, each with its own production merge
  (d1e99aa26, 08b36bca0, 42c38a85a, 450a61a4e, a013841da); 08-14 six "align X with snapshot
  cadence"; 08-25 sixteen bootstrap-qualification hardening commits in one day; 09-10 five commits
  on archive error classification/redaction.

### 3.3 Delivered versus attempted, last 30 days

Delivered to master (first-parent merges): integration-attempt recovery + overnight workflow
(08-22); Stage-1 live readiness stack, Codex host-load hook/tree budget, execution-tape false-backoff
fix (08-23); offline runner bootstrap (08-26); portable live execution host PRs #3-#5 (08-30/31);
baseline reconciliation (09-01..03); settlement-backfill quoting fix, workstation SSH admission
(09-04); maker governance / market identity / W3 feasibility diagnostics - the only maker-economics
code adopted (09-05); cache + cold-snapshot compression and the cold-archive bridge (09-07..10);
status docs (09-10, 09-13).

The one measured production outcome: **79,105,806,336 bytes reclaimed** by verified archive offload
(1,679 files, 85 batches) and **12,808,867,840 bytes** saved by lossless NTFS compression
(`item-325:10-13, 56-62`; `STATE_OF_PLAY.md:31-32`). Free space went 87.6 GB (09-11 08:57,
`item-325:82`) -> 67.6 GiB (09-13 02:16, `item-325:36`) -> 21 GB (09-18, lead): the gain was
consumed in about a week.

Attempted, not delivered (all unmerged today):

| Stack | Branch | Size vs master |
| --- | --- | --- |
| Reliability candidate (PR 61) | `codex/reliability-fixture-host-20260913` | 24 commits, 53 files, +5,777 |
| Maker cumulative candidate (PR 55) - the stated focus, item 330 | `codex/48h-maker-integration-20260912` | 89 commits, 166 files, +21,897 |
| Split qualification v2 (PR 68/69/70) | `codex/qualification-bootstrap-probe-20260915` | 161 files, +20,203 |
| Archive continuation / capacity / recovery | `codex/recovery-end-to-end-20260917` | 95 files, +9,898 |
| Settlement retry hardening (09-01) | `codex/workstation-overnight-ops-reliability-2026-09-81a` | 5 commits, ~1,400 lines |
| Capture memory-pressure incident + deployed watchdog (09-07) | `codex/capture-health-20260907` | 6 commits |
| Attended live Stage 0/1 test record (09-06) | `codex/stage1-pass-docs-20260906` | ~40 commits |
| Model/PIT research programme 08-31..09-04 (79a-100i) | `origin/...-2026-09-100i` | 36 commits, 99 files, +42,876 |
| Post-reclaim x9 (09-07), bounded settlement audit (09-12), misc | various | - |

Dependency chain to the first new maker-economics increment reaching production
(`STATE_OF_PLAY.md:34-38, 42-58`; `item-330:5-18`; branch `item-329` text): maker PR 55 <- reliability
PR 61 <- complete capture-host qualification (fails on memory) <- split qualification v2 (unmerged)
<- owner-approved first-landing envelope (not approved). Four layers of machinery.

### 3.4 Branch / worktree / merge-queue health

- 382 refs: local 115 merged + ~101 unmerged; remote 57 merged + 109 unmerged. 46 branches were
  retired on 08-11 (74 -> 28, `docs/roadmap/branch-retirement-2026-08-11.md`); five weeks later the
  count is 382.
- Age of the 109 remote-unmerged: 27 from 09-11..09-17, ~42 from 09-01..09-07, ~15 from
  08-11..08-31, 25 from 07-21..08-06.
- Unique code: see table in 3.3. Only **30 commits exist solely on this host** (no remote ref) -
  push discipline is good - but they include the capture hang-detection fix (edcdaeab5), model
  identity v0.3 (9f81b3fe5), the core model audit doc (d5efcd9bf), the Codex memory note (ea22c6002)
  and three archive result docs, on a disk with no backup (known_accepted) and ~4 days of headroom.
- Worktrees: exactly 200 (1 main + 199 linked): 8 in `C:/tmp`, 164 sibling directories under
  `C:/Users/micha/Desktop/github/`, 2 in `.claude/worktrees`, 25 in `scratch/w/`. 94 linked
  worktrees are on branches **already merged** into master; 87 on unmerged branches; ~18 detached
  (about half at commits on master). Two are `locked`; one of those
  (`weather-watchdog-deployed-aa99048`) is what the production health watchdog executes from.
- The merge gate: `scripts/ops/bounded_worktree_test_suite.ps1:23-25` sets 64% start / 66% abort
  commit ceilings and asserts them every chunk (`:543`, `:609`). On 08-14 the full suite peaked at
  36.49-38.96% commit (`ESTABLISHED_FINDINGS.md:2317, 2336, 2354, 2368`). On 09-13 the host attempt
  "stopped at 67.19% commit against its 66% abort limit after ten completed chunks"; on 09-14 a
  smaller-chunk successor "stopped during its first chunk at 68.5%" (design report on
  `codex/qualification-design-20260914`, b0cab6f8e). The gate is unchanged; the host's baseline
  moved ~30 points.
- Every large candidate rewrites the same hot files (`STATE_OF_PLAY.md`, `active-backlog.md`,
  `ROADMAP.md`, `schema_registry_data.py`): verified for the maker, reliability and split
  candidates with `git diff --stat master...<branch> -- <files>`. Under the project's own rule that
  any baseline advance invalidates a candidate's qualification, each landing invalidates all the
  others. The queue is serial, one slot a night (01:00-04:00), and that slot currently fails.

### 3.5 Automated drift commits

Source: `scripts/ops/quiet_window_merge.ps1:3487-3495` commits `config/locations.json` and
`config/location_market_events.json` before each guarded merge. 45 commits touched the 1.7 MB JSON
in 60 days (82 all-time); ~10 in the last 30 days, each changing 13,000-31,500 lines (6dd80bdfa:
11,846 insertions / 19,622 deletions). Estimated object-store cost is modest (order 10-20 MB;
inferred, I could not measure `.git`). The real costs are: a permanently dirty production working
tree (`git status` shows both files modified now; documented as routine at
`OPERATIONS_AGENT_ROLE.md:271-275`), unreviewable diffs on a file that drives market identity, a
merge tool that needs special rollback logic for it, and - since merges stopped on 09-13 - five days
of generated state that exists only as uncommitted working-tree bytes.

### 3.6 Converging or compounding?

Compounding. Evidence: (a) zero model/sources/backtesting touches and ~5% product commits in the
last 300; (b) the three stated objectives in `STATE_OF_PLAY.md:9-12` are each worse or blocked at
09-18 per the lead's live state - settlement hole 10/14, clean streak 2/14, unattended attempts
a1..a11 failed, maker candidate unadopted; (c) each failure of a gate has been answered with a
larger gate (item 329 -> reliability program item 331 -> split qualification v2 -> first-landing
installer); (d) test count rose from 4,544 (08-14 host suite) to 5,999 (09-14 split branch), almost
entirely operations/qualification tests, which makes the on-host full-suite gate heavier still;
(e) the process consumes the resource whose shortage trips the gates (section 4, findings 1 and 6).

## 4. Findings

### recent-work-1 (critical) - ~70 GiB of duplicated model pickles in 199 worktrees on a disk ~4 days from full

`git worktree list` returns exactly 200 entries. `.gitattributes` puts `artifacts/models/hgb/*.pkl`
under LFS, and the pickles are smudged in every worktree I sampled: `ls -l <wt>/artifacts/models/hgb`
reports `total 371548` (KiB) in each of 5/5 samples spanning every location class and 08-11..09-14:
`C:/tmp/wt-09-69a`, `weather-clock-health-status` (branch merged 08-14),
`weather-reward-cash-20260911`, `weather-capacity-day-20260909-a1` (detached),
`scratch/w/split-qualification-20260914`. Extrapolated: 199 x 363 MiB = ~70.5 GiB in pickles alone,
~80 GiB with the rest of each checkout. 94 linked worktrees are on branches already merged into
master (`git branch --merged master --format=%(worktreepath)`): ~37 GiB with no unmerged code at
stake. `ESTABLISHED_FINDINGS.md:2386-2392` recorded an unexplained 24.4 GB 24-hour drop on 08-14
"while many immutable proofs and new worktrees were active" and declined to assign causality; ~62
worktrees date from 08-13..08-15 (62 x 0.41 GB = ~25 GB). ~25 more were created 09-12..09-17
(~10 GB of the ~50 GB lost since 09-11). No doc under `docs/operations` or item 325 mentions
worktree disk cost (grep: zero hits). For scale, the five-week archive campaign reclaimed 79.1 GB by
moving irreplaceable capture originals to cloud storage.
Basis: live_state (count, 5 samples) + inferred (extrapolation, causality). Status: new.
Caveats: 5 of 199 sampled; worktrees may hold untracked receipts; two are locked and at least one is
referenced by a live scheduled task; scheduled one-shots seal "isolated checkout must remain exact
and clean" (`item-325:105`). Removal needs a per-worktree `git status` check, outside protected
windows, by the owner/ops agent - not a bulk delete.

### recent-work-2 (high) - The merge queue has stalled; 58% of the last 30 days' commits never reached master

Counts: `git shortlog -sn --since=30.days HEAD` = 266; `git shortlog -sn --since=2026-08-19 --all
--not master` = 360; since the last master merge (3bdba3d15, 09-13 04:09) = 80 unmerged, 0 merged.
Weekly unmerged/merged: W36 120/50, W37 157/71, W38 65/0. Gate mechanics and the 66% abort evidence
are in 3.4. The response to the failing gate was +16.7k to +20.2k lines of replacement
qualification machinery that must itself pass through a special owner-approved "first landing".
Hot-file overlap between the stacks guarantees serial re-qualification after every landing.
(Some unmerged commits are cherry-pick duplicates of merged ones, e.g. c7a4dd581/7aca80915, so 58%
slightly overstates unique work.)
Basis: verified_in_code. Status: known_open (`STATE_OF_PLAY.md:34-35, 38` admits the candidates are
unadopted; the quantification and the structural cause are new).

### recent-work-3 (high) - Master no longer describes production: a real-order live test, the archive reclaim code and the deployed watchdog exist only on unmerged branches

(a) `origin/codex/stage1-pass-docs-20260906` tip 8739902fe rewrites STATE_OF_PLAY to record that on
2026-09-06 the owner authorized, and the operator completed, an attended International Stage 0/1
lifecycle test: "up to 100 pUSD", attempt `pilot-20260907T001707063Z`, "Each Stage 1 mode placed one
0.005 pUSD BUY", zero fills, cleanup PASS. On master, `INTERNATIONAL_MM_LIVE_PILOT.md:28-29` still
says "no Stage 0 or Stage 1 protocol has passed", `item-330:113` says real W5-W7 sessions "remain
blocked by the no-live instruction", item 67 has no 09-06 entry (grep: none), and
`STATE_OF_PLAY.md:18-19` says only "No live trading is authorized". I did not verify the exchange
activity itself (evidence is off-repo); the divergence between master and the branch is verified.
(b) The archive campaign that deleted 79 GB of production originals executed from sealed isolated
checkouts of unmerged commits: `item-325:100-107` names execution source 811efd4c2 and states
"runtime adoption is still the earlier guarded archive/consumer stack"; 811efd4c2 and the later
reclaim commits (743ad12fa "reclaim approved originals after verified plain archive upload") are in
`master..codex/recovery-end-to-end-20260917`. (c) The production `WeatherHostHealthWatchdog` runs
from the locked detached worktree `weather-watchdog-deployed-aa99048` at unmerged aa99048ea
(`capture-memory-pressure-2026-09-07.md` on `codex/capture-health-20260907`; the file does not exist
on master - Glob: none). This is deliberate, hash-sealed practice, not an accident - but it means
`git log master` is not the record of what ran, the same defect shape the project already named
("we serve bytes that were never committed", `OPERATIONS_AGENT_ROLE.md:248-250`).
Basis: verified_in_code (divergence), doc_claimed (the live test itself). Status: new.

### recent-work-4 (high) - Small product-critical fixes stranded for 17-38 days while ~700 commits of machinery landed

(a) Capture hang detection. `OPERATING_REFERENCE.md:36-37`: a capture gap is fatal at 15 min, and
"on 2026-08-08 a hung snapshot loop took ~19 minutes to be declared DEAD ... and cost the day. A
supervisor that recovers slower than interval x 1.5 cannot save a day from a hang." Master still has
`dead_after = 2 * interval + 2` = 22 min (`src/weather/collection/snapshot_tracker.py:597, 607`).
The fix, edcdaeab5 "Bound snapshot hang detection below fatal gaps" (2026-08-14, 8 files,
+133/-26, adds `--supervisor-interval-minutes`), is on local-only branch
`codex/supervisor-gap-bound-20260814`; the flag does not exist on master (grep of
`src/weather/collection`: 0 hits). Clean-capture streak today: 2/14 (lead).
(b) Settlement recovery. 3e9b2c08c "Harden unattended settlement recovery and health reporting" and
511434d1d "harden settlement retry verification" (both 09-01; add
`settlement_backfill_retry_one.ps1` and `register_settlement_backfill_attempt.ps1`) are on
`codex/workstation-overnight-ops-reliability-2026-09-81a` only; Glob of `scripts/ops` on master finds
only `settlement_backfill_one.ps1`. The settlement hole grew to 10 of 14 dates in the interval
(lead); the only settlement commit to reach master since is a quoting fix (654bdc5eb, 09-04).
(c) Model identity binding. 7cf605a4f (08-11) / 9f81b3fe5 (08-15, local-only) fix the root cause the
project itself named for unreproducible serving; `loaded_code_hash` does not exist in master `src/`
(grep: 0 files); `OPERATIONS_AGENT_ROLE.md:266` still lists it "BUILT, not merged".
All three are roll-sensitive (they touch loaded capture/model modules), which is likely why they
lost every night's single merge slot to larger stacks.
Basis: verified_in_code. Status: known_open for the defects; the stranding is new.

### recent-work-5 (high) - Effort allocation does not match the stated objectives

See 3.1. Against `STATE_OF_PLAY.md:9-12` (protect capture and settlement evidence; restore reliable
unattended execution; non-live maker economics): capture/settlement data path received 4 of the last
300 commits, non-live maker economics 7, while live-pilot machinery - for an activity master says is
not authorized - received 53, qualification machinery 63, archive 64. `item-330:80-84` itself states
the problem ("earlier model, taker, reporting, and incident-response work still consumes
implementation attention ... A smaller active system should reach an honest economic decision
sooner"); two weeks later the system is larger (tests 4,544 -> 5,999; merge script 4,093 lines; PR
numbers #3 on 08-30 -> #70 on 09-15).
Basis: verified_in_code (hand-classified, +/-5). Status: new (measurement); the concern is
known_open.

### recent-work-6 (medium) - The development process is a measured consumer of the resources whose shortage trips the production gates (feedback loop)

Local-only commit ea22c6002 (09-09) records that the Codex agent backend on the production host held
5.09 GiB private memory, cut to 293 MiB by a restart. The unmerged 09-07 incident doc records a
51-minute snapshot outage (09:19-10:10, 547 errors, all 12 markets) under memory pressure, 75.5%
commit at 11:22, and that the 09-06 and 09-07 Stage-A chains "deferred at `ingest_quality_gate`;
the retained September 6 admission receipt explicitly names host commit above its 70% limit".
`item-325:25-27`: an archive batch "stopped at 71.033% host commit". Qualification aborts at 66%
(3.4). Full-suite peak commit was 36-39% on 08-14. So the same month-long rise in baseline commit
plausibly explains the settlement hole (70% gate), the merge stall (66% gate) and the archive stops
(71%) - and one measured contributor is the agent tooling itself, alongside ~70 GiB of worktrees on
the disk (finding 1). I did not measure current memory; causality is inferred.
Basis: inferred from doc_claimed measurements on unmerged branches. Status: new.

### recent-work-7 (medium) - Research results orphaned on unmerged branches again, including a spent terminal evaluation

Mission IDs `-09-86a` .. `-09-100i` have zero occurrences anywhere under `docs/` on master;
`-09-79a`..`-09-82a` likewise (only 83a-85a appear). The orphaned set includes the multiyear NWP
residual test (`agent-report-2026-09-12-workstation-multiyear-nwp-residual.md` at 30386b5f0):
verdict INCONCLUSIVE_UNDERPOWERED, improvement 0.2751 C^2-eq, 95% CI [-0.0234, 0.6186], power 0.389,
and "the spent 2025 terminal evaluation must not be tuned against or rerun" - plus the twelve-field
seasonal challenger "terminal result", a PIT v2 source-contract no-go and an "external residual
integrity failure". None is in `ESTABLISHED_FINDINGS.md` (grep: 0). The project already had to
rescue 13 reports from unmerged branches on 08-11 (4e2b8c279). The branch is on origin, so the risk
is not loss but a future agent re-running a spent evaluation or re-deriving a closed null because the
canonical findings file does not know it happened.
Basis: verified_in_code. Status: new (recurrence of a known defect shape).

### recent-work-8 (low) - Generated 1.7 MB JSON tracked in git and auto-committed

See 3.5. Basis: verified_in_code. Status: known_accepted (`OPERATIONS_AGENT_ROLE.md:271-275`).

### recent-work-9 (low) - Report filenames and mission IDs carry synthetic future dates

`agent-report-2026-09-02-...estimand-power-and-sign.md` was committed 2026-08-12 (ef4198b19);
`agent-report-2026-09-10-...` and `-09-11-...` were committed 2026-09-04 (2e6c9b49f, 2d586da6d);
mission IDs run `2026-09-78a`, `2026-09-100i`. `docs/roadmap/AGENTS.md:34` tells readers to order by
commit, "not filename date". With ~600 dated files this makes the correspondence hard to audit and
invites exactly the staleness errors the project keeps retracting.
Basis: verified_in_code. Status: known_open.

### recent-work-10 (low) - 30 commits exist only on this host

`git log --branches --not --remotes` lists 30 commits, including edcdaeab5 (capture hang fix),
9f81b3fe5 (model identity v0.3), d5efcd9bf (core model audit doc), ea22c6002 (Codex memory note),
402dfe38d / 61c3a349f / 5f0ed270b (archive result docs) and two `preserve/*` stashes. With the
mirror paused and the disk near full, these are single-copy. Pushing them is cheap.
Basis: verified_in_code. Status: new. (Off-host backup itself is an accepted owner decision; this is
only about un-pushed git refs.)

## 5. Strengths

- **Failed attempts stay failed.** Item 329 and item 325 preserve failed receipts, refuse to relabel
  them PASS and require a reviewed successor (`item-329:23-29`, `item-325:25-32`). Candid NO-GO
  reports are normal (a24cf0f41, d2ab532a5, ef4198b19).
- **Push discipline.** Only 30 of ~1,800 commits across all refs lack a remote copy.
- **Restorable cleanup.** The 08-11 branch retirement manifested every tip SHA
  (`docs/roadmap/branch-retirement-2026-08-11.md`).
- **The archive campaign delivered a measured, verified result** with byte-exact accounting and
  independent restore proofs (`item-325:56-66`).
- **Canonical docs do not oversell.** `STATE_OF_PLAY.md:12`: "No market edge or profitable maker
  opportunity is proved"; research threads were closed on power analysis rather than tuned
  (-09-78a, d1ce8c1ca).
- **Real product fixes do exist and are well written up** when they land: settlement finalize
  per-folder isolation (3c38a1b0b / bcb49506d, 08-11), backfill substring verification (150514079).

## 6. Not covered / open questions

- I did not read `data/` (not in my brief): the a1..a11 task failures, 09-14..17 archive task
  failures, disk and settlement figures are the lead's.
- I did not measure actual worktree sizes (no `du`); finding 1 rests on 5 `ls` samples.
- I did not open PRs on GitHub (no network); PR numbers come from docs.
- I did not inspect the 25 oldest remote branches (07-21..08-06) individually; the project's own
  08-11 note says they hold unique code.
- I did not diff every unmerged branch; "unique code" is established only for the stacks in 3.3.
- Open: why did host baseline commit rise ~30 points between 08-14 and 09-06? Is an agent session
  resident on the production host around the clock? Was the hang-detection fix deliberately held,
  and by whom? Is the 09-06 live test known to every agent that reads only master?
- Process note: I twice issued two light read-only calls in one turn (two `git shortlog`; one
  Grep + Read) before reverting to strictly serial calls, and used `tail -n 5` once instead of
  `head`. No heavy or recursive command was run.
