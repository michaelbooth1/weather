# YouTube plugin template

Status: canonical implementation guide for an external domain plugin.

- **Owns:** the YouTube team's starting template, contract pin and offline acceptance recipe.
- **Read when:** adapting captured video-view evidence to the domain-neutral maker API.
- **Contract owners:** [plugin contracts](maker-core-contracts.md) and [replay bundles](maker-replay-bundle.md).
  Current operating authority belongs to [state of play](STATE_OF_PLAY.md).

## Start from the pinned contracts

Pin the plugin API to Git tag **`maker-core-contracts-v0.1`** (`CONTRACTS_VERSION = "0.1"`).
The tag freezes the Protocols and value types in
[`maker_core.contracts`](../../src/maker_core/contracts/__init__.py); compatible changes are additive.
Do not add required arguments, reinterpret units or remove fields under that version.
The replay harness is an additive consumer on a later revision: the contract tag alone does not supply it.
Record the harness revision separately when retaining replay results.

Use [`fictional_domain.py`](../../tests/maker_core/fixtures/fictional_domain.py) as the
provider template and [`test_contracts.py`](../../tests/maker_core/test_contracts.py) as the
executable acceptance example. The fictional coin's captured bias, one-hour lifetime and settlement
are test data, not YouTube assumptions. Replace those with captured domain evidence and an explicit
freshness and resolution policy. This guide supplies no YouTube collector, fitted model or settlement source.

## Plugin protocols

Plugin code imports `maker_core.contracts` (and its conformance module), never quoting, venue or
weather implementation modules. The fixture implements the four required protocols on one instance;
separate provider instances are equally valid. Callers supply captured inputs and query clocks.

| Protocol | v0.1 methods, excluding `self` | YouTube adaptation |
| --- | --- | --- |
| `MarketUniverse` | `discover(as_of_utc, horizon_days) -> UniverseSnapshot`; `describe(condition_id, as_of_utc) -> MarketDescriptor` | Describe captured contract rules, video/event/condition identity, distinct YES/NO tokens, tick, minimum size, close/settle times, native unit, plugin version and source hashes. |
| `FairValueProvider` | `evaluate(market, as_of_utc) -> OutcomeView \| Unavailable` | Estimate the YES probability from domain evidence available at the query time. Retain input hash, model identity, uncertainty and calibration grade. |
| `InformationClock` | `upcoming(markets, from_utc, to_utc) -> tuple[InfoEvent, ...]`; `observe(markets, as_of_utc) -> tuple[InfoEvent, ...]` | Represent captured knowledge of scheduled updates and detected count changes, with affected conditions, severity and action hints. |
| `SettlementResolver` | `resolve(market, as_of_utc) -> SettlementFact \| Pending` | Resolve only from the contract's designated source and reconciliation policy; retain source hashes and capture time. |
| `ExposureModel` (optional) | `factors(market) -> Mapping[str, float]` | Supply documented common-risk factors where supported. Omitting factors does not remove event or wallet caps. |

For a view-count contract, explicitly define the unit (for example, views), counting window,
video identity and resolution rule from the captured rules. Bands may be a `partition` only when
mutually exclusive and exhaustive. Threshold markets use `nested_ge` or `nested_le` as appropriate;
their marginals are not partition `joint` mass. Do not infer grouping from a similar title.

All contract datetimes are UTC-aware with zero offset. Probabilities and severity are finite in
`[0, 1]`; `stdev` is in probability units, positive except that an exactly decided 0/1 view may use
zero. Optional `joint` mass sums to one within `1e-9` and agrees with this condition's marginal.
Choose `calibration_grade` from `none`, `shadow`, `scored` according to retained evidence; copying
the fixture's `scored` label does not establish calibration.

## Unavailable, not a guess

If required inputs are absent, expired, corrupt or outside the model's scope, return
`Unavailable(reason, as_of_utc, kind=...)`. The default kind is `missing_input`; the other kinds
are `out_of_scope`, `corrupt`, and `decided`. State the actual reason. A missing view count must
not become zero, a neutral `p_yes=0.5`, a market midpoint or a guessed probability.

