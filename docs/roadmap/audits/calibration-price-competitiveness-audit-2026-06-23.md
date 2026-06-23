# Calibration And Price-Competitiveness Audit - 2026-06-23

## Question

The latest week showed a clear pattern: the served model often identifies the
eventual final bucket by the end of the day, but still trails Polymarket on
Brier. June 22 was representative: raw model Brier improved to `0.0426`, while
market Brier was `0.0301`, so market-relative skill fell to `-41.6%`.

This audit asks whether the fix is simply more data, whether the roadmap already
owns the repair, and what work should be prioritized next.

## Evidence Reviewed

- `data/backtest/proper_scoring_reliability_scorecard.md`
- `data/backtest/market_benchmark_residual_edge.md`
- `data/backtest/weather_only_model_proof_packet_report.md`
- `data/backtest/f_family_promotion_refresh_report.md`
- `data/backtest/progress_audit_report.md`
- `data/backtest/settled_day_root_cause_report_2026-06-20.md`
- `data/snapshots/*/snapshots_long.csv` for target dates 2026-06-16 through
  2026-06-22
- `data/backtest/market_day_labels.csv`

## Finding

The problem is not just final-bucket recognition. It is a winner-rank and
winner-confidence gap versus the market, especially before final lock-in.

Across the comparable scored days in the last week, June 16, 17, 19, 20, 21,
and 22:

| Metric | Model | Market | Read |
| :--- | ---: | ---: | :--- |
| Row Brier | `0.0490` | `0.0406` | model trails by `+0.0083` |
| Brier skill | - | - | `-20.5%` |
| Winner-row probability | `48.5%` | `55.7%` | market recognizes winner sooner/stronger |
| Losing-row probability | `5.15%` | `4.57%` | model is slightly leakier on non-winners |
| Snapshot top-hit rate | `54.0%` | `63.7%` | market more often tops the eventual winner |

The winner row explains almost all of the Brier deficit:

| Row Type | Rows | Model Brier | Market Brier | Delta |
| :--- | ---: | ---: | ---: | ---: |
| Winner rows | 14,736 | `0.3918` | `0.3036` | `+0.0882` |
| Loser rows | 147,360 | `0.0147` | `0.0144` | `+0.0003` |

The sharpest diagnostic is the top-bucket parity split:

| Case | Snapshots | Model Brier | Market Brier | Winner Model P | Winner Market P |
| :--- | ---: | ---: | ---: | ---: | ---: |
| model top hit, market top hit | 6,673 | `0.0124` | `0.0108` | `0.8080` | `0.8325` |
| model top miss, market top miss | 4,084 | `0.0901` | `0.0856` | `0.1548` | `0.2074` |
| model top miss, market top hit | 2,665 | `0.0819` | `0.0311` | `0.2074` | `0.5405` |
| model top hit, market top miss | 1,267 | `0.0397` | `0.0729` | `0.4406` | `0.2744` |

The asymmetry is the problem. The model has real wins, but the market has about
twice as many snapshots where it tops the winner while the model does not. That
is why final-top success can coexist with weak all-day Brier.

## Not A Generic Sharpening Problem

Simple distribution temperature changes are not the fix. Re-normalizing the
model distribution is neutral to slightly worse, and power sharpening makes
Brier worse:

| Variant | Brier | Winner P | Top-Hit Rate |
| :--- | ---: | ---: | ---: |
| served model raw | `0.048980` | `0.4857` | `53.9%` |
| model power `0.70` | `0.048567` | `0.4575` | `53.9%` |
| model power `1.30` | `0.050385` | `0.5013` | `53.9%` |
| model power `1.50` | `0.051475` | `0.5087` | `53.9%` |
| market raw | `0.040649` | `0.5576` | `63.4%` |

Flattening slightly improves aggregate Brier but lowers winner probability and
does not close the market gap. Sharpening raises winner probability in some
snapshots but increases false high-confidence mass on wrong buckets. The right
repair is conditional centering/ranking, not global temperature scaling.

## Is It Just More Data?

No. More data is necessary for proof and retraining, but it is not sufficient.

More data is still required because:

- `progress_audit_report.md` shows only `36` promotion-grade market-days
  against an `84` market-day threshold.
- `settlement_source_revision_audit.md` reports only `54` proof-grade finalized
  labels and `147` labels that block promotion-grade use.
