# T1 maker simulator and pilot accuracy gate

Status: canonical offline implementation contract; parameter proposals are not frozen.

**Owns:** normalized captured inputs, maker replay accounting, pinned LFC receipt
adaptation and accuracy comparisons. **Read when:** preparing a T1 replay or pilot
accuracy package. The [edge trial charter](EDGE_TRIAL_CHARTER.md) owns eligibility
and trial PASS; [host load policy](HOST_LOAD_POLICY.md) owns execution admission.
This simulator has no order transport, credentials, source fetcher or live mode.

## Package and input contract

`weather.backtesting.t1_simulator.replay(payload, ReplayConfig)` is the pure engine.
`t1_capture` adapts saved CLOB books, 88a prints and the pinned pilot's public
snapshots; `t1_accuracy` reads the pin's chained journal and saved receipt export.
`t1_cli` writes an exclusive-new JSON report with source and input hashes.
The deterministic synthetic examples are the constructors in
[`tests/backtesting/t1_fixtures.py`](../../tests/backtesting/t1_fixtures.py).
They read no runtime data and are development evidence only.

The engine takes a bounded session export with:

- `start`/`end` UTC; `conditions` mapping IDs to International venue, YES/NO
  `token_ids`, `event_date`, `native_unit`, captured `tick`/`min_order_size` and
  complete `coverage_start`/`coverage_end`. Cash units are pUSD; shares and prices
  are decimal strings. Temperature units are retained, never converted.
- `events`: full two-token `book` snapshots at availability time; captured `terms`
  with `rate_per_day`, `min_size`, `max_spread_cents`, `valid_until` and source
  hash; `trade` rows with stable execution ID, native outcome, aggressor, price,
  size, receipt `at` and exchange `traded_at`; explicit `settlement` rows with
  venue YES payout fraction and source hash. No Gamma display prices or
  reconstructed weather labels can substitute for these inputs.
- `commands`: post-only native BUY YES/NO proposals (`id`, condition, outcome,
  observed time, price, size), or cancellation of an ID. Arrival is observation
  plus declared latency. An explicitly supplied arrival cannot precede it.
  The separate `market_centred_quote` proposer uses a captured midpoint, outward
  tick rounding, a declared distance and size; it makes no forecast.
- `rebate_pools`: complete, captured weather-category UTC-day taker fees and
  total maker fee-weight denominator, with source hash. The denominator includes
  all category fills, not only this condition or our orders. A missing pool is
  incomplete evidence, not a zero rebate assumption.

Exporting is not a licence to inspect trial dates: preserve the embargo and
freeze-before-read rules of the task and charter. Do not point this tool at
shadow tapes. Capture/export owners must establish coverage and stable trade
IDs before a countable run. Timestamp/price/size hashes alone cannot distinguish
two legitimate identical prints; `captured_print` therefore requires an
exporter-supplied deduplicated `execution_id`.

## Replay semantics and limits

The arrival-time native ask determines post-only rejection. Better-price and
same-price displayed volume is ahead of us. T1 permits at most one resting
order per native outcome per condition; cancel before replacing that leg.
Only matching native-token SELL-aggressor volume consumes that queue. There is
no cancellation credit. The default proposed rule additionally requires a print
strictly through our price; `back_at_price` is an explicit sensitivity that still
depletes the queue first. Retransmitted execution IDs do not duplicate volume.
At identical timestamps a trade precedes a cancellation or new post, conservatively.
Late public receipt does not move the exchange's execution time forward.
Unknown aggressors, mirrored prints without identity reconciliation and
ambiguous mint/merge executions must not be silently counted as own fills.

Resting reservations and filled cost both consume per-market and total capital;
settlement releases the reservation. Global cash cannot be reused after a loss.
Incentive accrual cannot finance orders before payment. The strategy holds native
tokens to venue settlement; it has no taker exit. `fee` implements the charter's
taker fee for accounting consumers; the maker pays zero. Adding a taker strategy
requires its own depth walk and minimum-slippage contract.

