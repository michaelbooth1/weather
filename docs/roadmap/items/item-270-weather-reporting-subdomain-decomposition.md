# 270. weather.reporting Subdomain Decomposition (Folder Cohesion After Size-Splits) [COMPLETE 2026-06-25 - REPORTING ROOT RATCHETED]

Goal: group the now-small `weather.reporting` modules into cohesive subpackages
by reporting subdomain, so the package is navigable and the import-architecture
ratchet can enforce boundaries *inside* reporting, not just between top-level
packages.

Source: the 2026-06-23 project structure review. `weather.reporting` has
**131 flat `.py` modules / ~76k lines** — 44% of the source package's files and
lines — with only one subpackage (`promotion/`). This is the *result* of the
completed module-size decomposition (items 98/130/173): large reporting modules
were correctly shattered into small single-purpose siblings
(`fleet_observability` -> `_payload/_render/_gates/_inventory/_loops/_cli`;
`promotion_refresh` -> `_decisions/_readers/_report/_orchestration/_gap_analysis`;
`hourly_model_performance` -> `_context/_gate/_scoring/_slots/_render/_cli`), but
the siblings were left at the package root, so cohesion got worse even as module
size got better. The module-size audit (warns at 2,000 lines) is green — the
largest reporting module is 1,892 lines — so this is purely a *foldering /
boundary* problem, not a size problem.

Why this matters: a 131-module flat package is hard to navigate, hides which
modules are recurring production reports versus one-shot research dispositions,
and gives the architecture ratchet no way to keep, say, a research disposition
from importing the promotion pipeline. The project-structure action plan
(2026-06-22) already names this: "`weather.reporting` is too broad and should
split by reporting subdomain," and concludes the next improvements should happen
*inside* the existing package structure. No item owns executing it.

Why it is not already covered: items 90/98/130/173 own large-module *size*
decomposition (splitting one big file into owners) and are COMPLETE; none owns
grouping the resulting modules into subpackages. Item 254 (serving-runtime
extraction) addressed a model/calibration boundary, not reporting cohesion.

## Constraint (do not break)

`weather.schema_registry` pins generated artifacts to fully-qualified module
paths (`module="weather.reporting.X"`); each reporting module that emits a
registered artifact is referenced there (~3 refs each for the one-shot
dispositions). Daily-refresh orchestration, CLIs, and tests import these paths.
Moves must update `schema_registry` module strings and importers **atomically**,
not leave a second permanent shim API (compat shims are being retired under
item 206).

## Design

1. Define the subdomain taxonomy and move modules into subpackages, one
   subdomain per change, each fully green:
   - `reporting/fleet/` - `fleet_observability*` (7)
   - `reporting/promotion/` (exists) - absorb `promotion_refresh*`,
     `promotion_corpus`, `promotion_gauntlet`
   - `reporting/hourly/` - `hourly_model_*`, `ten_minute_model_performance`,
     `candidate_hourly_performance`
   - `reporting/data_quality/` - `data_layer_audit*`, `data_auditor`,
     `*_quarantine`, `*_retention*`, `artifact_disk_budget`, `*coverage_audit`
   - `reporting/daily/` - `daily_learning*`, `daily_progress_ledger`,
     `daily_flow_analysis`, `daily_rollup_freshness`
   - `reporting/scorecards/` - `snapshot_evaluation`, `progress_audit`,
     `proper_scoring_reliability_scorecard`, `winner_rank_parity`,
     `weather_only_model_proof_packet`, `settled_day_root_cause`,
     `frozen_baseline_replay_trend`, `model_history`,
     `distribution_stage_attribution`
   - `reporting/validation/` - the `*_validation` modules (11)
   - `reporting/casebooks/` - `disagreement_casebook`, `taker_tail_casebook`,
     `winner_underpricing_casebook`
   - `reporting/market/` - `market_*`, `trading_evidence`
   - `reporting/research/` - item-prefixed one-shot dispositions and repairs,
     location/regime one-shots (`austin_*`, `predawn_*`,
     `bottom_location_winner_centering`, `cross_hub_research_audit`,
     `late_day_lock_in_repair`, `exact_band_distance_zero_calibration`), and
     narrow diagnostics such as blocked-market repair, forecast-profile/source
     reliability, forecast double-counting, and reanalysis synoptic ablation.
   - `reporting/candidate_lifecycle/` - active shadow refresh, candidate replay
     summaries, variant registries/evidence, repair integration, shadow monitors,
     disagreement analysis, price-free learning, and current max-trust gates.
   - `reporting/source_gates/` - source-family inventory/redundancy, source
     promotion gates, settlement-source audit, cross-hub readiness, and weak-input
     family disposition.
   - `reporting/serving_gates/` - served-distribution contracts, runtime identity
     reconciliation/evidence, model-scoring liveness, and serving/early-hour gates.
   - `reporting/location_analysis/` - location trust, similarity pooling,
     location-bias repair, transfer reports, extra-location registry, and
     pooled-F location gates.
   - `reporting/roadmap/` - roadmap backlog maintenance CLI.
   - keep only shared helpers at root (`formatting`, `overview_helpers`,
     `__init__`).
2. Update `schema_registry` module paths and all importers in the same change as
   each move; no root re-export shims.
