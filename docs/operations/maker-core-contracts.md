# Maker core contracts

Status: canonical plugin and offline foundation contract.

- **Owns:** the domain-neutral v0.1 plugin surface, conformance procedure,
  pure decision input conventions and evidence format.
- **Read when:** implementing a plugin or consuming `maker_core` proposals.
- **Not here:** current authority ([state of play](STATE_OF_PLAY.md)), architecture
  intent ([design](informed-maker-design-2026-09-25.md)), or dependency rules
  ([package boundaries](package-boundaries.md)).

## Plugin surface

The authority is `src/maker_core/contracts/__init__.py`, with
`CONTRACTS_VERSION = "0.1"`. The production agent creates
`maker-core-contracts-v0.1` after landing; this mission creates no tag.
After publication changes are additive only: do not remove or reinterpret fields,
change units, or add required arguments. A breaking change needs a new version.
The core never passes extra keyword arguments to v0.1 Protocol methods. The
conformance kit's deliberate keyword probe is a test, not a runtime convention.

Implement `MarketUniverse.discover/describe`, `FairValueProvider.evaluate`,
`InformationClock.upcoming/observe`, and `SettlementResolver.resolve`.
`ExposureModel.factors` is optional; absent factors mean independent exposures,
never absence of event and wallet caps. Plugins import only
`maker_core.contracts` (including its conformance module), never quoting or venue.

| Value | Meaning |
| --- | --- |
| `MarketDescriptor` | Domain/event/condition identity, binary token mapping, tick, minimum order size, optional sibling group, UTC close/settle times, native unit, plugin/source provenance |
| `UniverseSnapshot` | Tuple of descriptors, query `as_of_utc`, source hashes |
| `OutcomeView` | Condition, probability and probability-unit stdev (positive, or zero for p=0 or p=1), optional sibling distribution, input timestamp/expiry, input hash/model/grade; no market-price fields |
| `Unavailable` | Reason and UTC query time; never a guessed probability |
| `InfoEvent` | At least one scheduled/observed/detected reference time, affected conditions, severity, optional decided probabilities, action hint |
| `SettlementFact` | Condition, resolved YES payout fraction, captured UTC time, source hashes, reconciliation status |
| `Pending` | Reason and UTC query time; never an inferred settlement |

All datetimes must be aware with zero UTC offset. Mappings are copied and frozen;
probabilities must be finite in [0,1]. Joint mass must sum to one within 1e-9 and
agree with the condition's marginal when that condition is present. Settlement
probabilities admit fractional resolution. Settlement source/reconciliation
policy belongs to the plugin; a fact alone grants no execution authority.

The pre-tag additions are trailing and defaulted:

- `MarketDescriptor.group_relation=None`: optionally `partition` (mutually
  exclusive/exhaustive), `nested_ge`, or `nested_le` (nested threshold direction).
  Nested probabilities are marginals, not partition `joint` mass.
- `InfoEvent.active_until_utc=None`: optional UTC expiry, at or after the detected
  time, otherwise observed time, otherwise scheduled time. A reference is required.
  Expiry is inclusive; a timestamp-free event is invalid even without expiry.
  Detected events, or observed events without detection, remain active from that
  reference time until expiry or caller removal. Detection takes precedence when
  present, so a future detection is not made active by an earlier observation.
- `Unavailable.kind="missing_input"`: alternatives `out_of_scope`, `corrupt`,
  `decided` distinguish why a probability is not supplied.
- `SettlementFact.resolved_value=None`: optional domain-native text, not a payout override.
- `OutcomeView.stdev` also accepts zero exactly when `p_yes` is 0 or 1.

## Conformance and reference plugin

Use `tests/maker_core/fixtures/fictional_domain.py` as the external-team template.
Its four providers happen to share an instance; separate instances work too.
Call `maker_core.contracts.conformance.check_conformance` with `universe`,
`fair_value`, `information`, `settlement`, a `FixtureClock(now, missing_at,
later_at)`, and an `advance_inputs` callback that ingests a future captured record.

