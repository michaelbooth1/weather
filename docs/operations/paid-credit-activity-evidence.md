# Derived activity-to-pUSD credit evidence

Status: canonical evidence contract.

[`weather.market.mm_paid_credit_activity`](../../src/weather/market/mm_paid_credit_activity.py)
owns a pure `bridge_activity_credits(evidence)` transform. It joins a supplied
Polymarket activity row to one exact pUSD Transfer in supplied Polygon receipt
evidence. It performs no network, file, credential or exchange operation and
does not confer live authority.

`JOINED` means the supplied records satisfy the documented consistency checks.
The caller supplies every capture and its provenance; this transform does not
authenticate the endpoint or prove the caller actually made the request. The
result always retains `source_authenticity_verified=false` and
`evidence_origin=CALLER_SUPPLIED_RAW_CAPTURES`.

See [the International pilot](INTERNATIONAL_MM_LIVE_PILOT.md) for the separate
lifecycle and financial reporting gates. This bridge does not feed the paid
accrual matcher or alter those gates.

## Source meaning

The [official activity API](https://docs.polymarket.com/api-reference/core/get-user-activity)
documents `REWARD` and `MAKER_REBATE` row types, wallet, condition, timestamp,
transaction hash and `usdcSize`. Its `asset` field identifies an outcome token;
it is not the collateral contract. Neither an earned date, an accrual reference,
a transfer log index nor transaction finality is supplied by that row. The
bridge retains the venue type as a label without translating it into a verified
economic programme.

[pUSD](https://docs.polymarket.com/concepts/pusd) is a transferable ERC-20 with
six decimals. The [official contracts page](https://docs.polymarket.com/resources/contracts)
owns its Polygon mainnet chain and proxy address; the code imports the existing
repository address constant. Names containing `usdc` never replace the explicit
native-pUSD identity.

[ERC-20 Transfer](https://eips.ethereum.org/EIPS/eip-20#events) identifies sender,
recipient and integer amount. A [transaction receipt](https://ethereum.org/developers/docs/apis/json-rpc/#eth_gettransactionreceipt)
binds the transaction, execution status, block and logs.
[Polygon finality](https://docs.polygon.technology/pos/concepts/finality/finality)
supports the `finalized` block tag. The bridge checks these supplied responses;
it does not choose or endorse a live RPC provider.

## In-memory input contract

The only top-level keys are `scope`, `activity_captures` and `rpc_captures`.
Unknown top-level keys, including an attempted `accruals` addition, are rejected.
No current file writer or durable artifact schema is introduced. A future
persisting consumer must register its durable schema and preserve the raw input
captures with the result; output hashes alone cannot reconstruct source bytes.

`scope` requires:

- `maker_address` and `condition_id`: exact requested account and condition.
- `chain_id`, `asset_address`, `asset_decimals`: exact Polygon native-pUSD identity.
- `activity_start_utc`, `activity_end_utc`: inclusive UTC activity timestamp
  bounds, at whole-second resolution, with start before end.
- `as_of_utc`: explicit UTC evidence cutoff, at or after the window end. Capture
  observations after this cutoff are rejected; replay never consults wall time.

Each capture has exactly these fields:

| Field | Meaning |
| --- | --- |
| `source_id` | Bounded opaque caller label for the source. RPC responses used in one transaction proof must share it. It is not source authentication; do not put a credential, URL or secret here. |
| `request` | Exact structured request described below. Its canonical JSON SHA-256 is retained separately from the raw response hash. Request metadata remains a caller assertion. |
| `observed_at_utc` | Caller-supplied UTC observation time, no later than `as_of_utc`. |
| `http_status` | Required integer success status. |
| `raw_response` | Retained UTF-8 JSON response text, parsed directly with Decimal for non-integer numbers. |
| `raw_response_sha256` | SHA-256 of exactly those UTF-8 bytes, including whitespace. |

The source module owns byte, capture, row, log and transaction-count bounds.
Duplicate JSON keys, non-finite numbers, malformed quantities, excessive nesting
and oversized captures fail closed. Retain original bytes rather than serializing
an SDK model back to JSON: Decimal fields cannot recover earlier float rounding.

Activity requests are exactly `{"method": "GET", "url": "..."}`. The URL must
use the official HTTPS `/activity` endpoint, with each parameter present once:
`user`, `start`, `end`, `limit`, `offset`, `sortBy=TIMESTAMP`,
`sortDirection=ASC`, `excludeDepositsWithdrawals=false`. Account and epoch bounds
must equal the scope; page limits and offsets must satisfy the official API
bounds. Market/type filters and other parameters are not accepted by this
contract. Activity capture must occur at or after the window end.

All requested pages are retained in provenance, but a supplied collection of
pages is always a subset for this transform. Gaps, an empty page, a full page,
or offset-cap termination cannot establish full account coverage or zero paid
incentives. Non-incentive row types are ignored; incentive rows for another or
unknown condition prevent a successful scoped join.

RPC `request` is a JSON-RPC object with `jsonrpc`, integer `id`, `method` and
`params`. The raw response must be a matching success envelope with `result`.
Only these read methods and parameter shapes are accepted:

| Method | Required parameters and result |
| --- | --- |
| `eth_chainId` | `[]`; returned chain must match the fixed native-pUSD chain. |
| `eth_getTransactionReceipt` | `[transaction_hash]`; successful receipt with transaction/block identity, transaction index and complete standard log records. |
| `eth_getBlockByNumber` | `[receipt_block_number, false]`; canonical block at that numeric height, with matching block hash and transaction at the receipt's transaction index. |
| `eth_getBlockByNumber` | `["finalized", false]`; finalized height must cover the receipt height. Equal heights require equal block hashes. |

The canonical numeric-height block must be observed at or after the finalized
response. Block timestamps cannot exceed their observation evidence, and the
credited transaction's block timestamp must be inside the scoped activity
window. This chronology checks consistency of the supplied finality proof;
there is no caller boolean that substitutes for its missing raw responses.

## Join and duplicate rules

For an incentive row, the wallet, condition, transaction hash and timestamp must
match the requested scope. Its positive JSON amount must convert exactly to
native integer micro-units. The conversion is independent of ambient Decimal
precision; excessive precision is rejected instead of rounded.

In the same transaction receipt, a candidate transfer must:

1. Carry consistent transaction hash/index and block hash/number, a unique log
   index, and `removed=false`.
2. Be emitted by the exact pUSD proxy with the ERC-20 Transfer signature and
   correctly padded indexed addresses.
3. Credit the scoped wallet from a different address with exactly the activity
   amount. A zero or self-transfer does not qualify.

There must be exactly one matching transfer. Distinct activity labels cannot
claim the same credit, and equal matching logs are ambiguous. A multi-condition
or aggregate transfer is never split. No nearest timestamp or closest amount
fallback exists. All candidate joins are withheld if any candidate is unresolved.

Repeated semantically identical activity rows count once while retaining their
capture references. Identical repeated RPC results from the same source/request
also count once. A conflicting repeated result is unresolved, even if one copy
would pass. Different request IDs and byte formatting do not create extra cash.
Output credit IDs bind chain, transaction hash and log index; activity IDs are
explicitly derived hashes rather than venue-issued identifiers.

## Output limits

| Status | Meaning |
| --- | --- |
| `JOINED` | Every supplied incentive candidate has one unambiguous credit supported by the supplied receipt/block proof. |
| `EMPTY_SUBSET` | No incentive candidate was supplied. Amount totals remain unknown, not zero. |
| `UNRESOLVED` | A required semantic link, finality proof or unique allocation is missing/conflicting. Credits and totals are withheld. |
| `INVALID` | Shape, hash, scope, encoding, amount or other evidence validation failed. Credits and totals are withheld. |

`matched_transfer_total` and its integer micro-unit counterpart sum only joined
gross transfers. They are not net account earnings, actual fees, profit, or a
complete paid-programme total. Provenance retains both activity and RPC capture
hashes, structured request hashes, source labels and observation times.

Activity has an activity timestamp but no earned-period link; dated earnings and
rebates lack a shared payment identity. Matching equal amounts or assuming the
previous day cannot fill this gap. Every result therefore keeps
`accrual_linkage_verified=false`, `account_cash_completeness_verified=false`,
`economic_pnl_verified=false`, `network_reads_performed=false` and
`live_authority=false`. It contains no fabricated accrual or distribution record.

[Owner fixtures](../../tests/market/test_mm_paid_credit_activity.py) cover exact
joins, native precision, duplicate idempotence, conflicting evidence, invalid
scope, missing finality, ambiguous logs, aggregate payments and these limits.

## Update when

Update this contract when supported source fields, request scopes, native-asset
identity, confirmation rules, duplicate handling, input/output shape or evidence
limits change. Add a separately reviewed capture path before claiming locally
observed endpoints, and real authoritative accrual linkage before producing
paid-accrual attribution.
