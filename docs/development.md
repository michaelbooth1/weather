# Development and Verification

Status: canonical development guide.

- **Owns:** the change workflow, which check proves which kind of change, what CI runs, and the definition of done.
- **Read when:** about to edit code, choosing what to run to verify a change, or deciding whether a change is done.
- **Do not use for:** setup and the operator command catalog ([README](../README.md)); branch, worktree, commit and
  pull-request procedure ([Git workflow SOP](git-workflow.md)); when heavy work may run on the capture host
  ([HOST_LOAD_POLICY](operations/HOST_LOAD_POLICY.md) owns that, this file only routes to it).
- **Verify with:** `pytest.ini`, `pyproject.toml`, `.github/workflows/ci.yml`, and the `param()` block of
  `scripts/ops/bounded_worktree_test_suite.ps1`.

## Before editing

- Inspect `git status --short` and preserve unrelated changes.
- Read the nearest `AGENTS.md` and identify the owning package.
- Confirm whether the task touches local evidence, generated config, tracked
  artifacts, a scheduled task, release state, or a network service.
- Prefer a canonical `python -m weather...` entry point over a flat wrapper.

## Baseline commands

These four commands are exactly what CI runs, in this order (`.github/workflows/ci.yml`). From the repository
root on Windows:

```powershell
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
.\venv\Scripts\python.exe -m pytest -q
```

**Do not run them as written on the 16 GB production capture host.** See "Where verification may run" below.

`pytest.ini` collects only `tests/` and puts `src/` on the path; `scratch/` scripts named `test_*.py` are not part
of the suite. The editable install (`pip install -e ".[test]"`; the `test` extra pins pytest) is still the primary
package contract, and `requires-python` is `>=3.11`.

## What CI does and does not cover

- The `CI` workflow runs on **pull requests and on pushes to `master` only**. A push to any other branch runs
  nothing. A branch has no CI evidence until a pull request exists for it.
- Ubuntu, Python 3.11, 30-minute job timeout, Git LFS disabled on purpose (tests stub model artifacts).
  Production modules must therefore stay cross-platform even though scheduled operations are Windows specific.
- Tests that execute Windows PowerShell, ACL, Scheduler, or Job semantics carry precise non-Windows skips, so
  the Ubuntu job skips them. Every such file runs in a Windows qualification shard (below);
  `test_windows_qualification_shards.py` fails when a test file that skips off Windows is in no shard.
- The [`Host-load hook` workflow](../.github/workflows/host-load-hook.yml) runs the hook policy tests on Windows and Linux, only when the hook, its test, or
  that workflow file changes. It uses no fixtures or credentials and provides a verification path while an
  installed hook prevents dispatch of its own proposed repair.
- [`ci.yml`](../.github/workflows/ci.yml) runs a fast `audit` job first (compileall, agent-docs audit, roadmap
  check, then every test marked `@pytest.mark.ratchet`, uploading a `linux-junit-audit-*` artifact). The Linux
  `test` and `memory-flatness` jobs both `need` it, so a ratchet failure stops the run before the long suite, and
  then run in parallel on the same Python and dependencies: `test` runs
  `pytest -m "not ratchet and not memory_flatness"` and `memory-flatness` runs
  `pytest -m "memory_flatness and not ratchet"` (the slow 5-to-50-run tracemalloc flatness tests). Each uploads a
  `linux-junit-*` artifact. The three selections partition the suite, so each test runs exactly once per CI run;
  `tests/operations/test_ci_job_partition.py` proves it by truth table, so a new marker split must keep that test
  green. A ratchet is a repository-wide architecture or inventory check (imports, schema registry, docs audit, path
  policy, module size, ops-script and task inventories). Mark a new one `ratchet` and add its file to the audit
  job's list; `tests/operations/test_ci_ratchet_selection.py` fails until the list names exactly the files that use
  the marker and the jobs' selections are exact complements. A ratchet that skips off Windows also carries
  `windows_native` and executes in exactly one [Windows qualification](../.github/workflows/windows-qualification.yml)
  shard (shards holding ratchet files select `-m "not ratchet or windows_native"`); the same meta-test proves every
  ratchet executes exactly once across all workflows. Local and bounded-suite runs ignore these markers and run
  everything (plain `pytest -q`).
