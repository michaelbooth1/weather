# 142. Active Variant Registry Export Contract [COMPLETE 2026-06-18 - ACTIVE EXPORT CONTRACTS AUDITED]

Goal: make every active registry entry map to a concrete artifact, export path,
variant ID, and prediction function without manual CLI wiring.

Source: 2026-06-18 model-variant data audit. The active registry names
specific variants such as `item50_pooled_forecast_v3_candidate`,
`pooled_f_exact_winner_catchup_v0_1`, and
`pooled_f_dynamic_source_state_v0_1`, but the candidate replay default emits a
generic `pooled_f_candidate` ID unless callers override it. Promotion refresh
also disables candidate variant export by default with an empty
`--candidate-variant-out`.

Why this matters: active-variant reporting should be declarative. If the
registry says a variant is active, the scheduled pipeline should know how to
run it, where to write it, and how to validate that the emitted rows use the
registered ID.

## Design

1. Extend `config/model_variant_registry.json` with artifact path, prediction
   mode, export family, default output path, and optional postprocess
   parameters for active variants.
2. Add a registry validator that fails on active entries with no runnable
   artifact/export contract.
3. Update candidate replay and promotion refresh so registered IDs are the
   default for scheduled exports.
4. Require generated multi-variant reports to flag active registry variants
   that are missing from the current long table.
5. Keep archived, smoke, and alpha entries readable but excluded from scheduled
   active export unless explicitly requested.

- [x] Add export-contract fields to the registry schema and tests.
- [x] Add a registry audit command/report for missing artifact paths,
  duplicate IDs, and active variants absent from fresh evidence.
- [x] Update `pooled_candidate_replay` defaults so registered active IDs do not
  fall back to generic names.
- [x] Update `promotion_refresh` so scheduled candidate variant export is
  enabled when an active registry contract exists.
- [x] Add multi-variant governance warnings for active registry variants that
  did not produce rows.

Acceptance: every active registry variant is runnable and exportable from the
registry alone, and scheduled reports fail or warn when any active variant is
missing from fresh evidence.

## Implementation update - 2026-06-18

`config/model_variant_registry.json` now declares artifact paths,
`prediction_function`, `prediction_mode`, `export_family`,
`default_export_path`, `postprocess_config_hash`, and `live_runtime` for every
active headline variant. Policy-only variants explicitly set
`artifact_required=false`; archived, smoke, alpha, and extra-location shadow
lanes remain readable but excluded from scheduled active export.

Added `weather.reporting.variant_registry` audit support and schema
`model_variant_registry_audit_v0.1`. The audit checks duplicate IDs, missing
active export-contract fields, missing artifact/export paths, and active IDs
absent from configured evidence exports. The generated registry audit is `OK`.

`active_variant_shadow_refresh` now derives source paths from the registry when
no manual paths are supplied. The refreshed canonical active-shadow artifact is
`OK`: 8 active variants reported, 0 missing, 568,557 canonical rows, 76,879
unique observations, and 51 market-days. The refreshed
`model_variant_evidence_growth` artifact is `WARN` with the evidence SLA
passing and broad promotion claims allowed.

`pooled_candidate_replay` and `promotion_refresh` now inherit registry
contracts, so matching artifacts use registered variant IDs/families and
default export paths instead of falling back to generic names or disabled
exports. Multi-variant governance emits a warning when an active registry
variant is missing from a long table.

Verification:

- `python -m weather.reporting.variant_registry --json-out data\backtest\model_variant_registry_audit.json --report-out data\backtest\model_variant_registry_audit_report.md`
- `python -m weather.reporting.active_variant_shadow_refresh --variant-registry config\model_variant_registry.json --long-out data\backtest\active_variant_shadow_long.csv --json-out data\backtest\active_variant_shadow.json --report-out data\backtest\active_variant_shadow_report.md`
- `python -m weather.reporting.variant_evidence_growth data\backtest\active_variant_shadow_long.csv --baseline-predictions data\backtest\item86_no_market_bakeoff_multi_variant_shadow_long.csv --json-out data\backtest\model_variant_evidence_growth.json --report-out data\backtest\model_variant_evidence_growth_report.md`
- `python -m pytest -q tests\reporting\test_variant_registry.py tests\reporting\test_multi_variant_shadow.py tests\operations\test_daily_refresh.py tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py tests\operations\test_schema_registry.py tests\collection\test_live_variant_predictions.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - ACTIVE EXPORT CONTRACTS AUDITED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

