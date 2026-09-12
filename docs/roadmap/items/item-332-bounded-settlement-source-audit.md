# 332. Bounded Settlement-Source Audit [PARTIAL 2026-09-12 - IMPLEMENTATION IN PROGRESS; QUALIFICATION OPEN]

Goal: complete settlement-source auditing within the existing daily-chain resource
gates while preserving selected revisions, summaries, lineage meaning, and
truth-label decisions. This implements the approved R3 reliability increment.
The implementation contract is [settlement-source audit](../../operations/settlement-source-audit.md).

Owner/package: `weather.reporting.source_gates`, with existing daily and trading
consumer entrypoints.

Source: the operator's September 12 approval of the R3 reliability increment;
canonical baseline source and the retained legacy fixture described below.

Why this matters: retained revision histories must not exceed the daily audit's
memory budget or prevent later settled-day analysis steps from running.

Acceptance: preserve the legacy semantic result, qualify the complete bounded
path against its memory target, and obtain separate production execution proof.

## Scope

- Stream label and ledger history into a disposable disk-backed revision index.
- Preserve encounter-order whole-row selection and nonempty label overlay.
- Stream complete canonical output and bound downstream requested-date readers.
- Reuse hashes only for explicitly sealed, content-verified offline inputs.
- Release the first index before a daily reconciliation retry rebuilds it.
- Keep previous complete authoritative output on interrupted or failed writes.

## Evidence and acceptance

The baseline is canonical master
`f3814173775335adb546b7201a2e73ecec7703bf`. The frozen legacy fixture was produced
with that implementation on the separate workstation before replacing the
builder. It covers 18 selected events, label/ledger revisions, all audit status
families, both native settlement units, lineage, summaries and date gates.

The baseline synthetic fixture holds 256 events constant while increasing
superseded ledger history from 2,048 to 16,384 rows. Its semantic result stayed
identical while traced Python allocation peaked at 5,353,373 and 42,368,683 bytes.
This isolates the unbounded-history defect; it is not a production-corpus or
timing acceptance result.

Remaining acceptance:

- [ ] Execute the new parity, consumer, interruption, bounds and scaling tests.
- [ ] Qualify a representative sealed corpus at no more than 2 GiB private memory
  through the complete build/gate/publication path and compare legacy semantics.
- [ ] Publish exact source and retained qualification evidence, review CI, and
  obtain the repository-owned roll verdict before guarded production adoption.
- [ ] Verify an actual admitted daily-chain execution and its resource receipt.

The implementation is isolated on
`codex/bounded-settlement-audit-20260912`. No production adoption, Scheduler
change, historical ledger repair, capture restart, promotion, or live trading
has been performed by this increment.
