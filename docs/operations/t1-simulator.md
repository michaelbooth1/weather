# T1 maker simulator and pilot accuracy gate

Status: canonical offline implementation and evidence contract. No parameters are frozen here.

**Owns:** bounded captured inputs, receipt accounting, F0 intake and accuracy
certificates. **Read when:** preparing or reviewing T1 calibration. The
[edge trial charter](EDGE_TRIAL_CHARTER.md) owns the profit trial and its freeze;
[host load policy](HOST_LOAD_POLICY.md) owns command admission. This package
has no network client, credential access, order transport or live authority.

## Entry points and claims

`weather.backtesting.t1_simulator.replay` produces deterministic diagnostics from
explicit inputs. `t1_accuracy.accuracy_gate` reconstructs a session from a chained
journal and independent receipts. `t1_provenance.session_certificate` checks the
CLI envelope and retained raw files. `certify_campaign` consumes full CLI envelopes;
`combine_session_gates` alone is an arithmetic diagnostic, not a source certificate.
`t1_recorder` accepts the reviewed F0 writer's native shapes as partial evidence.

A result-level `status=PASS` means all session financial and calibration metrics
meet the supplied tolerances and evidence floors. It can be synthetic. A production
accuracy PASS additionally requires `accuracy_certificate.status=PASS`, nonsynthetic
inputs, common clean source, the prospective evidence contract and campaign gates.
The CLI returns zero for accuracy only under that certificate. Every output keeps
`trial_can_pass=false`: agreement does not establish positive expected profit.
`CASH_PENDING` separates matched economic accounting from completed cash. A
reconciled zero-activity session can receive completeness certification; positive
fill/reward floors apply to the frozen campaign, not each member.
Native partial intake has certificate claim `PARTIAL_INTAKE_NOT_CERTIFIABLE` and
status NOT QUALIFIED. Its certificate `gaps` and `gap_flags` mirror the result's
actual evidence checklist. Synthetic/dirty source caveats are separate
`provenance_gaps`; absent normalized fields are not called changed inputs,
excessive tolerances or an unreviewed recorder. Numerical certification is not
evaluated on that partial path, including when supplements are present.

An anonymous-book lower bound has a one-sided coverage comparison. It is never an
exact reward or net-P&L certificate. Continuous reward integration is an expectation
diagnostic, not reproduction of the venue's realized random minute samples.
Missing sample, midpoint, fee, competition or source evidence remains NOT QUALIFIED.
A real-session certificate is conditional on the books observed under that actual
intervention; it never qualifies the response to our posting on passive trial books.

## Normalized replay inputs

Use a bounded JSON session with UTC `start`/`end`, `conditions`, `events` and
`commands`. Conditions retain International venue identity, unique YES/NO tokens,
local `event_date`, native C/F unit, captured tick/minimum and coverage interval.
Cash is pUSD; quantities and prices are decimal strings. Current Gamma display
prices and weather labels cannot substitute for captured execution or venue payout.

`opening_state=flat` is mandatory. `opening_cash` is the actual funded cash, distinct
from the risk ceiling in `ReplayConfig.total_cap`. Never replenish cash by splitting
a capital period. Nonflat opening inventory is unsupported and NOT QUALIFIED.
`account_scope_complete` and independently captured `external_incentives` describe
the account-day payout threshold; other income is not this strategy's profit.
`operating_cost` is the prospectively declared cost charged to the period; receipt
accounting independently supplies its actual value.

Events carry availability `at` and `source_sha256`:

- `book`: both tokens' bids/asks, ticks, minimum size, oldest `observed_at`, captured
  `accepting_orders`, and an own-subtraction manifest. Missing acceptance evidence
  cannot admit a post. Competitor-only sides may be empty after valid subtraction;
  an executable ask and a composed qualified reward midpoint are separate checks.
  `token_times` retains each token's collection start/completion; sequential reads
  do not acquire a fictitious simultaneous timestamp.
