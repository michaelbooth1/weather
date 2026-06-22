# 212. Snapshot Cadence As Model-Quality And Trading-Permission Input [COMPLETE 2026-06-22 - CADENCE QUALITY NOW HAIRCUTS CONFIDENCE AND PERMISSION]

Goal: make snapshot cadence a first-class model-quality input that reduces
model confidence and taker/MM trading permission when captures are stale or
gappy, instead of leaving cadence solely as an operations alert.

Source: the 2026-06-21 log review. Fleet cadence proof was `BLOCK` for all 12
active markets with `54` unknown snapshot gaps and max gap `22.14` minutes,
while source-status proof still reported zero blocked markets. The taker tape
also showed `NO_TRADE_STALE_BOOK` / source-stale reasons, and MM preflight
blocked on freshness even though the model probabilities were highly confident
in several markets.

Why this matters: a model probability computed from stale or irregularly
captured inputs is not equivalent to a probability computed from a clean
live-forward tape. If cadence does not enter reliability scoring and trade
permission, the system can present high-confidence bands while the evidence
path is not clean enough for model review, taker fills, or MM quotes.

## Design

1. Convert snapshot cadence proof into per-market features:
   recent max gap, gap count over threshold, last successful model row age, and
   whether the current snapshot came from scheduled or triggered cadence.
2. Feed those features into reliability adjustment for served probabilities and
   expose the adjustment in snapshot explanations.
3. Add taker and MM policy gates that reduce size, widen quotes, or deny
   permission when cadence is outside the live-forward SLO.
4. Keep the existing ops alert, but ensure the consumer-side tape records the
   exact cadence reason that changed confidence or permission.

- [x] Add per-market cadence-quality fields to snapshot/source-status or model
  explanation tape.
- [x] Apply a confidence haircut for gappy cadence in the model reliability
  layer.
- [x] Add taker permission/size behavior for cadence degradation.
- [x] Add MM quote permission/widen behavior for cadence degradation.
- [x] Add tests for a high-probability stale-cadence row losing permission or
  confidence.

## Completion Notes

Added a shared `snapshot_cadence_quality` helper that normalizes cadence state,
recent gap count, max gap seconds, model-row age, confidence multiplier,
permission, and reason. Snapshot long/wide rows, snapshot JSONL, replay inputs,
and live variant prediction rows now carry cadence-quality fields. Variant
prediction rows also write cadence-adjusted served and variant probabilities.

Taker reliability scoring now includes cadence state in the reliability context,
multiplies confidence by the cadence haircut, records the cadence reason on the
order tape, and denies buys with
`NO_TRADE_SNAPSHOT_CADENCE_DEGRADED` when explicit cadence gaps exceed the SLO.
MM quote intents now carry the same cadence fields, compute a
cadence-adjusted fair probability, and deny quotes with
`NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED` by default; the policy can instead use the
configured cadence size/widen behavior when degradation is not set to deny.

Verification:

- `python -m pytest tests\collection\test_live_variant_predictions.py tests\collection\test_collection_robustness.py tests\market\test_mm_policy.py tests\market\test_taker_bot.py -q`
- `python -m pytest tests\market\test_market_making_run.py -q`

Acceptance: when a market has recent snapshot cadence gaps above the SLO, the
served model output, taker orders, and MM quote intents all carry an explicit
cadence-quality state, and stale/gappy cadence lowers confidence or permission
even if provider source status is otherwise fresh.

Related: items 31, 54, 116, 136, 157, 210.
