# 164. Settlement-Aware Taker P&L Finalization [COMPLETE]

Goal: make taker-bot reports reconcile paper fills to settled labels before
they feed daily learning, daily progress, or strategy-quality claims.

Source: the settled June 19 log audit. The 2026-06-19 taker run
`taker-20260619-221a357c` reported `0 / 50` settled fills and `-17.2087`
USDC mark-to-market P&L, but direct settlement scoring of its filled YES buys
against `market_day_labels.csv` gives `+36.6878` USDC: Atlanta, Toronto, and
Miami winners more than offset NYC losers. The later run
`taker-20260619-3d3450f0` reported `+1238.7500` USDC mark-to-market P&L on
Seattle, but settlement scoring gives `-10.0000` USDC because the filled
`82-83 F` band lost to the `80-81 F` settlement.

Why this matters: mark-to-market is useful intraday, but after settlement it is
the wrong source of truth. A resolved-day taker report that still shows
unsettled fills or stale mark P&L can invert the strategy-quality read and
pollute the daily progress ledger.

## Design

1. Add a taker finalization step that joins `orders_long.csv` fills to
   `market_day_labels.csv` by `target_date`, `market_id`, and band identity.
2. Write settled payout, settled P&L, settlement status, and winner/loser flags
   back to the taker summary artifacts without mutating the raw order tape.
3. Keep mark-to-market P&L as an intraday diagnostic only; after settlement,
   daily learning and the progress ledger should prefer settled P&L.
4. Add a reconciliation check that flags large differences between reported
   mark-to-market P&L and settled P&L once labels exist.
5. Add a guard for stale/resolved CLOB marks that can produce impossible paper
   P&L, including the Seattle `+1238.7500` mark-to-market case.

- [x] Implement a taker settlement-finalization command or daily-refresh step.
- [x] Add a non-mutating settled report beside each taker run.
- [x] Teach `trading_evidence`, daily learning, and the daily progress ledger
  to consume settled P&L when available.
- [x] Add regression coverage for the June 19 `+36.6878` and `-10.0000`
  settlement-scored cases.
- [x] Add a stale/resolution mark-price warning for post-close taker reports.

Acceptance: after market-day labels exist, a taker run report shows settled and
unsettled fill counts correctly, daily learning uses settled P&L for resolved
days, and any residual mark-to-market field is clearly classified as intraday
diagnostic rather than strategy-quality evidence.

## Completion - 2026-06-20

Implemented `python -m weather.market.taker_bot finalize`, which scores filled
taker orders against `market_day_labels.csv` and writes non-mutating
`settled_orders_long.csv`, `settled_pnl.json`, and `settled_report.md`
artifacts beside each taker run. `orders_long.csv` remains the raw tape.

The finalization artifact is registered as
`taker_settlement_finalization_v0.1` and includes reported-vs-finalized
reconciliation warnings for unresolved-after-labels, MTM divergence,
resolved-day mark outliers, and sign flips.

June 19 real-run verification:

- `taker-20260619-221a357c`: `50 / 0` settled/unsettled, settled net P&L
  `+36.687839` USDC, replacing the old `-17.208695` MTM read.
- `taker-20260619-3d3450f0`: `4 / 0` settled/unsettled, settled net P&L
  `-10.000000` USDC, with stale/resolved mark warnings for the reported
  `+1238.750000` MTM case.

Verification:

- `python -m pytest -q tests\market\test_taker_bot.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_learning.py tests\reporting\test_daily_progress_ledger.py tests\operations\test_schema_registry.py`
  -> `37 passed`.
- `python -m weather.market.taker_bot finalize --date 2026-06-19 --runs-root data\taker_runs --labels-csv data\backtest\market_day_labels.csv --now 2026-06-20T12:00:00+00:00`
  -> finalized both June 19 taker runs.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

