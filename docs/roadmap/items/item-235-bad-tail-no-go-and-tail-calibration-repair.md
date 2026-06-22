# 235. Bad-Tail No-Go And Tail Calibration Repair [COMPLETE 2026-06-22 - BAD TAIL SLICES FAIL CLOSED]

Goal: identify, block, and recalibrate the low-price and warm-tail slices where
the taker edge model has repeatedly bought losing tails.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
June 20 had `50/50` losing fills, all classified as warm-tail losing fills.
June 21 had `31` low-price-tail fills, all lost.

Why this matters: cheap tail positions can dominate fill counts while looking
small in notional terms. If the model is systematically overpricing
low-probability or far-from-current-high bands, scaling the strategy increases
expected losses rather than finding hidden edge.

## Design

1. Build a tail casebook by market, local hour, current-high distance, model
   probability, market price, warm-tail flag, low-price-tail flag, and source
   state.
2. Add a no-go registry for tail slices that remain blocked until they show
   repeated settlement-positive out-of-sample evidence.
3. Recalibrate or haircut the model in low-probability, high-temperature, and
   far-from-current-high bands before those fills can re-enter promotion
   evidence.
4. Tighten daily, per-market, and per-strategy low-tail notional/count caps.
5. Compare every tail fill to market modal/top-winner probabilities so the bot
   does not buy tails where the market is already smarter.

- [x] Produce a June 20-21 tail-loss casebook with settle outcome and feature
  slices for every losing tail fill.
- [x] Add a no-go/cap registry for bad warm-tail and low-price-tail slices.
- [x] Add replay tests proving the June 20 warm-tail and June 21 low-tail loss
  patterns are blocked or materially capped.
- [x] Add a tail calibration report that distinguishes true edge from lottery
  fills by settlement outcome.

Acceptance: known bad tail slices are either no-trade or capped to diagnostic
probe size until they are settlement-positive across multiple days, and the
June 20/21 loss patterns no longer pass candidate selection unchanged.

Related: items 192, 214, 232, 236, 241.

## Closeout 2026-06-22

Implemented in `weather.market.taker_bot_strategy_registry`,
`weather.market.taker_bot_strategy_evaluation`,
`weather.market.taker_bot_sizing`, and
`weather.reporting.taker_tail_casebook`.

- Added a fail-closed bad-tail no-go registry. Low-price tail rows at or below
  the configured tail price threshold now skip with
  `NO_TRADE_BAD_TAIL_NO_GO` unless explicitly allowlisted.
- Warm-tail rows retain the universal warm-tail block from item 236, while the
  no-go diagnostics record the bad-tail slice decision on the order tape.
- Added order-tape diagnostics for bad-tail no-go status, action, slice id, and
  reason.
- Added a June 20/21 tail casebook and calibration report:
  `data/backtest/taker_tail_casebook_2026-06-20_2026-06-21.json` and
  `data/backtest/taker_tail_casebook_2026-06-20_2026-06-21.md`.
  The report found `86` tail fills, `85` losing tail fills, and `29` no-go
  candidate slices across low-price and market-centered warm-tail patterns.

Verification:

- `python -m weather.reporting.taker_tail_casebook --run data\taker_runs\2026-06-20\taker-20260620-3d3450f0 --run data\taker_runs\2026-06-21\taker-20260621-bbe63642 --json-out data\backtest\taker_tail_casebook_2026-06-20_2026-06-21.json --report-out data\backtest\taker_tail_casebook_2026-06-20_2026-06-21.md`
- `python -m pytest tests\market\test_taker_bot.py tests\reporting\test_taker_tail_casebook.py tests\operations\test_taker_bot_daily_roll.py tests\operations\test_schema_registry.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_learning.py tests\reporting\test_daily_progress_ledger.py -q`
  - 79 passed, 5 subtests passed.