- The [Windows qualification workflow](../.github/workflows/windows-qualification.yml) adds exact-candidate native
  launch/integration regressions under Windows PowerShell 5.1, as parallel `native-launch (<shard>)` jobs
  balanced from JUnit timings (a file too slow for one shard, such as `test_status_script.py` or the reconciler execution tests, is
  split across shards by `split_select` -k expressions; `tests/operations/test_windows_qualification_shards.py` pins the
  plan and proves by collection that every listed test runs exactly once); each shard uploads its own receipt and JUnit. Hosted Windows evidence records its actual scope,
  candidate/tree, workflow and resolved dependencies. It does **not** replace the admitted production-host bounded
  suite or the actual-host S4U smoke; the production acceptance contract stays in force until a separately reviewed
  substitution is qualified.
- `ci.yml` and `windows-qualification.yml` cancel a superseded run on a pull-request ref but never on `master`, so
  every landed commit keeps its own evidence.
- There is no retrain or settlement-audit workflow: `retrain.yml` and `settlement-audit-qualification.yml` were
  removed on 2026-09-29 (owner decision 4 of the 2026-09-26 repo-health audit). Executable Windows coverage of the
  settlement-audit owners comes from the production-host bounded suite, which runs every tracked test.
- The GitHub CLI (`gh`) is not installed on the capture host. Do not plan a step there that opens a pull request
  or reads CI status with `gh`; use the web UI, the workstation, or the push path in the
  [Git workflow SOP](git-workflow.md).

### Known CI flakes

A test enters this table on a proven same-SHA fail-then-pass. A row is tracked evidence, not a quarantine: one
occurrence never justifies `@pytest.mark.quarantine`. Rerun the failed job on the same SHA; if a test reaches three
occurrences, raise it with the owner. Counts come from the item K CI history (P0-3, the 500 runs to 2026-10-04)
plus later sightings.

