# 98. Remaining Large Module Decomposition [COMPLETE 2026-06-16 - MM EXCHANGE REPORT OWNER SPLIT]

Goal: continue reducing high-risk large modules by splitting the remaining
1,000+ line files along stable responsibility boundaries.

Source: 2026-06-16 architecture review. Previous decomposition work split some
market-making and pooled-candidate responsibilities, but many active modules
remain very large: pooled feature training, feature-model training, data-layer
audit, observation trigger, exchange/paper scoring, model features/sources,
source redundancy, promotion refresh, and snapshot storage.

Why this is missing: the project has been moving fast around live operations,
research, and promotion gates. Tests cover behavior, but file size still makes
reviews slower and increases the chance that unrelated behavior changes ship
together.

- [x] Prioritize one target module at a time based on current change frequency,
  production risk, and clarity of boundaries.
- [x] Split `weather.market.mm_exchange` by moving pilot-report payloads,
  probe-status summaries, financial reconciliation summaries, and Markdown
  rendering into `weather.market.mm_exchange_reports`.
- [x] Keep `weather.market.mm_exchange` as the adapter/orchestration facade and
  preserve public helper imports, generated artifact names, schema version, and
  CLI behavior.
- [x] Add ownership/import guards so the extracted report module cannot import
  the orchestration facade.
- [x] Add focused tests for the extracted report owner and facade re-exports.

Acceptance: the most active large modules are reduced to focused orchestration
facades plus smaller owner modules, documented commands remain stable, artifact
schemas remain compatible, and focused tests cover each extracted boundary.

## Design

Use behavior-preserving extraction, not broad redesign.

- Capture public functions, generated files, CLI flags, and tests before each
  split.
- Keep existing module names as facades where callers or CLIs depend on them.
- Move pure helpers and side-effect-free transforms first.
- Move artifact IO and report rendering next.
- Leave orchestration and argparse in the facade until the extracted modules
  are stable.

Verification strategy:

- Focused test slice for the module being split.
- Import architecture guard for the new ownership boundary.
- Full suite after each high-risk extraction.

## Implementation

- `weather.market.mm_exchange_reports` now owns side-effect-free report
  transforms for exchange reconciliation, MM-2 probe status, pilot-report
  payloads, and financial reconciliation summaries.
- `weather.market.mm_exchange` remains the live adapter boundary and CLI facade.
  It imports and re-exports the report helpers so existing callers continue to
  work.
- `tests/operations/test_import_architecture.py` now scans the extracted module,
  rejects legacy bare `mm_exchange` imports, and forbids
  `mm_exchange_reports -> mm_exchange` dependencies.
- `tests/market/test_mm_exchange_reports.py` covers the report owner directly
  and verifies facade compatibility.

Follow-up candidates intentionally left as future prioritized slices:

- Split `weather.calibration.feature_model` into dataset construction,
  feature-value reporting, training/evaluation, late-day continuation training,
  artifact writing, and CLI modules.
- Split `weather.calibration.pooled_feature_model` into candidate dataset
  assembly, scoring/evaluation, training, artifact IO, reports, and CLI
  orchestration.
- Split `weather.reporting.data_layer_audit` into data loading, gate
  evaluation, recommendation generation, report rendering, and CLI glue.
- Split provider-specific fetch and parsing code out of
  `weather.model.model_sources` behind the existing source-adapter boundary.
- Split `weather.model.model_features` into artifact loading, live feature
  extraction, historical feature construction, analog search, transition
  features, and replay diagnostics.

## Verification

- `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_import_architecture.py -q`
  - 21 passed.
- `.\venv\Scripts\python.exe -m pytest -q`
  - 822 passed, 491 subtests passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - MM EXCHANGE REPORT OWNER SPLIT`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

