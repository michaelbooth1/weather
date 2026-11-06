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

- `opening_state=flat`: an explicit declaration that this simulated capital
  period begins with no resting orders or inventory. Missing or other opening
  states refuse; this kernel cannot resume unsettled inventory. Do not reset
  capital by splitting overlapping unsettled periods into independent inputs.
- `start`/`end` UTC; `conditions` mapping IDs to International venue, YES/NO
  `token_ids`, `event_date`, `native_unit`, captured `tick`/`min_order_size` and
  complete `coverage_start`/`coverage_end`. Cash units are pUSD; shares and prices
  are decimal strings. Temperature units are retained, never converted.
- `account_scope_complete=true`: the export covers the account-day incentive
  scope. Optional `external_incentives` rows declare captured, complete other
  reward/rebate accruals and source hashes. These affect only the account's
  payment threshold; they are never credited as this strategy's income.
- `events`: full two-token `book` snapshots at availability time; captured `terms`
  with `rate_per_day`, `min_size`, `max_spread_cents`, `valid_until` and source
  hash; `trade` rows with stable execution ID, native outcome, aggressor, price,
  size, receipt `at` and exchange `traded_at`; explicit `settlement` rows with
  venue YES payout fraction and source hash. No Gamma display prices or
  reconstructed weather labels can substitute for these inputs.
  Optional `redemption` events release a captured fraction of that condition's
  settled venue value into spendable cash, with venue source hash. Resolution
  value alone never finances another order; fractions cannot exceed one in total.
  A book has both `at` (completed-input availability) and `observed_at` (earliest
  observation/request start, a conservative age bound), plus each token's captured
  `tick` and `min_order_size`. Arrival uses those native rules, not initial metadata.
- `commands`: post-only native BUY YES/NO proposals (`id`, condition, outcome,
  input-availability `observed_at`, `decided_at`, `expires_at`, price, size), or
  cancellation of a submitted ID. Arrival is at least the later of availability
  plus end-to-end latency and decision plus order-transport latency. An explicitly
  supplied arrival cannot precede either bound. GTD expiry precedes a same-time trade.
  The separate `market_centred_quote` proposer uses a captured midpoint, outward
  tick rounding, a declared distance and size; it makes no forecast.
- `rebate_pools`: complete, captured weather-category UTC-day taker fees and
  total maker fee-weight denominator, with source hash. The denominator includes
  all category fills, not only this condition or our orders. A missing pool is
  incomplete evidence, not a zero rebate assumption.
- `reward_epochs`, when `reward_epoch_rule=captured_active`: per UTC day and condition, complete captured normalization
  `active_seconds` and source hash. This is 60 times the number of active venue
  minute samples, or the captured full-day expectation under the declared sample
  rule. Include counterfactual own-liquidity activation. It cannot be shorter
  than the replay's own eligible duration. A missing denominator is incomplete.
  The separately declared `full_day_upper_bound` rule uses 86,400 seconds as a
  denominator upper bound; it needs no invented observation of venue sample times
  and is labelled conservative rather than exact normalization.

Exporting is not a licence to inspect trial dates: preserve the embargo and
freeze-before-read rules of the task and charter. Do not point this tool at
shadow tapes. Capture/export owners must establish coverage and stable trade
IDs before a countable run. Timestamp/price/size hashes alone cannot distinguish
two legitimate identical prints; `captured_print` therefore requires an
exporter-supplied deduplicated `execution_id`.

## Replay semantics and limits

The arrival-time native ask, tick and minimum order size determine rejection. Better-price and
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
settlement releases the risk reservation. Spendable cash releases only through
an explicit redemption event. Global cash cannot be reused after a loss.
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
The epoch rule is explicit. Captured active normalization needs its own complete
coverage. Full-day upper normalization deliberately underestimates income when
some samples have no scoring liquidity; it does not assert 1,440 active samples.
Stale book/terms intervals are omitted and explicitly make the report incomplete.
No missing-configuration substitute ships: export captured settings or obtain
a preregistered substitute implementation before freezing.

