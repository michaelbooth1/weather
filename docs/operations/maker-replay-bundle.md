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

`Limits` defaults to 64 MiB, 100,000 records and 300 seconds. An explicit ceiling may be raised only up to the 16 GB
host caps (`HOST_MAX_BYTES` = 70% of 16 GiB, 2^31 records, 2,700 seconds); a Clarification 2 manifest derives its
ceilings from a measured calibration day and never truncates or samples to fit. Manifest, line, stream and condition
counts keep fixed ceilings in the module. Streams are opened, read, and closed serially; changed size, mtime or file
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

`--compare` requires `--pre-registration` and `--pre-registration-sha256` for its execution JSON manifest, plus
`--decision-log`, `--frozen-protocol` and `--execution-addendum`. The exact raw-byte manifest hash and owner must first
be enrolled in `replay.authorization.APPROVED_REGISTRATIONS` through a separate owner-approved code review. The table
is deliberately empty in this fixture-only build. An arbitrary caller hash, boolean or synthetic label cannot enroll an
approval, and an unenrolled request refuses before bundle or registration IO. The owner's signature is a DECISION_LOG
row binding the raw-byte SHA-256 of the frozen protocol and execution addendum. The CLI verifies the exact row,
document hashes and scoring time before bundle IO. This is review-attested authorization, without a signing key.
The [verifier contract](maker-replay-authorization-verifier-design-2026-09-27.md) owns the row format and remaining
one-look gates; real enrollment remains blocked until those gates are implemented and reviewed.

