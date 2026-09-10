# Cold archive locations and restore cache

Original snapshot paths remain the identities of historical inputs. Archiving
changes their storage location; it must not remove them from discovery or turn
an unavailable tape into an empty research population. The implementation lives
in `weather.cold_archive_locations` and `weather.operations.cold_archive_catalog`.

## Where to find data

| Local path | Purpose |
| --- | --- |
| `data/cold_archive/WHERE_DATA_IS.md` | Human-readable inventory refreshed by catalog-enabled uploads and explicit inventory publication; consult the catalog for later changes. |
| `data/cold_archive/catalog/inventories/<snapshot-id>.md` | Immutable historical inventory snapshots retained when the human-readable pointer changes. |
| `data/cold_archive/catalog/archives/<archive-id>/upload.json` | Immutable original members, hashes, exact private Drive folder/object IDs, and exact upstream proof bytes. |
| `data/snapshots/<event>/.cold_archive/<filename>.json` | Small location marker binding the original path and hash to one catalog entry. It is metadata, not a replacement data file. |
| `data/cold_archive/catalog/archives/<archive-id>/restores/<receipt-sha256>.json` | Independent download and complete materialized restore proof, retained after cache removal. |
| `data/cold_archive/catalog/archives/<archive-id>/custody/<record-sha256>.json` | Verified workstation metadata copies and the owner's external recovery-key custody confirmation. No keys are stored here. |
| `data/cold_archive/catalog/archives/<archive-id>/caches/<cache-id>.json` | Immutable record of one fully verified local cache population. |
| `data/cold_archive/catalog/archives/<archive-id>/cache.json` | Current cache pointer; earlier cache records remain. |
| `data/cold_archive/catalog/reclaims/<approval-sha256>/<attempt-id>/` | Immutable original-reclaim intent, canonical cleanup preflight, per-file completion and final receipt. |
| `data/cold_archive/catalog/reclaims/<approval-sha256>/progress.json` | Campaign pointer; immutable earlier revisions remain under `progress/`. |
| `data/cold_archive/restore_cache/<cache-id>/members/<original-relative-path>` | Temporary restored files for an admitted historical job. |

`data/` is ignored runtime state. These paths need not exist in a clean checkout.
Keep the small catalog, location markers and restore receipts when reclaiming
payload space. Keep a verified copy of the catalog with the workstation handback.
Encryption keys and encrypted client configuration need separate durable custody;
no key, token or decrypted configuration belongs in the catalog or Git.

Use the project interpreter from the exact reviewed checkout:

```powershell
.\venv\Scripts\python.exe -m weather.operations.cold_archive_catalog locate --source-path <absolute-original-file-path>
.\venv\Scripts\python.exe -m weather.operations.cold_archive_catalog inventory --source-root <absolute-data-root>
```

`locate` reports the original hash/size, catalog entry hash, exact cloud objects,
and whether the original, a verified cache copy, or an off-site restore is needed.
Cloud objects are private Drive files: `<archive-id>.rclone.bin`, `.manifest.json`,
`.stage.json` and `.crypt.json`. Their stable object IDs, rather than a folder
name alone, bind recovery. The manifest sidecar lists every original member.
`inventory` prints Markdown from local metadata only; a cached file is not
claimed verified without a content check. Call `write_inventory` after a batch or reclaim operation. It retains an immutable
Markdown snapshot, updates `WHERE_DATA_IS.md` atomically and returns both paths
and their SHA-256. Do not imply that a
historical Markdown snapshot is a fresh presence check.

## Publication and recovery

1. Plan whole-file chunks with `--chunk-grouping market_day_file_family_v1`
   for individual-family retrieval or `market_day_v1` for bulk recovery.
   Both keep one event folder per archive; the latter combines selected families
   within it. CSV and gzip halves remain independent members, and both policies
   retain the same 1 GiB and 256-member bounds.
2. Stage, encrypt and upload through the existing admitted paths in
   [Production cold-archive staging](production-cold-archive-staging.md).
   An upload receipt commits all four cloud object identities. Publish its
   catalog entry and source markers while the original native identities still
   match. Publication validates the exact staging, encryption and upload proofs;
   every record keeps `cleanup_eligible=false`. Set `publish_catalog=true` in an
   `upload_only` request to publish the catalog, markers and persistent inventory
   within that upload job's existing lease, deadline and capture checks. The flag
   is rejected on other transfer phases. Legacy requests can omit it.
3. Independently download the committed objects and restore the complete archive
   on the admitted workstation. Restore verifies the ciphertext, every member,
   its exact path/size/hash, and the materialized bytes. Retain the bound
   transport and restore receipts in the catalog. `RESTORE_VERIFIED` records
   recovery evidence, not fresh source identity or permission to delete.
4. For later research, resolve the complete explicit input list first. Download
   only the required archives into fresh attempts and repeat full verification.
   Download does not require the original local ciphertext. Restore does not
   require the original plaintext archive or ciphertext tree; if supplied,
   their additional identity comparisons still apply.
