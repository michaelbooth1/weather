# Account evidence for paid maker incentives

Status: canonical capture specification. W4 owns supplied-evidence validation
and reconciliation; this specification defines the missing collection boundary.
It does not authorize a live order or turn an accrual into cash.

## Evidence chain

| Relationship | Required evidence | Current implementation boundary |
| --- | --- | --- |
| Maker and earning date to condition/asset accrual | Complete, exact-scope raw earnings pages and programme/date identity | `mm_liquidity_earnings_capture` collects bounded raw pages for the existing validator; completed empty scope is distinct from missing pages |
| Accrual to distribution | An authoritative stable allocation identifier linking programme, maker, earned period(s), condition attribution and integer native amount to a distribution | No qualified authoritative source/interface is established |
| Distribution to wallet credit | Distribution identifier linked to exact chain, transaction hash, log index, recipient, asset and amount | `mm_exchange_reports.reconcile_incentive_payments` validates supplied links; caller-created IDs do not prove their authority |
| Activity to confirmed asset transfer | Exact raw account activity plus successful receipt and finalized block evidence | `mm_paid_credit_activity` supports its documented legacy activity shape and pUSD transfer scope; it never proves the earned period |
| Episode to complete cash result | Opening/closing balances and the full account cash, fill, position, funding, fee, reward, rebate and settlement scope | Supplied financial reconciliation requires independent completeness evidence |

Aggregate distributions remain aggregate. Equal amount or nearby time cannot
split a payment across conditions or earning periods. A single credit cannot
fund two distributions. An external deposit is funding, not incentive income.
A reversed credit needs an explicit supported reversal contract; until then
the existing matcher rejects it rather than inventing negative earnings.

## Read-only transport contract

Use the installed, hash-bound SDK only after inspecting construction and
authentication side effects. The reviewed `polymarket-client` 0.6.0 secure
constructor calls wallet-readiness logic that can deploy a wallet. Do not
construct that client incidentally to read earnings. The installed
`list_user_earnings_for_day` path uses a JSON-returning transport: the parsed
result cannot recreate original response bytes or HTTP metadata.

A collector must instead accept an already-qualified identity/authentication
context and perform only the reviewed read requests. It must not create API
credentials, deploy wallets, approve tokens, sign orders, refresh allowances,
bridge, redeem, transfer, or mutate sessions as an incidental prerequisite.
Keep secret header values in host-local memory and out of outputs. Record
header names and the public maker identity, never bearer tokens, API secrets
or signatures.

For each request retain method, exact allowlisted host/path/query, request
sequence and UTC times, response status/content type, byte count, original
bounded bytes in base64 and SHA-256, cursor in/out, and terminal/error state.
Hash original bytes before parsing. Reject redirects outside the same reviewed
scope, duplicate JSON keys, nonfinite numbers, repeated cursors, missing pages,
mixed assets/identities, and truncated bodies. Preserve partial responses and
the failure receipt in a new attempt namespace; incomplete never means zero.

### Earnings