- June 18 had model probabilities for all 12 locations but no market prices, so
  it cannot validate market-relative skill.
- `market_benchmark_residual_edge.md` blocks frozen CLOB evidence because
  timestamp/book-age/token/bid/ask/depth fields are incomplete.

But current evidence already identifies structural failure modes:

- The market is better at topping the winner early and midday.
- The model is overconfident in some wrong mid/high probability buckets while
  under-ranking the true winner in many snapshots.
- Market-informed rows can approach market Brier only by leaning heavily on
  prices; that cannot prove weather-only edge.
- The current candidate improves current replay but still trails the market:
  `0.0395` candidate Brier versus `0.0308` market Brier in promotion refresh.

More settled days will improve confidence and training power. They will not by
themselves add the missing real-time ranking signal.

## Existing Roadmap Coverage

The roadmap already owns many ingredients:

| Area | Current Owner | Status | Read |
| :--- | :--- | :--- | :--- |
| Broad proof and claim gate | Item 160 | PARTIAL | still blocked by negative daily-first skill |
| Validate final served distribution | Item 233 | PARTIAL | right home for a trained calibration head |
| Exact winner and distance-0 early slices | Item 230 | PARTIAL | target slice live, no candidate clears tolerance |
| Bottom location winner centering | Item 219 | PARTIAL | directly targets Seattle, NYC, Miami early/midday gaps |
| Current-max trust retrain | Item 232 | PARTIAL | required retrain/ablation is still missing |
| Forecast/source-state reliability | Items 134, 135, 136 | PARTIAL | useful but still shadow-only or blocked |
| Continuous density | Item 35 | PARTIAL | likely needed for smoother ordinal ranking |
| Market-informed CLOB continuity | Item 156 | OPEN | needed before market-informed anchors are split-stable |
| Proper scoring scorecard | Item 262 | COMPLETE | diagnostic is live |
| Market benchmark/residual edge lane | Item 264 | COMPLETE | fail-closed separation is live |

The missing owner is not another broad model item. It is a cross-cutting parity
metric and repair queue for `model_top_miss | market_top_hit` cases. Current
reports surface parts of this in root-cause and proper scoring, but no active
item requires the count to fall or routes each case class back into the relevant
active repair lane.

## Roadmap Decision

Add one roadmap item:

- Item 266, `Winner-Rank Parity And Market-Top-Miss Repair Gate`

Do not add separate new items for:

- Generic more-data collection. Existing evidence-growth and settlement-source
  audit items already own this.
- Generic probability calibration. Item 233 owns validate-what-you-serve
  calibration; scalar temperature scaling is not supported by the evidence.
- Market-informed blending. Items 156 and 264 already own market data continuity
  and lane separation.

## Recommended Work Order

1. Add winner-rank parity as a generated daily report and proof-packet input.
   Track model top hit rate, market top hit rate, the `model_top_miss |
   market_top_hit` count, and its Brier contribution by market, date, local
   hour, source state, forecast disagreement, settlement distance, and runtime
   identity.
2. Use Item 266 to route cases to existing active owners:
   - early/predawn to Items 160, 219, 228, and 230;
   - ramp warm-tail cases to Items 194, 195, and 232;
   - served-distribution interactions to Item 233;
   - market-informed anchor evidence to Items 156 and 264.
3. Prioritize no-market winner-rank features over global sharpening:
   current-max trust fields, robust forecast consensus, source-state
   reliability, continuous-density/ordinal geometry, and bottom-location
   residual centering.
4. Keep market-informed overlays separate. They may improve quote gating and
   trading decisions, but they should not clear weather-only model promotion.
5. Continue evidence growth, but treat it as a validation/retrain dependency,
   not the main causal fix.

## Acceptance Evidence For The Fix

A credible repair should prove all of the following on active replay-contract
evidence:

- `model_top_miss | market_top_hit` Brier contribution falls materially versus
  current.
- Model top-hit rate closes the gap to market top-hit rate without increasing
  false high-confidence adjacent-band errors.
- Winner probability improves in the affected slices while broad Brier and
  log-loss stay within market tolerance.
- Bottom-location, exact-band/distance-0, early-hour, ramp, and late lock-in
  guardrails pass together.
- Weather-only and market-informed claims remain lane-separated.

Until that evidence exists, the correct read is: we are data-limited for proof,
but signal-limited for price competitiveness.