5. Copy verified materialized members into a fresh managed cache attempt.
   Rehash during copy and readback, then publish the pointer. The cache has an
   explicit total byte limit and free-space reserve; quota refusal preserves
   sources and any partial attempt. Existing cached files may satisfy a later
   job only after their metadata and content match the original member proof.

`repair_locations` completes interrupted marker publication from an exact catalog
entry/hash while all original native identities still match. Existing markers must
bind that same entry; repair cannot replace another archive location. A failed
upload/catalog attempt remains spent. Repair completes its metadata and does not
repeat cloud creation.

`export_recovery_proofs` reconstructs the original manifest, stage, encryption
and upload receipt files byte-for-byte from their retained catalog proof bytes.
It requires a new output directory and returns their original hashes plus exact
cloud object IDs. This recovers the inputs needed for a fresh independent
download when the old working proof copies are no longer present. Exporting
metadata alone does not prove remote availability or restore payloads.

`import_locations` installs an exact catalog entry and its logical markers into
an explicitly selected recovery data root, including on another host. It requires
all corresponding original paths there to be absent; it cannot cover existing
unverified files. The immutable entry retains the original production root and
hash. Cache publication derives its destination from the local catalog layout,
so recovery does not recreate the production machine's absolute path. Existing
host and mirror boundaries still apply to the selected recovery root.

Catalog publication and cache population are orchestration APIs. Their caller
must own the correct host workload lease and provide its live admission and
deadline callback. The catalog CLI is read-only. The workstation publication
route below supplies admitted metadata publication. A callback that simply
returns true is a synthetic fixture seam, not production admission.

### Workstation recovery handback

Run the existing workstation wrapper with `-Kind weather_heavy` and Python
module `weather.operations.workstation_cold_archive_restore`, selecting
`--publish-recovery`. This metadata operation requires the wrapper environment,
the assigned non-capture Windows installation and attending principal, a pinned
assignment and a 60-second deadline. It performs no download, decryption or
original deletion.

Bind each input with its absolute path and raw SHA-256: `--entry-path` /
`--entry-sha256`, `--transport-receipt` / `--transport-receipt-sha256`,
`--restore-receipt` / `--restore-receipt-sha256`, and `--key-custody` /
`--key-custody-sha256`. Supply a fresh `--attempt-id` and an existing
`--recovery-data-root` at the reviewed workstation checkout's
`scratch/production_cold_archive_recovery/<campaign>/data`. Use short campaign
and archive IDs; paths that exceed ordinary Windows limits are refused.
This dedicated layout never writes the frozen mirror.

The key-custody input is an exact JSON object with schema
`cold_archive_key_custody`, `confirmed=true`, `outside_both_pcs=true`,
`approved_by`, timezone-aware `confirmed_at_utc` and `storage_reference`.
These fields record the owner's actual confirmation that the archive recovery
keys and required client configuration are stored outside both PCs. Store a
location reference, never a password, token or key. Extra fields are rejected.

The operation imports the exact entry and logical markers, validates and
publishes complete restore proof, verifies both copied metadata hashes and
writes custody plus a location inventory. Its create-only handback lives at
`scratch/production_cold_archive_recovery/<campaign>/handbacks/<attempt-id>/`.
A failure preserves the claim and all partial metadata; it is not an
automatic retry instruction. Copy the returned restore/custody records back
by their exact hashes. Original reclaim retains both in the production catalog
before any source removal; the workstation copies remain independent.


## Readers, housekeeping and cleanup

`resolve_local_path` returns an original file or a verified cache member.
`registered_sources` preserves logical discovery through markers;
`require_local_inputs` resolves a complete explicit dependency list before work.
`ArchivedInputRequired` and `CatalogIntegrityError` inherit from `RuntimeError`,
so ordinary missing-file handling cannot silently consume archived history.
Consumers with their own existence checks, globs, provenance hashing or direct
file opens require their own archive-aware integration. Shared JSON/JSONL/CSV readers, full-book readers, raw prediction consumers and
explanation diagnostics use this boundary. Full-book readers may use retained
canonical gzip when the raw JSONL is archived; they cannot quietly substitute
a partial CSV for known archived canonical books. A passing catalog test alone
does not establish that a new consumer is ready.

A job using cache files must hold the repository's host workload lease through
its final read. Cache cleanup must acquire that same lease, preserve all catalog
and restore receipts, and refuse in-use or changed files. Valid complete Parquet
projections and their original source identities must survive raw offload;
housekeeping must not replace them with a partial population or repeatedly try
to repair deliberately archived raw files. Closed-day Parquet maintenance reports
`preserve_archived_sources`; event-manifest backfill reports
`preserve_original_manifest` / `SKIPPED_ARCHIVED`. Neither reports a fresh content
validation. A strict event-manifest audit remains BLOCK until required archived
inputs are restored and verified. Explicit manifest building through a verified
cache preserves original timestamps and logical provenance. Data-layer and CLOB
audits expose archived locations and restore actions while local training
eligibility continues to require local inputs.

