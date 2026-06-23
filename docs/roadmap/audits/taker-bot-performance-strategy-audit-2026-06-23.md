# 2026-06-23 Taker Bot Performance Strategy Audit

This audit uses the current repository state to evaluate the taker bot over the
available June 18-22 run window. Evidence comes from `data/taker_runs/**`,
`data/backtest/market_day_labels.csv`, taker bakeoff artifacts, finalization
watchdog reports, and the taker strategy/scoring/reporting code.

## Settlement Finalization State

The first repair was operational: labelable runs existed without current
settlement finalization. I ran the taker finalization watchdog for June 19,
June 20, and June 21, then reran the all-runs report-only watchdog.

Generated evidence:

- `data/backtest/taker_finalization_watchdog_2026-06-19.md`
- `data/backtest/taker_finalization_watchdog_2026-06-20.md`
- `data/backtest/taker_finalization_watchdog_2026-06-21.md`
- `data/backtest/taker_finalization_watchdog_all_report_only.md`

Current watchdog state: `6` runs scanned, `4` labelable runs, `0` needing
finalization, `0` SLA breaches, and June 22 waiting for labels. Disk capacity is
currently `PASS`.

## Performance Reconstruction

| Date | Run | Strategy | Fills | Settled / unresolved | Wins / losses | Spent | Reported MTM / net | Settlement net | Tail low / warm | Untrusted / pre-late | Basis | Gate |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 2026-06-18 | `taker-20260618-221a357c` | - | 0 | 0 / 0 | 0 / 0 | 0.0000 | 0.0000 / 0.0000 | 0.0000 | 0 / 0 | 0 / 0 | - | - |
| 2026-06-19 | `taker-20260619-221a357c` | missing legacy id | 50 | 50 / 0 | 5 / 45 | 59.8051 | -17.2087 / -17.2087 | 36.6878 | 0 / 0 | 0 / 0 | `paper_no_fee` | WARN |
| 2026-06-19 | `taker-20260619-3d3450f0` | missing legacy id | 4 | 4 / 0 | 0 / 4 | 10.0000 | 1238.7500 / 1238.7500 | -10.0000 | 0 / 0 | 0 / 0 | `paper_no_fee` | WARN |
| 2026-06-20 | `taker-20260620-3d3450f0` | missing legacy id | 50 | 50 / 0 | 0 / 50 | 66.9901 | 0.0000 / -66.9901 | -66.9901 | 0 / 0 on legacy tape | 14 / 0 | `paper_no_fee` | WARN |
| 2026-06-21 | `taker-20260621-bbe63642` | `raw_edge_control` | 50 | 50 / 0 | 1 / 49 | 65.8333 | 4401.8075 / 4401.8075 | -56.3094 | 31 / 0 | 27 / 0 | `paper_no_fee` | BLOCK |
| 2026-06-22 | `taker-20260622-3d74b86b` | `low_price_tail_capped` | 8 | 0 / 8 | 0 / 0 | 2.5968 | 6.6068 / 6.6068 | 0.0000 | 6 / 2 | 2 / 2 | - | MISSING_SETTLED_SAMPLE |

Aggregate settlement-scored result for labelable runs: `154` settled fills,
`6` wins, `148` losses, and `-96.611751` USDC settlement net PnL. Every settled
row is `paper_no_fee`, so live after-fee profitability is strictly unproven and
likely worse than this aggregate.

## MTM Is Not Profitability Evidence

MTM/settlement divergence is severe:

- June 21 reported `+4401.8075` MTM and finalized to `-56.3094`; finalization
  emits `reported_mark_to_market_diverges_from_settlement`,
  `resolved_mark_to_market_outlier`, `resolved_mark_to_market_sign_flip`, and
  `reported_net_pnl_diverges_from_settlement`.
- June 19 `taker-20260619-3d3450f0` reported `+1238.7500` MTM and finalized to
  `-10.0000`.
- June 19 `taker-20260619-221a357c` moved the other way: reported `-17.2087`
  MTM and finalized to `+36.6878`.

Conclusion: MTM is useful only as stale-price telemetry. It must not drive
quality, promotion, live-profitability claims, or budget scaling.

## Losing Slices

Settlement-scored losses are concentrated in a few obvious slices.

| Slice | Count | Settlement net |
| --- | ---: | ---: |
| hour 9 | 76 | -112.4995 |
| hour 7 | 18 | -12.6903 |
| NYC | 47 | -58.3864 |
| Toronto | 30 | -42.3657 |
| Atlanta | 42 | -25.5526 |
| Miami | 21 | -29.7610 |
| current-high distance `gt3` | 33 | -50.0646 |
| missing current-high distance | 104 | -113.1196 |
| `all_fresh / current_max_above_history_minor_gap` | 41 | -72.8425 |
| `all_fresh / wu_history_validated_current_max` | 57 | -62.3473 |

