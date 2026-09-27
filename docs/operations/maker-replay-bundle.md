# Maker replay bundle and diagnostic contract

Status: canonical envelope, replay, scoring and diagnostic-default contract; fixture-verified.

- **Owns:** bounded closed-UTC-day replay envelopes, capture-time access, diagnostic output and the scoring boundary.
- **Read when:** producing neutral replay inputs (including an external domain plugin) or reviewing replay admission.
- **Not here:** the frozen [v0.1 plugin contracts](maker-core-contracts.md), the
  [design](informed-maker-design-2026-09-25.md), or current authority ([state of play](STATE_OF_PLAY.md)).

This is additive to the plugin contracts: no Protocol method or existing field changes. The core reads caller-supplied
paths and imports no weather modules. The authoritative envelope constants are in
`src/maker_core/replay/bundle.py`. No producer should treat acceptance of an envelope as validation of its payload,
decision eligibility, parity, a fill or an economic result.

## Closed-day envelope

A directory contains `bundle.json` and one or more flat, explicitly manifested JSONL streams. Unlisted files are never
opened. Compression and external payload references are not admitted by this envelope reader. Each manifest contains:

| Field | Meaning |
| --- | --- |
| `format` | `maker_core.replay.bundle.v0.1` |
| `day` | Canonical `YYYY-MM-DD` UTC capture day, not the contract's settlement target date |
| `sealed_at` | UTC time at or after the end of that day; a producer assertion, not an authenticated clock |
| `provenance` | `synthetic` or `captured`; neither label grants scoring authority |
| `conditions` | Unique binary condition identities with stable `market_id` cluster labels, `domain_id`, and an explicit minute-aligned `active_from` inclusive / `active_until` exclusive interval inside the day; equal endpoints mean settlement-only metadata with zero quote minutes |
| `streams` | Objects with `path`, raw-byte `sha256`, `bytes`, and `records`; flat alphanumeric/underscore/hyphen `.jsonl` names only |

Each stream record contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `sequence` | Unique nonnegative integer within the bundle, at most the exact JSON integer bound; breaks capture-time ties |
| `captured_at` | UTC timestamp within the bundle day; never replaced with provider issue or export time |
| `condition_id` | One of the manifest's conditions |
| `kind` | `descriptor`, `book`, `terms`, `coverage`, `trade`, `plugin_input`, `outcome_view`, `info_event`, or `settlement` |
| `payload` | Inline JSON object; kind-specific semantics require subsequent adapters and are not yet frozen |
| `payload_sha256` | SHA-256 of `maker_core.evidence.journal.canonical_bytes(payload)` (sorted ASCII JSON plus LF) |
| `source_hashes` | Nonempty mapping of provenance labels to lowercase SHA-256 digests; labels are not paths to open |

The enclosing stream hash binds capture times, identity, ordering and source hashes as well as payload bytes. The report
retains the manifest's raw-byte hash plus every stream hash. Hashes establish byte identity, not producer authenticity.
Unknown fields, ambiguous duplicate JSON keys, nonfinite numbers, unlisted identities, duplicate sequences, incomplete
lines and mismatched hashes/counts refuse the entire bundle. There is no partially admitted tape.

Records are sorted by `(captured_at, sequence)` independently of file layout. A `Timeline.at(t)` snapshot contains only
records captured at or before `t`, with recursively immutable payloads. Pass that snapshot to an adapter; do not pass the
full tape. Same-time records are all visible at the tick, ordered by producer sequence. This API prevents ordinary future
record access through snapshots; it is not a sandbox against a provider deliberately reading another source. Settlement
records follow the same rule. Later-captured settlement belongs to a later capture-day bundle. Multi-day replay carries
its own lots and cash across supplied days; it assumes no positions before the first bundle.

The fixture producer is `tests/maker_core/fixtures/replay_bundle.py`: three closed synthetic UTC days, two fictional
market clusters and one missing book minute per day. It is not an 88a export or evidence about any real market.

## Bounded reads and outputs