- `terms`: captured reward rate, minimum size, spread and `valid_until`. The pin
  adapter retains the original rules and fee evidence as well as their hash.
- `trade`: exchange `traded_at`, native token outcome, aggressor, price, shares,
  stable `consumption_id`, `status` and `execution_route`. `native_sell` consumes
  that native BUY book. `complementary_mint` retains an original BUY and, with
  linked route evidence, consumes the opposite BUY book at the complement price.
  `not_buy_liquidity` explicitly identifies other flow. Mirrors share one native
  consumption identity. FAILED prints supply no fills; unknown finality, route
  or identity makes coverage incomplete. A transaction hash or wire fingerprint
  alone does not identify a unique execution.
- `settlement`: venue payout fraction `yes_payout`, source and provenance. NO pays
  its complement; split/void fractions are supported. No held inventory needs a
  settlement merely to reconcile a true zero-fill period.
- `redemption`: unique transaction identity, venue source and actual per-token
  `tokens` burned. Legacy `fraction` redeems that fraction of all filled holdings.
  Tokens cannot be redeemed twice. Resolution releases risk, while only redemption
  releases spendable principal. Redemption never creates profit a second time.
- Optional `reward_sample`: actual venue sample time and integer
  `epoch_active_sample_count`; `reward_realization=observed_samples` enables this
  path. Duplicate condition/minute samples refuse. Retain the complete sampling
  and denominator evidence; a declared count is not proof of venue sampling.
  All samples for one condition/day use the same denominator, and represented
  samples cannot exceed it. The raw projector checks the full epoch population
  and the exact in-window subset.

`rebate_pools[UTC day].conditions[condition]` carries condition identity, eligibility,
total taker fees, maker fee-weight denominator, coefficient, rebate fraction,
validity interval, completeness and source hash. Optional `category_totals` must
reconcile to the supplied condition pools. Legacy category-only pools remain
unqualified diagnostics. Captured incompatible eligibility or economics refuse.
Do not replace unavailable denominators with zero.

Rewards retain per-condition/day accrual; rebates aggregate condition allocations
before the account-day payout threshold. Accrued, estimated payable and actual
cash credits remain distinct. No unverified sub-threshold carry is credited, and
paid incentives are excluded from reinvestment under this conservative capital
policy. Missing carry/rounding evidence remains NOT QUALIFIED. The fee rule may
be `unrounded_diagnostic` or explicit per-match five-decimal half-even rounding;
the latter needs dated receipt support before qualification, not assumption.

## Queue, clocks and policy

Orders are BUY-only, post-only, capped and expiry-bound. Queue is recorded by
price level: better-price executions retire better depth, same-price executions
retire same-price depth, and sweeps deplete preceding depth. Public executions
also deplete external depth before a cancel/repost can reconstruct queue. Ambiguous
native maker assignments remain a gap. Snapshot interpolation and cancellation
priority do not prove exact queue position.

`back_at_price` can fill after represented depth is exhausted. `back_strict_through`
requires a lower print. Both are uncertainty scenarios. **Fewer fills has no
one-sided net-P&L interpretation.** The output also reports the loose fixed-command
floor: every commanded posted lot fills completely and loses, incentives are zero,
and operating costs are charged. It is a bound only for that fixed command trace,
not for an adaptive policy generating different commands under different books.

Receipt replay uses observed request/ACK intervals for posts and cancels, rather
than replacing them with a p95 stress. Exposure inside an unresolved interval is
not identified. Passive simulation keeps availability-to-order and decision-to-ACK
latencies separate; cancellation uses `cancel_latency_seconds`. Empirical p95 is
not a tail guarantee. Preserve clock precision and synchronization evidence.

