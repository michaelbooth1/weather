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
host caps (`HOST_MAX_BYTES` = 70% of 16 GiB, 2^31 records, four hours); a Clarification 2 manifest derives its
ceilings from rehearsed calibration dates and never truncates or samples to fit. Manifest, line, stream and condition
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

A public print is available only at its record's `captured_at` (a fill's `at`); `traded_at_utc` is the venue clock as
recorded and is never moved. The venue clock may lead capture by at most `MAX_TRADE_CLOCK_SKEW` (5 s,
`maker_core.replay.payloads`); a larger lead refuses (`trade_clock_skew_exceeds_bound`). 5 s is about four times the
capture host's clock error bound (~12 ms NTP offset, ~1.2 s root dispersion) and a sixth of the 30-second trade-health
expiry, the shortest clock in the frozen design. A bounded lead cannot change a fill: the order-age check compares
against a placement at or before capture, so the venue time and the capture time give the same verdict. This matches the
execution addendum's rule that calibration timestamps are capture timestamps.

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
Under the addendum's shared value (`max_outputs` unset) `max_events` also bounds the input record count. Clarification 2
measures records and engine events as separate quantities, so with `max_outputs` set the engine bounds only its
scheduled heap events by `max_events`. Records are then bound by `max_records`: at load, in manifest build, and again
at `engine_preflight` (`engine_record_cap`).
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
messages. A venue trade clock ahead of capture by more than the 5-second bound refuses the day
(`future_public_trade_clock`); within it the print is exported at its capture time with the venue clock kept, and
`export.json` `trade_clock_skew` reports, in microseconds of venue minus capture, the bound, trade count,
`leading_capture` (prints whose venue clock led capture), min, nearest-rank p50/p90/p99/p99.9 and max. A clock parse/join failure invalidates any earlier clock snapshot. `ReleaseSources` stores its release-method
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
reader coverage (growth and skipped tails), the exporter's `trade_clock_skew` (under `bundle`), runtime and peak
process memory. The `bundle` summary (v0.1 and v0.2 night/calibration receipts) also carries
`clock_trigger_rows_skipped`: the plugin clock's trigger-row refusals by code, from the reader-coverage keys
`clock.trigger_rows_skipped.<code>`, with `observed_at_unparseable` always present (an explicit 0). It stays in the
receipt when an oversized receipt drops `reader_coverage`. It is a lower bound, not an exact count; see the
`observed_at` contract in [maker-core-contracts.md](maker-core-contracts.md).

Peak memory is driven by output size, not input: on a fixture the segment loop and join peak at about 2.5x the
`events.jsonl` bytes, and each whole-output validation load (once inside the exporter, once more in the receipt's
finalize step) adds about 5.5x. Coverage rows (one per condition at every book or stream capture) dominate a calibration
bundle's records. The exporter frees its record list, joined stream and last segment before validating. That
lifetime-only change leaves bundle bytes identical and cut the fixture peak from about 8x to about 6x output bytes.
Compare a receipt's `bundle.bytes` with `peak_memory_bytes` to see the same ratio on real days.

Reward terms are looked up only when the projection keeps `terms`, so a calibration export never evaluates them. At a
rewards capture only the conditions that capture names, at that clock, are looked up again. A malformed reward capture
falls back to looking up every condition, so its refusal is unchanged. `CaptureIndex` answers reward lookups by bisect
over time-sorted rows and passes only the newest-clock rows to `latest`. Bundle bytes are identical to the full scan
(fixture-tested against the previous exporter). A `MemoryError` during a night or calibration export is caught like any
refusal, so the day gets a `REFUSED` receipt and ledger entry instead of being left attempted with none. Before the
receipt's pre-publish byte check, long `gaps`, `restart_events` and `bundle.gaps` lists are shortened to a prefix.
`events_trimmed.<list>` records each list's full `total`, `kept` and the `sha256` of the full canonical list, so a
sealed day is not refused only for its receipt size.

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

### Panel export gate (maker replay v2)

Owner decision 3 (Swarm M, 2026-10-06) puts the `maker-replay-v2-v1` draft's rule into code: no panel or
settlement-only date's 88a data may be exported before the registration is signed.
`maker_core.replay.export_gate.export_permitted(day, owner_decision=None)` is the single gate; `read_permitted` is the
same function for read-only entry points (the registration says "exported or read").

