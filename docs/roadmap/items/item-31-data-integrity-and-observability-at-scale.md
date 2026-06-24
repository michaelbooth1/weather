# 31. Data Integrity And Observability At Scale [COMPLETE - FLEET REPORT LIVE]

Goal: answer "is every market complete and fresh right now?" at a glance.

- [x] Extend `collection_health` to all 12 markets plus a fleet view; per-market
  freshness SLAs.
- [x] Wire data audits (missing/sparse/duplicate/impossible) into CI and the loop
  (closes item 14).
- [x] Provenance manifests and schema versions on every artifact; drift/outlier
  alerts.

Acceptance: data problems surface as alerts before they corrupt training or
serving — the way the timezone bug should have.

Implementation result (2026-06-11): `src.collection_health` now has
`--fleet` mode over all 12 registered markets with per-market freshness SLAs,
and `src.snapshot_tracker --status` includes both the active-day collection
state and the full fleet collection state. The running loop also writes a
compact `fleet_collection` summary into `data/snapshots/loop_status.json`, so
collection gaps are visible from the operator heartbeat.

Fleet observability result: `src.fleet_observability report --strict` writes
`data/backtest/fleet_observability.json`,
`data/backtest/fleet_observability_report.md`, and
`data/backtest/artifact_provenance_manifest.json`. It combines fleet collection
health, fleet historical audits, artifact provenance/schema status, location
trust readiness, and alert severity into one CI/loop-friendly payload. The
standalone `src\data_auditor.py --fleet --json --strict` path is now
registry-aware and unit-aware, so F-market rows no longer trigger false Celsius
impossible-value alerts.

Fleet observability follow-up (2026-06-14 UTC): the report distinguishes raw WU
target-window holes from unresolved multi-source historical gaps. Current WU
missing/sparse days are covered by redundant METAR/ASOS, GHCNh, or reanalysis
daily rows, so they remain visible in the audit table without alerting as fleet
data-integrity issues. Legacy LR/HGB/late-day artifacts are also recognized from
their embedded per-hour feature schema, and future retrains stamp top-level
artifact schema metadata.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - FLEET REPORT LIVE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

