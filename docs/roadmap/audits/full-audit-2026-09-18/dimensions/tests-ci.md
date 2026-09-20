# Audit dimension: Tests and CI (`tests-ci`)

Audit date: 2026-09-18. Auditor: one read-only sub-auditor in the full-project audit.
Host: the live 16 GB production capture host, inside its protected window.
**No test, Python, PowerShell script, or CLI was executed.** Everything below comes from
reading files (Read/Grep/Glob) plus a handful of whitelisted `git log` / `git show` /
`git ls-files` / `git ls-tree` calls. Nothing in the project was modified.

Overall grade: **C**. The Python test suite is large, hermetic and genuinely behavioural,
and the incidents that hurt production on the Python side have real regression tests. But
the layer where production actually fails - 73 PowerShell ops scripts, Windows Job/ACL/
Scheduler semantics, the capture-host qualification path - is either skipped on CI,
"tested" by substring matching on source text, or gated behind a host suite that cannot
currently start or pass.

---

## 1. Scope covered and method

Read in full:
`pytest.ini`, `pyproject.toml`, `requirements.txt`, `sitecustomize.py`,
`.github/workflows/ci.yml`, `host-load-hook.yml`, `retrain.yml`,
`.github/pull_request_template.md`, `tests/AGENTS.md`, `docs/development.md`,
`scripts/ops/bounded_worktree_test_suite.ps1` (791 lines),
`docs/operations/STATE_OF_PLAY.md`, `config/international_live_execution_host.json`,
`tests/operations/test_bounded_worktree_test_suite_script.py`,
`tests/operations/test_settlement_backfill_scripts.py`,
`tests/operations/test_settlement_hole_check.py`,
`tests/operations/test_module_size_audit.py`,
`tests/operations/test_memory_commit_guard_script.py`.

Read in part (targeted ranges):
`tests/market/test_market_day_labels.py`, `tests/operations/test_workload_admission_script.py`,
`tests/operations/test_status_script.py`, `tests/operations/test_host_task_wrappers.py`,
`tests/operations/test_integration_attempt_scripts.py`,
`tests/operations/test_cold_snapshot_compression_wrapper.py`,
`tests/operations/test_production_baseline_reconciliation.py`,
`tests/operations/test_import_architecture.py`, `tests/operations/test_supervisor.py`,
`tests/collection/test_snapshot_capture_batch.py`,
`tests/calibration/test_lock_blocker_end_to_end.py`,
`tests/reporting/test_data_layer_audit.py`,
`scripts/ops/workload_admission.ps1` (lease function), `scripts/ops/settlement_backfill_one.ps1`,
`scripts/ops/AGENTS.md`, `docs/operations/HOST_LOAD_POLICY.md`,
`docs/operations/ESTABLISHED_FINDINGS.md` (sections 8k-8s),
`docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md`,
`docs/roadmap/items/item-329-*.md`, `docs/roadmap/items/item-325-*.md`,
`src/weather/calibration/feature_model.py` (CLI block).

Git (read-only): history of `.github/workflows`, of `bounded_worktree_test_suite.ps1`, of
`test_workload_admission_script.py`; first-parent master history since 2026-08-25; commits
`bcb49506`, `654bdc5eb`, `f60dbb9e6`; the two workflow files that exist only on the unmerged
branch `codex/reliability-fixture-host-20260913` (tip `aaa7f2de1`).

Inventories were taken with Grep over `tests/` only (never the repo root, never `data/`).

### Size of the suite (verified by Grep/ls-files)

- 422 tracked files under `tests/`; 403 files contain test functions; **~4,508 `def test_`
  definitions** before parametrisation.
- Project-recorded run sizes: 4,402-4,539 tests in 17-18 chunks on the production host on
  2026-08-14 (`ESTABLISHED_FINDINGS.md:2230-2320`); "full CI passed 4,644 tests and 921
  subtests (**321 skips**)" in September (`item-325-*.md:461-463`).
