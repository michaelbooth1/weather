# 323. Shared Forecast Payload CAS And Single-Fetch Fan-Out [PARTIAL 2026-07-15 - CONTROLLED STORAGE HOUR PASSED; HARDENING ON ISOLATED BRANCH; LIVE NETWORK PROOF AND REAL-ROOT INVENTORY PENDING]

Goal: store one verified copy of a market-invariant raw forecast response and
fan it out through point-in-time per-market manifests, so replay provenance is
preserved without multiplying national payload bytes by market count and
capture cadence.

Owner/package: weather.collection, weather.sources, weather.operations, weather.reporting

Source: the 2026-07-13 12-hour runtime-monitor incident
`nbm-national-raw-payload-storage-amplification`. During its first controlled
hour, 123 new forecast blobs consumed 2.164 GiB and explained 56.3% of the
3.8439 GiB host disk loss. Each US market/capture stored the same approximately
35.16 MiB national NBM bulletin in a distinct market-local content-addressed
store. Hour 8 continued losing 3.3418 GiB/hour, confirming persistent storage
amplification rather than a one-off burst.

Across the complete 12-hour raw host sample, free disk fell from 381.8955 GiB
to 337.8235 GiB: 44.0721 GiB, or 3.6737 GiB/hour. Reconstructed Hour 12 alone
lost 3.0737 GiB. Those host-wide totals include other repository workloads and
are not wholly attributed to NBM; the byte inventory above is the causal
evidence for this item. The sustained full-run slope nevertheless corroborates
the urgent storage-risk disposition, and no canonical payload, manifest,
snapshot, tape, or ledger was deleted during monitoring.

Why this matters: the observed host burn projects to roughly 80-92 GiB/day,
which can exhaust local operational storage even though the individual
payloads are immutable and hash-addressed. Ad hoc deletion is unsafe because
raw responses, per-market manifests, issue/update times, and hashes are
point-in-time replay evidence. Items 131 and 171 audit tracked artifacts and
generic retention, Item 190 owns NBM feature semantics and replay validity,
and Item 321 is the parent resource-isolation program; none implements
cross-market raw-payload deduplication or fetch fan-out.

## Design

1. Add a repository-owned shared forecast payload CAS, built with
   `weather.paths`, keyed by the verified raw-byte digest and independent of a
   market snapshot folder.
2. Keep per-market capture manifests append-only. Each row must retain its own
   capture time, source URL/issue metadata, target date, market context,
   extraction identity, payload digest, and a replay-safe reference to the
   shared immutable blob.
3. Permit single-fetch fan-out only for source adapters that explicitly attest
   that the raw response is market invariant for the same request/cycle key.
   Market-specific requests continue to fetch and persist independently.
4. Make shared writes atomic and concurrency safe on Windows. Concurrent
   markets writing identical bytes must converge on one verified blob; digest
   mismatch, partial write, missing blob, or corrupt blob must fail closed.
5. Preserve captured-input replay and train/serve parity. Reconstructing any
   market snapshot through its manifest must reproduce the same raw bytes,
   parsed source state, cutoff semantics, and feature inputs as the current
   market-local path.
6. Add created/reused blob counts, physical bytes written, logical referenced
   bytes, and avoided bytes to snapshot status, storage inventory, and runtime
   monitoring evidence.
7. Design migration and garbage collection as separate verified phases. Start
   with an inventory/dry run; do not remove a market-local blob until every
   referencing manifest replays from the shared CAS and restore/hash checks
   pass. Garbage collection must be reachability based, retention aware,
   auditable, and disabled by default.

- [x] Define market-invariant source/request keys and the shared CAS path and
  manifest-reference schema.
- [x] Implement atomic cross-process put/read verification with corruption and
  partial-write recovery tests.
- [x] Add NBM single-fetch fan-out and shared-blob reuse without changing
  market-specific capture timestamps or cutoff semantics.
- [ ] Prove captured-input replay, feature parity, and per-market lineage across
  the shared reference path.
- [x] Add logical/physical/avoided-byte observability to capture status,
  manifests, storage inventory, and runtime monitoring.
- [ ] Add a reviewed host disk-growth budget gate.
- [x] Implement a bounded inventory-only migration dry run with partial
  reachability, restore, hash, and replay proof.
