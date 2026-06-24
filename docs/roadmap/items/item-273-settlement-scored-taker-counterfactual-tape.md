# 273. Settlement-Scored Taker Counterfactual Tape [COMPLETE 2026-06-23]

Goal: turn every taker candidate row into settlement-scoreable counterfactual
evidence for each registered strategy and model variant, while keeping real
fills paper-only until promotion gates pass.

Source: the June 21-23 taker audit found only `58` settled fills across the two
latest labelable days, with `1` win and `57` losses. June 23 produced zero
fills because the new gates correctly blocked risky candidates, but that also
means ordinary fill-only learning is too slow.

Why this matters: waiting for actual fills is a low-throughput way to learn.
The system already observes candidate bands, model probabilities, market books,
fees, and gates. Persisting a per-strategy "would buy" decision for every
candidate lets us settlement-score thousands of hypothetical decisions after
labels arrive without increasing risk.

## Design

1. For every snapshot/band candidate, write a counterfactual row per active
   strategy with model fair value, YES/NO executable book, fee/slippage inputs,
   gate states, would-buy decision, and synthetic order size.
2. Preserve the real action separately from the counterfactual action so
   paper/live fills remain auditable.
3. After settlement, score every counterfactual row against the true outcome
   and emit by-strategy, by-market, by-hour, tail, current-high, and source-state
   summaries.
4. Keep promotion gates based on complete-label, after-fee, after-slippage,
   settlement-scored evidence, with market-day clustered confidence intervals.
5. Add retention controls so the wide counterfactual tape can be compacted to
   Parquet or summarized after settlement.

- [x] Add a counterfactual taker tape schema beside the raw order tape.
- [x] Score counterfactual would-buy rows after settlement without mutating the
  raw `orders_long.csv` fill tape.
- [x] Add summary reports for strategy lift versus no-trade, market-top, and
  current active policy.
- [x] Add storage/retention controls for high-row-count counterfactual artifacts.

Acceptance: a zero-fill day can still produce settlement-scoreable learning
about which strategies and slices would have traded, while promotion remains
blocked until complete-label after-fee evidence is positive.

Completion evidence (2026-06-23):

- Live taker runs now emit `counterfactual_orders_long.csv` beside
  `orders_long.csv`, using the configured counterfactual/bakeoff strategy set
  and the same shared snapshot/book/model inputs.
- Counterfactual rows carry their hypothetical action/status separately from
  `real_action`, `real_order_status`, `real_strategy_id`, and related raw-paper
  fields, so the real fill tape remains auditable.
- Settlement finalization now writes `settled_counterfactual_orders_long.csv`,
  `settled_counterfactual_pnl.json`,
  `settled_counterfactual_report.md`,
  `settled_counterfactual_strategy_summary.json`, and
  `settled_counterfactual_strategy_report.md` without mutating
  `orders_long.csv`.
- Counterfactual settlement reports include strategy lift versus no-trade, the
  active policy, and market-top benchmark, plus compact by-market, by-hour,
  tail, current-high, and source-state slice summaries.
- Retention metadata and the taker retention scan now account for raw and
  settled counterfactual artifacts so large tapes can be archived or compacted
  after summary artifacts are verified.
- Regression coverage proves a zero-real-fill run can still produce settled
  counterfactual would-buy rows while preserving the raw order tape unchanged.

Validation:

- `python -m pytest tests\market\test_taker_bot.py -q`
- `python -m pytest tests\market\test_taker_bot_two_sided.py -q`
- `python -m py_compile src\weather\market\taker_bot_strategy_registry.py src\weather\market\taker_bot_bakeoff.py src\weather\market\taker_bot_finalization.py src\weather\market\taker_bot_cli.py src\weather\market\taker_bot_reporting.py`

Related: items 238, 240, 241, 256, 269.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

