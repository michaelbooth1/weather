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
- Prefer focused behavioral tests over snapshots of large generated reports.
  Assert fail-closed behavior for evidence, promotion, release, and live gates.
- If changing native-unit or model features, cover Celsius and Fahrenheit paths
  and verify training/serving parity where applicable.

- Tests that write large temporary layouts must stay under `tmp_path`. On a
  shared host pass an explicit `--basetemp` and delete it afterwards; pytest's
  default temp root is not cleaned promptly and has filled the capture disk.

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

## PROPOSAL (not in force until the owner approves): test hygiene ratchet

Draft from test-suite review K (2026-10-04); see
[test-policy-proposals.md](../docs/research/test-suite-review-2026-10-04/test-policy-proposals.md) (P1, P5).
`tests/test_hygiene_ratchet.py` would block new instances only (today's are in
`tests/hygiene_ratchet_baseline.json`; `python -m tests.hygiene_ratchet --report` explains a failure):

- each new test module's docstring has a `Guards:` line naming the contract, EF/RF/HWGTW id or incident;
- no `.ps1` text assert in a module that never executes PowerShell: add an execution test instead;
- no `_private` imports from `src/` or `app`;
- tests that start git or PowerShell carry `@pytest.mark.spawns`;
- guideline only: `pytest.raises(match=...)` when the refusal reason is the contract; assert both sides of
  each boundary and give each guard clause a case where only it fires.

## Update this file when

Update when test layout, fixture policy, collection rules, or repository-wide
test invariants change.
