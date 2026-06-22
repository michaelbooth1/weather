# 214. Settlement-Scored Taker Promotion And Tail-Fill Gate [OPEN 2026-06-22 - MTM-ONLY PNL MUST NOT PROMOTE STRATEGIES]

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

- [ ] Enforce a settlement-scored minimum sample before taker strategy
  promotion.
- [ ] Add tail-fill quality metrics to `strategy_summary.json` and
  `strategy_report.md`.
- [ ] Mark MTM-only strategy results as provisional in daily progress.
- [ ] Add tests using the 2026-06-21 taker run shape: positive MTM, zero
  settled fills, and many tail fills.
- [ ] Add an alert when tail-fill count exceeds a configurable fraction of
  filled orders.

Acceptance: a taker run with positive MTM but zero settled fills remains
non-countable and non-promotable, tail fills are scored separately, and a future
strategy can promote only after settlement-scored thresholds pass.

Related: items 162, 165, 166, 167, 192, 209.
