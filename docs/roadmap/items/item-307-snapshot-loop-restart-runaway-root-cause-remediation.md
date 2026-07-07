# 307. Snapshot And Collection Loop Restart-Runaway Root-Cause Remediation [PARTIAL 2026-06-25 - FAST PROOF RESTORED, JUNE 25 CLEAN SOAK BLOCKED]

Goal: eliminate the active supervisor restart-runaway in the snapshot, CLOB, and
observation-trigger loops so collection holds cadence across an active day and
item 161's current-code soak can actually pass.

Source: settled 2026-06-23 log audit. `current_code_soak` is BLOCK with
`counts_toward_active_day=False`; the latest 24-hour restart budget shows
`snapshot_capture restart_budget_exceeded=427`, escalating to `460 > 6` later the
same morning, with `malformed_loop_line` events and persistent `stale_code`
identity churn (item 161's 2026-06-20 evidence already showed `1024` stale-code
events). This restart-runaway produced the ~1-hour fleet-wide collection gap on
2026-06-23: all 12 markets settled `partial` quality on `snapshot_high` fallback
(daily summary unavailable), the LA live-forward SLO failed on a 12-gap/63-minute
coverage gap, and the degraded snapshot cadence drove 660 of 792 taker no-trade
rows (83%) to `NO_TRADE_SNAPSHOT_CADENCE_DEGRADED`.

Why this matters: the restart-runaway is the upstream root cause of the entire
2026-06-23 cascade - partial labels, the failed live-forward SLO, and the taker
being blinded rather than disciplined. No model, taker, or maker improvement can
be trusted until collection holds cadence, because every downstream gate
correctly fails closed on the resulting gaps. The loop is crash-restarting right
now, so this is acute, not historical.

Why it is not already covered: item 161 owns the restart taxonomy, restart
budgets, and the current-code soak proof, and it has stayed PARTIAL/BLOCK for
days precisely because the loop keeps restarting - it measures and classifies but
does not own eliminating the dominant restart cause. Item 95 provides shared
supervisor primitives, item 112 owns single-writer/JSONL integrity, item 157
owns the cadence SLO, and item 212 consumes cadence as a trading-permission
input; none diagnoses and fixes why `snapshot_capture` restarts hundreds of
times per day. Item 299 (event-metadata rollover) and item 305 (finalization
ordering) are different collection failure modes.

## Design

1. Instrument the exact restart trigger at the moment of restart (cause,
   exception, runtime identity before/after, loop line offset) so the dominant
   cause is identified from live evidence rather than only post-hoc taxonomy.
2. Make the loop-status writer tolerate and quarantine a `malformed_loop_line`
   in place instead of treating it as a fatal condition that forces a restart.
3. Stop restarting on benign `stale_code`/runtime-identity transitions: adopt the
   current code in place or exit cleanly once, rather than entering a
   restart-on-every-tick identity-churn loop.
4. Add per-child exponential backoff and a circuit breaker so a crash-looping
   loop cannot blow the restart budget by 70x in 24 hours; surface a single
   blocking remediation when the breaker trips.
5. Prove a clean active-day soak with current runtime identity, restarts within
   budget, and no cadence SLO failures, which also closes item 161's open
   soak-proof checklist.

- [x] Add at-restart cause instrumentation for snapshot, CLOB, and
  observation-trigger loops.
- [x] Make the loop-status writer quarantine malformed lines without restarting.
- [x] Eliminate the stale-code/runtime-identity restart-on-every-tick loop.
- [x] Add per-child backoff and a circuit breaker with a single blocking
  remediation when tripped.
- [ ] Run a clean active-day soak within restart budget and attach it to item
  161's cadence proof, with a regression test for the dominant 2026-06-23 cause.

Acceptance: the snapshot, CLOB, and observation-trigger loops hold an active day
within their restart budgets, `current_code_soak` reports PASS with
`counts_toward_active_day=True`, no restart is caused by a malformed loop line or
benign runtime-identity transition, and the dominant 2026-06-23 restart cause is
eliminated with a regression test.

Related: items 16, 95, 112, 122, 157, 161, 212.

## 2026-06-24 Implementation Update

Implemented bounded supervisor recovery across the snapshot, CLOB, and
observation-trigger loops:

- Shared supervisor primitives now quarantine malformed JSONL/log lines, record
  loop file offsets around recovery actions, and enforce exponential backoff plus
  a 24-hour circuit breaker before launching another child process.