Managed cache cleanup uses
`weather.operations.cold_archive_cache_cleanup.clear_cache` with an exact entry
hash, published cache hash and fresh attempt ID. The caller holds the same
host lease as cache readers. Cleanup takes exclusive native NTFS handles for
every member, verifies identity and full content before any deletion, and
removes through those same handles. In-use, missing, changed, hardlinked or
redirected members refuse the complete batch before its first removal.
Claims, catalog pointers, prior cache records, restore proofs and directories
remain; an absent cache member correctly requires restore again.
Immutable intent, per-file completion and final receipts live under
`catalog/archives/<archive-id>/cache_cleanup/<attempt-id>/`.
An interrupted cleanup requires explicit reconciliation from those records;
a missing final receipt is never a successful batch or automatic retry authority.

Original-source reclaim is a separate, exact-file operation. It requires owner
selection authority, current protected-input checks, consumer compatibility,
independent full restore, a durable location record and fresh native source
identity/hash/allocation. Stop at the approved measured reclaim target; use a
conditional reserve only when primary exclusions or fresh allocation require it.
Neither this catalog nor the cache publisher deletes original or remote data.

## Original-source reclaim

The separate `weather.operations.cold_archive_reclaim` API removes approved
primary sources only after the full recovery chain passes. Its production
entrypoint is `production_cold_archive_run.ps1 -Operation reclaim`, with the
same mandatory wrapper arguments as staging and a new output attempt under
`scratch/production_cold_archive_reclaim`. The unchanged capture-host window,
tiering exclusion, shared lease, memory ceiling, BelowNormal child and
300-second whole-tree deadline apply. The exact plan selects the disk reserve;
a new target does not inherit an earlier plan's exception.

The request uses `production_cold_archive_reclaim_request`, operation
`reclaim`, the common production root, host, source tip, named approval and
expiry fields, and a unique `attempt_id`. Each of `catalog_entry`,
`owner_approval`, `proposal`, `selection`, `plan`, `source_review`,
`restore_record` and `custody_record` is exactly an absolute `path` and
raw `sha256`. Optional `spool_inventory` has the same path/hash form. The executor recomputes the complete selective plan and binds
the archive's original members to the approved proposal. Conditional-reserve
execution remains refused until a qualified complete primary-disposition proof
is supplied by a separately implemented lane.

The source review covers this exact archive and expires within five minutes.
It requires a closed market day, final settled/countability disposition, and
clear barriers, queues, point-in-time windows and protected release/replay
inputs, each supported by bounded hash-bound evidence. An operator must
actually review those controls; synthetic PASS flags are not production proof.
A catalog-bound independent complete restore must have finished within
24 hours. Custody evidence binds verified workstation copies of the catalog
entry and restore record and the owner's confirmation that recovery keys are
stored outside both PCs. Store only the custody location and confirmation,
never the keys or password.

Before removal, reviewed archive-aware consumers must be present in production
and all three capture identities must match current source. Every selected
original is exclusively pinned and checked for exact native identity,
allocation and full content SHA-256 before any removal starts. The canonical
cleanup preflight runs over those same-handle hashes. Intent and campaign
`IN_PROGRESS` precede native handle-based deletion. Each completed file gets
its own receipt; the updated location inventory and final receipt must exist
before the campaign returns to `READY`.

Counters track verified original NTFS allocation, not a promised net volume
free-space increase. Reclaim stops at the approved target at a whole-file
boundary. Failures preserve all evidence and block automatic continuation;
a killed or malformed child reports unknown deletion counts. Reconcile its
exact intent, native paths and completion records before authorizing another
attempt. Catalog entries, markers, recovery receipts, cloud objects and
staging/transfer evidence remain retained.

### Temporary payload lifecycle

For a reclaim batch that also releases its temporary payload space, include a
sealed `cold_archive_spool_inventory` bound to the same archive ID and entry
SHA-256. Its three ordered rows are `staged_archive`, `upload_ciphertext` and
`downloaded_ciphertext`. Each row records its repository-relative path, full
SHA-256, size, modification time, native device/file ID and allocated bytes.

Only these exact payload paths can be selected:

- `scratch/production_cold_archive/<stage-attempt>/stage/archive.tar.gz`, bound
  to the original stage receipt and manifest;
- `scratch/production_cold_archive_ingress/<archive-id>/archive.rclone.bin`,
  bound to the committed ciphertext identity;
- `scratch/production_cold_archive_transfer/<download-attempt>/transfer/downloaded-<archive-id>.rclone.bin`,
  bound to the independently verified download receipt.

The executor pins and fully hashes every source and temporary payload before
any deletion. After approval, complete restore, custody and consumer checks,
it journals campaign intent, removes those temporary copies, then reclaims
originals. `spool-intent.json`, `spool-file-*.json` and `spool-receipt.json` sit
beside the original-reclaim receipts. A failure keeps the campaign in
`IN_PROGRESS` for reconciliation. Directories, encrypted configuration,
metadata sidecars, catalog entries, cloud objects and workstation copies stay
retained. Temporary bytes are reported separately and never added to the
approved original-data target. Check the actual volume free space to establish
the net result before proceeding to another batch.

## Update when

Update when catalog paths or schemas, location states, chunk grouping, proof
requirements, consumer behavior, cache bounds or cleanup authority change.
