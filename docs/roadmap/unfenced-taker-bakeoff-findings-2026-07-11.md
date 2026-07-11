# Unfenced Taker Bakeoff Sweep — Findings (2026-07-11)

## Question

Should `fade_overpriced` (item 253, NO-side arm) enter the live paper basket?
Decided bakeoff-first (item 238): replay all registered strategies over the
historical run tapes with the edge-permission fence disabled, since the fence
requires settled-order evidence that fenced arms can never generate.

## Method

`weather.reporting.research.unfenced_taker_bakeoff_sweep`: re-ran the daily
strategy bakeoff over 24 historical run folders (2026-06-18 → 2026-07-11, one
per day, largest recorded tape) with `taker_edge_permission_enabled: false`
for the counterfactual arms only. Output isolated in
`data/backtest/research/unfenced_bakeoff/` (daily fenced artifacts and the
champion ledger untouched). Override verified via strategy policy-hash change.

## Result

**Zero counterfactual fills. Every strategy, every day, fence on or off.**

Root cause, from 431,145 recorded decision rows:

| | |
| --- | --- |
| Rows with positive calibrated after-fee edge | 162 (0.04%) |
| Rows with after-fee edge > 0.05 | **1** (cadence-degraded snapshot, permission=deny — a false edge, correctly refused) |
| Top reason codes | `EDGE_TOO_SMALL` 112k, `EARLY_HOUR_CURRENT_HIGH_GUARDED` 108k, `MARKET_CENTERED_WARM_TAIL` 52k, `BAD_TAIL_NO_GO` 39k, `SNAPSHOT_CADENCE_DEGRADED` 34k |

The calibrated fair (`market_bias_calibration`) anchors the tradeable fair to
the market price in slices where the model has no demonstrated
settlement-scored skill. With the model trailing the market (+0.0160 Brier on
the 297-day corpus), the calibrated edge is ≈0 essentially everywhere — the
zero-fill month is a **correct no-edge assessment**, not a plumbing failure.

## Conclusions

1. **The permission fence and the strategy basket are not the binding
   constraint — model skill is.** Activating `fade_overpriced` (or any arm)
   changes nothing today: there is no calibrated after-fee edge to take.
   Activation is deferred until the edge surface opens.
2. **Every fail-closed layer agrees independently** (permission map,
   calibration anchor, promotion gates, bakeoff): "model does not yet beat
   the market after fees." The system is internally consistent.
3. **The lever is the model-skill experiment queue** (predawn/evening
   repairs) — exactly the loop the week's infrastructure work unblocks. When
   slice-level skill appears, the calibration opens the edge surface, the
   permission map starts allowing, the daily (fenced) bakeoff starts
   filling, and the champion ledger produces activation evidence with no
   further wiring.
4. Secondary finding: ~8% of decision rows were lost to
   `SNAPSHOT_CADENCE_DEGRADED` — capture degradation directly shrinks the
   future decision surface, reinforcing the collection-protection work.
5. The sweep is rerunnable (`python -m
   weather.reporting.research.unfenced_taker_bakeoff_sweep`) and should be
   rerun after material model-skill improvements as the cheap leading
   indicator of taker viability — replay evidence, hours not weeks.
