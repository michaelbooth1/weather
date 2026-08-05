# Workstation report 2026-08-05 — map the held backlog onto the 97 blockers

## Verdict

The held queue contains **39** remote branches at fetched `origin/master @
ea3a802de807d160fbfca59046771921b99b0654`. The branch verdicts are:

| Verdict | Count |
| --- | ---: |
| MERGE | 6 |
| SUPERSEDED | 24 |
| REPORT-ONLY | 0 |
| NEVER | 2 |
| UNKNOWN | 7 |
| **Total** | **39** |

The most important result is not the merge count. **No held branch clears any
of the 97 retained-production blockers today.** Several branches implement
necessary machinery, but the missing real evidence remains missing:

- the consolidated stack provides the PIT corpus builder and the only exact
  PIT-corpus-to-feature-row binding, but no real corpus was collected;
- the first-retrain branch provides the refusing fleet lane, support and
  calibration machinery, but its retained preflight still reports all 97
  blockers;
- the parity branch provides a detector, not a repair; and
- no branch supplies a serving-compatible native-support reader, an exact-PASS
  parity corpus, candidate-specific fit evidence, or one unified artifact
  regime across the actual feature records.

The correct integration is therefore not “merge a branch and watch a gate turn
green.” It is a five-quiet-window program after Release #1 is completed and
reviewed, with the old PIT/retrain seam deliberately re-wired into the newer
`-09-12a` lane.

No branch was merged or deleted, no PR was opened, and no release, PIT corpus,
provider, schedule, capture process, floor, promotion gate, or production state
was touched. The reservation was re-read: **no dates are reserved; the window
is armed but undated**.

## Method and evidence boundary

The inventory is the exact output of:

```text
git branch -r --no-merged origin/master --format=%(refname:short)
```

filtered to `origin/codex/*`. For every ref I measured its tip, merge base,
cumulative changed paths, paths also changed underneath it on current master,
and a two-tree merge against current master using `git merge-tree --write-tree`.
This did not update a ref or working tree. The result is 29 clean merges and 10
textual conflicts.

Roll sensitivity uses the retained production
`runtime_identity.source_scope_files`, not `SOURCE_PATTERNS`:

| Protected loop | Recorded files |
| --- | ---: |
| snapshot | 77 |
| CLOB | 23 |
| observation trigger | 85 |
| union | 89 |

For a new module, I also followed reverse imports from a changed module already
in the closure. This matters for `triggered_snapshot_queue.py`, which cannot be
present in an older runtime record but is imported directly by the changed
snapshot and observation modules.

## All 39 branch verdicts

Hashes are unambiguous 12-character abbreviations. `Base` is the merge base
with current master, not a guessed branch-cut date. `Roll` means at least one
changed file is in, or becomes part of, a protected capture-loop import
closure. Conflict classes are expanded in the next section.