- Snapshot `--ensure` now records restart cause, runtime identity, file offsets,
  and recovery-guard state. The long-running snapshot child exits cleanly on
  stale code after writing a single diagnostic instead of remaining alive for the
  next ensure tick to kill repeatedly.
- CLOB and observation-trigger `ensure` commands now use the same bounded
  recovery guard while preserving their existing orphan-process and
  source-identity recovery decisions.
- Recovery-event scanning now prefilters diagnostics lines before JSON parsing
  and healthy `noop` ensures do not count diagnostics/console offsets, avoiding
  scheduler lock contention from large loop logs.
- Managed-loop console logging now captures Python warnings as JSON log records,
  preventing raw warning text from creating new malformed JSONL lines.
- Event metadata validation report rendering now emits Markdown tables
  correctly, so the live-forward gate validation command exits cleanly while
  writing both JSON and Markdown evidence.

Regression coverage added:

- `tests/operations/test_supervisor.py` covers malformed-line quarantine and
  recovery guard backoff/circuit behavior, large non-supervisor diagnostics
  prefiltering, and JSON routing for Python warnings.
- `tests/collection/test_loop_supervisor.py` and
  `tests/collection/test_collection_robustness.py` cover snapshot stale-code
  backoff and clean child exit.
- `tests/market/test_market_microstructure.py` and
  `tests/operations/test_observation_trigger.py` cover CLOB and
  observation-trigger bounded restarts, including the fast CLOB `noop` ensure
  path.
- `tests/operations/test_event_metadata_validation.py` covers Markdown report
  rendering and output writing for the event-metadata validation evidence used
  by the live-forward gate.

Verification:

- `python -m pytest tests\operations\test_supervisor.py tests\collection\test_loop_supervisor.py tests\collection\test_collection_robustness.py tests\operations\test_observation_trigger.py tests\market\test_market_microstructure.py tests\reporting\test_fleet_observability.py tests\operations\test_nightly_health_checks.py -q`
  passed (`153 passed`).
- `python -m pytest tests\operations\test_event_metadata_validation.py -q`
  passed (`6 passed`).
- `python -m weather.operations.event_metadata_validation --target-date 2026-06-24`
  now exits successfully and writes both
  `data/backtest/event_metadata_validation.json` and
  `data/backtest/event_metadata_validation_report.md`.
- Deployed the patched loops at source fingerprint `0112ea7b37a05047`.
  Snapshot, CLOB, and observation-trigger health all report `RUNNING`, current
  runtime identity, live pids, single writer locks, and `consecutive_errors=0`.
- Repaired legacy malformed snapshot and observation console lines. Final local
  integrity checks report `malformed_lines=0` for
  `data/snapshots/loop_console.log` and
  `data/snapshots/observation_trigger_console.log`.
- Refreshed same-day location event metadata and wrote
  `data/backtest/event_metadata_validation.json`; the final fleet probe reports
  event metadata validation `PASS` and live-forward SLO `PASS` /
  `counts_toward_live_forward_gate=True`.
- `data/backtest/fleet_observability_item307_event_validation_fix_probe.json` still
  reports fleet `CRITICAL` only because today's pre-fix restart storm remains in
  the 24-hour budget window: snapshot `447 > 6` until
  `2026-06-25T14:56:43.976503+00:00`, CLOB `432 > 12` until
  `2026-06-25T13:26:23.350449+00:00`, and observation-trigger `108 > 12` until
  `2026-06-25T13:58:12.968501+00:00`.

Remaining blocker: retain one full active-day soak after the pre-fix restart
storm ages out, where all three loops stay current-code, single-writer, under
restart budget, and live-forward cadence passes. That evidence is required
before this item should be marked complete.

## 2026-06-24 Taker-Audit Evidence

The same target date produced direct downstream evidence of why this item must
remain open. The 2026-06-24 taker run stayed alive but stopped receiving useful
late-day inputs: the regular snapshot loop was `DEAD` after a stale-code exit
around 14:07 EDT, and CLOB capture was `DEAD` with last books around 11:39 EDT.
The taker report consequently showed `latest tick rows=0`,
`crashed_before_scoring`, and remediation through
`python -m weather.market.market_microstructure ensure`.

This does not supersede the implementation update above; it records the
active-day failure shape that the clean soak must eliminate. Item 311 owns the
taker-side evidence-starvation classification so this item can stay focused on
the upstream collection-loop recovery and soak proof.