Fixtures must exercise missing input, an available view and its expiry. The kit
checks repeatability before/after future ingestion, UTC and probability validity,
joint consistency, expired-view refusal, event capture times, settlement identity,
and refusal or ignoring of an injected `market_price` keyword at 0.01 and 0.99.
This finite test is not a proof of no hidden input: review plugin data flow and
retain captured input hashes. A market price must never enter fair value.

## Pure decision inputs and units

`maker_core.quoting.policy.decide(DecisionInputs)` returns a `QuoteDecision`:
action, immutable legs, reason codes, complete canonical input SHA-256, profile,
qualified market centre, many-maker share and modelled net per minute.
The same inputs produce the same canonical bytes. No IO or wall clock is read.
Both legs are BUYs; a NO buy represents the YES ask side. `prices` preserves the
frozen RE-1 proposer; `rewards` copies the original reward kernels without an
import dependency on weather. Cents and probability units are explicitly named.

The caller supplies both token books, captured reward terms, plugin view/events,
local-date horizon, fill state, reservations and explicit band/order/event/wallet/
factor caps. Portfolio used amounts include inventory and other commitments but
exclude the current band's replaceable orders. Reserve every selected market
before deciding another; `rank` does not reserve funds. Factor loading uses its
absolute value, so offsets never silently increase available capital.

`informed_v0` implements the design's freshness, pull/decided, qualified-mid,
width/asymmetry, depth, size, positive-net and portfolio screens. Scheduled events
are active from -3 to +10 minutes; detected and observed-only events remain active
until explicit expiry or, without expiry, caller removal on captured fresh evidence. Only
`action_hint="pull"` triggers a pull, independent of the domain's event kind.
`Profile.eligible_horizons` owns eligibility (`informed_v0`: 1 and 2;
`blind_re1`: unrestricted). Expired or future views refuse quoting;
explicit `Unavailable` uses blind width with the lowest grade size cap.
Fair value never shifts the centre. Outward snapping steps one tick inward when
needed to keep a leg within the configured hold window.
Information `recentre` hints only widen in v0. Last-three-hour and post-only gates
apply to both profiles. Cancellation precedes the 60-second requote cooldown.
Own resting YES buys and mirrored NO buys are removed from displayed competition
and depth before scoring. Midpoint drift alone holds eligible legs inside the
[1,3]-cent window. The caller supplies `previous_fair_value` to identify a new
view: a half-delta asymmetry change of at least one tick or absolute probability
change above max(effective sigma, 0.01) pulls immediately. Smaller changes that
alter desired legs respect cooldown. Missing view history does not invent a move;
size-cap, touch, depth, share and net safety checks still precede HOLD.

The design leaves stale variance and grade trust constants unspecified. Phase 0
uses an explicitly exposed conservative offline default of 0.01 probability
units of added sigma per hour (quadrature), grade size ceilings 30/50/75 for
none/shadow/scored. Per the owner's MAK-1 decision, grade `none` uses the same
clipped width and size on both legs, with zero fair-value skew and no leg omission.
An eligible quote has both YES and NO legs; otherwise the normal safety/economic
gates may refuse the whole quote. Existing one-sided, unequal-size or asymmetric
legs are cancelled with `UNCALIBRATED_ASYMMETRY` before cooldown or HOLD. Shadow
and scored grades retain their asymmetry rule. These are not fitted results or
live caps. Numeric caps remain required inputs. The caller
must supply a finite per-band-minute trade hazard bound; no hazard means no quote.
The adverse settlement loss floor is 0.0043 probability units per filled share.
Net uses hazard times adverse loss times size, with no rebate credit. Its unit
contract is a conservative upper bound on total band shares filled per minute;
it must include either-leg exposure. No empirical hazard estimator ships here.

