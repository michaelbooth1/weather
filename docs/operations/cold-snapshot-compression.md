# Cold snapshot NTFS compression

- **Owns:** the attended compress-and-retain lane for old snapshot files
  (`cold_snapshot_compression_run.ps1`), its request schema, bounds, receipts,
  the read-only `-VerifyRetained` mode and the batch planner.
- **Read when:** the owner asks for more retained-file capacity, or you must
  reconcile an interrupted compression attempt.
- **Do not use for:** replay-cache files
  ([replay-cache-compression.md](replay-cache-compression.md)), gzip tiering or
  deletion ([data-retention-policy.md](data-retention-policy.md)), or measured
  savings to date (item 325 and [STATE_OF_PLAY.md](STATE_OF_PLAY.md)).
- **Verify with:** the `param()` block of
  `scripts/ops/cold_snapshot_compression_run.ps1` and the `MAX_*` /
  `MIN_FREE_DISK_BYTES` constants in
  `src/weather/operations/cold_snapshot_compression.py`.

The original exact-request lane is attended. The separately registered nightly
mode below selects its own bounded batches under an expiring approved policy.

This is a compress-and-retain capacity operation. Every source file, logical
byte, native file identity, and timestamp remains in place. NTFS provides the
same content to existing readers; no gzip reader migration or off-site
deletion eligibility is involved. It complements the
[verified archive path](verified-cold-archive.md), whose independent restore
and exact-file cleanup gates still govern any source removal.

**Both dated window exceptions are expired.** The wrapper still recognises
`-OwnerApprovedException OWNER_APPROVED_STORAGE_RECOVERY_20260908` and
`..._20260909`, but each is bound to its own calendar date (expiring 18:00
Toronto that day) and now refuses. The owner record is in the
[expired host-load exceptions appendix](history/host-load-policy-expired-exceptions.md).
Do not pass either argument; the ordinary overnight window and scheduled-tiering reserve
apply, and all resource, lease, capture and teardown checks remain mandatory.

## Selection and approval

The following 30-day/64-MiB contract is unchanged for attended requests.
Nightly requests use the distinct policy and limits below.

First obtain a completed source-bound
[metadata inventory](storage-recovery-inventory.md). The same reviewed source
tip must own both inventory and compression. Select only complete folder rows.
An inventory may explicitly cover only immediate files. In that scope, folder
completion means the immediate-file selection is complete; the compression
consumer and planner reject nested candidates and mismatched folder scopes.
The request binds the inventory wrapper receipt by absolute path and SHA-256,
and copies each selected file record exactly. The child independently verifies
the wrapper, result and inventory hash chain and their source/host bindings.

The request schema is `cold_snapshot_compression_request`. It names the exact
production root and capture host, `operation=compress_and_retain`, approval
identity, approval/expiry timestamps no more than 72 hours apart,
`inventory_wrapper_receipt`, `inventory_wrapper_sha256`, and `files`.
The registry owns schema versions; the implementation enforces exact fields.

Only built-in snapshot event days strictly older than 30 days are accepted.
Each file must also have been unchanged for at least 30 days, be an ordinary
nonempty JSON, JSONL or CSV file, and not already be NTFS-compressed. Links,
hardlinks, sparse/offline/encrypted files, hidden path components, hot dates,
cache roots and ambiguous metadata are refused. Each file is at most 64 MiB;
a batch has at most 256 exact files and at most 1 GiB of logical input.
Files outside these limits remain untouched.

An event-day archive manifest and final settlement are unnecessary for this
lossless retained-path operation. It does not change data quality, settlement
authority, archive eligibility or evidence retention. A split plain/gzip pair
stays split and both paths remain; this operation neither merges nor removes it.

## Attended execution

Use a clean isolated reviewed worktree and production Python through
`scripts/ops/cold_snapshot_compression_run.ps1`. Pass absolute normalized
`-ProductionRepoRoot`, `-RequestPath`, a new `-OutputRoot` directly below
production `scratch/cold_snapshot_compression`, `-RequestSha256` and the full
`-ExpectedSourceTip`.

Without `-Apply`, the child checks native identities and writer exclusion,
reads no source payload and performs no compression. Start with a one-file
dry run and apply; review its hash/identity/allocation receipts before expanding.
`-Apply` consumes the same exact inventory-bound approved selection. It captures
and flushes the preimage hash while holding the native file handle, rechecks
admission, compresses, then hashes again. A separate payload-hashing plan is
not required because the operation retains every source byte and verifies
the before/after content under the same writer-excluding handle.

The dedicated capture identity, shared workload lease, 00:30-09:00 Toronto
window, 04:45-06:45 scheduled-tiering reserve, healthy three-worker capture,
commit below 70%, 4 GiB available memory and BelowNormal priority are mandatory.
The per-lane disk reservation is 8 GiB for concurrent capture, two complete
64 MiB file images and 8 MiB for receipts. It does not change ordinary heavy
admission or the separate cache-compression reservation.