`maker_grouped` requires a complete census of unique native orders with order ID,
maker ID, outcome, side, price and size. Its reconstruction must equal the captured
books. Each native own order scores once; its displayed complement is not a second
order. Anonymous L2 price levels with maker labels cannot establish exact allocation.
`aggregate_upper_bound` uses half the sum of all four displayed side scores
as a denominator upper bound: each maker's Q_min is at most half its side-score sum.
Mirror duplication increases that bound. Its reward estimate is conservative conditional
on the displayed book. It is labelled as a bound, never exact reward allocation.
Neither mode predicts competition induced by our own quote. Replaying realized
pilot books measures conditional scoring accuracy; it does not identify the
counterfactual competition response in passive trial captures. That application
limit must be addressed in the trial preregistration, not hidden by a pilot PASS.

Rebates are 25% of category taker fees times our fee-weighted filled share when
configured with the charter's weather coefficient. Rewards and rebates retain
separate accrued and payable totals. A daily total below the venue's $1 payment
minimum is assigned no payable income; no unverified carry-forward credit.
The export must contain our entire rewarded account-day scope for that threshold
to be meaningful. Trial net P&L uses payable amounts, not unpaid accrual.

Raw settlement P&L always uses the venue's payout for every share of that token.
The proposed additional adverse-selection reserve is `f * filled cost`, independent
of whether the token won. It reserves the purchase cost on a declared fraction of
represented fills; it is not a bound on replacing those fills with different assets,
a different settlement, inferred trader knowledge, or a fitted informed-flow model.
It can conservatively double-charge losses already
present in realized P&L. The output labels that reserve and reports risk-adjusted
net separately. Its use and the interpretation of f require owner/master review.
Cash accounting uses actual captured redemption proceeds; a scoring reserve does
not fabricate a different wallet cash flow. Inventory remains reserved until settlement.
The raw trading component is also decomposed into entry-mid spread capture and
subsequent inventory movement to venue payout, with maker fees shown separately.
Markouts are share-weighted native-token midpoint minus entry at the fixed
horizon, using the first two-sided capture whose observation starts at/after the
horizon and whose availability is within the declared delay.
They are diagnostics and never enter the quoting information set.

## Accuracy receipt export

The LFC writer is read-only source authority at the task's pin, not an import or
runtime dependency. `read_pin_journal` verifies canonical newline bytes,
sequence, previous SHA, UTC order, opened/terminal records and evidence/cleanup
flags. `pin_commands` binds `submit_market_snapshot`, `submit_request`,
`submit_response`, LFC placement identity and acknowledged cancel events.
Fill detection timestamps in the journal are not precise trade times.
The pin's `observed_at_utc` is batch start, before sequential HTTP reads.
`pin_snapshot` therefore requires the completed snapshot journal time as
`available_at`; it does not backdate data availability to request start.
The terminal clean-up proof bounds quote exposure in session replay. A simulated
rejection of an acknowledged order is a lifecycle mismatch and fails the gate.
Journal input is streamed: every observation is hash/clock checked, while only
quote lifecycle records are retained. The reader caps individual lines and total
journal bytes; it never loads a whole pilot journal to replay a handful of quotes.
Retained lifecycle bytes also have a separate bound; book-update queue telemetry
is verified and discarded, while placement records remain part of the replay binding.

The sanitized receipt JSON contains `scope` (account, session, condition and
reward day), `journal_pin`, `journal_sha256`, and:

- `clob`: exact saved CLOB `/data/trades` endpoint, complete pagination through
  terminal cursor and wire `rows`. Confirmed `maker_orders` matching our order
  IDs supply price, matched amount, token, side and exchange match time. Unix
  seconds and normalized ISO UTC are accepted. Trade IDs deduplicate pagination;
  transaction hashes do not collapse distinct fills.
  Integer-second match times retain a one-second uncertainty interval. ISO exports
  must declare `match_time_precision_seconds`; they cannot silently invent precision.
  Markout comparisons use the worst error across the interval, bounded by the
  journal/ledger terminal proof, and need sufficient captured books for that interval.
