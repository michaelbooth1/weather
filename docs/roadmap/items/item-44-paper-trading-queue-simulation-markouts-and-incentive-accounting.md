# 44. Paper Trading, Queue Simulation, Markouts, And Incentive Accounting [COMPLETE 2026-06-15 - PAPER SCORER LIVE]

Goal: make MM-1 paper trading honest enough to decide whether live min-size
testing is justified.

Research source: the market-making audit says midpoint-only backtests and
headline P&L are not enough. Queue position, latency, adverse selection,
rebates, rewards, and overfit controls must be measured explicitly.

- [x] Build the conservative fill simulator as the promotion gate: a passive
  quote fills only when a recorded trade prints strictly through the intended
  price, never merely at the price, and fill size is capped by recorded trade
  size.
- [x] Add a queue-aware companion simulator using recorded book deltas to
  estimate queue depletion, cancellations ahead, partial fills, and missed
  fills. Report it beside the conservative simulator; do not let it replace
  the conservative go-live gate.
- [x] Score markout curves at `+30s`, `+1m`, `+5m`, `+30m`, and settlement by
  market, hour, band distance, quote age, regime, source freshness, book
  imbalance, and casebook taxonomy.
- [x] Decompose P&L into spread capture, adverse-selection markout,
  maker-rebate estimate, liquidity-reward estimate, taker/flattening fees,
  and settlement P&L. Reward/rebate income is valid only after toxic markout
  and flattening costs are deducted.
- [x] Implement reward accounting against Polymarket's formula: qualifying
  size, distance from adjusted midpoint, `Q_min`, normalized share, campaign
  pool, payout threshold, and rolling competition by hour/band. Refresh the
  reward-competition report continuously; thin competition is not assumed to
  persist.
- [x] Implement maker-rebate accounting: theoretical fee-equivalent, realized
  maker fee-equivalent, per-market rebate pool, our pool share, and paid-vs-
  predicted reconciliation once live.
- [x] Enforce anti-overfit discipline for policy changes: frozen replay day
  sets, held-out validation days, live-forward paper results generated in real
  time, parameter hashes, confidence intervals by slice, and a deflated-Sharpe,
  PBO, or equivalent multiple-test adjustment when many variants are tried.
- [x] Emit `data/backtest/mm_paper_report.md` plus machine-readable JSON with
  conservative and queue-aware results, markout slices, rewards/rebates,
  quote uptime, stale-input pulls, and casebook-linked fill toxicity.

Acceptance: before MM-2 live testing, there are at least 14 consecutive
live-forward paper days with locked policy parameters, conservative fills,
queue-aware companion analysis, net P&L after markout/rewards/rebates/fees,
slice confidence intervals, and no unresolved quotes resting through decisive
observation events.

Implementation status (2026-06-15): `src.mm_paper` /
`weather.market.mm_paper` scores `data/mm_runs/<date>/<run_id>/` quote-intent
runs into `data/backtest/mm_paper_report.md`,
`data/backtest/mm_paper_report.json`, and
`data/backtest/mm_paper_fills_long.csv`. The conservative simulator only fills
quotes on strict trade-through rows with recorded size and caps each fill by
remaining recorded trade size. The queue companion reports book-delta estimated
fills/misses next to, not instead of, conservative fills. The scorer attaches
30s/1m/5m/30m/settlement markouts, P&L decomposition, maker fee-equivalent and
rebate estimates, liquidity reward estimates, flattening fees, quote uptime,
stale-input pulls, casebook toxicity taxonomy, locked policy hashes, slice CIs,
and a conservative multiple-test CI floor.

Live gate note: the implementation is complete, but MM-2 live testing remains
blocked until the acceptance evidence exists: at least 14 consecutive
live-forward paper days under locked policy parameters with clean decisive-event
resting-quote audits and positive net results after markouts, fees, rewards, and
rebates.

Validation: `pytest tests\market\test_mm_paper.py -q` passed (2 tests);
`pytest tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_policy.py -q`
passed (13 tests); full `pytest -q` passed (453 tests, 84 subtests);
`compileall src tests` passed; `python -m src.mm_paper --help` exposes the CLI,
and `python -m src.mm_paper` wrote fail-closed default reports with zero fills
because no `data/mm_runs` folders exist yet.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - PAPER SCORER LIVE`.
- The file contains 8 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