- **Gated days.** Every UTC day 2026-09-30 through 2026-10-15 inclusive (quote dates 09-30..10-13 plus the
  settlement-only 10-14 and 10-15). A day is a UTC calendar date: it is gated when
  `[day 00:00Z, day+1 00:00Z)` lies inside `[GATE_FIRST_UTC, GATE_END_UTC)` = `[2026-09-30T00:00Z, 2026-10-16T00:00Z)`.
  2026-09-29 and 2026-10-16 are not gated; they meet the exporter's own checks next.
- **Where it runs.** It is the first statement of `maker_replay_night.export_day`, `maker_replay_night_v02.export_day`,
  `maker_replay_bundle.export`, `maker_replay_bundle_v02.export` and (as `read_permitted`) `maker_plugin_runner.run`,
  before any reader, output folder, lock or ledger. That covers every CLI (`replay_export`,
  `maker_replay_night{,_v02}`, `maker_replay_bundle{,_v02} bundle`, `maker_plugin.dry_run`) and the research runner
  `tools/research/maker_replay_v2`.
- **Carried bundles.** Each `--carry-bundle` is gated by its own day, read from its bounded `bundle.json`
  (`carry_bundle_manifest_required` otherwise), before any input is opened: a 10-16 export cannot carry 10-15 rows.
- **Night exports** forward `--owner-decision` to the inner `export`, which gates again with the same decision; a
  refusal by the gate comes before the ledger, so it never burns the day.
- **Structural ratchet.** `tests/market/test_maker_replay_panel_entry_points.py` parses every module under `src/` and
  `tools/`. Any function that reaches a capture reader (`Reader`, `Segment`, `sealed_segments`, `ExportReader`,
  `CaptureIndex`, or a subclass, through any import alias) without passing a gated function must have callers that
  are checked in turn; module-level code, a `main` or a callerless function that reaches one ungated fails. A gated
  function has no decorators and calls the gate, imported from `export_gate`, on its first parameter as its first
  statement.
- **Authorization.** While `export_gate.SIGNED_REGISTRATION_SHA256` is `None`, a gated day can never pass. After
  signature, a gated day also needs `--owner-decision PATH`, verified by
  `maker_core.replay.v2.authorization.verify_export_decision` (unit U4, imported eagerly so `module-hash` covers it),
  which must return exactly `True` and be read-only and idempotent (a night export verifies twice). The verifier
  always gets the wall clock, never a caller's `now`.
- **No override.** There is no parameter, environment variable or flag that skips it.

| Refusal code (`BundleError`) | Meaning |
| --- | --- |
| `panel_export_requires_signed_registration` | Gated day and the registration is unsigned (the only outcome today). |
| `panel_export_requires_owner_decision` | Gated day after signature, without `--owner-decision`. |
| `panel_export_authorization_unavailable` | Signed, but the v2 authorization verifier is not installed. |
| `panel_export_authorization_refused` | The verifier did not return `True`. |
| `export_gate_day_required` | The day is not a `date` or a string (a `datetime` is refused, never truncated). |
| `export_gate_noncanonical_day` | The day is not exactly `YYYY-MM-DD` (e.g. `20260930`). |
| `carry_bundle_manifest_required` | A `--carry-bundle` has no bounded, parseable `bundle.json`. |

A CLI prints these as `<command> refused: BundleError: <code>` and exits 2, with nothing written.

