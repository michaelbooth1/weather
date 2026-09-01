# Workstation handback — overnight operations reliability

**REPAIR_REQUIRED — the source branch contained real fail-closed gaps. They are
repaired and the complete workstation verification is green, but the canonical
roll verdict remains `UNDECIDABLE` until production supplies fresh live closure
evidence. This branch is not adoption or task-registration authority.**

Mission `2026-09-81a` was executed on the assigned 32 GB non-capture
workstation on 2026-09-01. The report filename is the path assigned by the
handoff. No real scheduled task or protected external system was touched.

## Identity

| Boundary | Commit | Tree / proof |
| --- | --- | --- |
| Required fetched source tip | `c49ade8338d123ea77c707e63a1943e3d2398c2b` | `e5b5267975d15dcf4e45e629365e417643323992` |
| Required implementation | `3e9b2c08c0f85468d1d5956cfd3bdcd0c7e3e2d3` | Required tree `d2d83251cd97a6f2f06997552f86e5954f77e82d`; ancestor check exit 0 |
| Workstation repair/evidence tip | `4ba5b8558671bafe72027453b30005a85137cba4` | `b1fec9d779fe1e518da6c28814c471f051abb241` |
| Workstation branch | `codex/workstation-overnight-ops-reliability-2026-09-81a` | Created directly from the exact fetched source tip; no merge or retarget |

The repair/evidence tip contains commits `511434d1daf84ae11086fc594f65897da89c4800`
and `4ba5b8558671bafe72027453b30005a85137cba4`. All executable verification
below binds to the latter through a detached worktree.

This tracked report cannot contain the hash or tree of the commit that carries
the report itself: inserting either value changes that commit and tree. The
external final handback therefore supplies the exact report-carrier tip/tree
and the live local, cached-remote, and `ls-remote` equality proof after push.
That is a self-reference boundary, not an omitted verification step.

## Review verdict and repairs

Every source-changed line was reviewed. The source direction was correct, but
text/source ratchets alone did not prove the unattended behavior and the review
found these concrete defects:

| Source defect | Workstation repair and deterministic proof |
| --- | --- |
| Same-date registrar invocations could race between scan and registration. | A target-date file mutex now owns scan, mutation, and readback. A held-mutex mock proves the concurrent invocation is refused before Scheduler mutation. |
| Only a narrow set of task states was considered active; queued and other ambiguous states could be mistaken for inert history. | Only disabled tasks and ready tasks whose next run is not future are inert. Running, queued, still-due, and unknown states fail closed. Active refusal and inert-history allowance are both exercised. |
| Registration/readback rollback swallowed disable uncertainty and did not prove final disabled state. | Rollback stops, disables, re-reads, and requires `Disabled`. Second-task registration failure proves the primary disabled; readback mismatch proves both disabled. |
| Registrar readback omitted root task path, principal user, trigger class/enabled state, and other exact bindings. | Readback now checks root `TaskPath`, principal `UserId`/S4U/Limited, exactly one enabled time trigger with no repetition, settings, and actions. |
| Date-format regexes admitted impossible calendar dates. | Registrar and successor now parse an actual invariant `yyyy-MM-dd` calendar date; the mocked registrar proves `2026-02-31` reaches no mutation. |
| A date-only receipt could be stale, unattributed, or race another attempt. | Primary and retry receipts are attempt-scoped, bind date/attempt/task, include offset timestamps, and publish through atomic temp-file replacement. |
| A never-run primary could remain due while its successor started. | The successor refuses a never-run primary whose next run is future, preventing overlap with a still-due attempt. |
| `SETTLED` did not prove every required all-market field or post-retry freshness. | Success requires schema/binding/refetch, run-correlated timestamps and mtime, a positive exact denominator, unique path-safe market IDs, exact total/settled counts, and zero unsettled/missing markets. The retry receipt must be new after invocation. |
| Watchdog JSON validity was only syntactic; `{}` could suppress an explicit blind alert. | Valid status now requires `OK`/`ATTENTION` plus `flags` and `warns`. The nested child exit is captured before parsing and appears in the blind alert. |
| Registry tests could inspect source without proving module execution from the tested checkout. | A subprocess executes `python -m weather.operations.settlement_backfill_registry`, requires the module path under the current checkout, and requires the exact unique 12-market fleet. |