`blind_re1` freezes RE-1's 1.5-cent outward pricing, inclusive [1,3]-cent hold
window, 20/30/50/75 sizes, one band and first-fill termination. Its resting
observer has no share-floor pull; the informed 5% rule above does not apply.
The offline lifecycle implements affected-leg cancel-then-post and ends before
the fifth requote. Recorded fixtures match all 313 minute projections; terminal
findings remain explicit strict xfails with an evidenced ledger. See the
[replay contract](maker-replay-bundle.md#scoring) for timing, sizing, transport
assumptions and the boundary between projected equality and full qualification.
`inventory_action` is advisory hold/resting-sell/exit-review using the
specified taker fee, not a live liquidation path.

## Journal and deferred execution

`Journal` and `write_new` take caller-supplied paths and use exclusive creation.
Canonical sorted JSON lines include sequence, UTC time and previous-line hash;
each append flushes and fsyncs. Reserved metadata cannot be overwritten. The
recursive guard drops auth/signature fields and refuses any remaining caller-
supplied secret string, including escaped strings. Normalized key substrings
include key, secret, passphrase, token, bearer, mnemonic, seed and private,
alongside header/auth/signature/password/cookie markers. **The runtime passes
every loaded secret to SecretGuard.** The guard never loads credentials.
Do not pass arbitrary raw SDK responses. `verify_journal` checks the chain,
monotonic clock, opening/terminal records and optionally an externally retained
whole-file SHA-256. The external digest is needed to detect full-chain rewriting
or truncation to another apparently valid terminal. This is tamper evidence,
not authentication. Journal IO failure poisons that writer; never retry append.
If the opening record fails, the newly created journal is closed and unlinked;
an existing file is never overwritten or removed.

## Weather adapter inputs

The weather plugin supplies partition descriptors and exact zero stdev for
decided 0/1 marginals. Scheduled METAR and model-cycle events expire ten minutes
after their scheduled instant; detected model-cycle events expire ten minutes
after fetch. New-high pulls and determined-band vetoes retain their original
no-expiry behavior. Core windows/freshness and other admission checks still apply.
Observation triggers: only the captured WU printed high (`wu_history_high_increased` from
`wu_history`) can produce a `decided` veto. A rising supporting METAR, ECCC SWOB or WU-current
trigger (the `*_bucket_crossed` and `*_above_wu_floor` pairs in `clock.SUPPORTING_TRIGGERS`) produces
a `new_high` pull only. Value-less (`*_became_fresh`), non-rising, unknown or mismatched
reason/source rows are ignored; the date, market, unit and point-in-time filters apply to all rows.
"Rising" is relative to the previous poll, not the day's running high, and a new-high pull never
expires. Owner decision (2026-10-07): keep this previous-poll rule for now, and switch supporting pulls
to a rise above the day's running maximum before any policy quotes T+0. Because a trigger's local detection date must equal the target date, these events reach
lead-0 (T+0) conditions only. Actions, legs, fills, P&L, pulled seconds and cell sums are
unchanged for every policy. What changes on a day with T+0 supporting pulls: `blind_re1`'s band-day
`fills_in_events`/`fills_outside_events` split (every policy's fill event window reads the info
events) and its `FIRST_FILL_ENDS` decision digest (the decision hashes the fill, which carries
`in_event_window`); `informed-v0`'s refusal reasons, wake/decision/interval counts and decision
digests (each new info event is a wake); and therefore the report traces, sidecar rows, sidecar
binding hash and report hash. Measure any v2 output limits on post-fix exports. **Trigger
`observed_at`:** the live producers write ISO-8601 with a UTC offset (SWOB: station local time with
its offset, from `model_sources.parse_swob_xml`), which the clock parses, so SWOB pulls work and DST is
unambiguous. Anything that is not an aware instant (a bare local `HH:MM`, a naive ISO string, garbage)
is refused, never interpreted (owner decision OD37,
2026-10-07): that row is skipped and counted in the runner coverage as
`clock.trigger_rows_skipped.observed_at_unparseable` (once per row per evaluated band-minute); it
never makes the clock unavailable. A row detected after `as_of` is neither used nor counted.
**Backfill CSV format (owner decision SWOB-a, 2026-10-07).** The ECCC SWOB backfill
(`weather.sources.eccc_swob_history`) writes every observation time in its CSVs (`daily_summary.csv`
`first_time`, `last_time`, `max_temp_times`, `swob_air_temp_max_times`, `swob_max_1h_times`;
`comparison_rows.csv` `swob_times`, `swob_first_reach_time`) as ISO 8601 local time with its UTC offset
(the hourly row's `valid_time_local`), so its rows are never refused if they ever feed the trigger file.
Files written before then carry bare `HH:MM`; they are not rewritten and still parse. Its readers
(`eccc_swob_history.time_to_minutes` and `source_redundancy.earliest_minute`) try the old `HH:MM`
parse first, unchanged, and read only an aware ISO value they could not parse before, taking the
string's own wall-clock minute, so every minute, peak minute and lead is unchanged. The hourly JSONL
`local_time` stays `HH:MM` (WU-shaped; that file already carries `valid_time_local` and `valid_time_utc`).
**Receipt summary (owner decision SWOB-b, 2026-10-07).** The night/calibration receipts (v0.1 and
v0.2) carry `bundle.clock_trigger_rows_skipped`, built by
`maker_plugin_runner.clock_trigger_rows_skipped` from these coverage keys, with
`observed_at_unparseable` always present (an explicit 0). It survives the receipt byte-cap trim that
drops `reader_coverage`, and it carries the same lower-bound caveat as the coverage key below. It is
receipt-only: `export.json` and bundle bytes are unchanged. Hash-pin impact: SWOB-b changes
`maker_plugin_runner.py`, `maker_replay_night.py` and `maker_replay_night_v02.py`, which are in the
night exporters' module closure, so `replay_export module-hash` (the nightly export's registered
`-ExpectedModuleSha256`), the v0.2 `module-hash` and `execution_manifest.source_hashes` change and must
be re-pinned from the landed checkout; `maker_fair_value_score`'s `implementation_hashes`
(`maker_plugin/*.py` only) does not. SWOB-a's modules are outside that closure and change no pin.
**Scope of the observed_at change (not T+0 only).** The v1-exam clock parsed every truthy
`observed_at` of an event's rows before the point-in-time filter, and the exporter keeps every row
detected up to the end of the UTC bundle day, so one unparseable value made that event's clock
unavailable for the whole UTC bundle day. That day can include lead-1 minutes before local midnight
(for New York, 00:00-05:00 UTC), which are scored `informed-v0` T+1 band-minutes. A `clock:` failure
makes `maker_plugin_runner.evaluate_event` record the band-minute unavailable and skip `decide` for
that minute, so a minute lost this way had no decision at all. The refusal therefore can change T+1
band-minute availability and with it scored `informed-v0` T+1 decisions, legs, fills and P&L (and
the cell sums built from them), not only T+1 inputs, wherever such a row exists; only the
supporting-pull change is lead-0 only. Expected incidence is 0, because live producers write aware
times. Measure the incidence with `tools/research/maker_clock_trigger_disclosure.py`
(`old_clock_unavailable_observed_at` per cell, `events_old_clock_unavailable_observed_at` per day)
and check `clock.trigger_rows_skipped.observed_at_unparseable` on post-fix exports. **Both are lower
bounds, not exact counts:**

- The disclosure tool emits a cell only for an event that has a trigger row detected on the
  `--date` day d. The v1 clock also read every earlier row of the event kept in d's bundle. So when the
  bad row was detected on d-1 and the event has no row detected on d, the v1 clock lost day d (its
  lead-1 minutes included) but no cell is emitted for d, and neither per-cell nor per-day field
  counts it. Rows from d-2 or earlier are missed the same way, as is a row stamped exactly 00:00:00 of
  d+1. Round 2's `clock_unavailable` has the same cell rule and the same limit.
- `clock.trigger_rows_skipped.*` is runner coverage: one count per refused row per band-minute whose
  clock step completed. It does count a bad d-1 row on d's minutes (d's bundle keeps it), but it misses
  every band-minute that never reached a completed `observe` (a descriptor failure, a corrupt
  `triggers` source, or another raise inside `observe`). Read it as "at least this many".

