# 112. Single-Writer Loop Status And JSONL Integrity [COMPLETE 2026-06-17 - LOOP INTEGRITY GATE LIVE]

Goal: stop concurrent loop processes from corrupting status/log artifacts and
make malformed JSONL an explicit fleet health signal.

Source: 2026-06-16 log audit. `clob_loop_console.log` contained invalid JSON
lines and repeated `PermissionError: [WinError 5] Access is denied` failures
while replacing `clob_loop_status.json.tmp` with `clob_loop_status.json`.
`observation_trigger_console.log` and `loop_console.log` also contained
malformed/interleaved lines, and source-cache JSON parse failures appeared in
manual observation logs.

Why this matters: loop status files are control-plane evidence. If multiple
processes write the same status path or console log at the same time, the
dashboard can report stale or missing state even when the underlying loop is
running, and automation can chase false failures.

## Design

1. Enforce a single-writer lock per loop status file and per append-only JSONL
   log, with process identity recorded in the status payload.
2. Use atomic replace helpers for every JSON status/cache file that is read by
   another long-running process.
3. Write detached process logs to per-process files and merge them through a
   structured reader, or add a synchronized append wrapper that preserves one
   JSON object per line.
4. Add a fleet integrity check that reports malformed JSONL counts, status
   write failures, duplicate loop owners, and stale status files separately.
5. Add regression tests for concurrent writers, Windows replace failures, and
   malformed JSONL recovery.

- [x] Inventory all long-running loop status and console-log writers.
- [x] Add single-writer ownership and locking for status artifacts.
- [x] Move shared JSON cache/status writes onto atomic helpers.
- [x] Add malformed JSONL counts to fleet observability.
- [x] Add Windows-focused tests for duplicate writers and replace failures.

Acceptance: loop console logs remain parseable as JSONL, duplicate writers are
visible immediately, and status/cache readers no longer fail on partially
written JSON.

## Implementation Notes

- Added shared supervisor writer-lock helpers that create per-status
  `.writer.lock` files with PID, status path, loop name, module, and acquired
  timestamp.
- Snapshot, CLOB, and observation-trigger loops acquire a lifetime writer lock
  before writing shared status; duplicate loop writers append a
  `duplicate_writer_blocked` diagnostic and exit before corrupting status.
- Loop status payloads now include `status_writer` metadata so fleet
  observability can compare the active writer lock to the status owner.
- Shared JSONL integrity scanning counts malformed lines and keeps example
  parse errors without breaking readers.
- Fleet observability now includes a Loop Artifact Integrity section and emits
  loop-integrity alerts for malformed logs or duplicate writers.
- Existing shared `write_json_atomic` continues to use PID-specific temp files
  and retry `PermissionError` on replace; tests now pin the Windows retry path.

## Verification

- Live fleet observability reports loop integrity separately: `426` malformed
  historical log lines, zero duplicate writers, and matching active writer lock
  for observation trigger (`lock_pid == status_pid`).
- `python -m pytest -q tests\operations\test_runtime_utilities.py tests\market\test_market_microstructure.py tests\operations\test_observation_trigger.py tests\reporting\test_fleet_observability.py tests\operations\test_schema_registry.py`
  passes with `69 passed`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-17 - LOOP INTEGRITY GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

