# LOW-ASK-1 captured-input contract

Status: freeze candidate. Owns the exact offline interface consumed by
`weather.backtesting.low_ask`; the F3 builders own export and capture. Read this
before producing a LOW-ASK-1 pack. The contract opens no historical input and
permits no agent to inspect trial values. [Prereg](PREREG_LOW_ASK_1.md) owns the
policy and deciding look. No capture configuration change is part of this package.

## Scope and closed physical inputs

Only International Polymarket **lowest** events for the twelve slugs in
`contracts.CITIES`, local target dates 2026-11-17 through 2027-01-30 inclusive.
There is one event per city-date. Missing events remain scheduled zero
opportunities. Never export highest, other cities, expansion-study loggers,
pilot/account records, model vectors, forecasts, Gamma display prices, NO
complements, reconstructed labels, rewards or trades. No wildcard reader,
directory discovery, source fetch or retrospective observation reconstruction.

`INPUTS.json` is the only entry. It lists every physical staged file and its
exact immutable byte/hash lineage. The reader opens only the staged `path`s,
never `source_files.physical_path`. Local paths use plain forward-slash relative
components; absolute, parent, stream, symlink and Windows reparse paths refuse.
All JSON fields below are mandatory and unknown fields refuse. UTF-8 JSON,
unique object keys, no NaN/Infinity. Decimal values are finite **strings** or
integers, never binary floating-point numbers. UTC clocks are ISO-8601 ending
`Z`; local dates are ISO dates. Prices are dollars per YES share; sizes are YES
shares; native temperatures are explicitly C or F. No field name ending `_c`
changes the declared unit.

The cumulative pack is bounded to 64 MiB of staged JSONL and 200,000 rows, at
most 10,000 files and 1 MiB per row. Export only the required decision-window
books and retained report rows, without price-dependent sampling. Crossing a
bound refuses; master changes a candidate bound before freeze, never silently
truncates a trial pack. A new manifest contains every earlier file unchanged,
and adds only files whose receipt ranges begin strictly after the previous
successful receipt's `as_of_utc`. No delayed export may backdate a decision.

## Manifest (`low_ask_inputs_v1`)

Exact fields:

| Field | Contract |
| --- | --- |
| `schema_version`, `trial` | `low_ask_inputs_v1`, `LOW-ASK-1` |
| `platform` | Exactly `polymarket_international`; compatibility/US inputs refuse |
| `first_date`, `last_date` | Fixed full trial endpoints, even for an early snapshot |
| `as_of_utc` | Cumulative receipt frontier; <= actual wall clock; advances on each successful snapshot |
| `producer_id` | Reviewed exporter identity, fixed in freeze |
| `reader_sha256`, `transform_sha256` | Reviewed reader/export transformation code hashes; fixed in freeze |
| `timezone_sha256` | Effective timezone fingerprint described below; fixed in freeze |
| `timezone_version` | Reviewed deployed tzdata/system-provider version from commissioning receipt; fixed in freeze |
| `latency_receipt` | Object below, identical to frozen object |
| `capital` | Exactly `{"total":"300","order":"15.80","band":"19.60","band_day":"30"}`; no wallet record |
| `files` | Ordered file-spec array, all six roles represented, including empty files |
| `previous_receipt_sha256` | Null first time; thereafter SHA256 of canonical previous public receipt |

File spec exact fields:

`path`, `role`, `bytes`, `sha256`, `schema_version`, `receipt_min_utc`,
`receipt_max_utc`, `source_files`, `chain_id`, `first_sequence`,
`previous_sha256`, `last_sha256`.

`schema_version=low_ask_rows_v1`; `role` is exactly one of `events`,
`observations`, `books`, `heartbeats`, `resolutions`, `integrity`.
`source_files` is a nonempty array of exact objects
`{physical_path, bytes, sha256}` for original capture evidence. It is metadata,
never a permission to read that original file. Actual production roots/names,
sizes and digests come from the capture owners; illustrative names do not prove
files exist. File names and physical paths must be neutral partition identifiers,
never selected-band, price, payout or verdict encodings.