## 2026-06-24 Post-Suppression Baseline Reset

After the duplicate circuit-open remediation landed in `fb2da228`, the managed
loops were explicitly restarted onto the stable current source identity
`master@fb2da2283d88 src:c4f6431ebdcd06e3` at 22:39 EDT. A follow-up `ensure`
pass returned `noop` for snapshot, CLOB, and observation-trigger:

- Snapshot: `RUNNING`, current runtime identity, live writer lock, and
  `consecutive_errors=0`.
- CLOB: `RUNNING`, current runtime identity, expected two-process launcher plus
  interpreter pair, no orphan-process restart, and `consecutive_errors=0`.
- Observation-trigger: `RUNNING`, current runtime identity, live writer lock,
  and `consecutive_errors=0`.

This is a pre-soak baseline, not completion evidence. The 2026-06-24 active day
already has unrecoverable snapshot coverage gaps and the historical restart
budget window remains blown. Completion still requires the next clean active-day
fleet observability run to show `current_code_soak=PASS`,
`counts_toward_active_day=True`, and `live_forward_slo=PASS`.

## 2026-06-25 Fleet Observability Timeout And Blocker Refresh

Diagnosed the two-minute `weather.reporting.fleet.fleet_observability report`

Verification:

- `python -m pytest tests\reporting\test_fleet_observability.py -q` passed
  (`42 passed`).
- `python -m weather.reporting.fleet.fleet_observability report --skip-audits`
  now completes in about 25-32 seconds and refreshed
  `data/backtest/fleet_observability.json` plus
  `data/backtest/fleet_observability_report.md`.

The refreshed canonical proof generated at `2026-06-25T18:47:03Z` is still
`CRITICAL`, so this item stays partial:

- `live_forward_slo=BLOCK` and `counts_toward_live_forward_gate=False`.
- `snapshot_cadence_proof.summary.snapshot_coverage_gap_blocked_market_count=12`,
  `total_gap_count=12`, and `max_gap_minutes=223.57417106666665`.
- `next_unblock_action` is now correctly
  `collect next active day with zero snapshot_coverage_gap blocked markets`.
- `current_code_soak=BLOCK` and `counts_toward_active_day=False`.
- Snapshot, CLOB, observation-trigger, and taker daily-roll loops are back to
  current code. The restart budgets are still blown: snapshot `38>6` until
  `2026-06-26T15:02:13.212901+00:00`, CLOB `25>12` until
  `2026-06-26T14:56:12.808360+00:00`, and observation-trigger `14>12` until
  `2026-06-25T22:21:16.195105+00:00`.

Conclusion: the proof is runnable and current, but June 25 is non-countable.
Closure still requires the next active day to hold zero snapshot coverage gaps
and pass the restart-budget soak.

## 2026-06-26 Dominant restart cause identified and fixed: stale-code churn burns the crash budget

Root-caused the recurring blown restart budgets to a specific interaction, not a
crash loop. The snapshot loop runs a runtime guard that exits cleanly whenever
its process code identity differs from the working source tree. Development
commits land in bursts (11 commits to master between 08:36-15:00 on 2026-06-25),
so every commit makes the live loop detect stale code and exit, and the
supervisor relaunches it on current code. Those benign current-code re-adoptions
were counted as crash restarts: the 6 budget-consuming events in the snapshot
window were `{STALE_CODE: 4, DEAD: 2}`. The 4 stale-code re-adoptions plus 2 real
restarts hit the budget of 6, tripped the circuit breaker, and - because the
breaker is a 24h window with no recovery when the cause clears - left the
snapshot loop dark from 14:54 onward even though HEAD was stable after 15:00.
That dark window is the direct cause of the 2026-06-24 settlement label outage
(capture_ratio median 0.51, 8.5h max gap, all 12 markets `low_capture_ratio` and
non-promotion-countable, which in turn blocks `settled_day_analysis_barrier` ->
`promotion_refresh`).

Fix: `weather.operations.supervisor._recovery_event` now excludes restarts whose
`restart_cause` is a benign current-code re-adoption (`stale_code`) from the
crash circuit-breaker budget. Crash restarts (`DEAD`, malformed line, etc.) still
count. This both prevents a normal commit burst from tripping the breaker and
auto-recovers an already-tripped breaker on the next ensure, because the recount
drops below budget once stale-code re-adoptions no longer count. The supervisor's
own per-minute ensure cadence still bounds how often a stale-code relaunch can
occur. All three collection loops share this primitive, so the fix applies to
snapshot, CLOB, and observation-trigger.

