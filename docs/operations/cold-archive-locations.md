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
| `data/cold_archive/catalog/archives/<archive-id>/caches/<cache-id>.json` | Immutable record of one fully verified local cache population. |
| `data/cold_archive/catalog/archives/<archive-id>/cache.json` | Current cache pointer; earlier cache records remain. |
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

1. Plan whole-file chunks with `--chunk-grouping market_day_file_family_v1`.
   Each chunk contains one event folder and file family. CSV and gzip halves
   remain independent members; a byte bound may split a family further.
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
deadline callback. The current catalog CLI is read-only. A callback that simply
returns true is a synthetic fixture seam, not production admission.

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

Original-source reclaim is a separate, exact-file operation. It requires owner
selection authority, current protected-input checks, consumer compatibility,
independent full restore, a durable location record and fresh native source
identity/hash/allocation. Stop at the approved measured reclaim target; use a
conditional reserve only when primary exclusions or fresh allocation require it.
Neither this catalog nor the cache publisher deletes original or remote data.

## Update when

Update when catalog paths or schemas, location states, chunk grouping, proof
requirements, consumer behavior, cache bounds or cleanup authority change.
