# 111. Tape Backup Manifest SLA And Restore Evidence [COMPLETE 2026-06-17 - BACKUP SLA ENFORCED]

Goal: make irreplaceable tape backup status operationally enforceable instead
of merely documented.

Source: 2026-06-16 settled-day audit. Fleet observability was `CRITICAL`
because tape backup status was `MISSING`. The missing critical classes were
snapshot tapes, CLOB tapes, observation-trigger tapes, settlement ledgers,
promotion corpora, market-making runs, and order lifecycle/risk artifacts. The
last restore drill was also missing.

Why this matters: settled-day learning depends on tapes that cannot be
reconstructed after the fact. A backup feature marked complete is not enough if
the current manifest is absent, stale, or missing critical artifact classes.

## Design

1. Add a scheduled backup job that writes a manifest with artifact classes,
   counts, byte totals, checksums, and source roots.
2. Add an SLA check to fleet observability: manifest age, critical class
   coverage, checksum failures, and last restore drill age.
3. Fail daily learning when backup status is missing or critical for
   irreplaceable artifacts, but include the exact remediation command and
   expected output path.
4. Add a small restore drill that samples each critical class and verifies the
   restored file can be parsed by its owning reader.
5. Keep backup manifest history so operators can distinguish a one-off missed
   backup from a persistent tape-retention failure.

- [x] Register the backup job on the production host.
- [x] Emit a backup manifest that covers all critical tape classes.
- [x] Add restore-drill evidence for each critical class.
- [x] Report backup SLA status in fleet observability and daily learning.
- [x] Add tests for missing manifest, stale manifest, missing critical class,
  and checksum failure cases.

Acceptance: fleet observability no longer reports backup status as healthy
unless current manifests and restore evidence exist for every critical tape
class needed to replay or audit settled days.

## Implementation Notes

- `weather.operations.tape_backup run` now performs the all-in-one export,
  restore drill, checksum verification, and status/report write used by the
  scheduled job.
- `backup_status` is fail-closed on missing, failing, stale, or manifest-hash
  mismatched restore-drill evidence, and exposes `restore_drill_sla_status` and
  `restore_drill_sla_detail`.
- `scripts/ops/register_tape_backup.ps1` registers
  `WeatherTapeBackupAndRestoreDrill` against
  `weather.operations.tape_backup run --verify-checksums`.
- Fleet observability and daily learning now surface tape-backup SLA failures;
  daily learning emits a P0 `operational_backup` blocker with the repair
  command and expected output artifacts.
- The backup manifest is recomputed from backed-up destination bytes after
  copying, so live files changing during export do not create false checksum
  failures in the resulting manifest.

## Verification

- Live backup job wrote manifest
  `8137dbf61b8c9902a7fa23559e1108099add80d17cae11082e631e6a1b333be8`
  covering `2394` files and all critical classes.
- Live restore drill status is `PASS`; backup status is `OK`; restore SLA is
  `OK`; checksum verification checked `2394` files with zero failures.
- Fleet observability tape section reports `Status | OK`, `Restore SLA | OK`,
  zero checksum failures, and no missing critical classes. Overall fleet status
  remains `CRITICAL` only because current collection loops are stale and the
  observation watcher is degraded.
- Windows scheduled task `WeatherTapeBackupAndRestoreDrill` is registered and
  ready, with next run `2026-06-18 02:15` local time.
- `python -m pytest -q tests\operations\test_tape_backup.py tests\operations\test_schema_registry.py tests\reporting\test_fleet_observability.py tests\reporting\test_daily_learning.py`
  passes with `29 passed`.
