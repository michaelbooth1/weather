# Agent Report — 2026-07-21 (Stage-A admission budget Phase 1)

## Outcome

Phase 1 is complete on branch `admission-budget-rightsize-2026-07-21`.
Stage-A admission now has a distinct working-set expectation, while the existing
working-set budget remains the subprocess containment/kill ceiling. Every
production policy leaves the new expectation unset, so this change has zero
admission-behavior effect until Phase 2 supplies reviewed measured values.

Isolated child result envelopes now also record the child's own peak working
set and peak commit on a best-effort basis. The active child result schema is
`daily_refresh_step_child_v0.2`; `daily_refresh_step_child_v0.1` remains
registered as legacy schema metadata.

No scheduler, capture-loop, release, promotion, or `data/` action was performed.
No `daily_refresh` run or live `maker_paper_score` step was executed. Verification
used only focused tests with mocked memory and mocked step/subprocess execution.

## Admission design and exact formulas

Before Phase 1, the pre-start physical-memory requirement was:

```text
required_available_before_start_bytes
    = minimum_available_reserve_bytes
    + working_set_max_bytes
```

After Phase 1, materializing an isolated step budget first resolves:

```text
effective_admission_working_set_bytes
    = admission_working_set_bytes
      if admission_working_set_bytes is not None
      else working_set_max_bytes

0 <= effective_admission_working_set_bytes <= working_set_max_bytes

required_available_before_start_bytes
    = minimum_available_reserve_bytes
    + effective_admission_working_set_bytes
```

The upper-bound invariant is enforced with an explicit `AssertionError` guard,
so it is not removed by optimized Python execution. The non-negative lower bound
also prevents a configured expectation from undercutting the reserve through a
negative addend.

The admission record's `physical_memory` block now exposes both:

- `admission_working_set_bytes`: the effective pre-start expectation;
- `working_set_budget_bytes`: the unchanged containment/kill ceiling.

The post-child physical check remains reserve-only, exactly as before. Host
commit admission, the 1,536 MiB minimum reserve, capture-loop freshness checks,
and `available_memory_bytes` were not changed.

## Proof of byte-identical Phase-1 defaults

`_budget(...)` stores `admission_working_set_bytes=None` when the optional value
is omitted. All 16 configured isolated Stage-A policies use that omitted path;
none declares a lowered value. `step_resource_budget(...)` resolves each `None`
to that policy's existing `working_set_max_bytes`. Substitution into the new
formula gives:

```text
minimum_available_reserve_bytes + effective admission
= minimum_available_reserve_bytes + working_set_max_bytes
```

which is the old formula byte-for-byte.

For `maker_paper_score`, the Phase-1 default remains:

```text
1,536 MiB reserve + 3,072 MiB working-set ceiling
= 4,608 MiB
= 4,831,838,208 bytes
```

The all-policy fallback test verifies, for every configured isolated step, that
the raw policy value is `None`, the resolved admission equals the ceiling, and
the required byte total remains `reserve + ceiling`.

The subprocess containment path is independent of admission: daily refresh
continues to pass `budget["working_set_max_bytes"]` to
`run_isolated_subprocess`. A regression test temporarily sets a 1,024 MiB
admission expectation on a step with a 1,536 MiB working-set ceiling and proves
that the subprocess still receives the full 1,536 MiB kill ceiling.

## Peak-memory instrumentation

`daily_refresh_step_child.py` writes these top-level fields to every handled
success or failure `{step}.result.json`:

- `peak_working_set_bytes`
- `peak_commit_bytes`

On Windows, the child queries its current process with
`GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)` and maps
`PeakWorkingSetSize` and `PeakPagefileUsage`. The structure uses native-width
`SIZE_T` fields and explicit 64-bit-safe API signatures. On POSIX,
`resource.getrusage(RUSAGE_SELF).ru_maxrss` supplies peak working set, with the
Linux KiB versus macOS byte conversion; portable POSIX peak commit remains
`null`.

The OS query is isolated behind a best-effort wrapper. Query/import/platform
failures write both fields as `null` and do not alter the child result, status,
or return code. These child-own peaks complement, rather than replace, the
parent-observed process-tree resource peaks.

Current readers resolve the active schema through the registry and therefore
accept v0.2. Preexisting v0.1 receipts remain readable as legacy artifacts but
do not satisfy exact-current-schema automatic terminal recovery; this is the
existing fail-closed reader behavior.

## Tests and checks

Every pytest batch was preceded by a read-only check of
`data/logs/memory_commit_guard_status.json` and ran only when
`commit_percent < 70`.

Final focused batch, guard timestamp `2026-07-21T09:35:02.0446125-04:00`,
`commit_percent=41.4`:

```powershell
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m pytest `
  tests\operations\test_daily_refresh_step_child.py `
  tests\operations\test_daily_refresh_resources.py `
  tests\operations\test_daily_refresh.py `
  tests\operations\test_schema_registry.py -q
```

Result: **132 passed, 4 subtests passed** in 5.25 seconds.

This coverage includes:

- explicit admission threshold use and both operator-facing fields;
- all-policy default fallback and byte-identical required totals;
- all-policy `admission <= ceiling` validation and rejection above the ceiling;
- unchanged containment ceiling after a test-only lower admission value;
- unchanged daily-refresh admission, deferral, loop, commit, and recovery tests;
- peak fields on child success and child failure;
- nullable peak fields without status/return-code change when the mocked OS
  query fails;
- active v0.2 and legacy v0.1 schema registration.

One earlier combined run exposed only a new test assertion using the wrong
resource-record key (`process_budget` instead of `budget`); the assertion was
corrected before the clean final batch. Production code was unaffected.

Additional checks:

```powershell
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m compileall -q app src tests
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
git diff --check
```

Results: compileall passed; agent docs audit passed for 18 agent files and 456
Markdown files; diff whitespace check passed. Independent read-only reviews
found no safety, ctypes, schema-consumer, containment, or scope violations.

## Branch and commit IDs

- Worktree: `C:\Users\micha\Desktop\github\weather-admission-budget-rightsize-2026-07-21`
- Branch: `admission-budget-rightsize-2026-07-21`
- Base/current-master commit: `b8a0c806cbf8dab1a9a185fac3f7439528fae322`
- Implementation commit: `88366e8b8da10ebd74c370186f1f9bdc2c8e384e`

The branch was not merged or pushed.
