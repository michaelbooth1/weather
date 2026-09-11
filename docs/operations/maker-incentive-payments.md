# Incentive payment reconciliation

Status: canonical input and reporting contract. Owner: weather.market.mm_exchange_reports.

The pure helper `weather.market.mm_incentive_payments.reconcile_incentive_payments`
matches supplied, normalized International incentive distributions to explicit
wallet transfers. It performs no I/O, authenticates no account, places no orders
and does not independently verify the supplied source evidence. A successful
fixture or mathematical reconciliation is not an observed payment or profit.
[Item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md)
owns implementation and qualification status.

## Scope and source qualification

The input uses the registered `mm_incentive_payment_evidence` schema. Its
`platform` must be `polymarket_global`. One `scope` binds the maker address,
the collateral asset in CAIP form (`eip155:137/erc20:0x...`), an ISO UTC
`query_date`, and one condition ID or explicit null for a portfolio period.
No asset is inferred from a legacy field ending in `usdc`.

These are application-owned normalized fields, not advertised venue API
response fields. A future capture/normalization reader must retain the official
request scope, every page/cursor and raw response, timestamps, current payout
rules and wallet transfer evidence, and verify the hashes before supplying
this structure. Setting a completeness flag or presenting a hash does not
perform that verification. This helper and the initial fixture integration
do not establish such a reader or any current account qualification.

Both incentive programs need separate queries: `maker_rebate` and
`liquidity_reward`. Each query repeats the exact scope and supplies
`earnings_sha256`, `distributions_sha256`, `rules_sha256`,
`queried_at_utc` and `payout_due_at_utc`. Its observed status, completed
earnings and distribution queries, and completed payout cycle must all be
explicit. “Complete” means the entire bounded exact-scope response, including
all pages; partial pagination cannot be normalized as complete. The payout
deadline comes from retained rules and must follow the earning date. A query
before that deadline remains incomplete.

The wallet query separately binds maker, asset, source hash and an explicit
coverage interval. Complete coverage must start no later than the earning
date and extend through the incentive queries. Supply the incentive transfers
being reconciled; unrelated deposits and withdrawals belong in the existing
financial identity's external cash flows. An unexplained extra supplied credit
blocks complete incentive attribution.

## Records and matching

Each earnings, distribution and wallet-credit list is bounded to 1,024 rows.
Every row has a nonempty stable ID and retained source SHA-256. Duplicate
record IDs are rejected. Reusing an earning/transaction/log allocation under
a different distribution ID is also rejected. A normalized earning is unique by program and
condition within this account/asset/day scope; repeated snapshots of the same
earning must not become additional income.

- Earnings retain program, account, asset, date, condition and nonnegative
  amount. Decimal strings or integers preserve up to twelve decimal places.
- Distributions name their earning ID and exact wallet transaction hash plus
  log index. Their program, account, asset, date and condition must agree with
  the earning. Amount-only matching is unsupported.
- Wallet credits bind account, asset, transaction hash, log index, amount,
  confirmation status and confirmation time. A second ID for the same
  transaction/log is still a duplicate. Pending, failed and reverted transfers
  cannot establish paid income.

Payment amounts use at most six decimal places. Partial payments can share an
earning, but total allocations cannot exceed its accrual rounded to six places
with half-up rounding. Several allocations of one program may share a credit
only when they explain its full amount. A credit claimed by both programs is
rejected. Any rounding residual is reported separately. The helper uses its
own Decimal context rather than ambient process precision.

Portfolio evidence cannot be assigned to a condition without explicit source
attribution. With a requested condition, portfolio earnings/payments stay
unresolved. An explicitly requested portfolio reconciliation can retain a
portfolio payment; it does not infer a session allocation.

## Results and financial reports

The registered `mm_incentive_payment_reconciliation` result separates
estimated amounts, accruals, diagnostic matched payments, bookable paid amounts,
unpaid accruals, rounding residuals and unresolved distributions. Bookable
`paid_amount` is null if any required query or attribution is incomplete.
Completed exact-scope empty queries can establish zero payment. A positive
unpaid accrual remains visible without assuming later payout or carry-forward.

Every result explicitly reports `source_evidence_independently_verified=false`
and `live_permission=false`: the calculation validates supplied records and
cannot vouch for their capture. Do not report a real paid incentive without the
separate source qualification and account evidence.

`mm_exchange_adapter_v0.3` financial reports require matched, exact-scope
maker-rebate and liquidity-reward payment evidence in
`rewards.incentive_payment_evidence`. A positive legacy venue rebate query
is retained as an accrual and cannot alone establish paid rebate income.
The supported financial report also checks the actual collateral address.
Missing or unsupported payment evidence keeps total financial reconciliation
incomplete. The renderer labels the payments as matched records and states that this
reconciliation does not independently verify their source evidence. It explicitly
refuses prior report versions;
retained legacy records are historical evidence and are never rewritten.

Only matched paid incentives enter the existing gross trading P&L minus fees
plus incentives identity. External cash flows stay outside profit. Existing
confirmed-fill, position, scope, gross-settlement-basis and cash-residual
checks remain. Paid rewards without fills can support supplied-record cash
reconciliation, while fill-quality and markout evidence remain incomplete.
The conservative paper assumed-reward contract is unchanged.

## Update when

Update when normalized record scope, precision, attribution, completeness,
schema compatibility or financial-report behavior changes. Record actual
source-reader and account qualification in item 330 with retained receipts.