Arbitrary stamped command lists do not prove an as-of policy. The implemented
`first_book_pair_v1` policy accepts only predeclared conditions, size, distance and
lifetime; it consumes the first available book and cannot inspect accounting
outcomes. Its decision trace binds book/config hashes. Other policy selection,
requotes and stops require their own reviewed event runner and prospective freeze.
Journal reconstruction is an external decision trace, not a passive strategy test.

`midpoint_rule` chooses explicit `level_filter` or `cumulative_depth` semantics.
Both candidates are available for controlled comparison. Venue-exact semantics
require dated authority; changing this candidate does not change shared live quoting.
Aggregate scoring uses the same summed price levels as midpoint composition, so
splitting one price into smaller rows cannot erase a qualifying competitor.

The deprecated config name `informed_fraction` is **cost reserve / filled purchase
cost**. Outputs call it `cost_reserve_fraction` and `cost_reserve`; the legacy
`informed_stress_cost` field is a compatibility alias. `stressed_net_pnl` subtracts
this reserve from raw net. It is not an informed-fill estimate, cannot be filled
from LFC `f_hat`, and even value one does not cover omitted or different losing
exposures. Freeze the primary profit quantity before looking at trial results.

## Independent receipt accounting

The full journal is streamed and its canonical newline bytes, sequence, clocks,
previous hashes and opened/terminal evidence are checked. Wire modes `live`,
`rehearse` and legacy synthetic `replay` retain their identity. Compatible recorder
commits are enumerated in `t1_accuracy.COMPATIBLE_RECORDER_PINS`; never relabel F0
as the legacy commit. The opened profile hash must match the retained profile.

The receipt JSON contains account/session/condition/day scope, actual recorder pin,
journal hash, profile hash and:

- `clob`: independently retained confirmed maker entries and complete `/data/trades`
  pagination through LTE=. Native order/token/side/price identities and quantities
  reconcile exactly with wallet fills and terminal LFC ledger quantities. Integer
  seconds retain uncertainty rather than fabricated subsecond precision.
- `wallet`: start/follow-up cash and clocks, selected-token opening/terminal/end
  positions including zeros, opening orders, `opening_other_positions` and
  `opening_other_open_orders`, fills, venue payout fraction/value, redemption
  transactions, reward/rebate credits, maker fees, operating cost, payment IDs and
  all other signed attributed cashflows. Unknown cashflows cannot be suppressed.
  Redemption receipts bind quantities, credit, transaction and collection time.
  `end_cash_source_sha256` identifies the common independent closing account read.
  Its shared `wallet_observations` role is separate from the session export's
  `activity_source_sha256`. `opening_observation`, `period_closing_observation`
  and `closing_observation` each name an observation `id` and `source_sha256`.
  The first two bind actual funded boundaries; the last binds the common later
  account follow-up after paid credits. A period's closing observation may be
  the next period's opening observation, without making their activity files
  identical. A shared native body is verified, not merely a copied hash.
- `state_checkpoints`: independently observed `id`, `at`, cash, reserved commitment,
  cost at risk, token positions and source hash. The engine produces predictions
  at those clocks. Required IDs cover opening/terminal, each post, cancel, actual
  fill, applicable expiry, settlement, redemption and timed cash movement; a
  caller-chosen terminal-only subset cannot certify. `transition_id` may name
  that required ID when `id` identifies an observation separately.
  Same-clock raw states require `activity_prefix_ids`: the exact observed prefix
  of ordered raw movement IDs incorporated in that native balance/position
  snapshot. Phase order is opening, expiry, executions, terminal/cancel, post,
  settlement, then redemption/payment. Settlement therefore keeps pre-redemption
  cash and tokens even at the same timestamp. Within-phase payment/execution
  ordering needs retained prefixes; absent or contradictory order remains
  NOT QUALIFIED. Do not invent subsecond clocks or simulator-derived snapshots.
- `lfc_ledger`: actual cap-ledger snapshot. The certificate replays its full retained
  chained history and compares every leg and terminal hash. This is not wallet cash.