The [official earnings endpoint](https://docs.polymarket.com/api-reference/rewards/get-earnings-for-user-by-date)
is `GET https://clob.polymarket.com/rewards/user`, keyed by date and signature
type. Match the authenticated maker identity and the supplied query contract;
do not infer it from an unrelated signer or a UI profile. The existing adapter
supports signature types 0, 1 and 2; another signature type requires a reviewed
contract change. Sponsored and standard rewards are separate scopes.

Use the validator's maximum 50 pages, maximum 100 rows per page, terminal
`LTE=` cursor, and existing per-response/total byte budgets. A bounded capture
request selects one maker and one earned UTC date before any request. Returned
condition and asset rows stay intact; do not filter pages before proving
termination. An empty completed date or below-minimum accrued date is not a
positive receivable. Check finality after the documented daily cycle using a
new capture; never overwrite the earlier snapshot.

### Daily earnings collector

[`weather.market.mm_liquidity_earnings_capture`](../../src/weather/market/mm_liquidity_earnings_capture.py)
implements `capture_liquidity_earnings` for the earnings relationship only. Its
keyword arguments freeze `query_date`, `maker_address`, `signer_address`,
`signature_type`, `sponsored`, an absolute fresh `output_dir`, and a
`headers_provider` callback. The callback receives `("GET", "/rewards/user", query)`
and returns the existing five CLOB L2 headers. Query parameters are supplied
separately so the caller can apply its already-reviewed signing contract.
The caller must independently qualify the signer/maker/signature-type binding;
the collector validates the declared signer header and requires matching maker
and signer for EOA type 0. It does not derive or attest proxy-wallet ownership.

This library entry point has no credential loader, SDK constructor, session
mutation, environment discovery or unattended CLI. Calling it requires an
already-qualified authentication context and authority for the account read.
It constructs verified HTTPS connections to the fixed official host, sends only
GET requests, and never follows redirects or retries. Existing capture-host and
workstation admission rules still govern where it may execute.

One invocation has a 60-second cooperative capture deadline, at most 10 seconds
per socket operation, and the existing earnings page/byte budgets. The clock is
checked between reads and requests; caller authentication code and system DNS
resolution are outside that cooperative deadline. A caller requiring absolute
process teardown must retain the governing workload wrapper. All pages retain
all returned conditions and assets; projection happens only after termination.

The registered capture schema has three artifact kinds, all created exclusively:

- `intent.json` freezes scope and budgets before authentication or network work.
- `request-NNN.json` preserves sequence, public request identity, header names,
  request times, cursor state, HTTP metadata and exact response bytes/hash.
  Failed and oversized responses retain available prefixes with
  `body_complete=false`; a known authentication-secret echo is withheld and
  makes the attempt incomplete.
- `capture.json` binds request-file hashes and returns either `COMPLETE` or
  `INCOMPLETE`. Only complete, scoped pages produce normalized earnings.
  Available prior request files survive failure; an interrupted invocation
  without a terminal receipt is incomplete and must not reuse its directory.

The normalized earnings retain exact decimal spellings through the existing
validator. To replay, verify the request-file hashes in `capture.json`, extract
each request's `response` in sequence, and pass those raw pages to
`normalize_liquidity_earnings_pages` using the frozen scope and cutoff.
The owner tests perform this replay and compare the normalized result.

A complete empty date is an empty accrual scope, not zero paid income. Every
capture keeps paid amount unknown, attribution blocked, and payment, source
authenticity, identity binding, whole-account completeness and live-authority
claims false. A local collection receipt is not independent source attestation.
This collector does not synthesize the missing distribution, earned-period or
transaction/log relationship or feed inferred amounts into financial reporting.

### Activity and chain receipts

The [activity-to-credit contract](paid-credit-activity-evidence.md) remains the
authority for the implemented legacy adapter: full account query scope, exact
pagination, timestamp ordering, and bounded raw captures. Its pUSD-only transfer
scope cannot validate a different liquidity-reward asset.

The [current activity API](https://docs.polymarket.com/api-reference/feeds/list-account-activity)
uses `/v2/activity`, user anchoring, bearer authentication and a cursor envelope.
The [migration guide](https://docs.polymarket.com/api-reference/data-api/migrating-from-v1)
keeps legacy interfaces separate. A v2 collector needs a new parser/schema
contract for its request and terminal cursor semantics; do not label v2 data as
legacy evidence. Neither documented activity format supplies an authoritative
earned-period-to-distribution allocation.

Chain collection is limited to the read methods, exact transactions and numeric
blocks in the bridge contract. Bind chain 137, canonical block/receipt identity,
successful execution, recipient, ERC-20 contract, integer amount and one exact
Transfer log. Read-only RPC POST is distinct from an exchange mutation.
Retain unresolved reorg/finality cases. The existing bridge's limits remain
256,000 bytes per capture, 2,000,000 total bytes, 128 captures per source list,
1,000 activity rows and 2,000 receipt logs; exceeding a bound returns an
incomplete request requiring a new reviewed scope.

### Whole-account cash scope

Freeze the account, asset set and half-open episode interval before capture.
For each native asset retain opening and closing balance snapshots at explicit
blocks/times; all fills and their fees; open-order reservations; positions and
inventory cost/valuation; deposits, withdrawals and transfers; independently
paid rebates/rewards; settlement/redemption flows; and every excluded external
funding row with its authoritative reason. Reconcile integer native quantities
before any conversion. Conversion into a common P&L unit requires its own
observed asset/rate/time contract.

A positions/equity accounting snapshot is supporting evidence. It cannot by
itself establish all intervening cash flows or the distribution allocation.

## Acceptance and reopening condition

`ATTRIBUTION_PATH_IDENTIFIED` requires a source-bound path through every
relationship above and tested completion/error semantics. Actual reconciliation
also requires complete account receipts; identifying a path is not payment.

Otherwise retain `ATTRIBUTION_BLOCKED`, naming the missing relationship.
The minimum reopening evidence is one authoritative distribution record that
binds the maker, programme, earned period(s), condition allocation or explicit
aggregate status, asset, integer amount, and exact credited transaction/log,
plus documented coverage/finality semantics. The daily earnings collector
closes only its raw acquisition boundary. Distribution collection and any
necessary native-asset/v2 payment adapter still require that evidenced contract.

## Update when

Update when an authoritative allocation source is qualified, SDK construction
or raw transport changes, a supported activity/asset contract changes, or the
account reconciliation boundary changes. Status and dated receipts belong to
[item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).
