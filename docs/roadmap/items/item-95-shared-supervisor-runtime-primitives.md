# 95. Shared Supervisor Runtime Primitives [COMPLETE 2026-06-16 - SHARED SUPERVISOR PRIMITIVES LIVE]

Goal: extract the repeated background-loop supervision mechanics into a shared
operations runtime module.

Source: 2026-06-16 architecture review. Snapshot capture, CLOB capture, and
observation-trigger loops each implement their own status files, atomic writes,
diagnostics, PID checks, detached process launching, health decisions, restart
logic, and supervisor locks.

Why this is missing: each managed loop was hardened as operational needs
appeared. The implementations are tested, but they now duplicate process-control
and status semantics in separate modules.

- [x] Add `weather.operations.supervisor` with small primitives for atomic JSON
  status writes, JSONL diagnostics, lock acquisition/release, Python process
  checks, detached child launch, stop requests, heartbeat age, and health-state
  decisions.
- [x] Define a `SupervisorSpec` or equivalent data object for loop-specific
  paths, command args, pause flag, stale thresholds, tolerated states, and
  status schema fields.
- [x] Migrate snapshot capture supervision to the shared primitives while
  preserving existing status JSON keys and CLI output.
- [x] Migrate observation-trigger supervision and CLOB supervision after the
  shared API has proven stable.
- [x] Keep loop-specific policy local where it is genuinely domain-specific,
  such as CLOB orphan-process detection and fast-interval selection.
- [x] Add focused tests for supervisor decisions, lock behavior, atomic writes,
  stale heartbeat handling, and detached command construction.

Acceptance: the three managed loops share one process/status supervision layer,
their existing operator commands and status artifacts remain compatible, and
future managed loops do not need to copy lifecycle code.

## Design

Separate generic process mechanics from loop-specific work.

- Generic: status IO, diagnostics, heartbeat freshness, lock file behavior,
  launch/stop commands, PID validation, stale-code restart policy, and
  pause/dead/error/running state normalization.
- Loop-specific: capture function, market selection, result summaries, special
  orphan detection, cadence changes, and domain diagnostics.
- Existing JSON schemas are operational artifacts. Migrations should be
  backward compatible or explicitly versioned.

Verification strategy:

- Existing snapshot supervisor, CLOB supervisor, observation-trigger, and
  operations dashboard tests.
- New pure tests for the shared supervisor primitives.
- Manual smoke checks for `status`, `ensure`, `restart`, `stop`, and `loop`
  commands where practical.

## Completion

Completed 2026-06-16.

- Added `weather.operations.supervisor` with shared primitives for
  `SupervisorSpec`, canonical module-command construction, atomic JSON status
  writes, JSONL diagnostics, heartbeat age/state helpers, Python PID checks,
  Python process termination, detached child launch, and stale file locks.
- Migrated snapshot capture supervision to those primitives while preserving
  the existing `read_loop_status`, `write_loop_status`, `append_diagnostic`,
  `pid_is_python`, `start_loop_detached`, `stop_loop`, and `ensure_decision`
  call surfaces.
- Migrated observation-trigger supervision to shared JSON/JSONL, lock, PID,
  termination, and detached-launch helpers. Its source-identity restart policy
  remains local.
- Migrated CLOB supervision to shared JSON/JSONL, lock, PID, termination, and
  detached-launch helpers. Its orphan-process detection, fast cadence policy,
  and market-specific health details remain local.
- Fixed observation-trigger status/diagnostic/lock wrappers to resolve default
  paths at call time, which keeps tests and future callers from writing to live
  operational artifacts when path constants are monkeypatched.
- Added `tests/operations/test_supervisor.py` for the shared primitives and
  added detached-start compatibility coverage for snapshot and observation
  supervisors. Existing CLOB detached-start coverage now exercises the shared
  launch helper.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\operations\test_supervisor.py tests\collection\test_loop_supervisor.py tests\market\test_market_microstructure.py tests\operations\test_observation_trigger.py -q`
  (54 passed)
- Non-mutating CLI status smokes passed for snapshot capture, CLOB capture, and
  observation-trigger supervisors.
- `.\venv\Scripts\python.exe -m pytest -q` (814 passed, 491 subtests passed)
