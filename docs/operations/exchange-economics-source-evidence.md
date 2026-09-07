# Exchange economics source evidence

Status: canonical public-source contract. The interface matrix was checked
against official documentation on 2026-09-07; recheck it before qualification.

[`weather.market.exchange_economics`](../../src/weather/market/exchange_economics.py)
owns the existing public collection and snapshot publication path.
[`exchange_economics_sources`](../../src/weather/market/exchange_economics_sources.py)
owns its bounded response parsing and current-reward page validation. This
contract supplies source evidence for the [pure feasibility calculator](maker-incentive-feasibility.md);
it establishes neither a qualifying opportunity nor account earnings.

## Current reward collection

The [official current rewards interface](https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations)
groups configurations by condition, with required `data`, `count`, `limit`
and `next_cursor` fields. Its terminal cursor is `LTE=`. Standard and
sponsored-only results are separate request scopes; this collector retains
the standard default scope and does not claim a sponsored-only census.

Before projecting any selected condition, collection requires:

- Object pages, an object-list `data`, integer counts/limits with count equal
  to row count and within the requested limit, and a nonempty cursor.
- A terminal cursor for an empty page. Missing/null data, an error envelope,
  an empty nonterminal page, repeated cursors and exhausted page budgets fail.
- Complete condition identity and finite nonnegative numeric economics.
  Allocation rows require identity, explicit asset, calendar dates and amounts.
  Repeated conditions, including identical or differently cased duplicates
  across pages, and repeated allocation identity within a condition fail.
- All pages to pass before normalization or publication. A refusal leaves the
  previously published snapshot intact; it cannot turn partial coverage into
  a zero-campaign observation.

A complete terminal empty result is valid evidence of no rows in that request
scope. It is not a paid-incentive zero, historical absence or account census.
API dates remain calendar strings: this parser does not invent timezone,
half-open interval or payout-finality semantics. Unknown asset addresses remain
explicit source values, never aliases for native pUSD.

## Replayable response bytes and compatibility

Each newly collected Gamma JSON response, rewards page and rule document retains
its original bytes as `response_body_base64`, plus `retrieved_at_utc`,
`response_origin`, `request_method`, exact URL, HTTP status, content type, byte
count and SHA-256. Retrieval time is observed for each completed response.
Decoding base64 recovers whitespace, BOM and decimal spelling; JSON rejects
duplicate keys, invalid UTF-8, nonfinite numbers and floating overflow.

The default HTTP reader records `response_origin=http_response_bytes`.
Injected parsed payloads are serialized and labelled
`caller_supplied_canonical_json`; injected text is `caller_supplied_text`.
Those labels do not authenticate a caller's request assertions. When an
injected parsed result also supplies raw evidence, the parser verifies agreement.
No credential or authentication header belongs in this public evidence.

The code bounds each raw body to 2 MiB and one successful snapshot's retained
raw bodies to 16 MiB. Rewards pagination allows at most 50 pages and 500 rows
per page. These are refusal budgets, not claims about normal venue volume;
a refused normal response needs measured review before increasing them.
Base64 and JSON make persisted files larger than the raw-body budget.

New raw fields are additive within `source_verification`. They bind
`source_proof_hash` but remain outside the material economics hash and drift
comparison. Existing captured snapshots and hash-only response records remain
readable; they are not upgraded to replayable evidence. Historical consumers
must retain their original run-bound snapshot rather than recollecting today.
If any new raw field is present, the complete byte/hash/time/origin/request
record must validate; recomputing the outer source hash cannot repair bad bytes.

Raw persistence enables later source replay and scrutiny. This change does not
add a full projection-rebuild command, prove a historical request authentic, or
bind a current reward rate to a realized receivable. The existing source gate
and exact event, book, adjusted-midpoint, capital and campaign checks still apply.

## Official interface-to-field matrix

“Feasible” below means the documented fields can support the named bounded
capture after its reader is qualified. It does not mean an account was queried,
a payout was observed or the pinned SDK exposes replayable wire bytes.

