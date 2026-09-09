# 325. Tiered Data Retention And Verified Archive Offload [PARTIAL 2026-09-08 - OVERNIGHT RECOVERY ARMED; PRODUCTION TARGET OPEN]

Goal: keep the production capture host permanently inside its disk budget by
holding only the operating window locally, offloading everything older to a
verified append-only archive on the workstation host, and never deleting a byte
that has not been proven durable elsewhere.

Owner/package: weather.operations, weather.collection

## 2026-09-08 additional capacity recovery approved

The owner approved a target of at least 120 GiB newly reclaimed and at least
100 GiB free on completion; the previous overnight 16.04 GiB is excluded.
The target is not yet achieved. At 11:47 Toronto the owner explicitly authorized
work now unless judged excessively risky. The bounded inventory and one-file
compression pilot are judged reasonable subject to all existing resource and
capture checks. The [dated host-policy exception](../../operations/HOST_LOAD_POLICY.md#owner-storage-exception-september-8-2026)
expires at 18:00 today and grants no deletion or other workload authority.
Expansion still requires verified positive pilot savings and fresh admission.

The new [metadata inventory](../../operations/storage-recovery-inventory.md)
measures complete cold folders by native allocation without source payload reads.
Missing or invalid archive manifests still block archive eligibility; a July 1
Toronto metadata spot-check found no event-day manifest. The archive/delete
executor and verified destination quota remain unresolved.

A supplementary [cold snapshot NTFS compression lane](../../operations/cold-snapshot-compression.md)
preserves all paths and logical bytes, avoiding an archive-deletion dependency
for this capacity source. It requires exact inventory receipt bindings, cold
file/event dates, native identity, a flushed preimage hash, and identical
post-compression content before reporting allocation savings. It is bounded to
64 MiB per file, 256 files / 1 GiB per batch, 16 MiB/s streaming and a 600-second
contained child. This is source qualification, not production reclaim evidence.

Native Windows verification at `e8531de71f60a715518749287b90d8f55ee4a139`
passed 134 focused checks, including an actual retained-file compression
workflow, receipt-chain negatives, inventory allocation and the real wrapper's
failure/teardown behavior in isolated fixtures. The preceding inventory/cache
regression run at `804ead764` passed 164 checks. Both remote wrapper sessions
ended at exit zero. Source changes after those tips require their own checks.

Receipts are workstation-local ignored files:
`scratch/capacity-cold-native-e8531de71.xml`, SHA-256
`62407327c1b548a984e1d1becb22ede89712adc25fb68ef619187d9c0af53ae7`,
and `scratch/capacity-inventory-wrapper-native-804ead764.xml`, SHA-256
`1869fb0e3253bb214838a897bc12fc6aebf81f4a2c470fd7024f784d870ca6ca`.
No fixture byte savings are counted toward the production target.

The receipt-only batch planner at `a4eb5450e76141ac13ee8bd1b26c312c9a164192`
passed 107 native checks covering the planner CLI, compressed-file verification,
receipt tampering, schema and documentation/import contracts. Expansion requires
a completed positive one-file pilot from the same source and inventory.
The earlier host-guard/reader matrix at `f2b32194b` passed 208 tests and
22 subtests. Both admitted workstation sessions ended at exit zero.

Their retained JUnit files are `scratch/capacity-batch-native-a4eb5450e.xml`,
SHA-256 `6d40dc950cabb360f663c51ef952d1730c5a941e8005f244fc5310bee8648f08`,
and `scratch/capacity-guard-readers-native-f2b32194b.xml`, SHA-256
`a7600dce40bb0817ac4c8487ca4cdbffe5e8f7a5c87c6d1acdeece39f7794bc9`.
The first production attempt at 12:14 Toronto refused the unchanged commit
memory gate before inventory; teardown was proved. After the owner approved
closing idle Chrome and restarting Explorer, memory headroom recovered.
Explorer was restored in its original desktop session; the completed temporary
nonrecurring restoration launcher was removed after its exit-zero receipt.

At 12:29, the second inventory passed resource/capture admission (66.59% commit)
but hit the 15,000-entry directory limit inside Atlanta July 1's raw subtree.
Its PARTIAL result and all observations remain retained, with zero completed
folder capacity and no compression authority. Production attempts are
`scratch/storage_recovery_inventory/capacity-daytime-july01-20260908-01` and
`capacity-daytime-july01-20260908-02`. Neither reclaimed space.

The qualified selection uses explicit `immediate_files` scope. It avoids
entering raw subtrees, reports selected-file capacity separately from unknown
whole-folder capacity, and requires completed scope-bound receipts before the
pilot. The per-file 64 MiB and all other compression bounds remain unchanged.

### September 9 overnight recovery armed

**Prepared and armed at September 8 20:43 Toronto; capacity outcome pending.**
The owner explicitly requested plan review, overnight arming and a second audit.
The [one-night controller](../../operations/storage-recovery-night.md) now owns
attempt `capacity-20260909-a2` through an immutable plan and two one-shot tasks.
This supersedes the daytime closeout's then-current absence of a recovery schedule.

| Segment | Start, September 9 Toronto | Absolute controller deadline | Scheduler backstop |
| --- | --- | --- | --- |
| Early | 00:30 | 04:42 | 254 minutes |
| Late | 06:45 | 08:55 | 134 minutes |

The 04:45-06:45 gap preserves the existing 05:00 CLOB projection and 06:00 raw-tape
tiering tasks. Their immediate filenames `order_books_long.csv` and
`order_books.jsonl` are excluded from this controller's planning and ledger.
No original recurring task definition changed. Both new tasks use S4U/Limited,
wake enabled, IgnoreNew, hidden execution, battery allowance and no late catch-up.

Execution is frozen at `1c96f162f2e9aab0afa53326173f8aec8b441a73` in the
isolated `weather-capacity-night-20260909-a2` checkout. The plan names ninety
exact cold-date groups: July 8-August 9, June 1-30 and May 5-31, each across
the twelve built-in event folders. Missing or incomplete inventory receives
zero capacity credit. Inventory and compression remain bounded to the qualified
immediate-file lane; no candidate capacity is inferred from the folder list.

The complete controller/retained-file matrix passed 472 native Windows tests at
`0faf9b8a4eb661f6aaff14d5cf4fb728b7143529`. The final registrar-only repair
passed 22 native checks, including both segment registrations using Windows'
normalized ISO durations, altered-limit rejection, owner identity and nested
child-tree containment. Exact execution-source
[full CI](https://github.com/michaelbooth1/weather/actions/runs/34295624213)
passed 4,725 tests and 921 subtests, with 342 skips;
[host-hook CI](https://github.com/michaelbooth1/weather/actions/runs/34295624226)
also passed. Workstation-local ignored JUnit evidence:

- `scratch/night-final-0faf9b8a4.xml`, SHA-256
  `0ef18a42bc14db0ae96fda6d1d392ded4f9d4c6820e88f651bdac60305ad9ce8`.
- `scratch/night-normalized-duration-1c96f162.xml`, SHA-256
  `422b05b08c60eed8cfc56427d38e5a52ec4531f18888bae65453c8b7b0405fb2`.

The actual S4U preflight passed at 20:37:29-30, validating the full source,
plan, native owner/host, baseline hashes and all 2,040 baseline identities, with
zero source payload reads or changes and proved complete teardown.
The subsequent independent audit rechecked every new task against retained XML,
future trigger times, exact source/plan bindings, untouched baseline files,
unchanged original schedules and all three native capture process identities.
All three workers remained AboveNormal; no recovery process was running before
the night. Production master stayed `6714b77d8bb57fa36b4d2dd33675cab971ef2432`
with only the two pre-existing generated-config changes.

Production-local ignored evidence:

- `scratch/handoffs/capacity-night-plan-20260909-a2.json`, SHA-256
  `54730c7559c0604b1fd75f3d5939ae55210b5eacfb48a53c739b6314751ca903`.
- `scratch/storage_recovery_nights/capacity-20260909-a2/preflight/wrapper-result.json`,
  SHA-256 `90d040da793b162785210cf3155d6d4dfce401a7c981a42c553c7a5f2bdcf502`.
- `scratch/handoffs/overnight-20260909-preparation-audit-03.json`, SHA-256
  `3b89e2a247dcb3b0efa46a49b690025cb353c44838f26a3118c55365aab5154f`.
- `scratch/handoffs/overnight-20260909-armed-bindings-a2.json`, SHA-256
  `db8f74fc8a22154b17729b1784c526843b84c7a9ed4ac52a29ca1aea46022d16`.
- Per-task intents, registered XML and PASS readbacks under
  `scratch/storage_recovery_nights/capacity-20260909-a2/registration-*`.

The first registration attempt, `a1`, rejected the equivalent Scheduler
duration `PT4H14M` because its source compared text with `PT254M`. Its exact
never-run early task is disabled, its late task was never created, and its
plan/source/preflight remain intact. The retained
`scratch/storage_recovery_nights/capacity-20260909-a1/failed-registration-closeout.json`
proves that the only task-XML change was Enabled=false. The repaired registrar
compares duration values and preserves the intended limits.

At 20:43 C: had **20.43 GiB free** and commit was **69.36%**. The controller
requires three stable samples below 66% commit with at least 4.5 GiB physical
availability before dispatch; children retain the existing 70% / 4 GiB gates.
Only known memory interruptions or a busy lease with safe teardown can resume
automatically, after complete file reconciliation. Unexpected failures stop.
This may limit throughput; preparation does not guarantee the capacity target.

The baseline remains 14,900,555,776 newly reclaimed bytes. The plan seeks the
original cumulative 120 GiB and actual 100 GiB free; **no additional overnight
bytes are claimed by this preparation**. After execution, reconcile both segment
results and ledgers, account for independent tiering only from its receipts,
and publish actual free space and remaining work. PR 44 remains queued; no
production merge, capture restart, live operation or source deletion was performed.

### Production pilot and resource-limited expansion, September 8

**Closeout at September 8 17:48 Toronto: PARTIAL, target unmet.** The
attended run verified **14,900,555,776 newly reclaimed bytes (13.88 GiB)**
across **2,040 retained files**. C: had **26,987,237,376 bytes free
(25.13 GiB)**. The earlier overnight 16.04 GiB and all fixture savings are
excluded. No source file was deleted.

| Target date | Verified files | Newly reclaimed bytes | Eligible immediate-file selection |
| --- | ---: | ---: | --- |
| July 1 | 281 | 2,118,795,264 | Complete |
| July 2 | 276 | 2,156,941,312 | Complete |
| July 3 | 273 | 2,033,250,304 | Complete |
| July 4 | 289 | 2,152,722,432 | Complete |
| July 5 | 279 | 2,085,097,472 | Complete |
| July 6 | 264 | 1,601,503,232 | Complete |
| July 7 | 289 | 2,163,539,968 | Complete |
| July 8 | 89 | 588,705,792 | Partial; 202 remain |

Completeness refers only to the qualified selection: immediate ordinary cold
JSON/JSONL/CSV files within the 64 MiB bound and the planner's 1 MiB floor.
Nested raw content, larger files, recent writes and other exclusions remain
untouched; whole-folder capacity and archive deletion eligibility are unproved.

Execution source `2c704c94d4acf1e5cb735a7a9d765b163cbfd6f3` passed **385
native Windows checks**, including actual interrupted compression followed by
read-only verification, plus [full CI](https://github.com/michaelbooth1/weather/actions/runs/34270368930)
and [host-hook CI](https://github.com/michaelbooth1/weather/actions/runs/34270369013).
The admitted workstation session ended at exit zero. Its ignored JUnit file
`scratch/capacity-retained-native-2c704c94d.xml` has SHA-256
`30325b2629376520317b8f23361f61c4d42d322d2a4a712065343af67aedeba8`.
Later documentation commits are not the execution identity of these receipts.

Repeated transient host commit above the unchanged 70% gate stopped batches,
including the final short attempt at 70.0445%. All wrapper teardowns were proved.
Six files whose compression preceded an interrupted post-hash check passed the
qualified [read-only verifier](../../operations/cold-snapshot-compression.md#read-only-verification-after-interruption).
Their original allocation savings are counted once; each verification command
reported zero newly reclaimed bytes and zero source files changed. Completed
journals inside failed attempts were counted only after exact fresh-inventory
identity/allocation reconciliation. No unmatched preimage or unverified
compressed file remains, and all spent attempts are preserved.

The final July 8 inventory reconciles all 89 completed file identities. Its
immediate-file allocation fell from 4,710,765,552 to 4,122,059,760 bytes, exactly
matching the 588,705,792 verified bytes above. At 17:48 all three capture
lock/process identities passed, their heartbeats were under 47 seconds old,
commit was 62.55%, and available physical memory was 6,393,008,128 bytes.
This is a point-in-time health observation, not a graded capture-day claim.

The production-local ignored evidence is:

- `scratch/handoffs/capacity-recovery-closeout-20260908.json`, SHA-256
  `deda3b5f023e131d4cd8f6ba9d3eea2c714a1900aecbc4531882ade0da842db3`: totals, per-attempt reconciliation, final admission and resume requirements.
- `scratch/handoffs/capacity-recovery-verified-files-20260908.json`, SHA-256
  `8fb61a1efa67620d50eb43ad28107dc246222bcc9b4334065c3d3647d29af3f1`: all 2,040 unique paths, content hashes, native identities, before/after allocations and original/verification attempt references.
- `scratch/storage_recovery_inventory/capacity-immediate-july08-20260908-04/wrapper-result.json`,
  SHA-256 `6cf87a944975c4f396b4dcde0692181e23d150ce306c88089a4899e246508b7a`.
  The closeout links the individual compression and verification receipts.

The owner-authorized helper cleanup was repeated at 16:03 after new idle
computer-use helpers appeared. Twenty-nine revalidated idle parent/child pairs
exited, accounting for 1,674,272,768 private bytes; Codex and excluded/active
helpers remained running. The create-only receipt is
`scratch/handoffs/codex-ram-cleanup-20260908-1600.json`. ProtonVPN's app and
both services were stopped; both services were still stopped at closeout.
The earlier 13:40 cleanup is retained below. These are RAM observations, not
disk-reclaim credits.

**Resume:** the target still needs 113,948,463,104 additional reclaimed bytes,
and free space remains below 100 GiB. No recovery process or recovery schedule
remains running. The September 8 exception and today's compression requests
expire at 18:00 Toronto. Use fresh ordinary 00:30-09:00 admission, a reviewed
execution source, new inventory and unexpired exact requests; recheck and
exclude the 89 completed July 8 identities before selecting its remainder.
Continue later cold dates through the qualified lane. Do not reuse spent
namespaces, count prior files twice, weaken capture/resource gates, or infer
deletion authority. The owner requested that the PR stay queued: production
master remains `6714b77d8bb57fa36b4d2dd33675cab971ef2432`, with no production
merge, capture restart, off-site upload or deletion from this recovery run.

The following earlier observations are retained as the sequence of evidence;
the latest disposition above supersedes their then-current pause/resume state.


At execution source `3426d5276f1d4c7db8ae70f945e2f2354bf01ed9`, the admitted
workstation run passed 332 native checks; full CI passed 4,644 tests and 921
subtests (321 skips). Native JUnit `scratch/capacity-scope-native-3426d5276.xml`
has SHA-256 `b0346b55ea7d16a19502136559e3d39068c587be681bb90c16e261985356182d`.
[Full CI](https://github.com/michaelbooth1/weather/actions/runs/34252429048)
and the Windows/Linux host-hook checks passed. These qualify source, not capacity.

The completed July 1 immediate-file inventory selected 4,566,156,272 allocated
bytes across twelve folders. Whole-folder capacity remains unknown. Its
production-local wrapper is
`scratch/storage_recovery_inventory/capacity-immediate-july01-20260908-01/wrapper-result.json`,
SHA-256 `a37c25f322b76e009280cffc437454b0dc5eb07e34a8f2960ae313d3f24bebc5`.

The Denver July 1 `replay_inputs.jsonl` dry run and apply passed. Apply reduced
allocation from 56,561,664 to 15,134,720 bytes, recovering **41,426,944 bytes
(39.5 MiB)**. Before/after content SHA-256 is
`cb1daf895425d6d60ad527e703468adbb0d37e6ced34a8a9fbe0f1f3c2ea81e4`;
native identity, timestamps and logical length were unchanged. The wrapper is
`scratch/cold_snapshot_compression/capacity-pilot-july01-apply-20260908-01/wrapper-result.json`,
SHA-256 `f493fb1d471df6a2cfaf7ee272d303fcdca6ddfd7637eed1b57e9a90992a26ed`.

The first 21-file expansion attempt stopped before mutation at 73.0% commit.
Its unchanged-request retry, `capacity-expand-july01-b00-20260908-02` under
`scratch/cold_snapshot_compression`, verified Austin and Atlanta July 1
`replay_inputs.jsonl` before stopping at **75.84% commit**. Their paired
`000-before/after.json` and `001-before/after.json` journals prove equal hashes,
unchanged identity/timestamps and allocation reductions of 39,391,232 and
38,793,216 bytes respectively. There is no third preimage or unmatched journal.
These additional **78,184,448 bytes (74.6 MiB)** are per-file verified evidence
inside a **FAILED_RETAIN_AND_INSPECT** batch, not a passing expansion receipt.
Do not count or select either file again without reconciling that attempt.

Post-partial re-inventory attempts
`capacity-immediate-july01-20260908-02` and `-03` both refused the unchanged
70% commit gate before inventory; every wrapper proved teardown. A simultaneous
native API comparison at about 13:04 measured 70.2152% with both
GlobalMemoryStatusEx and GetPerformanceInfo. Minute-old monitor samples around
66-68% therefore do not establish continuous admission. This is a measured
resource block; no threshold, capture identity, lease or deadline was relaxed.

At about 13:05, C: had **18,202,914,816 bytes free (16.95 GiB)**. The 120 GiB
new-reclaim / 100 GiB free target remains open. Compression is paused; no child
or recovery schedule remains running. Resume with fresh below-threshold
admission and a new completed inventory, reconcile the two verified files,
then prepare new exact requests from the same qualified execution source.
Later documentation commits are not the execution source of these receipts.
The September 8 token expires at 18:00; future execution uses the ordinary
admitted window or a new explicit owner decision. All source files remain;
there was no deletion, off-site upload, production merge or capture restart.


At 13:40 the owner-authorized shutdown of ProtonVPN and selective cleanup of
26 idle computer-use helper pairs restored headroom: the stopped processes
accounted for 2,124.4 MiB of private commit, and the 13:42 guard sampled 57.2%.
Codex, two preserved computer-use helpers, general code REPLs and all capture
workers remained running. The ignored receipt is
`scratch/handoffs/codex-ram-cleanup-20260908.json`; it records exact identities,
idle observations, retained helpers and unchanged service startup settings.

The new source-bound July 1 inventory `capacity-immediate-july01-20260908-04`
passed at source `1877039ceb60ac283e42d57ad2df4dc46f8c8a81` and reconciled the
three compressed files' native metadata and allocation. Its wrapper SHA-256 is
`d49db586599928414c921f3fd9813c8d70430bcd73c55b4c6f7ae70c771bd35c`.
The new Toronto July 1 `variant_predictions.jsonl` pilot dry run and apply
passed, recovering another 23,810,048 bytes with unchanged content and identity.
Apply wrapper `capacity-restart-july01-pilot-apply-20260908-01` under
`scratch/cold_snapshot_compression` has SHA-256
`1396bd0fb1db4e0dd197816e056bd464e385975e303a8642a0ddd02e0a2db0da`.

The subsequent `capacity-restart-july01-b00-20260908-01` batch verified twelve
files and 284,864,512 more bytes of reduced allocation before refusing
`capture_unhealthy:clob`. It has twelve complete before/after journal pairs,
no unmatched preimage, and proved teardown. Memory admission passed at 61.09%;
the reported CLOB heartbeat age was **-0.007398 seconds**, because the guard
sampled its comparison time before reading concurrently updated status files.

The correction samples the comparison clock after all status/identity reads
and evaluates the retained timestamps against that completed observation.
Future timestamps, the 180-second heartbeat and 900-second clean-iteration
limits, all resource bounds and identity checks remain strict. Regressions
cover publication during reads, genuinely future evidence and evidence that
becomes stale during reads. Requalify this changed source and create a fresh
inventory before reconciling the latest partial batch and expanding again.

## 2026-09-07 approved bounded cache compression

The owner approved the revised storage-reclaim plan and implementation of work
possible now. The production-local review is retained at
`scratch/handoffs/storage-reclaim-review-20260907.md`; it is ignored operational
evidence and is not assumed to exist in a clean checkout.

Immediate recovery now starts with the
[bounded replay-cache compression lane](../../operations/replay-cache-compression.md),
which preserves every path and logical byte. This does not authorize cache
eviction: the current full-key reachability and real rebuild gates in the
[retention policy](../../operations/data-retention-policy.md) still apply to
deletion, superseding any looser wording in the historical design below.

At September 7 14:32 Toronto, production had 29,009,707,008 bytes free (about
27.0 GiB). The two successful scheduled tiering receipts reported about 15.1
GiB reclaimed earlier that day; those completed candidates are not new reclaim
capacity. The old inventory's 32.3 GiB cache size is stale logical volume,
not measured savings. Twenty split CSV/gzip pairs remain deliberately retained.

The first implementation qualifies exact-request native compression with a
20 GiB capture reserve plus two bounded file images and receipt space, retains
the 00:30–09:00 window, shared lease, healthy capture, 4 GiB available memory
and commit below 70%, and caps requests at ten files / 512 MiB. Each file is at
most 64 MiB; actual production starts with one. Before/after hash, native
identity and allocation receipts are create-only. No directory compression,
deletion, automatic resume or decompression is provided.

Initial workstation qualification passed 69 checks including architecture,
native cache-reader parity, file/parent replacement exclusion and a 64 MiB
incompressible fixture. The fixture retained the same 67,108,864-byte allocation;
compression/read took about 0.64 seconds, with the test process observed at
about 53 MiB working set. This proves fixture compatibility, not production
savings or capture-host qualification. Later exact-head verification and the
pilot request are retained with the source publication evidence.

[Draft PR 39](https://github.com/michaelbooth1/weather/pull/39) publishes the
implementation. Native Windows verification at `77fb583f3e7796415306128cc6493de902b4942c`
passed 76 focused checks, including an actual NTFS plan/apply fixture with
immutable receipts and failed-attempt handling, schema registration and docs
audits. Production admission was simulated only in that workstation fixture;
no fixture result represents production reclaim. The canonical September 7
roll verdict is `ROLL-SENSITIVE` through the schema registry; production merge
therefore requires the quiet-window integration and recovery procedure.

The owner's subsequent pre-execution audit identified gaps in plan-to-apply
binding, actual-worker priority and launcher qualification. The revised lane
requires a hash-bound completed plan, verifies the OS-held lease, pins the
evidence directory during mutation and checks snapshot progress plus capture
process-creation identity. Native launcher failure, timeout and abrupt-exit
qualification belongs to this revision; earlier checks alone do not qualify
the updated source or authorize the production pilot.

At audit source `19be2b2737a0aaa41da01c6ecc1389301ccff5e0`, 106 native Windows
and architecture checks passed. This includes real PowerShell launcher and
native Job/lease tests for success, invalid result bindings, source/request
drift, timeouts, residual children and abrupt launcher termination. The test
clock, host assignment, mutex namespace and child payload are isolated
fixtures; the outer workstation admission and Job remain real. The native
compression tests separately prove bytes, plan binding and evidence-directory
exclusion. The audit corrected metadata-only directory handles after a native
rename negative test falsified their exclusion claim. The next production
attempt must use the revised runbook and exact current source, not the initial
implementation handoff's apply command.

The audit also verified the current daily tiering triggers at 05:00 and 06:00,
with PT31M/PT41M scheduler bounds and no late catch-up. Cache plan/apply now
refuses 04:45–06:45 and ends early enough to release its lease before that
reservation. This prevents the small pilot from making a larger scheduled
reclaim skip at a busy lease. Scheduler definitions were read, not changed.

- [x] Review previous archive/tiering work and native compression compatibility.
- [x] Implement bounded plan/apply and explicit retained-byte failure handling.
- [x] Complete exact-head publication and native failure-path qualification.
- [ ] Run the one-file production pilot under fresh overnight admission.
- [ ] Measure allocated savings before approving each bounded expansion.
- [ ] Scale verified off-site storage with production identity and dependencies;
  the prior one-log restore proof alone grants no production deletion authority.

No production reclaim was executed by this implementation entry. At 14:40,
the memory guard reported 78% commit, still above the ordinary 70% admission
ceiling. Time passage is not permission or proof that resource admission will
pass. Preserve the frozen mirror, all archive attempts and all trading evidence.

## 2026-09-08 overnight local tiering

The owner requested nine hours of hourly production audits, repairs and space
reclaim. Production source remained at `6714b77d8bb57fa36b4d2dd33675cab971ef2432`.
An early bounded run used the existing canonical projection-tiering wrapper
after a reviewed plan; the existing 05:00 projection and 06:00 raw-tape jobs
then ran on their unchanged schedule. All times below are America/Toronto.

| Run | Files | Original bytes | Retained gzip bytes | File-length reduction |
| --- | ---: | ---: | ---: | ---: |
| 02:05:57 early projection run | 4 | 5,061,200,633 | 218,928,763 | 4,842,271,870 |
| 05:00:02 scheduled projection run | 8 | 9,821,304,244 | 420,591,220 | 9,400,713,024 |
| 06:00:02 scheduled raw-tape run | 12 | 3,243,194,786 | 261,572,740 | 2,981,622,046 |
| Total | 24 | 18,125,699,663 | 901,092,723 | 17,224,606,940 |

These are the September 7 projection and canonical raw-tape files across the
twelve markets. The early plan selected Atlanta, Miami, New York and Toronto;
the scheduled projection job handled the other eight. Every action records
matching source/decompressed SHA-256 and line counts, passing cleanup
preflight, retained gzip and removal of only the verified uncompressed source.
Active or recently written files and split projection days were excluded.
The canonical raw-tape reader accepts the retained gzip representation.

The **16.0417 GiB file-length reduction** is distinct from allocation accounting
and concurrent volume deltas. The three wrappers measured volume increases of
4,796,256,256, 9,377,734,656 and 2,721,808,384 bytes respectively. All returned
zero with no hard stop, in 74.4, 166.7 and 202.8 seconds. The two scheduled
tasks independently reported successful completed runs and their next daily
triggers. This does not establish net overnight growth or week-long stability.

Production-local ignored receipt copies, relative to the repository root:

- `scratch/storage_reclaim/overnight-20260908-0205-before/`: prior projection reports.
- `scratch/storage_reclaim/overnight-20260908-0205-plan/`: early reviewed plan.
- `scratch/storage_reclaim/overnight-20260908-0207-apply/`: early apply and capture checks.
- `scratch/storage_reclaim/overnight-20260908-0503-projection/`: scheduled projection proof.
- `scratch/storage_reclaim/overnight-20260908-0604-raw/`: scheduled raw-tape proof.
- `scratch/handoffs/overnight-status-20260908-0803.json`: latest bounded host audit at this update.

The three retained apply JSON files have these SHA-256 digests, respectively:

- `cdf41ae7aea0acc4d236ac6651f3ba21733b6230fc37efae35cf7c43197023d4`
- `0c9d29fa21a56ad7321c3281667fa0bb3c0d3f8bee280b9e9e507882e87260b4`
- `c88471257f056d0982ffbc3bb1cff6e7530ca77d53011a14ac234e632b55df50`

These receipts are not distributed with a clean checkout. The hourly checks
through 08:03 show advancing snapshot clean iterations and zero consecutive
errors in all three capture loops; the execution-tape producer is connected
with integrity PASS, while complete price-path usability remains false.
No capture restart, source adoption, Scheduler change or live order occurred.

Free space fell to 8.7 GiB before the early intervention, reached 21.4 GiB after
the raw job, and was 20.2 GiB at 08:03. The separate reviewed replay-cache
compression pilot was not attempted: host commit remained above its strict
70% ceiling. Disk headroom also failed its reservation at several earlier checks.
No admission threshold was relaxed. This local lossless tiering does not prove
off-site durability, authorize retention deletion, resolve settlement gaps or
complete this item's sustained-capacity acceptance criteria. Continue the
verified offload work and preserve the paused mirror and spent attempts.

## Original design and measurements

Source: 2026-07-21 measurement on the production host (931 GB volume, 223 GB
free, 24%). Repository footprint 503 GB, of which `data/` is 466 GB:

| Subtree | Size | Files |
| --- | --- | --- |
| `data/snapshots` | 345.6 GB | 3,527,668 |
| `data/taker_runs` | 47.8 GB | 4,733 |
| `data/backtest` | 43.6 GB | 3,622 |
| all others combined | ~29 GB | ~164,000 |

`data/snapshots` is 74% of bytes and 95% of files, and is already organized as
one directory per market-day (`highest-temperature-in-<city>-on-<month>-<day>-<year>`,
562 present), so the market-day is a natural atomic retention unit with its date
in the name.

Measured per-day totals across all 12 markets: Jul 15 9.3 GB, Jul 16 13.0 GB,
Jul 17 9.0 GB, Jul 18 9.6 GB, Jul 19 26.0 GB, Jul 20 25.3 GB, Jul 21 16.2 GB
(partial). At the recent ~20 GB/day rate the free-space runway is roughly 11
days, so this item is time-critical even though no deletion is authorized yet.

Why this matters: the host cannot be grown, and capture cleanliness is the
critical path to the first release (Item 321 and the streak window). A full
disk stops capture, which is strictly worse than any storage cost. Retention
alone cannot solve it: a 45-day raw window at the current rate is ~900 GB,
larger than the whole volume, so per-day size reduction is mandatory alongside
retention.

Blocking prerequisite: the nightly `WeatherDataMirror` task currently runs
`robocopy /MIR`, whose delete-propagation makes the workstation copy a replica,
not an archive. Pruning locally under the present configuration would delete the
offloaded copy on the next run. Sync semantics must be split before any
retention policy is enabled.

## Design

Three tiers, with the market-day as the unit of movement:

- **Hot (production, raw).** The rolling window read directly by capture, the
  daily settlement chain, open barriers, and the point-in-time window. Sized by
  real consumers, not by convenience.
- **Warm (production, compressed).** Closed market-days retained locally as one
  compressed archive per market-day. Restores in seconds when a barrier resumes
  an older date. This also collapses the 3.5M-file count, which is itself a cost
  (enumeration, backup time, NTFS metadata).
- **Archive (workstation, append-only, compressed).** Every market-day ever
  produced, never deleted by a sync. Replay, backtest, and corpus work run
  against this tier on the workstation, which is where the memory and disk
  headroom already are.

Hot-window sizing must be derived from the longest real lookback, not guessed.
Known consumers: the point-in-time window needs 14 contiguous complete days
ending within 7 days (≈21 days), the maker-paper evidence window is 14 runs, and
observed barrier resumes have reached back several days (Jul 12 and Jul 14).
Minimum safe hot window is therefore ~30 days; the warm tier absorbs the rest.

Classification governs whether an artifact may ever be deleted without an
archive copy:

- **Irreplaceable:** market snapshots and observations. A market price at a past
  instant can never be recaptured. Archive forever; never delete unverified.
- **Evidence:** taker/maker run summaries, settlement tapes, ledgers, labels.
  Archive forever; prune locally only after settlement is final.
- **Regenerable:** replay caches, permission maps, feature stores, backtest
  outputs. May be deleted locally without archiving, and rebuilt on demand.

Deletion is gated on four conditions, all fail-closed:

1. the market-day is older than the configured hot window;
2. it is closed - settled, labeled, and referenced by no open barrier, queue
   entry, or active point-in-time window;
3. an archive copy is verified by manifest (file count, total bytes, and content
   hashes), not merely present; and
4. the deletion is recorded in a prune ledger carrying the restore pointer.

A restore drill must pass before any automated prune is enabled. An archive that
has never been restored is an assumption, not a backup.

## Scope

- [ ] Split sync semantics: keep the disaster-recovery replica separate from an
  append-only archive push (`/E`, never `/MIR`) into a distinct archive root.
  This must land before any retention policy is enabled.
- [ ] Investigate the 2.5x per-day growth step change (Jul 15-18 ~9-13 GB/day
  versus Jul 19-21 ~16-26 GB/day). Both spike days were operator outage days, so
  retry or duplicate-capture amplification is a plausible defect; if so, fixing
  it is the cheapest reclaim available and reduces every downstream tier.
- [ ] Derive the hot window from code rather than assumption: enumerate every
  production reader of `data/snapshots`, `data/taker_runs`, and `data/backtest`
  with its maximum lookback, and record the binding constraint.
- [ ] Build the market-day manifest and verification tool (file count, bytes,
  content hashes) plus a restore path, and prove both with a restore drill on a
  closed day before any deletion is authorized.
- [ ] Add per-market-day compression for closed days (warm tier), preserving the
  existing read paths through a restore-on-demand shim.
- [ ] Implement the four-gate prune with its ledger, defaulting to dry-run and
  requiring explicit authorization to delete.
- [ ] Never prune a market-day inside the point-in-time streak window or
  referenced by an open barrier; assert this in tests, not only in documentation.
- [ ] Dispatch the conservative cleanup already written in
  `docs/roadmap/agent-work-order-2026-07-20b.md` (duplicate and regenerable
  artifacts) as the immediate, no-new-mechanism reclaim.

## 2026-07-27 workstation storage-pressure build

The build-only slice in
[the workstation storage-pressure report](../agent-report-2026-07-27-workstation-storage-pressure-build.md)
adds three guarded mechanisms without authorizing production mutation:

- future full-book long-CSV capture is controlled by a checked-in policy whose
  default remains `true`; malformed or missing policy preserves current
  capture;
- replay-cache cleanup is full-key reachability based, retains ambiguity, and
  requires frozen candidate static context, an exact retained serving-release
  graph, two cache-off rebuild parity checks, and a durable write-ahead receipt
  before an exact-file unlink; and
- closed-day projection tiering has a complete family registry but permits only
  `order_books_long.csv`, whose canonical source and gzip/JSONL reader fallback
  are fixture-proven.

All production dry-runs, approvals, compression, deletion, deployment, mirror
topology changes, and restore drills remain operator-owned and not done. This
does not close the broader archive-offload item or change any scope checkbox
below.

## 2026-07-29 measurement: do the warm tier first

Host at 146 GB free, falling 15.7 GB/day (~9 days). Retained `data/snapshots` is
**8.88 GB/day** (Jul 27) and 8.99 GB/day (Jul 20) across 12 markets — steady, and
almost entirely canonical evidence, so no cleanup can touch it.

Gzip level 6 over the uncompressed files >5 MB of one closed market-day
(`atlanta-on-july-20`): **0.65 GB -> 0.05 GB, 14.3x.** `order_books.jsonl`
292->28 MB (10.5x), `clob_tokens.jsonl` 81->1 MB (74x), `replay_inputs.jsonl`
54->4 MB, `variant_predictions.jsonl` 51->4 MB, `order_books_summary.csv`
46->4 MB. Ordered by reclaim across 12 markets, `order_books.jsonl` alone is
3.2 GB/day and the top two families are 55% of the win.

This reorders the scope above. **The warm tier is not gated on the sync split**:
compressing closed market-days in place is not a deletion, so it needs no archive
verification, no prune ledger, and no `/MIR` topology change, and it is reversible.
It should take retained snapshots to roughly 1.3 GB/day and is a large one-time
retroactive reclaim. The sync split still gates every *deletion* and remains the
prerequisite for the archive tier.

The real blocker for the warm tier is reader coverage: the projection-family
registry marks 16 of 17 families ineligible with *"Direct gzip readers not all
proven"*. The compression mechanism already exists in
`closed_day_projection_tiering`; the work is proving the gzip read path per family
and flipping eligibility, which makes it incremental and safely interruptible.

Two corrections to earlier assumptions, both from measurement:

- `capture.write_order_books_long_csv=false` is **not** a disk fix. Tiering already
  compresses that projection 25x (1.44 GB -> 57 MB per market-day), so the flag is
  worth ~0.7 GB/day retained, not ~17 GB/day.
- `data/backtest/replay_cache` (32.3 GB, untouched since 2026-07-11) is **not**
  reclaimable: `storage_classes.py` gates it on
  `reviewed_exact_path_reachability_manifest` and states *"age and LRU are never
  deletion evidence"*. That manifest needs the active release pointer, and
  `artifacts/releases` does not exist on this host.

## 2026-07-29: a fourth tier (2 TB Google Drive), and what it can and cannot be

Exact figures from the 04:30 mirror log, which reports the whole replicated tree
without needing a scan: **531.805 GB, 3,785,460 files, 53,469 dirs.** That run
copied **39.476 GB** and purged **15.927 GB** of extras.

Two numbers govern every offload decision, and both rule out the obvious plan:

- **File count.** 3.79M files. A per-file cloud sync of that tree costs days of
  pure metadata round-trips on every pass, forever. The market-day archive
  (562 objects) is the only viable unit — so the warm tier is a **prerequisite**
  for any cloud tier, not an alternative to it.
- **Churn amplification, 4.4x.** 39.476 GB copied for ~8.9 GB of genuinely new
  retained data, because `order_books_long.csv` and its siblings grow all day and
  re-copy whole. A cloud target suffers the same amplification with no delta
  transfer. Therefore **only sealed (closed *and* tiered) market-days are ever
  pushed**, which makes the cold tier append-only by construction and sets upload
  volume to the retained rate rather than the churn rate.

Capacity arithmetic on 2 TB:

| what we push | initial | daily | 2 TB lasts |
| --- | ---: | ---: | ---: |
| raw tree as-is | 532 GB | ~10 GB | **~5 months** |
| sealed compressed market-days | ~70-120 GB | ~1.5-2 GB | **~3 years** |

So 2 TB is either barely a stopgap or multi-year headroom, decided entirely by
whether we compress first. Compressed is also the only version that fits a home
uplink: ~2 GB/night is minutes, whereas 39.5 GB/night never converges.

Tier 4 (cold, off-site) therefore reads: **one verified compressed object per
sealed market-day, pushed by `rclone` through a `crypt` remote, verified with
`rclone cryptcheck`.** Encryption is not gold-plating here — raw capture payloads
can embed provider API keys in request URLs and headers, and an upload to a
third-party service cannot be recalled, only rotated. A `crypt` remote closes
that question structurally instead of relying on a scan being exhaustive, and
`cryptcheck` satisfies gate 3's "verified by manifest, not merely present".
Cost acknowledged: no server-side dedup or preview, and the crypt passphrase
becomes load-bearing for a *copy* (never for the original).

Drive must **not** be a mirror target, a working tier for replay/backtest, a git
remote, or a `.git` host. It **should** carry the ~382 MB model artifacts that
exhausted the metered Git LFS quota, which is a clean, small, immediate use.

This does not reopen the durability agenda, which is deliberately deprioritized
until the model is profitable. The cold tier is being specified as **capacity
relief**, and it stays behind the sync split like every other deletion.

### Mirror scope is a separate lever from retention, and it was free

`WeatherDataMirror` ran a bare `/MIR` of all of `data/`, including
`data/backtest/replay_cache` — **32.28 GB / 770 files** of cache that
`storage_classes.py` classifies as rebuildable. Nothing requires a rebuildable
cache to be *replicated*; it is not archive payload. Excluded it via `/XD`
(2026-07-29), which is 3x the workstation's then-current 9.7 GiB admission
shortfall, recovered with no compression, no network, and no deletion of
canonical evidence. `/XD` skips the directory rather than purging it, so the copy
already on the workstation needs one explicit deletion there.

Next-cheapest compression family found while measuring: **10.67 GB of loose
analysis output at `data/backtest` root** (2,417 files; 4.86 GB `.csv`, 2.47 GB
`.pkl`, 1.94 GB `.jsonl`), untouched since 2026-07-11 — entirely cold and highly
compressible, but outside the closed-market-day family registry, so it needs its
own eligibility proof rather than an improvised one-off.

## 2026-08-02 first real dry run: the warm tier is blocked on the event-day manifest, not on reader coverage

First production dry run of `closed_day_projection_tiering plan` (`--as-of-date 2026-08-02`).
Read-only; wrote only to a review root outside `data/`. Result:

| Metric | Value |
| --- | ---: |
| Folders evaluated | 706 |
| **Eligible actions** | **0** |
| Blocked folders | 706 |
| Planned source bytes | 0 |

Blocker frequency across all 706 folders:

| Count | Blocker |
| ---: | --- |
| 661 | `order_books_long_csv_missing` (already tiered — benign) |
| 657 | `event_day_manifest_missing_or_invalid_json` |
| 93 | `canonical_order_books_jsonl_missing` |
| 48 | `event_day_manifest_current_validation_blocked` |
| 48 | `event_day_manifest_not_finalized_pass` |
| 12 | `event_day_is_not_closed_before_as_of_date` (today — correct) |
| 12 | `order_books_long_recently_written` (today — correct) |
| 1 | `event_slug_has_no_target_date` |

Isolating the 45 folders that actually hold a plain `order_books_long.csv`:

- **32 closed days whose *only* blocker is `event_day_manifest_missing_or_invalid_json`;**
- 12 open days from today, correctly refused as not-closed;
- 1 is `observation_source_cache`, a non-event directory under `data/snapshots` that the planner
  reports as a blocked folder rather than skipping as out-of-scope.

**Root cause.** `event_day_manifest.json` exists in **48 of 706** folders. Every one was written
`2026-07-11` and covers only June 6-9 (12 markets x 4 days) — and all 48 fail
`event_day_manifest_not_finalized_pass` *and* `event_day_manifest_current_validation_blocked`.
**No folder anywhere in the tree carries a finalized-PASS event-day manifest.** No manifest has been
generated since 2026-07-11.

**This corrects the 2026-07-29 entry above.** That entry named the real blocker as reader coverage —
"the projection-family registry marks 16 of 17 families ineligible" — and framed the work as proving
the gzip read path per family and flipping eligibility. That is a real constraint but it is **not the
binding one**. `order_books_long` is already eligible and already fixture-proven, and it still plans
zero actions. Proving the other sixteen families changes nothing while the manifest gate is
unsatisfied for all 706 folders. **The binding constraint is the event-day manifest pipeline.**

What is actually sitting there, measured the same day:

- **44 plain `order_books_long.csv`, 25.44 GB untiered**, against 588 already-tiered `.csv.gz`
  totalling 21.78 GB.
- **~17 GB of that backlog is 2026-08-01 alone** — twelve markets at ~1.4 GB each. At the measured
  ~23x this is ~16 GB reclaimable from one day of one family.
- **20 of the 44 have both a plain and a gz half.** These are the split-projection days: disjoint
  halves where a gz-first reader silently gets a partial day. They are not ordinary tiering
  candidates and the plain half must not be deleted. Any automation must exclude them explicitly.

The provenance of the existing 588 `.gz` files is **not** established by this dry run. Something
tiered them, but it was not this gated path, which has never been able to emit an action. Do not
assume the two are the same mechanism without checking.

Revised ordering for the warm tier, replacing the 07-29 framing:

1. Fix the event-day manifest pipeline: find why generation stopped after 2026-07-11 and why the 48
   that exist are not finalized-PASS. Nothing else in the warm tier can move until this does.
2. Re-run this dry run. Expect ~32 closed days to become eligible, worth ~25 GB.
3. Only then consider cadence (a scheduled plan/apply for the already-eligible family), with split
   days excluded.
4. Reader coverage for the other sixteen families remains genuinely open, but it is step four, not
   step one.

Automating an apply path is deliberately gated behind operator review by the design above, and it
would touch `src/**` or `scripts/**`, making it roll-sensitive. **Not before the release-#1 lock.**

## 2026-09-10 verified cold-archive foundation

The workstation build adds the fixture-only
[Verified Cold-Archive Foundation](../../operations/verified-cold-archive.md).
It now provides a deterministic one-day planner, one create-only deterministic
archive object plus a self-hashed sidecar, append-only object/member
verification, a traversal/link-safe exact-parity restore drill with a durable
receipt, and a reviewed cleanup-manifest generator with no delete executor.

The selection gate requires a current event-day manifest, no shared external
payload dependencies, a minimum 30-day hot window, final settlement and closure,
no open barrier/queue/point-in-time reference, stable non-reparse files, no
writer lock, and exact parity for split plain/gzip representations. Adversarial
tests use only synthetic `tmp_path` fixtures and cover determinism, collisions,
drift, manifest tampering, truncation, traversal, links, duplicate members,
restore mismatch, stale/open dates, and cleanup-plan gate failures.

This completes the build-and-test foundation, not the production scope checkbox.
The command surface refuses unmarked roots and repository `data/`. Production
still needs a source-of-truth selection-proof adapter, encrypted append-only
`rclone crypt` transport with `cryptcheck`, operator credential/OAuth setup,
mirror-topology separation, a real restore drill, and separately reviewed prune
ledger/execution work. Raw capture can contain sensitive request material and
must never be uploaded unencrypted. `/E`-equivalent append-only copy semantics
remain required; `/MIR` and destructive `rclone sync` remain forbidden.

## 2026-09-11 provisional workstation encrypted staging adapter

The next build-only slice adds the default-off
`weather.operations.workstation_cold_archive_stage` module and admits only that
literal module through the existing workstation-heavy `weather_heavy` lane.
It accepts one regular, non-reparse, operator-pinned provisional mirror file up
to 1 GiB; creates one deterministic normalized single-member `tar.gz`; and
stages it through an already configured encrypted rclone config whose named
crypt remote must wrap the exact explicit local ciphertext root.

The adapter recovers the DPAPI CurrentUser-protected config password only in
process and passes it only as `RCLONE_CONFIG_PASS` in a private bounded-child
environment. It uses no shell or password argv, permits no destructive rclone
verb, refuses a pre-existing local object, manifest, receipt, archive ID,
logical remote destination, mapped ciphertext, or retained partial, and runs
one-transfer/one-checker immutable copy plus `cryptcheck`. Exact before/after
ciphertext inventory and source rehashing gate create-only self-hashed manifest
and receipt publication. Failure after a copy attempt retains the encrypted
state and writes `FAIL_CLOSED` evidence rather than retrying or cleaning it.

Fixture-only adversarial tests substitute DPAPI and rclone behavior. No real
mirror data, production data, config, key, credential, remote, Drive target,
restore, cleanup, or delete operation was accessed. Every receipt is permanently
`production_identity_not_proved=true`, `cleanup_eligible=false`, and
`deletion_authorized=false`, and the module contains no deletion executor. The
schema additions are additive-only; because `schema_registry_data.py` belongs
to every live capture closure, this branch remains roll-sensitive at production
merge.

This does not complete a production scope checkbox. A separately authorized
run must still bind authoritative production selection, perform real encrypted
off-site transfer, complete and review a restore drill, split mirror semantics,
and add the independent prune ledger/executor before any source can become
deletion-eligible. The intended real source remains deletion-ineligible.

## 2026-09-05 takeover and encryption preflight repair

The owner authorized continuation of off-site storage and necessary changes,
with no live trading. This supersedes the historical build-only authority
limits above; authoritative selection, host admission, immutable attempts,
encrypted transfer, independent restore, and exact-file prune-ledger gates
still apply before source deletion.

The inherited `real-pilot-clob-console-20260713-v1` attempt is spent. It failed
at DPAPI recovery before ciphertext creation and remains preserved with its
source, plaintext staging and failure receipt. It proves no off-site restore
or production-source parity, and none of its bytes is deletion-eligible.

The repair checks DPAPI access and encrypted local destination binding before
source reads or compression. It rechecks supporting identities and destination
binding after compression, retains numeric-only native errors, and adds real
Windows ASCII/Unicode fixtures alongside failure-ordering and drift coverage.
Independent review found no remaining actionable issue. Exact-source admitted
workstation verification passed 51 tests and failed two positive fixtures in
PowerShell protection before the Python loader ran. The separate archive and
documentation ratchets passed 48 tests; changed Python files compile and the
agent-document audit passes. The full native positive-fixture gate remains open.

Run the unchanged native fixtures from the attending user's ordinary workstation
session to distinguish session access from loader compatibility. No real secret
reprovisioning, new upload, restore, or source deletion was performed in this
takeover. Do not infer a corrupt retained blob from the fixture's protection
failure. Continue with a wholly new reviewed namespace only after that gate
passes. The provisional adapter still has no production delete executor.

Acceptance:

- Free space on the production volume trends flat or upward across a full week
  of normal capture, with no manual intervention.
- Every deletion is traceable to a verified archive copy and a ledger entry, and
  a restore drill has been executed and recorded.
- Capture, the daily chain, and barrier resumes complete unchanged for every
  date inside the hot window, and any older date can be restored on demand.

## September 9 production-chunk transfer qualification

The owner requested at least 100 GB of verified Drive offload followed by local
reclaim, and approved the exact July-plan 20 GiB reserve exception. The retained
selection contains 5,584 files with 111,275,511,800 measured allocated bytes.
Those historical allocations are a candidate estimate, not reclaimed space.

The implementation is published at
d8bdb7111992cf0847ba1852ff2cf51a1a4e89d0 on
codex/bulk-cold-archive-20260909, [draft PR 45](https://github.com/michaelbooth1/weather/pull/45).
It adds native-pinned production staging, encryption of copied archive chunks,
private Drive transfer with independent ciphertext/metadata downloads, and
complete workstation plaintext restoration. The
[production archive runbook](../../operations/production-cold-archive-staging.md)
owns commands, schemas, reservations and proof limits.

Independent review corrections keep the active encrypted client configuration
and downloaded files pinned through terminal receipt, require complete upstream
encryption/production proof, and refuse infeasible transfers before upload.
At 8 MiB/s network and 16 MiB/s hashing, a maximum-size incompressible object
cannot fit the combined 300-second transfer. A separately qualified split
transfer or other bounded strategy is still required for such objects.

Native workstation evidence, retained under production scratch/handoffs/:

| Receipt | Result | SHA-256 |
| --- | --- | --- |
| archive-transfer-qualification-a1.xml | 224 cases: 215 pass, 7 test assertion failures, 2 skips | fc29044ace24e239220c9d14cdc45819aec6bb27ea0d0d231d7302724d05e182 |
| archive-transfer-qualification-a2.xml | 18 pass, zero failures/skips | 828130b67a51eb2bfb1ab3216da47fbed309f4f98292ae7a6295504a19e4876a |
| bulk-transfer-source-a2.json | Exact clean source and wrapper-dependency hashes | ba8f054d9e1f9b297cae060ff17059ff579bfdaa73cc156e850e4b822ef1a806 |

The seven failures were correctly rejected invalid inputs whose tests expected
ValueError instead of the existing typed archive exception. Only those test
assertions changed. Follow-up included every affected case plus installed-rclone
encryption/cryptcheck/decryption, native file pins, exact source/import identity,
compilation, PowerShell parsing and the documentation audit. The wrapper's
workstation invocation exited zero after the follow-up.

Drive setup separately proved a private app-created-files target and an 86-byte
native upload/download hash match. This establishes client connectivity only;
it is not production archive transfer or disaster-recovery proof. The retained
connection receipt is archive-drive-connection-verified-20260909.json,
SHA-256 6a4ff1e28e28165dc3d2be00d7e60928c9e2635a10d46d16c191100f77802003.

Production archive payload upload, full production restore, consumer closure,
fresh deletion identity and reclaim remain unproved. Raw token files also feed
scheduled Parquet provenance hashing; replay backfill enumerates all history;
settled-folder discovery can silently omit folders after required-file removal.
Even all available older July 1-8 allocations plus the July 16-31 raw token
family fall below 100 GB. A verified off-site availability contract must preserve
discovery and make historical restore requirements explicit before local
deletion. Current capture and hot-window daily behavior must remain available.

The split transfer implementation at 05188a2fe3c5bf4af58fbc13aa4f0451cba26ace
was subsequently checked on the workstation: 224 checks passed, covering both
phases, remote-object identity changes, source/plan membership, wrapper teardown,
schemas, compilation and documentation. The one remaining harness assertion
expected roadmap regeneration to leave Git clean; the generated file changed
only its timestamp. That generated update is included, and final validation
uses the generator's check mode. The retained archive-transfer-qualification-a3.xml
has SHA-256 96dcae13e48f806bf1e36e2541832c9489f003c9ccf6bb34b96d489aaba50340.

Separate upload and download jobs retain the 300-second limit, 8 MiB/s network
rate and 16 MiB/s hash rate. Each split job budgets one hash and one copy;
upload-only can never satisfy independent recovery. The reviewed staged
manifest must match the actual plan's exact source-member identities.

A read-only Drive metadata probe also succeeded with its encrypted config
pinned against replacement. Both source and attempt configs stayed unchanged;
the client reported a config-save warning but the lookup succeeded. No remote
object was created. The receipt archive-drive-pinned-config-check-20260909.json
has SHA-256 2db846d9e5255b32aa7aaaace09bb57aaa2c896b3cdb5f8bd27002d14df93957.
This is one observed client behavior, not production payload or restore proof.

## September 9 revised target for owner validation

After accepting restore on demand, the owner required selection of the least
frequently needed practical archive target and an explanation for validation
before any upload. The blanket July 16-31 selection above is superseded as the
current recommendation, while its plans and receipts remain historical evidence.

The preferred target is specific June 15-July 30 files across twelve markets:
2,154 paths with 101,760,323,584 recorded allocated bytes (101.8 decimal GB).
Market-detail history contributes 79.1 GB and full variant prediction JSONL
22.7 GB. The seven actual primary families are clob_tokens.jsonl,
variant_predictions.jsonl, order_books_long.csv.gz, price_history.csv,
market_ws.jsonl, order_books_long.csv and order_books.jsonl. Each original is
retained independently; CSV, JSONL and gzip representations are not assumed
interchangeable or safely rebuildable.

The separately bound reserve contains 552 snapshot_explanations_long.csv files,
10,238,812,160 recorded allocated bytes. Retain it unless final primary
allocation or protected-input exclusions leave the verified reclaim below
100,000,000,000 bytes; use only the oldest qualified reserve needed and only
after the owner validates that reserve. Primary validation does not authorize
the whole 112.0 GB pool. The original July plan's 20 GiB reserve exception does
not automatically apply to this replacement; staging/headroom feasibility must
be reviewed under the applicable floor.

Keep original weather/source payloads and their shared dependencies, snapshot
records, replay inputs, components, settlement/labels/control metadata, snapshot
tables, permanent token-map CSVs, book summaries, compact variant CSVs and raw
explanation JSONL local. Keep existing Parquet/reports, all July 31 onward data,
maker/taker/execution evidence and replay caches. Protect any current selected
event, repair or explicit research dependency even if its date is older.

This ranks likely demand from source readers and inspected Scheduler/config
state, not measured per-file access frequency. Stage-A legacy historical
scoring reads retained snapshot tables; current-day scoring uses retained
variant CSVs. Full variant JSONL still supports residual/parity research,
and the reserve explanation CSV has a direct historical root-cause reader.
Parquet provenance and all-history maintenance also need archive handling.
Neither age nor retention of a related format proves reader compatibility.

The comparison covers 18,058 immediate files in 564 complete market-day
selections, with 249.0 GB of recorded allocation. June 15-30 and July 9-15
received new admitted metadata inventories; the other July observations date
from September 8/9. The proposal excludes 520 recently modified book gzip
files (8.3 GB). All selected files meet the retained modification cutoff and
1 GiB whole-file bound. A later refresh was refused by snapshot-health
admission; it contributes no new capacity. An incomplete June 3 sample is
excluded. No production source payload was read for this target comparison.

The implementation must preserve a local availability catalog and resolve a
job's complete dependencies before execution. Archive by market/date/file
family in bounded parts; restore only required inputs with full verification,
reuse a bounded protected cache, and make housekeeping preserve valid complete
projections. Never silently skip archived history, repair it repeatedly, or
publish a partial historical population. Fresh source identity/allocation,
current consumer selections, complete independent restore and a qualified
exact-file deletion executor remain prerequisites to reclaim.

Bound proposal artifacts are production-local ignored review evidence under
scratch/handoffs/; they need not exist in a clean checkout. Their status is
PROPOSED_FOR_OWNER_VALIDATION_NOT_UPLOAD_AUTHORITY and every mutation gate is
false:

| Proposal | Files / recorded allocation | SHA-256 |
| --- | --- | --- |
| archive-target-primary-20260909.json | 2,154 / 101,760,323,584 bytes | d47eec8ff7fbd500c720a273339729cb9f8f75eb84be615082d9d39e2b22b927 |
| archive-target-standby-20260909.json | 552 / 10,238,812,160 bytes | f9053f2acca392ddad37d3afb72a2643dbf1b727dcc297c0cde329de8ddb034c |

Both bind parent archive-target-proposal-a2-20260909.json,
SHA-256 05da0e19623530f93382d4f8c6ea8757e85090d69c441025119de1f29b6011f1,
and comparison archive-target-metadata-comparison-a3-20260909.json,
SHA-256 95522eec2630f1ea5a2c071245121038f6a2e0d6511e19f6278745162e3d3d1e.
The owner-facing explanation is archive-target-recommendation-20260909.md.

Source qualification at 3160122d1c09c76a8aea0074e0d0e65dc36b76b5 passed final
workstation checks, CI 660 and host-load hook 27. These prove the existing
bridge, not the proposed reader workflow. The revised target awaits owner
validation. Production payload uploaded, files deleted and space reclaimed
remain zero.
