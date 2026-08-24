# International Maker Pilot Preregistration

Status: preregistered design; no live result. International Polymarket only.
This document narrows how the approved bounded pilot may be interpreted. It
does not authorize an order, override a gate, or establish the operator's or
execution host's action-time geographic eligibility.

All trading, balance, fee, and rebate outcomes are measured in native pUSD.
Compatibility field names containing `_usdc` denote dollar-scale amounts only;
they do not change the settlement asset.

## Decision being tested

The commercial hypothesis is not merely that a weather model can quote near
the market. It is that authenticated maker fills, including the maker rebate
actually attributed and paid for the same market/day, produce positive net
cash economics after adverse selection, inventory, exit, and settlement costs.

The first live order cannot establish that hypothesis. The experiment has two
separate verdicts:

1. **Lifecycle verdict:** the exact wallet and SDK can place only post-only
   liquidity, observe it through authenticated truth, and cancel it through
   both cancel-all and heartbeat lapse without residual orders or inventory.
2. **Economics verdict:** completed market-days show positive reconciled cash
   economics under the frozen analysis below. Until this verdict is earned,
   the run is an instrumentation experiment and capital remains capped.

## Unit of evidence

- Order and fill identity comes only from the authenticated account stream and
  exact REST reconciliation. The public market stream has no documented unique
  execution identifier and cannot supply own-fill counts.
- A fill enters economics only at the exchange's terminal confirmed state.
  `MATCHED`, `MINED`, and `RETRYING` remain pending; `FAILED` contributes no
  fill.
- The primary unit is a completed `maker address x condition x UTC payout day`
  account-market cell. This matches the documented per-market daily rebate
  calculation and avoids pretending that a wallet-level payout belongs to one
  selected fill.
- Rows from different conditions or payout days are never pooled before each
  cell passes identity, fee, position, balance, and rebate reconciliation.

## Frozen outcome definitions

The primary outcome is reconciled net cash P&L divided by confirmed maker-fill
notional. Reconciled net cash P&L is the exact starting-to-ending settlement
asset balance change, plus ending marked or redeemed position value, minus
external cash flows, with fees and paid incentives included exactly once. The
cash-flow identity must balance to the documented fee precision.

Secondary outcomes are:

- spread capture before incentives;
- signed markout at fixed post-fill horizons, including the existing 30-minute
  horizon;
- settlement P&L before incentives;
- predicted fee-equivalent rebate versus the exact `/rebates/current` cell;
- paid rebate versus the predicted and accrued amounts;
- fill-side imbalance, time-in-market, cancellation latency, and unexpected
  taker incidence.

Theoretical rebate and liquidity-reward estimates are diagnostics. They do not
enter the primary outcome until authenticated payout and balance reconciliation
prove receipt. Missing settlement, payout, balance endpoint, position, or fee
evidence makes the cell incomplete rather than zero or profitable.

## Quote treatment

The initial economics treatment is one selected band for one TTL, outside the
protected host window, with the smallest currently valid order size. A two-sided
quote is expressed as backed buys of complementary outcome tokens; no naked
sell is permitted. Both orders must fit the existing band, event, daily-loss,
wallet, and pilot ceilings under the worst case in which every resting order
fills.

The selected market, band, model release, fair probability, quote prices,
sizes, TTL, and all gate hashes are journaled before submission. Selection may
use only information available at that instant. A market or session cannot be
dropped after observing its fills, markouts, settlement, or rebate merely
because its economics are unfavorable.

The simultaneous paper counterfactual is frozen before the live submit. It is
diagnostic for missed fills and quote choice; it does not replace account cash
truth.

## Sequence and stopping

1. Pass Stage 0 on the production execution host.
2. Pass one heartbeat-lapse Stage 1 run and one cancel-all Stage 1 run. Neither
   run seeks a fill.
3. Run one minimum-size, one-TTL economics treatment. End with cancel-all,
   exact open-order and position reconciliation, and a durable journal.
4. Reconcile every fill through terminal exchange status, settlement or
   redemption, and the completed daily rebate cycle before interpreting net
   economics.
5. Repeat the same frozen treatment without increasing capital while the
   result remains diagnostic.

Stop immediately on any existing runbook stop condition, any taker execution,
unexplained cash difference, unbounded position, missing heartbeat, unknown
order, evidence loss, selection drift, or mismatch between live and journaled
intent. A safety failure overrides an economically positive result.

## Statistical claim boundary

No fixed small number of fills is a profitability proof. A positive point
estimate, a paid rebate, or one profitable market-day is only feasibility
evidence. The economics verdict requires all of the following:

- no safety or reconciliation failures in the included cells;
- positive aggregate reconciled net cash P&L;
- a positive lower confidence bound for net cash P&L per maker-fill notional,
  resampling whole market-day cells rather than individual fills;
- positive results after removing incentives, reported separately, so the
  operator can see whether the system depends entirely on a mutable program;
- no single market-day or condition accounting for the verdict; and
- predicted-versus-actual rebate error explained within the documented payout
  and precision rules.

Until the sample supports that claim, reports must say `INSTRUMENTATION_ONLY`
or `ECONOMICS_INCONCLUSIVE`, never `PROFITABLE`.

## Required negative controls

- Recompute the result with all rebates and liquidity rewards set to zero.
- Recompute with any unconfirmed fill removed.
- Recompute under a conservative exit/settlement treatment for every residual
  position.
- Show the same treatment's simultaneous paper quote and whether the live fill
  arrived during stale book, model, watcher, or source evidence.
- Report every attempted session, including zero-fill and aborted sessions.

## Update rule

Changing the primary outcome, unit of analysis, inclusion rule, quote treatment,
or profitability threshold after the first live economics order creates a new
dated preregistration. The original remains the interpretation contract for all
orders already observed.