| Required evidence | Official interface and available fields | Bounded disposition / missing link |
| --- | --- | --- |
| Exact campaign | [Current rewards](https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations): public `GET /rewards/markets/current`; condition, allocation ID, asset, dates, rates and score cutoffs | Public capture is implemented above. Keep exact asset and scope. Qualifying interval semantics, books and competitor scenarios remain separate inputs. |
| Liquidity earnings by date | [User earnings](https://docs.polymarket.com/api-reference/rewards/get-earnings-for-user-by-date): L2-authenticated `GET /rewards/user`; date, condition, maker, asset, earnings and asset rate; cursor pages | Feasible accrual snapshots after auth/raw-reader qualification. No documented shared distribution, transaction or transfer-log identity. A past date alone does not prove finality or earned-period payment. |
| Maker rebate accrual | [Current rebates](https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker): public `GET /rebates/current` with maker/date; condition, maker, asset and `rebated_fees_usdc` | Existing adapter reads native-pUSD rows conservatively. The legacy amount name and USDC prose do not override the explicit contract address. No payout transaction/distribution link is documented. |
| Actual scoring | [Order scoring](https://docs.polymarket.com/api-reference/trade/get-order-scoring-status): L2-authenticated `GET /order-scoring?order_id=...`, returning `scoring` | Feasible timestamped observations after reader qualification; instantaneous eligibility does not prove all samples, epoch share, accrued amount or payment. |
| Own fills and exits | [Authenticated trades](https://docs.polymarket.com/api-reference/trade/get-trades): trade/order, condition/token, side, size, price, status, transaction, maker rows and `fee_rate_bps` | Reuse the existing official adapter and exact own-order matching. Retain raw status/units and pagination; a scalar fee rate is not a confirmed cash fee. Exit attribution and final cash require additional reconciliation. |
| Fee basis | [Market details](https://docs.polymarket.com/market-data/market-details) and [fees](https://docs.polymarket.com/trading/fees): per-market fee schedule; share/price fee formula and rounding | Current captured fee semantics support estimates. Bind each actual fill/exit to its role, contemporaneous schedule, fee asset and confirmed cash effect before reporting actual fees. Do not substitute the old scalar `/fee-rate` value for a cash coefficient. |
| Labelled paid transfer | [User activity](https://docs.polymarket.com/api-reference/core/get-user-activity): public `GET /activity`; wallet, condition, timestamp, type, transaction hash and amount | Existing [activity bridge](paid-credit-activity-evidence.md) can join supplied REWARD/MAKER_REBATE rows to unique finalized native-pUSD transfers. It proves a labelled gross credit only; no earned-period/programme accrual link or complete account cash. |
| Inventory and redemption | [Current positions](https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user): wallet/condition/token, size and position metrics; activity includes redemption/conversion | Existing scoped position reader is useful for current inventory. Request zero size threshold when proving tiny residuals absent; preserve pages and before/after cash. Position metrics or a redemption label alone do not close realized cohort accounting. |
| External flows and total cash | [Activity](https://docs.polymarket.com/api-reference/core/get-user-activity) supports deposits/withdrawals when `excludeDepositsWithdrawals=false`; limit at most 500, offset at most 5000, bounded start/end windows | Feasible bounded samples. Offset exhaustion, page emptiness or supplied subsets do not prove complete history. A future collector must resolve ordering/window boundaries and duplicate coverage; the pure bridge intentionally makes no completeness claim. |
| Accounting export | [Accounting snapshot](https://docs.polymarket.com/api-reference/misc/download-an-accounting-snapshot-zip-of-csvs): public `GET /v1/accounting/snapshot?user=...` returns positions and equity CSVs in a ZIP | Useful documented snapshot candidate; not a documented flow ledger, programme-period payment link or replacement for transfer/fill evidence. No new ZIP capture is implemented from its name alone. |
| Operating costs | No documented venue endpoint above identifies attributable compute, paid infrastructure or operator time | Supply an explicit external cost record and attribution rule; keep cash costs and disclosed time separate. Do not infer zero from missing records. |

Explicit [native-pUSD contract identity](https://docs.polymarket.com/resources/contracts)
and the existing [activity bridge's chain/finality checks](paid-credit-activity-evidence.md#source-meaning)
own payment asset and transfer proof. Preserve an unsupported reward asset as an
unsupported asset; do not relabel it using the programme's usual payment asset.

The one-day interface result is therefore **feasible for bounded raw campaign,
accrual, scoring and labelled-credit evidence; unresolved for authoritative
accrual-to-payment linkage and complete cohort cash**. That conclusion follows
from the documented field gaps above, not an observed account failure.
The existing offline accrual matcher still requires real accrual, distribution
and unique confirmed-credit linkage. Neither matching equal amounts nor
assuming “yesterday” supplies the missing venue relationship.

The next accounting slice should qualify the exact official SDK/wire response
capture without retaining secrets, obtain authoritative period/distribution
semantics, and prove coverage and cash attribution on a bounded supplied
cohort. Until then, report unpaid accrual and unattributed gross credits
separately and do not feed fabricated distributions into the matcher.

## Verification and updates

Owner fixtures are
[`test_exchange_economics_sources.py`](../../tests/market/test_exchange_economics_sources.py)
and [the collector tests](../../tests/market/test_exchange_economics.py).
Use the owning host's required workload admission for them, the existing
feasibility/accounting tests, import ratchet and canonical documentation audit.

Update this contract with parsing/pagination limits, raw evidence shape,
compatibility changes, supported official interfaces or a demonstrated
attribution/coverage link. Work status belongs to the numbered roadmap owner.
