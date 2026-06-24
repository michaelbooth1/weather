# 288. Fresh Backup/Restore Deletion Gate Before Data Cleanup [COMPLETE 2026-06-23 - CLEANUP PREFLIGHT FAILS CLOSED ON CANONICAL EVIDENCE]

Goal: require a fresh tape backup plus restore-drill proof before any cleanup
manifest can delete or demote local canonical evidence, and surface that gate
as a hard blocker when critical files are missing from the latest manifest.

Source: the 2026-06-23 storage audit ran the existing tape-backup status
tooling and found `MISSING_CRITICAL_FILES`: 154 critical files, about 1.77 GB,
were present locally but absent from the latest backup manifest. The restore
drill SLA was current, but restore proof for deletion was not sufficient
because the newest critical files were not covered. Existing data-retention docs
already say not to delete `snapshots`, `mm_runs`, `taker_runs`, or canonical
historical source rows until restore gates pass, but the deletion-preflight
gate is not yet a first-class cleanup workflow.

Why this matters: raw tapes, settlement labels, market-making lifecycle logs,
taker ledgers, CLOB books, websocket events, and price history cannot be safely
recreated after deletion. A stale or incomplete backup is worse than no cleanup
because it creates false confidence. Cleanup should be boring: every deletion
candidate must be named in a reviewed cleanup manifest, every canonical
evidence dependency must be present in a fresh backup, and a restore drill must
prove the files needed for replay and audits can be recovered.

## Design

1. Add a cleanup preflight that loads the data-retention inventory,
   tape-backup status, restore-drill status, and cleanup manifest, then blocks
   deletion when any canonical-evidence class has missing critical files,
   stale backup age, stale restore drill, or checksum failures.
2. Require cleanup manifests to name exact files, storage class, retention
   class, deletion reason, rebuild source or "not rebuildable", backup manifest
   hash, restore-drill hash, and approving operator note.
3. Integrate the gate with existing `backtest_artifact_retention`,
   `clob_order_book_tiering`, and `tape_backup prune-unmanifested` paths so
   projection/cache cleanup remains possible while canonical evidence deletion
   remains fail-closed.
4. Surface deletion-gate status in fleet observability and daily refresh so a
   stale or incomplete backup is visible before disk pressure forces emergency
   cleanup.
5. Keep Item 246 as the owner for replacing the same-disk mirror with durable
   deduplicated storage; this item owns the local deletion gate regardless of
   which backend supplies restore proof.

- [x] Add a cleanup-preflight command that joins cleanup manifests to current
  backup/restore status and returns fail-closed deletion permission.
- [x] Define a cleanup-manifest schema with exact file paths, classes, hashes,
  backup manifest hash, restore-drill evidence, and operator review metadata.
- [x] Wire data-retention and cleanup reports to mark canonical-evidence
  deletion as blocked when tape status is `MISSING_CRITICAL_FILES`.
- [x] Add focused tests for stale backup, stale restore drill, missing critical
  files, checksum failures, projection-only cleanup, and canonical evidence
  cleanup.
- [x] Document the cleanup workflow in the data-retention policy and tape
  backup runbook.

Acceptance: no supported cleanup command can delete or demote canonical
evidence unless the named files appear in a reviewed cleanup manifest, the
latest backup manifest covers all required classes, restore-drill evidence is
fresh, and checksums pass; when tape status reports missing critical files, the
deletion gate reports a hard block with the missing file samples.

Implementation (2026-06-23): `weather.operations.cleanup_preflight` now defines
`cleanup_manifest_v0.1` and `cleanup_preflight_v0.1`, writes a fail-closed CLI
preflight, and validates exact relative paths, storage class, retention class,
deletion reason, rebuild source, byte count, SHA-256, backup manifest hash,
restore-drill manifest hash, and operator review metadata. Canonical evidence
deletion requires backup status `OK`, restore-drill SLA `OK`, zero missing
critical files/bytes, no checksum failures, latest backup-manifest coverage for
the candidate hash, and matching restore-drill evidence. Projection and
operator/cache cleanup can proceed with reviewed manifests without blocking on
canonical backup gaps.

`backtest_artifact_retention` now emits the reviewed cleanup-manifest shape and
runs the shared preflight before unlinking rebuildable exports.
`clob_order_book_tiering --delete-source` now runs the shared preflight before
removing verified gzip-tiered `order_books_long.csv` projections.
`tape_backup prune-unmanifested` now marks candidates with storage-class/delete
gate metadata, keeping that workflow scoped to operator/cache backup-mirror
partials. Data-retention and fleet observability both surface the canonical
cleanup gate, including the hard `MISSING_CRITICAL_FILES` block and samples.

Documentation: `docs/operations/data-retention-policy.md` and
`docs/operations/TAPE_BACKUP_RUNBOOK.md`.

Verification (2026-06-23):

- `python -m pytest tests/operations/test_cleanup_preflight.py -q` -> 6
  passed.
- `python -m pytest tests/reporting/test_data_retention_inventory.py -q` -> 4
  passed.
- `python -m pytest tests/reporting/test_backtest_artifact_retention.py -q` ->
  8 passed.
- `python -m pytest tests/operations/test_clob_order_book_tiering.py -q` -> 4
  passed.
- `python -m pytest tests/operations/test_tape_backup.py -q` -> 15 passed, 10
  subtests passed.
- `python -m pytest tests/reporting/test_fleet_observability.py -q` -> 33
  passed.

Related: items 65, 111, 146, 154, 171, 246, 247, 286.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - CLEANUP PREFLIGHT FAILS CLOSED ON CANONICAL EVIDENCE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