- `rewards`: genuinely distinct reads collected during UTC D+1 and D+2. Exclusive
  session attribution is legal only once per condition/day. A shared-day
  `allocation` names the actual payment ID, full day total, every session amount,
  source hash and `method=independent_venue_accrual_deltas`. Amounts sum to the
  independently observed credit. Simulated shares cannot allocate actual rewards.
  D+1 pending/zero followed by D+2 paid is valid. Optional `reward_followups`
  retain later immutable observations at D+3 or later; do not rewrite earlier
  reads. Paid amounts must agree with finalized cash movements by each read's
  own clock, and the wallet follow-up must cover the latest observation.
- `mark_books`: independent retained raw two-token horizon books. Own subtraction
  is reconstructed from acknowledged orders/cancels and confirmed fill intervals;
  raw and removed depth must sum exactly once to the supplied competitor book.
  Shared capture errors remain a provenance question. Five-minute marks are
  diagnostics, not executable exits or informed-trader labels.

The gate compares predicted purchase cost, fees/costs, payout, redemption, residual
venue value, available cash, wallet ending cash, terminal/end positions and raw
economic and cash net P&L. The actual cash-plus-residual-assets identity
independently reconciles economic profit. Completed cash additionally requires
no remaining selected tokens/reservations and finalized redemption/paid credits
by the follow-up clock. Pending money is not completed cash profit.

Each monetary component has a predeclared absolute budget. The total absolute
error across disjoint cost, proceeds, reward, rebate, fee and operating-cost
groups also has a joint budget, summed across campaign sessions; opposite errors
cannot cancel into PASS. Proceeds use the larger of total payout error and the
sum of disjoint redeemed-cash/residual-asset errors. Certificate ceilings are one cent
for money/joint error, .00001 pUSD for cash conservation and zero shares for
native positions. Derived economic/cash net formulas, aliases, asset/cash bridges
and predicted-versus-actual net use the cash-conservation ceiling independently
of component budgets. Persisted campaign consumption recomputes these checks.
Campaign net tolerance cannot exceed the cash-conservation ceiling; a wider
option is rejected and effective net limits also respect receipt reconciliation.
Predicted and publicly reported net aliases are also compared directly with the
independent cash/economic balance bridges. Campaign reports expose
`predicted_campaign_cash_bridge` and `predicted_campaign_economic_bridge`, both
required for PASS. Separate component-to-balance and prediction-to-component
allowances cannot compose into an endpoint error above the net ceiling.
These are implementation ceilings, not owner adoption of a
trial amendment. Reserve arithmetic is
checked separately and is not deducted from completed cash.

Markout comparisons measure distance to the actual timestamp interval. An interval
wider than twice the tolerance is insufficient time resolution, not measured model
error. Reports include available 1/5/30-minute and settlement diagnostics, with
missing horizons labelled NOT QUALIFIED. Phantom fills also face position/cost gates.

Unknown held settlements remain full-loss rows and fail completeness. A campaign
must retain every scheduled/failed/incomplete session from its frozen population;
it may not select only complete or profitable reports. A true zero-fill period
needs no resolution. Unresolved exposure cannot quietly be dropped downstream.

## Campaign and evidence certificate

The supported conservative capital alternative is verified flat, nonoverlapping
funded periods with exact cash continuity. Prior unredeemed inventory prevents a
new period. Interperiod deposits/withdrawals must have independent unique IDs,
clocks and source evidence. Settled residual assets in a final period are reported
explicitly and prevent completed-cash PASS. Persistent unsettled opening lots
and overlapping daily exposure remain NOT QUALIFIED.