- No `conftest.py` anywhere (Glob `tests/**/conftest.py` = none; `git ls-files` = none).
- Test extras are `pytest==9.0.3` only (`pyproject.toml:25-27`): no pytest-timeout,
  pytest-cov, xdist, or socket-blocking plugin.

---

## 2. What CI actually runs

`.github/workflows/ci.yml` (52 lines), triggers: every `pull_request`, and `push` to `master`.

| Aspect | Value | Cite |
| --- | --- | --- |
| OS | `ubuntu-latest` only | `ci.yml:17` |
| Python | 3.11, pip cache | `ci.yml:30-34` |
| Timeout | 30 minutes | `ci.yml:18` |
| LFS | disabled (model `.pkl` files are pointers; tests stub them) | `ci.yml:22-28` |
| History | `fetch-depth: 0` (tests inspect historical commits) | `ci.yml:27`, commit `3ff0e69cc` |
| Steps, in order | `compileall` -> `agent_docs_audit` -> `roadmap_backlog --fail-on-lint --check` -> `pytest -q` | `ci.yml:41-51` |
| Subset | none - the whole `tests/` tree (`pytest.ini:4`) | |
| Static analysis | none (no ruff/flake8/mypy/PSScriptAnalyzer/coverage; no config files tracked) | `git ls-files` check |

`host-load-hook.yml`: path-filtered to the Codex hook and its test; the **only** workflow on
master with a `windows-latest` leg; runs one test file with `--noconftest` plus the docs audit
(`host-load-hook.yml:24-44`).

`retrain.yml`: schedule commented out 2026-07-29; `workflow_dispatch` only (section 8 below).

Duration: I could not observe CI run times (no network). On the production host in mid-August
the full suite took **8-9 minutes** with peak commit 36.59% (`ESTABLISHED_FINDINGS.md:2230,
2252, 2274, 2310-2318`). Current duration is unknown; `item-329-*.md:23-26` says that on
2026-09-13 "the host suite was still running with known failed chunks" when the 03:25
follow-through deadline passed.

### What CI cannot see

1. **Any PowerShell.** No step parses or executes a `.ps1`. All 73 files under `scripts/ops`
   reach CI only as text that Python tests open and substring-match.
2. **Every Windows-only test.** Skip inventory (Grep over `tests/`):
   - 119 pytest skip sites in 45 files (`skipif` / `pytest.skip(`), plus 13
     `unittest.skipUnless` in `test_long_job_guard.py` and `test_supervisor.py`, plus 2
     `skipTest`.
   - **Zero `xfail`. Zero unconditional `skip`.** Every skip is conditional, almost all on
     `os.name != "nt"` (or "PowerShell/Git present", "symlink creation available",
     "rclone installed", "live SDK extra installed").
   - 5 whole modules are Windows-only via `pytestmark`
     (`test_cold_snapshot_compression_wrapper.py:26`, `test_production_cold_archive_wrapper.py:28`,
     `test_replay_cache_compression_wrapper.py:26`, `test_storage_recovery_inventory_wrapper.py:26`,
     `test_storage_recovery_night_wrapper.py:18`).
   - Critical paths inside the skipped set: capture-supervisor handle-scoped termination
     (`test_supervisor.py:1234-1328`), Job Object memory limit and lifetime accounting
     (`test_long_job_guard.py:363-537`), heavy-workload lease exclusivity
     (`test_workload_admission_script.py:142-145`), the AST operator-binding ratchet
     (`test_integration_attempt_scripts.py:1467-1521`, 13 of 73 scripts), every wrapper
     launch/teardown test, the bounded-suite runner's only executing test
     (`test_bounded_worktree_test_suite_script.py:140`).
   - Project's own number: **321 skips** on the full Linux run (`item-325-*.md:462-463`).
3. Scheduled tasks, S4U principals, ACLs, NTFS sharing modes, the real `data/` tree, LFS model
   bytes, the live SDK extra (`test_polymarket_sdk_contract.py:40-43`).