An approved artifact must specify owner, owner_decision, UTC signed_at, hurdles, dates, market clusters, all four
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
Both input event count (`max_events`) and combined decision/span count have hard ceilings. The decision/span ceiling is
`max_outputs`, or `max_events` when unset (the frozen addendum's shared value); Clarification 2 derives each separately.
Multi-day replay spans at most 366 calendar days, including gaps. Simultaneous
band cash admission is deterministic by condition ID, not an optimized band-selection
claim. Inventory is held with reduced available caps; no liquidation strategy is
invented. Late prints predating the currently resting order are explicitly excluded.

### Weather exporter

`weather.market.maker_replay_bundle` reuses 110h's `maker_plugin_capture.Reader` and `Segment`, outside the pure provider
package. Only manifested sealed 88a segments are opened; gzip, reward references and book shards are hash-verified.
Plugin support uses the same explicit captured-table/CAS paths as 110h, not live collectors. Those supporting tables are
not 88a seals. They are live append-only files, so `ExportReader` pins each plain file at the size first seen and every
later read of it in the same export takes exactly that prefix. Growth by appends is accepted at recheck only when the
pinned prefix still hashes the same (counted as `append_only_growth_accepted`); truncation, replacement or an edited
prefix refuses. A partial final line of a live file is skipped and counted as `unterminated_tail_skipped.<source>`,
never parsed. Gzip members, release files and sealed 88a files must stay byte-identical. Original per-row capture clocks
and the hashes of the exact bytes used are retained. No production qualification of
these assumptions is implied by fixture tests.

```text
python -B -m weather.market.maker_replay_bundle bundle --date YYYY-MM-DD --data-root <data> --markets nyc --out <new-dir>
```

The date must be closed in UTC. This single-market command defaults to a 1 GiB input cap, 64 MiB output (including
manifest/export metadata), 100,000 records and 300 seconds; explicit values may go up to the host caps. Outputs are `bundle.json`, `events.jsonl`, and `export.json`
(the last records projection diagnostics and all source hashes). No source writes, growing 88a segments, status files,
network calls or credentials are used. Refusal before writing produces no directory; an IO or final validation failure
can leave an explicitly incomplete output directory, never reused. Output must be new and outside every input tree.

Discovery supplies observed conditions; declared windows cover the whole UTC day so missing before/after-book periods
remain exclusions. Conditions unseen in discovery cannot be counted. Derived views and clocks are sampled at book
captures; raw plugin rows retain their original clocks. Stream coverage uses connected/inbound evidence and expires
after 30 seconds; unrecorded PONGs cannot renew it. This deliberately excludes silence unsupported by retained health
evidence. Public trades without venue IDs use content hashes, conservatively deduplicating identical simultaneous
messages. A clock parse/join failure invalidates any earlier clock snapshot. `ReleaseSources` stores its release-method
projection back into the event cache entry, so each event's projection and fair-value/clock/settlement providers are
built once per cached load, not once per book capture.

Repeat `--carry-bundle <earlier-bundle>` (maximum eight) for prior descriptor/band metadata when exporting a later
settlement day without books. It does not import account cash or lots. Such conditions have empty active intervals;
their captured reconciled facts can settle the engine's lots from earlier supplied days without adding quote minutes.
The weather provider's reconciliation status `match` and neutral fixture status `reconciled` are both admitted.
Both input and output limits still apply. Actual production bytes/day are unknown until an authorized diagnostic export.

### Nightly and calibration day bundles

The command facade `weather.market.maker_plugin.replay_export` delegates filesystem orchestration to
`weather.market.maker_replay_night`, outside the pure providers. It reuses the 110l exporter:

```text
python -B -m weather.market.maker_plugin.replay_export module-hash
python -B -m weather.market.maker_plugin.replay_export night --day YYYY-MM-DD --data-root <data> --release-root <immutable-releases> --out <panel> --expected-module-sha256 <hash>
python -B -m weather.market.maker_plugin.replay_export calibration --day 2026-09-2[789] --data-root <data> --out <calibration> --expected-module-sha256 <hash>
```

`module-hash` prints the SHA-256 of every repository source module the exporter process has imported (file content,
not a Git tip) and reads no data. With `--expected-module-sha256` an export refuses before creating any output unless
that closure matches; it also refuses if an imported module changes during the export, and records modules first
imported during the run. The receipt always carries `module_sha256`.

Each day produces **one all-city bundle directory** containing every discovered registered city, so
`maker_core.replay.pack_io.load_days` admits one directory per UTC date. `night` keeps every record kind. `calibration`
keeps only `descriptor`, `coverage` and `public trade` records, from the same sealed 88a sources, the same projection and
the same hashing, and refuses any date other than the three calibration dates before reading data. A weather condition
enters a bundle only with a captured book for both tokens (the descriptor requires them), so a calibration bundle's
city set is the sealed per-date captured-band inventory that Clarification 2's quote-market rule names; the receipt
lists it as `captured_band_cities`.

**Bundles carry no active intervals.** Clarification 2 makes the execution manifest the only source of quote-panel
exclusions (05:00–08:00 UTC maintenance and coverage), so the neutral reader keeps its exact field set and the former
`--exclude-utc` flag is removed. Book gaps are reported over each condition's whole UTC day.

The explicit output root must be disjoint from the entire input tree and have an existing parent. A closed, canonical
UTC date is required. Discovery reads only sealed 88a segments, including gzip and content references. An open segment,
missing projectable city, corrupt hash, changed source, module mismatch or exceeded cap refuses the entire day, never
truncating. Defaults are a 4 GiB input-read budget, 2 GiB of output and 2,700 seconds, each at most the host cap.

The output is `<root>/<day>/bundle/{bundle.json,events.jsonl,export.json}` plus a day `receipt.json` and an append-only
ledger (`panel-ledger.jsonl` or `calibration-ledger.jsonl`). A writer lock serializes admission and ledger appends. The
bundle is written under `<day>/pending` and renamed to `bundle` only after it validates. Only a `SEALED` ledger entry
matching the receipt hash seals the day. A missing/torn ledger entry, `REFUSED`, or partial directory grants no
completeness claim. Retries of any attempted day refuse; preserve the attempt for review and export again only into a
new output root. The exporter never deletes evidence or repairs a torn ledger. Each receipt records bundle file hashes,
bytes, records and conditions, observed free bytes, discovered cities, book gaps, recorded lifecycle events, final
reader coverage (growth and skipped tails), runtime and peak process memory.

The optional explicit `--release-root` (also supported by the single-city exporter) supplies immutable release directories.
`maker_replay_release.ReleaseSources` binds the captured source's release ID/content-manifest hash to the one declared
`base_model.<city>.probability_calibration` inventory role, checks its JSON size/hash, then projects `market_bin.method`
onto each verified source row as `release_calibration_method`, plus `release_calibration_artifact_sha256`. The plugin input
envelope also exposes the method beside `record`. Manifest/artifact reads each cap at 2 MiB, count against the shared
read/time budget and are rechecked before sealing. This verifies that specific export projection, not the entire model
graph's serving readiness. Wrong hashes, ambiguous roles, missing artifacts or a conflicting captured method refuse.
Without an explicit release root, existing captured methods remain available and absent methods stay null; no active
pointer or ambient artifact is consulted. Source files/clocks remain unchanged and the 88a writer is untouched. Run
summaries supply recorded 88a process starts; sealed stream gaps/disconnects, disk brakes and caps are retained
separately. Segment rotation is not called a restart. Crashes without a sealed summary remain explicitly unknown, so
restart coverage is never claimed complete.

### Scheduled production export

`scripts/ops/replay_bundle_export_nightly.ps1` is a roll-free wrapper. It admits only the assigned capture host, holds
the shared heavy-work lease, checks fresh commit charge below 70% and 50 GiB free, and owns the child in a kill-on-close
Job. Starts are limited to 00:30–04:54 America/Toronto, a strict subset of the heavy lane. The child gets at most
2,700 seconds of cooperative budget (`--max-seconds`) inside a 2,730-second outer deadline and stops by 04:54:45 at the
latest, reserving 15 seconds for teardown/lease release before 04:55. A 2 GiB monitored child memory ceiling also
refuses; the exporter itself launches no descendants. Unproved teardown poisons the lease. A busy lease fails without
waiting or automatic catch-up. The default day is yesterday in UTC, not local time.

`scripts/ops/register_replay_bundle_export_nightly.ps1` requires `-DataRoot`, `-ReleaseRoot`, `-OutputRoot`,
`-ExpectedModuleSha256` (from `module-hash` in the same checkout) and `-ExpectedRunnerSha256`; `-RepoRoot` defaults to
its own checkout. Use `-WhatIf` first: it checks pins without touching Scheduler. Registration binds 00:35 daily,
S4U/Limited current user, IgnoreNew, a 50-minute Scheduler ceiling and no StartWhenAvailable. It reads back the complete
action, principal, trigger and safety settings. The runner is pinned by its own hash and the exporter's module-closure
hash, not by a Git tip, so an unrelated master commit no longer stops the export; a change to any imported exporter
module does, until the registrar is re-run with reviewed pins. Registration and production qualification belong to the
production operator; fixture tests and a draft PR grant neither. The task can contend with other heavy jobs at 00:35
and visibly refuses a busy lease; choosing a different schedule needs a reviewed registrar change.

The implementation includes typed payload validation, the shared-`decide()` event engine and portfolio reservations,
both fill bounds and sibling cancellation, reward/fee/markout/settlement scores, baselines, and date/crossed inference.
RE-1 qualification uses guarded, minimal recorded-journal fixtures; see the qualification limits below.
Reports must distinguish all such limitations from passed checks and retain the design's replay optimism assumptions.

## Update when

### Scoring

`replay.pull_efficiency.pull_efficiency` reports the registered five-minute YES-midpoint move endpoint alongside
economic intervals under both fill bounds. It samples the post-decision resting state at each UTC minute, forms a
common covered opportunity set, verifies its own one-minute pull-count match, and resamples paired counts by date
and crossed date x market. Zero pull denominators or zero clock removed moves are UNIDENTIFIED. The point ratio
threshold and all endpoint conventions are owned by the [registration](../research/maker-replay-hurdles-preregistration-2026-09-27.md)
and [execution addendum](../research/maker-replay-execution-addendum-2026-09-27.md); endpoint success is not a combined
economics/admission verdict. JSON contains counts, exclusions, band-days, intervals and omitted replicate counts.

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
All 313 recorded minutes match the pinned live observer and carried-state
lifecycle. Five terminal projections still have named source-revision/input
coverage findings; full-session parity is **NOT QUALIFIED**. See the
[110l continuation](../roadmap/agent-report-2026-09-110l-maker-replay-harness.md#re-1-behavior-port--2026-09-27-continuation-from-0bd7adf98)
for the per-session byte comparisons and their exact projection limits.
Blind RE-1 treats each UTC capture day as one retrospective session, ending after
its first fill (or six-hour deadline) and restarting on the next day with shared
inventory/cash carried. A six-hour session crossing UTC midnight is refused.
This daily convention is not evidence of full live-session parity.

The blind profile uses RE-1's frozen-size observer: inclusive 1–3 cent hold
window, no share-floor pull or requote cooldown, maximum four requote rounds and
ten submit attempts. It cancels only affected legs, confirms their removal before
posting either replacement, and ends on fills or an ambiguous POST without retry.
Selection uses the 20/30/50/75 ladder and wallet-minus-ten reserve budget; submit
caps are 0.79 times size per leg and min(0.98 times size, reserve budget) per pair.
Fresh submit and post-signing touch checks are separate from resting-price checks.
The informed policy and QuoteDecision schema retain their existing semantics.

The offline lifecycle accepts explicit acknowledgments. The 88a adapter lacks
private acks and post-signing live books, so it records `RE1_TRANSPORT_ASSUMED`
when using instantaneous success and the same captured book. Capture gaps end
that diagnostic session; missing live reads are never presented as successful
parity. The recorded-session tests instead consume retained acknowledgment facts.
Default CLI execution remains diagnostic-only, behind the existing score gate.

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

## Clarified execution pack

The [unsigned prospective Clarification 1](../research/maker-replay-clarification-1-2026-09-27.md) shifts the
registered dates, defines pooled sparse-city fallback, and excludes maintenance. The frozen registration and addendum
are unchanged. Production must sign all three hashes before manifest construction. Publication is not that signature.

`python -m maker_core.replay calibrate_hazard --help` describes bounded calibration on **calibration-only sealed
bundles**, containing only descriptor, trade and coverage records. These use the existing bundle envelope and are
produced by `replay_export calibration` (above) from the allowed 88a streams, with their original source hashes
retained. A panel bundle emits additional kinds and is deliberately refused as calibration input. Do not use an ad-hoc
filter that drops gaps or invalid trade records, or open outcomes to select calibration.
The CLI performs no network access or raw 88a export. Supplying a future seal, duplicate date, changed bytes or incorrect
hash refuses; missing files produce a 1.0 fallback explicitly marked incomplete and cannot qualify a manifest.

The quote-market JSON is a sorted unique array of stable city IDs. Under Clarification 2 it is exactly the rule output of
`quote_markets` (cities with a captured band on any calibration date); any other list refuses. The estimator combines it
with calibration discovery to freeze M. Final panel discovery must reproduce that union;
an unexpected city blocks verification rather than recalibrating after a scored read. Every city reports n/x/dates,
coverage exclusions, numerical brackets, fallback reasons and the selected city/pooled bound. Empty/sparse pools and
uncomputable numerical bounds retain 1.0. Coverage must last for the entire minute, with the exporter's 30-second
expiry. Identical trade IDs count once across the window; conflicting duplicates exclude every affected capture minute.
The CP CDF is evaluated with the pinned SciPy regularized beta and inverted by bisection, retaining the upper endpoint
and rounding upward to twelve places; it uses no normal approximation.

`python -m maker_core.replay manifest build --help` and `manifest verify --help` describe the preparation surface.
Both require all fifteen sealed panel/settlement bundles, the three calibration bundles, the calibration JSON,
the rule-derived city JSON, the ceiling measurement JSON, and a sorted universe JSON array. Each universe row contains exactly `condition_id`,
`market_id`, `domain_id`, `target_date` and `local_timezone`. Every discovered condition is retained, including excluded
conditions; the target and timezone must match the captured descriptor's local midnight close and local horizon.
Missing descriptors or cluster mismatches block. This is a supplied domain-export binding, never a slug heuristic.

The builder checks the explicit owner-decision JSON against the current DECISION_LOG row and all four document
hashes, recomputes calibration and the ceiling rule, then binds every ReplayConfig field, fixed hurdles/bootstrap settings, exact sorted
universe, active intervals, stream/bundle hashes, source-hash digests and operational ceilings. It hashes the complete
maker core, weather plugin/adapter/exporter sources and dependency manifest without importing weather into the core.
Only `approved_registrations.py` is excluded from the executable hash set: enrollment cannot hash itself. The verifier
checks the raw manifest hash and regenerates all bindings. It may run before the scoring date and does not enroll a
hash or execute a policy. All JSON outputs are create-only and capped; failures never truncate or select a sample.

The scored `run --compare` requires independent enrollment, the scoring date, current owner-log verification and every
binding path. It applies the sealed intervals to every policy and clock matching, preserving carried inventory and
settlement while keeping maintenance and the settlement-only day out of quote exposure. The report retains the
selected clock windows. Immediately before the first policy replay it rechecks the owner log and consumes
`attempts/<authorization_id>.json` next to the canonical sealed execution manifest. This is shared across output
directories; failures after it remain consumed, and earlier operational refusals are recorded without consuming
(Clarification 2, below). Never relocate a manifest to evade this receipt. A completed receipt is
additional evidence, never a replacement for the original consumption record. Reports expose the full hurdle
conjunction separately from their counterfactual/transport limitations. No result authorizes live work.

### Clarification 2 (v2) execution

The unsigned Clarification 2 draft (`docs/research/maker-replay-clarification-2-2026-09-29.md`, carried by the 111e
handoff branch) changes only operational execution; this section describes the tooling built to it. Authorization ID `maker-replay-2026-10-15-v2` must bind the
raw SHA-256 of the registration, addendum, Clarification 1 (`clarification_sha256`) and Clarification 2
(`clarification_2_sha256`); a v2 row without the second hash refuses, and v1 rows still verify under their old rules.
Every manifest, run and verify command takes `--clarification-2`.

- **Quote markets (rule).** `python -m maker_core.replay quote_markets --calibration-bundle <3 dirs> --out <json>`
  writes the sorted cities of the three calibration bundles. `calibrate_hazard` and manifest build/verify refuse any
  other list (`quote_markets_rule_mismatch`); there is no hand list.
- **Ceilings (rule).** `measure_ceilings --bundle <2026-09-27 panel-format bundle> --calibration <json> --out <json>`
  runs the complete scored pipeline (both fill bounds, all four policies, matched-clock trials, bootstrap and report
  rendering) on that single calibration date and writes only input bytes, records, the largest engine event count, the
  largest decision+span count, peak process memory and runtime, plus per-pass counts. No score, fill, reward or hurdle
  value is written. Each ceiling is measurement × 15 × 4 rounded up to a power of two in its own unit (bytes, records,
  seconds), compared with the host cap (input bytes and peak memory ≤ 70% of 16 GiB, runtime ≤ 2,700 s). If any cap
  binds, the file says `executable: false` and manifest build refuses `not_executable_on_host:<field>`. The manifest
  binds the measurement and its hash; the CLI ceilings, `ReplayConfig.max_events` and `max_outputs`, and a sampled
  process-memory ceiling come from it. The 8 MiB report ceiling is unchanged.
- **Rehearsal.** `rehearse` is the same score-free pipeline on one to three calibration dates. Both refuse any other
  date from the path before a byte of the bundle is read.
- **Look protection.** A scored run records its stage. Output-directory and host-commit preflight, bundle input,
  manifest verification, scope binding, an engine construction check and the action-boundary recheck all precede the
  reservation of `attempts/<id>.json`, which happens immediately before the first policy replay. A refusal in those
  stages writes `attempts/<id>.refusal-<UTC>-<nonce>.json` (`NOT_CONSUMED_OPERATIONAL_REFUSAL`, stage, reason, Toronto
  date) and leaves the look available; manifest build/verify refusals after the owner decision verifies do the same.
  After reservation any stop writes `<id>.stopped.json` with its stage; the look is consumed.
- **Late look.** A v2 look normally runs on its scoring date. It may run on a later Toronto date up to 2026-10-31 only
  if a non-consuming refusal was recorded on the scoring date and no attempt was consumed; the owner row's `expires_at`
  must then extend to 2026-11-01.

The workstation wrapper admits exactly `maker_core.replay` as offline heavy work; no venue/runtime wildcard is added.
An installed Codex hook with the older independent module list may still reject this command. This change does not
alter that hook or authorize bypassing it; production must qualify its invoking path under the host-load policy.

Update when the envelope, payload validation, time/byte limits, export path, ceiling rule, scoring admission, look
protection or report semantics change.
