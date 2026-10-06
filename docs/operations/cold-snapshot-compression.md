# Cold snapshot NTFS compression

- **Owns:** the attended compress-and-retain lane for old snapshot files
  (`cold_snapshot_compression_run.ps1`), its request schema, bounds, receipts,
  the read-only `-VerifyRetained` mode, the batch planner, the nightly
  selection and the failed-nightly resolution record.
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
compresses nor decompresses the source. This section covers attended-lane
journals; an unfinished file in a nightly batch uses the nightly request in
[Resolving a failed nightly attempt](#resolving-a-failed-nightly-attempt).

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
`WeatherColdSnapshotNightly` daily at 06:50, current-user S4U/Limited, IgnoreNew,
140-minute Scheduler limit, with no late catch-up. Registration is production
work after review and guarded integration; it is not performed by workstation tests.
The wrapper and runner each contain their child tree in a kill-on-close Job.
A busy shared lease refuses.

The nightly window is **06:50-09:00 America/Toronto** (owner decision 2026-10-05):
after the 04:45-06:45 tiering reserve, so the 01:00-04:00 quiet window stays free
for roll-sensitive merges. Until 2026-10-06 it was 00:30-04:45.

- **Late start.** A start needs 90 minutes before 09:00, so the latest start is
  07:30. The biggest night so far (2026-10-02, 21.3 GB) took 73 minutes. A refused
  start creates no attempt and does not consume the local date.
- **Deadlines, in order.**
  - Soft stop: the child takes no new batch (at most 1 GiB) in its last 600 s
    and ends `PASS` with `stopped_at_soft_deadline: true`, like the byte budget.
  - Child deadline: 09:00 - 15 s - 120 s. A guard trip there ends in the child's
    own `FAILED_RETAIN_AND_INSPECT` receipt, which the resolution below can clear.
  - Wrapper hard stop: 09:00 - 15 s, a backstop. A hard-stopped receipt cannot be
    resolved by the tool.
  - Runner backstop: 09:00, so the wrapper can still write its receipt.
- **One attempt per local date** is unchanged. Attempts are still named
  `nightly-YYYYMMDD-*` by the local date of the start.

The nightly policy schema is `cold_snapshot_nightly_policy` (version from the
central registry). Exact fields: `schema_version`, `production_repo_root`,
`execution_host_id`, `operation` (`compress_and_retain`), `approved_by`,
`approved_at_utc`, `expires_at_utc`, and `nightly_budget_bytes`. Approval lasts
at most 31 days. The approved policy's file and SHA-256 and the reviewed full
source SHA are frozen into the scheduled action; renewal requires a new
create-only policy and reviewed re-registration. No policy changes itself.

Selection is oldest built-in event first, once the closed market-day is at
least two local calendar days old (owner decision 2026-09-30 in
[DECISION_LOG](DECISION_LOG.md), replacing fourteen): at the 06:50 run on day D+2 the
market-day D is selectable, D+1 and later are not. Only immediate ordinary
nonempty JSON/JSONL/CSV files qualify; each must also be unchanged for two full
days, so a file last written late on D is picked up a night later and a later
backfill waits out its own two days. Nested directories, RE-1 campaigns,
mm_runs, payload CAS, settlement roots, links and already-compressed files are
excluded. The metadata inventory's original CLI still uses thirty days; only
this separate nightly consumer selects its two-day profile (`HOT_WINDOW_DAYS`
and `UNCHANGED_SECONDS` in `cold_snapshot_nightly.py`). Every hash, identity,
writer-exclusion and admission check is unchanged by the shorter age.

Files that cannot shrink are skipped at selection: logical size below one
4 KiB cluster (including files NTFS keeps resident in their MFT record) or
allocation not above one cluster. They are never opened, compressed or counted
against the budget; each night records them with a reason in
`skipped-NNNN.json` (bound to its inventory hash, inside the 64 MiB evidence
bound) and counts them as `files_skipped_unshrinkable`. A selected file that
still reclaims nothing stops its batch exactly as before.

Snapshot-root selection classifies entries by name only: live status files,
writer locks and hot event folders are never stat'ed or opened, and an error on
a selected closed-day folder refuses. The capture loops atomically replace their
status files, so the per-second capture-admission read can land on a
delete-pending file (the 2026-10-03 night failed after 87 batches with
`PermissionError` on `clob_loop_status.json`). A `PermissionError` or `BLOCK`
from one admission observation is followed, after 0.25 s, by one fresh complete
observation that decides; criteria are unchanged and a second failure refuses.
The receipt counts these as `admission_retries` and keeps the first 32 first
observations in `admission_retry_notes`.

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
blocks subsequent automatic runs. Never delete or rename a failed attempt to
clear this interlock. A second scheduled-entrypoint attempt on the same local
date refuses, so the budget is not reset by a retry, and a resolved attempt
still consumes its date.

### Resolving a failed nightly attempt

After inspecting the attempt, production records a resolution with the
reviewed source (read-only over the attempt's receipts; no lease needed, no
source payload read):

```powershell
.\venv\Scripts\python.exe -m weather.operations.cold_snapshot_nightly_resolution `
  --production-repo-root $productionRepo --attempt nightly-YYYYMMDD-... `
  --approved-by "<reviewer>"
```

It refuses unless the wrapper receipt is `FAILED` with proved teardown and no
hard stop, the child result is the bound `FAILED_RETAIN_AND_INSPECT`, and every
started file in every batch has both journals, follows its hash-bound
selection in order, and has an after-journal `VERIFIED` with the preimage
SHA-256, unchanged identity fields and LZNT1 format. It writes one create-only
`scratch/cold_snapshot_compression/resolved-nightly/<attempt>.json` binding the
attempt's `wrapper-result.json` SHA-256. The scheduled runner accepts a failed
prior attempt only when that record exists and its hash matches. The record's
`verified_reclaimed_bytes` is for reconciliation and is never added to a
nightly total; its files are already compressed and can never be selected again.

An attempt with a started but unfinished file (a before-journal without its
after-journal) is refused and stays blocking until that file is verified. Such
a file can only be the last started file of the attempt's last batch. Verify it
read-only with the attended wrapper in its ordinary window (00:30-09:00 outside
04:45-06:45, shared lease, capture admission, 600-second bound) and a new
reviewed request with schema `cold_snapshot_verification_request_v1`, operation
`verify_retained_nightly` (which selects this contract) and exactly these other
fields: `production_repo_root`, `execution_host_id`, `approved_by`, `approved_at_utc`,
`expires_at_utc` (at most 72 hours later), `attempt` (the `nightly-*` name),
`batch` (`batch-NNNN`), `ordinal` (integer), `preimage_sha256` (hash of that
`NNN-before.json`) and `predecessor_wrapper_sha256` (hash of the attempt's
`wrapper-result.json`). Name the output directory anything **but**
`nightly-*` (for example `verify-nightly-YYYYMMDD-a`): the scheduled runner
treats every `nightly-*` directory as an attempt, and the verifier refuses
such a name.

```powershell
& .\scripts\ops\cold_snapshot_compression_run.ps1 `
  -ProductionRepoRoot $productionRepo -RequestPath $verifyRequestPath `
  -RequestSha256 $verifyRequestSha256 -ExpectedSourceTip $reviewedSourceTip `
  -OutputRoot "$productionRepo\scratch\cold_snapshot_compression\verify-nightly-YYYYMMDD-a" `
  -VerifyRetained
```

The verifier refuses unless the attempt is a torn-down `FAILED` apply on this
host whose child result is `FAILED_RETAIN_AND_INSPECT`, its retained
`request.json` matches the wrapper's request hash, the named batch is the last
one and holds no `result.json`, every earlier file of that batch has both
journals and the named ordinal has only its before-journal. The before-journal
must name its selected path, carry an exact SHA-256 and the full uncompressed
native preimage and equal its `selection.json` row; that row must appear in the
hash-bound PASS `inventory-NNNN.json` and still satisfy the nightly cold-file
contract. The verifier then opens the retained file without write access and
requires unchanged identity fields (size, volume, file index, mtime, creation
time), a compression state that is either untouched (format 0 with the original
allocation and attributes) or LZNT1 (format 2 with exactly the compressed
attribute added), and a streamed SHA-256 equal to the before-journal's. A hash
mismatch, any other state or a missing file fails verification and writes no
PASS. Then resolve with the verification bound by hash:

```powershell
.\venv\Scripts\python.exe -m weather.operations.cold_snapshot_nightly_resolution `
  --production-repo-root $productionRepo --attempt nightly-YYYYMMDD-... `
  --approved-by "<reviewer>" `
  --verified-retained "$productionRepo\scratch\cold_snapshot_compression\verify-nightly-YYYYMMDD-a\wrapper-result.json" `
  --verified-retained-sha256 $verificationWrapperSha256
```

The resolution accepts the unfinished file only when that verification wrapper
is a torn-down read-only `PASS` (`apply=false`, `reclaimed_bytes=0`,
`source_files_changed=0`), its `result.json` and `request.json` match their
hashes, and its single `VERIFIED_RETAINED` row binds this attempt, batch,
ordinal, current before-journal hash, path, preimage and equal SHA-256. Every
other started file still needs its `VERIFIED` after-journal. The row is marked
`verified_by: retained_verification`, its `verified_reclaimed_bytes` enters only
the record's reconciliation figure, and the record lists the verification
wrapper hash in `retained_verifications`. A verification that matches no
unfinished file is refused. A file verified untouched (format 0) stays
uncompressed and a later night may select it.

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
compression, or silently change the nightly two-day protection. A
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
