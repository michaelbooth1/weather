# 278. Maker Model-Version Shadow Bakeoff [OPEN 2026-06-23 - MAKER TAPES SHOW ONE SERVED MODEL VERSION]

Goal: run a small pre-registered basket of model versions through maker quote
intent generation so maker strategy results can be separated from model-version
quality.

Source: the June 21-23 maker log audit found every raw maker quote row using
`v0.5.10 HGBC feature-based ML model`. Policy hashes varied, but the served
model version did not. The user asked whether more model versions could help
collect market-making data faster; the answer is yes for shadow evidence if the
variants are first-class and scored without increasing live risk.

Why this matters: a maker run can look weak because the quote policy is weak,
because the probability model is weak, or because the interaction is weak.
Current tapes do not let us distinguish those cases. Shadow model versions let
each market tick create counterfactual evidence without placing additional
orders or widening risk.

## Design

1. Define a small maker variant basket: current served model, current-high trust
   retrain, dynamic-source-freshness variant, conservative no-market baseline,
   and CLOB-overlay risk-only lane where available.
2. Emit quote-intent rows for each `(model_variant_id, policy_id)` pair in a
   shadow-only counterfactual tape.
3. Persist model artifact path/hash, runtime identity, feature schema, variant
   family, and prediction timestamp on every maker quote and counterfactual row.
4. Score variants against settlement, market top, no-trade, markout, and
   queue-estimated fill baselines using the same active-day slices.
5. Keep the basket small and frozen per campaign to avoid uncontrolled multiple
   testing.

- [ ] Add maker quote-time support for a configured model-variant basket.
- [ ] Persist first-class `model_variant_id` and model runtime identity on
  maker quote/counterfactual rows.
- [ ] Add maker model-version by policy score reports.
- [ ] Gate model-version conclusions through clustered statistical evidence.

Acceptance: maker reports can attribute positive or negative paper results to
model version, quote policy, or their interaction using a pre-registered variant
basket and settlement/markout-scored counterfactual rows.

Related: items 69, 83, 140, 216, 220, 258, 274.
