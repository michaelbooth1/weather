# 146. Tape Backup Capacity And CLOB Tiered Retention [PARTIAL 2026-06-19 - LOCAL BACKUP/RESTORE OK; EXTERNAL DURABLE ROOT PENDING]

Goal: make the tape backup SLA realistically sustainable now that CLOB order
book tapes are much larger than the local backup volume can hold.

Source: the 2026-06-18 data-layer continuation attempted
`python -m weather.operations.tape_backup run --backup-root data\tape_backups --verify-checksums`
after daily learning surfaced a P0 `operational_backup` blocker. The job failed
with `OSError: [Errno 28] No space left on device`. The repaired backup status
first reported `INSUFFICIENT_BACKUP_CAPACITY` before copying: about 534
critical files and roughly 108 GB of critical local tapes were not present in
the backup root, while the C: drive had only about 2.3 GB free after removing a
verified partial failed-copy file.

Current state: guarded cleanup plus gzip tiering of settled full-depth CLOB
books has cleared the local capacity blocker. The canonical
`data/backtest/tape_backup_status.json` is `OK`, restore-drill SLA is `OK`,
and fleet observability now reports tape backup as `OK`. The item remains
partial because the configured backup root is still a same-workstation local
path; full completion still requires a durable external/NAS/cloud root with
documented growth headroom.

Why this matters: item 111 made backup status enforceable. Local capacity is no
longer the active blocker, but the project still cannot claim workstation-loss
durability while the latest backup root lives on the same local disk as the
source tapes.

## Design

1. Move the critical tape backup root to storage with enough capacity for the
   current tape set plus growth headroom.
2. Split CLOB artifacts into retention tiers: raw order-book JSONL,
   order-book long tables, summaries, price history, websocket events, token
   maps, and derived features.
3. Decide which CLOB artifacts are irreplaceable versus rebuildable from raw
   payloads, then update the backup policy so `MISSING_CRITICAL_FILES` reflects
   true irreplaceability instead of copying every large derivative forever.
4. Add a preflight capacity check before export so backup jobs fail before
   partially copying multi-GB files.
5. Keep restore-drill coverage for every retained critical tier.
6. Document the operator runbook for moving the backup root and verifying the
   new manifest.

- [ ] Provision or configure a backup root with enough free space for the
  current critical tape set and 30 days of projected growth.
- [x] Add a capacity preflight to `weather.operations.tape_backup run`.
- [x] Reclassify rebuildable CLOB derivatives or compress/tier them before
  they are required in the critical backup manifest.
- [x] Rerun the backup job and restore drill successfully.
- [x] Refresh fleet observability and daily learning so tape backup no longer
  contributes a P0 blocker.
- [x] Add tests for insufficient backup capacity.
- [x] Add tests for the final CLOB tier policy.

Acceptance: `data/backtest/tape_backup_status.json` reports `OK`,
`fleet_observability` no longer reports tape backup as critical, restore-drill
evidence is current against the latest manifest, and the backup job refuses to
start when free space cannot cover the planned critical export.

## 2026-06-18 implementation progress

`weather.operations.tape_backup` now performs a disk-capacity preflight before
export. If the planned copy set plus the configured margin cannot fit, the run
raises a structured `INSUFFICIENT_BACKUP_CAPACITY` status, writes the normal
status JSON/report, skips the restore drill, and does not partially copy large
files. `backup_status` also reports the same explicit capacity state when local
critical tapes are missing and the current backup root cannot hold them.

Refreshed evidence:

- `data/backtest/tape_backup_status.json`: `INSUFFICIENT_BACKUP_CAPACITY`;
  free `2236768256` bytes, required `109096769828` bytes, insufficient
  `106860001572` bytes.
- `data/backtest/fleet_observability.json`: still `CRITICAL`, with tape backup
  reported as `INSUFFICIENT_BACKUP_CAPACITY`.
- `data/backtest/daily_learning.json`: still `BLOCKED`; tape backup remains a
  P0 operational blocker until storage/tiering is fixed.

Verification:
`python -m pytest tests/operations/test_tape_backup.py tests/reporting/test_fleet_observability.py tests/reporting/test_daily_learning.py tests/reporting/test_source_family_inventory.py tests/reporting/test_snapshot_evaluation.py -q`
passes with `51 passed, 9 subtests passed`.

## 2026-06-19 tiering progress

Gzip-tiered full-depth order-book tapes are now first-class retained CLOB
evidence. `data_layer_audit`, `clob_coverage_audit`, source-family inventory,
market-making live-pilot preflight, and `tape_backup` all recognize
`order_books_long.csv.gz` alongside the uncompressed `order_books_long.csv`.
This prevents a verified compacted full-depth book from showing up as missing
raw CLOB evidence after local tiering.

