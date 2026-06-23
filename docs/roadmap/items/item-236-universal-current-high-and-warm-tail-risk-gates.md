# 236. Universal Current-High And Warm-Tail Risk Gates [COMPLETE 2026-06-22 - STRATEGY-FAMILY LOOPHOLES CLOSED]

Goal: close the strategy-family and time-window loopholes that allow warm-tail
or untrusted-current-high aggressive taker trades to slip through non-raw-edge
candidates.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
Warm-tail blocking is configured only for the `raw_edge` family, while the
active `low_price_tail_capped` candidate can still fill market-centered warm
tails. The current-high trust gate allows aggressive untrusted-current-high
trades before the late window.

Why this matters: risk gates should protect the trading surface, not only one
strategy family. A candidate that changes family labels should not reopen the
same market-centered warm-tail and untrusted-current-high failures.

## Design

1. Make market-centered warm-tail blocking apply to all active and candidate
   taker strategy families by default.
2. Allow exceptions only through an explicit allowlist backed by
   settlement-scored evidence for that slice.
3. Deny aggressive untrusted-current-high trades from the start of the trading
   day, not only in the late window.
4. Treat missing or `CONFIG` weak-slot/cadence/trust state as blocking unless
   the strategy has an explicit diagnostic-only permission.
5. Add selection tests for `low_price_tail_capped` and other candidate families
   so family changes cannot bypass the gates.

- [x] Replace family-specific warm-tail blocking defaults with fail-closed
  universal blocking plus an evidence-backed allowlist.
- [x] Remove the pre-late-window aggressive untrusted-current-high allowance.
- [x] Make missing weak-slot, cadence, and trust states block candidate fills
  unless explicitly marked diagnostic-only.
- [x] Add tests covering June 22 active-strategy shapes with warm-tail and
  untrusted-current-high fills.

Acceptance: replaying the June 22 filled shapes marks market-centered
warm-tail and aggressive untrusted-current-high trades as skipped or capped for
all active strategy families unless an explicit settlement-backed allowlist is
present.

Related: items 192, 212, 215, 235, 237.

## Closeout 2026-06-22

Implemented in `weather.market.taker_bot_strategy_registry` and
`weather.market.taker_bot_strategy_evaluation`.

- Warm-tail and weak-slot taker gates now default to all strategy families and
  only bypass through explicit strategy-family or strategy-id allowlists.
- The current-high trust gate starts at local hour 0 and blocks aggressive
  untrusted-current-high trades before the former late-window boundary.
- Missing current-high trust state and missing snapshot-cadence proof now deny
  taker candidates by default, with diagnostics written to the orders tape.
- Added regression coverage for `low_price_tail_capped` weak-slot/warm-tail
  blocks, pre-late untrusted-current-high blocks, missing trust state, and
  missing cadence proof.

Verification:

- `python -m pytest tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py tests\operations\test_schema_registry.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_learning.py tests\reporting\test_daily_progress_ledger.py -q`
  - 76 passed, 5 subtests passed.

## Follow-Up Hardening 2026-06-23

Item 255 closed the remaining config-drift loophole: delayed
`current_high_trust_gate_start_hour_local` overrides now emit a daily-roll
warning, but aggressive untrusted-current-high taker rows still deny from local
hour `0`.
