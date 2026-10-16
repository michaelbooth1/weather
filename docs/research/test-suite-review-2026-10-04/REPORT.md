# Test-suite review K: report (2026-10-04)

Status: dated research report for item K (test-suite value and speed review), written by role 22 (scribe)
on 2026-10-04 at about 20:30 local. It is historical evidence. It is not policy: the adopted test policy is in
PR #205, and the current state lives in `docs/operations/STATE_OF_PLAY.md`. Read this when you need to know
why the K PRs exist, what they measured, and what the owner still has to decide.

## Verdict

**The suite is not bloated with useless tests.** The evidence does not support cutting tests to save time.

- **Duplicates.** The overlap analysis screened 111,985 high-overlap pairs. After a fault argument for each,
  only **2 true duplicates** remain. Both are in frozen safety families, and together they cost **about 0.01 s**
  [role 5].
- **Trivial tests.** There are **0 unfalsifiable tests**: no test asserts only a constant or its own mock
  [role 7, confirmed by roles 15–19].
- **Quarantines.** **0 quarantines were proposed.** Four owner-package reviewers read 1,564 flagged tests, and
  every removal candidate failed the brief's condition (a) (a named fault argument) or condition (d)
  (a measured cost) [roles 16–19].
- **The cut list is empty.** Section 4 explains why, and records the quarantine mechanism for future use.

**The time goes on a few process-heavy files, the Windows shard setup and the single heavy lease.**

- **A few files.** On a full Windows run, the reconciler execution file alone is **44%** of the time
  (1,743 s of 3,933 s). The top 10 files take 71%. The 39 files that start PowerShell take 69%
  [P0-2, coverage-traced].
- **Windows shard setup.** About 100 s of each Windows CI shard is checkout and dependency install [P0-3].
- **The single heavy lease.** It serialised every heavy run on the workstation. During this review it blocked
  verification for hours: role 11's xdist trials never ran, and several before/after runs were still blocked
  when this report was written (section 1, the lease row).

**The larger risk is under-assertion, not over-testing.**

- **Surviving faults.** Hand mutation of hot safety code left **54 real faults** that no test caught (59
  uncaught, 5 judged equivalent) [role 6]. Examples: the serving physical floor (`max` changed to `min`); the
  maker countability gate; the release bootstrap interval; the maker quoting gates; settlement band spelling;
  source-health classification.
- **Mostly closed.** PRs **#206** and **#208** add assertions that kill **53 of the 59** uncaught mutants.
  3 of the remaining 6 are equivalent mutants. The other 3 are maker-freshness and countability rules: two wait
  on #145/#207, where the owner's fail-closed freshness#3 decision is applied; the third is a rule the owner has
  not ruled on (section 6.2).
- **Other blind spots.** 303 Windows-only cases never ran in any CI job; PR #209 adds the lane, and its first
  run found **15 latent failures** in them. 12 import-architecture ratchets passed vacuously when run from
  another working directory. 2,030 `.ps1` text-substring asserts stand in for execution — the pattern that hid
  an inert kill path for 27 days (EF §10g).

## Sources and caveats