No production code outside the overnight operations surface was changed to
make tests pass. Windows `MAX_PATH` was handled by a retained validation-only
pytest adapter, not by weakening the executor sandbox or changing host policy.

## Files changed on the workstation branch

The source tip already carried the canonical registry module, registrar,
successor, watchdog/root binding, source ratchets, operations documentation,
Item 324 note, and this mission handoff. Relative to that exact source tip, the
workstation changed:

- `scripts/ops/register_settlement_backfill_attempt.ps1` — concurrency,
  active-state classification, rollback proof, and exact readback;
- `scripts/ops/settlement_backfill_one.ps1` — attempt-bound atomic primary
  receipt;
- `scripts/ops/settlement_backfill_retry_one.ps1` — run/freshness binding,
  still-due refusal, exact all-market proof, and atomic retry receipt;
- `scripts/ops/health_watchdog.ps1` — injectable bound root and structural JSON
  validity while preserving child exit evidence;
- `tests/operations/test_settlement_backfill_scheduler_behavior.py` — real
  Windows PowerShell execution with Scheduler commands shadowed by isolated
  mocks;
- `tests/operations/test_settlement_backfill_registry.py` and
  `tests/operations/test_settlement_backfill_scripts.py` — executable registry
  and durable source-contract coverage;
- `docs/operations/OPERATIONS_DESIGN.md`, `scripts/ops/AGENTS.md`, and Item 324
  — owning contract and evidence updates;
- this handback report.

The validation-only files are ignored workstation evidence, not branch
content:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `pytest_preserve_subst_basetemp.py` | 4,670 | `1d5e7fe50070b03f71531fdc274055b6567874c1d7ad595ff230de474f8565d7` |
| `pytest_subst_nonexecutor_physical.py` | 849 | `09f033b51569abe0875874907015e5d10dda127b972ecad3fd237750367d7f87` |

The first file is byte-identical to the repository's previously validated
SUBST adapter. It preserves a prevalidated Q: spelling only after reparse
checks, shortens fixture names deterministically, and injects the same rule
into generated executor child guards. The small overlay confines Q: spelling
to `test_experiment_executor.py`; all other fixtures use the original physical
resolver so Git and Windows PowerShell agree on worktree identity. Each run
used a fresh ordinary `C:\tmp\q81a-*` backing directory, required Q: to be
unused, checked the exact mapping and non-reparse ancestry, removed only that
mapping in `finally`, and verified Q: absent after the wrapper Job exited.
The retained directories are test evidence and were not recursively deleted.

## Verification

All pytest and compileall commands used the exact project interpreter
`C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe`, an
absolute repository root, and the canonical host-bound
`scripts/ops/workstation_heavy.ps1` wrapper. The main checkout's managed ACL
denied creation of `data\logs\heavy_workload.lock`, so no lease was bypassed or
ACL weakened. Verification used detached worktree
`C:\tmp\w81a-4ba5b855` at the exact evidence commit, where the canonical lease
could function.

### Mocked Scheduler behavior

```powershell
& 'C:\tmp\w81a-4ba5b855\scripts\ops\workstation_heavy.ps1' `
  -Kind pytest `
  -PythonPath 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' `
  -ArgumentsBase64 'WyItbSIsInB5dGVzdCIsInRlc3RzL29wZXJhdGlvbnMvdGVzdF9zZXR0bGVtZW50X2JhY2tmaWxsX3NjaGVkdWxlcl9iZWhhdmlvci5weSIsIi1xIl0=' `
  -RepoRoot 'C:\tmp\w81a-4ba5b855'
```

