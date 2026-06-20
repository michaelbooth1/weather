# 152. Active-Day Bot Preflight And Disk Liveness [COMPLETE 2026-06-18 - DISK AND DISCOVERY DENY-BY-DEFAULT GATES]

Goal: make active-day market-making and taker bot runs fail closed with accurate
operator status when disk capacity, CLOB token discovery, or CLOB book capture
prevents valid trading evidence.

Source: the June 18 log audit found both bot families blocked across all
markets and then vulnerable to stale liveness reporting. The market-making run
`data/mm_runs/2026-06-18/20260618T040102695625Z` produced 89,049 cumulative
rows and zero quote-permission rows because every market failed preflight on
missing active event rows, missing CLOB token IDs, missing current book rows,
and missing reward metadata. The taker run
`data/taker_runs/2026-06-18/taker-20260618-221a357c` produced 6,083 rows, all
`NO_TRADE_MARKET_INACTIVE`, with zero fills. Both daily-roll status files still
reported `started` even after their recorded PIDs were no longer alive, and the
console logs ended in `OSError: [Errno 28] No space left on device`.

Why this matters: a blocked no-trade day is acceptable; a bot that stops writing
or leaves stale `started` status is not. The operator needs to know whether a
zero-trade day was a deliberate preflight block, a missing market-discovery
state, or a process death caused by storage pressure.

## Design

1. Add a disk-headroom preflight to market-making and taker daily rolls before
   opening append-only CSV/JSONL writers.
2. Update daily-roll supervisors to record terminal states such as `exited`,
   `failed`, `disk_full`, and `pid_missing` instead of leaving stale `started`
   status after child exit.
3. Treat all-market blank CLOB token IDs or all-market inactive Gamma rows as a
   first-class preflight incident with a single root-cause summary and
   immediate remediation command.
4. Add a CLOB discovery sanity check: if `clob_tokens.csv` grows while
   `clob_token_id` and `condition_id` remain blank for every active-day row,
   fail the CLOB loop health gate rather than only producing zero book captures.
5. Require bot run summaries to distinguish `blocked_by_market_discovery`,
   `blocked_by_clob_books`, `blocked_by_disk`, and `policy_no_edge`.
6. Add a compact operator alert that links the current bot run, CLOB loop
   status, disk-free bytes, and first failing gate.

- [x] Add disk-capacity preflight and structured low-space failure status to
  market-making and taker daily rolls.
- [x] Update supervisor status after child process exit and add tests for stale
  PID detection.
- [x] Add an all-market blank-token / inactive-event CLOB discovery gate.
- [x] Add report fields for root-cause class, first failing gate, and whether
  zero trades were expected.
- [x] Add regression tests using a simulated disk-full writer failure.
- [x] Add regression tests for `clob_tokens.csv` rows with blank token IDs and
  inactive Gamma rows.

Acceptance: when CLOB discovery or disk capacity blocks a run, the bot status
shows a terminal or blocked state within one supervisor interval, the run report
states why zero trades occurred, and the remediation path is a single concrete
command rather than 12 repeated per-market symptoms.

## Implementation Notes

Completed 2026-06-18. `weather.operations.bot_run_liveness` now provides shared
disk-capacity preflight, disk-full classification, and stale PID terminal-state
helpers. Market-making and taker daily rolls use those helpers before launching
child processes and when loading status. Market-making/taker run summaries now
emit `root_cause_class`, `first_failing_gate`, `zero_trades_expected`, and a
compact operator alert.

The CLOB path now has a first-class `clob_discovery` gate for blank token IDs or
inactive Gamma rows, and CLOB loop health degrades when a fresh loop captures
zero tokens and zero books for every market. Fleet observability surfaces that
sanity gate as a broad live-forward blocker.

Validation: `python -m pytest tests/operations/test_market_making_daily_roll.py tests/operations/test_taker_bot_daily_roll.py tests/operations/test_observation_trigger.py tests/market/test_market_microstructure.py tests/market/test_market_making_run.py::TestMarketMakingRun::test_blank_clob_tokens_are_market_discovery_blocker tests/market/test_market_making_run.py::TestMarketMakingRun::test_quote_rows_include_settlement_normalized_current_high tests/market/test_taker_bot.py tests/reporting/test_fleet_observability.py tests/market/test_mm_policy.py` passed with 110 tests.
