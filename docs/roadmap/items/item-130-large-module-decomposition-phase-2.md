# 130. Large Module Decomposition Phase 2 [COMPLETE 2026-06-18 - REPORT AND EVIDENCE OWNER SPLITS LIVE]

Goal: continue reducing high-risk large modules inside the existing package
boundaries without creating new top-level folders.

Source: 2026-06-18 repository hierarchy review. The directory structure is now
mostly right, but several modules still carry multiple responsibilities. Top
pressure points include `weather.calibration.pooled_feature_model`,
`weather.calibration.feature_model`, `weather.reporting.data_layer_audit`,
`weather.reporting.disagreement_casebook`, `weather.model.model_sources`,
`weather.reporting.promotion_refresh`,
`weather.reporting.fleet_observability`, `weather.market.mm_paper`,
`weather.operations.observation_trigger`, and
`weather.market.market_microstructure`.

Why this matters: once files are in the right package, the next maintainability
risk is oversized modules. Large files blur ownership, increase merge
conflicts, and make behavior-preserving changes harder than necessary.

## Design

1. Pick one target module at a time and document its public CLI, generated
   artifacts, important functions, and current tests before moving code.
2. Split along existing responsibilities, such as data loading, artifact IO,
   scoring, report rendering, command parsing, runtime supervision, or source
   adapters.
3. Keep public module execution and compatibility imports stable while the
   implementation moves.
4. Add import-architecture guards so extracted helper modules do not import
   their orchestration facades.
5. Prefer submodules under existing owner packages over new root-level
   directories.

- [x] Rank the next five decomposition targets by line count, churn, and
  operational risk.
- [x] Split one calibration target into dataset/training/artifact/report/CLI
  responsibilities.
- [x] Split one reporting target into data assembly and rendering/report
  responsibilities.
- [x] Split one operations or market target into supervision/capture/policy
  responsibilities.
- [x] Add or extend architecture tests for extracted modules.

Acceptance: at least three high-pressure modules are split into smaller owner
modules, documented commands and artifact schemas remain stable, and the
architecture ratchet prevents newly extracted modules from re-coupling to their
old orchestration facades.

## Completion

Completed 2026-06-18.

Current decomposition pressure ranking after this pass:

| Rank | Module | Lines | 90-day commits | Risk driver |
| :--- | :--- | ---: | ---: | :--- |
| 1 | `weather.calibration.pooled_feature_model` | 2659 | 9 | Largest calibration/artifact training owner. |
| 2 | `weather.reporting.promotion_refresh` | 1430 | 10 | Promotion gate orchestration and artifact publication. |
| 3 | `weather.market.market_microstructure` | 1243 | 12 | Live capture, CLOB policy, and operational freshness. |
| 4 | `weather.reporting.disagreement_casebook` | 1548 | 5 | Large research/report surface with settled-case logic. |
| 5 | `weather.model.model_sources` | 1439 | 7 | Runtime source selection and data freshness decisions. |

Implementation:

- Extracted feature-model ablation grouping, promotion decision summaries, and
  report rendering to `weather.calibration.feature_model_reports`. The
  existing `weather.calibration.feature_model` facade still exposes the same
  imported helpers and keeps the training CLI/artifact writes in place.
- Extracted data-layer remediation manifest assembly to
  `weather.reporting.data_layer_audit_remediation`. The public
  `build_remediation_manifest(gates, snapshot, historical)` entry point remains
  on `weather.reporting.data_layer_audit`, while markdown rendering stays in
  `weather.reporting.data_layer_audit_report`.
- Extracted market-making paper run eligibility and per-market live-forward
  evidence policy to `weather.market.mm_paper_evidence`. The paper scorer keeps
  orchestration and artifact output, while `weather.market.mm_paper_reports`
  remains the rendering/known-edge report owner.
- Extended import-architecture tests so `feature_model_reports`,
  `data_layer_audit_remediation`, and `mm_paper_evidence` cannot import their
  former orchestration facades.

Verification:

- `python -m compileall -q src\weather\calibration\feature_model.py src\weather\calibration\feature_model_reports.py src\weather\reporting\data_layer_audit.py src\weather\reporting\data_layer_audit_remediation.py src\weather\market\mm_paper.py src\weather\market\mm_paper_evidence.py`
  passed.
- `python -m pytest tests\model\test_feature_model_ablation.py -q` passed.
- `python -m pytest tests\reporting\test_data_layer_audit.py::TestDataLayerAudit::test_build_remediation_manifest_classifies_low_fill_and_artifact_gaps -q`
  passed.
- `python -m pytest tests\market\test_mm_paper.py -q` passed.
- `python -m pytest tests\operations\test_import_architecture.py::test_extracted_modules_do_not_import_orchestration_facades -q`
  passed.
- `python -m pytest tests\operations\test_import_architecture.py -q` currently
  reports 14 passed and 1 clean-checkout failure because unrelated untracked
  files `src/weather/reporting/hourly_model_performance.py` and
  `tests/reporting/test_hourly_model_performance.py` are present in the
  workspace.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - REPORT AND EVIDENCE OWNER SPLITS LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

