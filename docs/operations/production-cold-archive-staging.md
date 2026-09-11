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
For bulk recovery, `market_day_v1` combines selected file families from one
event folder under the same 1 GiB and 256-member bounds. It never mixes market
days, and every member retains its independent path, native identity and hash.
For larger campaigns, `whole_files_with_isolated_events_v1` packs ordinary
folders together while repeated `--isolate-event <event-slug>` arguments keep
specified folders separate. All file representations and existing byte/member
bounds remain. The sealed isolation list and canonical membership are checked
again before staging and reclaim; isolation never supplies deletion authority.
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

For an approved multi-batch run, use the
[resumable campaign controller](cold-archive-campaign.md). It derives phase
requests from receipts and retains the existing individual phase gates.


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
16 MiB/s; admission requires healthy capture, system commit below 80%, at least
4 GiB physical memory available, and the bounded process memory checks.
Archive memory admission uses system-wide `GetPerformanceInfo` commit and
physical-page counters. The archive-only 80% threshold leaves the shared
70% default and the emergency watchdog unchanged. The campaign requires five
good samples two seconds apart below 78% before starting a capture phase;
missing counters, less than 4 GiB available, or unhealthy capture still block.
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

For the owner's September 10 overnight recovery using only the existing PCs
and Drive, the exact approved primary plan or its identical-selection same-day
or isolated-event regroupings use a 6 GiB capture
reserve between 04:00 and 13:00 UTC on September 10. The owner renewed the
same three exact plans for September 11, 04:30-13:00 UTC only. The gap between
these dated windows and all later dates keep the ordinary reserve. The
04:45-06:45 Toronto tiering exclusion and every capture, lease, restore and
deletion gate remain unchanged. The CLI binds each exact plan
digest and verifies the actual plan bytes; other plans keep their existing
reserve. Each chunk remains at most 1 GiB, with evidence and worst-case output
reserved separately. The controller must also reserve ingress and download
copies before copying them onto the capture disk.

The archive workstation wrapper accepts one `--archive-unattended` token
inside its encoded Python arguments only for the archive stage and restore
modules. It removes the token and launches under the same host/principal lease
and kill-on-close Job without requesting an interactive user token. This does
not change other workstation workloads or any live-execution admission.
Dedicated archive credentials may use the explicitly tagged
`weather-archive-machine-v1:` DPAPI format in a directory restricted to the
owning Windows account and SYSTEM. Recovery keys must also have a verified
private off-PC copy before reclaim. The archive owner authorized the agent to
save and independently verify that backup; the custody record must identify
the actual backup and verification evidence.

Exact-file transport uses `copyto` with its hard transfer-byte cap. It must not
add rclone size filters: rclone 1.75 rejects filters for single-file copies.
Pinned source size/hash and the independently checked remote size retain the
per-object bounds. Failed transfers retain only source module/line locations,
never exception messages or client output; a capture refusal also retains its
bounded resource observation. A committed-object lookup may retry a transient
empty not-found response at most four times under the same deadline. A download
may retry only while its destination is still absent; uploads and partially
created downloads are never automatically retried. Every returned object must
still match its committed ID, size and hashes.

## What a PASS establishes

A staging PASS proves byte identity during its pinned reads and local archive
readback. It keeps `source_retained=true`, `cleanup_eligible=false`,
`upload_performed=false`, `restore_performed=false` and
`consumer_closure_proved=false`. The outer wrapper additionally proves complete
child-tree teardown. It reports zero reclaimed bytes.

