# Explicit-input maker incentive feasibility

Status: canonical diagnostic contract.

`weather.market.maker_incentive_feasibility.assess_buy_plan` evaluates one
explicit YES BUY, NO BUY, or simultaneous pair of BUY orders. It is a pure
calculation with no file loader, network client, executor integration, or CLI.
It returns separate order, capital, reward-eligibility, and payment-estimation
results. A feasible result grants no order or promotion authority.

## Supplied evidence

- `MarketTerms` reuses the per-condition names in
  `exchange_economics`'s `markets[]` projection, with a mandatory separate
  exchange-minimum unit (`shares` or `collateral`) and source reference.
  Supply the exact YES/NO token
  mapping and explicit collateral asset; never infer outcomes from a sorted
  token list. The registered canonical event slug preserves the native market
  unit. The platform is International Polymarket only.
- Every `Evidence` carries a full SHA-256 and timezone-aware capture time.
  The caller supplies `as_of`, the horizon end, terms freshness, stricter book
  freshness, and paired-book skew limits. Future inputs are rejected.
- `Book` inputs are the named condition/token's best prices, with references
  to their captured representations. Existing full-book readers in
  `order_book_tape` own representation selection; this calculator does not
  scan tapes or reinterpret aggregated recon rows.
- `AdjustedMidpoint` must explicitly identify size-cutoff adjustment, its
  method reference, both input-book hashes, and the exact reward size cutoff.
  It must be captured no earlier than those books. There is no ordinary
  midpoint fallback and no new midpoint-construction algorithm.
- Supply exactly one `Campaign`, identified by condition, allocation ID, and
  canonical `eip155:<chain>/erc20:<lowercase-address>` reward asset. Its interval
  is explicitly half-open with timezone-aware endpoints and a boundary
  reference. The calculator does not reinterpret ambiguous API calendar dates.
  Missing, nonoverlapping, or zero-rate allocations are incentive infeasibility;
  multiple allocations are unsupported and rejected rather than combined.
- `ScoringRules` carries captured multiplier, one-sided divisor and midpoint
  endpoints. These changing values have no implicit defaults.

This validates supplied identity, chronology, and numerical consistency; it
does not authenticate the referenced bytes or establish that supplied facts
are true. Production evidence still requires the existing economics source
gate. Historical work requires the exact snapshot captured by its own run;
today's snapshot cannot qualify old evidence. Synthetic fixtures remain
synthetic even when all consistency checks pass.

## Calculation

Prices are probability prices in whole collateral units per share. Sizes are
shares. Monetary and score inputs are finite `Decimal` values, at most `1e18`,
with decimal exponents from -18 through 18. An isolated 80-digit context makes
capital products and comparisons independent of the caller's Decimal context;
there is no float coercion or asset conversion. Reward minimum shares and
maximum distance cents differ from the exchange minimum and price tick.
[Polymarket market details](https://docs.polymarket.com/market-data/market-details)
describes those units and dated allocation fields.
That page currently describes Gamma `orderMinSize` as USDC notional. Do not
assume the retained `order_min_size` name denotes shares, or equate it with a
different CLOB field. The caller must bind the selected unit and asset to its
source; unproved units are rejected.

Convert maximum distance cents once: `v = rewards_max_spread_cents / 100`.
An eligible order contributes `size * ((v - distance) / v)^2 * multiplier`.
Distance is measured from the adjusted YES midpoint or its NO complement;
at or outside `v` the contribution is zero. YES BUY and NO BUY contribute to
opposite sides. In the supplied inclusive midpoint range,
`Qmin = max(min(Qyes,Qno), max(Qyes,Qno)/divisor)`; outside it, use the minimum.
Normalize using `Qown / (Qown + Qother)`.
[Polymarket liquidity rewards](https://docs.polymarket.com/programs/liquidity-rewards)
defines this per-maker scoring and epoch normalization.

The supported plan excludes other own resting orders on the condition,
explicitly declared by `other_own_orders_absent=True`. Otherwise the module
refuses: nonlinear per-maker aggregation prevents treating our existing quotes
as competitors. SELL orders, conversion and existing-own-order scoring require
a separately scoped extension.

Every proposed order must fit exchange size, tick, accepting-order and
nonmarketable BUY checks. All planned orders must also qualify for positive
reward scores for the plan to be incentive-feasible. The recommended minimum
quantity is the larger reward cutoff and the exchange submission minimum
converted to shares at each proposed price. Notional-derived thresholds round
up to 18 fractional digits. There is no automatic price selection or resizing;
the caller still owns any venue share-quantity grid. A resting partial remainder
is scored against the reward cutoff, without reapplying a new-order submission
minimum.

`Capital.backed_capital` means free collateral plus existing reservations plus
fully funded inventory cost. `available_collateral` cannot exceed that amount
less inventory and reservations. This preserves the reservation principle in
`mm_risk` while adding explicit asset identity and exact Decimal bounds.
Condition and event commitments are nested portions of existing tied capital.
New reservation is the sum of all simultaneous `price * shares` amounts.
Cleanup reserve must also fit available cash and condition/event limits;
order caps and the total wallet capital cap are checked independently.
Cancellation, complete-set conversion, resale, or future reward proceeds do
not reduce required funding. These are capital checks, not loss estimates.

## Conditional reward scenarios

Each named `CompetitionScenario` supplies a range for the sum of other makers'
already aggregated `Qmin`, participation across samples, and remaining size
fractions separately for YES and NO. Remaining sizes are rescored against the
minimums, so a partial fill can erase a side's eligibility. Anonymous aggregate
depth and `clob_recon.reward_competitor_q` are not this denominator.

Without `EpochPayoutModel`, the result contains scores and shares but no reward
amount. An explicit model binds one campaign/asset, an epoch containing the
whole plan horizon, an assumed epoch pool, planned samples and the total
nonempty epoch samples. Conditional estimates multiply that pool by the sample
weight, participation fraction, and share range. The model's denominator must
account for all scored samples, including those outside our plan. There is no
daily-rate prorating. A configured daily rate is not a receivable; sponsored
rates may already be folded into the supplied allocation.
[Polymarket's raw reward configuration contract](https://docs.polymarket.com/api-reference/rewards/get-raw-rewards-for-a-specific-market)
describes that folding.

Estimates are bounded by the declared pool and are assumptions, not expected
payments. The declared payout-minimum comparisons are reported separately;
they do not establish the venue's aggregation or payment treatment. Every
result includes a zero-payment possibility, `paid_rewards=None`, and
`realized_pnl=None`. Nothing updates primary liquidity-reward P&L, executed
maker rebates, or reconciled paid receipts.

## Verification

Deterministic cases live in
`tests/market/test_maker_incentive_feasibility.py`. Run that file and the import
architecture ratchet through the owning host's required workload wrapper.
The fixtures cover identity/freshness refusal, C/F event identity, quadratic
distance, cutoff endpoints, size/tick/post-only limits, simultaneous capital,
campaign absence, competitor dilution, participation and partial-size loss,
and explicit epoch binding. No venue access is required.

## Update when

Update alongside input or result contracts, supported order plans, scoring or
capital semantics, or any consumer that attempts to persist or promote these
diagnostics. A persisted artifact would need the normal registered schema and
captured-input lineage; this in-process return value creates neither.
