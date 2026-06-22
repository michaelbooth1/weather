# 214. Settlement-Scored Taker Promotion And Tail-Fill Gate [COMPLETE 2026-06-22 - MTM-ONLY PNL IS PROVISIONAL AND TAIL FILLS ARE GATED]

Goal: prevent taker strategy promotion from mark-to-market P&L alone and add a
separate tail-fill quality gate before a strategy can be treated as countable
or promotable.

Source: the 2026-06-21 taker run
`data/taker_runs/2026-06-21/taker-20260621-bbe63642` had tape integrity
`PASS`, `50` cumulative paper buys, `0` settled fills, and positive MTM P&L
(`1702.2090` USDC in the latest report). The strategy report still correctly
marked `MISSING_SETTLED_SAMPLE` and `Countable=false`, with `31` tail fills.

Why this matters: MTM can move sharply before settlement and can reward
lottery-like fills that are not repeatable settlement edge. The taker bot needs
to learn from MTM, but promotion and policy default decisions must wait for
settlement-scored evidence and explicit tail-fill evaluation.

## Design

1. Add a hard promotion gate requiring minimum settled fills, settled market
   count, and settlement-scored net/EV metrics before a taker strategy can be
   marked countable or promoted.
2. Add a tail-fill report that separates low-price tail fills from core edge
   fills by market, range, probability, and eventual settlement outcome.
3. Keep MTM P&L visible as provisional evidence only, with a label that cannot
   satisfy promotion gates.
4. Add daily-progress wording that flags positive MTM but missing settlement
   sample as non-countable evidence.

- [x] Enforce a settlement-scored minimum sample before taker strategy
  promotion.
- [x] Add tail-fill quality metrics to `strategy_summary.json` and
  `strategy_report.md`.
- [x] Mark MTM-only strategy results as provisional in daily progress.
- [x] Add tests using the 2026-06-21 taker run shape: positive MTM, zero
  settled fills, and many tail fills.
- [x] Add an alert when tail-fill count exceeds a configurable fraction of
  filled orders.

## Completion Notes

Added explicit settlement-scored promotion thresholds to taker P&L artifacts:
`promotion_min_settled_orders`, `promotion_min_settled_markets`,
settlement-scored net/expected P&L floors, and
`promotion_max_tail_fill_fraction`. Strategy rows now carry a
`settlement_promotion_gate`, `quality_candidate_evidence_basis`, and
`mtm_promotion_allowed=false` in strategy comparison output, so positive MTM
cannot create a countable settlement-scored candidate.

Added `tail_fill_quality` payloads to daily P&L/strategy summary output,
including low-price tail fill count/fraction, settlement vs unsettled tail
fills, alerts, and by-market/range tail breakdowns. Bakeoff promotion gates now
include settled-market, settlement-EV, unresolved-order, and tail-fraction
checks before a strategy can pass.

Daily progress and daily learning summaries now expose `pnl_evidence_status`.
MTM-only taker P&L is labelled `PROVISIONAL_MTM_ONLY`, and tail-fill status,
tail alert count, and MTM promotion eligibility are reported alongside the
active strategy gate.

Regression coverage includes the June 21 shape: positive MTM, zero settled
fills, 50 paper buys, and 31 low-price tail fills. The fixture remains
non-countable, has no best settlement-scored strategy, and raises high-tail and
missing-tail-settlement alerts.

Verification:

- `python -m pytest tests\market\test_taker_bot.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_progress_ledger.py -q`
- `python -m pytest tests\reporting\test_daily_learning.py tests\operations\test_daily_refresh.py -q`

Acceptance: a taker run with positive MTM but zero settled fills remains
non-countable and non-promotable, tail fills are scored separately, and a future
strategy can promote only after settlement-scored thresholds pass.

Related: items 162, 165, 166, 167, 192, 209.