All rows' `received_utc` lie in their declared inclusive receipt range, with its
upper bound <= frontier. Per `(role, chain_id)`, files are in sequence order.
The initial predecessor is 64 zeros; each row hash is SHA256 of its canonical
sorted-key compact ASCII JSON (no newline). Each next row carries that hash in
`previous_sha256`, with integer `sequence` advancing by one. File anchors and
tails must match. Events have no row sequence fields: their position increments
the same file-level chain, hashed from the exact event object. Empty initial
files have `first_sequence=1`, zero predecessor/tail and zero bytes. Their
receipt range is the frontier. Empty files need real empty-export provenance.
`reader_sha256` must equal the frozen `pack.py` source hash. The effective
timezone fingerprint is `contracts.timezone_fingerprint()`: canonical UTC
conversions for every trial local wall hour, both folds, for all fixed city
zones. It must match at runtime, alongside the frozen timezone-version receipt.
Routine events' `parser_sha256` must equal the actual frozen T046
`metar_reports.py` hash; arbitrary adapter hashes refuse.

Hashes establish byte integrity, not the truth of a capture; capture-regime and
scope attestations are separately required in the freeze.

## Event/rule/bin rows (`events`)

Exact fields:

`city family target_date event_id received_utc rule_received_utc rule_sha256
rule_status source station unit zone rounding parser_sha256 fallback_required
source_verified active bins`.

- `family=lowest`; `rule_status=reviewed` for admission; rule text and dated
  source map are hash-bound. Discovery and rule receipts must precede the cut.
- `zone`, `unit` match the fixed city map. Routine-METAR station must match the
  reviewed T046 station. A station drift skips, never falls back to the forecast
  registry. Denver is KDEN; Chicago is KORD.
- `source` is `metar_routine` or `wu_intraday` for an executable candidate;
  missing/unrecognised source rules skip. `rounding=ties_to_higher_integer`
  matches T046's native bucketing, including negative half-degree ties.
- `fallback_required`, `source_verified`, `active` are explicit booleans.
  Event `active` records discovery-time metadata; the execution snapshot's
  `active` is the decisive trading-status check. An inactive initial discovery
  cannot permanently disable an event that subsequently opens before its cut.
  Fallback without a verified received-WU path skips. WU is admitted only with independently verified
  **received intraday station prints** and the exact dated WU station; T046's
  daily WU stub does not establish this. No daily-final value enters decisions.
- `bins` is the complete captured event bin identity map, with unique YES
  tokens. Each exact object is `band_id yes_token lower upper lower_closed
  upper_closed tick min_size`. Bounds are native-unit decimals or null tails;
  closures are booleans. Require exactly one container at the rounded running
  minimum. No band interpolation or inferred label semantics.

Events must be exported when first received, before dependent rows. Event rules
are immutable for this interface. A later rule drift is an integrity defect and
cannot rewrite a prior event row; the master records unavailable future slots
and a failed accuracy gate rather than adapting the rule.

## Observation rows (`observations`)

Exact fields (plus `sequence previous_sha256`):

`event_id received_utc observed_utc source station report_key source_sequence raw
raw_sha256 native_value status parser_sha256`.

`received_utc` is the **first actual service receipt** of these bytes, not the
METAR valid time or a retrospective fetch time. `observed_utc` is the source's
report instant and cannot follow receipt. `report_key` is its canonical UTC ISO
instant, paired with event source/station; replacements share that key.
`source_sequence` is the source-service's monotone order for tied receipts.
Distinct conflicting rows at the same key/order refuse. No source sequence may
be fabricated from lexical report text. Unordered revisions are integrity
failures. Retain reports when subsequent API responses drop them.
Repeated delivery of the same normalized report bytes must retain the same
first receipt; a new receipt on identical old bytes cannot undo a correction.

`raw` contains only that received report/print, not a window with future reports;
`raw_sha256` hashes UTF-8 raw bytes. Routine METAR is reparsed using the frozen
T046 parser, raw T-group precedence and body fallback. SPECI cannot supersede a
routine report. The observation instant must be exactly the parsed instant.
`native_value` is null for METAR; for verified WU intraday it is the native
station print. `status` is `valid`, `defect` or `withdrawn`; defects/withdrawals
cause a failed opportunity rather than optimistic retention. `parser_sha256`
matches the dated event adapter. Export only same-event local-date reports
received by a deciding cut; after-18:00 observations are outside this trial.
The service must preserve late corrections with their actual receipt, so that
17:00 and 18:00 views can differ without a later revision entering 17:00.

## Full YES book rows (`books`)

Exact fields (plus `sequence previous_sha256`):

`event_id received_utc response_utc exchange_utc yes_token book_id full active
integrity_ok asks`.

