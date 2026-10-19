# Phase B-R: requalify the 3.11.9 stage venv on the post-N12 tip, 00:30 on Wed 2026-10-21 (capture host)

Night 10-20/21 is **B-R only** (master-agent, option A, 2026-10-19). Night 10-21/22 is C only. The source is
`docs/operations/HOST_PYTHON_UPGRADE_RUNBOOK.md`, section "B-R", plus the revision note of 2026-10-19, on
`claude/pyup-c-1021-review-20261019`. Its delta review is `docs/operations/pyup-c-1021-delta-review.md` on the same
branch. If the landed runbook differs from this kit, the runbook wins: regenerate the kit.

**No Phase B night script is in git.** `git log --all -- '*phase-b-run*'` and `git log --all -S 'phase-b-run'`
both return nothing. So `phase-br-run.ps1` was written from the runbook. The section 6 header functions and the
B0, B1c, B1d, B1e, B2 and B3 text are copied from the runbook. Everything else is a wrapper gate and is listed below.

## Files

| File | Role |
| --- | --- |
| `phase-br-run.ps1` | The whole night in one script: P gates, then B0, B1c-B1e, B2, B3. `-DryRun`/`-WhatIf` runs the P gates only. |
| `PHASE-BR.md` | This file. |
| `SHA256SUMS` | sha256 of `phase-br-run.ps1` (ASCII, LF). `.gitattributes` keeps these files byte-exact. |

Copy the script to the host byte-exact, and check its sha256 against `SHA256SUMS` before running it.

## Inputs

| Parameter | Value |
| --- | --- |
| `-ProductionRoot` | the production checkout, the `WeatherSnapshotLoopSupervisor` working directory |
| `-ExpectedHead` | **the post-N12 master sha, all 40 hex characters**, as master reports it once N12 has landed. The script refuses any other HEAD. |
| `-NightDate` | `2026-10-21`, the morning date. The script refuses another local date, and names the branch `py3119-qual-20261021`. |
| `-RecordRoot` | `C:\pyup\cp3119` (default; the Phase A/B `$R`) |
| `-NewHome` | `C:\Program Files\Python311-cp3119` (default) |
| `-StagePath` | default `<parent of the checkout>\weather-py3119-stage-br`, which must be absent. The 10-16 stage `weather-py3119-stage` is **kept** (see "Differences" below). |
| `-GitExe`, `-GitSha`, `-GitVer` | default: the Phase B binding read on the host on 10-15, `C:\Program Files\Git\cmd\git.exe`, `5385ff9a…59cc`, `2.45.2.windows.1`. Re-read on the host. If Git changed, pass the new values, recorded with their source. |

## Order

1. **Tue, after N12 lands, before 12:00 (light, read-only):** run the dry run.
   `powershell -NoProfile -ExecutionPolicy Bypass -File phase-br-run.ps1 -ProductionRoot <P> -ExpectedHead <40-hex> -NightDate 2026-10-21 -DryRun`
   It must end `RESULT: every non-window gate PASS; nothing was written`, exit 0. The two window gates (night date,
   00:30-02:00) report `WINDOW-CLOSED` in the daytime and do not count. The dry run writes nothing: no record
   directory, no `night.log` line, no lease, no worktree, and no `__pycache__` (`PYTHONDONTWRITEBYTECODE`). Its
   one temporary folder under `%TEMP%` is deleted on exit.
2. **Wed 00:30-02:00:** run the dry run again, then the real run, the same command without `-DryRun`. Use one
   elevated Windows PowerShell 5.1 window. Nothing may tail `night.log`.
3. Read the result: exit 0 and `B-R PASS: qualification.json now names tip <ExpectedHead>`. Report it with
   `<R>\br-2026-10-21-<HHmmss>\br-receipt.json` and the new `qualification.json` sha256 before 09:00.

## Gates the script enforces (any failure = NO-GO, exit 1)

**P, read-only:**
- the local date is `-NightDate`, and the time is 00:30-02:00;
- production HEAD is `-ExpectedHead`, and the tracked tree is clean;
- the Phase A and B files are present:
  - `constants.json` with every key;
  - `oldhome.txt`;
  - `paths.json` matching the session;
  - `$NewPy`, whose `-VV` and sha256 match `constants.json`;
- the previous `qualification.json` is a case-A PASS on a **different** tip;
- the stage path and `py3119-qual-20261021` are both absent;
- the wheelhouse equals `wheelhouse-sha256.txt`, and every line of `lock-hashed.txt` carries a hash;
- the production freeze, with the editable line masked, equals `receipts-3110\freeze-3110.txt`;
- the production `capture_runtime_versions` direct dependencies equal `rtv-3110.json`;
- G5: `WeatherTrainingWindow` and `WeatherEveningEvidenceRefresh` are disabled or absent, and there is no 00:35 U6;
- **exclusive night:**
  - `WeatherReplayBundleExportNightly`, `WeatherEvidenceHost` and every `WeatherMakerEvidence<Family>` task are
    **not registered**;
  - no enabled `WeatherIntegration*`, `WeatherSuite*`, `WeatherStorageRecovery-*` or `WeatherTrainingWindowReenable*`
    task is due before 09:00;
- the shared lease is free (`Get-WeatherHeavyWorkloadLeaseState`);
- C: has at least 55 GB free;
- the git binding matches;
- the suite's `param()` block has the interpreter, git-binding, `-PreflightOnly` and `-MaxRuntimeSeconds` parameters
  (AST, G1);
