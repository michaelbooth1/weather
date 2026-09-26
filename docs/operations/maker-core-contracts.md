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
| `InfoEvent` | Scheduled/observed/detected times, affected conditions, severity, optional decided probabilities, action hint |
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
  Expiry is inclusive; absent expiry preserves the original event lifetime.
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
are active from -3 to +10 minutes; detected events remain active until explicit
expiry or, without expiry, caller removal on captured fresh evidence. Only
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
none/shadow/scored, and no leg tightening for unscored probabilities. These are
not fitted results or live caps. Numeric caps remain required inputs. The caller
must supply a finite per-band-minute trade hazard bound; no hazard means no quote.
The adverse settlement loss floor is 0.0043 probability units per filled share.
Net uses hazard times adverse loss times size, with no rebate credit. Its unit
contract is a conservative upper bound on total band shares filled per minute;
it must include either-leg exposure. No empirical hazard estimator ships here.

`blind_re1` freezes 1.5-cent outward pricing, the [1,3]-cent hold window,
20/30/50/75 sizes, one band and first-fill termination. Historical public quote
fixtures prove **first-minute price parity only**. Per-leg replacement and the
RE-1 five-requote limit are not reproduced; account, transport and full-minute
runtime parity are not claimed. The attempt-1..12 replay skeleton is skipped
until an authorized sanitized journal export is available.
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

Served T+0 joins require the bounded export to project `release_calibration_method`
from the verified release's calibration artifact (`market_bin.method`) onto each
matching source row. Missing or conflicting method evidence is unavailable;
`market_shrink` returns `Unavailable(kind="out_of_scope")`. The method enters
both model identity and input hash. This extra export field is not provided by
the existing capture writer. T+1/T+2 estimators remain independent of market
prices; T+0 is outside their frozen scoring protocol. See the
[dated clarification](../research/t1-fair-value-preregistration-2026-09-25.md#clarification-1--2026-09-25-handoff-110c-before-scoring).

`portfolio`, `venue`, `runtime` and `replay` are docstring-only placeholders.
The fictional replay lives in tests. Production evidence loading, portfolio
accounting, venue/credential access, session control, fitted hazard estimation,
YouTube plugins, shadow scoring and live execution are later phases. The weather
adapters consume caller-supplied captured records without provider or filesystem IO.

## Update when

Update for additive contract fields, conformance checks, decision-unit conventions,
policy defaults, evidence serialization or publication rules.
