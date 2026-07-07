# 161. Loop Restart Noise And Current-Code Cadence Proof [PARTIAL 2026-06-25 - JUNE 25 SOAK BLOCKED, NEW CLEAN SOAK NEEDED]

Goal: reduce supervisor restart noise and prove that current-code loops can
hold cadence across a full active day.

Source: the raw June 13-20 diagnostics. The audit found many restarts and
duplicate-writer blocks: snapshot diagnostics had 213 restarts, CLOB diagnostics
540 restarts, and observation-trigger diagnostics 248 restarts in the inspected
window. Top causes included stale-code identity mismatches, duplicate-writer
blocks, access-denied status writes, and earlier disk-full errors. Current
status files show the loops running on the latest commit with zero consecutive
errors, but that is not yet a cadence proof.

Why this matters: restart supervision is useful only if it converges to stable
single-writer collection. Repeated restarts can create exactly the cadence gaps
that block broad live-forward SLOs, even when the latest status looks healthy.

## Design

1. Add a restart taxonomy across snapshot, CLOB, and observation-trigger
   diagnostics: stale code, duplicate writer, process dead, hung heartbeat,
   disk/backpressure, permission/write error, and manual/operator restart.
2. Define a restart budget for a countable active day.
3. Add a current-code soak report that proves runtime identity stayed current,
   no duplicate writer persisted, and cadence remained within threshold.
4. De-duplicate benign `duplicate_writer_blocked` events from true duplicate
   writer incidents.
5. Feed restart counts and soak status into fleet observability and daily
   progress.

- [x] Add loop restart taxonomy fields to diagnostics or a derived report.
- [x] Add restart budget thresholds per loop for active-day countability.
- [x] Add a current-code soak summary to fleet observability.
- [x] Add tests for stale-code restart convergence and duplicate-writer
  classification.
- [ ] Run one active-day soak with current runtime identity and no cadence SLO
  failures.

## 2026-06-20 Update

Implemented `current_code_soak` in fleet observability and daily learning.
The derived report classifies seven-day diagnostics into restart causes
(`stale_code`, `duplicate_writer_blocked_benign`,
`duplicate_writer_incident`, `duplicate_writer_prevention`,
`process_dead_or_hung`, `hung_or_erroring_heartbeat`,
`permission_write_error`, `disk_backpressure`, and operational/manual
events) while applying restart budgets over the latest 24-hour window.

Current generated evidence:

- Soak status is `BLOCK`; `counts_toward_active_day=False`.
- All 3 managed loops report current runtime code and single-writer status.
- The latest 24-hour restart budget still fails: snapshot `273 > 6`, CLOB
  `272 > 12`, observation-trigger `571 > 12`.
- Seven-day taxonomy still shows `3959` restart-class events, including
  `1024` stale-code events, `79` duplicate-writer incidents, and `209` benign
  duplicate-writer blocks.
- Observation-trigger is still not countable in the generated proof because it
  was `DEGRADED` with `consecutive_errors=1` at report time.
- Fleet and daily learning now render `## Current-Code Soak Proof`; daily
  learning emits a P0 `current_code_soak` learning when the proof blocks.

Remaining blocker: run and retain one full active-day soak where all loops stay
current-code, single-writer, under budget, and the live-forward cadence SLO
passes.

## 2026-06-20 Loop-Log Cleanup Follow-Up

`weather.operations.loop_jsonl_repair` now fails closed when asked to repair a
managed loop console log whose writer lock belongs to a live process, unless
the operator passes `--allow-active`. This prevents active-writer rewrites from
creating sparse/NUL-filled console-log gaps. The cleanup quarantined the prior
malformed console text and repaired the final active CLOB sparse-line artifact
after stopping the CLOB writer.

I also fixed the observation-trigger supervisor stop/start path. It now removes
the stopped or dead writer PID's lock before launching a detached watcher, and
blocks start when a live writer lock is still present. This matches the
snapshot/CLOB supervisor behavior and prevents restart attempts from producing
short-lived watchers that immediately exit with `duplicate_writer_blocked`.

