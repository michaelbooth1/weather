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

The conditional explanation-CSV reserve needs its own owner-bound selection,
complete source review and a conservative primary-allocation proof before reclaim.
That proof reconciles every sealed campaign reclaim receipt with the current
counter and its approved original identities. Remaining primary files count at
their full approved allocation ceiling; an allocation above that ceiling cannot
qualify under the existing identity contract. Actual past allocation reductions
and fresh, pinned review-queue protection are the only deductions. Reserve reclaim is allowed only
when this complete upper bound is below the owner's target, and retains the proof
inside its immutable reclaim receipt. Missing or inconsistent history refuses.
Packed plans stop at sixteen distinct market days, matching the existing
settlement-review bound.

The workstation cleanup module accepts `--plain-downloads` with one to twenty
repeated `--upload-receipt <absolute-path> <sha256>` references, plus its existing
`--attempt-id` and `--expected-source-tip`. Use the exact workstation heavy wrapper.
It rehashes both the retained copied archive and its independent verification
download against the successful upload receipt, then removes only the duplicate
download. Copied archives, manifests, receipts, credentials, directories, failed
attempts and cloud objects remain. Verification is bounded to 12 GiB per job at
the existing workstation read rate; temporary savings never advance the original
archive-reclaim target.

## September 14 owner-approved resumption

On September 13 the owner resumed the existing campaign and approved a 20 GiB
capture reserve for September 14, 00:30-04:42 America/Toronto. Only the exact
existing repacked primary and conditional-reserve plan/selection hashes pinned
in `production_cold_archive_stage_cli` qualify. Actual plan bytes must match;
changed plans retain the ordinary 50 GiB floor. The child independently requires
its deadline to leave 15 seconds for teardown before the approval expires.

This changes only the archive reserve in that window. Evidence and worst-case
output reservations, serial admission, the host lease, fresh healthy capture,
memory limits, payload throttling, 300-second Jobs, independent cloud verification,
final settlement and protected-input review, and exact native identity/hash
checks remain mandatory. It grants no daytime execution or qualification-floor
exception. The conditional reserve still requires its complete primary-budget
proof; the resumption does not make an ineligible file eligible.

Pending successful phases remain immutable. Refresh cloud-download evidence
with a new existing-object verification attempt when needed; create a fresh
request filename for an expired unlaunched copy. Do not repeat successful stage
or upload work, reuse failed attempt directories, or overwrite expired requests.

The plain continuation uses archive_plain_campaign_run.ps1, its bounded
metadata contract and serial worker, and register_archive_plain_campaign.ps1.
The private immutable configuration pins both hosts, exact source tips, existing
approval/plan/proofs, the ordered primary queue, and a separately qualified
retained-file compression plan. The registrar requires an exact successful S4U
metadata preflight before arming the single 00:30 launch; no late catch-up runs.
The outer Job stops the complete local child tree at 04:42 and records teardown.
Remote archive work uses its independently bounded workstation wrapper, with
enough time reserved before the campaign deadline.

If initial archive headroom is below 22 GiB, the controller invokes the existing
admitted retained-file compression controller first. Its separate plan targets
only the required working headroom; failure or insufficient capacity stops
archive work. Once enough space is proved, no additional compression is started.
Every original reclaim follows an independently downloaded cloud archive and a
private recovery-metadata backup. A second metadata backup records the resulting
catalog, native removal receipt and canonical counter. Failed or spent phases
are retained for review. The initial queue does not automatically repack held
files or expand into the conditional reserve.

Campaign evidence is create-only under
scratch/archive_plain_campaigns/<campaign-id>/{preflight,run}; registration
intents/readbacks have separate directories. Each phase has its own native
receipt. The wrapper reports new original-source allocation separately from
retained-file compression and current free-volume space; a partial failure never
becomes a zero-removal assertion. QUEUE_COMPLETE, WINDOW_COMPLETE, and
TARGET_REACHED remain distinct outcomes.
## Update this file when

Update when the approved transfer or original-deletion route changes.