| Branch under `origin/codex/` | Tip | Base | Current merge | Roll | Verdict and disposition |
| --- | --- | --- | --- | --- | --- |
| `live-canary-bot` | `10ad54f55fd4` | `32ecb337e2bd` | conflict C2 | yes | **NEVER.** Named exclusion; research canary requires a fresh explicit operator instruction and audit. |
| `workstation-1000-information-gap-audit-2026-08-19a` | `f032bf4eef0e` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a`; it is an exact ancestor of that retained cumulative research stack. |
| `workstation-bootstrap-rehearsal-2026-07-23` | `b6aa1c111c75` | `00032eeafaea` | clean | no | **UNKNOWN.** Report-only diff, but its report has never landed on master; retain pending archival decision. |
| `workstation-build-base-retrain-step-2026-08-26a` | `71d18318cfcc` | `73d53cde722b` | clean | yes | **SUPERSEDED** by the newer `-09-12a` lane; its PIT seam survives separately in `-09-01a`. |
| `workstation-build-pit-forecast-corpus-2026-08-31a` | `f2dbc71e26ce` | `b7345ab2e6b0` | conflict C1 | yes | **SUPERSEDED** by the second and third commits of `-09-01a`, which carry the corpus implementation and add the missing binding. |
| `workstation-build-the-first-retrain-2026-09-12a` | `b7ee084cd41c` | `4f9bf149cbec` | conflict C1 | yes | **MERGE after refresh.** Owns the current explicit-only, six-gate, fleet-atomic retrain lane; current evidence remains 97/97 blocked. |
| `workstation-consolidate-merge-queue-2026-09-01a` | `450f03c53fad` | `b13b28518a53` | conflict C1 | yes | **MERGE in its own slot after refresh and Release #1 review.** Preserve PIT corpus commits `9cb708c6` and seam `5ae82294`; separately audit the 00:05 retention commit before adoption. |
| `workstation-continuation-candidate-2026-08-12a` | `1e525a02dfce` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-detect-win-power-2026-09-04a` | `933de9336b31` | `9d65a21acdb4` | conflict C1 | yes | **MERGE after refresh.** Needed to recompute reservation power at candidate freeze; clears none of the 97 input blockers. |
| `workstation-fix-the-watcher-stretch-2026-09-14a` | `4e0498224df3` | `eeb214c40b1d` | clean | yes | **MERGE last.** Bounded watcher/snapshot handoff and active-window maker gap semantics; no retrain blocker cleared. |
| `workstation-floor-informativeness-gate-2026-08-13a` | `55f5f5ddda9e` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-floor-informativeness-replication-2026-08-14a` | `703075f7e3a9` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-forecast-residual-anchor-2026-08-18a` | `ed0f5ffe0ae5` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-gate-cost-diagnosis-2026-08-17a` | `b5be028a4b1f` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-gate-harness-2026-08-09a` | `b9c62ead999b` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-hardening-lock-blocker-fixes-2026-07-24` | `1d9d58d37420` | `097562272312` | conflict C3 | yes | **SUPERSEDED.** Current master owns the lock/release fixes; the branch also embeds the excluded old research/release rewrite and must not be merged wholesale. |
| `workstation-is-the-bias-conditional-2026-08-24a` | `fd1a0bb70c8c` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (immediate ancestor). |
| `workstation-lock-blocker-fixes-2026-07-24` | `06a38069bdd0` | `097562272312` | clean | no | **UNKNOWN.** Its sole report is not in master history; the underlying fix is in master, but deleting the ref would discard the report. |
| `workstation-lock-window-sweep-2026-08-02a` | `b28efa541f61` | `697fe0d08e9e` | clean | no | **MERGE after Release #1 review.** Small fail-closed empty-manifest diagnostic fix plus test; clears no retrain blocker. |
| `workstation-make-mm-days-countable-2026-09-11a` | `14dd1e849234` | `d259cc2c9a83` | clean | yes | **MERGE first.** Current MM critical path; no retrain blocker cleared. |
| `workstation-make-the-first-retrain-count-2026-08-25a` | `92bb53477967` | `b125e2df013c` | clean | yes | **SUPERSEDED** functionally by `-09-12a`; retain until its 14 unique research reports are archived. |
| `workstation-measure-blindness-causally-2026-08-22a` | `ababbfd15153` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-mm-gate-2026-07-28b` | `34fda2a4010d` | `5c004c4554d8` | clean | no | **SUPERSEDED** by merged `-09-10a` and held `-09-11a`, which own the current decision/countability contracts. |
| `workstation-pit-simplex-2026-07-24` | `8252209ba6ec` | `097562272312` | clean | no | **SUPERSEDED** by the PIT-simplex fix now on master (`4041d358`) and current trust tests. |
| `workstation-prove-1000-blindness-2026-08-20a` | `6a068783a8ba` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-prove-repair-wu-parity-2026-08-30a` | `6990913a9b5f` | `b804513ed2dd` | clean | no | **UNKNOWN.** Evidence-only branch whose report is absent from master; preserve until archived or explicitly rejected. |
| `workstation-release-one-blockers-2026-07-29` | `0beb40b8c7e4` | `51d53b69ae44` | clean | yes | **SUPERSEDED** by master commit `447dda75` and later release work; its report is already in master history. |
| `workstation-release-one-rehearsal-2026-07-29` | `e13851ccf447` | `28d0dfb433e6` | clean | no | **UNKNOWN.** Historical rehearsal report is absent from master and Release #1 review is still pending. |
| `workstation-repair-d1-anchor-2026-08-15a` | `8377873e44e3` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |
| `workstation-research-2026-07-22` | `423eaa59beee` | `99c0616419ce` | conflict C4 | yes | **NEVER for this plan.** Named exclusion: broad release/PIT rewrite; no proposal before Release #1 completes and receives a fresh audit. |
| `workstation-scope-forecast-archive-extension-2026-08-28a` | `39ab20476e4a` | `3eb4305a3de2` | clean | no | **UNKNOWN.** Its feasibility report is still relevant to the PIT repair but is absent from master. |
| `workstation-second-clock-bootstrap-2026-07-30f-keystone` | `eadcd4b1f74c` | `a29590d62f8f` | clean | yes | **SUPERSEDED** by master (`ea0167a7`, `d56e87cb`, and later release code); both reports are in master history. |
| `workstation-size-forecast-lookahead-2026-08-29a` | `9b8fde665aa9` | `027f65bfde2b` | clean | no | **UNKNOWN.** Measurement report is required context for the PIT choice but has never landed on master. |
| `workstation-skill-gap-2026-07-25b` | `e91255785724` | `008a0b82a6f7` | conflict C5 | yes | **SUPERSEDED** by master and later ownership/schema ratchets; its report landed as `c7aba44b`. |
| `workstation-spec-contract-repair-2026-08-21a` | `371832439485` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor); it specifies a repair but does not implement the current parity fix. |
| `workstation-strict-parity-2026-07-29` | `0591e4c228c1` | `5954da1b2129` | clean | yes | **SUPERSEDED** by master release fixes and the newer `-09-03a`/`-09-12a` parity contract; archive its unique report before deletion. |
| `workstation-train-serve-parity-gate-2026-09-03a` | `af32501b9a6c` | `9275a41ea6d7` | conflict C1 | yes | **SUPERSEDED** by `-09-12a`, whose report says this implementation, fixture, and tests were carried forward. It detects but does not repair the one parity blocker. |
| `workstation-who-breaks-floor-2026-07-27g` | `58ab0dd39293` | `873d5f66ff6d` | conflict C6 | yes | **UNKNOWN.** The ref actually carries a large warm-tier/storage stack, not a floor diagnosis; it needs its own storage-contract audit. |
| `workstation-why-is-the-morning-cool-2026-08-23a` | `b893857ebb7a` | `b125e2df013c` | clean | yes | **SUPERSEDED** by `-08-25a` (ancestor). |

## What changed underneath the conflicted branches

| Class | Affected refs | Exact current conflict and cause |
| --- | --- | --- |
| C1 | `-08-31a`, `-09-01a`, `-09-03a`, `-09-04a`, `-09-12a` | `src/weather/schema_registry_recent_data.py`; master added the live maker scoring-input binding in `f1dc00ec` after each base. Preserve both additive registrations during refresh. |
| C2 | `live-canary-bot` | `tests/operations/test_nightly_retrain.py`; the lock-blocker fix and its revert/reapply sequence (`09756227`, `50b8021c`, `4041d358`) changed the nightly contract underneath the canary tests. |
| C3 | `hardening-lock-blocker-fixes` | Eleven conflicts in the nightly runbook, module map, generated backlog, replay backtest, `io.py`, release serving, and five test owners. Its base predates 275 master commits and the current package/release boundaries. |
| C4 | `workstation-research-2026-07-22` | Eighteen conflicts across the same release/PIT/IO surface plus pooled feature assembly, daily reporting, promotion corpus, and tests. Its base predates 285 master commits; textual repair would still violate the named release/PIT exclusion. |
| C5 | `workstation-skill-gap-2026-07-25b` | Module ownership, `schema_registry_recent_data.py`, and module-size tests; master later landed the ownership ratchets in `1623c76f`/`c6319fa1` plus many schema additions. |
| C6 | `workstation-who-breaks-floor-2026-07-27g` | Generated `active-backlog.md` and Item 325; master changed them in `ede251c8`, `7b5d3e0f`, and `ce1f3854`. The source diff is a separate 6,500-line storage feature and must not be resolved as a two-file docs conflict. |

“Clean” in the inventory means only that Git can synthesize a tree. It is not
semantic acceptance. In particular, the cumulative `b125e2df` research stack
merges clean because master did not touch most of its private modules; that is
not a reason to merge rejected candidates or old schema registrations.

## The 97-blocker map

| Gate | Retained blockers | Held implementation owner | What it actually clears today | Work with no gate-clearing branch |
| --- | ---: | --- | ---: | --- |
| `forecast_archive_coverage` | 36 | `-09-01a` carries the `-08-31a` immutable corpus builder and verifier. | **0/36** | Run the authorized feasibility probe; collect and verify the real 2021–2025 May 10–Aug 31 matrix; bind every source manifest, coverage cell, and feature record. The existing archive still ends June 30. |
| `point_in_time_forecast_binding` | 24 | `-09-01a` commit `5ae82294` adds manifest-file, preflight, exact-selection, and feature-record bindings. | **0/24** | Materialize the non-stitched issue-aware corpus and port the seam into refreshed `-09-12a`; prove the selected bytes are exactly those used by the fit. |
| `class_support` | 12 | `-09-12a` carries the native-unit candidate fitter and contiguous-support contract; older design is in `-08-25a`. | **0/12** | Build the serving-compatible reader for declared support and supply real per-market evidence containing estimator classes and warm-tail requirements without weakening the trusted floor. |
| `candidate_specific_calibration` | 12 | `-09-12a` can emit blocked-OOF candidate calibration and refuses inherited bytes. | **0/12** | Supply the predeclared plan, execute the later authorized fit, and bind changed candidate bytes, calibration, and exact fleet fit receipt. No branch can manufacture this evidence before the fit. |
| `artifact_regime_boundary` | 12 | `-09-12a` enforces the gate; `-09-01a` can bind the forecast component. | **0/12** | Rebuild the complete feature-record corpus under one code identity and one exact source-artifact graph. The PIT forecast corpus alone is not the complete artifact regime. |
| `train_serve_feature_parity` | 1 | `-09-03a` implements the detector and is carried into `-09-12a`. | **0/1** | Repair the 220 retained findings and produce one exact-PASS 12-market, 221-field report. No held branch implements that repair. |

Therefore the forecast/PIT pair has **partial software** but no current
gate-clearing evidence. The other four gates have an enforcement or fitting
surface but **no held branch that supplies their missing real evidence**.

### The seam that must survive refresh

The four commits on `-09-01a` are:

1. `a5247509` — older all-market base lane;
2. `9cb708c6` — PIT training corpus;
3. `5ae82294` — bind the base fleet to that exact PIT corpus; and
4. `450f03c5` — taker counterfactual retention at the existing 00:05 roll.

`-09-12a` correctly supersedes commit 1, but it deliberately excluded commits
2–3. A refresh must not pick one whole implementation and discard the other.
The integrated lane needs all of these properties simultaneously:

- `-09-12a`'s explicit/manual invocation, live-registry projection, six
  independent gates, fleet-atomic candidate publication, release-path
  unreachability, and current support/calibration contracts;
- `-09-01a`'s verified PIT corpus manifest file hash, corpus preflight hash,
  exact market/date/cutoff selection hash, feature-record selection hash, and
  no ambient stitched fallback; and
- `-08-31a`'s immutable plan, request/raw/issue hashes, availability-at-cutoff
  proof, complete coverage matrix, and training-only content-addressed root.

The semantic acceptance test is not “the merge conflict is gone.” Mutating one
PIT row, coverage cell, raw-response hash, selection key, or feature-record
binding must make refreshed `-09-12a` refuse before fit. Conversely, the fully
repaired synthetic fixture must still reach exact PASS.

There is a second seam: the PIT builder's fixed-lead Previous Runs contract is
not the current stitched serving feature contract. Merging it does not prove
train/serve parity. The serving resolver must either adopt the same admissible
issue contract through a separately reviewed release-bound change or the
affected fields must be explicitly excluded with matched train/serve
missingness. No compatibility fallback to `forecast_daily.csv` is acceptable.

## Roll-safety audit

The six MERGE branches have these exact protected-closure intersections:

| Branch | Capture-roll-sensitive files | Worker-only or roll-free notes |
| --- | --- | --- |
| `-08-02a` lock-window sweep | none | `point_in_time_evaluation.py` is absent from all three retained capture closures. Its old report used a broader calibration-path proxy. |
| `-09-01a` consolidated stack | `model_distribution.py`, `model_features.py`, `schema_registry_data.py`, `schema_registry_recent_data.py`, `forecast_history.py` | The base/PIT/taker orchestration modules are not capture-loaded. This measured five-file set corrects the older 16-file glob-style count for capture-roll purposes. |
| `-09-04a` detect power | `schema_registry_recent_data.py` | Reporting code and fixture are roll-free. |
| `-09-11a` MM countability | `schema_registry_data.py` | MM modules and PowerShell registration are not capture-loaded; activating the new producer is a separate stateful action. |
| `-09-12a` first retrain | `schema_registry_data.py`, `schema_registry_recent_data.py` | Trainer, candidate fitter, and parity reporter are not capture-loaded. |
| `-09-14a` watcher stretch | `snapshot_capture_batch.py`, `snapshot_tracker.py`, new reverse-imported `triggered_snapshot_queue.py`, `observation_trigger.py` | Maker-run files are worker-sensitive but capture-roll-free; docs/tests are roll-free. |

Every branch marked `yes` in the 39-row table intersects the same measured
closure by at least one file. Every branch marked `no` has an empty
intersection. Per the handoff, any `yes` branch is merged only at 01:00–04:00
and all three capture loops are deliberately re-adopted and verified.

## Safe merge and refresh order

This plan begins **only after Release #1 has completed and been reviewed**.
The roll-free lock-window diagnostic branch can be refreshed, tested, and
merged outside the capture roll sequence after that review.

### Quiet window 1 — MM critical path

1. Re-fetch and confirm `-09-11a` still merges clean.
2. Re-run its countability, schema, architecture, and PowerShell parser checks.
3. Merge `-09-11a`, then roll and verify all three capture loops.
4. Do not activate the new MM execution producer merely because code merged.

This goes first because it is the current MM critical path and lets every later
branch refresh once against its `schema_registry_data.py` addition.

### Quiet window 2 — consolidated PIT/seam stack, alone

1. Refresh `-09-01a` onto the post-`-09-11a` master, preserving maker/MM schema
   registrations and resolving README changes intentionally.
2. Review all four commits separately. In particular, verify the exact roots,
   age rule, hash walk, and dry-run/disable behavior of `450f03c5` before the
   existing 00:05 taker roll can adopt it.
3. Satisfy the already-recorded prerequisite to dispose of the approved large
   counterfactual tape before enabling a retention pass that would hash it.
4. Run the PIT corpus, base-retrain seam, taker retention, schema, and
   architecture suites. Merge in its own 01:00–04:00 slot and roll all three
   capture loops.

No provider build occurs in this merge window. Corpus execution remains a
separately authorized, bounded operation after its exact probe passes.

### Quiet window 3 — power tool

Refresh `-09-04a` against the now-expanded recent schema registry, run its
fixture and schema tests, merge, and roll all three loops. It may be deferred
until closer to candidate freeze, but it must land before reservation sizing;
deferring it must not block the PIT/retrain repair.

### Quiet window 4 — current retrain lane plus the PIT seam

1. Merge current master into published `-09-12a`; do not rewrite its history.
2. Resolve its six-file overlap with `-09-01a` as an integration change, not an
   ours/theirs selection. The older base lane is superseded; the PIT corpus and
   `5ae82294` binding are retained.
3. Preserve `-09-12a`'s explicit-only/no-release/no-scheduler boundary. Do not
   reintroduce the older nightly wiring or inactive-release construction.
4. Re-run the full base/PIT/parity/schema/import slice, the mutation tests
   listed above, and the retained-evidence preflight. Expected truth remains
   BLOCK until real evidence exists; a surprising PASS is a stop condition.
5. Merge and roll all three capture loops. Do not execute a fit.

### Quiet window 5 — watcher topology last

Refresh `-09-14a` after the preceding merges. Its only intentional overlap
with `-09-11a` is README and `OPERATIONS_DESIGN.md`; preserve both contracts.
There is no owned source overlap. Re-run watcher/snapshot/maker tests, merge,
roll all three loops, verify queue counts and iteration latency, and soak before
any separately authorized producer activation.

This is realistically **five quiet windows**. It can be reduced to four only
if the operator deliberately bundles the small `-09-04a` registry addition
with another already-stopped window after combined testing. The consolidated
stack and watcher-topology branch should not be bundled; each changes a
different operational failure boundary and deserves an observable adoption.

### Held-branch overlaps found now

Patch-owned overlaps, after stripping inherited master drift, are:

- `-09-01a` ↔ `-09-04a`: `schema_registry_recent_data.py`;
- `-09-01a` ↔ `-09-11a`: README and `schema_registry_data.py`;
- `-09-01a` ↔ `-09-12a`: nightly runbook, candidate fitter,
  `base_retrain.py`, both schema registries, and base-retrain tests;
- `-09-01a` ↔ `-09-14a`: README only;
- `-09-04a` ↔ `-09-12a`: `schema_registry_recent_data.py`;
- `-09-11a` ↔ `-09-12a`: `schema_registry_data.py`; and
- `-09-11a` ↔ `-09-14a`: README and `OPERATIONS_DESIGN.md` only.

Raw tip-to-tip merge-tree checks show extra schema conflicts because the tips
were cut from different master generations. Sequential refreshes remove that
inherited ancestry noise; the overlap list above is the actual patch ownership
that must be reconciled.

## Deletion recommendations — recommendation only

No remote ref was deleted.

### Safe once the retained successor remains

The following thirteen branches are exact ancestors of `-08-25a`; deleting
their refs loses no commit while that successor remains:

- `-08-09a`, `-08-12a`, `-08-13a`, `-08-14a`, `-08-15a`, `-08-17a`,
  `-08-18a`, `-08-19a`, `-08-20a`, `-08-21a`, `-08-22a`, `-08-23a`, and
  `-08-24a`.

### Delete after the named successor is integrated

- `-08-26a` after refreshed `-09-12a` is merged and verified;
- `-08-31a` after refreshed `-09-01a` is merged and its PIT corpus/seam commits
  are verified;
- `-09-03a` after refreshed `-09-12a` is merged and its parity implementation,
  fixture, and tests are confirmed present;
- `workstation-release-one-blockers-2026-07-29`,
  `workstation-second-clock-bootstrap-2026-07-30f-keystone`, and
  `workstation-skill-gap-2026-07-25b`, whose accepted code and reports are in
  master; and
- `workstation-mm-gate-2026-07-28b` and
  `workstation-pit-simplex-2026-07-24`, whose current successors are already on
  master.

### Archive before deletion

Do not yet delete `-08-25a`, `strict-parity`, or
`hardening-lock-blocker-fixes`. Their functional work is superseded, but they
still retain unique report files that are absent from master. First preserve
the accepted reports through a reviewed docs-only archival change, or record
an explicit operator decision that they are intentionally discarded.

There are **49** distinct `agent-report` paths introduced across the held
branches. Only four have ever appeared in `origin/master` history:

- `agent-report-2026-07-25-workstation-skill-gap.md`;
- `agent-report-2026-07-29-workstation-hash-keystone.md`;
- `agent-report-2026-07-29-workstation-release-one-blockers.md`; and
- `agent-report-2026-07-30-workstation-second-clock.md`.

That is why the REPORT-ONLY count is zero. The report-only diffs classified
UNKNOWN do not meet the handoff's definition “report already landed on
master,” and deleting them now would erase their only remote copy.

Do not delete either NEVER branch as part of backlog hygiene; their disposition
is a separate operator decision. Do not delete any UNKNOWN branch.

## What would falsify this plan

1. A fresh fetch producing a different unmerged `origin/codex/*` set or moving
   any tip invalidates the 39-row inventory and requires re-running it.
2. A current master merge-tree differing from the recorded 29 clean / 10
   conflicted split invalidates the conflict plan.
3. A retained capture status with a materially different loaded-module closure
   invalidates the roll table; use the newer recorded closure.
4. A real immutable PIT corpus with exact complete coverage and feature-row
   binding would reduce the first 60 blockers; a dry-run plan does not.
5. An exact-PASS full-fleet parity report would clear the parity blocker; the
   current detector branch alone does not.
6. A serving-compatible support reader, candidate-specific fit receipt, or
   unified-regime feature corpus on another ref would change the NO-branch
   findings for gates 3–5.
7. If the refreshed `-09-12a` synthetic PASS still succeeds after corrupting a
   PIT manifest, selection, raw hash, or feature-record binding, the seam is
   not repaired and the merge must stop.

## Commands and verification

Network use was limited to `git fetch --prune origin`. No provider or web data
endpoint was contacted. Git inspection used `merge-base`, `diff`, `log`,
`rev-list`, `cat-file`, ancestry checks, and non-checkout `merge-tree`.

No tests from held branches were rerun merely to make a confident verdict:
where current behavior depends on a future refresh, the plan requires those
tests at refresh time; where unique evidence is not preserved, the branch is
UNKNOWN rather than guessed safe to delete.

Final verification after a second fetch:

- `origin/master` remained `ea3a802de807d160fbfca59046771921b99b0654`;
- the unmerged `origin/codex/*` count remained 39;
- all 39 recorded tip and merge-base hashes matched their live refs;
- all 39 table rows accounted for exactly 6 MERGE, 24 SUPERSEDED, 0
  REPORT-ONLY, 2 NEVER, and 7 UNKNOWN verdicts;
- `git diff --check` passed; and
- the agent-docs audit passed (18 agent files, 622 Markdown files).

This report itself is documentation-only and capture-roll-free.
