# Taker Bot Log Audit - 2026-06-20

Scope: all available taker-bot artifacts under `data/taker_runs` through the
latest audit snapshot. The 2026-06-20 bot process was still running during this
audit; its latest report read here was generated at
`2026-06-20T15:05:05.763482+00:00`, so that day remains intraday and
unsettled.

## Evidence Reviewed

- `data/taker_runs/daily_roll_status.json`
- `data/taker_runs/daily_roll_console.log`
- Every run folder with an `orders_long.csv` tape under `data/taker_runs/*/*`
- `run_config.json`, `run_summary.json`, `daily_pnl.json`, `budget_ledger.jsonl`
- Available June 19 `settled_pnl.json`, `settled_orders_long.csv`, and
  `settled_report.md` artifacts
- Taker policy implementation in `src/weather/market/taker_bot.py`

## Run Summary

| Target date | Run | Policy hash | Ticks | Rows | Fills | Spent | P&L source | Net P&L | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| 2026-06-18 | `taker-20260618-221a357c` | `221a357c` | 310 | 5,444 | 0 | 0.0000 | none | 0.0000 | All rows skipped as `NO_TRADE_MARKET_INACTIVE`; this was not countable strategy evidence. |
| 2026-06-19 | `taker-20260619-221a357c` | `221a357c` | 253 | 24,778 | 50 | 59.8051 | settlement | 36.6878 | Initial simple edge policy. Reported MTM was `-17.2087`, but final settlement was positive. |
| 2026-06-19 | `taker-20260619-3d3450f0` | `3d3450f0` | 171 | 11,077 | 4 | 10.0000 | settlement | -10.0000 | Early-hour guardrail policy replayed the prior date and bought only Seattle `82-83 F`; reported MTM was a stale/resolved outlier at `+1238.7500`. |
| 2026-06-20 | `taker-20260620-3d3450f0` | `3d3450f0` | 584+ | 67,353 | 50 | 66.9901 | mark-to-market | 17.3540 | Still active and unsettled at audit time; current-high trust was false for several filled markets. |

The daily roll console includes a prior `OSError: [Errno 28] No space left on
device` while rewriting `orders_long.csv`. The current roll status later showed
`disk_capacity_preflight.status=PASS`, roughly 126 GB free at launch, and an
active `pythonw` PID for the June 20 run.

## Is The Bot Using The Model Effectively?

The model is wired in correctly at the mechanical policy layer. `taker_bot`
builds each candidate from the latest snapshot/model rows, maps
`model_probability` to `fair_probability`, joins current CLOB best ask and ask
size, gates on active market, source freshness, book age, model age, price
range, and positive edge, then sorts candidates by raw edge. Every observed
fill in the available logs has positive `fair_probability - best_ask`.

That is not enough to say the model is being used effectively as a trading
strategy. The current policy consumes raw model edge directly, with no explicit
calibration confidence, no per-market/bin/time reliability adjustment, no
settled-outcome strategy arm, and no portfolio-aware sizing beyond static
budget, per-token, and fill-count caps. This causes two problems visible in the
logs:

1. Low-price tails dominate expected value. The settled June 19 `221a357c` run
   had `+152.3226` USDC of raw model expected profit on 59.8051 USDC spent,
   but settled at `+36.6878`. The later Seattle run expected `+58.1713` USDC
   on 10 USDC spent and settled at `-10.0000`.
2. Fill count overstates independent evidence. The June 19 positive run had 50
   fills but only eight market/band opinions; repeated snapshot fills in the
   same band are useful exposure records, not independent model-quality samples.

The bot is therefore using the model, but it is using it too naively for
strategy-quality claims.

## Are We Testing Different Taker Strategies?

Not in a rigorous way. There are two policy hashes:

- `221a357c`: the original simple raw-edge taker policy.
- `3d3450f0`: the same policy with early-hour current-high/source/edge
  guardrails added.

Those hashes were run sequentially, not as a controlled experiment. The order
tape has `policy_hash`, but no `strategy_id`, `experiment_id`, arm assignment,
or control/candidate pairing. The June 19 `3d3450f0` run also targeted a
settled prior date after the main June 19 run, so it is not an active-day
parallel comparison. We can compare artifacts after the fact, but the taker bot
is not yet running deliberate strategy tests.

## Strategy Tests To Add

The next taker work should test strategy arms explicitly, all settlement-scored:

- `raw_edge_control`: current policy as the control.
- `calibrated_edge`: shrink raw fair probabilities by market, bin, hour,
  source-state, and recent model reliability before computing edge.
- `low_price_tail_capped`: keep the tail-lottery behavior but isolate it with a
  tiny budget and strict per-market/per-band caps.
- `winner_centered_or_adjacent`: buy the top modeled winner or adjacent bundle
  only when credible mass is concentrated and the current high/state supports
  that region.
- `current_high_lockin`: trade only after a trusted current high or high-has-
  stood signal says the market underprices the already-reached/nearby final
  band.
- `late_day_liquidity_filtered`: require CLOB continuity, non-stale marks,
  minimum depth, and price-history sanity before taking late opportunistic asks.

Roadmap items added from this audit:

- Item 165: Taker Strategy Experiment Harness And Arm Attribution
- Item 166: Settlement-Scored Taker Strategy Bakeoff
- Item 167: Calibration-Aware Taker Sizing And Tail-Risk Controls

