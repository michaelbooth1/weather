# 162. Countable Trading Evidence And Taker Strategy Quality Gate [COMPLETE 2026-06-20 - GATES LIVE, CURRENT EVIDENCE NON-COUNTABLE]

Goal: turn trading-loop outputs into correctly classified evidence and prevent
paper activity from being mistaken for strategy quality.

Source: the June 19 trading reports. The market-making run passed preflight for
all 12 markets, emitted 4,019 cumulative quote rows and 8,026 paper-posted
lifecycle legs, but was explicitly `operator_drill` and
`counts_toward_live_forward_gate=false`. The taker bot produced 50 paper fills
and spent `59.8051` USDC, but reported `-17.2087` USDC mark-to-market P&L and
`policy_no_edge` as the root cause for latest no-trade behavior.

Why this matters: the trading stack is operationally useful, but it needs two
separate gates: countable live-forward evidence and strategy-quality evidence.
Passing preflight or emitting paper orders is not enough to claim strategy
improvement.

## Design

1. Require every market-making and taker run to declare evidence mode:
   active-day live-forward, post-settlement evaluation, operator drill, or
   non-countable diagnostic.
2. Keep model-review, paper-trading, and live-trade-permission evidence
   separate in reports and progress tracking.
3. Add taker quality gates for P&L, markout, exposure concentration, stale-book
   decisions, source-stale blocks, and policy-no-edge behavior.
4. Require active-day schedule alignment before a run can count toward
   live-forward evidence.
5. Keep live-order enablement blocked unless live-trade permission rows,
   platform gates, and risk gates all pass.

- [x] Add the latest market-making evidence-mode, quote rows, paper-posted rows,
  and live-trade permission rows to the daily progress ledger.
- [x] Add taker P&L and root-cause metrics to daily learning without treating
  one negative paper day as conclusive strategy failure.
- [x] Add a countable active-day market-making run requirement distinct from
  `operator_drill`.
- [x] Add taker strategy-quality thresholds over a rolling sample, not one
  isolated mark-to-market report.
- [x] Add tests that operator-drill runs remain non-countable even when all raw
  data gates pass.

2026-06-20 update: `weather.reporting.trading_evidence` now classifies
market-making and taker reports before daily learning and the daily progress
ledger consume them. The latest market-making run remains non-countable because
`evidence_mode=operator_drill` and `live_forward_gate=BLOCK`, despite
`4019` quote rows and `8026` paper-posted lifecycle legs. The latest taker run
is tracked as `50` paper fills, `-17.208695` USDC net/mark-to-market P&L, and
`policy_no_edge`; the quality gate is `SAMPLE_PENDING_NEGATIVE_LATEST`, so it
is operational evidence rather than a strategy-quality win or loss.

Daily progress now records `trading_mm_evidence_mode`,
`trading_mm_quote_rows`, `trading_mm_live_trade_permission_rows`,
`trading_taker_fills`, `trading_taker_net_pnl_usdc`,
`trading_taker_mark_to_market_pnl_usdc`, `trading_taker_root_cause`, and
`trading_taker_quality_status`. Focused tests cover operator-drill
non-countability and rolling taker sample gating.

Acceptance: a future trading report can be used as countable evidence only when
the run is classified as active-day live-forward and all selected markets count.
Strategy-quality claims require a rolling paper/taker sample with P&L or
markout metrics clearing thresholds; operator drills and one-off negative P&L
days remain diagnostics.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - GATES LIVE, CURRENT EVIDENCE NON-COUNTABLE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