`docs/development.md:28-33` states this design openly: Windows-executing tests "carry precise
non-Windows skips ... executable Windows coverage remains part of the admitted
production-host bounded suite." The weakness is therefore not hidden - but see Finding 1:
that host suite is currently unattainable, so for master the Windows population executes
nowhere automatically.

A `windows-qualification.yml` and a `settlement-audit-qualification.yml` exist **only on the
unmerged branch** `codex/reliability-fixture-host-20260913` (`git log --all` shows commits
`a2ea4e3e2..aaa7f2de1`, none on master). Even there, the Windows job runs 14 named files,
not the suite, and its receipt declares `scope = 'native_launch_regressions_only'`,
`production_adoption_authorized = $false`.

---

## 3. Findings

### tests-ci-1 (HIGH) - The only gate that counts, the production-host bounded suite, cannot currently start and master cannot pass it

Basis: verified_in_code + doc_claimed + lead-auditor live state. Known status: known_open.

Two independent blockers:

**(a) Disk floor.** `bounded_worktree_test_suite.ps1:288-312` (`Assert-SuiteDiskHeadroom`)
throws unless every volume holding the repo, the worktree, the log and `%TEMP%` has
`53687091200` bytes (50 GiB) free. It is called at `:365`, before the time-window check, and
again before every chunk (`:608`). It was added 2026-08-25 (`f259e1b24`).
`STATE_OF_PLAY.md:24`: "Ordinary qualification retains its 50 GiB disk floor."
`item-325-*.md:7-8, 34-39, 50`: a compression campaign was run on 2026-09-13 expressly to
restore this "qualification reserve"; C: reached 67.6 GiB free at 02:16. The lead auditor's
live state (MORNING_BRIEFING, 2026-09-18 21:20) reports ~21 GB free and falling ~5.9 GB/day.
I did not read `data/` myself; if that figure is right the runner refuses at line 365 every
night until ~30 GB is recovered, and the reserve bought on 09-13 lasted under five days.

**(b) Host-bound fixtures on master.** Four native wrapper test modules build their fixture
host assignment as
`dedicated_capture_execution_host_id=assignment["active_portable_execution_host_id"]`
(`test_cold_snapshot_compression_wrapper.py:96-99`, `test_production_cold_archive_wrapper.py:162`,
`test_replay_cache_compression_wrapper.py:86`, `test_storage_recovery_inventory_wrapper.py:94`),
reading the **tracked** `config/international_live_execution_host.json`, whose portable id
(`a740ee7d...`) differs from the capture host id (`6a085bc0...`) (`:2,5`). The wrappers under
test reject any host whose id is not the fixture's "dedicated capture" id, so these modules
can pass only on the one physical workstation. The project records exactly this:
"The ensuing full host suite then exposed disposable test fixtures that assumed the portable
PC's identity, plus a launcher fixture using obsolete seal tokens" (`item-329-*.md:14-15`);
"its complete host suite has native fixture failures" (`STATE_OF_PLAY.md:35`). The repair
(`f60dbb9e6`, `current_execution_host_id()`) exists only on the unmerged PR 61 branch - and
that branch itself needs a host PASS to land.

Impact: every code change, including the reliability repair and anything that would fix the
settlement hole or disk growth, is queued behind a gate that is closed by the very
conditions (disk, failed fixtures) those changes are meant to address. Eleven qualification
attempts on 09-13/09-14 failed (lead context). Only roll-free docs merges are landing
(first-parent master log since 09-10 is docs/status merges only).

Recommendation: treat "restore a working qualification path" as the top reliability item.
Decide explicitly whether the 50 GiB floor is a hard rule for an 8-9 minute, <40%-commit job
whose own writes are JUnit XML; land the fixture repair through a reviewed exception or
cherry-pick rather than through the gate it blocks.

### tests-ci-2 (HIGH) - Master CI is Ubuntu-only: no PowerShell is parsed or run, ~321 tests skip, and the Windows workflows live on an unmerged branch

Basis: verified_in_code (+ doc_claimed for the 321). Known status: known_open.

