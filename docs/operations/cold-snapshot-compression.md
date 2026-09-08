# Cold snapshot NTFS compression

This is a compress-and-retain capacity operation. Every source file, logical
byte, native file identity, and timestamp remains in place. NTFS provides the
same content to existing readers; no gzip reader migration or off-site
deletion eligibility is involved. It complements the
[verified archive path](verified-cold-archive.md), whose independent restore
and exact-file cleanup gates still govern any source removal.

## Selection and approval

First obtain a completed source-bound
[metadata inventory](storage-recovery-inventory.md). The same reviewed source
tip must own both inventory and compression. Select only complete folder rows.
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

## Update when

Update when bounds, allowed files, admission, wrapper parameters, request or
receipt fields, or verification semantics change. Record measured outcomes in
item 325.