- [ ] Design and review any apply/GC phase separately; perform no evidence
  deletion until it is explicitly authorized.
- [x] Complete a clean multi-market post-restart soak showing repeated national
  NBM captures reuse one shared physical object.

Acceptance: when all US markets capture identical raw NBM bytes for the same
declared request/cycle, exactly one verified physical blob is created while
each market retains its own append-only point-in-time manifest. Concurrent and
restart recovery tests preserve hashes and replay outputs; corrupt or missing
shared blobs fail closed; physical bytes written no longer scale with market
count; and no legacy evidence is deleted without a reviewed migration report
whose restore, hash, reachability, and replay checks all pass.

Verification:

- Focused snapshot-store, forecast-payload persistence, captured-input replay,
  path-policy, and Windows concurrency tests.
- A multi-market deterministic fixture proving one physical blob, multiple
  lineage-complete manifests, and byte-identical replay.
- A representative paper/capture soak reporting logical bytes, physical bytes,
  avoided bytes, disk slope, parse parity, and zero corrupt/missing references.
- `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`.

Related: items 131, 154, 171, 190, 289, 320, 321.

## 2026-07-13 implementation evidence

New NBM capture writes now attest the exact national request/cycle and separate
the invariant UTF-8 bulletin bytes from station/date extraction identity. A
repository-owned shared CAS publishes a completely flushed staging file by an
atomic same-volume hard link; concurrent writers converge on one digest path,
and missing, corrupt, symlinked, or size-mismatched blobs fail closed. Forecast
manifest v2 retains per-market capture time, market/date, request/cycle,
extraction identity, shared reference, and created/reused plus
logical/physical/avoided-byte evidence. Legacy/non-attested sources continue
using their market-local CAS.

The NBM adapter also has a bounded same-process request/cycle fan-out
coordinator. Completed responses are reusable only under an explicit capture-
pass scope; unscoped calls coalesce only concurrent in-flight work, so a later
same-URL request observes provider updates. Reused market rows retain the
original fetch, request-start, and response-received provenance and are marked
as fresh-cache reuse. Deterministic multi-market tests prove one scoped fetch,
one shared blob, distinct station parses, and byte-identical manifest replay.
Production fleet captures currently run in isolated child processes, so a
parent-prefetch or cross-process request receipt is still required before
claiming one network fetch per live fleet cycle.

The migration command is inventory-only: it verifies legacy local hashes and
replay, and verifies every scanned shared manifest's schema, request/cycle,
reference, path, hash, byte count, extraction identity, and replay before
counting it active. Its reachability output is explicitly partial to snapshot
forecast JSONL inventory; it exposes no global-unreachable or deletion
candidates and has no copy, rewrite, GC, or delete mode. Generic cleanup and
retention review gates hard-block shared-CAS deletion.

Event-day manifests now record each unique external shared-CAS dependency and
fail closed until both the off-machine backup and restore proof include its
exact path, byte count, and digest. The snapshot fleet status retains only
compact created/reused, logical/physical/avoided-byte, and budget scalars per
market plus a current-pass aggregate; the read-only runtime monitor projects
that bounded aggregate and can reconstruct it from older per-market status
rows. A reviewed disk-growth threshold, cross-process network-fetch fan-out,
and the controlled capture soak remain open. No local runtime evidence was
scanned or changed during this implementation.

Independent fail-closed review added three further proof boundaries. Shared
CAS candidates are classified against the canonical data root, so choosing an
inner cleanup `--root` cannot bypass the unconditional deletion block.
Event-day dependency records require the exact canonical CAS root plus digest
reference rather than accepting a matching external suffix. One source-owned
NBM validator now derives request/cycle from the source URL and verifies target,
extraction identity, and known market-to-station binding at attestation,
persistence, resolution, event-day, and migration boundaries. Focused tamper,
cleanup, event, migration, fan-out, NBM, capture, path, and architecture tests
pass; this strengthens local integrity but does not close the cross-process
fleet-fetch or controlled-soak gaps above.

## 2026-07-13 cross-process and bounded-inventory follow-up

