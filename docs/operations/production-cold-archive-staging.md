# Production cold-archive staging

This lane stages exact cold snapshot files into bounded local archive objects.
It is a prerequisite for the off-site workflow in
[Verified cold archive](verified-cold-archive.md), not restore or deletion proof.

## Scope and evidence

A measured candidate selection records exact relative names, native file
identity, sizes, timestamps and allocated bytes. Planning reads this retained
metadata only. It validates accounting and creates deterministic whole-file
chunks of at most 1 GiB and 256 files. Files larger than 1 GiB are refused.
Plain CSV and compressed CSV halves are independent selected objects.
For selective historical retrieval, choose `--chunk-grouping
market_day_file_family_v1`: chunks do not mix event folders or file families.
The default `sorted_whole_files_v1` preserves existing plan bytes and grouping.
Unknown grouping policies are refused. The grouping is included in the plan hash.

The production CLI admits only immediate files of recognized market-day
snapshot folders strictly older than thirty days. Each source is pinned on
NTFS against writes, deletion and ancestor replacement while streaming its
SHA-256 into a deterministic USTAR/gzip archive. The completed object is reread
and every ordered header, member, content hash, padding and footer is checked.
No archive is extracted on the capture host.

Every attempt is create-only. Claim, archive, manifest, inner receipt, copied
request, execution receipt and wrapper receipt remain available for review.
A failure preserves partial evidence and spends that attempt path.

## Execution

Use the project interpreter and exact reviewed source checkout. Metadata-only
planning is:

```powershell
.\venv\Scripts\python.exe -m weather.operations.production_cold_archive_stage_cli plan --selection <absolute-selection-path> --selection-sha256 <raw-sha256> --output-path <new-absolute-plan-path>
```

The plan's raw SHA-256 binds a request with exactly these fields:
`schema_version`, `production_repo_root`, `execution_host_id`, `operation`
(`stage_only`), `approved_by`, `approved_at_utc`, `expires_at_utc`,
`plan_path`, `plan_sha256`, `chunk_id`, and `source_git_sha`.
The request must be currently valid and expire within 72 hours of approval.

Run one request at a time through `scripts/ops/production_cold_archive_run.ps1`
with mandatory `-ProductionRepoRoot`, `-RequestPath`, `-RequestSha256`,
`-OutputRoot` and `-ExpectedSourceTip`. Output must be a new immediate child of
production `scratch/production_cold_archive`. Source must be the exact clean
reviewed worktree; imports, request, source tip and host identity are checked.

This payload lane uses the ordinary capture-host 00:30-09:00 timetable,
excluding 04:45-06:45 for existing tiering jobs. Dated inventory/compression
exceptions do not admit it. It holds the shared workload lease, owns the whole
child tree in a kill-on-close Windows Job, and stops within 300 seconds with
teardown reserved before the window boundary. Streaming is throttled to
16 MiB/s; admission requires healthy capture, commit below 70%, at least
4 GiB physical memory available, and the bounded process memory checks.
The core reserves worst-case output plus 50 GiB capture headroom and 16 MiB
evidence headroom, then checks remaining reserve on every write.

Owner approval on September 9, 2026 permits 20 GiB of capture reserve only
for the selected July 16-31 archive. The CLI pins the exact plan raw SHA-256
and its selection digest in `APPROVED_ARCHIVE_PLAN_SHA256` and
`APPROVED_ARCHIVE_SELECTION_SHA256`. It verifies the actual plan bytes before
selecting the lower reserve; a different or regenerated plan keeps 50 GiB.
The same selected reserve reaches both ongoing admission and core output
reservation. Evidence headroom, worst-case output reservation, time, lease,
memory, capture health and teardown guards all remain. Final admission evidence
records `source_disk_reserve_bytes`.

## What a PASS establishes

A staging PASS proves byte identity during its pinned reads and local archive
readback. It keeps `source_retained=true`, `cleanup_eligible=false`,
`upload_performed=false`, `restore_performed=false` and
`consumer_closure_proved=false`. The outer wrapper additionally proves complete
child-tree teardown. It reports zero reclaimed bytes.

Transport must separately prove encryption and recovery-key custody, private
remote destination and exact object identity, independent remote download and
full restore. A later deletion lane must also prove consumer closure, retained
restore metadata and fresh exact source identity. This staging CLI exposes no
upload or source deletion operation.


## Encrypted transfer and independent restore

The production staging module continues to expose staging only. After a
successful staging receipt, transfer the exact archive and its manifest/receipt
to a restricted workstation inbox. Verify their raw hashes there. Use the
existing admitted workstation stage entrypoint with `--production-chunk` to
encrypt this copied archive; use the restore entrypoint with that flag to
restore an independently downloaded object. Both route to
`weather.operations.bulk_cold_archive_crypt`. The workstation wrapper and its
host, principal, shared-mutex and complete child-tree constraints still apply.

Encryption requires `--archive-file` (named `archive.tar.gz`). Both commands require
`--production-manifest`, `--production-manifest-sha256`,
`--production-receipt`, `--production-receipt-sha256`, `--plan-sha256`,
`--archive-id`, `--rclone-executable`, `--rclone-config`, `--dpapi-secret`,
`--crypt-remote-name`, `--ciphertext-root` and `--output-root`.
Restore additionally requires `--restore-id`, `--crypt-receipt`,
`--crypt-receipt-sha256`, `--transport-receipt`,
`--transport-receipt-sha256` and `--downloaded-file`. The original plaintext
`--archive-file` and `--original-ciphertext-root` are optional on restore:
recovery uses the bound source manifest and independent download after local
originals have been reclaimed. Supplied originals retain their extra checks.
Use short unique IDs and fresh attempt paths.

