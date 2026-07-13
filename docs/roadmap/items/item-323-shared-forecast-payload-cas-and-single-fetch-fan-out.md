# 323. Shared Forecast Payload CAS And Single-Fetch Fan-Out [PARTIAL 2026-07-13 - NEW NBM WRITES DEDUPLICATED; CROSS-PROCESS FETCH FAN-OUT AND SOAK PENDING]

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
- [ ] Add NBM single-fetch fan-out and shared-blob reuse without changing
  market-specific capture timestamps or cutoff semantics.
- [ ] Prove captured-input replay, feature parity, and per-market lineage across
  the shared reference path.
- [ ] Add logical/physical/avoided-byte observability and a host disk-growth
  budget gate.
- [ ] Implement a dry-run-first migration/GC tool with reachability, restore,
  hash, and replay proof; perform no evidence deletion until explicitly
  reviewed.
- [ ] Complete a multi-market soak showing repeated national NBM captures reuse
  shared bytes and remain healthy through process restart.

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
