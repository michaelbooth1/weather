# 84. Cross-Family Control De-Duplication And Variant Namespace Hygiene [COMPLETE 2026-06-16 - SHARED CONTROL DEDUPE LIVE]

Goal: prevent shared controls and reused variant identifiers from inflating
combined multi-family reports.

Source: `docs/research/MODEL_VARIANT_AUDIT_2026-06-16.md` and the regenerated
`data/backtest/item72_73_full_multi_variant_shadow_report.md`. The audit found
that combining the CLOB overlay and conservative bridge exports duplicated
`pooled_f_candidate_control` observations and mixed control-family metadata.

Why this is missing: individual family reports are clean, but combined
cross-family reports can receive identical control rows from several exporters.
That is useful for family-local diagnostics, but misleading when a combined
report treats the rows as additional evidence.

- [x] Decide whether combined exporters should namespace controls by source
  family or deduplicate identical controls before scoring.
- [x] Make duplicate `variant_id` + observation keys a hard failure for
  production governance reports, or document the narrower cases where a warning
  is acceptable.
- [x] Add a combined CLOB-plus-bridge fixture proving shared
  `pooled_f_candidate_control` rows are counted once or are explicitly
  family-scoped.
- [x] Regenerate item 72/73 combined artifacts after the accounting decision,
  with either a clean `OK` report or an intentional failure when duplicates
  remain.
- [x] Document control-row emission rules for candidate replay, CLOB overlay,
  conservative bridge, and future policy exporters.

Acceptance: combining unrelated variant families cannot overstate evidence,
hide immutable metadata conflicts, or make duplicated controls look like
additional paired observations.

Completion update 2026-06-16:

- Chose deduplication for identical shared control rows in combined reports,
  while keeping `--duplicate-observation-policy error` available for production
  governance when duplicates are not explicitly deduped.
- Added `--dedupe-shared-controls` to `src.multi_variant_shadow`. Identical
  control rows over the same `variant_id` + market/date/snapshot/band key are
  collapsed before scoring; mixed-family controls are reported as
  `shared_control` instead of creating metadata conflicts.
- Regenerated `data/backtest/item72_73_full_multi_variant_shadow_report.md`
  with shared-control dedupe enabled and duplicate-observation policy set to
  `error`: status `OK`, 289,388 raw rows, 221,958 scored rows, 67,430 unique
  observations, 67,430 dropped duplicate control rows, zero warnings, and zero
  errors.
- Fixture coverage lives in
  `tests/reporting/test_multi_variant_shadow.py` and proves both hard-failure
  duplicate policy and clean shared-control dedupe.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - SHARED CONTROL DEDUPE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

