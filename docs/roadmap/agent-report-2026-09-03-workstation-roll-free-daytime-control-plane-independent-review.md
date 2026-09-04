# Independent review: roll-free daytime control plane

**Mission:** `workstation-roll-free-daytime-control-plane-independent-review-2026-09-98a`

**Mission SHA-256:** `79cfc97e22177801706552d0523a62786925a3ffa65fd13d08616427b5cca504`

**Verdict:** `PASS_REVIEWED_REPAIRED`

**Implementation commit:** `1a3f94d1fd4d8e16f618411670418eb009f8e319`

**Implementation tree:** `93197c8f83e045695b347e91fad95ae94acf313b`

The frozen candidate was not safe to accept unchanged. The review demonstrated
three mutation-authority defects and repaired them with adversarial tests first:

1. the 09:00-18:00 lane used a first-come shared mutex, allowing a merge to
   acquire before or during the 09:30-11:55 Stage-A reservation and delay the
   sole scheduled chain;
2. the wrapper reused one pre-verdict `$h`, so a delayed 17:59 classification
   could cross 18:00 and retain stale mutation authority; and
3. exit code 0 alone set `$rollFree`, so missing, malformed, stale, incomplete,
   or identity-mismatched JSON could receive daytime mutation authority.

The repair reserves 09:00-11:55 exclusively for Stage A and opens the
control-plane candidate lane only from 11:55-18:00. It validates fresh
machine-readable verdict evidence against the exact tip, synchronized base,
invocation interval, complete required closures, optional active execution-tape
closure, allowed problem shape, and nonrolling file rows. It also requires the
classifier to be a stable regular file matching the checked-out Git blob,
freezes the full base identity, and rechecks base and classifier bytes before
the first Git mutation. The wrapper recomputes policy immediately after the
verdict and immediately before `git fetch`, while retaining the same OS lease
through all later mutation, reporting, recovery, documentation, and publication
steps.

## Frozen identity and P0

All P0 checks passed before the isolated worktree was created.

| Proof | Result |
| --- | --- |
| Canonical origin | `https://github.com/michaelbooth1/weather.git` |
| Base/sole parent | `c932b54f8747df5cdefc4cc42f8454b6797f09ae`; tree `6df5bac16d8c780c35b4601941eaca1137ea7070` |
| Source | `f2601198715163c8991d3065dc5622708e3b01db`; tree `5c45123b524a9e1a145d1b5ac18124ce148f9bd1`; sole parent exact |
| PR | Public GitHub API reproduced open draft PR #13, base `master`, exact source head |
| CI | Public GitHub API reproduced CI run `33768288205`, workflow run `570`, completed `success`, exact source SHA |
| Collision checks | Result local/cached/remote refs absent; result path absent; source had zero worktrees |
| Cleanliness | Root/source state clean before creation; isolated result worktree clean at source tip |
| Workstation admission | Assigned non-capture host `a740ee7dc03165b0c88094f8b313aa6676f0984b30737ec5bcd9f723709fe5dc` and principal `899c8218f19e948baf648733e34ab9e3301c154300a30477816ed749c3c8507b`; mutex available; no poison marker or recognized heavy process |

The source object was initially absent. The mission's sole network exception was
used once to fetch the exact public source ref with credential helpers and
prompts disabled. Public unauthenticated GitHub API reads reproduced PR and CI
identity. No authenticated Git action occurred.

## Falsifier results

| # | Result and evidence |
| --- | --- |
| 1 | **Defect repaired.** Daytime authority now requires exact exit 0 plus validated JSON. Nonzero, null, stale, incomplete, dangerous-problem, rolling-file, wrong-tip, wrong-base, and missing active execution-tape closure cases all return false in an executable Windows test. Invalid evidence follows the conservative sensitive/undecidable path. |
| 2 | **Pass after repair.** Lease acquisition precedes verdict invocation. The same lease is released only by the outer finalizer after all terminal paths. Tip equality is rechecked after fetch; the full base SHA and classifier SHA-256 are frozen and rechecked before mutation; the classifier blob must equal `HEAD:scripts/ops/roll_verdict.ps1`. |
| 3 | **Defect repaired.** Policy is recomputed after classification and directly before `git fetch`. Executable tests cover 00:30, 01:00, 04:00, 09:00, 11:55, and 18:00 transitions, including delayed sensitive and roll-free outcomes. |
| 4 | **Defect repaired.** The control-plane lane is unavailable from 09:00 through 11:54:59, so a new merge cannot win the mutex immediately before or during Stage A. A Stage-A overrun already holding the mutex still wins at 11:55. |
| 5 | **Pass.** `Enter-WeatherHeavyWorkloadLease` admits the switch only under `capture_colocated_v1`, exact workload `quiet_window_merge`, with no Stage-A or owner combination. Portable and workstation profiles reject the switch. |
| 6 | **Pass.** `-Force` can retain only its prior ordinary 00:30-09:00 behavior; it cannot admit a daytime undecidable tip. The literal 2026-08-23 owner exception remains exact, lineage-bound, and expired. |
| 7 | **Pass.** 18:00-00:30 returns no ordinary or roll-free policy. Sensitive/undecidable tips remain 01:00-04:00 unless the already documented exact owner exception applies. |
| 8 | **Pass.** The new lane is reachable only through the exact merge workload. The pytest/compileall/training/replay/collector surfaces are unchanged, and no production full-suite route was added. |
| 9 | **Defect repaired.** Path names and prose never set `$rollFree`; only exact validated output from the canonical, Git-blob-matched script does. |
| 10 | **Pass.** No retry, rollback, marker, report-collision, capture-recovery, documentation-transaction, or one-shot publication branch was weakened. New report fields are additive: `policy_window`, `mutation_policy_window`, verdict exit/evidence status, and classifier SHA-256. |
| 11 | **Pass.** The Windows job uses `fetch-depth: 0`, `lfs: false`, Windows PowerShell 5.1 AST parsing of every operations script, and executable focused contracts under ordinary failing command semantics. Source exact-head CI passed. |
| 12 | **Defect repaired.** Owning docs now distinguish the 11:55-18:00 roll-free integration lane from heavy-resource authority, reserve 09:00-11:55 for Stage A, and explicitly deny malformed evidence and arbitrary workloads. |

