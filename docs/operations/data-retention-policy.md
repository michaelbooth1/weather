# Data Retention Policy

Use the data-retention inventory before pruning local `data/` files. The
report is read-only and exists to classify ownership, TTL policy, restore
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
  different backup, rebuild-source, and deletion gates.
- Do not delete `snapshots`, `mm_runs`, `taker_runs`, or canonical historical
  source rows unless the inventory restore gate is `PASS` and a reviewed
  cleanup manifest names the exact files.
- Run `python -m weather.operations.cleanup_preflight --manifest <cleanup.json>`
  before any cleanup workflow that could delete local data. A canonical
  evidence candidate is blocked when tape status is `MISSING_CRITICAL_FILES`,
  restore-drill evidence is stale, backup checksums fail, or the candidate is
  absent from the latest backup manifest.
- Closed market-day Parquet partitions live under
  `data/archive/closed_market_days/v0.1` and are analysis copies, not raw
  evidence replacements. Follow
  [Closed Market-Day Parquet Archive Contract](closed-market-day-parquet-archive-contract.md)
  for eligibility, manifest validation, reader fallback, and raw-evidence
  boundaries.
- Use `python -m weather.operations.tape_backup status --verify-checksums`
  and a restore drill as deletion proof for irreplaceable classes.
- Follow the [Tape Backup Runbook](TAPE_BACKUP_RUNBOOK.md) before treating
  backup status as deletion proof.
- Use `python -m weather.reporting.backtest_artifact_retention` for large
  rebuildable `data/backtest` row exports; delete only from its cleanup
  manifest when paired reports or manifests exist.
- Use `python -m weather.operations.tape_backup prune-unmanifested` only as a
  dry-run review for failed same-disk backup partials under
  `data/tape_backups/latest`. Apply requires the reviewed dry-run JSON,
  current manifest and restore-drill evidence, backup status `OK`,
  byte-identical source counterparts for every row, and explicit operator
  approval. Do not apply mirror cleanup while durable backup evidence is stale,
  missing, or incomplete.
- Prefer gzip tiering or externalization for large historical JSONL/CSV
  evidence before deleting local copies.

Routine provider caches may be pruned after TTL expiry when no replay,
promotion, or incident report references them. Forecast archives used for
settled replay evidence are not routine cache.