The pre-signature check of `clock.trigger_rows_skipped.observed_at_unparseable` (and of the disclosure
fields) on the post-fix calibration exports must carry these lower-bound caveats: a zero there does
not by itself prove that no event-day lost its v1 clock to defect 2. **Re-pin** after
this change: `execution_manifest.source_hashes` and the exporter hashes over `maker_plugin/*.py` and
`maker_plugin_runner.py`, and `maker_fair_value_score`'s `implementation_hashes` over
`maker_plugin/*.py` (fair-value score report bytes change on a rerun).

Served T+0 joins require the bounded export to project `release_calibration_method`
from the verified release's calibration artifact (`market_bin.method`) onto each
matching source row. Missing or conflicting method evidence is unavailable;
`market_shrink` returns `Unavailable(kind="out_of_scope")`. The method enters
both model identity and input hash. This extra export field is not provided by
the existing capture writer. T+1/T+2 estimators remain independent of market
prices; T+0 is outside their frozen scoring protocol. See the
[dated clarification](../research/t1-fair-value-preregistration-2026-09-25.md#clarification-1--2026-09-25-handoff-110c-before-scoring).

Portfolio accounting and saved-read orchestration are owned by the
[portfolio ledger contract](portfolio-ledger.md). The additive
[replay bundle contract](maker-replay-bundle.md) supplies a bounded neutral
envelope reader, capture-time snapshots and a diagnostic-only CLI; scored
replay and weather bundle export remain unfinished. The fictional decision
replay lives in tests. Session control, fitted hazard estimation, YouTube
plugins, shadow scoring and live execution are later phases. The weather
adapters consume caller-supplied captured records without provider or filesystem IO.

## Bounded weather plugin dry run

`python -B -m weather.market.maker_plugin.dry_run --date YYYY-MM-DD --data-root <data>
--output <new-dir> [--markets nyc chicago] [--max-seconds 2700]
[--max-output-bytes 200000000] [--max-input-bytes 1073741824]
[--max-cache-bytes 536870912] [--minute-stride 1]` is an offline diagnostic caller.
Use the topic's installed packages, or set `PYTHONPATH` to its absolute `src` directory.
The interpreter's `-B` is required for the no-writes-outside-output invocation:
it suppresses import-cache writes even before the entrypoint loads.
Production runs remain subject to the host-load lease and window.

It reads only sealed `maker_evidence/<UTC-date>/<hh>-<segment>/` manifests and their
discovery, books, reward journals and referenced book shards. Raw and gzip forms
are supported; no status, temporary file, stream, venue or credential is read.
Only consumed files are hash/size/offset/count verified against the seal.
References are confined to the same manifest; unchanged bodies are verified
against their canonical hash while retaining the new response's capture time.
Each input is opened, read and closed before another input or policy evaluation.
Redirected paths, arbitrary payload paths and output overlap with source trees refuse.

For registered events, explicit supporting paths beneath `--data-root` are:

- `snapshots/<event>/snapshots_long.csv[.gz]` for captured bands and probabilities;
- `forecasts_long.csv[.gz]`, `snapshot_explanations.jsonl[.gz]`,
  `forecast_payloads.jsonl[.gz]` and `observation_payloads.jsonl[.gz]` in that event folder;
- `snapshots/<event>/clob_tokens.jsonl[.gz]`, else `clob_tokens.csv[.gz]`, for band
  metadata before the event has point-in-time snapshot rows (T+1/T+2): the first complete
  token batch (both outcomes of every condition, identical native bin fields, numeric token
  ids, no negative label) is streamed and the read stops there. Production capture is
  local-T+0 only (the snapshot loop's pre-local-day guard; the CLOB loop's
  `market_local_date`), so a T+1/T+2 event's first batch is normally captured after the run
  date. A batch at or before the minute is a point-in-time band capture. A later batch is
  used only as **condition identity** (a band is part of its condition's immutable
  question): only when no band capture exists at the minute, and only when that minute's
  88a discovery lists exactly the batch's conditions with the same YES/NO token ids.
  `WeatherUniverse.bands` enforces this for every caller (descriptors, fair value, clock,
  settlement) against the discovery the universe holds at that minute: other contracts are
  `band_identity_mismatch`, no discovery at the minute is `band_identity_unverified`. The
  runner feeds each event's replayed discovery to the shared universe (one capture per
  content change). Partition membership, books and prices stay point in time. The basis is reported per band (`band_basis`), in the
  descriptor's `source_hashes` and in the fair-value input digest; no batch at all remains
  `descriptor:missing_captured_band_metadata`;
