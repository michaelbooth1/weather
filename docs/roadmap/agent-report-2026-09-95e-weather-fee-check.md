# 95e — Weather fee check, Q-15

**YES: weather platform taker fees apply. All 418 active bands across the
12 configured daily-high families and Taipei had the 0.05, exponent-1 fee
schedule; platform maker fees are zero. Actual taker charges are demonstrated
on every September 20–24 UTC date for every family.** Optional builder fees
are additional and can apply to makers as well as takers.

Historical workstation evidence for [Q-15](../operations/OPEN_QUESTIONS.md),
requested September 24, 2026. This report answers the question; accepting and
updating the canonical findings belongs to the production agent under the
[delegation contract](../operations/DELEGATION_CONTRACT.md). No live authority.

## What rate, and since when?

The platform weather charge is `shares × 0.05 × p × (1 − p)` pUSD, where `p`
is the traded token's price. The coefficient is **not a flat 5% of notional**.
At 0.50, 100 shares incur 1.25 pUSD, or 2.5% of their 50-pUSD notional.
The published weather maker fee is zero. [Official fee schedule](https://docs.polymarket.com/trading/fees).

The venue dates weather's fee-category introduction to **March 30, 2026**.
Its March 31 update directs calculations to `feeSchedule`; CLOB V2 went live
April 28 with match-time fees. The observed changelog contains no new weather
fee activation on September 20–24. This is the documented category timeline,
not proof of the first charged fill on every individual condition.
[Official changelog](https://docs.polymarket.com/changelog/predictions).

Direct dated evidence here establishes charging **by September 20 at
00:10:09 UTC**, the earliest selected on-chain transaction. Current Gamma
metadata on closed markets cannot establish when their fees were enabled.
This bounded check does not recover the exact first-ever weather fee or
every condition's historical schedule.

## Current market census

The discovery retained 103 event bodies and 1,133 bands, including recently
closed events. Of these, 38 events / 418 bands were active and unclosed with
`acceptingOrders=true`. The fee reads span **September 24, 23:46:51–23:56:48
UTC**; this is a sequential snapshot, not an atomic book observation.

| Family | Active events | Active bands / YES fee-rate reads | Trade rows since Sep 20 | On-chain transactions |
| --- | ---: | ---: | ---: | ---: |
| Atlanta | 3 | 33 | 722 | 5 |
| Austin | 3 | 33 | 676 | 5 |
| Chicago | 3 | 33 | 776 | 5 |
| Dallas | 3 | 33 | 769 | 5 |
| Denver | 3 | 33 | 766 | 5 |
| Houston | 3 | 33 | 644 | 5 |
| Los Angeles | 3 | 33 | 799 | 5 |
| Miami | 3 | 33 | 738 | 5 |
| NYC | 3 | 33 | 697 | 5 |
| San Francisco | 3 | 33 | 744 | 5 |
| Seattle | 3 | 33 | 800 | 5 |
| Taipei | 2 | 22 | 700 | 5 |
| Toronto | 3 | 33 | 654 | 5 |
| **Total** | **38** | **418** | **9,485** | **65** |

Every active band, and all 1,133 retained Gamma bands, returned the same fields:

```json
{
  "feesEnabled": true,
  "feeType": "weather_fees",
  "makerBaseFee": 1000,
  "takerBaseFee": 1000,
  "feeSchedule": {
    "rate": 0.05,
    "exponent": 1,
    "takerOnly": true,
    "rebateRate": 0.25
  }
}
```

All 418 YES-token CLOB `/fee-rate` responses were HTTP 200 with
`{"base_fee":1000}`. One NO-token control and one CLOB `/markets/{condition}`
control per family agreed: 13 NO results were 1000; all 13 market controls
reported both base-fee fields as 1000. These raw base fields do **not** prove
a 10% actual maker charge or a flat 10% taker charge. The documented
`feeSchedule` and actual match receipts determine this report's conclusion.
[Field semantics](https://docs.polymarket.com/market-data/market-details).
Exact conditions, token IDs, event slugs, request times and response hashes
are in [fee_fields.json](weather-fee-check-20260924/fee_fields.json).

## Public trades omit fee fields; they do not demonstrate zero fees

The check read one recent 100-row v2 taker page per event, then filtered actual
timestamps locally to September 20 00:00 UTC onward. The retained 9,485 rows
span September 20 00:00:04 through September 24 23:57:48 UTC and 650 conditions.
**None has a fee or rebate field.** Thirteen maker-inclusive v2 controls and
13 legacy v1 controls add 260 rows, also without fee fields.

The current public [v2 OpenAPI Trade schema](https://data-api.polymarket.com/v2/openapi.json)
likewise contains no fee/rebate property. Event queries ignore server-side
start/end bounds, so filtering was local; the API's default minimum trade
size also applies. **97 of 103 main pages have more rows available.** These
are bounded field-presence samples, not an exhaustive execution census.
Raw property names and any fee-like fields are preserved in
[trade_samples.json](weather-fee-check-20260924/trade_samples.json), with
[page receipts](weather-fee-check-20260924/trade_pages.json) and
[controls](weather-fee-check-20260924/trade_controls.json).

Consequently, the existing inference “zero fees on public trades, therefore
zero rebates” is unsafe as a statement about current weather economics.
This check did not access the old 377,104-row evidence or its original schema;
it cannot decide whether those historical zeros were explicit values or
missing fields coerced to zero. Preserve that old observation with its dates
and provenance; retire its extrapolation to today's fee and rebate policy.

## Dated charges from public transaction logs

To distinguish missing fields from actual charges, select the sampled trade
closest to 0.50 for each family × UTC trade date and read its public Polygon
transaction logs. This yields **65 distinct transactions, 61 conditions,
60 event slugs, 13 families × five dates**. All log pages were exhausted,
including the multi-page Chicago sweep. Official CTF Exchange V2 addresses
and pUSD were bound using the venue's [contract list](https://docs.polymarket.com/resources/contracts).

`OrderFilled.maker` names the order signer, not necessarily the liquidity
maker. Roles were identified by matching the order hash against
`OrdersMatched.takerOrderHash`. Token IDs were checked against the selected
public trade. Results:

- **65/65 taker orders paid positive fees; 180/180 matched maker fills paid zero.**
- Taker charges total **9.71270 pUSD, including any builder fees**. Each
  transaction's taker-fee sum equals its separate `FeeCharged` event sum.
- **61/65** taker charges equal the aggregate-price platform curve truncated
  to five decimals. The other four have nonzero builder codes, detailed below.
- Retained maker-leg curve sums are diagnostic only: a multi-price sweep
  differs from that sum while matching the aggregate taker-price calculation.
  Native Polygon gas transfers were excluded.

Two directly reviewable examples:

| UTC time | Family | Taker fill | Paid fee | Maker fee | Public receipt |
| --- | --- | --- | ---: | ---: | --- |
| Sep 20 00:10:09 | Denver | Sell 6.14 at 0.95 | 0.01458 | 0 | [Transaction](https://polygon.blockscout.com/tx/0x905f1dd1be283d11a8f3a53899ae0a0769d06ed45996e0091f9a30475243df58) |
| Sep 24 22:37:42 | Miami | 30 shares at 0.50 | 0.37500 | 0 | [Transaction](https://polygon.blockscout.com/tx/0x2464bd7a54e8d5a0911bdb41fa50ffc14752f45e80b5bae774a9192d13b853a0) |

The first curve evaluates to 0.01458250 before precision handling; the second
is exactly `30 × .05 × .5 × .5 = .375`. Full decoded exchange events,
collateral transfers, conditions and raw-unit fee values are retained in
[chain_fee_evidence.json](weather-fee-check-20260924/chain_fee_evidence.json).

This is descriptive support with crossed **UTC date × condition** clustering:
five date clusters, 61 condition clusters and 65 observed joint cells, also
covering all 13 family × five date cells. It is not an IID sample or an estimate
of population fee incidence. No confidence interval, bootstrap or edge test is
claimed; the joint cells share conditions/dates and are not independent.
Positive receipts establish existence and timing without such an inference.

## Optional builder charges

Builder charges are separate percentages of notional, added to the platform
fee. Documented defaults are zero; limits are 100 bps taker and 50 bps maker.
The signed builder code is included in `OrderFilled`. Thus “platform maker
fee zero” does not guarantee every routed maker order is free.
[Builder fee documentation](https://docs.polymarket.com/programs/builders/fees).

Four observed excess charges are compatible with the following added rates,
assuming each fee component is separately truncated to five decimals:

| Family / UTC date | Notional pUSD | Platform curve, unrounded | Total charge | Compatible builder rate |
| --- | ---: | ---: | ---: | --- |
| Atlanta / Sep 20 | 0.0069 | 0.00010695 | 0.00016 | 87–100 bps; tiny amount prevents unique inference |
| Austin / Sep 23 | 12.3756 | 0.0634664563 | 0.12533 | 50 bps |
| Denver / Sep 24 | 1.26 | 0.03150000 | 0.03780 | 50 bps |
| Taipei / Sep 20 | 5.7879 | 0.005498505 | 0.06336 | 100 bps |

Austin and Denver carry the same builder code. These are **inferred compatible
rates**, not fetched historical builder profiles. A nonzero code alone does
not prove a fee rate. The four transaction hashes, exact codes and compatible
integer-bps sets are in [builder_reconciliation.json](weather-fee-check-20260924/builder_reconciliation.json).
No sampled maker had a positive charge; the task did not inspect our account
or order routing to determine whether our own orders attach a builder code.

## Implication for reward economics

Gamma configures a **25% weather maker-rebate allocation**. The program uses
filled maker liquidity and fee-curve weights within each market, with daily
pUSD payments and a one-pUSD minimum. A configured share of collected fees is
not a guaranteed payment to us. [Maker rebate rules](https://docs.polymarket.com/programs/maker-rebates).

Liquidity rewards and fee-funded maker rebates are distinct possible revenue
streams. This evidence invalidates a blanket assumption that the latter must
be zero because weather takers pay nothing. Economics should account for
taker exits and any builder charges, alongside fill losses and separately
verified payments. This report proves no account payout, profitability,
forecast edge, or permission to change the RE-1 lane.

## Reproduction, boundaries and handback

Branch: **`codex/weather-fee-check-20260924`**. Evidence commit:
**`253f6f6bd1f91149421035a50636abf610a25f48`**.
The branch was created after fetching, from the user-named
`origin/codex/reward-test-attended-handoff-20260921` at
`35b7cf8ef684caa70c54269b2bbad5722c90c347`; it is a stack on that docs branch,
not a fresh master branch. Fetched master was
`198f7ccbcd8e80271693462425582097d22b298b`. The task adds only this report and
the linked evidence directory. Source, registries and canonical findings are
unchanged by this task.

The public client retained **655 HTTP-200 request receipts** across discovery,
fee queries, trade samples, schema probes and chain checks. Reads crossed into
September 25 UTC while still September 24 local. **Throttle deviation:** two
initial standalone CLOB probes started 0.255682 seconds apart at 23:46:51 UTC.
After correction, the main collection used persistent 1.05-second spacing
across invocations. This does not claim perfect compliance with the requested
one-request-per-second limit. The exact pair is disclosed in
[request_manifest.json](weather-fee-check-20260924/request_manifest.json);
web documentation-reader calls are outside that manifest.

No `.env`, credentials, authenticated/account endpoints, config or registry
edits, production/mirror evidence access, registration, capture restart,
live orders, production write, or merge occurred. Raw replies are held only
in this task's ignored cache; portable derived evidence and hashes are
committed. Public GET reads are explicit-allowlist, bounded and serial.

From an accepting checkout's repository root with its project interpreter:

```powershell
.\venv\Scripts\python.exe docs/roadmap/weather-fee-check-20260924/reproduce.py verify --offline
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ops/roll_verdict.ps1 -Branch codex/weather-fee-check-20260924 -Base origin/master
```

`verify` uses committed JSON and needs no raw cache or network. The evidence
[README](weather-fee-check-20260924/README.md) describes the collector and
limitations. Fresh `discover`, `fees`, `trades`, `chain` commands with a new
`--cache` re-observe later data; they cannot recreate this historical snapshot.
`chain --offline` rebuilds logs only when the original ignored cache is present.

Validation: portable evidence verification passed; roadmap lint/check passed;
the existing focused roadmap suite passed **12 tests** through
`scripts/ops/workstation_heavy.ps1`. Its explicit pytest temporary directory
was removed after checking the resolved task-local path; available disk was
152,683,778,048 bytes both before and after that test run. No full suite was
needed for additive evidence under `docs/`.

Per-file integration disposition: this report and **every file under
`docs/roadmap/weather-fee-check-20260924/` are additive `docs/` files**, hence
categorically roll-free under delegation §3. The required workstation tool
returned **UNDECIDABLE, exit 1**, because all four live closure evidence files
are absent; its [output is retained](weather-fee-check-20260924/roll-verdict.txt).
There is no closure-derived per-file verdict here. Production must rerun the
tool before integration; no production evidence was fetched to manufacture
one. Pushing this branch does not roll capture.

Acceptance recommendation: mark Q-15 answered for these observed families
and dates; amend the current zero-fee/zero-rebate extrapolation in EF §10a,
the findings digest and state of play. Keep historical raw observations
qualified and distinguish platform fees, builder charges and actual rebates.
