# Agent Report - 2026-07-22 Workstation H2 Validation Audit

## Outcome

**The 2026-06-20 H2 leakage defect no longer survives in current source.** No
new repair was needed. The feature-model baseline and ML arms now use the same
leave-one-year blocked indices, preprocessing is fitted inside each training
fold, and reported temperature/blend calibration is nested inside each outer
training block.

This closes the source-code audit question, not artifact provenance. The
workstation fallback artifacts used by replay are demonstrably older than the
complete correction, so their historical validation scores must not inherit
the current source guarantee. A future release needs a fresh artifact and a
training receipt bound to the corrected path.

## Original defect

The core-model audit found an asymmetric comparison:

- climatology excluded the entire validation year;
- HGB/LR excluded only one validation row;
- temperature and blend constants were then selected on those leaky HGB
  predictions.

That gave ML nearby same-season observations that the baseline was denied and
could bias both claimed lift and selected sharpness.

## Current-code trace

`feature_blocked_validation_plan(records, mode="holdout_year")` builds one
canonical set of training indices for every validation row. In the training
loop:

1. `train_indices` comes only from that blocked plan;
2. baseline `train_days` is indexed by exactly those indices;
3. LR and HGB use `y.iloc[train_indices]` and fold matrices constructed from
   exactly those same indices;
4. median imputation and scaling are fitted by
   `fold_local_feature_matrices` on the outer training fold only; and
5. reported tuned predictions come from
   `nested_temperature_blend_predictions`, whose inner blocked OOF search is
   confined to the outer training block.

The full-corpus blocked OOF fit is retained only to choose the final serving
transform; it is reported separately from nested outer-fold validation. The
generated honest-validation rows name the evaluation contract
`nested_inner_oof_by_outer_train_block` and count any fallback rows.

## Artifact-lineage follow-up

The complete fold-local preprocessing and nested outer-fold calibration repair
entered source in commit
`e4685cec29980f4bdfaf532148f787df4704351e` at
2026-07-12 18:55:22 ET. The workstation has no immutable active-release pointer,
so its ordinary model fallback resolves the 12 checked-in per-market
`feature_model_hgb*.pkl` files. The most recent repository commit touching
every one of those files is `5b6f5af2d396a7847873ffeb80889c0aaba2194a` at
2026-06-20 15:43:24 ET, before the repair. Their sorted canonical inventory
(`filename|SHA-256|artifact commit`, newline terminated) hashes to
`67A55AFD89B53EBF172E198CB643FC0633E74FA46B46B4CD8C848E98E8043692`.

The tracked pooled-F v0.3 artifact does contain a clean blocked-split audit,
but that is not proof of nested calibration. Its SHA-256 is
`3B472BD32667256C6605A6F48C2C9C4BA7E58F140A89C504C4B4FBFCAC6A497C`,
its embedded `trained_at` is `2026-07-07T03:40:16.487345`, and its audit reports
zero split leaks across 28,322 rows. It too predates the July 12 change that
added fold-local preprocessing and `nested_temperature_blend_predictions`.
Thus split symmetry is proven for that artifact, while calibration-selection
independence is not.

## Verification

The focused audit ran:

```powershell
.\venv\Scripts\python.exe -m pytest tests\model\test_feature_model_ablation.py tests\calibration\test_blocked_validation.py -q
```

Result: **14 passed**.

The tests assert validation-year exclusion, zero split leakage, fold-local
preprocessing, and nested calibration behavior. No mirror file or serving
artifact was written.

## Disposition

Do not implement the old H2 fix again. Keep the blocked-split and nested-tuning
tests as the ratchet. Retrain any candidate meant to rely on H2 evidence, bind
the exact code/artifact/input hashes and nested-calibration counters in a
training receipt, then rerun replay gates. Source inspection and a zero-leak
split audit cannot retroactively certify the older pickles.