Added `weather.operations.clob_order_book_tiering` with a dry-run planner and
guarded apply path. Apply mode requires free space for the source file plus a
1 GiB reserve, writes a deterministic gzip temp file, verifies decompressed
SHA-256 and line count against the source, and deletes the uncompressed source
only when `--delete-source` is passed after verification.

Initial tiering evidence:

- `data/backtest/clob_order_book_tiering_plan.json`: `WARN`; 84 folders have
  uncompressed full-depth book tapes, 72 settled files are tiering candidates,
  12 are active/unsettled, and zero gzip-tiered books exist. Candidate bytes
  are `86432963124` (`82428.9` MiB). The largest candidate is Atlanta
  2026-06-16 at `2212.8` MiB. All top candidates have both
  `order_books_summary.csv` and `order_books.jsonl` present.
- `data/backtest/clob_order_book_tiering_apply_preflight.json`: `BLOCKED`;
  one-file apply preflight skipped without writing or deleting data because the
  smallest candidate needed `1345969633` free bytes including reserve and only
  `144015360` bytes were free.

Remaining unblock: free or attach enough local scratch space to run
`python -m weather.operations.clob_order_book_tiering apply --settled-before
2026-06-19 --delete-source`, then rerun `weather.operations.tape_backup run`
against a backup root that can hold the retained critical tape set.

Verification:
`python -m pytest tests/operations/test_clob_order_book_tiering.py tests/operations/test_tape_backup.py tests/reporting/test_clob_coverage_audit.py tests/reporting/test_data_layer_audit.py tests/market/test_market_making_run.py -q`
passes with `63 passed, 10 subtests passed`.

## 2026-06-19 cleanup and partial tiering update

The local backup root contained unmanifested partial-copy files from a failed
same-disk backup attempt. `weather.operations.tape_backup prune-unmanifested`
now writes a manifest-backed cleanup plan and only deletes files under
`data/tape_backups/latest` that are not in `tape_backup_manifest.json` and have
a source counterpart. Applying
`data/backtest/tape_backup_unmanifested_cleanup_applied.json` deleted 67
unmanifested backup duplicates totaling `17264418975` bytes, with zero skipped
or missing-source rows. This restored local scratch headroom without deleting
source tapes.

With scratch headroom restored, the first guarded CLOB tiering batch completed:
`data/backtest/clob_order_book_tiering_apply_batch1.json` compressed 10 settled
Atlanta/Austin `order_books_long.csv` files, verified decompressed SHA-256 and
line count, and deleted the uncompressed sources only after writing
`order_books_long.csv.gz`. The batch compacted `11777842191` source bytes into
`499422307` gzip bytes. The follow-up plan
`data/backtest/clob_order_book_tiering_plan_after_batch1.json` reports 10
already-tiered files, 62 remaining settled candidates totaling `74655121015`
bytes, and 12 active/unsettled files.

Remaining unblock at this point was to continue guarded settled-book tiering or
move the backup root to larger storage, then rerun
`weather.operations.tape_backup run` and the restore drill. The next update
records the local restore pass after all settled full-depth books were tiered.

Verification:
`python -m pytest tests\operations\test_tape_backup.py -q` passed with
`14 passed, 10 subtests passed`.

## 2026-06-19 settled-tiering and restore-pass update

All settled full-depth CLOB books are now gzip-tiered or already tiered. The
post-tiering plan
`data/backtest/clob_order_book_tiering_plan_after_all_settled.json` is `PASS`:
`72` `order_books_long.csv.gz` files are retained, `0` settled uncompressed
full-depth books remain, and the only uncompressed full-depth books are the
`12` active/unsettled June 19 files.

`weather.operations.tape_backup` now skips zero-byte files during candidate
discovery, because empty files cannot serve as recoverable evidence, and the
promotion-refresh lifecycle manifest schema
`promotion_refresh_incomplete_v0.1` is registered so started/complete/failed
promotion-refresh lifecycle records remain restorable.

Refreshed backup evidence:

- `data/backtest/tape_backup_status.json`: `OK`; manifest hash
  `93f8432a16d52ae39e32d23cb0f734eae3488ef113eac5687d5a142cc425702c`,
  `3357` files, `48957791167` manifest bytes, zero missing critical files,
  zero checksum failures, restore-drill SLA `OK`.
- `data/backtest/tape_restore_drill_after_restore_policy_fix.json`: `PASS`;
  restored `3357` files, schema failures `0`, and restored all `6` required
  CLOB artifact classes.
- `data/backtest/fleet_observability.json`: still `CRITICAL`, but tape backup
  is `OK` with restore SLA `OK` and `0` missing critical files. The remaining
  criticals are collection and settled-day freshness, not tape capacity.
- `data/backtest/daily_learning.json`: still `BLOCKED`, but the first P0 gate
  is settled-day freshness, not operational backup.

Verification:
`python -m pytest tests\operations\test_tape_backup.py tests\operations\test_schema_registry.py -q`
passed with `18 passed, 10 subtests passed`.