- `wallet`: independently exported start/end cash, start/end snapshot times,
  account/session identity, complete attributed order fills, reward/rebate/
  redemption credits and an empty unattributed-cashflow list. It must agree
  with CLOB fills and the cash identity. Ending snapshot follows D+2 evidence.
  `other_attributed_cashflows` may contain independently sourced signed amounts
  from other sessions, each with a unique ID, other session ID and source hash;
  these reconcile whole-wallet cash without becoming this session's income.
  `settlement_complete`, `settlement_value` (redeemed plus remaining venue value)
  and `settlement_source_sha256` independently check the captured payout against
  the actual filled holdings. Redemption credit cannot exceed that venue value.
- `lfc_ledger`: the pin's actual `Ledger.snapshot()` JSON, including history tail,
  cost figures and terminal legs. The reader independently checks L_filled,
  L_resting, L, session/order/token/price identities and matched quantities
  against the journal and CLOB fills. This cap ledger is not a cash balance;
  retain its verified history alongside the snapshot and wallet cash evidence.
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
order and horizon markouts per actual filled order. Disagreement fails.
Incorrect rebate payment also fails at the receipt reconciliation tolerance;
venue payout inconsistent with the wallet's settlement evidence refuses the input.
Missing or inconsistent receipt evidence raises before certification. Source fill
quantities agree exactly; monetary reconciliation alone has a rounding tolerance.
Journal account/session identity must match the receipt scope. No-fill sessions
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
`sample_count` and `synthetic`. The CLI recomputes nearest-rank end-to-end and
decision-to-ACK p95 values; the two configured latency bounds must cover them.
Synthetic evidence is explicitly
labelled and cannot become live accuracy evidence merely by passing arithmetic.
`t1_accuracy.pin_latency_evidence` exports those samples directly from a verified
pin-format journal; its projection retains the raw journal hash and live/replay mode.
The report records Git HEAD, worktree cleanliness and hashes of all T1 modules.
Freeze authority requires a clean committed source and retained input manifests.

All replay and verification obey the workstation wrapper, HOLD and memory rules.
The exact CLI module is listed by the wrapper and hook mirror; no child or
similarly named module is admitted. Encode its argument array as UTF-8 JSON
base64 for `workstation_heavy.ps1 -Kind weather_heavy`, with absolute project
interpreter and repository paths. Fixture CLI coverage runs inside focused
wrapped pytest. Normalized JSON inputs are capped at 16 MiB and 50,000 events/commands;
the separately streamed journal is capped at 2 GiB with 1 MiB per record.
Large tape streaming/export and resumable cross-session state are separate work.
Module admission does not authorize a read of trial dates or a live action.

When using another checkout's shared interpreter, set the invoking process's
`PYTHONPATH` to `<worktree>;<worktree>\src` before starting the wrapper. The root
selects that checkout's existing bootstrap, and `src` selects its packages.
`-RepoRoot` chooses the child's working directory; it does not replace an editable
install. The CLI refuses a maker dependency from another checkout. Keep that
refusal enabled and verify the source hashes; do not change interpreter installs
or persistent environment settings to run this task.

## Values proposed for owner/master review

These are proposals only; they are not runtime defaults or a preregistration.

| Input | Proposal | Basis and limit |
| --- | --- | --- |
| f low/mid/high | 0.25 / 0.50 / 1.00; primary high absent stronger pilot evidence | Stress scenarios, not informed-trader estimates. The high case reserves another full filled cost; 0.75 has no demonstrated conservative coverage. Review the reserve definition above before freezing. |
| Latency | Measured availability-to-ACK and decision-to-ACK p95 or worse; 2 s / 1 s synthetic rehearsal only | No measured latency was supplied. The pin exposes batch start separately from data availability; freeze only after pilot measurement. |
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
