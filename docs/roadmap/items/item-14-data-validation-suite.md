# 14. Data Validation Suite [COMPLETE - FLEET-AWARE]

- [x] Add tests for:
  WU history parsing, daily summary generation, market-bin parsing,
  snapshot append format, and model distribution normalization.
- [x] Add data validation checks for missing days, sparse days, duplicate timestamps,
  and impossible weather values.

Codex audit (2026-05-28): partial. Unit tests pass, and
`src/data_auditor.py` checks missing days, sparse days, duplicate timestamps,
and impossible values. Issues found: the tests do not cover snapshot append
format, the data auditor is not wired into the automated test suite, and the
auditor currently reports 4 missing target-window days plus 1 sparse day for
the May 28 market window.

Codex update (2026-05-31): unit coverage has expanded to 103 passing tests,
including forecast features, live observed floors, collection health, retries,
and backtest settlement behavior. This item remains partial until data audits
and snapshot append/schema checks are part of routine verification.

Codex update (2026-06-11): completed by item 31. `tests/test_data_auditor.py`
covers the auditor as a regression guard, `tests/test_fleet_observability.py`
covers fleet collection/provenance/status helpers, and the command
`src\data_auditor.py --fleet --json --strict` gives automation a unit-aware data audit.
`src.fleet_observability report --strict` combines audits, collection health,
artifact provenance, and trust readiness into a fail-closed report. The running
snapshot loop also exposes fleet collection state in `loop_status.json`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - FLEET-AWARE`.
- The file contains 2 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

