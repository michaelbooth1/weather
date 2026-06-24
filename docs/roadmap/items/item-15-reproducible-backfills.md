# 15. Reproducible Backfills [COMPLETE]

- [x] Add commands to rebuild WU normalized data from raw payloads without
  refetching the network.
- [x] Record source endpoint, API params, generated timestamp, and code version in
  manifests.
- [x] Add a lightweight checksum or row-count audit per partition.

Codex audit (2026-05-28): passes. `src/wu_history.py` provides `backfill`,
`rebuild`, and `audit` commands; the manifest records endpoint, redacted API
params, generated timestamp, code version, row counts, and SHA-256 checksums.
The partition audit passed for 533 WU hourly partitions.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

