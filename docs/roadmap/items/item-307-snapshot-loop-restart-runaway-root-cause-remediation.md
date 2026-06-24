# 307. Snapshot And Collection Loop Restart-Runaway Root-Cause Remediation [PARTIAL 2026-06-24 - CODE REMEDIATION LANDED, ACTIVE-DAY SOAK PENDING]

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

Regression coverage added:

- `tests/operations/test_supervisor.py` covers malformed-line quarantine and
  recovery guard backoff/circuit behavior.
- `tests/collection/test_loop_supervisor.py` and
  `tests/collection/test_collection_robustness.py` cover snapshot stale-code
  backoff and clean child exit.
- `tests/market/test_market_microstructure.py` and
  `tests/operations/test_observation_trigger.py` cover CLOB and
  observation-trigger bounded restarts.

Verification:

- `python -m pytest tests\operations\test_supervisor.py tests\collection\test_loop_supervisor.py tests\collection\test_collection_robustness.py tests\operations\test_observation_trigger.py tests\market\test_market_microstructure.py tests\reporting\test_fleet_observability.py tests\operations\test_nightly_health_checks.py -q`
  passed (`149 passed`).

Remaining blocker: deploy/restart the managed loops with this code and retain one
full active-day soak where all three loops stay current-code, single-writer,
under restart budget, and live-forward cadence passes. That evidence is required
before this item should be marked complete.
