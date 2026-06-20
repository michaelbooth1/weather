# Data Retention Policy

Use the data-retention inventory before pruning local `data/` files. The
report is read-only and exists to classify ownership, TTL policy, restore
requirements, and disk-growth pressure.

## Daily Report

Run directly:

```powershell
python -m weather.reporting.data_retention_inventory --root data --out data\backtest\data_retention_inventory.json --report data\backtest\data_retention_inventory_report.md
```

The normal daily refresh also writes the same artifacts:

- `data/backtest/data_retention_inventory.json`
- `data/backtest/data_retention_inventory_report.md`

## Pruning Rules

- Do not delete `snapshots`, `mm_runs`, `taker_runs`, or canonical historical
  source rows unless the inventory restore gate is `PASS` and a reviewed
  cleanup manifest names the exact files.
- Use `python -m weather.operations.tape_backup status --verify-checksums`
  and a restore drill as deletion proof for irreplaceable classes.
- Use `python -m weather.reporting.backtest_artifact_retention` for large
  rebuildable `data/backtest` row exports; delete only from its cleanup
  manifest when paired reports or manifests exist.
- Use `python -m weather.operations.tape_backup prune-unmanifested` only for
  failed same-disk backup partials under `data/tape_backups/latest`.
- Prefer gzip tiering or externalization for large historical JSONL/CSV
  evidence before deleting local copies.

Routine provider caches may be pruned after TTL expiry when no replay,
promotion, or incident report references them. Forecast archives used for
settled replay evidence are not routine cache.