Every number below carries a tag naming the role whose output it comes from. Those outputs are
workstation-local under `C:\wt\workstation-chat\k-data\<role>\` (JSON plus `summary.md`). They are not in the
repository.

| Tag | Source | Caveat |
| --- | --- | --- |
| P0-1 | AST safety census of `tests/` at `492ee6e5` (`safety_manifest.json`) | Family assignment is deliberately inclusive |
| P0-2 | One full Windows workstation run at `492ee6e5`: 7,247 cases, 0 failures, wall time 3,989 s, sum of per-test times 3,933 s | **Coverage-traced.** CPU-bound Python tests are inflated; spawn-bound tests are not. Trust the ranking, not the absolute seconds |
| P0-3 | Last 500 Actions runs (2026-09-27 to 10-04), 59 failed jobs read with `--log-failed` | Only a 7-day window; Linux had no JUnit before #197 |
| R10-base | Role 10's run of the 39 PowerShell-spawning files without coverage: 944 cases, 0 failures, 3,472 s | Workstation, under the lease |
| CI | GitHub job durations and JUnit from each PR's own runs | Hosted-runner noise is about ±60 s per shard |
| role N | `k-data\NN\summary.md`, `candidates.json`, `verdicts.json` (role 20), `pr-body.md` | Single workstation runs unless stated |

## 1. Projected minutes saved, per intervention

Columns: the local workstation full run (58–66 min [R10-base, P0-2]); the capture-host bounded suite (K could
not run on the capture host, so these are projections only); Linux CI (test job median 542 s, pytest 478 s
[P0-3]); Windows CI (critical path median 439 s before #203 [P0-3]).

| Intervention | PR | Workstation | Capture-host bounded suite | CI Linux | CI Windows | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Lease: FIFO queue and focused-run exemption (P3) | #205 rule, #213 mechanism (item M) | Removes the queue wait for runs of ≤ 25 files. Measured waits this session: role 11 waited more than 2 h and never ran; role 9's runs were refused 192–209 times (about 3.5 h); role 14 waited about 3 h for a 28 s collect; role 13 abandoned a run after 2.5 h; role 21 abandoned one after 25 min | 0 (capture-host rules unchanged) | 0 | 0 | Status logs in `k-data\09`, `11`, `13`, `14`, `21` | P3 adopted. #213 is a draft; its CI `test` job was **failing** at `2da2c5cb` when this was written |
| Local definition of done = focused + affected tests (P2) | #204 tool, #205 rule | Replaces a 58–66 min full run with a selection: median 23.5 test files (5.2% of files, 7.0% of functions) over the last 30 merged PRs [role 12]. In force only once the Windows lane covers the Windows-only cases | 0 (the bounded suite stays the integration gate) | 0 | 0 | Recall 13/16 culprit files; the 3 misses were a cross-branch conflict [role 12] | P2 adopted with the Windows-lane condition. #204 is advisory |
| Time-packed bounded-suite chunks and rebalanced Windows shards | #203 | 0 | **0 total**: chunks run serially. The worst chunk drops from 1,885 to 1,743 s (P0-2 seconds). Chunk cap 25 (19 chunks) saves about 80 s per run — approved by the owner on 2026-10-04 and being added to #203 | 0 | **About 1–3 min per PR**: shards 260–368 s at `5109f977`, against a 439 s median critical path before | CI JUnit 448 → 451 ids, none missing, no outcome changes [role 13, Defender] | CI green. Bounded-suite before/after still lease-blocked |
| Shared PowerShell host and cached status git history | #201 | About 2.3 min (estimate for `test_status_script`) [role 16] | About 2.3 min (projection) | 0 | Unproven: `test_status_script` 395 → 345 s, within the ±60 s noise [Defender] | CI 448/448 identical ids and outcomes | CI green. Full Windows run (host on and off) lease-blocked |
| Git template, reconciler step 0 and wait ceilings | #202 | About 4.7 min: reconciler ~245 s, exam step ~28 s, wrappers ~10 s [role 16] (P0-2-based estimate) | About 4.7 min (projection) | 0 | 0 on today's shards (noise). Applies to the #209 reconciler shards once both land. The ceilings remove the wrapper-deadline flake class, 2 of the 4 Windows flake events in 7 days [P0-3]; each rerun costs about 15 min | CI 448/448 identical, but the changed files are in no shard | CI green. Mandatory reconciler Windows run lease-blocked |
| Ratchet marker: ratchets run once, in the fast audit job | #200 | 0 | 0 | Small: 5 ratchet files no longer run twice. The real gain is **time to signal**: the most frequent fire class (22 SHA-level fires in 7 days [P0-3]) now fails in the ~78 s audit job instead of after the ~9 min test job | 0 | Collect-only identical (7,247 → 7,254, +7 new); ratchet 122 + not-ratchet 7,132 = full, overlap 0 [role 14] | CI green. Outcome run lease-blocked |
| Windows lane for the 303 never-in-CI cases | #209 (stacked on #203) | 0 | 0 | 0 | **Adds cost**: 9 new jobs, about 67 runner-minutes; the critical path rises to about 11.7 min (`reconciler-2`, 701 s). Buys coverage, not speed | First run found 15 latent failures, fixed at their cause | All 13 Windows jobs and CI green at `3767c21f` |
| Reconciler step 1 (per-module template) | none (signed off with conditions) | About 1.75 min (105 s) [role 16] | Same | 0 | Shard-local | Projection | Not built |
| Reconciler step 3 (`-n 4` for this file only) | none (signed off with conditions) | About 1,283 → 365 s wall [role 16] | Never (bounded suite stays serial) | 0 | Shard-local | Projection | Not built. Deadline cases must stay serial |
| Settlement audit-scaling shrink | none (signed off with conditions) | — | — | About 50 s [role 17] | — | Bench measured; mutant check pending | Not built |
| Casebook memory-test shrink | none | — | — | About 32 s [role 17] | — | Bench measured | Moot if #145/#207 delete the file |
| `mm_paper.anti_overfit_summary` single-pass rewrite | none (escalated; product change) | — | — | About 21 s (69 → 48 s) [role 18] | — | 5-run fixture only | Out of K's scope; #145 deletes the file |
| Module-scoped `_evaluation` fixture | none (signed off with conditions) | — | — | About 10 s [role 19] | — | Estimate | Not built |
| Deduplicating the 2 true duplicates | none | 0.01 s | 0.01 s | ~0 | ~0 | [role 5] | Recommend keep |
| Converting sleeps to polled waits | none | 0 | 0 | 0 | 0 | All 19 sleeps are floors, stimuli or already polled; about 10.4 s of floors per full run [role 9] | Nothing to do |
| Collection tuning | none | About 0.3 s per process (`tests/operations/__init__.py`) | Collection ~16 s × 24 chunks ≈ 6 min; only fewer chunks reduce it | Collection is under 6% of the job [role 15] | — | [role 15] | Hygiene only |
| xdist | none | — | Never | — | — | No run ever completed | **Refused** until three identical `-n 8` runs exist |

**Net effect.**

- **Built and green.** About 7 min off a 58–66 min workstation or bounded-suite full run (estimates, not yet
  measured), and 1–3 min off Windows CI from #203.
- **Coverage added.** #209 adds about 5–6 min to the Windows CI critical path and about an hour of runner time
  per PR, in exchange for 303 cases that never ran in CI.
- **The real lever is not running or waiting.** The gain comes from not running the full suite locally (P2)
  and not queueing behind the lease for focused runs (P3, item M).

## 2. Invariant coverage retained or added

**Mutation gaps closed** (role 6's 104 hand mutants over 27 hot functions).

- **#206** (operations and reporting) kills 9 mutants: the WU orphan writer PID 0 boundary; the inclusive
  replay-cache memory floor; a duplicated capture-loop row; the bootstrap interval (alpha not halved, no
  resampling, lower bound from the upper quantile); the countability gate (quote-starvation BLOCK, PASS without
  the live-gate flag, the first blocker).
- **#208** (market, maker_core, model, settlement, sources, app) kills **44 of 44** targeted mutants: the serving
  physical floor, 4 mutants (train/serve parity could not catch these because both paths call the same
  function); maker eligibility 4 and `qualified_mid` 2; `band_contains_value` 4; the WU cutoff dropping untimed
  rows; the hashed-inventory entry count; band spelling 3 and the ledger `gte` boundary; source status,
  degradation and age 9; NBM CDF and slot, and Open-Meteo `split_ranges`; app helpers 9.
- Every new test passes on master and fails under its mutant (`k-data\pa\evidence\kill_matrix.json`,
  `k-data\pb\results.json`).
- **Left open (6):** `order_score#4` ×2 and `_verify_hashed_inventory#1` are equivalent;
  `maker_paper_score_freshness#1` lives in `test_mm_paper.py`, which #145 deletes; `freshness#3` — the owner
  ruled fail-closed, and #207 applies it with `test_countability_block_fails_closed_per_status`;
  `_maker_countability_gate#3` (the NON_COUNTABLE → WARN row) is deliberately unpinned until the owner rules on
  extending fail-closed to the summary (#207's open point).
- **Sole killers kept.** 10 tests are each the only test that kills a named fault, e.g.
  `test_protected_capture_window[4-45-False]` (the only pin on the 04:45 tiering-window boundary) and
  `test_gte_or_higher` [role 6].

**Execution twins (#198).** Seven tests run the real `memory_commit_guard.ps1` and `daily_refresh.ps1` with the
host cmdlets shadowed and recorded: EF §10g (the critical commit kills the largest ungoverned Python); EF §8d
(orphan reaping only inside the protected window, and the deadline killing child and grandchild); EF §8u (an
agent heavy tree killed children-first). Reintroducing the EF §10g `$pid` bug fails the twins while **all 7
substring tests it twins still pass** [role 8] — the brief's reason for replacing text gates rather than deleting
them.

**CWD-anchored ratchets (#206).** On master, `test_import_architecture.py` run from `C:\` gives 12 failed and 15
passed; the 15 passes are vacuous (every import-time glob constant came back empty, e.g. `PATH_POLICY_MODULES` 0
instead of 607). #206 anchors the globs on the repository; the anchored constants are byte-identical to a
repo-root run, and the file passes 28 of 28 from both directories. Finding: the `src/weather/market/maker_plugin`
root scans nothing even from the repository root, so half of `test_maker_core_and_plugin_import_boundaries`
checks nothing today (recorded, not changed). `test_app_architecture.py` has the same pattern (role 19, B07); not
changed yet, because #200 edits that file.

**The never-in-CI Windows tests get a lane (#209).** 303 Windows-only cases ran only in local full runs
[role 15], including the reconciler's 70 (EF §8w), scheduler RPC 38, `monitoring_fixes` 35, `workload_admission`
23 and `wallet_reader_logon_task` 10. #209 puts all 38 such files in Windows shards; the reconciler is split 7
ways by `-k` with a complement shard so a new test always lands somewhere; a ratchet fails when a Windows-only
file is in no shard. **The first run found 15 latent failures**: 11 reconciler cases (the hosted checkout had no
LFS objects) and 4 workload-admission cases that had silently skipped ever since lease-recovery warnings began
printing to stdout.

**Ratchets execute exactly once (#200).** A meta-test proves the audit and test selections are complements; the
Windows-only ratchets (`windows_native`) run in the launch shard; every ratchet executes exactly once across all
workflows.

## 3. Counts by class

S = safety/frozen, R = fired for real, C = unique contract, B = brittle, I = inventory ratchet, D =
duplicate/overlap, T = trivial/unfalsifiable, W = runs only on Windows. Each row counts that reviewer's flagged
tests by primary class (a test flagged by two reviewers counts twice; there are almost no such overlaps).

| Reviewer | Rows | S | R | C | B | I | D | T | W |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 operations | 1,162 | 388 | 18 | 149 | 213 | 1 | 1 | 0 | 392 |
| 17 reporting (+ `test_daily_refresh.py`) | 292 | 185 | 2 | 105 | 0 (37 secondary) | 0 | 0 | 0 | 0 |
| 18 market + maker_core | 34 | 10 | 1 | 17 | 4 | 0 | 0 | 1 | 1 |
| 19 model, calibration, backtesting, collection, sources, app | 76 | 16 | 2 | 54 | 2 | 0 | 1 | 1 | 0 |
| **Total** | **1,564** | **599** | **23** | **325** | **219** | **1** | **2** | **2** | **393** |

- **D = 2**: role 5's two true duplicates, both frozen (`test_loop_supervisor::test_fresh_heartbeat_is_noop`;
  `test_production_cold_archive_stage_cli::test_capture_time_and_resources_refuse[free_disk-…]`).
- **T = 2**: the same item seen by two reviewers — 12 unconditional placeholder skips in `test_re1_parity.py`,
  not tests that assert nothing.
- **I = 1 here**: the ratchet class is counted by role 14 instead (122 ratchet-marked cases in 21 files).

Context: 3,583 of 5,099 test functions (70%) are in never-cut families [P0-1]. What fired in CI [P0-3]: real
defects 81 ids from 4 incidents; test defects 8; inventory ratchets 7 ids / 22 SHA-level fires; flakes 4 (one of
them, the fan-out `PermissionError`, was really a capture-host race — item L, #210). Brittleness [role 7]: 2,030
`.ps1` substring asserts across 216 tests; 6 pins of a current file's hash; 494 private-name couplings; 13
CWD-relative paths; 53 mock-interaction-only tests (falsifiable: most assert a kill or start is *not* called on
an identity mismatch).

## 4. Cut list, by risk tier

| Tier | Candidates |
| --- | --- |
| Low | **none** |
| Medium | **none** |
| High | **none** |

**The cut list is empty.** Removal needs (a) a fault argument, (b) no real fire in CI history, (c) no incident
pointer and (d) a measured cost. Zero-killer flags (905 of the 1,352 tests that executed a mutated line killed
nothing) are incidental coverage through fixtures, not redundancy, so (a) fails [role 6]. Non-frozen
near-duplicates each test a different input partition and cost under 0.5 s, so (d) fails. The two true
duplicates are frozen and cost 0.01 s in total: keep them.

Instead of cuts: collapse the 12 placeholder skips in `test_re1_parity.py` into one (Defender signed off with
conditions; it removes 11 ids, so it stayed out of the tests-only #208). Substring gates are **replaced, never
bare-deleted**, and retire only under the Defender's conditions in section 5.

**The quarantine mechanism for future use (#199)** is built, and no test is marked:
`@pytest.mark.quarantine(reason=, added=, sunset=, replaced_by=)` keeps a test collected and running; its failure
becomes a non-strict xfail with a warning, a terminal section and JUnit properties (a teardown error stays fatal).
`tests/quarantine_registry.json` records `first_added` and every renewal; the sunset is at most 6 weeks after
`added` and at most 12 weeks after `first_added`. An expired sunset fails collection only under GitHub Actions;
off CI, including the capture-host bounded suite, it is reported, so a calendar date never aborts an integration
night. Deletion is stage 3 and an owner decision: at least 2 weeks of CI and at least 3 bounded-suite runs with no
real-defect failure.

## 5. The Defender's dissent (role 20)

The Defender ruled on 36 proposals: 9 signed off, 20 signed off with conditions, 3 refused, 4 escalated.

**The refusals stand** (owner, 2026-10-04):
1. **Reconciler step 2** (one shared "pristine" harness for 20 refusal cases). The cases assert only
   `returncode != 0` and "state unchanged"; a leftover marker, journal or ref would make every later case refuse
   at that leftover, and all 20 would stay green while the preflight under test goes unexercised (EF §8w's
   failure mode). Resubmit only with which-stage assertions, a whole-root fingerprint and periodic fresh-harness
   runs.
2. **Splitting `test_daily_refresh.py`, for now.** Open PRs #145, #124 and #125 edit it; conflict resolution in
   moved code is how a test gets silently dropped, and the split saves about 0 s. It can return after those PRs
   settle, with a 149 → 149 id map and an AST body hash per test.
3. **xdist, until there is evidence**: three identical runs; the lease and poison-path files in one serial group;
   `OUTER_WORKSTATION_LEASE` is evaluated at import; #199's terminal summary loses failures from xdist workers.

**Leak paths the Defender found that the proposers did not name:** the lease GUID mutex copy still resolves the
real ProgramData poison file (#206 left the 14 lease-skipped tests unchanged; a safe version needs a test seam in
`workload_admission.ps1`); under parallel load a mutant that extends a deadline can still pass its deadline test
(reconciler `-n 4`); the wrapper flake message covers both the deadline and the memory ceiling; the audit-scaling
shrink was checked and found safe.

**Defender conditions still open** (at the head SHAs in section 7):
- **#198**: #203's pinned shard plan must name the twins once both land; substring gates retire only once their
  twin exists, passes and runs in a Windows CI shard, with a needle-to-assertion map per retired test.
- **#199**: make `replaced_by` mandatory and validate it names a collected node id for frozen-family tests; warn
  ahead of an expiring sunset in CI; fix the xdist summary before any xdist adoption; show the identical outcome
  set on a full Windows run. Done: bounded renewal, CI-only expiry, hook self-test.
- **#200**: pin the pytest version behind the private `_pytest.mark.expression` import; owner note — with
  `needs: audit`, a stale inventory now withholds the behavioural signal for that push. Done: Windows coverage
  (`306361e6`).
- **#201**: a full Windows pass with the host on and off; a retained diagnostic file instead of host stderr to
  `DEVNULL`. Done: call-site guard and the `$PID` and exit-code exclusions (`759d5e1d`).
- **#202**: all 70 reconciler cases and `test_storage_recovery_night_wrapper.py` on Windows before and after with
  identical ids and outcomes; a mutation check under the cache; a blob-hash check against a stat collision in
  `commit --all --amend`; justify the exam-fixture worktree; prove from the attempt-1 log that the deadline fired,
  not the memory ceiling, before raising the ceiling.
- **#203**: an identical bounded-suite run before and after; the first capture-host bounded run after merge must
  log per-chunk disk lows. Done: shard-file pin (`5109f977`).
- **#204**: advisory only; a roll verdict for the new `src/weather/operations` module, or move it to `tools/`; a
  coverage cross-check before any policy use.
- **#205**: run the anti-regrowth ratchet report-only for 2 weeks (no report-only switch was found on the branch).
- **#209**: an independent Defender-style review of the exact-payload helper added to the never-cut
  workload-admission tests (in progress; its verdict goes into #209's body before landing).

## 6. Owner decisions

### 6.1 Taken (2026-10-04, relayed by the production agent)

- **P2 adopted, with a condition**: the local definition of done becomes focused + affected tests once a Windows
  CI lane covers the ~303 Windows-only cases (including the reconciler's 70); until then a local full suite stays
  required for changes touching Windows-executing scripts.
- **The Windows-only CI lane is approved** (#209); keep 7 reconciler shards.
- **P3, P4 and P5 adopted.** The P3 mechanism (heavy FIFO queue plus the focused-run exemption) is item M, PR #213.
- **Bounded-suite chunk cap 25 (19 chunks) approved** (being added to #203).
- **freshness#3 fails closed**, applied on #207 in `retired_trading_evidence.py`.
- **The fan-out race fix is item L, PR #210** (roll-sensitive: quiet window).
- **The Defender's refusals stand.**

### 6.2 Still needed

1. **The lease bottleneck itself.** Until #213 lands (its Linux `test` job was failing at `2da2c5cb`), every heavy
   run queues behind one host-global lease with no order; this session lost hours to it and most of K's
   identical-pass-set evidence is still blocked. Decide the landing order (#205, then #213) and consider granting
   K's evidence runs an uncontended lease window (about 4 full-run slots: #199, #200, #201, #202).
2. **#145 / #207.** Landing them moots four K proposals (casebook shrink, `mm_paper` rewrite, freshness#1,
   `daily_refresh` split sequencing). Open point: should the trading-evidence summary (`_summary_status`) also
   BLOCK on NO_ACTIVE_DAY? That decides whether the countability WARN row is pinned.
3. **The reconciler speed path.** Approve building step 1 and step 3 (both signed off with conditions).
4. **A test seam in `workload_admission.ps1`** (inject the state root, mutex name and process snapshot): an
   ops-script change needing a roll verdict and Defender review. Without it, 14 admission tests keep skipping
   inside every wrapped run.
5. **Merge-order hazards.** #199, #200 and #205 each add a `markers =` key to `pytest.ini`; #199 creates
   `tests/conftest.py`, as do #152, #173 and #177; `windows-qualification.yml` is edited by #127, #193, #194, #198,
   #203 and #209. The meta-tests catch a dropped line, but only on the PR that lands second.
6. **Retiring the substring gates.** Once the twins run in a shard, quarantine the gates they replace, then delete
   them after the staged-cut evidence (role 16 counts about 200 text gates, 165 High tier). The quiet-window-merge
   twins (`test_quiet_window_merge_script.py`: 43 text-only tests, no execution test) are in progress.

## 7. PR table

Read on 2026-10-04 at about 20:30. "CI" is the head commit's checks. "Pass set" is the brief's identical-pass-set
proof (same ids and outcomes before and after, on Linux CI and one Windows full run).

| PR | What | Head | CI | Pass-set proof | Open Defender condition |
| --- | --- | --- | --- | --- | --- |
| #197 | Linux JUnit artifact | `bc78abc8` | green | Not needed: no selection change; artifact confirmed | none |
| #198 | Execution twins (7) | `2c124458` | green | Additions only; twins run in the archive shard | Pin twins in #203's plan; retirement rules |
| #199 | Quarantine marker | `344e3c9f` | green | Collect-only identical (7,247 → 7,288, 0 lost); **full Windows outcomes pending (lease)** | `replaced_by` for frozen tests; pre-expiry warning; xdist summary; outcome run |
| #200 | Ratchet marker | `306361e6` | green | Collect-only identical (7,247 → 7,254); selections partition the suite; **outcome run pending (lease)** | pytest version pin; owner note on `needs: audit` |
| #201 | Shared PowerShell host | `759d5e1d` | green | CI 448/448 identical; **Windows full run, host on and off, pending (lease)** | Full Windows run; retained diagnostic file |
| #202 | Git template, reconciler step 0, ceilings | `f218b40f` | green | CI 448/448 identical, but the changed files are in no shard; **reconciler Windows run pending (lease)** | Reconciler and night-wrapper Windows run; cache mutation check; blob-hash check; exam worktree; deadline-vs-memory log |
| #203 | Time-packed chunks, balanced shards | `5109f977` | green | CI 448 → 451, none missing; **bounded-suite before/after pending (lease)** | Bounded-suite run; disk lows on the first capture-host run |
| #209 | Windows lane (stacked on #203) | `3767c21f` | green (CI + 13/13 Windows jobs) | First CI run of the 303 cases; 15 latent failures fixed at their cause | Defender review of the exact-payload admission helper |
| #204 | Affected-test tool | `706223d2` | green | Not needed: additive tool | Advisory only; roll verdict or move to `tools/`; coverage cross-check |
| #205 | Anti-regrowth ratchet + adopted policy | `c73efbe8` | green | Not needed: additive | Ratchet report-only for 2 weeks |
| #206 | Assertions: operations + reporting | `d344b3b9` | green | Additions + CWD anchor: anchored set byte-identical, 28/28 from both directories | none (signed off) |
| #208 | Assertions: market, model and others (tests only) | `9b368a12` | green | Additions only: 44/44 mutants killed; touched files 684 passed | none |
| #213 | Item M: FIFO heavy queue + focused exemption | `2da2c5cb` | **`test` failing** (at time of writing) | — | P3 mechanism; lands after #205 |
| #210 | Item L: fan-out `PermissionError` race | `624af5db` | green | — | Roll-sensitive: quiet window |
| #207 | #145 retarget incl. freshness#3 fail-closed | `4b27ae2c` | green | — | Lands after #104 in the quiet window |

## 8. Corrections to the brief's facts

| Brief said | Evidence says | Source |
| --- | --- | --- |
| 724 `.ps1` substring asserts in 59 files | 2,030 static asserts in 43 files (216 tests). 16 of the 59 files have no such assert: they execute the script, ratchet over all scripts, or read output files. Counted another way: 2,087 literal needles in 208 pure-gate tests [role 8], or 810 asserts in modules that never run PowerShell [role 21] | role 7 |
| `test_status_script` pins the SHA-256 of five sibling scripts | The five scripts are copied and hashed **at run time**; the literal hashes are historical blob hashes at commits `3361520f`/`c932b54f`. Editing those scripts does not break the test; a shallow clone would | role 7 |
| `test_maker_replay_exam_step_script` imports the dead `weather._fixture_record` | The import sits inside string constants (fixture source the test writes into its temp repository). All 20 tests collect; there is no dead import | role 7 |
| 141 skips, mostly without a reason | 139 skip sites [role 7] or 158 [role 15]; **0 lack a reason**. The real problem: 303 Windows-only cases never ran in CI | roles 7, 15 |
| 41–45 files start PowerShell | 39 files actually spawn PowerShell; the rest only read or classify command text | P0-1 |
| 5,099 test functions + 412 parametrizes ≈ 7,100 cases | 7,247 collected cases (390 parametrized functions expand to 2,528 cases) | role 15 |
| `test_status_script` alone takes 503 s on Windows | 378–489 s per CI shard [P0-3]; 265 s on the workstation [P0-2] | P0-3, P0-2 |
| Windows 46–50 min | Not reproduced by K (no capture-host runs). Sharded Windows CI critical path median 439 s; a workstation full run is 58–66 min | P0-3, R10-base, P0-2 |
| 6 of 8 recent CI failures were inventory ratchets | Over 500 runs, ratchets were the most frequent fire **by SHA** (22). Real defects fired too: 81 ids from 4 incidents. 17 of 33 failed `test` jobs were ratchet or audit fires | P0-3, role 14 |
| P0-2's temp bytes: ~0.9 GB per reconciler test (about 64 GB per run) | A size walk double-counts git-lfs hard links; the real footprint is about 141 MiB per test, freed on pass | role 10 |
| Role 15: the `tools/` morning-guidance test is never collected | It **is** collected, through a re-export in `tests/reporting/test_morning_guidance.py` | role 19 |
| Role 6: the quote-starvation BLOCK mutant is a real gap | Near-equivalent: the summary builder already appends that blocker | role 19 |
| The fan-out failure is a flake | A real Windows race (O_EXCL claim → `PermissionError`) on the capture host's shared CAS | role 19, Defender; item L |

Confirmed as stated: Linux CI runs about 9 min (test job median 542 s [P0-3]); `test_daily_refresh.py` holds 149
tests [role 17]; the 21 git-fixture files [P0-1]; the 24 serial bounded-suite chunks (⌈465/20⌉ [role 13]).