Result: exit 0, `10 passed in 4.27s`. The suite shadowed every Scheduler command;
it did not register, start, stop, disable, or delete a real task.

### Focused operations and roadmap scope

The wrapper received the following Base64-decoded argument array; the adapter
setup and teardown described above surrounded the literal wrapper call.

```json
["-m","pytest","tests/operations","tests/reporting/test_roadmap_backlog.py","-q","-p","pytest_preserve_subst_basetemp","-p","pytest_subst_nonexecutor_physical","-p","no:cacheprovider","--basetemp","Q:\\q"]
```

Result: exit 0, `1,425 passed, 17 skipped, 77 subtests passed in 196.41s`.

### Compileall

```powershell
& 'C:\tmp\w81a-4ba5b855\scripts\ops\workstation_heavy.ps1' `
  -Kind compileall `
  -PythonPath 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' `
  -ArgumentsBase64 'WyItbSIsImNvbXBpbGVhbGwiLCItcSIsImFwcCIsInNyYyIsInRlc3RzIl0=' `
  -RepoRoot 'C:\tmp\w81a-4ba5b855'
```

Decoded command: `python -m compileall -q app src tests`. Result: exit 0 with
no output.

### Documentation checks

```powershell
& 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' `
  -m weather.operations.agent_docs_audit
& 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' `
  -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
```

Results before this report carrier:

- agent docs: exit 0, `PASS (18 agent files, 828 Markdown files)`;
- roadmap: exit 0, `Roadmap backlog: OK (generated report matches sources)`.

Both checks are rerun after the report and Item 324 update before the carrier
commit. That final rerun also passed: agent docs reported 18 agent files and
829 Markdown files, and roadmap lint/check again reported an exact generated
match. Those post-report results are the authoritative documentation verdicts.

### Complete repository suite

The wrapper received:

```json
["-m","pytest","-q","-p","pytest_preserve_subst_basetemp","-p","pytest_subst_nonexecutor_physical","-p","no:cacheprovider","--basetemp","Q:\\q"]
```

Result: exit 0, `4,235 passed, 22 skipped, 13 warnings, 862 subtests passed in
471.89s`. The warnings are the existing scikit-learn all-missing-feature and
NumPy/netCDF binary-size warnings; there were no test failures.

## Canonical roll verdict

The required command was run from the finished evidence branch:

```powershell
.\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-overnight-ops-reliability-2026-09-81a
```

Exact result: exit 1, `UNDECIDABLE: no live closure evidence`.

- `clob_enrichment`: 864.8 hours old, sole source for 21 files;
- `clob_loop`: 486.2 hours old, sole source for 23 files;
- `loop`: 486.2 hours old, sole source for 78 files;
- `observation_trigger`: 486.2 hours old, sole source for 83 files.

Because all closures were dormant beyond the canonical 24-hour limit, the
script exited before its changed-file phase and emitted no per-file rows. No
manual per-file or roll-free verdict is substituted. The branch must be
treated as roll-sensitive/undecidable until the same canonical command is run
where fresh live closure evidence exists.

## Safety and remaining production-only work

This was an implementation, mocked-scheduler, and deterministic test mission.
Market/date clusters, model fitting, training intervals, replay intervals, and
measurement estimands are not applicable. No production `data/` was copied or
rewritten. No provider, collector, exchange, credential, account, geoblock,
live execution, order, promotion, release, pointer, production master, merge,
or real Task Scheduler mutation occurred.

Remaining production-only steps are exactly:

1. rerun the canonical roll verdict with fresh live closure evidence and
   review its actual per-file output;
2. make a reviewed adoption decision under the existing integration and
   quiet-window contracts if that verdict requires them;
3. no earlier than a future admitted 00:30-09:00 window, register a new primary
   and successor for an actually open settlement date, then inspect their
   durable receipts.

A green workstation branch authorizes none of those steps. The spent August 30
task remains evidence and must not be recreated, deleted, or retried.
