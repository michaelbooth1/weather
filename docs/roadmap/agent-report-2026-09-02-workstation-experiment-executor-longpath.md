# Experiment executor Windows long-path repair

**Verdict: PASS.** The executor now stages and publishes both successful and
quarantined terminal results beneath ordinary Windows path limits without
changing the final result location, generic `weather.io` behavior, or the
directory-rename terminal commit. The complete workstation suite is green.

## Identity and scope

- Branch: `codex/workstation-experiment-executor-longpath-2026-09-93a`.
- Required and used source tip:
  `c932b54f8747df5cdefc4cc42f8454b6797f09ae`.
- Required and used source tree:
  `6df5bac16d8c780c35b4601941eaca1137ea7070`.
- Implementation/test tip:
  `3bba576a91b2fb1be0149c565b97b7b27687c1bb`.
- Implementation/test tree:
  `c1bbb69434708bb7ccfbb2edb669388057b89e6d`.
- Implementation files: `.gitignore`,
  `src/weather/operations/experiment_executor.py`, and
  `tests/operations/test_experiment_executor.py`.
- This report is committed separately after the implementation/test commit.
  The exact final report commit and tree are supplied in the handback that
  accompanies the pushed branch.

## Reproduction and mechanism

The unmodified source reproduced the Windows path-limit family before any
edit:

- Normal pytest temporary root: `13 failed, 11 passed`. The accumulated normal
  pytest prefix crossed `MAX_PATH` while creating the duplicated candidate
  workspace, before terminal staging.
- `--basetemp=C:\t93pre`: `12 failed, 12 passed`. All 12 reached
  `write_json_atomic(staged_result, ...)` and failed when it created the sibling
  atomic temporary file.
- `--basetemp=C:\x`: `12 failed, 12 passed`. With the current five-digit PID,
  the first staged path was 230 characters and its atomic path was exactly 260,
  which still exceeds the legacy Win32 limit once the terminating null is
  included. This explains why the previously observed 24-pass short-root
  control is PID/path-prefix sensitive; it does not contradict the confirmed
  mechanism.

The regression fixes the authoritative geometry: the legacy construction is
267 characters for `staged_result`, and the normal atomic suffix makes it 297.
For the same repository root, the repaired paths are 191 and 221 characters,
respectively, a 76-character reduction. The separately named long-root suite
also passed with a 257-character atomic path in its longest ordinary success
case.

The excess came from nesting the scratch run under
`artifacts/candidates/<candidate>/experiments/.executor_runs`, then recreating
the complete repository-relative candidate path below a `workspace` child.
The repair uses the ignored, repo-root-local shape
`.e/<manifest-prefix><full-uuid>/...`: eight manifest hash characters retain
diagnostic attribution, and the complete 128-bit UUID retains run isolation.

## Preserved contracts

- The executor still verifies the complete child artifact inventory, hashes,
  schemas, resource result, queue currency, and protected serving fingerprint
  before publication.
- The self-hashed terminal result is still written with
  `write_json_atomic` inside the staging tree. On success, its temporary sibling
  is atomically replaced with the staged result.
- The executor then publishes the terminal result and declared artifacts
  together with the existing single `stage_root.replace(candidate_root)`
  directory rename. The candidate root must still be empty, so publication is
  create-only and refuses overwrite.
- Before any child runs, `st_dev` equality now proves scratch and candidate
  output are on the same filesystem. A mismatch fails closed; no cross-device
  fallback or direct write exists.
- Scratch remains inside the resolved repository root and passes the existing
  symlink/escape guard before and after its parent is created. Candidate/source
  containment and child audit-hook policy are unchanged.
- Failed/untrusted child output is still detached into a unique quarantine
  below its run root. Successful scratch cleanup remains bounded; quarantine
  and interrupted-write scratch remain retained.
- The outer lifecycle guard still releases every acquired claim. If the atomic
  staged-result replace is interrupted, the executor removes only its own
  PID/time-named temporary sibling and re-raises, leaving the rest of the run
  scratch for audit.
- `weather.io` was not changed. The tests are platform-neutral and carry no
  Windows-only skip, preserving the Linux execution path.

## Verification

| Check | Result |
| --- | --- |
| Complete executor file, normal workstation temp root | `27 passed in 3.50s` |
| Complete executor file, intentionally long root | `27 passed in 3.52s` |
| Complete executor file, short-root compatibility control | `27 passed in 3.49s` |
| Experiment-contract and IO tests | `50 passed, 1 skipped in 6.87s` |
| `compileall -q app src tests` via `workstation_heavy.ps1` | exit `0` |
| Full repository suite via `workstation_heavy.ps1` | `4223 passed, 22 skipped, 862 subtests passed in 430.60s`; 13 warnings |
| Agent-document audit | `PASS (18 agent files, 827 Markdown files)` |
| Roadmap lint/check | `OK (generated report matches sources)` |
| `git diff --check` | exit `0` |

The 13 full-suite warnings are the existing scikit-learn empty-feature warnings
and one NumPy/netCDF binary-size warning; no test failed, so no pre-existing
failure separation was necessary.

Reproduction commands from a checkout of this branch:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_experiment_executor.py -q
.\venv\Scripts\python.exe -m pytest tests\operations\test_experiment_executor.py -q --basetemp=C:\x94
.\venv\Scripts\python.exe -m pytest tests\operations\test_experiment_contract.py tests\reporting\test_experiment_queue_contract.py tests\operations\test_runtime_utilities.py tests\test_io_streaming.py -q
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
git diff --check origin/master...HEAD
```

The full suite and compileall were run through the exact checkout-owned
`scripts\ops\workstation_heavy.ps1` wrapper with the
`workstation_offline_v1` profile, shared host mutex, and kill-on-close Job.

## Roll verdict and prohibited actions

No roll classification was derived by hand. The canonical
`scripts\ops\roll_verdict.ps1` cannot be executed within this mission's stated
boundary: it calls `Get-ScheduledTask` and consumes live capture closure files,
while the mission expressly prohibits Scheduler and production access. The
production integration owner must run the canonical command against the pushed
branch before considering integration:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/workstation-experiment-executor-longpath-2026-09-93a
```

No production host/data, Scheduler, provider, exchange, credential, live
execution, model, corpus, merge, pull request, release, or runtime-adoption
action was accessed or performed. GitHub `master` was not mutated; the only
remote-master operation was the mission's required read-only origin fetch.