- NBP manifests from every run-window event folder of the market
  (`snapshots/<event>/forecast_payloads.jsonl`, read once per market per run as
  `nbp_pool_manifests`): an NBP cycle is a national product, and the copy captured for the
  T+0 event also carries T+1/T+2 maxima. Each manifest is verified against the event it was
  captured for; the provider selects its own target's slot and skips a cycle without it.
  An unreadable pooled manifest makes that market's fair value and clock corrupt, never fallback;
- shared NBP bulletins (`payload_storage_scope=shared_market_invariant`) at
  `forecast_payload_cas/sha256/<prefix>/<payload_hash>.blob`, the path produced by the
  store's own `shared_payload_ref`; the manifest's CAS kind, raw-bytes hash algorithm,
  encoding, media type, ref and station/target identity are checked, and the SHA-256 and
  byte count cover the exact national blob bytes (strict UTF-8). Each blob is streamed
  once per run and only requested station blocks are kept; the provider receives the
  verified station extract with the national hash as lineage. Legacy market-local rows
  still use `forecast_payloads/sha256/<prefix>/<payload_hash>.json[.gz]` (hash over the
  JSON bytes without the trailing newline). `raw_payload_path` is never followed;
- `snapshots/observation_triggers.jsonl[.gz]` and `settlements/<market>/ledger.jsonl[.gz]`,
  each streamed once per run and indexed by run-window event.