- the release is case A.

**Real run:**
- **B0:** takes the shared lease, workload `py3119_requal`, and holds it through B1e. Any NO-GO releases it, and so
  does the outer `finally`. The previous `qualification.json` is copied to `qualification-<old tip 12>.json`, and
  the copy's sha256 is checked.
- **B1c:**
  - `git worktree add -b py3119-qual-20261021 <stage> <ExpectedHead>` runs with `GIT_LFS_SKIP_SMUDGE=1`, and the
    stage HEAD is checked.
  - The venv is created from `$NewPy`.
  - `Build-Venv` is the runbook's verbatim text, so every pip call is `--isolated --no-index --find-links <wheelhouse>`.
    The script also clears the `PIP_*INDEX*`, `PIP_FIND_LINKS`, `PIP_PROXY` and `PIP_TRUSTED_HOST` variables and sets
    `PIP_NO_INDEX=1`.
  - **There is no download step.** `pypi_hash_lock.py` and `pip download` are never called.
- **B1d:** `Test-Venv`, verbatim, tag `stage-br`, which writes `<R>\check-stage-br\`. It checks the 3.11.9 `-VV`, the
  `pyvenv.cfg` home, `pip check`, the freeze, the import location, the stdlib location, the import smoke test, and the
  rtv python and direct dependencies.
- **B1e:** the HGB load smoke test; then the lease is released.
- **B2:**
  - It must start by 03:00, and the git binding is re-checked.
  - `bounded_worktree_test_suite.ps1` runs a preflight and then the full suite, with `-InterpreterPath <stage python>`,
    `-ExpectedInterpreterVersion 3.11.9` and the git binding. The suite takes its own lease.
  - `-MaxRuntimeSeconds` is min(5400, the seconds left until 04:45), so the suite ends before the tiering reserve.
    The suite's own 09:00 hard teardown and kill-on-close Job stay in force.
  - Each child's PID is written to `suite*.pid.txt` (the track-and-terminate rule).
  - **basetemp:** the suite gives every chunk an explicit `--basetemp` under `%SystemDrive%\pt\bs-<run>-NNN` and
    deletes it. Afterwards the wrapper looks for this run's leftover `bs-*` directories (created after the suite
    started; never a reparse point), removes them, and records anything it could not remove in
    `basetemp_leftovers`. A leftover is a WARN, not a NO-GO.
  - **PASS requires** all of these:
    - suite exit 0;
    - `VERDICT: ALL CHUNKS PASSED`;
    - `interpreter override re-hash matched`;
    - an `interpreter_override` line naming the stage venv and 3.11.9;
    - the `selected_git=` line naming the binding;
    - a clean stage worktree.
- **B3:** case A again on 3.11.0. Then, **only on PASS**, `qualification.json` is written to a temp file, read back,
  and moved into place. It holds:
  - `result=PASS`, `procedure=B-R`, `release_case=A`;
  - `tip`, `branch`, `stage`, `stage_python`;
  - `python_version=3.11.9` and `python_vv`;
  - `pyvenv_cfg` and its sha256, and `pyvenv_home`;
  - `stage_freeze` and its sha256;
  - `suite_log` and its sha256, `suite_exit`, and the preflight log and its sha256;
  - `git_binding`;
  - the wheelhouse manifest and its sha256, and the `lock-hashed` sha256;
  - `supersedes` (old tip, archive path and sha256);
  - `basetemp_leftovers`, `record_dir` and `at`.

  C0 reads `result`, `release_case` and `tip`.
- **Any failure:** `qualification.json` is left as it was (the 10-16 tip). At C0, G3 then fails, and C is NO-GO.
  `br-receipt.json` always records the outcome.

## Differences from the runbook's B-R text (the runbook branch matches these)

- **A new stage path; the old stage is kept.** The runbook's first draft ran §D (`git worktree remove`) first. The
  wrapper never deletes anything. The 10-16 stage and its branch stay until §D, which now removes every
  `py3119-qual-*` worktree and branch.
- **`qualification.json` is written only on PASS.** In Phase B, B2 wrote `PENDING_B3`/`FAIL` into it. Here a failure
  leaves the old record, and G3 stops C.
- **The extra gates** are the HEAD pin, the night date, the exclusive-night tasks, the free-lease check and the G1 AST
  check.

## Failure handling

B-R never touches the production venv, capture or a task. A failure needs no rollback:
- keep the stage, `<R>\br-*` and `<R>\check-stage-br` for diagnosis;
- report the failure;
- C on 10-21/22 is then NO-GO under G3, unless the owner rules otherwise.

If the window is closed mid-run, the script is gone, but a suite child may still run. Read `suite*.pid.txt` and
terminate that PID's tree; `Stop-Process` on the recorded PID is enough, because the suite's Job kills its own
children. Then confirm that `Get-WeatherHeavyWorkloadLeaseState` shows the lease free.

## Verification done on the workstation (never on the host)

- PowerShell AST parse: 0 errors. The top-level `try` has a `catch` and a `finally`.
- `-WhatIf`, run against the workstation checkout with a fabricated record root: every non-window gate PASS, exit 0;
  nothing written to the record root, the checkout's `git status` unchanged, and no dry-run temp folder left.
- Negative control, with a wrong `-ExpectedHead` and an extra freeze line: `RESULT: 2 gate(s) FAIL` (the HEAD and
  freeze gates), exit 1.
- The real path (B0-B3) cannot run off the host. It is the runbook text, plus the gates above.
