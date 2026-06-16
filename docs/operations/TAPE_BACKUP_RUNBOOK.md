# Irreplaceable Tape Backup And Restore Runbook

This runbook covers evidence that cannot be reconstructed after a workstation
loss: snapshot tapes, replay inputs, CLOB captures, observation-trigger events,
settlement labels, promotion corpora, market-making run folders, order
lifecycle ledgers, and risk events.

## Backup Root

Use an external disk, NAS, or cloud-synced cold-storage folder. Configure it
with `WEATHER_TAPE_BACKUP_ROOT` or pass `--backup-root` explicitly.

Recommended layout:

```powershell
$env:WEATHER_TAPE_BACKUP_ROOT = "E:\weather-tape-backups"
python -m src.tape_backup export --backup-root $env:WEATHER_TAPE_BACKUP_ROOT
python -m src.tape_backup restore-drill --backup-root $env:WEATHER_TAPE_BACKUP_ROOT
python -m src.tape_backup status --backup-root $env:WEATHER_TAPE_BACKUP_ROOT --verify-checksums
```

The backup manifest is written to `latest/tape_backup_manifest.json` and to a
timestamped copy under `manifests/`. Each manifest records tape classes,
recoverability, retention rules, SHA-256 checksums, file counts, total bytes,
and a manifest hash.

## Retention Rules

- `snapshot_tapes`: retain permanently. Includes snapshot, feature, component,
  source-status, forecast-payload, and replay-input tapes.
- `clob_tapes`: retain permanently. Includes CLOB tokens, book/feature tapes,
  diagnostics, and loop status.
- `observation_trigger_tapes`: retain permanently. Includes trigger events,
  diagnostics, status, and console traces.
- `settlement_ledgers`: retain permanently. Includes settlement ledgers,
  market-day labels, and resolution provenance.
- `promotion_corpora`: retain permanently. Includes pinned promotion corpora,
  location trust, promotion decisions, and gauntlet JSON outputs.
- `market_making_runs`: retain permanently. Includes run folders, quote tapes,
  fills, budgets, and run summaries.
- `order_lifecycle_and_risk`: retain permanently. Includes order lifecycle,
  risk, budget, and remediation-event records.
- `model_artifacts_and_manifests`: retain through the corresponding promotion
  and live-forward window.
- `source_manifests` and `operational_status`: retain with the backed-up data
  to prove provenance and last known operational state.

Markdown reports, lock files, PID files, temp files, and clearly rebuildable
scratch outputs are excluded.

## Restore Drill

Run a restore drill after the first backup, after changing backup storage, and
at least once per week while live-forward tests are active.

```powershell
python -m src.tape_backup restore-drill --backup-root $env:WEATHER_TAPE_BACKUP_ROOT
```

The drill restores files to a temporary workspace, verifies manifest hash,
per-file checksums, registered JSON schema versions, critical tape-class counts,
and writes regenerated restore-input reports for fleet, promotion, and
market-making evidence.

The latest drill status is copied to
`latest/tape_restore_drill.json` under the backup root and is surfaced by
`src.fleet_observability`.

## Recovery After Workstation Loss

1. Clone the repository on a clean machine and install dependencies.
2. Attach or sync the configured backup root.
3. Run `python -m src.tape_backup status --backup-root <root> --verify-checksums`.
4. Run `python -m src.tape_backup restore-drill --backup-root <root> --restore-root <new-workspace> --keep-restore`.
5. Copy the restored `data/` and `artifacts/` trees into the active workspace,
   preserving relative paths.
6. Regenerate operational reports:

```powershell
python -m src.fleet_observability report --tape-backup-root <root>
python -m src.daily_refresh run --continue-on-error --tape-backup-root <root>
```

7. Do not enable live-order mode until fleet observability shows backup status,
   restore-drill status, snapshot collection, CLOB capture, and observation
   trigger gates as healthy or explicitly accepted by a documented risk cap.
