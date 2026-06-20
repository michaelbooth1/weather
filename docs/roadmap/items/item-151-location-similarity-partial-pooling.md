# 151. Location-Similarity Partial Pooling [COMPLETE 2026-06-18 - WEIGHTED TRANSFER PATH LIVE]

Goal: build a no-market candidate that uses extra locations through
similarity-weighted partial pooling instead of flat pooling.

Source: `scratch/no_market_location_fast_audit.md` showed flat
target-plus-extra pooling regressed target-only history, while item 86 showed
that structured no-market candidate lanes can still improve current replay.
This item tests the more defensible hypothesis: extra locations might help when
their influence is weighted by climate, source, and forecast-error similarity.

Why this matters: transfer learning can produce negative transfer when source
and target distributions differ. Weather postprocessing also depends on local
station information. A candidate should therefore learn what transfers across
locations and shrink extra-location signal toward zero when it is not useful.

## Design

1. Compute location-similarity features from climate normal, climate variance,
   latitude/longitude, elevation, coastal/marine context, source-reliability
   priors, forecast-error covariance, and cutoff-regime behavior.
2. Train a partial-pooling residual or band model with explicit target-local
   weight and extra-location shrinkage. The target-local model remains the
   fallback when similarity evidence is weak.
3. Select pooling strength by blocked target-market validation, not by pooled
   aggregate score.
4. Compare at least four conditions: target-only, flat target-plus-extra,
   extra-only, and similarity-weighted target-plus-extra.
5. Require no target-market or early-hour regression beyond tolerance before
   the candidate can move from shadow to promotion consideration.
6. Export attribution showing which extra locations contributed weight to each
   target market and cutoff regime.

- [x] Add a similarity feature table for registered and extra no-market
  locations.
- [x] Add a weighted-transfer training path or postprocessor.
- [x] Add pooling-strength tuning with blocked daily-first validation.
- [x] Add per-target attribution of extra-location influence.
- [x] Compare weighted transfer against flat pooling and target-only in the
  item-149 harness.

Acceptance: weighted extra-location transfer is considered useful only if it
beats target-only and flat pooling on daily-first target-market validation,
with per-location weights and negative-transfer guardrails visible in the
report.

## 2026-06-18 implementation update

Added `weather.reporting.location_similarity_pooling`, with schemas
`location_similarity_features_v0.1` and
`location_similarity_partial_pooling_v0.1`.

Similarity features cover distance, elevation gap, climate-normal gap,
climate-variance gap, coastal match, source-reliability gap, and
forecast-error MAE gap. The weighting policy preserves an explicit
target-local weight and shrinks extra-location influence to zero when no extra
location clears the minimum similarity threshold.

`weather.reporting.no_market_location_transfer` now scores
`similarity_weighted_minus_target_only` alongside target-only,
flat target-plus-extra, and extra-only. The transfer report exports
per-target attribution rows showing each target-local and extra-location
weight, prediction, and contribution. The item-149 promotion gate still
prevents any weighted-transfer candidate from leaving shadow unless the
blocked daily-first self-comparison clears.