`Limits` permits lowering, never raising, the reader's byte, row and time ceilings. Manifest, line, stream and condition
counts also have fixed ceilings in the module. Streams are opened, read, and closed serially; changed size, mtime or file
identity refuses admission. Symlinks, Windows junctions/reparse points, path traversal and alternate streams refuse.
An actively hostile process swapping paths during open is outside this offline reader's trust model; source directories
must be controlled by the operator. Do not use a growing capture file as an input.

The diagnostic CLI is:

```text
python -B -m maker_core.replay run --bundle <closed-day-dir> --policy blind_re1 --out <new-dir> --diagnostic-only
```

`-B` suppresses import-cache writes. Paths are explicit and output parents must exist. Output must be a new directory,
disjoint from the entire bundle tree in either direction. JSON and Markdown are create-only; a filesystem write failure
can leave a partial output directory and never triggers cleanup or reuse of that directory. The same bytes and arguments
produce the same reports, with no generation time, elapsed duration or absolute input paths embedded.

`--max-input-bytes`, `--max-records`, `--max-seconds` and `--max-output-bytes` lower hard limits. Time checks occur between
bounded reads, records and report phases; one serialization or filesystem write may finish after the deadline. Exit 0
means envelope diagnostics completed, even with exclusions; exit 2 means refused invocation/input or an exceeded cap.