## Verification

Every Python, pytest, and compileall process ran serially beneath
`scripts/ops/workstation_heavy.ps1`, using the assigned
`workstation_offline_v1` profile and
`C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe`.
The two light Python repository checks ran serially as subprocesses of a
temporary one-test pytest harness under that same wrapper and kill-on-close Job;
the harness was removed immediately afterward.

| Command/argument vector | Result |
| --- | --- |
| Test-first explicit four-node vector against the frozen source behavior | Expected red: **4 failed, 65 deselected**. It demonstrated Stage-A admission, stale clock, missing evidence validation, and missing script integration. |
| `-m pytest -q tests/operations/test_quiet_window_merge_script.py::test_quiet_merge_serializes_daytime_classification_before_mutation tests/operations/test_workload_admission_script.py::test_policy_admits_only_explicit_roll_free_control_plane_hours tests/operations/test_workload_admission_script.py::test_quiet_merge_recomputes_every_delayed_classification_boundary tests/operations/test_workload_admission_script.py::test_roll_free_machine_evidence_fails_closed_on_every_identity_gap` | **4 passed** in 0.90 s on the final implementation tree. |
| `-m pytest -q tests/operations/test_quiet_window_merge_script.py tests/operations/test_workload_admission_script.py` | **54 passed, 15 skipped** in 8.17 s. Skips are the files' declared platform/environment cases. |
| `-m pytest -q` | Complete workstation suite executed: **4210 passed, 18 skipped, 17 failed, 862 subtests passed** in 506.85 s. The failures are reproduced baseline Windows path defects in unchanged Python code. |
| Exact 17 failed nodes with `--basetemp=C:\t98a` | **5 passed, 12 failed** in 4.94 s. The case-only path failures and one length-sensitive case cleared; the remaining 12 are the known experiment-executor `MAX_PATH` defect already assigned to draft PR #11. The mission temp was removed. |
| `-m compileall -q app src tests` | **Pass**. |
| Windows PowerShell AST parse over every base-to-implementation changed `*.ps1` | **Pass, 2/2**: `quiet_window_merge.ps1`, `workload_admission.ps1`. |
| `-m weather.operations.agent_docs_audit` | **Pass:** 18 agent files, 828 Markdown files. |
| `-m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check` | **Pass:** generated report matches sources. |
| `git diff --check` and staged diff check | **Pass**. |

The 17 full-suite failures are reproduced, not introduced: the base-to-result
delta changes no `src/` or application Python file, and none of the failing test
files changed. Four failures were case-only comparisons between
`pytest-of-Michael` and `pytest-of-michael`; the others were Windows path-length
failures. The short-base rerun left exactly the 12 experiment-executor failures
whose code is unchanged here and whose `MAX_PATH` repair is already tracked by
PR #11. They do not falsify this control-plane result and were not folded into
this mission.

## Roll classification boundary

No production roll verdict was requested or run. This workstation has no
authoritative live closure evidence, so the overall dynamic verdict is
`UNDECIDABLE`. No changed-path or prose inference substitutes for the canonical
production command.

For reviewer routing only, every base-to-implementation changed path is outside
the canonical importable candidate set: `.github/workflows/ci.yml`, the five
changed `docs/operations/*.md` files, `docs/roadmap/ROADMAP.md`,
`docs/roadmap/active-backlog.md`, Item 331, `scripts/ops/AGENTS.md`, both changed
PowerShell scripts, and both changed `tests/operations/*.py` files. Their
structural closure entry is `none`; this is not a production roll verdict.
The report and JSON handback are likewise documentation/evidence files with
structural closure entry `none`.

## Prohibited-action audit

No production host, Scheduler mutation, credential store, provider, exchange,
capture runtime, merge, release, model, outcome, or live-trading action was
used. No branch was pushed and no PR was opened or edited. The only network
actions were the mission-authorized credential-disabled public source fetch and
unauthenticated public GitHub identity reads during P0. The root checkout and
all existing worktrees were left unchanged.

The final receipt uses an external self-binding rule because a file cannot
contain the hash of the commit/tree that contains its own bytes. Its final
commit must have implementation commit
`1a3f94d1fd4d8e16f618411670418eb009f8e319` as its sole parent, change only the
report and receipt, and contain the receipt/report blobs and SHA-256 values
verified after commit. The complete bundle and isolated strict-fsck proof bind
that resulting final tip externally.
