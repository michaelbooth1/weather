# 278. Maker Model-Version Shadow Bakeoff [COMPLETE 2026-06-23 - MAKER MODEL-VARIANT BAKEOFF LIVE]

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

- [x] Add maker quote-time support for a configured model-variant basket.
- [x] Persist first-class `model_variant_id` and model runtime identity on
  maker quote/counterfactual rows.
- [x] Add maker model-version by policy score reports.
- [x] Gate model-version conclusions through clustered statistical evidence.

Acceptance: maker reports can attribute positive or negative paper results to
model version, quote policy, or their interaction using a pre-registered variant
basket and settlement/markout-scored counterfactual rows.

Completion evidence 2026-06-23:

- Maker quote rows now carry first-class model identity fields:
  `model_variant_id`, family, role, basket id/size, probability source,
  prediction timestamp, artifact path/hash, feature schema, runtime identity,
  served model version, and served fair probability. Served quote rows are
  tagged `served_current`.
- `build_run_once` writes a separate
  `model_variant_quote_intents_long.csv` counterfactual tape plus
  `model_variant_bakeoff.json` and `model_variant_bakeoff.md`. The default
  frozen basket includes served-current, current-high trust, dynamic-source
  freshness, conservative no-market baseline, and CLOB-overlay risk-only lanes;
  unavailable probability sources are reported as skipped rather than copied
  from the served model.
- Operators can configure external precomputed variant exports with
  `maker_model_variant_paths`; matching rows are joined by
  `(market_id, target_date, snapshot_id, band_key)` and run through the same
  `decide_quote` policy path as served maker inputs.
- The standard maker paper scorer now loads model-variant quote tapes, simulates
  conservative fills through the same markout/settlement engine, and reports
  `(model_variant_id, policy_hash)` quote rows, quote legs, fills, settlement
  P&L, net after fees/incentives, and deltas versus `served_current`.
- Model-version promotion is explicitly blocked inside the bakeoff payload by a
  `clustered_statistical_gate_required` promotion gate, routing conclusions to
  item 279 instead of allowing row-count-only claims.

Validation:

- `python -m pytest tests\market\test_market_making_run.py tests\market\test_mm_policy.py tests\market\test_mm_paper.py tests\reporting\test_trading_evidence.py -q`
- `python -m py_compile src\weather\market\market_making_model_variants.py src\weather\market\market_making_run.py src\weather\market\mm_policy.py src\weather\market\mm_paper.py src\weather\market\mm_paper_reports.py src\weather\reporting\trading_evidence.py`

Related: items 69, 83, 140, 216, 220, 258, 274.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - MAKER MODEL-VARIANT BAKEOFF LIVE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