| Test | Lane | Occurrences | Evidence |
| --- | --- | --- | --- |
| `tests/collection/test_forecast_payload_cross_process_fanout.py::test_holder_http_backoff_outcome_is_shared_without_second_provider_call` | Windows | 1 | same-SHA rerun (P0-3) |
| `tests/collection/test_forecast_payload_cross_process_fanout.py::test_timeout_fetch_plus_holder_counts_two_fetches_and_one_write` | Windows | 1 | same-SHA rerun (P0-3) |
| `tests/operations/test_storage_recovery_inventory_wrapper.py::test_real_wrapper_completion_binding_failure_and_child_tree_teardown[success-True]` | Windows | 1 | run 37078892774 attempt 1 failed, attempt 2 passed |
| `tests/operations/test_live_wrapper_credential_launcher.py::test_forced_launcher_exit_kills_the_live_child_tree_before_mutex_reuse` | Windows | 1 | inferred, not same-SHA proven (P0-3) |
| `tests/operations/test_production_baseline_reconciler_execution.py::test_post_start_hung_read_cannot_consume_the_containment_stop_reserve` | Windows (`reconciler-5`) | 1 | run 37246104447 (PR #209, 3767c21f): attempt 1 asserted `[] == ['WeatherOneShotPush']` after 48 s; same-SHA rerun passed. Timing-sensitive hang test on a slow hosted runner |

## Where verification may run

### Production capture host (16 GB)

The baseline commands are not authority to run a direct full suite or parallel verification here.
[HOST_LOAD_POLICY](operations/HOST_LOAD_POLICY.md) is the contract. In short: focused tests run serially and only
inside 00:30-09:00 local; in Codex sessions the user-layer hook rejects direct unbounded pytest at every hour and
rejects pytest/compileall outside that window (Claude Code has no hook; the S4U guard is its only backstop). A full suite runs only through
`scripts/ops/bounded_worktree_test_suite.ps1`, against a clean worktree at an exact commit. Its enforced limits
(read the script, not this list, if they matter to a decision):

| Limit | Value in the script |
| --- | --- |
| Mandatory parameters | `-RepoRoot`, `-WorktreeRoot`, `-ExpectedTip` (40-hex), `-BranchRef`, `-LogPath` |
| Chunk size | `-MaxFilesPerChunk` default 25 (owner decision 2026-10-04; was 20), which is also the hard maximum and what new integration attempts freeze; always `ceil(files / MaxFilesPerChunk)` chunks |
| Chunk grouping | time-packed (longest first into the lightest chunk with room) from the candidate's `tests/bounded_suite_file_timings.json`; an unlisted file weighs `default_seconds`, an absent table weighs every file equally, a malformed one refuses. Grouping never changes the file set, the cap or the chunk count. Regenerate the table from one or more complete Windows JUnit runs with `python tools/bounded_suite_timings.py --run "<run>/*.xml" --source "<what, when, sha>"` |
| Commit charge | refuses to start above `-StartCommitPercent` 64, aborts before any chunk above `-AbortCommitPercent` 66 |
| Free disk | 50 GiB (53,687,091,200 bytes) free on the volume, or it refuses |
| Window | must start inside 00:30-09:00; hard teardown at 09:00 or `-MaxRuntimeSeconds` (max 5400) |
| Exclusivity | takes the `data/logs/heavy_workload.lock` lease; refuses if another heavy workload holds it |
| Modes | `-PreflightOnly`, `-SmokeTest`, `-IntegrationPreflight`, `-RequireLiveSdkContract` |

The only merge-eligible result is the final log line `VERDICT: ALL CHUNKS PASSED`. When free disk is under the
floor the suite cannot be admitted at all; that is a blocker to report, not a limit to lower.

Test runs write large temporary trees. Give focused pytest an explicit `--basetemp` outside the repository and
delete it afterwards; judge disk with the volume's free space, not a directory size.

### Separate non-capture workstation

On a separate non-capture workstation, including the 32 GB PC when it also
holds the portable live-executor assignment, ordinary local development and
verification are not subject to the capture-host timetable, chunked wrapper,
or serial-only rule. Route recognized heavy Python work through
`scripts/ops/workstation_heavy.ps1` (`-Kind pytest|compileall|weather_heavy`, `-PythonPath`, `-ArgumentsBase64`,
`-RepoRoot`, all mandatory) with an absolute repository root, absolute
Python path, and the documented base64 JSON argument contract. Its distinct
offline profile admits only the assignment's exact non-capture Windows
installation and attending principal and holds the same host-global mutex as
the portable launcher. Both paths own their complete child tree in a kill-on-
close Windows Job, so wrapped heavy work and launched live work cannot overlap.
Size concurrency to the workstation's current resources and finish heavy work
before sealing to avoid spending an attempt. This does not authorize
production `data/` access, Scheduler or capture mutation, credentials,
networked collectors, exchange contact, or live orders, and a workstation
PASS does not replace any explicitly required production-host qualification.

An attended PowerShell operator can build the bounded argument contract like
this (use `compileall` or an allowlisted `weather_heavy` module as appropriate).
This variable-based form is for a person at an interactive shell, not for a
Codex tool call:

```powershell
$repoRoot = (Resolve-Path .).Path
$pythonPath = (Resolve-Path .\venv\Scripts\python.exe).Path
$argumentJson = ConvertTo-Json -InputObject @("-m", "pytest", "-q") -Compress
$argumentBase64 = [Convert]::ToBase64String(
  [Text.Encoding]::UTF8.GetBytes($argumentJson)
)
& (Join-Path $repoRoot "scripts\ops\workstation_heavy.ps1") `
  -Kind pytest -PythonPath $pythonPath -ArgumentsBase64 $argumentBase64 `
  -RepoRoot $repoRoot
```

For a Codex tool call, replace every `C:\absolute\weather` placeholder with the
same real repository root, then submit this exact literal shape as one line:

```powershell
& 'C:\absolute\weather\scripts\ops\workstation_heavy.ps1' -Kind pytest -PythonPath 'C:\absolute\weather\venv\Scripts\python.exe' -ArgumentsBase64 'WyItbSIsInB5dGVzdCIsIi1xIl0=' -RepoRoot 'C:\absolute\weather'
```

The hook accepts the wrapper owned by that absolute repository root, in the
exact parameter order shown, with literal absolute paths and a literal
canonical base64 value, optionally followed by ` -Queue` or
` -Queue -QueueTimeoutSeconds <N>` to wait first-in first-out for a busy lease
([host load policy](operations/HOST_LOAD_POLICY.md#workstation-focused-runs-fifo-queue-and-xdist-owner-decision-2026-10-04)). A sibling worktree or clone is accepted only
when its workstation wrapper, workload-admission script, and Windows Job helper
are byte-identical to the installed hook's reference checkout. Compute the
base64 value in a light command, then submit the wrapper invocation as a second
command; backtick continuations, chained commands, variables, `Join-Path`, and
other dynamically expanded forms fail closed.

### Starting workstation verification from the capture controller

The capture host's hook distinguishes one literal SSH transport from local
heavy work. The original ambient-config form (`ssh weather-workstation ...`)
remains rejected: SSH configuration can itself start local processes through
`Match exec`, `ProxyCommand` or `LocalCommand`.

Use the Windows system OpenSSH executable, existing workstation identity key
and known-hosts file under the controller user's `.ssh` directory, an explicitly
reviewed RFC1918 IPv4 address, and the exact token order below. Replace every
placeholder with a literal value. Paths use forward slashes and may contain
only ASCII letters, digits, underscores, dots and hyphens; spaces, traversal,
quotes, variable expansion, command chaining and additional options are refused.

```text
C:/Windows/System32/OpenSSH/ssh.exe -F none -T -n -o BatchMode=yes -o StrictHostKeyChecking=yes -o PermitLocalCommand=no -o ProxyCommand=none -o ProxyJump=none -o ClearAllForwardings=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 -o HostName=<workstation-ip> -i C:/Users/<controller>/.ssh/id_ed25519_workstation_codex -o UserKnownHostsFile=C:/Users/<controller>/.ssh/known_hosts -l <workstation-user> weather-workstation C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <remote-repo>/scripts/ops/workstation_heavy.ps1 -Kind pytest -PythonPath <remote-python.exe> -ArgumentsBase64 WyItbSIsInB5dGVzdCIsIi1xIl0= -RepoRoot <remote-repo>
```

This grants transport only. Independently review the exact remote checkout and
wrapper dependency bytes before dispatch, preserve source identity evidence,
and retain/poll the SSH executor session through terminal exit. The controller
cannot hash remote files as though their paths were local. The remote wrapper
must still prove the tracked non-capture Windows installation and attending
principal, acquire its host-global mutex, and contain its full child tree in
the Windows Job. A refused admission or uncertain remote termination remains
fail-closed. Changing the SSH route grants no source, capture, exchange,
Scheduler or deletion authority.

The controller also admits the exact offline module
`weather.operations.workstation_cold_archive_stage` through this transport.
The reviewed remote checkout must contain the adapter and independently admit
it in its workstation wrapper. The stage/restore entrypoints accept explicit
provisional mirror copies or the hash-bound production chunk bridge described
in the [archive runbook](operations/production-cold-archive-staging.md).
Their validation, encryption, create-only evidence and
source-retention gates remain mandatory. This controller admission does not
install the adapter on production or authorize production hashing, upload,
restore or deletion. Those actions retain their separate mission and host-load
requirements; the disk-headroom policy is unchanged.

`-F none` ignores both user and system SSH configuration; strict host-key
checking uses existing trust and cannot enroll a new host in this lane. The
hook validates the same base64/module arguments as local workstation calls.
It still rejects every local workstation-wrapper launch on the capture host,
unknown capture-host identity, all ambiguous remote forms, and unsupported
remote destinations. See the official [SSH command manual](https://man.openbsd.org/ssh.1)
and [SSH configuration manual](https://man.openbsd.org/ssh_config.5).

## Focused verification matrix

| Change | Minimum focused verification |
| --- | --- |
| Streamlit router/view | `pytest tests/app -q` |
| Source adapter/history | matching `tests/sources` tests; no live network in unit tests |
| Model/distribution/features | matching `tests/model`; C and F paths; mass/floor/cutoff checks |
| Training/calibration | matching `tests/calibration`; train/serve schema and artifact compatibility |
| Snapshot/forecast collection | matching `tests/collection`; atomicity, cadence, and replay persistence |
| Settlement ledger, tape scoring, replay | matching `tests/backtesting` |
| Market, maker, or taker logic | matching `tests/market`; keep execution non-live |
| Daily/nightly/supervisor behavior | matching `tests/operations`; use status/dry-run paths |
| `scripts/ops/*.ps1` | the matching `tests/operations/test_*_script*.py`; tests that execute PowerShell are skipped off Windows, so CI does not prove them. A clean parse does not prove parameter binding; read the `param()` block |
| Shared root modules (`weather.io`, `weather.artifacts`, release serving) | the top-level `tests/test_*.py` files plus the owning package tests |
| Reports, gates, roadmap | matching `tests/reporting`; verify fail-closed evidence behavior |
| Package/import/path changes | `tests/operations/test_import_architecture.py` |
| Landing preflight (`weather.operations.landing_preflight*`) | `tests/operations/test_landing_preflight.py` plus `tests/test_hygiene_ratchet.py` and the schema-registry tests (via the workstation wrapper); a `--tests none` dog-food run on a real night plan ([landing preflight](operations/LANDING_PREFLIGHT.md)) |
| Canonical docs/agent files | `python -m weather.operations.agent_docs_audit` |
| Roadmap item/index or generated backlog | roadmap lint plus `roadmap_backlog --fail-on-lint --check` after regeneration |

Run the full suite for cross-owner changes, release/evidence contracts, shared
utilities, or before handing off a broad refactor: on a workstation or through CI, and on the capture host only
through the bounded runner above.

### Affected-test selection

`python -m weather.operations.affected_tests` lists the test files a change can reach through the static
graph, with one reason per file (the shortest chain from the test to a changed file):

```powershell
.\venv\Scripts\python.exe -m weather.operations.affected_tests --base origin/master            # HEAD vs its merge base
.\venv\Scripts\python.exe -m weather.operations.affected_tests --base origin/master --worktree # include uncommitted and untracked files
.\venv\Scripts\python.exe -m weather.operations.affected_tests --base origin/master --format paths   # file list for pytest
```

`--format json` gives the same result for tooling. The graph is read from the git tree of `--head` (no
checkout needed), so it is cheap enough to run anywhere; running the selected tests is still a pytest run under
the host rules above. What it follows and where it stops is in the module docstring; in short:

- Python imports (and, in tests and scripts, strings naming a module), PowerShell lines that run
  `-m weather.*` or launch another script, and file or directory paths that a test or module names.
- Any `conftest.py`, `pytest.ini`, `pyproject.toml`, `requirements*.txt` or the import bootstrap selects the
  full suite. The repository ratchets are always selected, and the output lists the always-run audit commands.
- It is advisory. Dynamic imports, computed paths and behavior that crosses branches (a master change that
  breaks a test that exists only on a feature branch) are invisible to it; a pull request's full CI run stays
  the evidence. Changes it cannot connect to any test are listed under "changes no test reaches statically".

## Staged test cuts: the quarantine marker

A test is never deleted in one step. Removing a test that is believed redundant, trivial or brittle is staged:

1. **Quarantine.** Mark it
   `@pytest.mark.quarantine(reason="...", added="YYYY-MM-DD", sunset="YYYY-MM-DD", replaced_by="...")` and add an
   entry to [`tests/quarantine_registry.json`](../tests/quarantine_registry.json):
   `"tests/x.py::test_y": {"first_added": "<added>", "renewals": []}` (the key is the test function; parametrized
   cases share it). `reason`, `added` and `sunset` are required; `added` is not in the future and `sunset` is at
   most 6 weeks after it. `replaced_by` names the surviving test that still kills the same fault. Name a twin
   that CI actually runs: a Windows-only twin in no Windows qualification shard leaves pull-request CI with
   neither test. A class-level or module `pytestmark` marker applies to every test under it; stacking two
   markers on one test is refused.
2. **Observe.** A quarantined test is still collected and still runs everywhere (CI, the workstation, the bounded
   suite). If it fails in setup or call, the run does not fail: the result becomes a non-strict xfail with the
   quarantine reason, a `QuarantinedFailureWarning` is shown, the terminal report ends with a "quarantined tests"
   section naming each failure, and the JUnit test case carries `quarantine` and `quarantine_failure` properties.
   A teardown error stays fatal. Every quarantined failure must be triaged: a real defect means the test is
   restored (marker and registry entry removed), not deleted.
3. **Renew at most within 12 weeks.** A renewal appends the new `added` date to the entry's `renewals` and sets a
   new sunset, so it is a visible, reviewed registry diff. No sunset may fall more than 12 weeks after
   `first_added`, however often the entry is renewed.
4. **Delete or restore.** Deletion is an owner decision, taken only after at least two weeks of CI and at least
   three bounded-suite runs with no real-defect failure.

**When the sunset passes.** Under GitHub Actions (`GITHUB_ACTIONS=true`) collection fails with a usage error
that names the test, in every job that collects it: the test job, and the audit job through
`tests/test_quarantine_registry.py`. This also holds under `--collect-only` and under a `-k`/`-m` selection
that would skip the test. Off CI (the workstation, and the capture-host bounded suite on an integration night)
the expiry is only reported: a `QuarantineExpiredWarning`, an `EXPIRED QUARANTINE` line in the terminal
section, and a `quarantine_expired` JUnit property. The test stays quarantined, so a calendar date alone never
changes a local or bounded-suite outcome. `--quarantine-expired=fail|report` overrides the detection.
Malformed markers and registry mismatches always fail collection; CI catches them before merge.

[`tests/quarantine_plugin.py`](../tests/quarantine_plugin.py) implements the marker (registered in `pytest.ini`,
loaded by `tests/conftest.py`). `tests/test_quarantine_marker.py` pins its behaviour, and
`tests/test_quarantine_registry.py` proves that the hooks are registered (so a bad `conftest.py` merge cannot
silently drop them) and that the registry matches the markers. Under pytest-xdist the terminal section sees only
the controller's reports; the JUnit properties stay per test. Never-cut families (safety, parity, settlement,
release binding, architecture ratchets and the like) are not quarantined without the review that froze them.

## Stateful command boundaries

The following categories require inspection before execution because they can
write local or tracked state, use the network, change scheduled tasks, or affect
serving:

- source backfills and location-event refresh;
- Windows task registration and loop start/restart/stop commands;
- artifact registry, size, externalization, and promotion-preflight generators;
- cleanup, retention, migration, and archive commands;
- candidate creation, release promotion/rollback, and any live exchange mode.

Use `--help`, read the relevant [operations runbook](operations/README.md), and
prefer status, audit, dry-run, read-only, shadow, or paper modes. Never assume an
argument-free registration example is valid; the script parameter block is the
executable source of truth.

## Model-change evidence

A model improvement claim needs more than unit tests. Preserve training/live
feature parity, run captured-input or frozen-tape replay as appropriate, compare
against market prices with proper scoring, inspect protected slices and data
quality, and keep the candidate inactive until promotion and release gates pass.
Exact gates evolve and belong to the release/runbook code, not copied prose.

## Definition of done

- The intended behavior is implemented through the correct owner.
- Focused tests pass on a host allowed to run them; broader checks follow "Verification scope and assertion
  strength" below, including its Windows condition. State where each
  check ran. A capture-host refusal (window, disk floor, commit charge) is reported as a blocker, not as a pass.
- CI evidence exists only for a pull request or for `master`; say which, or say there is none.
- Windows-executing script tests are proven only by the bounded production-host suite, never by CI.
- New behavior is deterministic and network-free under unit tests.
- Schemas, fixtures, manifests, and documentation are updated together where
  their source contracts changed.
- No secrets, machine-specific paths, ignored runtime files, or unrelated user
  changes entered the diff.
- Documentation links and knowledge contracts pass the agent-doc audit.

## Verification scope and assertion strength (owner decision 2026-10-04)

Adopted by the owner on 2026-10-04 (test-suite review K; [decision log](operations/DECISION_LOG.md) row of
2026-10-04; record and evidence:
[test-policy-proposals.md](research/test-suite-review-2026-10-04/test-policy-proposals.md) P2 and P5).

**Local verification and CI (P2, approved with a condition).**

- **Condition, not yet met.** The rule below takes effect only once a CI Windows lane runs the Windows-only
  tests that CI never runs today (about 303 cases in files in no `windows-qualification` shard, including the
  70 reconciler-execution cases; that shard work is approved separately). The change that adds the lane must
  update this paragraph to say the condition is met.
- **Until then**, a change that touches a Windows-executing script (`scripts/ops/*.ps1`, or a test that runs
  PowerShell) still needs a local full suite: the bounded production-host suite, or a Windows workstation full
  run through `scripts/ops/workstation_heavy.ps1`.
- **The rule (once the condition is met).** Local verification is the focused tests for the owner package plus
  the affected tests from `python -m weather.operations.affected_tests --base origin/master --format paths`
  (draft PR #204), run through the host's normal pytest route. The pull request's CI is the full-suite
  evidence; nobody runs a local full suite only to duplicate CI. A handoff may still require more.

**Mutation-informed assertions (P5).** A mutation sample (104 faults in 27 functions) found 51 faults that were
executed but never asserted. New tests, and tests touched in a change:

1. assert both sides of every boundary they cover: the value at the threshold and one step past it;
2. give each guard clause a case where only that guard fires, and assert the specific outcome, not just
   "not PASS";
3. check computed statistics and numeric outputs against an independent expected value, not only presence or
   order;
4. for an incident test, name the mutation it kills in the module `Guards:` line or the test docstring;
5. prefer one strong case per input partition over many cases in the same partition.

## Update this file when

Update when baseline checks, test ownership, CI platforms, stateful command
boundaries, or the repository-wide definition of done changes.
