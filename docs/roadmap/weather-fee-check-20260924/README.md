# 95e public weather fee evidence

Historical evidence answering Q-15. Read the
[report](../agent-report-2026-09-95e-weather-fee-check.md) for conclusions,
coverage, timing and the distinction between fee configuration and charges.
No file here changes registry, capture, execution or account state.

Generator: `reproduce.py`, a bounded research script kept with its evidence,
not an importable production dependency. Reads use an explicit public GET
allowlist and no credentials, cookies or proxy configuration. Raw replies are
cached under ignored `data/research/weather-fee-check-20260924/`; that directory
is not part of a clean clone. Existing URL cache entries are immutable.

| File | Meaning |
| --- | --- |
| `fee_fields.json` | Exact Gamma fee fields for discovered bands; one YES-token CLOB fee-rate read per active band; NO-token and CLOB market controls for each family |
| `trade_pages.json` | Public Data API v2 event-query receipts, response hashes, retrieval times and pagination limits |
| `trade_samples.json` | Up to 100 recent taker rows per event, filtered locally to timestamps since September 20; raw field names and all fee/rebate fields retained, profiles omitted |
| `trade_controls.json` | Additional maker-inclusive v2 and legacy v1 trade-schema checks for each family |
| `chain_fee_evidence.json` | Public transaction-log checks selected near 0.5 per family/UTC date; token binding, exact exchange logs, collateral transfers and formula comparison |
| `builder_reconciliation.json` | Four excess-charge orders and compatible whole-bps builder rates; explicitly inferred, not historical profile reads |
| `summary.json` | Portable verification result and coverage by family |
| `request_manifest.json` | Public request timestamps/status/hash and spacing audit; no raw private/account data |
| `documentation_notes.json` | Primary-source URLs and concise interpretations, not historical paid-fee receipts |
| `SHA256SUMS.txt` | Retained evidence hashes, excluding the checksum file itself |

An absent fee field is **unknown**, not zero. `base_fee`, `maker_base_fee` and
`taker_base_fee` are retained exactly and are not substituted for Gamma's
documented `feeSchedule`. In that object, `rate` is a curve coefficient,
`exponent` is the price-component exponent, `takerOnly` identifies the charged
liquidity role, and `rebateRate` is a fraction of taker fees.

`active_band` requires active/unclosed event and market plus `acceptingOrders`;
it reflects the Gamma discovery snapshot, not a simultaneous guarantee through
the final network read. Historical Gamma fields were retrieved now and cannot
date a historical activation. Event scope is the twelve built-in daily-high
families plus Taipei; it does not include daily lows or other weather products.

Trade samples are for field presence and dated positive controls, not total
volume, population fee incidence or a complete execution census. A page with
`has_more=true` is intentionally not exhausted. Data API v2 ignores `start` and
`end` on event queries; the script filters actual epoch timestamps locally.
Its default minimum trade-size filter also remains applicable. Maker-inclusive
controls can contain both sides of one fill and must not be double-counted.

Chain evidence uses only the official Polygon CTF Exchange V2 and Neg Risk CTF
Exchange V2 addresses. An `OrderFilled` event's parameter named `maker` means
the order signer, which can be the taker in the matching transaction. The
script classifies that order by matching its `orderHash` to
`OrdersMatched.takerOrderHash`, not by the parameter name. It retains the
separate `FeeCharged` events and pUSD transfers as cross-checks. Amounts use
six-decimal raw units, also checked against the public trade's size and price.
Polygon native gas `LogFeeTransfer` is excluded from trading-fee totals.

The formula comparison uses the aggregate taker order price. Sixty-one charges
equal that curve truncated to five decimals. Four excess-charge orders carry
nonzero builder codes; the reconciliation tests additive notional fees under
separate five-decimal truncation. These compatible rates are inferences, not
verified historical builder profiles. Optional builder fees can also apply to
makers even though the platform's weather fee is taker-only.
The retained sum of maker-leg curves is a diagnostic, not a charging rule:
it differs materially on a multi-price sweep while the aggregate curve agrees.
`verify` rebuilds `summary.json` entirely from committed evidence, without
network or the raw cache. To re-observe later, choose a new `--cache` directory;
the study's fixed September 20 cutoff is explicit in `START`.