The combiner rejects repeated sessions, order IDs, redemption/payment IDs, false
exclusive day claims, overlapping capital and cash resets. A shared reward credit
may appear only with the same complete independent allocation across all named
sessions. The account-day threshold is applied to combined predicted accrual,
never independently to each short session. Aggregate predicted/actual net P&L has
its own tolerance. Evidence floors are coverage requirements, not power claims.
All session exports must reference the same independently observed closing cash
snapshot and its source hash. The sum of actual session profits must equal whole
account cash change, less external flows, plus remaining venue assets.
The campaign consumer decodes persisted decimal fields by their schema location;
numeric-looking token IDs and hashes remain strings. Older accounting exports
must be regenerated. Idle, zero-fill and interrupted IDs remain in the frozen
population; an incomplete member makes the whole campaign NOT QUALIFIED.

`receipts.evidence_bundle.files` lists explicit safe relative paths, roles and
SHA256s beneath the staged receipt directory. Files are streamed and verified;
there is no directory discovery. Preserve raw journal, profile, full ledger,
private fills, wallet, D+1/D+2 rewards, books/marks/terms, settlement/redemptions,
rebates, exporter source, actual recorder source manifest and preregistration. The
recorder manifest binds the clean actual recorder commit, journal/profile hashes
and session identity. Every declared source hash must bind
retained bytes. Hashes establish byte identity, not venue authenticity.

The internal raw projector checks content as well as hashes. Its financial
receipt binds exact role hashes, normalized input hashes and independently
recomputed accounts. An exporter is retained for identity, never executed as
proof of its output. Unsupported raw shapes are NOT QUALIFIED. Supported roles:

| Role | Retained body and verification |
| --- | --- |
| `wallet` | `format=t1_raw_projection_v1`, account/session, opening/terminal/closing snapshots, ordered confirmed `activity`, final `activity_cursor`, and raw checkpoints. Snapshots retain integer micro-unit `collateral_evidence.balance`, native v2 `position_walks` for OPEN/REDEEMABLE_LOST and cursor-complete `order_pages`. Optional aggregate cash/positions must match native bodies. |
| `wallet_observations` | Shared full-account native `snapshots`, each with immutable `id`, clock, collateral, complete position walks and order pages. The role binds account identity and scope completeness. Session exports reference opening, funded-period closing and common later closing observations and retain matching native bodies; each funded boundary is flat. |
| `clob` | Native request-cursor/response pages for `/data/trades` ending LTE=; confirmed maker quantities, identity and costs are independently reconstructed. |
| `settlement` / `redemptions` | Final resolution token mapping, payout numerators/denominator, availability clock; independently retained transaction IDs, burned tokens, credit and finality clocks. |
| `reward_d1`, `reward_d2`, `reward_followup_N` | Original collection clock, account/condition/day, individually identified pending/confirmed credits and full session allocation. Latest pending credits cannot certify completed payment. |
| `books`, `marks`, `terms` | Exact raw two-token books/collection clocks/own manifest; native census when claimed; F0 snapshot terms and original availability/validity clocks. Acceptance state is checked against raw fields. |
| `reward_samples`, `market_state`, `rebates` | Full sample epochs/population, raw public prints, condition/day fee inputs. Projection consistency does not establish sampling, execution-route or global-fee authority. |

Each `position_walks` status holds a list of complete walk attempts, each a list
of `{request_cursor,response}` pages. Response bodies retain `data` and
`pagination.next_cursor/has_more`; multipage positions require two agreeing
complete walks. Selected token/account/condition identities and other holdings
are checked. Raw activity rows retain ID, kind, clock, confirmed status, cash
delta, native BUY price/quantity or REDEEM burned quantities, and payment
finality. Unknown manual exits, other terminal holdings or uncovered activity
cannot qualify this flat BUY/hold projection. These envelopes require retained
native bodies; copying normalized totals into them is not a native export.
The wallet also retains `period_closing` and the three corresponding
`*_observation_id` references. With shared observations, ending-cash source binds
that role; activity source binds the separate session wallet role. Raw interperiod
funding changes need an independent movement adapter and remain unsupported.
Post-period foreign movements may retain signed native `token_deltas` for other
tokens; every intermediate full-account position must reconcile to those
movements. This does not admit overlapping funded periods or opening carry.