Market prices never enter fair value. The core may combine separate book and plugin inputs under
its own policy; the plugin must not manufacture an `OutcomeView` to obtain that behavior. Normal
v0.1 calls pass no extra keywords. The conformance kit deliberately injects `market_price=0.01`
and `market_price=0.99`: reject the keyword with `TypeError`/`ValueError`, or ignore it without
changing the result.

Likewise, return `Pending(reason, as_of_utc)` until settlement evidence is available. A forecast,
a crossed threshold or a late query clock is not a reconciled settlement. `SettlementFact.p_yes`
is the resolved YES payout fraction; optional `resolved_value` is native-domain text, not a payout override.

## `valid_until` and capture-time queries

The field is **`OutcomeView.valid_until_utc`**. For a query at `t`, serve a view only when:

```text
view.as_of_utc <= t < view.valid_until_utc
```

Expiry is exclusive: at `valid_until_utc`, return `Unavailable` unless a newer captured input
supports a fresh valid view. The constructor requires expiry strictly after `as_of_utc`. Set
the lifetime from the plugin's documented freshness policy; repeated queries do not renew it.
In the fictional fixture, a record captured at 00:00 expires at 01:00. It is unavailable before
00:00 and at 01:00; a later record captured at 02:00 cannot repair the earlier missing interval.

