# 329. Live Maker Event Ledger And Architecture Hardening [OPEN 2026-08-16 - APPROVED; PRE-PROBE PREPARATION ONLY]

Goal: make the International maker system cognitively scalable and make its
tests distinguish internal software consistency from real exchange and
economic evidence.

Owner/package: `weather.market`, `weather.operations`, shared train/serve
contracts, test infrastructure, and canonical agent documentation.

Source: the operator approved the 2026-08-16 read-only architecture and test
audit. The audit found a safe but procedural live path built from large mutable
payloads and multi-hundred-line functions, strong fail-closed unit coverage,
and no authoritative live outcome yet. It also found executable legacy
Polymarket US mutation code, duplicated train/serve density math, monolithic
tests coupled to private helpers, deprecated taker maintenance surface, and a
canonical findings file whose older forecast-first sequencing can misroute a
compacted agent after the market-harvest pivot.

Why this matters: the first live session should prove or reject narrowly
defined exchange and economics assumptions. It should not silently turn
synthetic test success into a claim of profitability, nor should a premature
rewrite erase the event shapes needed to design the durable system correctly.

Critical-path boundary: this programme **does not block the first bounded live
probe**. Before that probe, only a concrete missing safety sequence, dependency
contract, or fixed-scope wrapper defect may enter the live-test path. Broad
refactoring waits for the first legitimate session so the target contracts are
based on observed event shapes rather than richer synthetic assumptions.

## Phase 0 — safe preparation before the first probe

- [ ] Maintain a requirement-to-evidence matrix for ambiguous submit results,
  partial-fill/cancel races, duplicate and out-of-order user events, reconnects,
  stale account readers, crash recovery, and delayed fee/rebate evidence.
- [ ] Add only missing pre-probe sequence tests through a deterministic,
  no-network exchange fault harness; do not generalize the live mutation path.
- [ ] Run the real pinned official-client contract as a non-skippable focused
  suite when live-adapter code changes; prepare a small Windows contract lane
  for scheduler/process semantics without model artifacts or network access.
- [x] Record the repository-wide evidence truth ladder and correct the canonical
  strategy supersession so tests cannot be presented as live or economic proof.

## Phase 1 — event architecture after the first legitimate session

- [ ] Preserve a redacted, hash-bound fixture from the real session with field
  provenance, capture time, contract version, and known omissions.
- [ ] Define immutable typed boundaries for evidence, quote decisions, risk
  budgets, one-shot session authority, exchange commands, authoritative events,
  reconciliation, and economics output. Serialized payload schemas remain
  versioned and replayable.
- [ ] Replace the procedural session core with an append-only event ledger and
  deterministic reducer covering preparation, submission, acknowledgement,
  partial/final fill, cancellation, ambiguous mutation, teardown, and final
  reconciliation states.
- [ ] Split evidence validation, authority issuance, exchange mutation, event
  reduction, teardown, and reporting into owner modules. Keep independent
  checks at trust boundaries rather than copying field parsing throughout each
  phase.
- [ ] Add model-based event-sequence tests and targeted mutation testing for
  risk caps, post-only forcing, one-submit authority, no-naked-sell behavior,
  ambiguous outcomes, cleanup, and final state reconciliation.

## Phase 2 — reduce misleading and low-value surface

- [ ] Remove the executable Polymarket US live mutator and secret-configuration
  path. Retain only a quarantined pure historical normalizer if a proven replay
  consumer still needs it, and ratchet International live modules against any
  legacy-US import.
- [ ] Move the duplicated density-shape and forecast-relative math behind one
  pure train/serve contract so parity is structural rather than maintained by
  copied implementations.
- [ ] Move reusable payload builders into `tests/support`, remove cross-test
  imports, split monolithic test files by behavior, and replace global-count
  ratchets with per-module budgets plus ownership metadata.
- [ ] Classify the suite into always-run safety contracts, diff-selected owner
  tests, real-dependency contracts, and the immutable full integration suite.
  The full suite remains mandatory for the existing high-risk integration
  boundaries; test tiering must not weaken them.
- [ ] Quarantine or retire the deprecated taker implementation and its default
  CI burden only after proving no current maker, evidence, or historical replay
  consumer depends on it. Preserve durable trading evidence and branch history.
- [ ] Move completed one-off research implementations out of the production
  import surface while retaining reproducible evidence and exact historical
  entry points where they are still required.
- [ ] Split the findings corpus by forecast, maker economics, and host
  operations behind a concise claim index with explicit `supersedes` links.
  Add roadmap metadata for critical-path lane, blocker, and next evidence so
  old `PARTIAL` work cannot masquerade as current priority.

Acceptance: the live maker path is an International-only, typed, event-sourced
state machine whose mutation authority and economics are reconstructable from
an append-only authoritative ledger; train/serve math has one implementation;
tests are mapped to failure classes and evidence rungs; legacy US and taker
surfaces cannot enter the live path; and a compacted agent can identify current
priority without reading the historical corpus. No risk ceiling, promotion
gate, evidence requirement, credential boundary, or quiet-window rule is
weakened to complete this item.

## Update this item when

Update after the first legitimate session fixes the observed event contract,
when a phase begins or closes, or when evidence proves that a proposed cleanup
would remove a still-live consumer. Exact runtime measurements belong in
`docs/operations/ESTABLISHED_FINDINGS.md`, not here.
