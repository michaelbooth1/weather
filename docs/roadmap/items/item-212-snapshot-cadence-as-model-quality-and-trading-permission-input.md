# 212. Snapshot Cadence As Model-Quality And Trading-Permission Input [OPEN 2026-06-22 - CADENCE GAPS MUST REDUCE CONFIDENCE]

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

- [ ] Add per-market cadence-quality fields to snapshot/source-status or model
  explanation tape.
- [ ] Apply a confidence haircut for gappy cadence in the model reliability
  layer.
- [ ] Add taker permission/size behavior for cadence degradation.
- [ ] Add MM quote permission/widen behavior for cadence degradation.
- [ ] Add tests for a high-probability stale-cadence row losing permission or
  confidence.

Acceptance: when a market has recent snapshot cadence gaps above the SLO, the
served model output, taker orders, and MM quote intents all carry an explicit
cadence-quality state, and stale/gappy cadence lowers confidence or permission
even if provider source status is otherwise fresh.

Related: items 31, 54, 116, 136, 157, 210.
