# 65. Irreplaceable Tape Retention, Backup, And Restore [COMPLETE 2026-06-15 - BACKUP + RESTORE DRILL LIVE]

Goal: make one-machine loss non-fatal for the append-only evidence that cannot
be reconstructed after the fact.

Why this is missing: completed data-layer work made snapshot, CLOB, trigger,
ledger, promotion, and market-making tapes more complete and auditable, and
item 39 moved large regenerable data out of git. That leaves a separate risk:
the most valuable raw/live-forward tapes now live outside git and some of them
cannot be rebuilt from public sources once the day passes.

- [x] Classify artifacts by recoverability: irreplaceable raw/live tapes,
  rebuildable derived reports, model artifacts, manifests, and scratch output.
- [x] Define retention rules for snapshots, replay inputs, CLOB raw books,
  CLOB summaries, trade streams, observation-trigger events, settlement ledgers,
  promotion corpora, market-making run folders, order lifecycles, and risk
  events.
- [x] Add an incremental backup/export job with checksums and manifest hashes
  to a configurable external or cold-storage root, excluding clearly
  rebuildable intermediates.
- [x] Add a restore drill that rebuilds a clean temp workspace from backup,
  verifies hashes/schema versions/tape counts, and regenerates the latest
  fleet, promotion, and market-making reports from restored inputs.
- [x] Surface backup age, last successful restore drill, missing critical tape
  classes, and checksum failures in the daily refresh or fleet observability
  report.
- [x] Document the operator recovery steps for a failed workstation or corrupt
  data directory before any live-order mode is enabled.

Acceptance: a local data loss event does not destroy settlement, CLOB, trigger,
or market-making evidence needed for promotion gates, live-forward paper gates,
or post-trade audit, and a restore drill proves the current reports can be
recreated from the backup root.

Completion update 2026-06-15:

- Added `weather.operations.tape_backup` and `python -m src.tape_backup` with
  `policy`, `export`, `status`, and `restore-drill` commands.
- `export` writes an incremental `latest/` backup plus timestamped manifests
  under a configurable `WEATHER_TAPE_BACKUP_ROOT` / `--backup-root`. Each
  manifest records recoverability class, retention rule, SHA-256 checksum,
  class counts, total bytes, and a manifest hash.
- `restore-drill` restores into a clean temporary workspace, verifies manifest
  hash, file checksums, registered JSON schema versions, and critical tape
  counts, then writes restored-input reports for fleet, promotion, and
  market-making evidence.
- Fleet observability now includes a `Tape Backup And Restore` section and
  emits backup alerts for missing/stale/corrupt backups, missing critical tape
  classes, checksum failures, and failed restore drills. `daily_refresh` passes
  through `--tape-backup-root` and checksum-verification options.
- Schemas registered: `tape_backup_manifest_v0.1`,
  `tape_retention_policy_v0.1`, and `tape_restore_drill_v0.1`.
- Operator recovery steps are documented in
  `docs/operations/TAPE_BACKUP_RUNBOOK.md`.
- Verification:
  `python -m pytest tests/operations/test_tape_backup.py
  tests/reporting/test_fleet_observability.py
  tests/operations/test_daily_refresh.py
  tests/operations/test_import_architecture.py
  tests/operations/test_schema_registry.py -q` passed.
