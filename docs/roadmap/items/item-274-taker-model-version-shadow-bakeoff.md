# 274. Taker Model-Version Shadow Bakeoff [COMPLETE 2026-06-23]

Goal: run a small, pre-registered set of true model versions through the taker
candidate and counterfactual scorer so strategy performance is not confounded
with a single served model.

Source: the June 21-23 taker audit found every taker candidate row using
`v0.5.10 HGBC feature-based ML model`. The June 23 six-arm smoke varied
strategy policy, not model version. The user asked whether more model versions
could help collect taker bot data faster; the answer is yes for shadow
evidence, if variant identity is first-class and promotion is statistically
gated.

Why this matters: a strategy can look bad because the entry policy is bad, the
served probabilities are bad, or both. True model-version shadowing lets us
separate model calibration/winner-ranking failures from taker policy failures
without spending additional budget.

## Design

1. Select a small variant basket from the existing registry: current served
   model, dynamic-source-state, exact-winner/catch-up, continuous-density, and
   market/CLOB-overlay lanes where available.
2. Write `model_variant_id`, model family, artifact/runtime identity, feature
   schema, and prediction timestamp onto every taker candidate and
   counterfactual row.
3. Score each `(model_variant_id, strategy_id)` pair against settlement,
   no-trade, and market-top baselines.
4. Require model-version promotion evidence to be clustered by target day and
   market, not by raw row count.
5. Keep the model basket small and pre-registered to avoid uncontrolled multiple
   testing.

- [x] Wire taker candidate generation to request predictions from a configured
  model-variant basket.
- [x] Persist first-class `model_variant_id` and runtime identity on taker
  order/counterfactual rows.
- [x] Add settlement-scored model-version by strategy reports.
- [x] Add a multiple-testing-aware promotion summary for variant selection.

Acceptance: taker reports can say whether a positive or negative result belongs
to the strategy, the model version, or their interaction, using a small
pre-registered variant basket and settlement-scored evidence.

Completion evidence (2026-06-23):

- Taker order rows now carry first-class model identity fields:
  `model_variant_id`, family, role, basket id/size, probability source,
  prediction timestamp, served model version, artifact path/hash, feature
  schema, and runtime identity.
- Counterfactual generation expands live candidate inputs through a
  pre-registered model-variant basket. `served_current` always uses the served
  probability; shadow variants such as `dynamic_source_state`,
  `exact_winner_catchup`, `continuous_density`, and `clob_overlay` materialize
  only when their configured probability columns are present, avoiding
  fabricated duplicate evidence.
- Variant identity is part of the taker intent key, so `(model_variant_id,
  strategy_id)` rows cannot be deduped into a single served-model row.
- Settlement finalization now emits a `model_variant_bakeoff` section in the
  counterfactual payload/report with `(model_variant_id, strategy_id)` P&L,
  delta versus served-current for the same strategy, and a
  `bonferroni_pre_registered_basket` multiple-testing summary.
- Regression coverage proves a shadow model probability can create positive
  settled counterfactual P&L while the served-current row does not trade, and
  the variant remains blocked by the settled-sample gate until enough evidence
  accrues.

Validation:

- `python -m pytest tests\market\test_taker_bot.py -q`
- `python -m pytest tests\market\test_taker_bot_two_sided.py -q`
- `python -m py_compile src\weather\market\taker_bot_strategy_registry.py src\weather\market\taker_bot_strategy_evaluation.py src\weather\market\taker_bot_bakeoff.py src\weather\market\taker_bot_finalization.py src\weather\market\taker_bot_cli.py`

Related: items 69, 83, 140, 216, 256, 273.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