Reward shares use the quadratic order score, size-qualified midpoint, the
single-sided divisor and complementary books. Own liquidity is composed with
the canonical `maker_core.quoting.book.compose_book`; it moves the midpoint and
is excluded from competing scores. Actual pilot books must first have actual
own outstanding sizes removed by `t1_capture`, then simulated sizes are added.
Every book/terms/fill/cancel boundary updates the reward estimate; selection-time
share is never held for the session. Continuous integration is the expectation
of the venue's random minute sampling, not an assertion about its realized offset.
Stale book/terms intervals are omitted and explicitly make the report incomplete.
No missing-configuration substitute ships: export captured settings or obtain
a preregistered substitute implementation before freezing.

`maker_grouped` sums Q_min separately per identified competing maker, requiring
order-level maker IDs. Anonymous L2 does not supply those identities.
`aggregate_upper_bound` instead uses the sum of both sides' qualifying scores
as a denominator upper bound, so its reward estimate is conservative conditional
on the displayed book. It is labelled as a bound, never exact reward allocation.
Neither mode predicts competition induced by our own quote. The accuracy gate
must expose whether either estimate is adequate for our pilot.

Rebates are 25% of category taker fees times our fee-weighted filled share when
configured with the charter's weather coefficient. Rewards and rebates retain
separate accrued and payable totals. A daily total below the venue's $1 payment
minimum is assigned no payable income; no unverified carry-forward credit.
The export must contain our entire rewarded account-day scope for that threshold
to be meaningful. Trial net P&L uses payable amounts, not unpaid accrual.

Raw settlement P&L is reported separately from the declared informed-flow stress:
`stressed payout = (1-f) * venue payout`, equivalently a mixture of observed
settlement and a worst-case zero payout on fraction f of filled shares. This
does not estimate f, alter queue fills, invent information or add a markout loss
on top of the same settlement loss. Inventory stays capital-bound until settlement.
The raw trading component is also decomposed into entry-mid spread capture and
subsequent inventory movement to venue payout, with maker fees shown separately.
Markouts are share-weighted native-token midpoint minus entry at the fixed
horizon, using the first subsequent two-sided capture within the declared delay.
They are diagnostics and never enter the quoting information set.

## Accuracy receipt export

The LFC writer is read-only source authority at the task's pin, not an import or
runtime dependency. `read_pin_journal` verifies canonical newline bytes,
sequence, previous SHA, UTC order, opened/terminal records and evidence/cleanup
flags. `pin_commands` binds `submit_market_snapshot`, `submit_request`,
`submit_response`, LFC placement identity and acknowledged cancel events.
Fill detection timestamps in the journal are not precise trade times.

The sanitized receipt JSON contains `scope` (account, session, condition and
reward day), `journal_pin`, `journal_sha256`, and:

- `clob`: exact saved CLOB `/data/trades` endpoint, complete pagination through
  terminal cursor and wire `rows`. Confirmed `maker_orders` matching our order
  IDs supply price, matched amount, token, side and exchange match time. Unix
  seconds and normalized ISO UTC are accepted. Trade IDs deduplicate pagination;
  transaction hashes do not collapse distinct fills.
- `wallet`: independently exported start/end cash, start/end snapshot times,
  account/session identity, complete attributed order fills, reward/rebate/
  redemption credits and an empty unattributed-cashflow list. It must agree
  with CLOB fills and the cash identity. Ending snapshot follows D+2 evidence.
- `rewards`: exact-scope D+1 and D+2 completed venue reads with source hashes,
  reward day, account/session/condition identity, paid amount and an explicit
  assertion that this session exclusively owns the attributed scope. Shared
  reward days require an independently reviewed allocation/export; subtracting
  a simulated reward prediction from a wallet credit is not attribution.

The CLI hashes the sanitized export and raw journal. Source hashes in an export
are provenance assertions: the preparing operator must retain their underlying
raw responses and projection script. This command does not authenticate or
fetch those responses. No credentials or authenticated request headers belong
in the export. Capture correctness and source authenticity remain distinct
from the arithmetic accuracy comparison.

`accuracy_gate` reports predicted/actual payable rewards, filled shares per
order and horizon markouts per actual filled order. Disagreement fails. Missing
or inconsistent receipt evidence raises before certification. No-fill sessions
cannot alone identify fill/markout accuracy. `combine_session_gates` enforces
distinct sessions, one configuration/tolerance and campaign evidence floors;
the caller must additionally bind every report to the same clean simulator
commit and preregistration. Neither session nor campaign report is a trial PASS.
The trial scorer must refuse a failed, insufficient, incomplete or unbound gate.