Isolated snapshot children now receive one parent-owned capture-pass scope plus
the canonical shared-CAS root while retaining the existing shared provider-
cooldown path. For each NBM request/cycle, one child atomically creates a claim,
performs the provider fetch with the existing retry/backoff behavior, publishes
the exact UTF-8 bulletin through the immutable CAS, and publishes a small
immutable receipt. Other children wait a bounded 30 seconds, verify the receipt
identity and CAS hash/size, and parse their own station from those bytes. A
holder's final HTTP, timeout, or connection outcome is receipt-shared within
the pass, avoiding independent provider retry storms. If a claim remains
wedged past the bound, the waiter fails open to its normal provider fetch; CAS
writes still converge without replacing evidence.

The holder's per-market manifest owns the one prepublished physical-write
receipt even when a follower finishes persistence first. JSONL manifests and
compact fleet/runtime status now expose network fetch, reuse, cross-process
reuse, and timeout-fail-open counts alongside the existing created/reused and
logical/physical/avoided-byte counters. Deterministic process-like tests use
independent coordinator instances and prove one fetch, one CAS blob, distinct
market extraction, completion-order-independent byte accounting, shared HTTP
failure outcome, and timeout fail-open.

The inventory-only migration artifact is now schema v0.2 and streams the
snapshot tree under explicit elapsed-time, directory, tree-entry, manifest-
count, manifest-byte, JSONL-line, row, per-payload, aggregate payload-read,
candidate-detail, and physical-blob bounds. It can select one `YYYY-MM` month
and reports verified legacy stored bytes, projected one-copy bytes, and
projected reclaimable bytes by month. Repeated references count one physical
legacy file once, inconsistent physical identity evidence blocks every affected
row, and legacy paths must remain inside the selected snapshot root and event
folder. Truncation is explicit, includes a resume cursor, prints a partial
terminal result, and returns nonzero; candidate detail is sampled independently
of streaming totals. The command still has no apply, copy, rewrite, garbage-
collection, or delete mode, and its reachability observations remain non-
authoritative. The migration-only regression slice is 34 passed.

The immediate post-adoption live pass showed one completed US-market NBM
network fetch and cross-process reuse by the other completed markets. That pass
was only 11/12 because the NYC isolated child exited with code 137, so it is not
the required clean fleet proof and does not close the soak. A first monitor
started at 14:29 local and is retained as outage/repair evidence. After the
worker completed a clean iteration and cleared its error latch, a separate
controlled hour started at 14:44 under
`data/monitoring/item323_controlled_healthy_hour`; only that interval can become
the controlled-hour proof if its final readback stays continuously healthy. No
extra capture loop was launched for the measurement. The real-root migration
inventory remains deferred to the bounded 01:00–08:30 load window, and no
evidence was copied, rewritten, or deleted.

Read-only follow-up review found proof-boundary gaps that must land before this
item closes. The migration directory traversal, record-size, honest elapsed-
time, repeated-physical-reference, path-containment, scan-error, and invalid-
digest gaps are corrected in the worktree. The receipt path must still reject
symlinks and oversized/mutable records, bind bulletin issue semantics to the
requested NBM cycle, and retain network-fetch/physical-write attribution even
when the holder dies after publishing the CAS blob but before writing its
market manifest. Those receipt and accounting corrections are held for the
01:00–04:15 adoption window because those modules are loaded by the live
snapshot worker.

## 2026-07-14 controlled-hour readback

The clean monitor at
`data/monitoring/item323_controlled_healthy_hour/20260713T184446Z` completed
from 14:44:46 to 15:44:46 local. All 60 one-minute snapshot observations were
`HEALTHY` and `fresh`, all retained PID 9828 with zero consecutive errors, and
capture/heartbeat age stayed below 405.329/397.623 seconds against the
1,320-second dead threshold. The frozen diagnostic cursor contains 69 clean
iterations, 72 successful snapshots, and six complete passes in which all 12
markets wrote once. It omitted only the final NYC and Toronto snapshots: both
iterations began after the monitor start and completed at 15:44:36/15:44:44,
before the planned 15:44:46 end. Captured-at timestamps plus the immediately
following diagnostic records therefore establish 74 successful in-hour
snapshots. The incidents folder is empty. The earlier 14:29 monitor under
`data/monitoring/item323_controlled_hour/20260713T182928Z` remains separate
outage/repair evidence and is not relabeled.