Encryption checks the complete production archive, encrypted configuration,
local crypt destination, ciphertext header/hash and cryptcheck. Native pins
protect regular inputs and path ancestors. Supporting secrets remain local and
must be usable by the admitted Windows principal. The 600-second bridge deadline
includes its local hashing, encryption or restore work.

Back on the capture controller, `production_cold_archive_run.ps1 -Operation
transfer` retains the same request/source/host, lease, capture, memory, overnight
window and 300-second teardown requirements as staging. Its new immediate output
parent is `scratch/production_cold_archive_transfer`. The request uses
`production_cold_archive_transfer_request` with operation
`upload_and_independent_download`, the common staging request fields, plus
`archive_id`, `drive_remote_name`, `drive_root_folder_id`,
`ciphertext_path`, `crypt_receipt_path`, `crypt_receipt_sha256`,
`production_manifest_path`, `production_manifest_sha256`,
`production_receipt_path`, `production_receipt_sha256`,
`rclone_executable`, `rclone_config`, and `dpapi_secret`.
The same exact-plan reserve exception applies; another plan keeps 50 GiB.

The client requires encrypted configuration and Drive's app-created-files
scope, with the reviewed private folder ID explicitly supplied to every call.
It creates four new objects: ciphertext and production manifest, stage receipt
and crypt receipt sidecars. Every name must be absent first. Sidecars contain
recovery metadata; captured payload bytes are encrypted. Each object is
downloaded to a fresh local path, fully hashed and compared with stable remote
ID/size/hash metadata. Network copies use one transfer at 8 MiB/s; hashes use
16 MiB/s. Required remaining time includes two copies, input/download hashes
and 45 seconds for startup/metadata. A chunk that cannot fit is refused before
upload, even when it meets the staging size limit. Use the separately bounded upload/download phases below for full-size
incompressible chunks.

An attempt-local encrypted config copy is pinned throughout network operations;
the source configuration stays immutable. Token refresh that needs to replace
this pinned copy may refuse and must be resolved through separately reviewed
credential preparation, never by dropping the pin. Every failed attempt and
possible partial remote upload is retained for inspection.

Transport PASS proves independent ciphertext download, not plaintext restore.
Copy that downloaded object and the hash-bound transport receipt to the
workstation; restore into a fresh crypt namespace and plaintext tree. Complete
ordered archive verification, materialization and per-file rehash are required.
Drive provenance remains controller-supplied evidence on the workstation.
Recovery keys/configuration need separate durable custody.

All phases retain production sources and set cleanup eligibility false. Neither
transport nor restore establishes fresh production identity or consumer closure.
In particular, historical replay-status backfills and rotating conversions can
still reference old folders; recent date alone does not clear those consumers.
There is no production deletion executor in this bridge.


### Separate upload and download jobs

For a ciphertext object that cannot fit the combined operation, run
`production_cold_archive_run.ps1 -Operation upload` first. Its request uses
operation `upload_only` and the same exact bound inputs. The create-only
`production_cold_archive_upload_receipt` records all four remote object
identities and hashes, sets `upload_performed=true`, and keeps
`independent_download=false`. A snapshot archive upload may additionally set
`publish_catalog=true`: after upload receipt readback, the same admitted job
publishes the exact source locations and refreshes `data/cold_archive/WHERE_DATA_IS.md`.
The flag requires Boolean true and `upload_only`; other phases reject it. Catalog
publication failure retains the completed upload and sources for inspection;
finish location metadata through the catalog repair API, not another upload into
the spent namespace.

Then issue a fresh request with operation `download_and_verify`, additional
`upload_receipt_path` and `upload_receipt_sha256`, and run the wrapper with
`-Operation download`. The raw upload-receipt digest binds the exact original
object IDs, names, sizes and hashes; every object is checked before downloading
to a new local attempt and hashing it. This phase never uploads. Its transport
receipt sets `upload_performed=false` and `independent_download=true`.
The download request may omit `ciphertext_path`; this phase does not require
the original local ciphertext to remain present.
Restoration still requires that transport receipt and the complete plaintext
verification described above.

Both phases use the same transfer output parent and independent 300-second
Jobs. Their leases are `production_cold_archive_transfer_upload` and
`production_cold_archive_transfer_download`. Each budgets one ciphertext hash,
one network copy and metadata allowance at the unchanged rates. The download
phase relies on hash-bound upstream ciphertext evidence, then hashes the fresh
download; it does not spend another pass reading the original local ciphertext.
A successful upload is never presented as independent recovery. The existing
`transfer` operation retains its stricter combined two-way budget.

## Location and recovery records

Keep each original discoverable through the [cold archive location catalog](cold-archive-locations.md).
Publish exact cloud object identities and upstream proof bytes while original
source identities still match; retain independent full restore receipts
separately from temporary cache copies. These records do not grant deletion
authority or prove historical consumer closure.

## Update when

Update when chunk format, request fields, admission, output evidence or the
relationship to transport and verified reclaim changes.
