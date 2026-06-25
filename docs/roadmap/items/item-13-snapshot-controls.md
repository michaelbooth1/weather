# 13. Snapshot Controls [COMPLETE]

- [x] Add dashboard controls for:
  force snapshot, pause/resume background snapshot loop, and view last snapshot.
- [x] Show current snapshot file paths and row counts.
- [x] Add a mini changelog of the last few snapshots.

Codex audit (2026-05-28): passes for the dashboard control scope. The app has a
force-snapshot button, a pause/resume flag respected by the snapshot loop,
snapshot file paths with row counts, last-snapshot inspection, and a mini
changelog. Full PID/heartbeat/error process management remains item 16.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