Across the full interval's 578 forecast-manifest rows, compact observability
reports 65 created and 513 reused payload blobs, 2,342,478,936 logical bytes,
3,022,842 canonical physical bytes written, and 2,339,456,094 avoided bytes.
All 65 newly created market-local files were non-NBM source payloads; the extra
boundary file is NYC `nws_hourly` at 85,791 canonical bytes. The cursor-only
figures were 564 rows, 64/500 created/reused, 2,307,464,142 logical,
2,937,051 physical, and 2,304,527,091 avoided bytes. All referenced payloads
checked for this readback are present and pass their declared hash and
byte-count checks.

The NBM result is stronger for storage than for network fan-out. The 67 US-
market NBM rows all reference one 34,714,882-byte shared blob and one digest;
all 67 reused it, wrote zero shared physical bytes, avoided 2,325,897,094
logical bytes, and created zero market-local NBM copies. Their JSONL reference
rows total 224,554 bytes at 3,343–3,374 bytes each; the paired CSV rows add
108,446 bytes, for 333,000 bytes total and 4,953–5,016 bytes per reference pair.
Combined JSONL-plus-CSV reference bytes by market were ATL 29,814, AUS 29,790,
CHI 29,837, DAL 29,790, DEN 29,790, HOU 29,837, LA 29,910, MIA 29,766,
NYC 34,671, SF 29,981, and SEA 29,814; Toronto has no NBM row.

Staggered cadence produced 64 coordination scopes for those 67 NBM rows:
64 holders fetched from the provider and three followers reused receipts, with
no timeout or fail-open. Across the six complete US-market sweeps, fetch/reuse
was respectively 9/2, 10/1, 11/0, 11/0, 11/0, and 11/0; the final in-hour
partial sweep added NYC at 1/0. This proves same-scope coalescing and closes the
storage soak, but it does not prove one provider fetch for an entire fleet
cadence pass or bulletin cycle; network coalescing remains open.

Whole-host disk free fell 2.1399 GiB during unrelated concurrent activity,
while forecast-payload physical writes were 2.883 MiB (0.132% of that delta)
and NBM physical writes were zero. Physical headroom briefly reached 1.848 GiB,
but capture stayed healthy. Daily-refresh and taker state transitions in the
monitor are retained as unrelated host context and are not Item-323 failures.
The generated `final_report.md` title says “12-Hour” even though the manifest
and lifecycle prove a one-hour run; that cosmetic runtime artifact is preserved
unchanged.

Commits `391fb628` and `51460b7e` recorded the core implementation and both
schema registrations. A current-code audit confirms the destructive supervisor
authorization and fan-out receipt/accounting gaps described above were not
actually completed by those commits. They remain queued for the next
01:00–04:15 code window. The bounded real-root migration inventory also remains
pending; no evidence was copied, rewritten, or deleted in this readback.

## 2026-07-15 adoption-window hardening

The preserved controlled-hour result above was re-read from its structured
artifacts before this change. All 60 one-minute snapshot samples remained
`HEALTHY` and `fresh` under PID 9828 with zero errors, and its incidents folder
is empty. The 74-snapshot/578-row totals still reconcile to 65 created plus 513
reused blobs, 2,342,478,936 logical bytes, 3,022,842 physical bytes, and
2,339,456,094 avoided bytes. All 67 NBM rows still resolve to one
34,714,882-byte shared blob, zero market-local NBM copies, 224,554 JSONL bytes
plus 108,446 CSV bytes, and the documented 64/3 network-fetch/reuse split. The
earlier 14:29 monitor remains unchanged as separate unhealthy-start evidence.

Inside the verified 01:00–04:15 window, the destructive snapshot, CLOB, and
observation paths were hardened to authorize termination only when the exact
managed command, status and writer-lock provenance, and current OS process
instance all agree. Windows holds the verified process handle through command
and creation-FILETIME validation, termination, and exit observation; supported
POSIX hosts use a pidfd. Unknown inspection, reused PIDs, command mismatches,
and provenance mismatches fail closed. A live mismatched writer-lock owner is
authoritative, generic CLOB process scans are diagnostic-only, and a same-PID
replacement lock is retained. Every ensure, explicit restart, and operations-
monitor restart path refuses to launch a replacement after an unconfirmed
stop. Positive exact-instance and negative unknown, command-mismatch, reused-
PID, lock-mismatch, lock-replacement, and restart-gating coverage exercises all
three loops.