## CLI and admission

The CLI interface is `python -m weather.backtesting.t1_cli simulate` or `accuracy`,
with required `--inputs`, `--config`, `--latency-evidence`, `--output`; accuracy
also requires `--journal`, `--receipts`, `--tolerance`. These are explicit file
paths. Outputs are create-only; an existing destination is an error. A failed
accuracy comparison exits 2. There is no freeze command or trial look command.

`--latency-evidence` binds the config's SHA to retained samples containing
`observed_at`, `decided_at`, `acknowledged_at`, `kind=observation_to_order_ack`,
`sample_count` and `synthetic`. The CLI recomputes nearest-rank empirical p95;
configured latency must be at least that p95. Synthetic evidence is explicitly
labelled and cannot become live accuracy evidence merely by passing arithmetic.
The report records Git HEAD, worktree cleanliness and hashes of all T1 modules.
Freeze authority requires a clean committed source and retained input manifests.

All replay and verification obey the workstation wrapper, HOLD and memory rules.
The exact CLI module is listed by the wrapper and hook mirror; no child or
similarly named module is admitted. Encode its argument array as UTF-8 JSON
base64 for `workstation_heavy.ps1 -Kind weather_heavy`, with absolute project
interpreter and repository paths. Fixture CLI coverage runs inside focused
wrapped pytest. Inputs are capped at 16 MiB and 50,000 events/commands;
large tape streaming/export and resumable cross-session state are separate work.
Module admission does not authorize a read of trial dates or a live action.

## Values proposed for owner/master review

These are proposals only; they are not runtime defaults or a preregistration.

| Input | Proposal | Basis and limit |
| --- | --- | --- |
| f low/mid/high | 0.25 / 0.50 / 0.75; primary high | Conservative stress scenarios, not estimates from the small historical fill sample; disclose the worst-case mixture definition above. |
| Latency | Retained end-to-end p95 or worse; 2 seconds synthetic rehearsal only | No measured latency was supplied. Observation-to-ACK captures decision and transport delay; freeze only after pilot measurement. |
| Queue | back_strict_through; back_at_price sensitivity | Displayed better/same-price shares first, no cancellation credit; do not treat a touch as a back-queue fill. |
| Reward tolerance | max(0.05 pUSD, 20% of actual), per attributed session | Allows random minute sampling and rounding while detecting the historical order-of-magnitude overstatement; low reward days alone are weak evidence. |
| Fill tolerance | max(1 share, 10% actual), per order | Permits timestamp/granularity differences, prevents aggregate cancellation of missed and excess fills. |
| Markout tolerance | 0.01 pUSD/share at 5 minutes, per filled order | One cent is below the pin's adverse-markout indicator; use identical captured horizon convention for predicted and actual fills. |
| Receipt reconciliation | 0.01 pUSD, including D+1 versus D+2 | Accounting completeness is mandatory, separate from model tolerances. |
| Campaign evidence | At least 3 complete sessions, 5 distinct filled orders, 1 pUSD paid reward | Avoid certifying a zero-fill model; first-fill termination means the floor spans sessions. Report uncertainty; this floor is a proposal, not proof of precision. |
| Capture/mark delay | At most 30 seconds for books; 30 seconds after markout horizon | Conservative prospective starting point; verify capture cadence outcome-blind before freeze. |

The owner/master must decide whether an aggregate reward lower bound is
acceptable after calibration, specify the capital scale, establish the rebate
category denominator and approve a raw-receipt export/attribution protocol.
No output of this implementation freezes any of those choices.

## Source contracts and update triggers

Venue primary references: [reward method](https://docs.polymarket.com/programs/liquidity-rewards),
[fees](https://docs.polymarket.com/trading/fees),
[rebates](https://docs.polymarket.com/programs/maker-rebates),
[CLOB trade wire format](https://docs.polymarket.com/trading/manage-orders).
The charter and captured daily configuration take precedence over current
web pages when replaying a historical condition.

Update this document with input/export, accounting, queue, latency, gate or CLI
changes. Tests must remain synthetic and dated within the permitted development
window; real receipts and trial dates require their own authority and freeze.
