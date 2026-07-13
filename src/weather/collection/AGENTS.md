# Collection Guidance

Scope: live capture and persistence under `src/weather/collection/`. Inherits
[package-wide guidance](../AGENTS.md).

- `snapshot_tracker` owns capture orchestration; `SnapshotStore` owns snapshot
  schemas and persistence. Keep those responsibilities separate.
- Snapshot, forecast, source-status, component, and replay tapes under `data/`
  are ignored local evidence. Preserve them with append-only or explicit
  migration behavior; never rely on their presence in a clean checkout.
- Keep one-writer, lock, atomic-write, JSONL-integrity, redaction, and canonical
  captured-input hash guarantees intact. Schema changes require registry,
  reader, writer, backfill/migration, and fixture updates together.
- The managed fleet loop uses bounded isolated child processes, per-market
  failure isolation, runtime-fingerprint checks, and explicit fleet deadlines.
  Do not replace an explicit failed/skipped result with a silent omission.
- Scheduled and observation-triggered captures have different cadence
  semantics. Preserve the due tolerance, local-market-day guard, source
  freshness visibility, and serving-release lineage.
- Tests must build temporary data layouts rather than read the developer's
  `data/` tree.

Run focused tests in `tests/collection/` plus relevant operations tests for
supervision, runtime identity, JSONL repair, and schema registry changes.
Storage placement is defined by
[Repository Path Policy](../../../docs/operations/path-policy.md) and operational
loop behavior by
[Operations Design](../../../docs/operations/OPERATIONS_DESIGN.md).

## Update this file when

Update when capture/persistence ownership, tape durability, writer/hash/schema
contracts, cadence semantics, or collection verification changes.