The source manifests supply release lineage; the runner never manufactures the
missing `release_calibration_method` projection or reads ambient model artifacts.
All provider joins are point-in-time. A payload's first manifest capture also
bounds its availability. Missing joins produce explicit coverage/Unavailable
reasons; corrupt NBP or clock inputs cannot silently become fallback or an empty clock.
Append/change during a file read refuses that input. Whole-file reads (the per-event
tables above) above 64 MiB decoded or 100,000 rows refuse with a reported input reason;
decoded segment bodies and the per-segment journal cache each have a 64 MiB limit.
Streamed files (tokens, triggers, ledgers, shared blobs) keep one 1 MiB line in memory
and at most 100,000 retained rows. Rows that cannot be point in time for any minute of
the run date are not loaded: anything captured/recorded after the date, and forecast
or NBP manifest rows more than 48 hours before it (a daily-high forecast or NBP issue
is eligible for at most 24 hours after issue, and issue precedes capture).

Each event's supporting inputs are loaded once per run and kept within
`--max-cache-bytes` (encoded rows); over-budget events are reloaded and counted
(`cache.*`). Providers are built once per cached event. Each segment is indexed once,
so a minute reads no files. Coverage reports `input_bytes.<source>` and
`files_read.<source>` for every source, and `unavailable.lead<N>.<reason>` by local lead.
`--minute-stride N` evaluates only UTC minutes of the day divisible by N; it is recorded
in the summary and counted as `segment_minutes.skipped_by_stride`.
`band_basis.lead<N>.<basis>` counts band-minutes by band basis, and `end_to_end.lead<N>`
counts bands whose descriptor, fair value (`OutcomeView`), clock, settlement join, book,
terms and policy decision all ran. At the default hazard every informed decision is
`MISSING_CONSERVATIVE_FILL_BOUND` (0 legs) by design, and `informed-v0` refuses T+0
(`HORIZON_NOT_ELIGIBLE`) before reading fair value; legs need an explicit hypothetical hazard.
On a host without an active release pointer, served T+0 rows carry
`release_identity_status=research_unbound_non_countable` and stay
`served_snapshot_release_unbound`; no release is inferred.

