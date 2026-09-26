# Maker replay bundle and diagnostic contract

Status: canonical envelope contract; payload semantics and scored replay are unfinished.

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
| `conditions` | Unique binary condition identities with stable `market_id` cluster labels, `domain_id`, and an explicit minute-aligned `active_from` inclusive / `active_until` exclusive interval inside the day |
| `streams` | Objects with `path`, raw-byte `sha256`, `bytes`, and `records`; flat alphanumeric/underscore/hyphen `.jsonl` names only |

Each stream record contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `sequence` | Unique nonnegative integer within the bundle, at most the exact JSON integer bound; breaks capture-time ties |
| `captured_at` | UTC timestamp within the bundle day; never replaced with provider issue or export time |
| `condition_id` | One of the manifest's conditions |
| `kind` | `descriptor`, `book`, `terms`, `trade`, `plugin_input`, `outcome_view`, `info_event`, or `settlement` |
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
records follow the same rule. Later-captured settlement belongs to a later capture-day bundle; multi-day engine joins,
carry-in state and kind-specific validity checks remain to be implemented.

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
modifying the installed launch guard. Production uses its own admission policy and has no new export entrypoint yet.

## Diagnostic and scoring boundary

The default is diagnostic-only for both provenance labels. Selecting `--policy` records the requested name but does not
execute it. Reports contain raw record counts, input hashes and per-condition book-capture coverage with missing-minute
exclusion intervals. Multiple book captures in a minute count once. Coverage is measured only over declared active
intervals; omitted conditions or narrowed intervals cannot be discovered by this reader. `evaluable_minutes` is null,
not the count of captured books. Present but malformed books do not become valid decisions. No P&L, rewards, fill rates,
returns, comparisons or confidence intervals are emitted. Parity is explicitly `NOT_RUN`.

`--compare`, `--pre-registration`, and `--pre-registration-sha256` currently refuse **before input IO**, even together and
even for fixtures. They reserve the intended interface; they do not implement authorization. A user-provided hash or an
`owner_signed: true` field cannot authenticate the owner. A later increment must verify the owner-approved signed artifact,
bind its exact hash, policy/hurdles/date/cluster scope, and obtain the required review before exposing scored real-data
reads. Do not add a permissive fallback. Diagnostic mode must continue to suppress comparisons after scoring is added.

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
or replacements. This increment's trade hook is deliberately inert until the fill
facade is installed. Quotes do not fabricate fills or account state.

Public books omit our hypothetical orders. Before calling the shared kernel,
replay restores matching own levels that the kernel removes, preserving measured
competition without introducing a new best price. Between captures, books are
held for at most 60 seconds; a gap withdraws quotes and produces excluded spans.
This is a disclosed sampled-book approximation, not a live freshness relaxation:
the shared kernel's ten-second submit freshness still applies at every decision.
Both input event count and combined decision/span count have hard ceilings.

The weather exporter must reuse the 110h sealed-segment reader (`maker_plugin_capture`) outside the pure weather-provider
package. It must project both-token 88a v2 books, reward-on-change records and public trades plus captured plugin inputs and
settlement facts, retaining original clocks and source hashes. No export is implemented by this increment. No production
command or per-day measured size is claimed yet; fixture size is not an estimate of production volume.

Subsequent increments add typed payload validation, a shared-`decide()` event engine and portfolio reservations, both fill
bounds and sibling cancellation, reward/fee/markout/settlement scores, baselines, date and crossed date×market inference,
and parity. The Phase 0 RE-1 fixture proves first-price parity only; sanitized full-session journals are unavailable.
Reports must distinguish all such limitations from passed checks and retain the design's replay optimism assumptions.

## Update when

Update when the envelope, payload validation, time/byte limits, export path, scoring admission or report semantics change.
