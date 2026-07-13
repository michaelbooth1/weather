# Data Retention Policy

Use the data-retention inventory before pruning local `data/` files. The
report is read-only and exists to classify ownership, TTL policy, cleanup
requirements, and disk-growth pressure.

## Daily Report

Run directly:

```powershell
python -m weather.reporting.data_quality.data_retention_inventory --root data --out data\backtest\data_retention_inventory.json --report data\backtest\data_retention_inventory_report.md
```

The normal daily refresh also writes the same artifacts:

- `data/backtest/data_retention_inventory.json`
- `data/backtest/data_retention_inventory_report.md`

## Pruning Rules

- Classify files with the
  [Data Storage Class Contract](data-storage-class-contract.md) before cleanup:
  `canonical_evidence`, `analysis_projection`, and `operator_cache` have
  different review, rebuild-source, and deletion gates.
- Do not delete `snapshots`, `mm_runs`, `taker_runs`, or canonical historical
  source rows unless a reviewed cleanup manifest names the exact files.
- Run `python -m weather.operations.cleanup_preflight --manifest <cleanup.json>`
  before any cleanup workflow that could delete local data. A canonical
  evidence candidate requires operator review, exact paths, and current
  checksums.
- Closed market-day Parquet partitions live under
  `data/archive/closed_market_days/v0.1` and are analysis copies, not raw
  evidence replacements. Follow
  [Closed Market-Day Parquet Archive Contract](closed-market-day-parquet-archive-contract.md)
  for eligibility, manifest validation, reader fallback, and raw-evidence
  boundaries.
- Use `python -m weather.reporting.data_quality.backtest_artifact_retention` for large
  rebuildable `data/backtest` row exports; delete only from its cleanup
  manifest when paired reports or manifests exist.
- Prefer gzip tiering or externalization for large historical JSONL/CSV
  evidence before deleting local copies.

Routine provider caches may be pruned after TTL expiry when no replay,
promotion, or incident report references them. Forecast archives used for
settled replay evidence are not routine cache.

## Shared Forecast Payload CAS

New explicitly market-invariant forecast responses use the shared immutable
CAS under `data/forecast_payload_cas/`; their per-market append-only manifests
retain capture and extraction lineage. Inventory a possible legacy migration
without copying, rewriting, or deleting evidence:

```powershell
python -m weather.operations.forecast_payload_cas_migration
```

The command is dry-run only. It verifies legacy hash/restore/replay checks and
the shared references found in snapshot `forecast_payloads.jsonl` files. That
scan is explicitly partial inventory, not global reachability: blobs absent
from the scanned references are non-authoritative observations, never deletion
candidates. No current cleanup review can authorize shared-CAS deletion.
Event-day manifests enumerate referenced shared blobs as external canonical
dependencies and remain blocked until both backup and restore evidence includes
their exact digests. Legacy market-local blobs remain canonical evidence.