Cross-process fan-out receipts now require a stable regular file no larger
than 16 KiB. `lstat`, file-handle, and pre/post-read checks reject final-file
links, non-regular files, mutation, and symlink/junction/reparse ancestry from
the CAS root through the receipt parent. Every NBM outcome—including holder,
receipt reuse, unscoped, and timeout-fail-open paths—parses the bulletin header
and binds its semantic issue cycle to the requested cycle before the payload is
accepted. Preserved legacy v0.1 success receipts remain readable, but their
unrecoverable historical network/physical attribution is explicitly counted
as unavailable rather than invented.

New success receipts carry a content digest and one immutable coordinator
attribution tuple. That tuple owns network-fetch and physical-write accounting
even if the holder publishes the CAS blob and receipt but dies before its
market manifest. Child summaries retain a maximum-32 bounded tuple list;
snapshot-parent and runtime-monitor aggregation deduplicate identical
coordination IDs and fail closed on conflicting receipt or payload evidence.
The offline audit uses an internal exact-ID merge across separate market/event
folders, supports normal histories with more than 32 scopes without relaxing
the live-status bound, and strips the internal tuples before serialization.

The post-review implementation matrix passed **299 tests plus 9 subtests**;
one final-file symlink test skipped because this Windows account lacks symlink
privilege, while the mocked reparse-parent fallback passed. The affected
fan-out/schema rerun passed **58 tests** with that same single skip. The three
daily-refresh assertions plus schema-registry and import-architecture suites
passed **31 tests**, and `python -m compileall -q app src tests` passed.
Roadmap regeneration/lint and the agent-docs audit passed, as did **15**
roadmap/app/documentation regression tests. The work verified rather than
duplicated the receipt v0.1 and migration dry-run v0.2
registrations already present in `51460b7e`, as well as the explicit daily-
refresh temp paths, promotion disk preflight, and exact 23-step Stage-A
boundary.

A final pre-commit audit also found and repaired an ensure-path availability
regression: snapshot, CLOB, and observation now use the same proven-gone
authorization predicate as their explicit restart paths, so an already-absent
recorded instance permits replacement while unknown or mismatched identity
still blocks it. The three loop suites then passed **128 tests plus 9
subtests**; the final supervisor/fan-out/docs slice passed **98 tests** with the
same one symlink-privilege skip, and a fresh compileall pass succeeded.

All implementation, tests, and this checkpoint remain isolated on
`codex/item323-hardening` from base `713692de`; they have not been merged into
`master` or adopted by the live worker. At the 01:46 read-only checkpoint, the
scheduled worker was still exact PID 35100 (started 01:02:17, parent 62336) at
loaded/current main identity `713692de26ea` / `4867a3ef74fe4668`. It continued
writing and fleet cadence reported 12/12 healthy markets, but the loop had 31
consecutive error iterations: the latest Denver and San Francisco children
ended in `MemoryError`, and Seattle ended with return code 137. Free physical
RAM was 3.728 GiB, commit use was 47.21%, and free C: space was 296.561 GiB.
That incident was inspected and preserved without restart, signal, lock
cleanup, or any other loop control.

At the final 01:59 readback, that same PID and command still had a current
01:59:20 heartbeat and the same loaded/current source identity, but the count
had risen to 44 consecutive error iterations: Seattle and San Francisco ended
in `MemoryError`, while Denver returned 137. Free RAM had fallen to 3.437 GiB,
commit use was 49.30%, and free C: space was 296.196 GiB. This later evidence
was likewise read without controlling the process.

Because this branch has not been live-adopted, the controlled hour's 64 fetches
and three receipt reuses remain the only live network evidence and do not prove
one provider fetch per fleet pass or bulletin cycle. The bounded read-only
real-root monthly migration inventory is also still pending; no migration
apply, rewrite, GC, or evidence deletion was performed. Item 323 therefore
remains partial pending owner adoption, a clean live network proof, and the
bounded real-root inventory.
