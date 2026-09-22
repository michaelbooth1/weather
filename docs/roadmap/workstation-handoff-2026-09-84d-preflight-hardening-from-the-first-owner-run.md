# Workstation handoff 2026-09-84d — preflight hardening from the first owner run

Written 2026-09-22 by the production agent after walking the owner through the first real `preflight` runs on the
workstation (execution worktree `scratch\w\reward-test-attended-20260921` @ `7e6e1709c`, tunnel down, real
terminal). Three successive runs each stopped at a different `FAIL` line, and none of the three lines said why.
Two were environment defects in the script's assumptions, one was the selection rule working. This mission
removes the two defects and makes every `FAIL` line self-explanatory. It changes no money control, no venue call,
no selection rule and no attempt accounting. All 84a–85b boundaries bind unchanged; the execution worktree is not
touched, and the owner's sessions stay on `7e6e1709c` unless the owner decides otherwise.

## 1. What the owner saw (all times 2026-09-22 UTC; receipts under `%USERPROFILE%\.weather-re1m-20260921\`)

1. **12:59:19 — `{'status': 'FAIL', 'step': 'proxy_host_tip', 'exception_type': 'JSONDecodeError'}`.**
   `live_mutex()` (`re1_evidence.py`) spawns `powershell.exe -NoProfile -NonInteractive -Command …` with no
   `-ExecutionPolicy` argument. The workstation's policy was `Restricted`, so dot-sourcing
   `scripts/ops/workload_admission.ps1` printed "running scripts is disabled on this system" to stderr, stdout was
   empty and the exit code was **0** — `check=True` passed and `json.loads('')` raised. Diagnosis needed a hand-written
   probe (rc 0, STDOUT `''`, STDERR the policy text). The owner cleared it with
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
2. **~13:08 — `{'status': 'FAIL', 'step': 'credential_topology', 'exception_type': 'ModuleNotFoundError'}`.**
   `load_owner_credentials` (`re1_transport.py`) does `from dotenv import dotenv_values`; `python-dotenv` is declared
   in neither `pyproject.toml` nor `requirements.txt` and appears nowhere else in the repository. The owner installed
   it by hand into the RE-1 interpreter.
3. **13:16:12 — `{'status': 'FAIL', 'step': 'public_selection', 'exception_type': 'RuntimeError'}`.** This is
   `raise RuntimeError('no_qualifying_band')` — `selection.json` shows `ranked_conditions: []` and every row
   `eligible: false, refusal: "predicted_below_two"` (best: austin 09-23, `predicted_360_minutes` 1.34). Correct
   refusal; but the owner had to open a one-line JSON file to learn that nothing was broken.

Every one of the three also printed `{'status': 'FAIL', 'step': 'heartbeat_latency_budget', 'exception_type':
'TimeoutError'}`, because `timeouts.get('heartbeat', 8) >= 8` fires whenever the heartbeat was never measured. On a
run that failed at step one that line is noise that reads like a second defect.

## 2. Changes — five, all bounded

1. **`live_mutex` spawn** (`re1_evidence.py`): argument list becomes
   `['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command, str(REPO_ROOT)]`.
   Drop `check=True` in favour of an explicit check: if the return code is nonzero, stdout is empty, or stdout is not
   a JSON object with both keys, raise `RuntimeError('host_identity_query_failed: rc=<rc> stderr=<first 200 chars>')`.
   Those 200 characters are the child's own error text (policy, missing file, parse error) — pass them through the
   guard like everything else. Nothing else in the function changes: assignment check, Global mutex, poison file.
2. **`python-dotenv` declared**, not replaced. It parsed the owner's file correctly three times today; a home-grown
   reader could disagree with it silently on quoting or `export` lines, and that failure would look like
   `credential_fields_missing` or, worse, a wrong value. Pin it in `requirements.txt` and `pyproject.toml` exactly as
   the other pinned packages are, at the version `pip show python-dotenv` reports in the RE-1 interpreter. Add a test
   that every third-party top-level import under `src/weather/market/re1_*.py` resolves to a declared distribution
   (`importlib.metadata.packages_distributions()`), so the next undeclared import fails in the suite, not in a
   session.