Heavy execution still requires the [workstation wrapper](HOST_LOAD_POLICY.md#workstation-and-portable-executor-scope).
Its current offline-module allowlist does not admit `maker_core.replay`. Until a reviewed admission update lands, exercise
this entrypoint through the fixture-only pytest suite under that wrapper. This contract does not authorize bypassing or
modifying the installed launch guard. Production uses its own admission policy for the exporter described below.

## Diagnostic and scoring boundary

The default is diagnostic-only for both provenance labels. Selecting `--policy` records the requested name but does not
execute it. Reports contain raw record counts, input hashes and per-condition book-capture coverage with missing-minute
exclusion intervals. Multiple book captures in a minute count once. Coverage is measured only over declared active
intervals; omitted conditions or narrowed intervals cannot be discovered by this reader. `evaluable_minutes` is null,
not the count of captured books. Present but malformed books do not become valid decisions. No P&L, rewards, fill rates,
returns, comparisons or confidence intervals are emitted. Parity is explicitly `NOT_RUN`.

`--compare` requires `--pre-registration` and `--pre-registration-sha256`. The exact raw-byte hash and owner must first
be enrolled in `replay.authorization.APPROVED_REGISTRATIONS` through a separate owner-approved code review. The table
is deliberately empty in this fixture-only build. An arbitrary caller hash, boolean or synthetic label cannot enroll an
approval, and an unenrolled request refuses before bundle or registration IO. This is **review-attested hash pinning**,
not cryptographic signature verification. The owner signs the registration in the review process; the signature field
records its review reference and is not itself trusted. No key, private material or signing identity is invented here.

An approved artifact must specify owner, signature reference, UTC signed_at, hurdles, dates, market clusters, all four
policies, both clustering schemes, replay_config, bootstrap_replicates, bootstrap_seed, and both net metrics. Exact scope
and configuration equality is checked before scoring. Repeat `--bundle` for closed UTC days in comparison mode; total
bytes/records and the whole-run clock remain bounded. `--hazard-per-minute`, `--initial-cash`, bootstrap options and all
other ReplayConfig defaults must match the registered artifact. Diagnostic mode accepts one bundle and suppresses
scores even after authorization machinery exists; registration flags require explicit `--compare`.

`replay.report.comparison_report` is the pure fixture/library composer used by tests. It always renders both fill bounds,
input hashes, exclusions, band-day scores, matched-control status, paired intervals and explicit parity limitations.
JSON and Markdown are deterministic and bounded. Libraries are not a security sandbox; production operators must use
the gated CLI and the repository's admission path.

## Remaining adapters and acceptance

### Event engine

`maker_core.replay.engine.replay(bundles, ReplayConfig(...))` runs the shared pure
`decide()` against typed records in capture order. `payloads.decode` validates
descriptors (market plus plugin-owned local horizon and optional exposure factors),
both-token books, reward terms, available/unavailable views, event snapshots,
trades and reconciled settlement facts. Object payloads use the existing contract
field names serialized by `maker_core.evidence.journal.plain`; views are wrapped
as `{available, value}` and event snapshots as `{events}`. No provider clock may
exceed the envelope capture time; known scheduled event times may be in the future.

All conditions share cash reservations and wallet/event/factor caps. Timers cover
scheduled pulls, event expiry, view expiry, reward freshness, capture gaps and the
last three hours. Decidedness latches; fresh captured book/view inputs are required
after an information pull. Safety cancellation precedes replacement cooldown.
Replacing an eligible quote waits 60 seconds from its previous placement.
Same-time prints are processed against previously resting orders before inputs
or replacements. The fill facade copies the 89a price/size predicate at
`de76a4a9b67b25781c6c6f33b10691841e8630cc`; its original module is unchanged.
Strictly-through is primary; at-price is a sensitivity. Public prints are a price-path
counterfactual without a queue model or aggressor-side filter. Both orders, including
any unfilled remainder, are pulled immediately after the first fill. Equal-time
prints cannot consume a replacement. Duplicated trade IDs are idempotent; conflicting
duplicates refuse. Buy costs reduce shared cash and settlement credits reconcile lots.

`coverage` payloads contain `trade_stream_ok` and `valid_until_utc` (at most 60 seconds
after capture). A book alone cannot establish a zero-fill interval. Missing/expired
trade coverage excludes the interval. Producers must derive this assertion from
captured lifecycle/heartbeat evidence; they must not infer it from an empty tape.

Public books omit our hypothetical orders. Before calling the shared kernel,
replay restores matching own levels that the kernel removes, preserving measured
competition without introducing a new best price. Between captures, books are
held for at most 60 seconds; a gap withdraws quotes and produces excluded spans.
This is a disclosed sampled-book approximation, not a live freshness relaxation:
the shared kernel's ten-second submit freshness still applies at every decision.
Both input event count and combined decision/span count have hard ceilings.
Multi-day replay spans at most 366 calendar days, including gaps. Simultaneous
band cash admission is deterministic by condition ID, not an optimized band-selection
claim. Inventory is held with reduced available caps; no liquidation strategy is
invented. Late prints predating the currently resting order are explicitly excluded.

### Weather exporter

`weather.market.maker_replay_bundle` reuses 110h's `maker_plugin_capture.Reader` and `Segment`, outside the pure provider
package. Only manifested sealed 88a segments are opened; gzip, reward references and book shards are hash-verified.
Plugin support uses the same explicit captured-table/CAS paths as 110h, not live collectors. Those supporting tables are
not 88a seals: files must remain unchanged during and across reads through the end of projection, and original per-row
capture clocks and raw file hashes are retained. A changed source refuses the export. No production qualification of
these assumptions is implied by fixture tests.

```text
python -B -m weather.market.maker_replay_bundle bundle --date YYYY-MM-DD --data-root <data> --markets nyc --out <new-dir>
```

The date must be closed in UTC. Input cap is 1 GiB, output cap 64 MiB including manifest/export metadata, record cap
100,000, and time cap 300 seconds; all can be lowered. Outputs are `bundle.json`, `events.jsonl`, and `export.json`
(the last records projection diagnostics and all source hashes). No source writes, growing 88a segments, status files,
network calls or credentials are used. Refusal before writing produces no directory; an IO or final validation failure
can leave an explicitly incomplete output directory, never reused. Output must be new and outside every input tree.

Discovery supplies observed conditions; declared windows cover the whole UTC day so missing before/after-book periods
remain exclusions. Conditions unseen in discovery cannot be counted. Derived views and clocks are sampled at book
captures; raw plugin rows retain their original clocks. Stream coverage uses connected/inbound evidence and expires
after 30 seconds; unrecorded PONGs cannot renew it. This deliberately excludes silence unsupported by retained health
evidence. Public trades without venue IDs use content hashes, conservatively deduplicating identical simultaneous
messages. A clock parse/join failure invalidates any earlier clock snapshot.

Repeat `--carry-bundle <earlier-bundle>` (maximum eight) for prior descriptor/band metadata when exporting a later
settlement day without books. It does not import account cash or lots. Such conditions have empty active intervals;
their captured reconciled facts can settle the engine's lots from earlier supplied days without adding quote minutes.
The weather provider's reconciliation status `match` and neutral fixture status `reconciled` are both admitted.
Both input and output limits still apply. Actual production bytes/day are unknown until an authorized diagnostic export.

The implementation includes typed payload validation, the shared-`decide()` event engine and portfolio reservations,
both fill bounds and sibling cancellation, reward/fee/markout/settlement scores, baselines, and date/crossed inference.
The Phase 0 RE-1 fixture proves first-price parity only; sanitized full-session journals are unavailable.
Reports must distinguish all such limitations from passed checks and retain the design's replay optimism assumptions.

## Update when

### Scoring

Inference sums paired band-day net differences within each market/UTC-date and
averages complete market/date cells. Any incomplete/unpaired band drops its entire
cell. Date bootstrap resamples whole dates; crossed bootstrap independently draws
dates and markets with multiplicity, then multiplies their weights. It reports 90%
percentile intervals, fixed seeds, counts and empty intersections. Fewer than ten
dates (or ten markets for crossed inference) is UNDERPOWERED. The displayed normal
80%-power MDE approximation is descriptive; even ten clusters do not establish
power. No estimate is a promotion decision or permission to score real data.

Baselines are `no_quote`, `blind_re1`, and `clock_only`. Clock-only runs shared
informed quoting safety with unavailable fair value and no information events.
Its UTC active-interval prefix windows are predeclared for each replay. A bounded
12-step duration search matches aggregate pulled fraction to within one covered
minute; exposure alone selects the schedule. This retrospective matching is
descriptive, not a deployable policy. Additional safety/cash pulls may prevent a
match; such results report UNMATCHED and are excluded from clock inference.
Full-trace parity compares every supplied decision field and terminal event.
The owner-authorized RE-1 journal projection now retains all recorded minute
decisions and terminal outcomes, with source hashes and guard-first derivation.
It exposes policy differences and transport states the neutral kernel cannot
replay; full-session parity is **NOT QUALIFIED**. See the
[110l qualification](../roadmap/agent-report-2026-09-110l-maker-replay-harness.md#recorded-session-qualification--2026-09-26-owner-authorization)
for the per-session byte comparisons and their exact projection limits.
Blind RE-1 treats each UTC capture day as one retrospective session, ending after
its first fill and restarting on the next day with the shared inventory/cash carried.
This daily convention is not evidence of full live-session parity.

`replay.score.score(result)` produces per-policy, per-condition, UTC-day rows.
Reward accrual uses contemporaneous share and terms, with k=1 and k=0.5. Maker fees
are zero; the nominal rebate is `shares * .25 * .05 * p * (1-p)` (EF §10o), not a
cash credit. The engine has no taker-exit strategy or optional builder fee.
Markouts use each bought token's first two-sided midpoint at/after 1/5/30 minutes,
within 120 seconds, copied from the public-tape markout convention. Missing marks
remain null with missing counts. Markouts are alternative valuations, not added
to settlement P&L. Reconciled payout less purchase cost is attributed to the fill
date. Inventory cash-hours continue outside quote windows to settlement or the
last bundle's UTC boundary; unresolved inventory is explicitly counted. No carry-in
inventory is assumed. Missing coverage or unresolved fills suppress modeled net
totals for that band-day. Cash-hours, observed pull fraction, replacements and
inside/outside-event fill counts are retained separately from economics.

Update when the envelope, payload validation, time/byte limits, export path, scoring admission or report semantics change.
