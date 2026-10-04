# Maker shadow runner design

Status: proposed Phase 3 implementation contract; documentation only.

- **Owns:** workstation public-read orchestration, the per-minute quotes tape,
  nightly replay scoring, agreement tolerance and shadow safety drills.
- **Read when:** implementing or reviewing Phase 3 of the
  [informed-maker plan](informed-maker-design-2026-09-25.md#phased-plan).
- **Prerequisites:** [maker-core contracts v0.1](maker-core-contracts.md) and the
  [replay bundle/scorer contract](maker-replay-bundle.md). Current authority lives
  in [STATE_OF_PLAY.md](STATE_OF_PLAY.md); this design grants no run authority.

## Scope and capability boundary

Run on the separate non-capture workstation. Production continues to own 88a
capture and bounded, sealed exports. This change implements no runner, CLI,
schedule, credentials, exporter or score authorization. Names below describe
proposed records and components, not installed commands or schema versions.

The runner has **no order path at all**. It must be possible to run its complete
import closure without a signing SDK, wallet, credential store or live adapter:

| Component | Allowed capability |
| --- | --- |
| Public input adapter | Credential-free International market discovery/rules, both-token books, current public reward terms and public market-stream trades/health; allowlisted endpoints and bounded reads |
| Domain adapter | Capture free public inputs or consume immutable captured inputs, then call the v0.1 plugin providers; preserve first availability, hashes and expiry |
| Decision loop | Call `maker_core.quoting.policy.decide(DecisionInputs)` and update an explicitly hypothetical portfolio |
| Evidence writer | Create-only local input artifacts, hash-chained proposals, coverage records and terminal seals |
| Nightly evaluator | Read closed shadow/88a bundles and use the offline replay engine, fill model and scorer through their admission gate |

No account REST reads, authenticated user stream, wallet-reader connection,
WinCred or environment credential loading, signing, heartbeat REST calls,
submit, amend, cancel, cancel-all, redeem, transfer or allowance operation is
reachable. Public WebSocket subscribe/ping messages are permitted protocol
traffic, never order messages. HTTP redirects and arbitrary caller URLs cannot
escape the public endpoint allowlist. A capability flag or `dry_run` around a
live client is insufficient: the public adapter interface has no mutation
methods and the runner never constructs that client. There is no switch that
turns this runner into Phase 4.

Extend the existing import ratchet with the runner's transitive imports and
exercise every stop/drill branch with a recording transport that refuses
anything outside public reads. The live venue, credential, RE-1 attended and
wallet adapters must remain unreachable. Plugins still import only
`maker_core.contracts`; core code still imports no `weather.*` module. A
weather-specific composition layer owns provider IO outside the pure plugin.

## Session, clocks and hypothetical state

Before a session, freeze a manifest binding code and contract revisions, plugin
and model identities, selected conditions and local target dates, active UTC
intervals, profile/configuration hashes, initial hypothetical cash, all caps,
hazard assumption, fill bound, input allowlist, resource ceilings and run ID.
Caps are explicit simulation inputs, never wallet balances or live authority.
The manifest also identifies the proposed scoring registration and parent run,
if any. Missing admission or configuration refuses startup.

Use the shared kernel and lifecycle rules, not a second quoting policy. The
profile identifier is `informed-v0`; centre, grade-`none` symmetry, event expiry,
cooldown, reservations and missing-hazard behavior remain owned by
[the pure-input contract](maker-core-contracts.md#pure-decision-inputs-and-units).
Do not upgrade a provider to grade `shadow` merely because this runner consumes
it. `Unavailable` stays explicit; stale, corrupt or future inputs cannot become
fresh probabilities. A missing conservative hazard remains a refusal, and a
synthetic hazard is labelled diagnostic throughout.

Use these proposed orchestration rules:

1. Order received inputs by local capture time and a stable producer sequence;
   retain provider/venue timestamps separately. At decision time `t`, pass only
   inputs captured at or before `t`. Preserve the v0.1 `as_of_utc` and
   `valid_until_utc`; a later export or unchanged body never moves first availability.
2. Emit one minute checkpoint for every admitted condition, including holds,
   refusals and missing-input coverage. Use UTC minute slots, but record actual
   decision and capture instants. Do not round a late response back into a slot.
   Process conditions in the replay engine's stable condition-ID order and
   reserve each proposal before evaluating the next condition.
3. Public input events and safety timers can withdraw a proposal between minute
   checkpoints. Do not wait for the next minute on a kill request, stale input,
   information pull, changed terms or ambiguous local state. Record every such
   transition. A minute row references intervening events; it does not replace them.
4. Re-read reward terms each minute. Preserve the kernel's ten-second book
   decision freshness and existing terms/view/event limits. Arm explicit expiry
   timers; this design withdraws hypothetical legs once their book exceeds the
   ten-second budget. A public feed must supply sufficient fresh observations;
   a one-minute REST sample alone cannot justify a full minute of resting exposure.
   Stream health and book freshness are separate facts. A heartbeat never
   refreshes a book, view or terms body.
5. Carry hypothetical cash, lots, reservations, previous fair value, placement
   and cooldown times, event latches and deduplication state across decisions.
   Public books contain none of our simulated orders: reuse the replay adapter's
   own-level compensation before the kernel removes hypothetical own levels.
   Carry state across midnight; do not reset inventory to make the next day score.
6. The primary hypothetical lifecycle uses the replay strictly-through fill
   model; the at-price sensitivity has independent state. Preserve trade-time
   ordering, duplicate handling and first-fill sibling withdrawal. These are
   simulated fills only. Any unavailable trade-health interval is excluded,
   never interpreted as zero fills or silently bridged with known inventory.
   Resume uncertain campaigns only as separately labelled diagnostic runs with
   an explicit new initial state; do not splice them into countable continuity.

The incremental event adapter, deadline scheduling and replay projection are
Phase 3 implementation work. Reuse/extract the Phase 2 transition logic with
parity fixtures; do not claim the existing closed-bundle engine already runs a
public feed. In particular, its sampled-book hold of up to 60 seconds is a
disclosed replay approximation, not permission to relax shadow freshness.
The shadow replay must reproduce the recorded ten-second expiry timers.

## Per-minute hash-chained quotes tape

Use the existing `maker_core.evidence.journal.Journal` envelope and
`canonical_bytes`: sorted ASCII JSON plus LF, zero-based sequence,
`recorded_at_utc`, and `previous_sha256` equal to SHA-256 of the preceding line's
exact bytes (null on the opening record). Every append flushes and fsyncs. One
writer owns each session segment; names are unique and files are never appended
after restart. This is a tape of proposals, not submitted orders.

Proposed payloads inside that unchanged journal envelope:

| Record | Required content |
| --- | --- |
| Opening | Run/segment and parent identities, UTC scope, frozen manifest hash, simulation mode, predecessor seal if present |
| Input capture | Kind, condition, capture and source clocks, producer sequence, content digest and bounded manifest reference; response/error and feed-health evidence |
| Decision transition | Actual decision UTC, condition, full `QuoteDecision` including reasons and input hash, exact typed input artifact hash, hypothetical state before/after and applied local transition |
| Minute checkpoint | UTC slot, expected conditions, each condition's latest decision/event reference, active hypothetical legs, freshness/coverage and refusal reasons, reservation/lot state digest; explicitly mark unevaluable conditions |
| Gap or drill | Affected scope, start/end or unknown end, reason, injected event if applicable, withdrawal time and any ambiguous local acknowledgment |
| Terminal | End reason, last completed minute, counts, coverage/exclusions, remaining hypothetical lots, final state and manifest hashes; never an assertion about exchange orders |

Store complete replay inputs as create-only, content-addressed, allowlisted
typed artifacts beside the tape, with relative paths, lengths and hashes in a
manifest. Reject traversal, redirects/reparse points, unlisted files, changed
bytes and output/input overlap. Preserve source payload hashes and exact capture
clocks; a hash alone cannot reconstruct an input. Repository-owned path defaults
must use `weather.paths`; the neutral core accepts explicit caller paths. Any
eventual ignored `data/` layout is runtime state, absent in a clean checkout.

Serialization must round-trip to the exact `DecisionInputs` whose canonical
digest the decision stores. Test this explicitly: the existing `SecretGuard`
removes keys containing `token`, including a raw `outcome_tokens` field. Use a
reviewed public-data projection (for example outcome-to-asset mapping under
`outcomes`) and an exact inverse, rather than weakening the guard or losing
identity. Never journal raw HTTP/SDK objects or headers. Secret-field filtering
must not silently make a parity artifact incomplete; reject such a record.

Seal at UTC-day/size boundaries with a terminal record, then retain a create-only
seal containing whole-file SHA-256, final line hash, count, byte length, manifest
and final-state digests. Retain the seal digest independently in the closed-day
export/verification receipt. Link the next segment's opening to that seal.
`verify_journal(..., expected_digest=...)` is necessary: a chain alone cannot
detect replacement by another valid chain or truncation to an earlier terminal.
Hashes prove byte identity, not authenticity.

Journal failure poisons the writer and halts decisions; never retry an append.
A crash leaves the old bytes intact and the segment incomplete. Recovery records
the last verified prefix and gap in a new segment, without truncating, repairing
or inventing the old terminal. Restore only fully persisted hypothetical state
with verified lineage; otherwise stop that campaign. Missing minutes, torn
records and stopped intervals remain visible in the declared coverage denominator.

## Nightly scoring against 88a

Evaluate a closed UTC capture day on the workstation after its sealed production
88a export arrives. Export/transfer authority is separate; this runner never
opens growing production files or reads production state remotely. Use the
[weather exporter and neutral envelope](maker-replay-bundle.md#weather-exporter)
with exact condition identities, both-token books, time-bound terms, public
trades/health, plugin inputs and subsequently captured reconciled settlements.
Late bundles or settlements produce a pending/incomplete report, not a zero.

Each nightly evaluation creates a new immutable report directory and binds the
shadow seals, every 88a manifest/stream hash, plugin artifacts, code/configuration
and scoring-registration digest. A later settlement may produce a successor
report referring to the old one; neither report nor input tape is overwritten.

The evaluation has three separate outputs:

1. **Captured-input replay agreement.** Reconstruct the shadow's ordered events,
   timers, exact inputs and carried state offline. Re-run the shared decision
   and lifecycle logic and compare every decision and terminal transition under
   the tolerance below. Minute checkpoints verify coverage but cannot stand in
   for a full event trace.
2. **Recorded-shadow counterfactual scoring.** A proposed adapter converts the
   recorded active-leg intervals into the scorer's `ReplayResult` representation,
   retaining original decisions and withdrawals, and joins them to 88a paths,
   contemporaneous terms, health and settlements. Use the existing fill model
   and `maker_core.replay.score.score(result)`; do not regenerate proposals from
   later 88a information and call them the shadow tape. A simulated first fill
   clips both legs. If 88a yields state different from the recorded shadow state,
   exclude the affected continuation until a provably identical state is reached;
   do not force recorded replacements onto contradictory cash or inventory.
3. **Policy comparison.** Run `informed-v0`, `blind_re1`, `no_quote` and
   `clock_only` on the same admitted 88a bundles via the existing replay report
   composer. Report this separately from recorded-shadow scoring. The former is
   a common-input policy experiment; it is not evidence that two independent
   feeds emitted identical proposals.

The recorded-shadow adapter and scoring-entrypoint integration do not exist by
virtue of this document. They must preserve the Phase 2 authorization check;
calling a library directly must not bypass it. Nightly **economic** scoring
requires an owner-reviewed pre-registration enrolled by exact hash in
`replay.authorization.APPROVED_REGISTRATIONS`, with dates, market clusters,
policies, caps, hazard, both fill bounds, metrics, seeds and hurdles frozen before
the first scored read. The current table is empty. Without admission, the job
reports diagnostics/coverage and `NOT_RUN` economics, not an ungated comparison.
No new CLI flags or nightly scheduled task are authorized here.

Retain the scorer's strictly-through primary and at-price sensitivity; modelled
reward at k=1 and k=0.5; nominal rebate separately; 1/5/30-minute and settlement
markouts; held-inventory settlement P&L; cash-hours; pull fraction; replacements;
and fills inside/outside event windows. These are counterfactual quantities, not
paid rewards or own-account P&L. Preserve missing marks, unresolved lots and net
suppression. Do not add alternative markouts to settlement P&L. Reuse the
[scoring contract](maker-replay-bundle.md#scoring) for matched clock controls,
paired complete market/date cells, date and crossed date-by-market 90% intervals,
cluster counts and `UNDERPOWERED`; missing feed intervals cannot become gains
for no-quote or disappear from the coverage report.

## Replay-vs-shadow agreement tolerance

**Proposed acceptance: zero discrepancies on identical captured inputs.** This
implements the design's byte-for-byte parity requirement; it is not a fitted
economic hurdle or a claim that independent book captures match.

| Check | Tolerance and disposition |
| --- | --- |
| Input lineage, event ordering and replay clock | Exact identities, hashes, sequence, decision instants and timer boundaries; no nearest-minute substitution |
| Decision trace | Zero missing/extra events and canonical byte equality of every `QuoteDecision` field, including action, reasons, legs/order, Decimal prices/sizes, profile, input hash, centre, share and net; zero floating-point epsilon |
| Lifecycle and terminal | Exact transition order, reservations, lots, hypothetical cash, withdrawals and terminal outcome; minute-only equality cannot pass |
| Repeated scoring of the same admitted trace | Identical deterministic report bytes with pinned code/config/seeds; no rounding away a difference |
| Shadow versus independently captured 88a inputs | Report unmatched/different-input intervals and their reasons separately. No numeric tolerance can turn them into matched parity or prove own fills |

Use `maker_core.replay.parity.compare_journal` for the complete decision
projection and add explicit state/terminal/checkpoint comparisons in Phase 3.
Its event-count comparison does not by itself validate the journal seal or
portfolio. A failure remains `FAIL`; an absent trace or required terminal is
`INCOMPLETE`/`NOT_RUN`, never PASS. Investigate even one mismatch before counting
the date; corrected code starts a new pinned evidence cohort.

Count at least seven complete closed shadow UTC dates toward the plan's
7-14-day observation period only when every declared minute/condition is
accounted for, all available transitions replay exactly, required 88a evidence
is admitted, and no required comparison is missing. Genuine no-quote decisions
count as decisions, while gaps and drill injections do not qualify a date.
Seven all-refusal days cannot establish quoted-lifecycle or economic readiness;
report actual covered quoting exposure and separately pass the drills. Keep
partial days in diagnostic totals, and never shrink the frozen scope after
seeing coverage. Economic hurdles remain the owner's pre-registered Phase 2/4
decision, including the plan's separate replay evidence requirements. Parity
alone cannot promote the maker or end a live-trading pause.

## Drills and required receipts

Run deterministic fixtures first, then injections into an explicitly labelled
shadow drill session on the workstation. No drill is an exchange-lifecycle
test. In particular, cancel-all and lost ack concern the local simulation sink;
they cannot prove live cancellation, dead-man behavior or account reconciliation.
Every receipt binds code/config, initial state, injection, ordered transitions,
time-to-withdrawal, final state and tape seal, plus a transport log demonstrating
zero authenticated or mutation calls. Injected intervals are excluded from
economic and seven-day qualification evidence.

| Drill | Injection | Required result |
| --- | --- | --- |
| Kill switch | Latch a local stop during active hypothetical legs, including between minute ticks | Withdraw all local proposals before further decisions; stop input workers; terminal receipt or explicitly incomplete journal on forced death; restart cannot clear the latch implicitly |
| Stale feed | Expire books, trade-health, terms and plugin validity independently; disconnect and reconnect | Timestamp-specific refusal/withdrawal at the frozen deadline, recorded gap, no zero-fill inference; fresh reconnection does not erase history or restore unknown inventory |
| Cancel-all | Request a global local withdrawal with several conditions and reservations | One idempotent simulation transition clears all proposed legs/reservations, preserves held lots and blocks replacements until explicitly resumed; zero venue cancel calls |
| Restart | Stop cleanly and crash after input persistence, decision persistence and simulated application; try a duplicate writer | Refuse duplicate ownership; recover only a verified committed state in a new linked segment; missing application acknowledgment stays ambiguous; no replay of an old intent as a fresh quote, no cash reset or tape rewrite |
| Terms change | Raise minimum size above proposed size, change rate/spread, remove terms and supply a wrong-condition record | Withdraw invalid legs before cooldown, re-evaluate only on correctly bound fresh terms; split scored intervals at the captured change; never use tonight's terms for earlier minutes |
| Lost ack | Drop the simulation sink acknowledgment after a local proposal or withdrawal application | Persist ambiguity, stop replacements and never retry the proposal as a new intent; reconcile only from the durable simulation log or end incomplete; duplicate/delayed acknowledgments are idempotent and cannot revive withdrawn legs |

An acknowledgment here is a local durable-state receipt. Keep the simulation
sink type separate from every venue interface, with no client, HTTP method or
real order identifier. Passing it tests recovery logic only; future owner-started
live sessions still need their own authenticated lifecycle drills and gates.

## Implementation acceptance and operation boundary

Before enabling a public shadow run, require conformance with the fictional and
weather plugins, no-order import/transport tests, journal corruption/truncation
and secret-guard round trips, minute/gap accounting, cross-midnight state,
same-time trades, all six drills and exact replay fixtures. Pin resource/time/
disk/output ceilings and single-writer/process identity in the launcher; bound
all worker children and leave explicit terminal or partial evidence on limits.

Nightly replay is heavy workstation work under
[the host-load policy](HOST_LOAD_POLICY.md#workstation-and-portable-executor-scope).
The existing offline wrapper does not authorize a networked runner, and its
allowlist does not yet admit `maker_core.replay`. A reviewed admission integration
must land before real nightly execution; fixture tests use the admitted test
path meanwhile. Do not weaken or bypass the wrapper. Any future shadow launcher
must respect the workstation live-executor exclusion and child-tree cleanup;
production receives no new quoting workload or scheduled task.

The owner reviews replay evidence, shadow coverage/agreement and drill receipts
before separately commissioning Phase 4. This document neither lifts the live
pause nor implements that runtime. Public evidence cannot certify own fills,
fees, rebates or wallet reconciliation; those remain governed by
[the pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md) and
[portfolio accounting](portfolio-ledger.md).

## Update when

Update when implementing the public adapter or incremental replay bridge,
freezing the tape projection/launcher/scoring registration, changing agreement
or coverage rules, or adding a drill. Keep plugin API semantics in v0.1's owner,
scorer mechanics in the replay contract, and current decisions in state of play.
