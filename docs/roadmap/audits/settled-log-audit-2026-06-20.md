# Settled Log Audit - 2026-06-20

Generated: 2026-06-21

Scope: settled 2026-06-20 normal location tapes, market-making run
`data/mm_runs/2026-06-20/20260620T233005288278Z`, and taker run
`data/taker_runs/2026-06-20/taker-20260620-3d3450f0`.

## Verdict

The model underperformed the market on June 20, and the active taker policy
turned that weakness into a real paper loss. The main failure was not bad
settlement mapping: all 12 settled labels reconcile to Polymarket. The failure
was warm-side winner centering in the morning/ramp window, plus an active taker
default that still spent on raw model edge when the market was more centered on
the eventual winner.

## Model Performance

One-day hourly scoring with partial labels included:

- Hourly checkpoints: model Brier `0.0503` versus market `0.0398`, delta
  `-0.0105`; model log loss `0.1691`, log-loss delta `-0.0360`.
- Hourly gate: `BLOCK`, with early-hour Brier and log-loss regressions.
- Worst hours by model Brier: local `09:00`, `08:00`, and `11:00`.
- Regime deltas: `00:00-08:00` Brier delta `-0.0048`,
  `09:00-14:00` delta `-0.0131`, `15:00-19:00` delta `-0.0247`.

One-day 10-minute scoring:

- Checkpoints: model Brier `0.0486` versus market `0.0383`, delta `-0.0103`.
- Weak slots: `05:00`, `06:40`, `07:30` through `09:10`, `12:30`, `14:10`,
  and `15:50`.
- Weak-slot winner probability: model `21.4%` versus market `34.8%`.
- Weak-slot effective-band gap: model spread was `0.86` bands wider than the
  market on average.

New diagnostic used here: fill-time final-winner join. For each taker fill, I
joined the bought band back to the same snapshot's final winning band row.
This showed the model often liked the bought warm band while the market was
more centered on the actual winner.

## Taker Bot

Finalized taker report:

- Filled orders: `50`
- Settled wins/losses: `0 / 50`
- Spend: `66.9901` USDC
- Net P&L: `-66.9901` USDC
- Fill timing: 12 fills at local hour `07`, 38 fills at local hour `09`
- Filled markets: Toronto, NYC, Atlanta, Miami

Fill-time final-winner comparison:

| Market | Spent | Bought avg model/market P | Final winner model/market P at same snapshots |
| :--- | ---: | :--- | :--- |
| atlanta | 13.6090 | 14.5% / 3.2% | 27.6% / 36.0% |
| miami | 13.5996 | 11.5% / 3.0% | 37.5% / 49.5% |
| nyc | 17.7758 | 18.9% / 4.3% | 22.0% / 59.2% |
| toronto | 22.0057 | 14.2% / 4.9% | 8.9% / 38.6% |

The refreshed full-tape bakeoff over 131,857 input rows is more useful than
the older partial-run bakeoff:

- `raw_edge_control`: blocked, about `-64.6` USDC settled net P&L.
- `calibrated_edge`: mechanical pass, `+1.9` USDC.
- `low_price_tail_capped`: mechanical pass, `+5.7` USDC.
- Global blocker remains `partial_target_date_labels`, so June 20 alone should
  not promote a strategy.

Action created: item 192, "Taker Active-Policy Warm-Tail Kill Switch And Arm
Cutover".

## Root-Cause Addendum

The follow-up root-cause pass points to multiple interacting failures:

- Raw forecast highs were not the primary explanation for taker losses. At fill
  time, Atlanta, Miami, NYC, and Toronto raw forecast highs were often near or
  below the final settlement, but the distribution still put enough probability
  in cheap warm tails for the taker policy to buy them.
- WU current-max support was suspicious in some weak windows. Houston showed
  `wu_max_since_7am_c=93` against final `84-85 F`; Seattle showed
  `wu_max_since_7am_c=81` against final `70-71 F`. Those values can warm the
  model if they are treated as trusted current-high evidence.
- High forecast-source disagreement let isolated warm guidance over-center the
  distribution in the morning/ramp window, especially Austin, Houston, Seattle,
  Denver, and NYC.
- The model had a ramp-window ordinal-centering problem from local
  `08:00-14:59`: it spread too much mass one to three bands warm while current
  observations and robust forecast anchors already pointed lower.
- Late-day lock-in components were accurate when available, but too sparse. The
  model trailed the market in `15:00-19:00` because it did not saturate toward
  already-reached highs quickly enough on enough rows.
- Startup feature rows for several F markets leaked `17.0` as high/current
  temperature while live observations were missing, producing implausible
  forecast gaps. This did not drive the taker fills directly but contaminates
  live-forward scoring and training exports.

Actions created from this pass: items 193 through 198, covering current-max
quarantine, forecast warm-outlier dampening, ramp-window centering, late-day
lock-in coverage, startup observation null/unit guards, and a canonical
settled-day root-cause report.

## Market-Making Bot

Run `20260620T233005288278Z` was operationally conservative:

- Mode: `paper-live-forward`
- Ticks: `206`
- Quote-intent rows: `27,192`
- Quote-permission rows: `687`
- Fills: `0`
- Live-trade rows: `0`
- Latest preflight: `STALE`
- Latest quote outcome: `preflight_blocked`

Top quote reasons:

- `NO_QUOTE_KNOWN_EDGE_PERMISSION`: `10,725`
- `NO_QUOTE_STALE_INPUT`: `6,171`
- `NO_QUOTE_MISSING_BOOK`: `6,149`
- `NO_QUOTE_INFORMATION_EVENT`: `3,256`
- `QUOTE_HARVEST_MID`: `687`

This run avoided loss because no fills occurred. The issue was liveness and
permissioning, not bad execution: latest-tick preflight was stale across all
12 markets, with model freshness, CLOB book freshness, and observation watcher
staleness contributing. Existing liveness items cover this unless the same
late-day stale pattern recurs.

## Normal Location Logs

All 12 settlement files reconcile with Polymarket and have `quality_grade`
`partial`, mostly because WU snapshot coverage had small gaps:

- Snapshot counts ranged from `176` to `315` per market.
- Max unique snapshot gap was about `20.9` minutes.
- Settlement coverage gaps were 2-7 gaps per market, max 16-21 minutes.

Source-health issues were present but not large enough to explain the model
miss:

- `wu_history`: 80 failed rows, mostly HTTP 400s.
- Denver `metar`: 16 `stale_cache` rows.
- Toronto `wu_current`: 2 `stale_cache` rows.

Every active variant prediction row for June 20 was `skipped` with
`unsupported_runtime`. That is a serving gap, but it is already represented by
item 140, "Live First-Class Variant Prediction Tape".

## Follow-Up

Do not promote from June 20 alone because labels are partial, but do use it as
negative evidence against raw-edge active default. The next useful analysis is
to replay item 192's active-arm cutover and weak-slot kill switch on June 19 and
June 20 together, then require the active taker run config to name the passed
arm before another active-paper run can spend.