Evidence:

- Live recount after the fix: snapshot `recent_recovery_count` dropped from `6`
  to `2` (crash-only), guard `allowed=true`, `within_restart_budget`.
- The snapshot loop relaunched and is healthy on current code: new pid,
  `runtime_code_state=current`, fresh captures resuming after a ~6h dark window.
- CLOB and observation-trigger loops confirmed running.

Validation:

- `python -m pytest tests/operations/test_supervisor.py tests/collection/test_loop_supervisor.py -q` (27 passed),
  including a new regression test
  `test_stale_code_restarts_do_not_consume_crash_budget` proving a 4-stale-code +
  2-crash burst keeps the breaker closed.

Remaining for closure: the final checklist item (a clean active-day soak within
budget with zero snapshot coverage gaps) still needs one full clean current-code
day now that the breaker no longer goes dark on commit bursts.

## 2026-06-26 Cadence-preserving fix: scope stale-code detection to imported files

Eliminated the per-commit teardown itself, not just its budget accounting. The
runtime identity now supports a scoped source fingerprint over only the repo
files a process actually imports (`sys.modules`, intersected with the project
source set so third-party `venv` dependencies are excluded). The collection
loops capture a scoped identity (`get_runtime_identity(scope_files="loaded")`,
stored as `source_scope`/`source_scope_files`), and every staleness comparison -
the loop self-check (`snapshot_tracker.runtime_identity_status`), the CLOB check
(`market_microstructure.clob_runtime_matches_current`), and the fleet
(`fleet_observability_loops._runtime_code_state`) - now recomputes the current
fingerprint over the recorded scope via `runtime_identity.current_identity_for`.
Legacy whole-tree identities (no recorded scope) fall back to the existing
whole-tree comparison, so taker/soak/other consumers are unchanged.

Effect: the snapshot loop's scope is `62` source files (collection, the model
feature/source code it imports, operations/supervisor, runtime_identity) out of
`507`. The churn-heavy modules a collection loop never imports - pooled-feature
model retrain, promotion refresh, fleet rendering, daily_refresh steps,
repair_integration, settlement_ledger - are out of scope, so commits to them no
longer flip the loop to stale or interrupt capture cadence. A commit to a file
the loop does import still triggers a clean current-code re-adoption.

Code/tests:

- `src/weather/runtime_identity.py` (`_module_source_files`, `_fingerprint_relpaths`,
  `get_runtime_identity(scope_files=...)`, `current_identity_for`).
- `src/weather/collection/snapshot_store.py` (scoped `PROCESS_RUNTIME_IDENTITY`),
  `snapshot_tracker.py`, `market_microstructure.py`, `observation_trigger.py`,
  `reporting/fleet/fleet_observability_loops.py` + `_inventory.py`.
- `tests/operations/test_runtime_identity.py`: out-of-scope change stays current,
  in-scope change goes stale, deleted scope file goes stale, legacy whole-tree
  fallback preserved. `131` tests pass across runtime-identity, supervisor,
  collection, and fleet-observability suites.

Verified live: after restart the snapshot loop captured `source_scope=loaded_modules`
with `62` scoped files, `runtime_code_state=current`, and resumed fresh captures.

## 2026-06-26 12h audit follow-up: extend benign-cause exclusion to the CLOB loop

A 12-hour stability review found the snapshot loop healthy (no circuit trips,
capture ratio 0.89-1.29 across markets vs 0.51 on 2026-06-24) but the CLOB loop
circuit-broken with a 30-minute dark window. Root cause: the
snapshot loop labels benign current-code re-adoption `stale_code`, but the
CLOB/microstructure loop labels the same condition `runtime_identity`
(`restart_cause = "runtime_identity" if not runtime_matches_current`). The
circuit-breaker exclusion only covered `stale_code`, so the CLOB loop's benign
re-adoptions still consumed its budget and tripped the breaker
(`restart_budget_exceeded=12>=12`, repeating every ~40 min). Extended
`_BENIGN_RESTART_CAUSES` to `{"stale_code", "runtime_identity"}`; the live CLOB
recovery count dropped from `12` to `0`, the breaker closed, and the loop
relaunched on current code with a scoped `35`-file identity. Regression test
`test_stale_code_restarts_do_not_consume_crash_budget` now covers both labels.