3. Extend the import-architecture ratchet with intra-`reporting` rules: research
   dispositions and validation must not be imported by production pipelines
   (fleet/promotion/daily/scorecards); shared helpers may be imported by all.
4. Add a one-time guard that fails if a new module lands directly in
   `reporting/` root outside the shared-helper allowlist, so the flat package
   cannot re-accumulate.
5. Keep each subdomain move behind a green run of the reporting test suite plus
   `schema_registry` and `module_size_audit` tests.

- [x] Land scoped `fleet/`, `data_quality/`, and `daily/` safe slice.
- [x] Land `promotion/` absorption, `hourly/`, and `scorecards/` slice.
- [x] Land `casebooks/`, `market/`, and `validation/`.
- [x] Land `research/` for the clear one-shot/research diagnostics.
- [x] schema_registry paths updated atomically for moved safe-slice modules; no
      new root re-export shims.
- [x] Targeted architecture ratchet blocks the moved safe-slice modules from
      returning to the reporting root.
- [x] Resolve explicitly classified root exceptions into accurate homes:
      `candidate_lifecycle/`, `source_gates/`, `serving_gates/`,
      `location_analysis/`, `data_quality/`, and `roadmap/`.
- [x] Root guard allows only shared root helpers: `__init__.py`, `formatting.py`,
      and `overview_helpers.py`.

2026-06-24 safe-slice update: `fleet_observability*` now lives under
`weather.reporting.fleet`, the historical/data-quality audit family now lives
under `weather.reporting.data_quality`, and daily learning/ledger/flow/rollup
reports now live under `weather.reporting.daily`. Promotion, hourly, research,
`bottom_location*`, `exact_band*`, and item-224 modules were intentionally left
at the root or in their existing packages until item 224 finishes.

2026-06-25 safe-slice update: promotion corpus, gauntlet, and refresh now live
under `weather.reporting.promotion`; hourly performance and candidate reports
now live under `weather.reporting.hourly`; and snapshot/progress/proof-packet
scorecards now live under `weather.reporting.scorecards`. Registered schema
owner paths, daily-refresh/import callers, compatibility-wrapper targets, and
the import-architecture root guard were updated atomically; the obsolete root
`promotion_refresh_*` wrappers were removed instead of preserved as permanent
re-export shims. Remaining item 270 work is `validation/`, `casebooks/`,
`market/`, and `research/`.

2026-06-25 follow-up safe-slice update: casebooks now live under
`weather.reporting.casebooks`, non-validation market reporting plus trading
evidence now live under `weather.reporting.market`, and the eleven
`*_validation.py` modules now live under `weather.reporting.validation`.
Registered schema owner paths, active imports, compatibility-wrapper targets,
and the import-architecture root guard were updated atomically. Remaining item
270 work is the final `research/` bucket.

2026-06-25 research classification update: clear one-shot and item-owned
diagnostics now live under `weather.reporting.research`, including `item*`,
`austin_*`, `predawn_*`, bottom-location, exact-band, late-day, cross-hub
research audit, blocked-market repair diagnostics, forecast-profile/source-state
diagnostics, forecast double-counting, and reanalysis synoptic ablation. Shared
or cross-cutting infrastructure such as `roadmap_backlog`, `variant_registry`,
`variant_evidence_growth`, `source_family_inventory`,
`candidate_variant_replay_summary`, and `pooled_f_retrain_location_gate` was left
at the root temporarily as explicit architecture-ratchet exceptions until the
final taxonomy gave those modules accurate homes.

2026-06-25 final taxonomy update: all remaining non-helper root modules now have
accurate subdomain homes. Candidate lifecycle, source gates, serving gates,
location analysis, data-quality retention/quarantine, and roadmap maintenance
modules were moved atomically with schema owner paths, app/test imports,
compatibility-wrapper targets, and active docs. The import-architecture root
guard now enforces that `weather.reporting` root contains only `__init__.py`,
`formatting.py`, and `overview_helpers.py`.

Acceptance: `weather.reporting` root holds only shared helpers and subpackages;
every registered artifact's `schema_registry` module path resolves; the
import-architecture ratchet enforces intra-reporting boundaries and blocks new
root-level modules; and the full reporting, schema-registry, and module-size
test suites are green.

## Completion Notes

Completed in the 2026-06-25 reporting taxonomy closeout:

- `weather.reporting` root now contains only `__init__.py`, `formatting.py`, and
  `overview_helpers.py`.
- All other reporting modules live under explicit subdomain packages:
  `candidate_lifecycle/`, `casebooks/`, `daily/`, `data_quality/`, `fleet/`,
  `hourly/`, `location_analysis/`, `market/`, `promotion/`, `research/`,
  `roadmap/`, `scorecards/`, `serving_gates/`, `source_gates/`, and
  `validation/`.
- Schema registry owners, imports, compatibility-wrapper targets, app/test
  callers, and active docs were retargeted atomically; no root re-export shims
  were added.
- The import-architecture ratchet enforces helpers-only reporting root
  membership and prevents moved safe-slice modules from returning to root.
- Future validation should rerun
  `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`,
  `python -m weather.schema_registry audit --paths src --strict`,
  `python -m pytest tests/operations/test_import_architecture.py`, and focused
  reporting tests.

Related: items 90, 98, 130, 173, 204, 206, 254, 262; project-structure-action-plan-2026-06-22.
