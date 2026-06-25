# 315. First-Class Repair Integration Into The Active Artifact And Replay Contract (Retire The Row-Export Surrogate) [COMPLETE 2026-06-25 - ACTIVE REPAIR INTEGRATION CONTRACT ADDED]

Goal: replace the "score a validated repair as a row-export surrogate" shortcut
with a first-class path that folds a validated repair into the active candidate
artifact and re-runs the real active-replay/export contract, so repairs
consolidate into serving instead of fragmenting into one-off scoped wins.

Source: 2026-06-25 gate audit and the recurring 178/219/224/301 pattern.
`weather.reporting.candidate_variant_replay_summary` defines `validation_evidence`
as either `row_export_surrogate` (explicitly listed in `NON_COUNTABLE_ROW_MARKERS`)
or `active_replay_contract`. Validated repairs - predawn weak-slot, bottom-location
winner-centering, the item 301 location-bias packet - are scored as surrogates and
pass their own scoped gates, but the canonical `f_family_promotion_refresh`
stays stale (zero `winner_centering` mentions, aggregate still trails market by
+0.0067) because nothing integrates them into the active artifact. The result is
many individually-validated repairs that never move the aggregate market gate.

Why this matters: the surrogate is a quick preview that lets a repair "count"
against its own gate without the expensive active re-export. Used as the end
state, validated improvements never reach serving or promotion - this is exactly
the "each repair passes its own gate but never consolidates" failure the project
keeps hitting, and it is the structural reason the north-star
aggregate-Brier-minus-market has not moved despite many closed repair items.

Why it is not already covered: candidate_variant_replay_summary owns the
surrogate adapter and the promotion path consumes it, but no item owns the
integration that promotes a validated repair from `row_export_surrogate` to
`active_replay_contract` by folding it into the active artifact and re-running the
real replay. Item 224 re-exported the pooled artifact but did not fold in the
validated repairs; item 269 measures market-beating but does not integrate.

## Design

1. Add a repair-integration step that applies a validated repair (predawn,
   winner-centering, location-bias) to the active candidate artifact itself - not
   just a row export - and re-runs the real `pooled_candidate_replay` / export
   contract.
2. Consolidate multiple validated repairs into one candidate before re-scoring,
   so 178 (parity), 219/301 (location), and 160 (early-hour) combine rather than
   each being scored in isolation.
3. Make promotion countability require `active_replay_contract` evidence for any
   repair that changes serving; mark surrogate evidence preview-only with an
   explicit `not_yet_integrated` status.
4. Report which validated repairs are integrated versus still surrogate, and the
   consolidated candidate's aggregate-vs-market delta.

- [x] Add a repair-integration step that folds a validated repair into the
  active candidate artifact and re-runs the real replay/export contract.
- [x] Consolidate multiple validated repairs into one candidate before scoring.
- [x] Require active-replay-contract evidence for promotion of serving-changing
  repairs; mark surrogate evidence preview-only.
- [x] Report integrated-vs-surrogate repairs and the consolidated
  aggregate-vs-market delta.
- [x] Add an end-to-end test proving a surrogate-validated repair can be
  integrated, re-scored on the active contract, and reflected in the canonical
  promotion artifact.

Acceptance: a validated repair is integrated into the active candidate artifact
and re-scored through the real replay/export contract rather than a row-export
surrogate, multiple repairs consolidate into one candidate, the canonical
promotion artifact reflects the integrated repairs, and surrogate evidence can no
longer satisfy promotion countability, proven by an end-to-end integration test.

Related: items 35, 178, 219, 224, 269, 296, 301.

## Completion Notes

Implemented a first-class repair integration contract in
`weather.reporting.repair_integration`. The new artifact consumes validated
repair specs, consolidates their countable rows into one active candidate export,
writes a registry/contract sidecar with `live_runtime=repair_integration_active_contract`,
and re-scores the consolidated candidate through
`candidate_variant_replay_summary` with `validation_evidence=active_replay_contract`.
The CLI writes both the integration wrapper and a promotion-refresh-compatible
active replay summary JSON/Markdown pair for direct
`--precomputed-candidate-json` consumption.

Promotion now treats explicit `row_export_surrogate` evidence as preview-only for
cutover/readiness, while active-contract repair candidates expose their
`repair_integration` metadata through the promotion candidate summary. Repair
rows are reported as `integrated` or `not_yet_integrated`, and the active variant
shadow refresh executor can regenerate repair-integration exports from a registry
entry and `repair_specs_path`.

Validation:

- `python -m pytest tests\reporting\test_repair_integration.py -q`
- `python -m pytest tests\reporting\test_variant_registry.py tests\operations\test_schema_registry.py::TestSchemaRegistry::test_registry_lookup_returns_public_versions -q`
- `python -m pytest tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_active_variant_shadow_refresh.py -q`
- `python -m pytest tests\calibration\test_promotion_refresh.py -q`