Evidence: `ci.yml:17` (`ubuntu-latest`); `ci.yml:41-51` (no PowerShell step); skip inventory
in section 2; `item-325-*.md:462-463` ("321 skips"); `git log --all --
.github/workflows/windows-qualification.yml` lists only unmerged commits;
`docs/development.md:28-33`.

Impact: the production system is a Windows Scheduler/PowerShell/Job-object system. The
defects that have actually cost nights are Windows-runtime defects: PowerShell 5.1 strict
mode rejecting an empty Git-query array (`item-329-*.md:10-13`), `Start-Process` splitting an
argument at spaces in `settlement_backfill_one.ps1` (commit `654bdc5eb`), operator-as-
parameter binding in `integration_attempt_suite.ps1` (2026-08-20). CI was green through all
of them because it cannot see that layer. CI is also post-hoc for production: integration is
a local merge on the capture host followed by a push (`git-workflow.md:265` "Confirm ...
master CI passes" is a post-merge step).

Recommendation: merge a `windows-latest` job to master that runs the **whole** suite (the
August host runs show it is an 8-9 minute job), not a 14-file allowlist; add a cheap
PowerShell AST sweep over all 73 scripts (parse errors + the 63-operator binding check that
currently covers 13 files and only on Windows).

### tests-ci-3 (HIGH) - The PowerShell operations layer is "tested" mainly by substring assertions on source text; scripts on the critical path have zero executing tests

Basis: verified_in_code. Known status: known_open (recorded in the agent's private memory
`powershell-parse-ratchet-cannot-see-binding.md`; **not** recorded in any canonical repo doc I
could find - Grep of `docs/operations` for "substring"/"source-text" returned nothing).

Scale: **1,098** assertions of the form `assert "<literal>" in text` across 34 test files
(Grep, `tests/`). Largest: `test_status_script.py` 238, `test_quiet_window_merge_script.py`
155, `test_bounded_worktree_test_suite_script.py` 93, `test_boot_recovery_script.py` 78,
`test_host_task_wrappers.py` 64, `test_workload_admission_script.py` 61,
`test_suite_gated_quiet_merge_script.py` 52, `test_settlement_backfill_scripts.py` 41.
`scripts/ops/AGENTS.md:231` institutionalises it: "Validate PowerShell syntax without
executing scripts".

Traced instances (each opened end to end):

1. **`settlement_backfill_one.ps1` - the repair tool for the settlement hole.** Its only test
   file is `tests/operations/test_settlement_backfill_scripts.py` (70 lines, no `subprocess`
   import): every assertion is a substring check. The fix for the known production defect
   "backfill reports settled on a `none` row" is the function `Test-RowSettled`
   (`settlement_backfill_one.ps1:240-250`); the test for it is
   `assert "Test-RowSettled" in text` (`:32`). No test feeds it a `none` row. On 2026-09-04 a
   runtime bug in the same script (`Start-Process -ArgumentList @('-c', $registryCode)` split
   at spaces) was fixed in `654bdc5eb`; the "test" added was three more substring assertions
   (`:22-24`). `chain_recovery_run.ps1` is covered the same way (`:43-69`).
2. **`memory_commit_guard.ps1` - a process killer that runs every minute on the capture
   host.** `tests/operations/test_memory_commit_guard_script.py` has 7 tests; all 7 are
   `read_text` + substring/`index` checks; none executes anything. A test named
   `test_memory_guard_reaps_only_unowned_evidence_refresh_inside_protected_window` proves only
   that `"Stop-Process -Id $target.Id"` appears in a slice of the file (`:86-98`). The
   predicate that spares production workers (`Test-GovernedWeatherProcess`) is never invoked
   by any test (Grep: the script is referenced by no other test file).
3. **`bounded_worktree_test_suite.ps1` - the merge gate itself.** 93 substring assertions
   plus one Windows-only test that extracts `Write-SuiteLog` and checks timestamp culture
   (`test_bounded_worktree_test_suite_script.py:17-137, 140-218`). Chunking, failed-chunk
   aggregation, deadline kill, JUnit publication and the final identity re-check are never
   executed by a test.

Impact: these tests prove a string is present, not that the behaviour is right. They pass
while the script is broken (instance 1 demonstrates it) and they are edited in the same
commit as the code they "verify", so they add no independent signal. This is the layer where
the 2026-08/09 incidents concentrate.

Recommendation: for each scheduled-path script, extract functions by `FunctionDefinitionAst`
and execute them against constructed inputs (the project already does this in
`test_integration_attempt_scripts.py` and `test_bounded_worktree_test_suite_script.py:140`).
Start with `Test-RowSettled`, the memory guard's governed-process predicate, and the suite
runner's verdict logic. Reword `scripts/ops/AGENTS.md:231`.

### tests-ci-4 (MEDIUM) - Change-detector ratchets make refactoring expensive without protecting behaviour

Basis: verified_in_code. Known status: new.

- **Byte pin of a live script.** `test_production_baseline_reconciliation.py:882-899` asserts
  `sha256(scripts/ops/boot_recovery.ps1) == EXPECTED_BOOT_SHA256` (constant at `:21`) and that
  the file equals the blob at commit `3361520f` (2026-08-30). The test is not Windows-gated,
  so it runs on CI: **any** edit to `boot_recovery.ps1`, including a comment, fails until the
  constant is changed. `test_status_script.py:33-58` pins SHA-256 of six more files at
  historical commits.
- **One-day exceptions frozen into tests.** `test_workload_admission_script.py:209-212`
  requires the strings `OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823` and
  `ToString("yyyy-MM-dd") -cne "2026-08-23"` to remain in the lease script - dead code for an
  expired date is now un-removable.
- **Error-message prose asserted** (e.g. `test_status_script.py:102-103`
  `"old report cannot poison an unrelated later commit" in text`).
- **Tests patch the script under test by exact text replacement**
  (`test_cold_snapshot_compression_wrapper.py:80-93`, `replace_once` asserts `count == 1`), so
  they execute a modified copy and break on any reformatting of the patched lines.
- Reasonable ratchets, for contrast: AST import boundaries (`test_import_architecture.py`),
  module-size ownership (`test_module_size_audit.py:46-77`), schema registry. These did fail
  host suites by design (`ESTABLISHED_FINDINGS.md:2236-2242`) and the project added an
  `-IntegrationPreflight` mode to run them first (`bounded_worktree_test_suite.ps1:549-576`).

Impact: high friction for exactly the scripts that most need repair; agents satisfy the
ratchet by editing the constant/string alongside the code, so the ratchet records a change
rather than reviewing it. `tests/AGENTS.md:11-13` tells agents to "Preserve architecture
ratchets", which entrenches them.

Recommendation: keep AST/structural ratchets; retire byte pins and prose assertions once the
incident they commemorate is closed; replace dated-exception assertions with a test that the
exception is inert after its date.

### tests-ci-5 (MEDIUM) - No single environment runs every test; the host-global lease tests are skipped wherever agents run them and (by code trace) collide with the production runner

Basis: verified_in_code for the skip conditions; **inferred** for the collision (not
executed). Known status: new.

`test_lease_is_exclusive_and_recovers_when_owner_exits`
(`test_workload_admission_script.py:142-145`) is skipped when (i) not Windows, (ii) local
time is outside 00:30-09:00 (`_inside_heavy_window()`, `:128-131`, evaluated at import), or
(iii) `WEATHER_WORKSTATION_WRAPPER_ACTIVE=1`. Eleven more lease tests carry skip (iii)
(`:888, 1017, 1121, 1657, 1747, 1803, 1867, 1972, 2189, 2327`). That variable is set only by
`workstation_heavy.ps1:149` - the wrapper the Codex hook requires for agent-run pytest on the
workstation (`docs/development.md:75-89`). So: CI skips them (Linux); agent runs on the
workstation skip them (wrapper); only an attended, unwrapped Windows run in the small hours
executes the exclusivity test.

On the production host the bounded runner does not set that variable, so the tests run - but
the runner's parent PowerShell holds the real mutex `Global\WeatherProjectHeavyWorkloadV1`
for the whole suite (`bounded_worktree_test_suite.ps1:437`; `workload_admission.ps1:1505-1516`
acquire with `WaitOne(0)`, `:1715-1720` keep it in the returned lease). These tests dot-source
the unmodified lease script and expect to acquire that same mutex
(`:145-173` expects `ACQUIRED`; `:921-926` throws `'portable lease was unexpectedly busy'`).
A child process cannot take a named mutex its ancestor owns, so I expect deterministic
failures there. The wrapper-fixture tests avoid this by renaming the mutex to a `Local\`
fixture name (`test_cold_snapshot_compression_wrapper.py:81`); these tests do not. The
portable-host tests entered master through a GitHub PR merge on 2026-08-30 (`3361520fa`),
i.e. via Ubuntu CI where they skip; the last full host PASS I can find in canonical docs is
2026-08-19 (`ESTABLISHED_FINDINGS.md:2456-2458`).

Impact: the mutual-exclusion guarantee that protects capture from concurrent heavy work has
no routinely executed behavioural test, and may be a second source of "native fixture
failures" on the host beyond the host-id fixtures.

Recommendation: have the bounded runner export a marker the tests honour (or rename the mutex
in these fixtures as the wrapper tests do); drop the wall-clock skip by injecting the policy
window.

### tests-ci-6 (MEDIUM) - Hermeticity is policy, not mechanism: no conftest, no network guard, no per-test timeout, and the "offline" marker has no reader on master

Basis: verified_in_code. Known status: new (the runbook hints at it:
`INTEGRATION_ATTEMPT_RUNBOOK.md:141-144` "unmerged code may enforce the marker").

- `tests/AGENTS.md:6-8` forbids network and `data/` dependence; nothing enforces it. There is
  no `conftest.py`, no autouse socket block (Grep: three file-local autouse fixtures only).
- `bounded_worktree_test_suite.ps1:479-483` sets `WEATHER_INTEGRATION_TEST_OFFLINE=1`,
  `..._SECRET_POLICY`, `..._PRODUCTION_ROOT`, `..._CANDIDATE_ROOT`, `..._ALLOWED_WRITE_ROOT`.
  Grep of `src/`, `tests/`, `scripts/` and `sitecustomize.py` finds **no consumer** other than
  the runner itself and the substring test that asserts the runner sets them
  (`test_bounded_worktree_test_suite_script.py:38-49`). On master the variables are inert.
- No pytest-timeout: a hung test costs the whole 30-minute CI budget, or on the host the
  chunk runs until the 90-minute/09:00 kill (`bounded_worktree_test_suite.ps1:642-650`).

Mitigating facts (strengths): I found no test that reads the real `data/` tree (Grep for
`repo_path("data`, `REPO_ROOT / "data"` = none; `test_data_layer_audit.py:181-184` chdirs into
a temp dir first), only 11 wall-clock call sites in all of `tests/`, and the runner does scrub
credential-bearing environment variables before starting candidate Python
(`bounded_worktree_test_suite.ps1:88-112, 460-478`).

Impact: on the capture host a test that accidentally reaches the network or production paths
is stopped by nothing in the harness; the documented "bootstrap boundary" is currently a
label.

Recommendation: add a root `tests/conftest.py` that blocks `socket.connect` and fails on
writes outside `tmp_path` when the marker is set; add pytest-timeout.

### tests-ci-7 (MEDIUM) - CI has no coverage, lint, type or PowerShell static analysis, and documentation lint runs before (and can mask) the test step

Basis: verified_in_code. Known status: new.

`ci.yml:41-51` is compileall -> docs audit -> roadmap check -> pytest, as sequential steps
with no `if: always()`. With a history dominated by docs/roadmap commits, a roadmap-drift
failure stops the run before any test executes. There is no coverage measurement anywhere
(no `--cov`, no `.coveragerc`), so nobody can say which of ~360k lines the 4.5k tests touch;
no ruff/pyflakes/mypy for a codebase written mostly by agents; no PSScriptAnalyzer for 73
scripts. Dependencies pin direct packages only (`requirements.txt:4-12`); transitive
versions float between CI, workstation and host.

Recommendation: split docs checks into their own job; add `ruff` (errors only) and a coverage
report as non-blocking first; run PSScriptAnalyzer or the existing AST sweep on all scripts.

### tests-ci-8 (LOW) - The operations suite proves refusal far more than completion

Basis: inferred (test-name heuristic; treat as indicative only). Known status: known_open
(theme recorded in agent memory "we measure eligibility, never outcome").

In `tests/operations`, 613 test names contain refuse/reject/block/deny/forbid/cannot/never/
must_not/does_not versus 169 containing recover/retry/resume/heal/complete/succeed/admit/pass
(Grep over `def test_` names). `tests/AGENTS.md:14-15` directs "Assert fail-closed behavior".
The live state - eleven failed qualification attempts, failed archive tasks, ten unsettled
dates - is what a system optimised and tested for refusing looks like. There is no test that
drives the daily chain through a deferral and asserts the settlement step eventually
completes via the real wrappers.

Recommendation: for each fail-closed gate add one liveness test: given the refusal, what
path completes the work, and does it?

### tests-ci-9 (LOW) - `retrain.yml` is dormant and unverified; no retrain lane is running anywhere

Basis: verified_in_code + doc_claimed. Known status: known_accepted (owner decision: no new
model-alpha work; host owns training).

Schedule disabled 2026-07-29 (`retrain.yml:4-11`, commit `c95ec591c`); manual dispatch only.
The CLI surface it calls still exists (`historical_backfill_plan.py:776`,
`historical_backfill_runner.py:318-329`, `feature_model.py:1851-1883`, `src/weather/artifacts.py`)
but nothing has exercised the workflow for seven weeks. If dispatched it would run the full
pytest, then a networked historical backfill and two trainings from an empty `data/` on a
hosted runner with LFS pointers instead of model bytes, under a 6-hour timeout, then upload
all of `artifacts/`. The host-side training window is also disabled (`STATE_OF_PLAY.md:36`).
Consistent with the standing decision; flagged so nobody assumes a working hosted fallback.

Recommendation: delete it or mark it explicitly unsupported; do not leave a 6-hour networked
job one click away.

### tests-ci-10 (INFO) - The suite itself is cheap; the constraint is the machinery around it

Basis: doc_claimed. Known status: known_open.

Answer to "can this suite ever be run where it matters?": it has been. Four immutable host
runs on 2026-08-14 took 8-9 minutes each for 4,400-4,539 tests with peak commit 36.59%
against a 64/66% ceiling and all three capture workers healthy at every admission
(`ESTABLISHED_FINDINGS.md:2230-2320`). Since then the runner gained a 50 GiB disk floor, a
90-minute cap, a required 3/3 healthy-worker check per chunk, the 00:30-09:00 window (shared
with 04:45-06:45 tiering and the 01:00-04:00 merge window, `STATE_OF_PLAY.md:47-49`), and
master gained host-bound Windows tests. The documentation also disagrees with itself on chunk
size: "25-file" (`HOST_LOAD_POLICY.md:372`, `development.md:38`, hook message) versus a
default of 20 (`bounded_worktree_test_suite.ps1:20-21`, `INTEGRATION_ATTEMPT_RUNBOOK.md:116`).

---

## 4. Coverage of the paths that actually failed in production

| Incident | Python-side regression test | PowerShell-side |
| --- | --- | --- |
| Finalize lost a settlement day (`[Errno 13]`, 08-11) | **Yes, behavioural**: `test_market_day_labels.py:85-122` (one failing folder keeps the others), `:161-185` (transient error retried) - added with the fix `bcb49506` | n/a |
| Labels CSV truncated by partial re-finalize | **Yes**: `test_market_day_labels.py:124-159` | n/a |
| Backfill says "settled" on a `none` row | Hole detector tested behaviourally: `test_settlement_hole_check.py:22-47` | **Substring only**: `Test-RowSettled` never executed (`test_settlement_backfill_scripts.py:32`) |
| Log rotation took capture down (08-09) | **Yes**: `test_supervisor.py:438` (rotation does not reset restart budget), `:483`; `test_market_microstructure.py:2194, 2233`; `test_runtime_utilities.py:162-214` | n/a |
| Disk full | Partial: `test_capture_resource_gate.py:255-256`, `test_market_making_daily_roll.py:355`, `test_taker_bot_daily_roll.py:641`, `test_production_cold_archive_stage.py:241`. I found no test of the snapshot/CLOB tape writers under ENOSPC. | none |
| PS strict-mode / argument-splitting / operator binding | n/a | Found by failed production attempts, not by tests (Findings 2-3) |

Mock usage: 547 `mock.patch`/`monkeypatch.setattr` sites in 106 files, but only 140
call-assertions (`assert_called*`, `call_count`, `call_args`) in 27 files, mostly
`assert_not_called` on fail-closed short circuits (`test_daily_refresh.py:1135, 1301, 3111`).
Sampled capture tests use injected runners and assert on results
(`test_snapshot_capture_batch.py:51-113`). **Asserting on mocks instead of behaviour is not a
material problem in this suite.**

Host coupling: absolute `C:\Users\micha\...` strings in tests are fixture data or negative
assertions, not accessed paths (`test_lock_blocker_end_to_end.py:66`,
`test_host_task_wrappers.py:26`). The real host coupling is the execution-host identity in
Finding 1(b) and the mutex in Finding 5.

---

## 5. Strengths

1. **Incident-driven behavioural regression tests on the Python side** -
   `tests/market/test_market_day_labels.py:85-185`, `tests/operations/test_supervisor.py:438-483`.
2. **Hermetic by construction**: `tmp_path`/tempdirs throughout, injected clocks (11 wall-clock
   call sites in the whole tree), no dependence on real `data/` found; policy stated in
   `tests/AGENTS.md:6-10`.
3. **Honest skip discipline**: zero `xfail`, zero unconditional skips; every skip names a
   platform or tool condition.
4. **A carefully engineered host runner**: exact-tip + clean-tree + registered-worktree
   checks, import-origin probe, kill-on-close Job per chunk, credential scrubbing, capture
   admission per chunk, post-run identity and inventory re-proof
   (`scripts/ops/bounded_worktree_test_suite.ps1:377-410, 507-543, 697-740`), with a
   ratchet-first preflight mode (`:549-576`).
5. **Detector-sensitivity testing**: the train/serve parity gate must rediscover 4 known
   defects (`tests/reporting/test_train_serve_feature_parity.py:47-48`). CI hygiene is also
   sound: least-privilege token, concurrency cancel, LFS off with a written reason
   (`.github/workflows/ci.yml:8-13, 22-28`).

---

## 6. Not covered / open questions

- Actual GitHub Actions history: pass/fail state of master, run durations, flake rate, branch
  protection settings (no network).
- Current wall-clock duration of the full suite on the production host and whether it still
  fits the 90-minute cap.
- I did not run anything, so I cannot say whether the suite is green on any platform today.
- `tests/reporting` (largest directory) and `tests/calibration` were sampled by name and
  count only; `tests/app` not read.
- The free-disk figure in Finding 1(a) comes from the lead auditor's live-state summary and
  `item-325`; I did not open anything under `data/`.
- The mutex collision in Finding 5 is a code trace, not an observation. It should be
  confirmed from the retained JUnit sidecars of the 2026-09-13 host attempt
  (`scratch/handoffs/overnight-20260913-complete-a9/`), which were outside my read scope.
- Contents of PR 61 beyond the two workflow files and the fixture commit `f60dbb9e6`.
- The Codex host-load hook's internals (`.codex/hooks/`), beyond confirming its pytest rule.