The child streams hashes at at most 16 MiB/s. Files are processed serially.
The wrapper owns the complete child tree in a kill-on-close Job, bounds runtime
to 600 seconds, and clamps to the next protected boundary with teardown reserve.
The child checks capture/resources at least every second while progressing.
Heartbeat and clean-iteration ages use a comparison time sampled after all
status/identity reads, so a heartbeat published during a read is not mistaken
for future evidence. Genuinely future or stale timestamps still fail closed.
A synchronous filesystem operation is additionally bounded by the parent Job.

## Receipts and stopping rules

Retain every attempt. The request, per-file before/after journals, terminal
result and wrapper receipt are create-only. Per-file evidence is flushed before
compression; final source/request equality and child-tree teardown are required
for wrapper PASS. A failed or interrupted attempt remains evidence and is not
reused. No automatic decompress, retry or deletion is provided.

Count savings only for `VERIFIED` files with equal before/after SHA-256,
unchanged native identity/timestamp, and reduced physical allocation. A hash,
identity, admission or non-positive-savings result stops the batch. Retain the
file and inspect its journal before selecting anything further. An interrupted
file must be re-inventoried and verified; do not infer its savings from disk
free space alone.

Compare the sum of verified allocation deltas with fresh volume free space.
Concurrent capture means the two numbers can differ. Previously counted file
identities must never contribute twice. All receipts keep `deleted_files=0`
and `cleanup_eligible=false`; none is an archive restore or deletion proof.

## Read-only verification after interruption

Use the same wrapper with `-VerifyRetained`, never together with `-Apply`.
This mode opens one exact file without write access, denies concurrent writers,
streams its hash under the unchanged resource/capture/lease/deadline gates,
and compares every original native identity field and timestamp. It neither
compresses nor decompresses the source.

First obtain a fresh completed inventory at the new reviewed execution source.
The request uses schema `cold_snapshot_verification_request_v1`, operation
`verify_retained`, the ordinary host/root/approval/expiry and inventory-wrapper
fields, and exactly one current inventory row in `files`. Additionally bind:

- `preimage_receipt`: the absolute retained `NNN-before.json` path under one
  direct `scratch/cold_snapshot_compression` attempt.
- `preimage_sha256`: the exact hash of that original journal.
- `predecessor_wrapper_sha256`: the exact hash of that attempt's wrapper receipt.

New attempts retain the approved request bytes exactly, preserving the wrapper's
request hash across key order, whitespace and encoding. Older attempts may have
saved a sorted, formatted request copy instead. For such an attempt, additionally
name `predecessor_request`: the absolute normalized path to its still-retained
original approval JSON directly under production `scratch/handoffs`. The verifier
checks that original against the predecessor wrapper's request hash and requires
the attempt copy to equal either those exact hashed bytes or the exact legacy
serialization of the same original. It never rewrites a spent receipt. A missing,
changed or differently bound original or copy blocks verification.

The predecessor must be a terminal failed apply on the same host with proved
teardown. Its original request hash, journal ordinal, native preimage and source
identity must agree. Its source may differ from the newly qualified verifier;
the old approval is historical evidence, never current execution authority.
Both uncompressed and LZNT1-compressed retained files can be verified.

A new create-only attempt publishes `000-verification.json`, `result.json`
and a wrapper receipt. `reclaimed_bytes=0` and `source_files_changed=0`
describe this read-only operation. `verified_reclaimed_bytes` reports the
original-to-current allocation difference separately, which must never be
counted twice. Verification PASS proves retained content integrity; it is not
an automatic retry, recompression, expansion, decompression or deletion grant.
A failed verification remains immutable evidence and keeps further action
blocked until its exact disagreement is resolved.

## Preparing expansion requests

`weather.operations.storage_recovery_batch_plan` reads only completed
inventory and pilot receipts. It does not open source payloads or execute
compression. Bind `--production-repo-root`, `--inventory-wrapper-receipt`,
`--inventory-wrapper-sha256`, `--source-git-sha`, `--execution-host-id`,
`--approved-by`, `--expires-at-utc`, and a new `--output-root` directly
below the existing production `scratch/storage_recovery_plans` directory.

Default `--mode pilot` prepares one exact request for the largest eligible
file. The planner initially excludes files smaller than 1 MiB to avoid
spending compression work on negligible allocation savings. Review its
`plan.json` and request; run the compression wrapper first without and then
with `-Apply`, each in its own new output attempt.

`--mode expand` additionally requires `--pilot-wrapper-receipt` and
`--pilot-wrapper-sha256`. It verifies the hash chain, completed apply,
unchanged file identity and positive allocation delta for one pilot file
from this same inventory and source. The pilot path is excluded from expansion.
At most eight bounded request files are emitted per plan, with exact hashes
and a deterministic `next_index`. Advance `--start-index` only after the
previous planned batches have completed and their receipts were reviewed.
A failed batch stops expansion; re-inventory and reconcile its exact journals.
No cursor is permission to skip failed evidence or count savings twice.

Eligible and selected allocation totals are candidate capacity. Estimated
reclaim stays null and actual reclaim stays zero in the plan. Only the
compression receipts can establish saved bytes.

## Nightly automatic selection