The JSON preregistration binds the common clean CLI source envelope, configuration,
tolerances, exporter, `expected_session_ids`, a prospective `frozen_at_utc`, and
`missing_session_rule=FAIL_WHOLE_CAMPAIGN_RETAIN_FULL_LOSS_ROWS`.
The final certificate rejects synthetic, dirty, mixed or unsupported pins and
unqualified components. Actual venue sampling, midpoint semantics and condition-day
rebate precision require their own retained evidence. A passed conditional pilot
cannot identify posting-induced competition: the passive incentive floor remains
zero until a defensible intervention/response envelope is independently validated.
No authoritative sample-feed, midpoint-rule, public execution-identity,
global rebate-input or precision-rule verifier is implemented. Active sessions
therefore retain those NOT QUALIFIED components even with internally consistent
raw projections. Hash-linked `midpoint_rule_evidence`, `reward_sample_evidence`
or `fee_rounding_evidence` labels cannot override this. Qualification needs a
reviewed authoritative/independent adapter or a separately frozen uncertainty
design. Irrelevant market components are NOT APPLICABLE for proven idle sessions.

## Native F0 intake and command

For partial intake, set inputs to `input_kind=f0_lfc_recording` and the actual
`recorder_pin` from `t1_accuracy.F0_PIN`. Supply the original journal; receipts may
be an empty JSON object. The adapter preserves raw snapshot diagnostics, exact
submit/cancel ACKs, confirmed versus pending terminal trades, profile and journal
identity, and explicit gap flags. It never sets invented coverage/complete flags.
An optional `normalized_payload` plus complete supplementary receipts runs the
strict comparison beside this partial report. The native report remains partial.

The reviewed F0 pin replaces its predecessor; native intake accepts only that
exact identity. Normalized intake, latency binding and certification share
`t1_accuracy.COMPATIBLE_RECORDER_PINS`, which also retains the legacy LFC pin.
Journal byte compatibility alone does not authorize an additional recorder pin.

F0 normally captures books each minute and stops soon after a fill. It lacks
continuous post-fill books, unique confirmed public maker consumption, exact
competing orders/random samples, complete day denominators, independent shared
paid-reward attribution, rebate totals and a complete cash/redemption account.
Position endpoint repairs do not create those missing observations. These gaps
cannot be repaired by loosening freshness or relabelling a rehearsal as live.

Use `python -m weather.backtesting.t1_cli simulate` or `accuracy` with `--inputs`,
`--config`, `--latency-evidence`, `--output`; accuracy also requires `--journal`,
`--receipts`, `--tolerance`. Paths are explicit; output creation is exclusive.
Accuracy exits 2 on a diagnostic match without a real certificate, incomplete
F0 evidence, mismatch or insufficient evidence. No freeze/trial command exists.

Latency evidence contains sample clocks, count, kind, synthetic identity and a
file hash bound by config. Complete replay recomputes both empirical p95 values.
Partial F0 intake alone permits an empty measurement set, clearly unqualified.
The report binds all T1 sources and their imported first-party economic dependencies.
Run through `scripts/ops/workstation_heavy.ps1 -Kind weather_heavy`, encoding the
exact argument array as UTF-8 JSON base64. Check task HOLD/freeze constraints first.
Set process `PYTHONPATH` to the worktree and its `src` when sharing an interpreter.

Normalized inputs are bounded to 16 MiB and 50,000 events/commands. Journals stream
under the explicit reader limits; raw evidence bundles are bounded to 2 GiB.
Admission never grants access to trial dates, credentials, a reader or a venue.

## Update triggers

Update with input/export, financial identity, timing, queue, reward/rebate, policy,
qualification or CLI changes. Synthetic constructors and regression coverage are
in `tests/backtesting/t1_fixtures.py` and the `test_t1_*` modules. Real qualification
requires its own authorized, mature evidence run and prospective contract.
