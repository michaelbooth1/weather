# 247. Tape Backup Mirror Demotion And Guarded Reclaim [COMPLETE 2026-06-25 - DURABLE PROOF-BACKED MIRROR RECLAIM APPLIED]

Goal: safely demote `data/tape_backups/latest` from long-term archive to
short-term local restore cache, then reclaim only unmanifested duplicate mirror
files after manifest and restore evidence pass.

Source: the 2026-06-22 storage audit found about 21.9 GB in 29 files under
`data/tape_backups/latest` that are not referenced by the latest manifest.
Most sampled files are old order-book CSV mirror copies whose source
counterparts still exist. The repo already has
`python -m weather.operations.tape_backup prune-unmanifested`, but the current
operator policy does not require a full dry-run, report inspection, restore
drill, and apply gate before reclaiming local mirror bytes.

Why this matters: the safest way to regain local headroom is to remove
verified duplicate backup mirror files, not source data. But reclaim must be
fail-closed: no source tape, raw JSONL, Parquet partition, or manifest should
be deleted because a mirror cleanup looked plausible.

## Design

1. Treat `data/tape_backups/latest` as a local cache for recent restore
   convenience, not as the durable archive of record once Item 246 is live.
2. Require `prune-unmanifested` dry-run output before any local mirror cleanup,
   with candidate rows showing latest manifest hash, source counterpart, file
   size, and reason.
3. Require latest manifest validation and a current restore drill before apply
   mode can delete any unmanifested mirror file.
4. Restrict apply mode to files under `data/tape_backups/latest` that are not
   in the latest manifest and whose source counterpart still exists or whose
   durable deduplicated repository restore is verified.
5. Write an applied cleanup manifest with deleted paths, bytes, manifest hash,
   restore-drill evidence, skipped rows, and post-cleanup backup status.
6. Add a local mirror retention setting for how much recent cache, if any, is
   worth keeping after the deduplicated repository is operational.

- [x] Run and review `python -m weather.operations.tape_backup
  prune-unmanifested` in dry-run mode against the current mirror.
- [x] Add or tighten tests that apply mode refuses to delete without manifest
  validation and restore-drill evidence.
- [x] Add an operator gate that blocks cleanup when candidate files lack a
  source counterpart or verified durable-repository restore.
- [x] Apply cleanup only to verified unmanifested mirror duplicates.
- [x] Refresh backup status, fleet observability, and local storage inventory
  after cleanup.
- [x] Document the new role of `data/tape_backups/latest` as cache, not
  archive.

Acceptance: unmanifested duplicate files in `data/tape_backups/latest` can be
reclaimed through a dry-run, restore-verified, manifest-backed apply workflow;
no source snapshot data is deleted; post-cleanup backup status remains healthy;
and the runbook makes clear that durable retention belongs to the
deduplicated repository, not the local mirror.

Implementation note (2026-06-24): `weather.operations.tape_backup
prune-unmanifested` now emits a dry-run plan with manifest validity,
restore-drill SLA, source/mirror SHA-256 comparison, plan hash, apply gates,
and local mirror cache-retention metadata. Apply mode is fail-closed: it
requires `--reviewed-plan`, explicit operator approval metadata, a valid latest
manifest matching the reviewed plan, current restore-drill evidence, backup
status `OK`, no blocked dry-run rows, and a second source/mirror hash
revalidation before unlinking any file. The applied manifest records deleted
paths, skipped rows, operator review, restore evidence, manifest hash, and
post-cleanup backup status.

Dry-run review (2026-06-24): the current mirror produced
`data/backtest/tape_backup_unmanifested_cleanup.json` and report with
`status=WARN`, `apply_permission=false`, 28 unmanifested files totaling
23,518,335,013 bytes, 4 byte-identical tiny source-backed candidates, and 24
blocked missing-source rows. Apply is blocked because the latest manifest hash
does not validate and the blocked rows have no source counterpart. No cleanup
was applied.

Current review (2026-06-24 13:25 UTC): reran
`python -m weather.operations.tape_backup prune-unmanifested` against the
current local mirror. The latest local manifest now validates, the restore drill
SLA is `OK`, and the dry-run plan hash is
`c886ced92e42d6bc8a00d6af0609569c1d107e75fa3990fb267fc0270e0b6f0a`, but
`apply_permission=false` remains correct. The plan still has 28 unmanifested
rows: 4 byte-identical zero-byte operator-cache candidates and 24 blocked
missing-source `order_books_long.csv` mirror rows totaling 23,518,335,013
bytes. Because all meaningful reclaim bytes are missing source-counterpart
evidence, item 247 cannot be safely finished yet without either source evidence
or a per-row durable-repository restore proof for those 24 blocked mirror files.

## Completion Notes

2026-06-25: added and used the durable proof lane for missing-source
unmanifested mirror rows. `python -m weather.operations.tape_backup
prove-unmanifested --plan data\backtest\tape_backup_unmanifested_cleanup.json`
created `data/backtest/tape_backup_unmanifested_durable_restore_proof.json`
with `status=PASS`, Restic snapshot
`a88af2fe884396a6e6eeb862d3a4526bb4116f95a68792a4e6c9cfb4298a9680`, proof
hash `81c431cd798bfaa24f2a7f0a3a41567bf8fcf5208dada1e8226d49b4bbab2692`, and
24/24 restored missing-source mirror rows verified byte-identical
(`23,518,335,013` bytes). The proof-backed dry-run then reported
`apply_permission=true`, 28 candidates, zero blocked rows, and plan hash
`8b25e098ca49fd2516c233d5714930a95ac23ed22bf66d7fbabd7a91b5f3df93`.

Guarded apply was run with the reviewed plan and operator note:
`python -m weather.operations.tape_backup prune-unmanifested --apply
--reviewed-plan data\backtest\tape_backup_unmanifested_cleanup.json
--operator-approve --operator-approved-by codex --operator-note "...durable
restore proof verified..."`. Apply passed and deleted only unmanifested files
under `data/tape_backups/latest`: 28 files, `23,518,335,013` bytes. A final
dry-run now reports `status=PASS`, zero unmanifested files, zero candidates,
and zero blocked rows. Refreshed backup status is `OK`, restore-drill SLA is
`OK`, fleet observability reports tape backup status `OK` even though unrelated
fleet alerts keep the overall fleet report `CRITICAL`, and the data retention
inventory reports `PASS`.

Related: items 65, 111, 124, 146, 154, 239, 246.