T+1/T+2 NBP knots are whole degrees, so adjacent percentiles often tie. A tie is an
atom of the piecewise-linear CDF
([amendment 1](../research/t1-fair-value-preregistration-2026-09-25.md#amendment-1--2026-10-01-mission-111k-before-scoring-owner-decision)).
A tied end pair is read one degree apart, the print resolution, so its tail falls at the
frozen 0.15 per degree and ends 2/3 degree beyond the knot
([amendment 2](../research/t1-fair-value-preregistration-2026-09-25.md#amendment-2--2026-10-01-mission-111l-before-any-panel-export-owner-decision)).
Strictly increasing knots keep `nbp-v2-piecewise-linear`, interior-only ties report
`nbp-v2-piecewise-linear-atoms`, a tied end pair `nbp-v2-piecewise-linear-atoms-resolution-tails`,
counted as `fair_value_model.lead<N>.<model_id>`. A decreasing knot refuses
(`decreasing_percentile_knots`), and so do all-equal knots (`degenerate_percentile_knots`). Each
`fair_value:missing_point_in_time_forecast` carries a `forecast_gap`, counted as
`missing_forecast.lead<N>.<gap>`: `expired_next_cycle_fetched_late` (the newest
target-bearing issue passed its pre-registered expiry, next cycle + 1 h, before the next
cycle was captured), `expired_next_cycle_not_captured`, `fetched_after_expiry`,
`no_cycle_with_target` or `no_bulletin`. Each pooled station extract's earliest capture is
also counted against its expected availability (`nbp_capture_vs_expected_availability.<bucket>`:
`on_time`, `late_0_15m`, `late_15_30m`, `late_30_60m`, `late_over_60m`); a late cycle is a
gap in which the previous issue has already expired.

The last books capture in each segment's minute is the decision clock. Split
minutes across segment boundaries are explicitly flagged, not silently deduplicated.
Each discovered active band gets a descriptor attempt; missing both-token rules
do not erase valid siblings. 88a books only its selected, reward-eligible bands
(at most ten per city), judged on the UTC date; a band with no captured book is
`descriptor:book_not_captured`, a capture coverage limit rather than an input fault. The JSON and Markdown contain available probability
mass sums, expected/available bands, partial-mass flags, joins, provider refusals,
clock events (JSON), settlement Pending/facts, policy reasons and leg counts.

Probability mass is judged over **the band set 88a captures** (owner bar, DECISION_LOG
2026-10-01): a band is captured when both token books exist at or before the minute
(`captured_by_88a`). A record's `probability_mass.captured_set` is `complete_unit_mass`
when every captured band has a fair value, all from one joint over the full partition,
and that joint sums to one; otherwise `partial`, `complete_without_one_joint`,
`complete_nonunit_mass` or `no_captured_bands`. The summary counts these by lead
(`captured_set_mass`), the reasons on captured bands (`captured_set_reasons`), and,
beside them, the all-band classes by lead (`all_band_mass`; `mass_coverage` keeps the
lead-free all-band count). The summary's `verdict`, the first section of `report.md`,
computes the exam-line bar: status COMPLETE, `end_to_end.lead1` > 0, no
`band_identity_mismatch` or `band_identity_unverified`, and at least one lead-1 record
with complete unit mass over the captured set. The hand check of one T+1 fair value
against its bulletin stays manual.
Not-evaluable inputs are counted separately from a policy decision with zero legs.

`informed_v0` supplies profile name `informed-v0`. Every decision is independent
with disclosed hypothetical 100-unit caps, empty inventory and no resting orders.
This is not a portfolio replay. The default hazard is None: 88a supplies no
measured conservative fill bound, so `MISSING_CONSERVATIVE_FILL_BOUND` is expected
unless an earlier gate refuses. Optional `--hypothetical-hazard-per-minute`
is an explicit synthetic control passed unchanged to the policy, never a fitted
estimate or live authority. Book and reward capture clocks are preserved.

`report.json` and `report.md` are create-only in a new/empty output directory.
The combined final byte count includes both files; 32 KiB is reserved for their
terminal summary, and output caps below 64 KiB are rejected before writing.
Input bytes count decompressed reads including rereads. Time checks run between
bounded reads/records/provider calls; terminal report flushing can add overhead.
Time/input/output cap stops leave valid partial reports. Exit 0 means processing
completed (coverage gaps may still exist); exit 2 means partial, input error,
no event-minute coverage or invalid invocation. No score, fill or edge is inferred.

## Update when

Update for additive contract fields, conformance checks, decision-unit conventions,
policy defaults, evidence serialization or publication rules.