New evidence:

- `data/backtest/loop_jsonl_repair_final_fixed_supervisor_audit.md`: `PASS`,
  malformed lines `0` across snapshot, CLOB, and observation-trigger console
  logs.
- `data/backtest/fleet_observability_after_observation_lock_fix_report.md`:
  loop artifact integrity `OK`, duplicate writers `0`, and all three managed
  loops `RUNNING`, current-code, single-writer, with zero consecutive errors.

The soak item remains `PARTIAL`, not complete. The same fleet report still
blocks on historical restart and duplicate-writer incident counts inside the
soak window: snapshot `298>6` restarts with 4 incidents, CLOB `294>12` with 34
incidents, and observation-trigger `618>12` with 48 incidents. A future active
day must age out that noise and keep the cadence SLO passing.

## 2026-06-20 Post-Resume Refresh

The daily-refresh resume regenerated fleet observability after the promotion
step completed. Loop artifact integrity remains `OK`, malformed lines are `0`,
and all three managed loops still report current-code and single-writer status.
The current-code soak proof remains blocked by the latest 24-hour restart
budget and the cadence SLO: total restart count `1226`, seven-day diagnostic
restart-class events `4080`, and first blocker `snapshot_capture` with
`restart_budget_exceeded=304>6; duplicate_writer_incidents=4`.

## 2026-06-22 Active-Day Window Readiness Update

Fleet observability now separates active-day countability blockers from
seven-day diagnostic context. Duplicate-writer incidents use the same 24-hour
countability window as restart budgets; the seven-day count remains in
`diagnostic_duplicate_writer_incident_count` for taxonomy/history.

Current regenerated evidence:

- `data/backtest/fleet_observability.json` still has `current_code_soak`
  `BLOCK` and `counts_toward_active_day=False`.
- Active-day duplicate-writer incidents are now `0`; seven-day diagnostic
  duplicate-writer incidents remain `86`.
- Restart budgets still block all three loops: snapshot `228>6`, CLOB
  `226>12`, and observation-trigger `263>12`.
- The latest restart-budget aging blocker clears at
  `2026-06-22T18:26:13.925019+00:00` if no new restarts occur.
- Two malformed console-log lines still block artifact hygiene:
  `data/snapshots/loop_console.log` and
  `data/snapshots/observation_trigger_console.log`.
- The normal repair command intentionally skipped both console logs because
  live writer locks were present (`active_writer_lock`). Repair should happen
  during a maintenance pause before the next countable active-day soak, then
  the loops should be restarted once and left to age through the 24-hour
  restart window.

Acceptance: fleet observability can prove a full active day where all managed
loops stayed current-code, single-writer, under restart budget, and within
cadence thresholds; otherwise it reports the exact loop, restart class, and
owner blocking countability.

## 2026-06-22 Maintenance Repair

The two remaining malformed loop-console lines were both expected cache-lock
warnings emitted as plain text into JSONL-style console logs. I added a shared
JSON-line logging formatter for managed loop modes, wired it into the snapshot,
CLOB, and observation-trigger loop entrypoints, stopped the managed loops,
repaired the affected console logs while no writer was alive, and restarted the
loops on current source.

Evidence:

- `python -m pytest tests/operations/test_supervisor.py tests/operations/test_loop_jsonl_repair.py tests/model/test_source_cache_ttl.py -q`
  passed (`33 passed`).
- `python -m pytest tests/collection/test_loop_supervisor.py tests/operations/test_observation_trigger.py tests/market/test_market_microstructure.py -q`
  passed (`67 passed`).
- `python -m weather.operations.loop_jsonl_repair repair data/snapshots/loop_console.log data/snapshots/observation_trigger_console.log`
  produced `PASS`.