Filter every provider by capture time, including rules, clock knowledge and settlement records.
Ingesting a future record must leave past queries unchanged. Keep provider observation/issue time
separate from when the record was captured. Known scheduled events may point into the future;
`observe` must not expose future observations or detections. `InfoEvent.active_until_utc` is a
separate, inclusive event expiry, not the view's exclusive freshness deadline; see the
[event contract](maker-core-contracts.md#plugin-surface).

## Replay bundle shape

Follow the [closed-day envelope](maker-replay-bundle.md#closed-day-envelope) for authoritative
validation rules. A bundle is one closed **UTC capture day**, which may differ from the contract's
settlement date. Its directory contains `bundle.json` plus flat, explicitly listed `.jsonl` streams:

```text
closed-day/
  bundle.json
  records.jsonl
```

The following is a shape illustration, not a sealed bundle; replace placeholders with calculated
hashes and exact counts. `synthetic` is appropriate for fixtures; use `captured` only for retained captures.

```json
{
  "format": "maker_core.replay.bundle.v0.1",
  "day": "2020-01-01",
  "sealed_at": "2020-01-02T00:00:00+00:00",
  "provenance": "synthetic",
  "conditions": [{
    "condition_id": "fictional-video-band",
    "market_id": "fictional-video",
    "domain_id": "youtube",
    "active_from": "2020-01-01T00:00:00+00:00",
    "active_until": "2020-01-02T00:00:00+00:00"
  }],
  "streams": [{
    "path": "records.jsonl",
    "sha256": "<raw stream SHA-256>",
    "bytes": "<integer byte count>",
    "records": "<integer record count>"
  }]
}
```

Each JSONL record has exactly `sequence`, `captured_at`, `condition_id`, `kind`, `payload`,
`payload_sha256` and `source_hashes`. `sequence` is a unique nonnegative integer within the bundle;
`condition_id` must be declared above; `payload` is an inline JSON object. Compute `payload_sha256`
over `maker_core.evidence.journal.canonical_bytes(payload)` (sorted ASCII JSON plus LF). Supply a
nonempty `source_hashes` mapping from provenance labels to lowercase SHA-256 digests. Stream hashes
bind the raw bytes, including capture time, ordering and provenance; labels are not paths to open.

The admitted kinds are `descriptor`, `book`, `terms`, `coverage`, `trade`, `plugin_input`,
`outcome_view`, `info_event` and `settlement`. Condition `market_id` labels must remain stable across
days for clustering. Active intervals are minute-aligned and half-open within the day; equal
endpoints allow settlement-only metadata. Do not narrow intervals to hide missing capture.

[`replay_bundle.py`](../../tests/maker_core/fixtures/replay_bundle.py) generates envelope fixtures;
its deliberately minimal payloads are not engine-ready. For typed records, follow
[`replay_scenario.py`](../../tests/maker_core/fixtures/replay_scenario.py) and the
[`payloads.decode`](../../src/maker_core/replay/payloads.py) adapter:

- `descriptor` wraps the serialized `MarketDescriptor` as `market`, plus plugin-owned local
  `horizon_days` and optional `exposure_factors`.
- `outcome_view` is `{"available": true, "value": <serialized OutcomeView>}` or
  `{"available": false, "value": <serialized Unavailable>}`; `info_event` is `{"events": [...]}`.
- `plugin_input` retains domain provenance; it does not automatically become a fair-value view.
  Books, reward terms, trades and reconciled settlement need their own typed captures.
- `coverage` supplies `trade_stream_ok` and `valid_until_utc`, expiring at most 60 seconds after
  capture. It must be supported by captured stream-health evidence. An empty trade tape does not
  establish a zero-fill interval.

Those serializers and replay modules belong to the bundle adapter/test harness, outside the
contracts-only plugin. Feed providers a `Timeline.at(t)` snapshot, not the full tape: only records
captured at or before `t` are visible, sorted by `(captured_at, sequence)` with immutable payloads.
Later-captured settlement goes in a later capture-day bundle. Missing captures stay explicit exclusions.
No compression, external payload references, unlisted file reads or partial admission are supported.
Hash validation proves byte identity, not authenticity, payload validity or economic edge.

Use the [diagnostic CLI and scoring boundary](maker-replay-bundle.md#diagnostic-and-scoring-boundary)
only through the permitted host admission path. Default diagnostics do not execute the selected
policy or establish fills, P&L or parity. A synthetic label or passing conformance test grants no
scoring or live-execution authority.

## Conformance test command and adaptation

With this checkout's `src` on the import path (pytest configures it), the reference suite is:

```text
python -m pytest tests/maker_core/test_contracts.py -q --basetemp <new-absolute-temp-directory>
```

On the workstation, pass these `-m pytest ...` arguments through
[`workstation_heavy.ps1`](../../scripts/ops/workstation_heavy.ps1) as documented in
[development](../development.md#separate-non-capture-workstation); the capture host has separate
admission rules. Use the project interpreter and remove the dedicated test temporary directory
afterward. `maker_core.contracts.conformance` is a library, not a conformance CLI.

Adapt the existing reference test to the YouTube provider instances and captured test records:

```python
from maker_core.contracts.conformance import FixtureClock, check_conformance

check_conformance(
    universe=universe,
    fair_value=fair_value,
    information=information,
    settlement=settlement,
    clock=FixtureClock(now=available_at, missing_at=missing_at, later_at=later_at),
    advance_inputs=ingest_future_capture,
)
```

Bind these names to deterministic fixtures with `missing_at < available_at < later_at`, a nonempty
universe, genuinely missing inputs, an available view and expiry. The callback must ingest a later
captured record. The kit checks Protocol shape, repeatable discovery, descriptor identity,
Unavailable-on-missing, probability/UTC validity, expiry refusal, the market-price probe, event
times, settlement identity and unchanged historical answers after ingestion. Also exercise the
plugin's own rule joins, missing/corrupt inputs, event and settlement cases; finite fixtures cannot
prove absence of hidden IO or leakage. Review the input flow and retain captured hashes.

For bundle adaptation, run `tests/maker_core/test_replay_bundle.py` through the same pytest path.
For changes to this guide, include `tests/operations/test_agent_docs_audit.py` in the focused run;
the canonical audit entrypoint is `python -m weather.operations.agent_docs_audit`.

## Update when

Update when the pinned plugin interface, external-team conformance recipe, freshness semantics or
replay adapter shape changes. Keep the detailed contracts in their linked owners.
