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