- The refreshed `data/backtest/fleet_observability.json` has
  `loop_integrity_status=OK`, malformed lines `0`, duplicate writers `0`, and
  all three loops `RUNNING`, current-code, and single-writer on
  `master@1e175b4428b7 src:f0eef80ee37a7f33`.
- `current_code_soak.summary.immediate_repair_loop_count=0`; the first blocker
  is now only `snapshot_capture restart_budget_exceeded=293>6`.

The item remains partial because all three restart budgets still exceed the
countable active-day thresholds: snapshot `293>6`, CLOB `293>12`, and
observation-trigger `315>12`. If no further restarts occur, the latest aging
blocker clears at `2026-06-23T03:48:21.125579+00:00`, after which the proof
still needs a clean active day with the cadence SLO passing.

## 2026-06-22 Midnight Fleet Refresh

Regenerated `data/backtest/fleet_observability.json` at
`2026-06-22T04:20:04Z` after the source-family inventory fix and the managed
loop restart at the new current source fingerprint `ce533797aeb70c1d`.

The structural loop hygiene remains good:

- `loop_integrity_status=OK`
- malformed JSONL lines: `0`
- duplicate writers: `0`
- all three managed loops are `RUNNING`, single-writer, `consecutive_errors=0`
- current loop identity: `master@1e175b4428b7 src:ce533797aeb70c1d`

The item still cannot close because the current-code soak remains `BLOCK`.
There are no immediate repair loops, but all three restart budgets are still
inside the 24-hour aging window:

- snapshot capture: `296>6`, clearing at `2026-06-23T03:50:15.286515+00:00`
- CLOB capture: `295>12`, clearing at `2026-06-23T03:30:12.682470+00:00`
- observation trigger: `319>12`, clearing at `2026-06-23T03:29:59.356290+00:00`

Next unblock: leave the loops running on `ce533797aeb70c1d` through the aging
window, then rerun fleet observability after `2026-06-23T03:50:15Z`. Completion
still requires the restart budgets and the snapshot cadence SLO to pass.

## 2026-06-24 Active-Day Soak Failure Evidence

The 2026-06-24 taker audit shows the current-code soak is still not countable.
By end-of-day review, the snapshot loop was `DEAD` after a stale-code exit and
CLOB capture was also `DEAD`, with last captured books around 11:39 EDT. The
taker bot process remained alive, but its latest scoring tick was empty and the
run report classified the zero-trade root cause as `crashed_before_scoring`.

This evidence belongs here as a soak failure, not as a completed restart-budget
proof. The open acceptance remains unchanged: retain a full active day where
snapshot, CLOB, and observation-trigger loops stay current-code, single-writer,
under restart budget, and within cadence thresholds.

## 2026-06-25 Soak Refresh

the generated status cache by default. The refreshed
`data/backtest/fleet_observability.json` was generated at
`2026-06-25T18:47:03Z`, but the current-code soak is still `BLOCK` and
`counts_toward_active_day=False`.

Current loop state:

- Snapshot: `RUNNING`, current code, single writer, but restart budget `38>6`
  until `2026-06-26T15:02:13.212901+00:00`.
- CLOB: `RUNNING`, current code, single writer, but restart budget `25>12`
  until `2026-06-26T14:56:12.808360+00:00`.
- Observation trigger: `RUNNING`, current code, but restart budget `14>12`
  until `2026-06-25T22:21:16.195105+00:00`.
- Taker daily roll: `PASS`, `RUNNING`, current code, `6/12` restarts.
- Market-making daily roll remains a scheduled-start blocker before its local
  start window; the immediate command is
  `python -m weather.operations.market_making_daily_roll ensure`.

The cadence side also blocks the soak: `live_forward_slo=BLOCK` because all 12
markets have nonrecoverable June 25 `snapshot_coverage_gap` evidence. This is a
fresh failed soak, not completion evidence. The next acceptable proof is still a
future active day with current-code loops under budget and live-forward cadence
passing.