3. **`FAIL` rows carry a message** (`re1_owner_checks.py`): the row becomes
   `{'step', 'exception_type', 'message'}` with `message = guard.clean(str(exc))[:200]`; same shape in the journal
   row, the printed line, the receipt's `failures` list and the `close` / `AccountNotEmpty` rows (`message` = a fixed
   string there). `clean_preflight` compares the receipt against the terminal journal row field-for-field, so the
   new key is covered automatically; confirm with the existing round-trip test.
4. **No band is a named outcome, still a `FAIL`**: before raising `no_qualifying_band`, print one guarded line
   `NO QUALIFYING BAND at <HH:MM>Z — best <location> <event_date> predicted_360_minutes=<x> (<refusal>); retry at
   the next quarter hour` computed from `table['rows']` (highest `predicted_360_minutes`; "none" if the table is
   empty), and journal it as `preflight_step` with `status='NO_BAND'` and the same numbers. The receipt keeps
   `status: FAIL` and the `public_selection` failure row (message `no_qualifying_band`), so `live` keeps refusing
   exactly as now. The selection rule itself is not touched.
5. **Derivative heartbeat failure suppressed**: append the `heartbeat_latency_budget` row only when the heartbeat was
   measured (`'heartbeat' in stats`) **or** when no failure was recorded at all (so an unmeasured heartbeat on an
   otherwise clean run still fails closed). A run that died at `proxy_host_tip` prints one `FAIL` line, not two.

## 3. Tests

- `tests/market/test_re1_evidence.py`: monkeypatch `subprocess.run` to capture the argument list; assert
  `'-ExecutionPolicy', 'Bypass'` appear, in that order, before `'-Command'`. Second case: the fake returns rc 0 with
  empty stdout and policy text on stderr → `RuntimeError` whose message starts `host_identity_query_failed` and
  contains the stderr text. Third: rc 1 → same. Fourth: valid JSON but a missing key → same.
- `tests/market/test_re1_owner_checks.py`: a preflight whose selection table has no `selected_condition_id` prints
  the `NO QUALIFYING BAND` line with the best row's numbers, records `status='NO_BAND'`, writes a `FAIL` receipt
  whose only failure row is `public_selection` / `no_qualifying_band`, and prints **no** `heartbeat_latency_budget`
  row. A run that fails at `proxy_host_tip` likewise prints exactly one `FAIL` row. A clean run whose heartbeat
  measurement is absent still gets the budget failure.
- The declared-dependency test from §2.2.
- Existing suites unchanged and green; the parity audit (`test_re1_attended_parity_audit.py`) must still pass — no
  selection or sizing code is touched.

## 4. What not to do

- Do not touch `re1_attended.py`, `re1_resilience.py`, `re1_public_books.py`, the payout modules or the reconciler.
- Do not check this branch out into the execution worktree, and do not run `preflight` or `live` yourself; the
  owner runs both. Do not read the root `.env` (variable names only) and do not print any value from it.
- Do not start a workstation full suite between 09:00 and 19:00 Eastern today (2026-09-22): the live session may be
  running. Focused tests at any hour; the full suite after 19:00 Eastern or the next night.
- Do not reword the printed `PASS`/`FAIL` tokens or the receipt keys the owner already knows; only add.

## 5. Boundaries and report

Branch `codex/re1-preflight-hardening-20260922` stacked on `4bb04b686` (the 85b tip), draft PR onto PR 83. Append
a dated 84d section to `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`:
verdict first in bold; the exact spawn argument list; the pinned `python-dotenv` line; a real `FAIL` row as now
printed; the `NO QUALIFYING BAND` line as printed by the test; suite counts; what was NOT done. Update the run card
in `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` so it lists the two environment prerequisites the owner met by
hand today (execution policy no longer required once §2.1 lands; `python-dotenv` installed by the pin) and says
that `NO QUALIFYING BAND` means "retry later", not "broken".

Adoption is the owner's decision: sessions 1–3 may all run on `7e6e1709c` (a new tip forces a fresh same-day
`preflight`, and the campaign root is shared across tips, so attempt counting is unaffected either way). Not
urgent for today's session; wanted before the second session's preflight.