The legacy June 20 tape predates the current low/warm-tail columns, so the
canonical tail classification comes from
`data/backtest/taker_tail_casebook_2026-06-20_2026-06-21.md`. That casebook
shows `86` tail fills, `85` losing tail fills, `72` low-price-tail fills, `55`
warm-tail fills, and `-80.90935` USDC settlement PnL. Low-price-only tails went
`0/31` with `-24.98942` USDC, and low-price plus market-centered warm tails
went `0/41` with `-18.84514` USDC.

## Strategy Selection

The active default in current source is still `low_price_tail_capped`
(`src/weather/market/taker_bot_strategy_registry.py`), but the current evidence
does not qualify it for live trading:

- The existing champion/challenger ledger built from the available bakeoffs has
  `0` complete-label days; every bakeoff day is partial-quality.
- `low_price_tail_capped` has `17` settled bakeoff fills and `+3.2103`
  after-fee field PnL across the partial-quality bakeoffs, but this is not a
  valid promotion sample.
- The June 22 active run has `8` fills, `0` settled orders, `8` unresolved
  orders, `75%` low-price-tail fills, and promotion failures:
  `min_settled_orders`, `min_settled_markets`, `no_unresolved_orders`, and
  `max_tail_fill_fraction`.

Current code has important improvements: default `taker_fee_rate` is now `0.05`,
canary complete-label requirement is `3` days, market-centered warm-tail
blocking defaults to `*`, bad-tail no-go is enabled, missing snapshot cadence
blocks, and settlement-only rolling quality gates exclude MTM. Those are good
guardrails, but the historical runs being audited mostly used older configs
with `taker_fee_rate: 0.0`, warm-tail blocking limited to `raw_edge`, weak-slot
blocking limited to `raw_edge`, and current-high trust starting at hour `15`.

One source-code gap remains: `current_high_trust_gate_state` still contains an
`allow_pre_late_window` branch. The current default start hour is `0`, so the
default path is closed, but any config override can reopen the exact loophole
that affected the June 22 run.

## Operational Findings

- Finalization is now repaired for all labelable runs; June 22 remains
  legitimately `WAITING_FOR_LABELS`.
- `data/taker_runs/daily_roll_console.log` contains an earlier
  `OSError: [Errno 28] No space left on device`.
- Current disk capacity is healthy, but the previous failure justifies keeping
  disk preflight and retention enforcement active.
- PID `26204` is still alive as `pythonw` with near-zero CPU and a tiny working
  set. Liveness should be based on useful tape writes/heartbeats, not PID
  existence.
- `data/taker_runs/daily_roll_status.json` still reflects old launch defaults
  (`taker_fee_rate: 0.0`, current-high start hour `15`, warm/weak blocks limited
  to `raw_edge`). Any new paper run needs a fresh launch under current defaults.

## Current Answer

The taker bot does not yet have proven live edge. The last labelable evidence is
settlement-negative overall, all settled PnL is paper-no-fee, the strongest
positive candidate evidence comes from partial-quality bakeoffs, and the active
June 22 candidate has no settled sample. It should remain paper-only.

Immediate blocks before live execution:

1. Block low-price tails and market-centered warm tails unless the slice has
   repeated settlement-positive out-of-sample evidence.
2. Block aggressive untrusted-current-high fills from the start of day in code,
   not only through defaults.
3. Block any strategy promotion unless evidence is settlement-scored,
   after-fee, after-slippage, complete-label, and has no unresolved fills.
4. Relaunch paper runs under current fee and risk defaults; ignore the old
   `daily_roll_status.json` defaults for live-readiness claims.

Best path to profitability:

1. Keep the bot paper-only and run a fresh champion/challenger campaign under
   current defaults.
2. Require `3-5` complete-label settled days, enough fills across markets, net
   PnL after fees/slippage, no MTM sign flips, and stable per-market slices
   before promotion.
3. Prefer narrow, evidence-backed edges: trusted current-high lock-in,
   adjacent-band trades, and tiny two-sided/fade probes. Do not scale broad
   raw-edge or low-tail buying.
4. Use no-trade as a first-class action whenever the market benchmark beats the
   model in a slice.
5. Treat the two-sided NO arm as a promising research direction, but require
   real NO-book depth and the same settlement-only promotion loop before scale.

## Roadmap Follow-Ups

- Item 255: make current-high aggressive deny immutable against start-hour
  config regressions.
- Item 256: collect a fresh post-fix after-fee taker requalification campaign.
- Item 257: replace synthetic NO-book complement sizing with real NO-book
  depth before scaling the two-sided arm.
