# Direct verified private uploads

The owner replaced the encrypted campaign with a simpler task on September 11:
upload approved data without content encryption, independently download and
compare SHA-256 hashes, then delete only the matching originals. Retain a
simple source-to-Drive-object record. Existing encrypted archives remain
recoverable through their retained records and keys.

The workstation's existing upload-and-download helper accepts `--plain-file`
for a copied input under `scratch/ac-in`, up to 1100 MiB. Invoke it through
`workstation_cold_archive_stage --backup-recovery --plain-file` with the exact
input SHA-256 and private Drive destination. It uploads the original file
bytes; the stored credential configuration remains protected separately.

Capture host resource admission and exact-source deletion checks still apply.
The earlier multi-phase encrypted controller is not the current execution route.

If upload succeeded but verification failed, a fresh attempt can use
`--existing-remote-key <archive-id>u<N>-archive.tar.gz` to verify that exact
existing object without uploading again. The key must belong to the same
copied input; independent download, full-file SHA-256, immutable object ID and
parent-folder checks remain mandatory. Plain gzip files accept gzip media
types; encrypted binary files retain their existing type restriction.

The production reclaim wrapper accepts an explicit
`production_cold_archive_plain_reclaim_request_v0.1` request with
`payload_encryption=none`, an archive ID, the owner approval/proposal/selection/plan
bindings, and exact `production_manifest`, `production_receipt`, and
`plain_upload` path/SHA-256 evidence. It first checks complete staged member
parity against the byte-identical independent workstation download, publishes
source-to-object locations, and runs the existing fresh settlement/protected-input
review. The approved primary detail families include `order_books.jsonl`;
its review retains the same settlement, queue, corpus and replay protections.
Native identity and same-handle full SHA-256 checks precede every exact
original deletion. It also removes the verified production staging payload,
preserves receipts and workstation copies, and advances the existing allocation
ledger. No encryption or key-custody record is invented for plain data.
An interrupted publication can reuse only identical verified catalog bytes;
partial original deletion still requires the existing ledger reconciliation.

## Update this file when

Update when the approved transfer or original-deletion route changes.