`response_utc` is the captured response's local observation/completion instant,
`received_utc` the trusted service receipt. Their lag must be 0..2 seconds.
`exchange_utc` must be within one second of `response_utc`, backed by the
capture/clock receipt. Export all full snapshots in each token's fixed cut+L
through cut+L+60s window. No exporter chooses a cheaper snapshot, drops a small
ask or fetches on demand. `book_id` is globally unique to one physical snapshot,
not one consumer. `full`, `active`, `integrity_ok` are booleans.

`asks` is the full captured YES ask depth, strictly increasing distinct prices,
with positive size at each `[price,size]` level. Empty depth is allowed and
cannot fill. Require the selected best level alone to cover five shares.
Size 4.99 does not become five by walking depth. Preserve the remainder as
execution proof. No bid/mid, NO complement, trade price or Gamma display price.
If the F3 fallback misses this token, export the gap, not a replacement book.

## Heartbeats, venue payouts and later integrity

`heartbeats` exact fields (plus chain fields):
`event_id received_utc yes_token ok`. Include the last beat at/before t0-60s
and every beat through execution, per token. A gap >90s or explicit bad beat
fails execution; heartbeat gaps cannot be repaired by reconstructing books.

`resolutions` exact fields (plus chain fields):
`event_id received_utc effective_utc yes_token revision final payout_per_share
treatment evidence_sha256`. This is actual **venue** cash treatment, not our
weather label. Both receipt and venue effective time must have occurred to
release cash. Monotone positive `revision` is per event/token. All tokens with
paper holdings need actual payouts; `normal` final pays 0 or 1; `void`/`refund`
may pay any captured cash amount in [0,1] per share. Fees/reserve remain costs.
Corrections are append-only and can debit cash. A finality reversal fails
accuracy; no optimistic new capital is created. The look uses no selectively
backfilled post-look payout.

`integrity` exact fields (plus chain fields):
`event_id received_utc book_id ok evidence_sha256`. A later bad proof does not
drop the opportunity. For a doubtful fill, set its payout to zero in the loss
bound and fail accuracy. A whole-pack hash defect refuses the snapshot; the
master retains its scheduled population and records integrity unavailability.

## Required commissioning and freeze receipts

`latency_receipt` exact fields: `p95_seconds frozen_L_seconds samples
deployed_path_sha256 evidence_sha256 synthetic`. At least 100 synthetic clocks
through the **deployed** decode/decision/account/seal path; nearest-rank p95;
`L=max(30,p95_seconds)`; no price/outcome used. `synthetic=true` does not mean
an imaginary measurement. Supply actual timing and path hashes before freeze.
Separately attest clock discrepancy, full-depth/heartbeat capture and received
source parity. Metadata-only field tests are not deployment proof.

The external canonical `freeze.json` (`schema_version=low_ask_freeze_v1`),
pinned by required `--freeze-sha`, has
the exact fields validated in `runner.validate_freeze`: trial/time, complete
code hash map, prereg/contract hashes, producer/reader/transform/timezone pins,
latency/capital objects, public-key hash, named prerequisite booleans and the
calibration receipt/status, `claimants` (the full frozen profit family), and
absolute `state_root`. The latter binds continuation/locking and the consumed
look marker across every invocation. Every prerequisite boolean must be true. The code
hash map covers every owned Python module plus parser/bucketing/initializer/path
dependencies. Freeze time must be strictly before 2026-11-17T05:00:00Z.
The repository bootstrap/shim bytes are pinned too. The dedicated entry point
retires the benign startup console shim and its stdlib subprocess import from
its own module cache, then denies re-import; other preloaded clients refuse.
`SCREEN_ONLY` cannot PASS; calibration power/size receipt is required for
`CALIBRATED`. Do not fabricate a timing or calibration receipt to bind a draft.

The custodian supplies a JSON **public** RSA key `{n_hex,e}` (3072 or 4096 bits,
e=65537). Its hash is frozen. Private decryption material never enters this
checkout or the unattended process. Windows CNG RSA-OAEP-SHA256 encrypts a
fixed padded ledger payload. The public `low_ask_receipt_v1` has file hashes/lineage,
row/defect counts and ciphertext hash only; economic state, selected bands,
skip reasons, fills and deterministic economic digest are encrypted. The seal
uses a trial-specific OAEP label and random padding; plaintext length is inside.
It also records the neutral `snapshot` path below the frozen root; the next
invocation verifies this prior sealed artifact's digest before continuing.
No tracebacks or input values are printed on refusal. Failed snapshots leave no
plaintext file and never overwrite prior evidence.

Update only before binding the freeze, with matching parser/writer tests.