**Thread pins (owner decision 2).** OpenBLAS reads `OPENBLAS_NUM_THREADS` once, at load, and the exporter imports
numpy (through scipy) before `main` runs, so the pin must come from the launcher. `maker_replay_night_v02`'s `night`
and `calibration` commands only verify, through `maker_core.replay.v2.threads.check_thread_pins`, that
`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `NUMEXPR_NUM_THREADS` all equal `1`; otherwise they
refuse `blas_threads_not_pinned` before any output (after the panel gate). Every v0.2 receipt carries `threads`:
the four values as seen, `pinned`, `logical_cpus` (`os.cpu_count()`), the `threadpoolctl` version (or `"absent"`)
and the actual `pools` (API, library prefix, `num_threads`). In-process callers of `export_day` that pass no
`environ` are recorded, not refused.

### Scheduled production export

`scripts/ops/replay_bundle_export_nightly.ps1` is a roll-free wrapper. It launches the **v0.2** exporter
(`maker_replay_night_v02 <night|calibration>`, `-Kind`, default `night`).

**Panel gate first.** A `-Day` (default yesterday, UTC) in 2026-09-30..2026-10-15 writes
`REFUSED: PANEL_GATED <day> ...` to stderr and exits **3** before the time window, path checks, self-hash, lease,
Python or any output. Exit 3 is an expected refusal, not a failure; the task refuses every night from 10-01 to 10-16
until the wrapper is changed. There is no override; exporting a panel day after signature needs a reviewed wrapper
change and a re-pinned `-ExpectedSelfSha256`.

**Two trees that never mix** (exact-tip deploy, as `maker_replay_exam_step.ps1`):

- `-DeployRoot` is the exact-tip code tree and must be the absolute, normalized path of the tree that holds the
  invoked wrapper (otherwise `DeployRoot must own the invoked wrapper`). **Always pass it explicitly.** Its declared
  default is computed from `$PSScriptRoot` in the `param` block, which is empty under `powershell.exe -File` in
  Windows PowerShell 5.1, so a run that omits it fails parameter binding with exit 1 before the panel gate (a gated
  day then exits 1, not 3). The registrar always passes it.
  Its `src` is the child's only `PYTHONPATH`, and it is the child's working directory.
- `-ProductionRoot` (mandatory) supplies `venv\Scripts\python.exe`, run as `python -P -B`, the memory guard status
  `data\logs\memory_commit_guard_status.json`, `scripts\ops\workload_admission.ps1` (lease and host assignment) and
  the host assignment config.
- The two trees, and the output root and the deploy tree, must be disjoint. The deploy must contain
  `src\maker_core\replay\export_gate.py`.
- Before launch, a `__file__` probe (in its own limited Job) imports `weather.market.maker_replay_night_v02`,
  `maker_core.replay.export_gate`, `maker_core.replay.v2.writer` and `maker_core.replay.v2.threads` with the same
  interpreter, flags and `PYTHONPATH`, and refuses `module-path probe failed` unless every file resolves inside
  `<DeployRoot>\src`.

**Admission per export.** Immediately before the launch, after the probe, available physical memory
(`GlobalMemoryStatusEx`) must be at least `-MinAvailableMiB` (mandatory, 512..65,536). Otherwise the wrapper throws
`REFUSED: available physical memory ... not waiting` at once; it never waits for memory. Each wrapper run is one
export, so every export is admitted on its own reading. The commit-charge (< 70%) and 50 GiB free checks still
apply.

**Job-level ceiling and priority.** The venv `python.exe` is a redirector that starts the real interpreter as its
child, so limits on the started process alone would miss the exporter.
`scripts/ops/replay_export_limited_job.ps1` (`Weather.Operations.ReplayExportLimitedJob`) creates a kill-on-close Job
with `JOB_OBJECT_LIMIT_JOB_MEMORY` and `JOB_OBJECT_LIMIT_PROCESS_MEMORY` at 2 GiB of commit and
`JOB_OBJECT_LIMIT_PRIORITY_CLASS` BelowNormal for every member. On a memory-limit notification its watcher terminates
the whole Job (exit code `0xE0E0E0E0`) and records the kind and the process that hit it. The wrapper also polls the
summed working set of every Job member at 250 ms against 2 GiB. On exit it prints one JSON line: available MiB at
launch, the Job's peak commit, the peak summed working set, whether and where the limit was hit, and the exit code.

The thread variables are set to `1` just before the probe, in the wrapper's own process environment, which both
children inherit. It admits only the assigned capture host and holds the shared heavy-work lease. Starts are limited
to 00:30–04:54 America/Toronto, a strict subset of the heavy lane. The child gets at most 2,700 seconds of cooperative
budget (`--max-seconds`) inside a 2,730-second outer deadline and stops by 04:54:45 at the latest, reserving 15 seconds
for teardown/lease release before 04:55. Unproved teardown poisons the lease. A busy lease fails without waiting or
automatic catch-up.

`scripts/ops/register_replay_bundle_export_nightly.ps1` requires `-DataRoot`, `-ReleaseRoot`, `-OutputRoot`,
`-ExpectedModuleSha256` (from `python -P -B -m weather.market.maker_replay_night_v02 module-hash` with
`PYTHONPATH=<deploy>\src`), `-ExpectedRunnerSha256`, `-ProductionRoot` and `-MinAvailableMiB`. Its `-RepoRoot`
is the deploy tree and is passed to the runner as `-DeployRoot`; pass it explicitly, because its `$PSScriptRoot`
default has the same `-File` defect. `-WhatIf` checks paths, disjointness and the runner hash only, not the module
hash, the time zone or the host assignment. It refuses equal or
nested deploy and production trees. Use `-WhatIf` first: it checks the runner pin without touching Scheduler. Registration
binds 00:35 daily, S4U/Limited current user, IgnoreNew, a 50-minute Scheduler ceiling and no StartWhenAvailable. It
reads back the complete action, principal, trigger and safety settings. The runner is pinned by its own hash and the
exporter's module-closure hash, not by a Git tip; a change to any imported exporter module stops the export until the
registrar is re-run with reviewed pins. Registration and production qualification belong to the production operator;
fixture tests and a draft PR grant neither. The task can contend with other heavy jobs at 00:35 and visibly refuses a
busy lease; choosing a different schedule needs a reviewed registrar change.

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
Reward accrual uses contemporaneous share and terms, with the registered k=1 and k=0.5,
plus Clarification 2's measured-reaction sensitivity k=0.3 (`reward_k03`/`modeled_net_k03`
and their paired intervals): the per-session reward multiplier of the three RE-1 sessions that ran about one hour
(0.27–0.32); the pooled 60-minute k over all nine posting episodes is 0.67, raised by short sessions that ended
before the decay (111f amendment 1). k=0.3 is reported only: no hurdle, estimator or decision reads it. Maker fees
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
checks the raw manifest hash and regenerates all bindings. Under Clarification 2 the CLI refuses before the scoring date
(below); verification does not enroll a hash or execute a policy. All JSON outputs are create-only and capped; failures never truncate or select a sample.

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

[Clarification 2](../research/maker-replay-clarification-2-2026-09-29.md), signed by the owner on 2026-10-01
(DECISION_LOG), changes only operational execution; this section describes the tooling built to it. Authorization ID
`maker-replay-2026-10-15-v2` must bind the raw SHA-256 of the registration, addendum, Clarification 1
(`clarification_sha256`) and Clarification 2 (`clarification_2_sha256`). The verifier pins those four signed hashes,
scoring date 2026-10-15 and an `expires_at` no later than 2026-11-01T04:00:00Z (`SIGNED_BINDINGS` and
`EXPIRES_NO_LATER_THAN` in `src/maker_core/replay/authorization.py`): a v2 row missing the second hash, or binding any
other hash, date or later expiry, refuses. v1 rows still verify under their old rules.
Every manifest, run and verify command takes `--clarification-2` (v3, below, also takes `--clarification-3`).

- **Quote markets (rule).** `python -m maker_core.replay quote_markets --calibration-bundle <3 dirs> --out <json>`
  writes the sorted cities of the three calibration bundles. `calibrate_hazard` and manifest build/verify refuse any
  other list (`quote_markets_rule_mismatch`); there is no hand list.
- **Rehearsal.** `rehearse --bundle <one calibration-date panel-format bundle> --calibration <json> --out <json>`
  runs the complete scored pipeline (both fill bounds, all four policies, matched-clock trials, bootstrap and report
  rendering) score-free on that one date. Run it once per calibration date, each in a fresh process, so peak memory is
  per date. It keeps only input bytes, records, the largest engine event count, the largest decisions+spans count,
  rendered report bytes, runtime, peak memory above the pre-input baseline and that baseline, plus per-pass counts.
  Any other date refuses from the path before a byte of the bundle is read.
- **Ceilings (rule).** `derive_ceilings --rehearsal <09-27> --rehearsal <09-28> --rehearsal <09-29> --out <json>`
  takes each quantity's largest date × 15 (fourteen quote dates plus settlement), rounded up to the next power of two in
  its natural unit (bytes, records, seconds); the rounding is the only headroom. So each calibration date's rehearsal
  must finish in about 546 s or less (8,192 s is the largest power of two within 4 h) and peak about 546 MiB or less
  above the baseline (8 GiB plus the baseline within 70% of 16 GiB). The memory ceiling is that value for peak-above-baseline plus the largest baseline, not multiplied.
  Decisions+spans bind `ReplayConfig.max_outputs`, separately from `max_events`; report bytes bind the report ceiling.
  Host limits: memory and memory-resident input/report bytes ≤ 70% of 16 GiB, runtime ≤ 4 h, counts ≤ 2^31. If any
  ceiling exceeds its limit the file says `executable: false` and `verdict: "not executable on this host"`,
  `derive_ceilings` exits 3, and manifest build refuses `not_executable_on_host:<field> (not executable on this host)`.
  The panel is never sampled or truncated to fit. Manifest build refuses a measurement whose `calibration_sha256` is
  not the sealed calibration JSON's hash (`ceiling_measurement_calibration_mismatch`). At `engine_preflight`, before
  reservation, the run counts the pull endpoint's candidates: the minute starts in each condition's union of active
  windows, which equals the scored loop's count. If that count exceeds `max_events`, the run refuses
  `pull_opportunity_cap` there without consuming the look. The manifest binds the measurement (per-date values, rehearsal hashes) and derives
  every CLI ceiling, the engine ceilings and a sampled process-memory ceiling from it.
- **Universe.** `python -m weather.market.maker_plugin.replay_export universe --bundle <15 panel dirs> --out <json>`
  lists every condition in the bundles with its registered city, target date and IANA timezone from the captured
  descriptor's event slug. The manifest's descriptor check verifies it; it is create-only.
- **Look protection.** A scored run records its stage. Output-directory preflight, the host preflight (system commit
  below 70%, and the whole runtime ceiling fitting inside 00:30–09:00 Toronto), bundle input,
  manifest verification, scope binding, an engine construction check and the action-boundary recheck all precede the
  reservation of `attempts/<id>.json`, which happens immediately before the first policy replay. A refusal in those
  stages writes `attempts/<id>.refusal-<UTC>-<nonce>.json` (`NOT_CONSUMED_OPERATIONAL_REFUSAL`, stage, reason, Toronto
  date) and leaves the look available; manifest build/verify refusals after the owner decision verifies do the same.
  A failed reservation that wrote no `attempts/<id>.json` records the same non-consuming refusal at stage
  `reservation`; one that wrote it is consumed. After reservation any stop writes `<id>.stopped.json` with its stage;
  the look is consumed.
- **Manifest timing.** `manifest build` and `manifest verify` refuse before the scoring date in America/Toronto
  (`manifest_before_scoring_date_toronto`); the manifest is built, verified and enrolled on or after 2026-10-15.
- **Late look.** A v2 look may run on any America/Toronto date from 2026-10-15 to 2026-10-31 inclusive while no
  `attempts/<id>.json` reservation exists beside the canonical manifest; a reservation consumes the look whatever the
  date. Refusal records do not gate it. The same panel, hurdles, ceilings, manifest and authorization apply on every
  permitted date; the v2 row expires 2026-11-01.
- **Measured-k label.** The registered decision carries `measured_k_sensitivity`: whether the k = 0.3 and k = 0.5
  lower bounds are positive (strictly_through, both economic baselines, both clusters; a missing or non-OK estimate
  is not positive), with per-cell detail. A `REPLAY_HURDLES_MET` status whose k = 0.3 bounds are not all positive gets
  `label: "hurdles_met_not_positive_at_measured_k"`. Neither changes a status, hurdle, reason or decision rule.

### Clarification 3 (v3) reporting

[Clarification 3](../research/maker-replay-clarification-3-2026-10-01.md) was **signed by the owner on
2026-10-01T17:44Z**. It is reporting only, and this section describes the tooling built to it. Authorization ID
`maker-replay-2026-10-15-v3` binds v2's four hashes plus `clarification_3_sha256`, with v2's scoring date, late-look
limit and expiry. Its pin `CLARIFICATION_3_SHA256` in `src/maker_core/replay/authorization.py` is the signed file's
raw SHA-256; a v3 row binding any other Clarification 3 bytes refuses
(`signed_binding_mismatch:clarification_3_sha256`). v1 and v2 rows still verify. A v2 row given `--clarification-3`
refuses `clarification_3_not_attested`. Manifest build and verify, and `run`, take `--clarification-3`, which a v3 row
requires. The manifest builder accepts a v2 or v3 owner decision.

- **Quote presence.** Every comparison report's `bounds.<bound>.quote_presence` gives, for each policy and city-market,
  plus pooled, the covered active seconds, the seconds with a leg resting, and their fraction. The Markdown renders it
  in band-minutes.
- **Decision fields.** A scored look's `registered_decision` is `evaluate_hurdles` unchanged, plus one key,
  `clarification_3` (`maker_core.replay.clarification_3.registered_decision`). That key holds the quote presence, the
  four primary economic cells' SE, `mde_80` and non-significance statement with the binding MDE, and the screen label
  `NOT_MET_SCREEN_SUPPRESSED`. The label applies to `HURDLE_NOT_MET` when informed-v0's pooled strictly_through quoted
  fraction is below 0.5. Status, flags and reasons are tested byte-identical with and without these fields.
- These modules are under `src/maker_core`, so they change the manifest's source hashes. Land them before the ceiling
  rehearsal and before the manifest build.

The workstation wrapper admits exactly `maker_core.replay` as offline heavy work; no venue/runtime wildcard is added.
An installed Codex hook with the older independent module list may still reject this command. This change does not
alter that hook or authorize bypassing it; production must qualify its invoking path under the host-load policy.

Update when the envelope, payload validation, time/byte limits, export path, ceiling rule, scoring admission, look
protection or report semantics change.