`cold_snapshot_nightly_run.ps1` calls the same guarded compression wrapper with
`-Nightly`. `register_cold_snapshot_nightly.ps1` registers
`WeatherColdSnapshotNightly` at 00:30, current-user S4U/Limited, IgnoreNew,
255-minute Scheduler limit, with no late catch-up. Registration is production
work after review and guarded integration; it is not performed by workstation tests.
The wrapper and runner each contain their child tree in a kill-on-close Job;
the wrapper reserves teardown before 04:45. A busy shared lease refuses.

The nightly policy schema is `cold_snapshot_nightly_policy` (version from the
central registry). Exact fields: `schema_version`, `production_repo_root`,
`execution_host_id`, `operation` (`compress_and_retain`), `approved_by`,
`approved_at_utc`, `expires_at_utc`, and `nightly_budget_bytes`. Approval lasts
at most 31 days. The approved policy's file and SHA-256 and the reviewed full
source SHA are frozen into the scheduled action; renewal requires a new
create-only policy and reviewed re-registration. No policy changes itself.

Selection is oldest built-in event first, strictly older than fourteen local
calendar days. Only immediate ordinary nonempty JSON/JSONL/CSV files qualify;
each must also be unchanged for fourteen days. Nested directories, RE-1
campaigns, mm_runs, payload CAS, settlement roots, links and already-compressed
files are excluded. The metadata inventory's original CLI still uses thirty
days; only this separate nightly consumer selects its fourteen-day profile.

Limits: 256 MiB/file, 1 GiB and 256 files/batch, at most 32 GiB and 8,192 files
per night (policy may lower the byte limit), 10,000 root entries, 64 MiB total
inventory evidence. The disk reservation is 8 GiB plus two 256 MiB file images
and 128 MiB evidence headroom. Streaming hashes remain capped at 16 MiB/s and
use 1 MiB buffers. All resource, host, source, writer-exclusion, identity,
preimage/postimage and positive-savings requirements remain in force.
The shared native helper's default remains 64 MiB for all other callers.

Each new attempt contains the approved policy, complete per-folder inventory,
hash-bound exact batch selections, flushed before/after file journals and
batch/night/wrapper results. Count only verified allocation differences;
uncompleted batches can have per-file proofs but receive no aggregate credit.
Any failure stops expansion. A failed or unfinished prior nightly attempt
blocks subsequent automatic runs; production must inspect and explicitly
resolve it through the retained-file verification contract. Never delete or
rename a failed attempt to clear this interlock. A second scheduled-entrypoint
attempt on the same local date refuses, so the budget is not reset by a retry.

Production registration, after creating and reviewing the policy and proving
the exact source tip (all paths absolute):

```powershell
& .\scripts\ops\register_cold_snapshot_nightly.ps1 `
  -ProductionRepoRoot $productionRepo `
  -RequestPath $approvedPolicyPath -RequestSha256 $approvedPolicySha256 `
  -ExpectedSourceTip $reviewedSourceTip -Apply
```

The variables must name the actual production root, immutable policy file,
its hash and reviewed tip. Omitting `-Apply` registers metadata/writer-lock
validation only. Before registration, perform a bounded dry run with
`cold_snapshot_compression_run.ps1 -Nightly` and a fresh output directory,
then one bounded low-budget apply; review its complete receipts. Do not invoke
either production path from the workstation. A policy expiry is an explicit
stop, not permission to manufacture renewal authority.

## Compress-on-close design and reader compatibility

Use NTFS compression after the day closes, through a future separate close
queue, rather than renaming these families to gzip. Existing gzip support is
uneven: the projection registry has gzip alternatives for several CSVs, while
direct readers still name plain paths. NTFS preserves names and logical bytes
for every reader, including dynamic path consumers. The native regression
proves identical SHA-256 and size through ordinary reads of a file over 64 MiB;
the compression receipt repeats that proof for each real file.

Capture-side integration is **design only**: `SnapshotStore` owns replay,
snapshots, components, variants and explanation files; `MarketMicrostructureStore`
owns token and book-summary files. Neither is modified. A close queue must
prove event close, quiescent writer handles, replay/backfill coordination and
durable enqueue before releasing a file to the same compressor. It must not
compress synchronously inside a capture iteration, set inherited directory
compression, or silently change the nightly fourteen-day protection. A
separate reviewed close policy and production roll verdict precede that work.

Reader/reference inventory for the proposed unchanged-path format is retained
in the mission 91a report. Native lossless verification is the compatibility
contract; a per-reader gzip migration is not claimed.

## mm_runs retention proposal

Keep `market_making_lifecycle_risk` permanent evidence under
`storage_classes.py` and the [storage-class contract](data-storage-class-contract.md).
Age alone is not a deletion gate. Propose a separate closed-run NTFS lane,
admitting only terminal paper runs after writer/replay-reference checks, with
the same identity/hash receipts. Reclaim via the existing verified off-PC
archive only after exact-file restore proof and approval. Do not include RE-1,
live runs, active runs, or incident-referenced evidence in that initial lane.
This mission changes no mm_runs retention or bytes.

## Update this file when

Update when bounds, allowed files, admission, wrapper parameters, request or
receipt fields, or verification semantics change. Record measured outcomes in
item 325.