Transport must separately prove encryption and recovery-key custody, private
remote destination and exact object identity, independent remote download and
full restore. The separate [original reclaim lane](cold-archive-locations.md#original-source-reclaim)
also requires consumer adoption, retained restore metadata, custody and fresh
exact source identity. This staging CLI exposes no
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
Recovery keys/configuration need separate durable custody. Use the admitted
[workstation recovery handback](cold-archive-locations.md#workstation-recovery-handback)
to publish the complete restore and verified off-host metadata copies.

All phases retain production sources and set cleanup eligibility false. Neither
transport nor restore establishes fresh production identity or consumer closure.
In particular, historical replay-status backfills and rotating conversions can
still reference old folders; recent date alone does not clear those consumers.
Original deletion is owned by the separately gated
[reclaim executor](cold-archive-locations.md#original-source-reclaim). The
staging, encryption, transport and restore bridge retains its sources.


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

## Transfer from an already staged workstation copy

The admitted workstation stage entrypoint accepts `--production-transfer`,
followed by `upload_only` or `download_and_verify`. It routes to
`weather.operations.workstation_cold_archive_transfer` under the existing
workstation host/principal lease and Windows Job. Supply `--attempt-id`,
`--expected-source-tip` and the transfer core's explicit paths, hashes, archive,
plan and private Drive bindings. Inputs must be outside data and mirror trees;
only already copied archive inputs are eligible.

Each workstation network phase has a 900-second deadline, 20 GiB of reserve, native
input/config/source pins, the unchanged bounded transfer client, and a fresh
attempt beneath `scratch/production_cold_archive_transport`. Its parent and
the checkout's empty protected `data` directory must exist. Never populate
that data directory from a mirror. Exact name lookups must be complete and
unambiguous before upload; subsequent reads use immutable object IDs.

Before payload reads, the workstation prepares a new encrypted credential copy,
performs a bounded metadata-only refresh, and verifies at least 930 seconds of
token validity. The supplied credential file remains unchanged; the prepared
copy is pinned during transport. Local verification uses the workstation-only
64 MiB/s profile. Network transfer remains capped at 8 MiB/s; admission budgets
2 MiB/s as a conservative measured baseline, rather than treating the cap as
a guaranteed minimum. Production transfer rates and deadlines are unchanged.

The core upload and independent-download receipts retain their existing
schemas. A separate workstation execution receipt binds the clean source tip,
module hashes, host and assignment to the core receipt. It proves no fresh
production identity and publishes no production location markers. Production
catalog publication/reclaim still requires its own fresh admitted operation;
preserve the new upload instead of repeating it to obtain a catalog entry.

## Location and recovery records

Keep each original discoverable through the [cold archive location catalog](cold-archive-locations.md).
Publish exact cloud object identities and upstream proof bytes while original
source identities still match; retain independent full restore receipts
separately from temporary cache copies. The [temporary payload lifecycle](cold-archive-locations.md#temporary-payload-lifecycle)
releases only the exact three reviewed production staging/transfer payloads after
complete recovery and custody checks; retaining them indefinitely defeats net
headroom recovery. These records do not grant deletion
authority or prove historical consumer closure.

The dated overnight staging path additionally reserves two complete worst-case
encrypted payload copies before opening any original: the ingress copy and the
independent download. The archive writer separately reserves its own complete
worst-case output. Thus the lower fixed reserve includes explicit working-space
accounting for all three production payloads. Requests that cannot fit remain
source-retaining refusals. Upload, download and reclaim still recheck capture
and headroom throughout their bounded jobs.

Read-only queries for an already-bound Drive object may retry an empty or null
transient response at most four times within the unchanged job deadline. Every
successful query must still match the exact object identity and size. Uploads
are never retried automatically, and a materialized download is never overwritten.

The separate download phase resolves each already-committed object directly by
its Drive file ID. Authenticated GET requests remain restricted to the Google
Drive API host, reject redirects, verify the exact parent/name/size/checksums,
and stream create-only payloads at 8 MiB/s under the existing lease, resource
and deadline guards. This avoids repeated filename listings against the shared
client quota. Credential refresh remains a separate preparation step; no
plaintext credential is written into an archive receipt.

## Publishing an already committed upload

When a reviewed workstation transfer has already uploaded the four bound objects,
use `production_cold_archive_run.ps1 -Operation publish` with a fresh attempt
under `scratch/production_cold_archive_transfer`. This registers the existing
upload and source locations without starting a cloud client, reading ciphertext,
or uploading again. It remains inside the production window, tiering exclusion,
lease, exact source, capture, resource, owner-expiry and 300-second Job gates.

The request uses `production_cold_archive_transfer_request` with operation
`publish_uploaded` and `publish_catalog=true`. Include the ordinary production
root, host, named approval, source tip, expiry, plan/chunk/archive and four upstream
hash bindings; the manifest, stage and crypt receipt paths; the exact
`drive_root_folder_id`; and `upload_receipt_path` / `upload_receipt_sha256`.
Omit `ciphertext_path`, `rclone_executable`, `rclone_config`, `dpapi_secret`
and `drive_remote_name`: these are rejected for publication. The supplied upload
must be a sealed, successful upload-only receipt for those exact bindings.

Publication validates the full catalog proof chain and pins every original native
identity against its stage manifest. It retains the prior upload receipt bytes,
records the existing object IDs, and updates the location inventory. A changed
original or existing location refuses publication; an interrupted marker write
requires the existing reviewed location-repair path. The new result reports
`upload_performed=false`, `independent_download=false` and
`committed_upload_reused=true`; prior remote upload evidence remains in its
original receipt. Publication is not restore, custody or reclaim authority.

## September 10 attended daytime authority

The owner's immediate archive instruction has a separate dated execution
token described in [Host Load Policy](HOST_LOAD_POLICY.md#owner-archive-exception-september-10-afternoon).
Pass `-OwnerApprovedException OWNER_APPROVED_ARCHIVE_RECOVERY_20260910` to the
same production wrapper. It is valid only September 10 13:10:38–18:00 Toronto,
for the already pinned primary plans, with the same 6 GiB reserve and complete
capture, lease, bounded-child and recovery checks. Requests remain exact,
fresh and source-bound; this token cannot revive expired or spent attempts.
The wrapper records the token, forwards it explicitly, and restores the prior
environment after teardown. The independent child rejects a missing, wrong or
expired token, mismatched live lease, different plan, or overlong deadline.

## Copying a staged archive to the workstation

Use the same native wrapper with `-Operation copy`. The
`production_cold_archive_copy_request` binds the ordinary expiring production
approval, exact plan/chunk/source identity, an archive ID, direction
`to_workstation`, and three exact files derived from its sealed stage evidence.
It also binds the manifest and stage receipt paths and raw hashes, an isolated
workstation root, literal private IPv4 address and principal, explicit native
OpenSSH executable/key paths, and the known-hosts file and its SHA-256.
The `files` rows contain only `local`, `remote`, `bytes` and `sha256`.

The only outbound files are `archive.tar.gz`, `manifest.json` and
`receipt.json` from that archive's immediate production staging attempt.
The remote destination is a new `scratch/ac-in/<archive-id>` directory beneath
the approved workstation root. Existing namespaces, redirected ancestors,
different files, hashes or plan members refuse; interrupted destinations remain
spent evidence. The native production lease, current capture checks, 384 MiB
process limits and 300-second complete-child Job remain mandatory. Source
hashing and SCP each use the existing 16 MiB/s payload ceiling and run serially.
The copy phase retains native source pins and a complete pre-copy SHA-256 check.
No ambient SSH configuration,
proxy, forwarding or unpinned host-key acceptance is allowed.

When upload and independent download both occur on the workstation, production
retains only its staged archive payload. The reclaim spool inventory may contain
that single stage role only when the successful restore proves the separate
workstation layout and the fixed production ciphertext path is absent. Existing
local ciphertext still requires the ordinary two-role inventory. All selected
spools remain native-pinned and hash-checked before any original is removed.

A successful copy retains every source and reports
`destination_hash_verified=false`. The existing workstation cryptographic
bridge must independently verify all three received files before encryption.
Upload, independent download, full restore, custody and exact original reclaim
remain separate evidence gates. Prefer the approved packed plan for sustained
batching; small per-day chunks serve only bounded qualification or isolated
exceptions. Copy receipts live under a fresh immediate
`scratch/production_cold_archive_copy/<attempt>` directory.

## Update when

Update when chunk format, request fields, admission, output evidence or the
relationship to transport and verified reclaim changes.

The September 10 evening renewal uses the distinct
`OWNER_APPROVED_ARCHIVE_RECOVERY_20260910_EVENING` token from 23:43:24 UTC
through September 11 04:30 UTC. It preserves the same three pinned plans,
6 GiB reserve and archive guards; see the [dated host-policy renewal](HOST_LOAD_POLICY.md#september-10-evening-archive-renewal).
An evening job still reserves 15 seconds for teardown before the exception ends.


Staging permits a lower NTFS allocation than the measured selection only when
path, volume, file ID, logical size and modification time remain exact. It
records the current allocation in the manifest; increased allocation or any
other metadata change refuses. The proposal and plan remain immutable.
The verifier hashes the archive and every ordered member in one streaming
read. The 16 MiB/s disk-read cap applies to compressed bytes once; decompressed
bytes are checked in bounded memory without counting them as another disk read.


Archive admission recognizes the snapshot producer's declared idle sleep after
a clean iteration. Only that producer may use its advertised sleep of at most
600 seconds plus ten seconds to wake: no market may be in progress, its
heartbeat must precede the matching clean completion by at most one second,
and canonical liveness, native process/lock identity and all resource checks
must still pass. A heartbeat from a new iteration invalidates the idle case.
Busy snapshot work and the other producers keep the 180-second bound; other
storage workloads keep their existing policy. This handles the producer's
existing sleep behavior without changing capture cadence or restarting it.
