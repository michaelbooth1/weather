# Test Instructions

Tests mirror owner packages under `tests/app`, `backtesting`, `calibration`,
`collection`, `market`, `model`, `operations`, `reporting`, and `sources`.

- Tests must not depend on the developer's ignored `data/` tree or active
  network services. Build data layouts under `tmp_path` or use small reviewed
  files under `tests/fixtures/`.
- `pytest.ini` intentionally collects only `tests/`; scripts under `scratch/`
  may hit the network and are not tests.
- Preserve architecture ratchets. New package edges, compatibility calls, large
  facades, schema literals, or canonical-doc commands may need explicit owner
  documentation as well as tests.
  Mark a repository-wide ratchet `@pytest.mark.ratchet` and list its file in
  the CI `audit` job (`test_ci_ratchet_selection.py` enforces both).
- Prefer focused behavioral tests over snapshots of large generated reports.
  Assert fail-closed behavior for evidence, promotion, release, and live gates.
- A fixture that turns a freshly written tree into a one-commit repository
  (`git init`, `git add .`, `git commit`) may use `tests/git_template.py`'s
  `commit_fixture_tree`, which reuses a per-session `.git` of the same shape and
  spawns one git commit instead of three. Wait for a condition by polling with
  the old wait as the ceiling; keep a fixed sleep only where it proves that
  something did *not* happen.
- Import a research module whose import guard refuses the capture host only
  through `tests/host_guard.py`'s `import_or_skip_on_capture_host`;
  `test_capture_host_collection.py` collects the suite under capture-host
  emulation ([development.md](../docs/development.md#capture-host-collection-emulation)).
- If changing native-unit or model features, cover Celsius and Fahrenheit paths
  and verify training/serving parity where applicable.

- Never delete a test in one step: quarantine it first with
  `@pytest.mark.quarantine(reason=, added=, sunset=, replaced_by=)` plus a
  `tests/quarantine_registry.json` entry; the staged-cut rules live in [development.md](../docs/development.md).

- A test that only evaluates PowerShell logic (parse a script, define its
  functions, print JSON) may call `tests/powershell_host.py`'s `run_command`:
  one shared host per pytest process, a fresh runspace per call. Exit codes,
  kill-on-close jobs, timeouts, mutexes, the workload lease, `-File` startup
  and scheduled-task behaviour keep a real `powershell.exe` child.
- A test that runs a real scheduled-task registrar against stubbed Scheduler
  cmdlets starts its harness with `tests/scheduler_stubs.py`'s `prologue` and
  ends with `assert_only_stubs_invoked`. The real commands are CDXML functions
  that autoload, so a missing stub reaches the host scheduler. The prologue sets
  `WEATHER_TASK_TEST`, under which registrars that dot-source
  `scripts/ops/scheduled_task_test_guard.ps1` refuse any non-stub. A refusal case
  swaps a stub for `module_lookalike`; never just delete a stub.
- Tests that write large temporary layouts must stay under `tmp_path`. On a
  shared host pass an explicit `--basetemp` and delete it afterwards; pytest's
  default temp root is not cleaned promptly and has filled the capture disk.
  On Windows, `tests/conftest.py` swaps any base temp longer than 64 characters
  for a fresh `C:\pt\t-*` directory removed at exit, so nested `tmp_path`
  layouts never hit the 260-character path limit wherever the caller points it.

Run the narrow directory or file first, then the full suite:

```powershell
.\venv\Scripts\python.exe -m pytest tests\<owner> -q
# Workstation and CI only. On the 16 GB capture host a direct full run is
# forbidden at every hour; focused tests run serially inside 00:30-09:00 and the
# full suite only through scripts\ops\bounded_worktree_test_suite.ps1.
.\venv\Scripts\python.exe -m pytest -q
```

Host rules are owned by [the host load policy](../docs/operations/HOST_LOAD_POLICY.md)
and [development.md](../docs/development.md).

## Test hygiene (owner decision 2026-10-04)

From test-suite review K ([decision log](../docs/operations/DECISION_LOG.md) row of 2026-10-04; record:
[test-policy-proposals.md](../docs/research/test-suite-review-2026-10-04/test-policy-proposals.md)).
`tests/test_hygiene_ratchet.py` blocks new instances only (today's are in
`tests/hygiene_ratchet_baseline.json`; `python -m tests.hygiene_ratchet --report` explains a failure):

- each new test module's docstring has a `Guards:` line naming the contract, EF/RF/HWGTW id or incident;
- no `.ps1` text assert in a module that never executes PowerShell: add an execution test instead;
- no `_private` imports from `src/` or `app`;
- tests that start git or PowerShell carry `@pytest.mark.spawns`.

`tests/operations/test_source_control_bytes.py` (no baseline) refuses C0 control bytes other than tab, LF
and CR in `src/**/*.py` and `tests/**/*.py`: write `r"\b"`, never a literal backspace (a 2026-10-25 regex
held one and its test checked nothing).

Guidelines (not mechanically checked): `pytest.raises(match=...)` only when the refusal reason is the
contract; mutation-informed assertions as in
[development.md](../docs/development.md#verification-scope-and-assertion-strength-owner-decision-2026-10-04)
(both sides of each boundary, one case per guard clause where only it fires, statistics against an
independent value).

## Update this file when

Update when test layout, fixture policy, collection rules, or repository-wide
test invariants change.
