# International Market-Making Live Pilot

Status: canonical runbook. This runbook records the operator's 2026-08-13
authorization to work toward a bounded International Polymarket live test. It
does not make a blocked gate pass and it never authorizes Polymarket US.

## Purpose and claim boundary

The first live session is an exchange-lifecycle probe, not a profitability
proof. It tests whether the production path can place only resting liquidity,
observe the authenticated order lifecycle, stop safely, and reconcile account
state. Profitability requires repeated maker fills and subsequent paid-rebate,
markout, position, and settlement reconciliation.
The claim boundary and frozen economics decision rule are preregistered in
[`INTERNATIONAL_MM_PILOT_PREREGISTRATION.md`](../research/INTERNATIONAL_MM_PILOT_PREREGISTRATION.md).

Use International Polymarket only (`polymarket_global`). The live pilot must
reject every other platform identifier.

The current native trading and rebate settlement unit is `pUSD`. Stage 0,
Stage 1, and full platform verification must all bind that exact unit. Legacy
schema fields ending in `_usdc` remain compatibility names for one-dollar
amounts; they do not authorize reading a USDC.e balance as the trading
collateral balance or treating an unwrapped asset as pUSD.

Physical eligibility is separate from using the International platform.
Polymarket's official [geographic-restrictions API](https://docs.polymarket.com/api-reference/geoblock)
must return `blocked=false` for the public IP that will submit the order. The
operator must also confirm that the response matches the host's real physical
location and that no VPN, proxy, relay, or other geoblock circumvention is in
use. Viewing and public capture may continue from a blocked host; order
mutation may not. On 2026-08-13 the production host returned `blocked=true`,
`country=CA`, `region=ON`, so this host is preparation/read-only only. Never
move submission unless the new host is genuinely and lawfully physically
eligible.

## Immutable pilot envelope

- Dedicated isolated wallet funded with no more than **100 pUSD**
  of the exchange-supported settlement collateral verified during preflight.
- Requested run budget no more than the wallet cap and no more than **100**.
- Exactly one weather market per run.
- Existing ceilings may be lowered but not raised: **25** daily loss, **25**
  event notional, **10** band notional, and **120 seconds** quote TTL.
- Smallest current exchange-valid share size and current tick size, read from
  the selected book immediately before the order.
- Post-only limit orders only. No marketable retry after a post-only rejection.
- No naked sell. A sell requires verified owned outcome inventory; otherwise
  express the complementary side with a backed buy.
- No overnight or unattended first session. End with cancel-all plus an
  authenticated query proving zero open orders.
- No order from a location blocked by the official geoblock endpoint. Fetch a
  new response before constructing the authenticated client, before issuing
  the one-submit Stage 1 capability, and immediately before submit. Evidence
  expires after five minutes, retains country/region and content hashes, and
  deliberately discards the detected IP.
- Do not assume liquidity rewards. Model the current documented maker rebate
  only after market-level fee eligibility is verified. Treat an unpaid or
  sub-threshold estimate as unrealized.

## Prerequisites

All must be current for the target date and selected market:

1. Continuous execution capture is running and has produced rows. This remains
   ahead of the paper harvest lane in the approved sequence.
2. The International economics snapshot passes and matches the live platform.
3. Before the first lifecycle order, `mm_platform_bootstrap_v0.1` passes for
   the exact token and condition. This read-only, at-most-one-hour-old artifact
   proves a fresh official physical geoblock response, explicit real-location
   match and no-circumvention confirmations, the isolated wallet identity,
   recorded cap, numeric collateral
   balance and allowance each backing the requested budget, a content-bound
   account snapshot, an observed zero open-order count, current
   book/min size/tick/neg-risk, market fee
   eligibility, a non-posting signed-order preview bound to the exact signer,
   funder, signature type, and token (raw signature discarded), account-wide
   user stream, rotating heartbeat chain,
   cancel-all-to-zero, SDK contract, and secret hygiene. It cannot authorize a
   general maker run.
4. Credential references are present outside the repository. The API key,
   API secret, passphrase, and private key must all enter by storage reference;
   their values are forbidden in environment variables, command lines, logs,
   config, or artifacts. The public funder address may be supplied directly.
   On this Windows host the only prepared resolver is `wincred://`, backed by
   the current user's Windows Credential Manager generic credentials. Provision
   entries through the interactive Credential Manager UI; never put a secret in
   `cmdkey /pass`, PowerShell history, a scheduled-task argument, or a reference
   URI. The loader does not print target names or resolved values.
5. The official International CLOB client `py-clob-client-v2==1.1.0` is
   installed from the `live` dependency extra and wrapped by a tested adapter.
   Its pinned client owns post-only placement, CLOB account reads,
   cancellation, and dead-man heartbeats. The existing hand-built request-plan
   adapter remains diagnostic and cannot authorize capital.
   Placement stays disabled until authoritative user-event and position readers
   are present and explicitly verified, the rotating heartbeat ID has been
   acknowledged within 7.5 seconds, and a matching book/min-size/tick/neg-risk
   snapshot has been read within 10 seconds.
6. Current live-readiness, data-layer, fleet, risk, release, and explicit
   confirmation gates all pass without overrides or exceptions.
7. A simultaneous one-market paper counterfactual has quote permission and is
   writing auditable artifacts. Zero quote-permission rows means no live test.
8. The session is outside the host's protected 12:00-18:00 local capture window.
9. The submitting host is physically eligible. The production Ontario host is
   currently blocked and cannot satisfy this prerequisite.

## Staged protocol

### Stage 0: read-only account proof

- Fill the public `mm_stage0_client_identity_v0.1` manifest. It binds only the
  International host, chain, pinned SDK, public wallet topology, fresh
  IP-redacted official geoblock response, physical-location/no-circumvention
  confirmations,
  isolated-wallet declaration, and capital cap. It exists to construct the
  authenticated client needed to collect Stage 0; it is not evidence that any
  account check passed and cannot authorize an order.
- Authenticate and subscribe to the entire user account stream.
- Require the reader thread to remain active. A historical PONG from a stopped
  or failed reader is not liveness, and ordinary account events do not satisfy
  the independent server-PONG deadline.
- Query balance, allowance, positions, and open orders.
- Require no unknown open orders. If any exist, stop and reconcile them.
- Require an exact-condition position query and zero starting outcome inventory.
- Read the chosen book, market fee eligibility, min order size, tick size, and
  closed-only state immediately before mutation.

### Stage 1: dead-man and cancel proof

- Start the exchange heartbeat and require acknowledged 5-second cadence.
- Start the first heartbeat with an empty ID, then pass the returned
  `heartbeat_id` into every subsequent request. A missing ID, broken chain, or
  response older than 7.5 seconds disarms placement.
- Submit one far-from-mid, smallest-valid, post-only buy with notional no more
  than the band cap.
- Require both the placement response and authenticated stream/open-order
  observation.
- Treat every scoped trade lifecycle state, including `MATCHED`, `MINED`, and
  `RETRYING`, as an unexpected Stage 1 outcome. Send cancel-all, reconcile, and
  stop; zero positions from a potentially lagging account API is not sufficient
  no-fill evidence.
- Continue the rotating heartbeat at no more than five-second intervals during
  placement and observation. Before either cancellation proof, acknowledge one
  fresh heartbeat and prove the order is still open. Otherwise a slow
  observation could let the dead-man timer cancel the order and falsely credit
  cancel-all.
- The immediate response must be successful, carry an order ID, report `live`,
  and carry no trade IDs or transaction hashes. Any other response is an
  ambiguous or taker-like outcome: send cancel-all, reconcile, and stop.
- Intentionally stop heartbeats once from that fresh acknowledgment, observe
  automatic cancellation no earlier than the documented ten-second timeout and
  within the timeout-plus-five-second cancellation-check window, then query
  until the order is absent. If this is not proven, stop the pilot.
- Repeat with one order, invoke cancel-all, and require zero open orders.

This stage is a successful live test even if no fill occurs.

After both distinct probes pass, construct
`mm_stage1_lifecycle_bundle_v0.1` with
`weather.market.mm_live_lifecycle_probe.build_stage1_lifecycle_bundle`. The
builder rereads both append-only journals, verifies their hashes and critical
events, requires distinct journal files and order IDs, and derives the no-fill,
cancel-all, and heartbeat-lapse facts. Do not hand-author those facts. The
tracked bundle template is deliberately fail-safe.

Stage 1 is the only order mutation allowed from the bootstrap artifact. Its
completed, content-bound lifecycle bundle upgrades platform proof to
`mm_platform_verification_v0.4`. The ordinary `market_making_run` live-pilot
path continues to require that stronger artifact and must never accept the
bootstrap artifact. Version v0.4 embeds the bundle and its SHA-256, rechecks
the two probe identities and budgets, and requires its flattened private-stream,
cancel-all, and heartbeat claims to match the bundle's derived facts. The
prepared `weather.market.mm_live_lifecycle_probe`
orchestrator is deliberately not exposed as a CLI until credential-by-reference
loading and an exact SDK/wallet topology pass their keyless contract tests. It
requires the literal confirmation
`INTERNATIONAL_POLYMARKET_STAGE1_LIFECYCLE_PROBE`, a passing bootstrap bound to
the exact adapter funder, condition, token, and SDK, zero starting orders, and
one cancellation mode per run. Every starting, ending, and failure-cleanup
position check must carry the exact maker/condition request URL, HTTP status,
and response hash; an unbound empty list is not zero-position evidence.
The upgraded proof may satisfy the private-stream lifecycle requirement with a
verified no-fill path: REST zero starting orders, authenticated placement and
cancellation events, absence of every scoped trade lifecycle event, zero ending
orders, and zero exact-scope positions. It
must not invent an initial WebSocket order snapshot, which the protocol does
not document, and it does not claim that a fill path has been tested. Actual
fill, settlement, fee, and payout evidence remains a Stage 3 requirement.
The official adapter fetches a new official geoblock response before issuing
an in-memory opaque capability and requires country/region to match Stage 0.
It fetches again immediately before submit. The capability permits exactly one
network submit and is consumed before that final check and the SDK call, so
Stage 0, the ordinary runner, or a retry after
an ambiguous response cannot call the adapter's order method directly.
It also requires a new, non-existing journal path. Before placement it writes
and flushes the authorization, bootstrap hash, exact intent, and budget; after
placement it appends exchange observation, cancellation, zero-open-order, and
terminal-stream events. Success also requires zero ending positions. A failed
phase records separate zero-open-order and zero-position cleanup verdicts plus
only its exception type, never raw SDK exception text or credentials. The returned
result binds the completed journal SHA-256. A missing, unwritable, reused, or
later modified journal prevents bundle construction.
`weather.market.mm_credentials` prepares the reference resolver and pinned
client factory. The factory accepts only the narrow public Stage 0 identity
manifest; requiring the later observed bootstrap here would create an
impossible dependency cycle. The returned raw SDK client is still not order
authorization: only `weather.market.mm_live_lifecycle_probe`, with a passing
observed bootstrap and its separate literal confirmation, may perform Stage 1.
No credential entries were read or created by this change.

`weather.market.mm_live_bootstrap.collect_platform_bootstrap_payload` is the
prepared Stage 0 evidence collector. It converts the CLOB's integer atomic
collateral balance and allowances to six-decimal settlement units, rejects a
balance above the isolated-wallet cap, validates a public Data API position
query scoped to the exact proxy wallet and condition, content-binds that query
and the full account snapshot, locally constructs and hashes a signed minimum
BUY without posting it, discards the raw signature, requires a live user-stream
PONG, exercises two
rotating five-second heartbeat acknowledgements, and sends cancel-all followed
by a zero-order query. The WebSocket does not document an initial account
snapshot, so the gate does not invent one: REST establishes the starting state,
PONG establishes transport liveness, and the first Stage 1 order event proves
the authenticated event path.

### Stage 2: one-band maker quote

- Require a current passing `mm_platform_verification_v0.4`, including fresh
  official physical geoblock eligibility and the
  Stage 1 automatic heartbeat-lapse cancellation and cancel-all-to-zero proof.
  The full gate repeats the numeric balance, allowance, actual-wallet-cap,
  zero-open-order-count, and account-snapshot-hash checks; Stage 0 booleans are
  not carried forward as financial proof.
- Select one central band whose current market spread, depth, fee eligibility,
  source freshness, book freshness, watcher freshness, and current-high trust
  gates pass.
- Place one or two smallest-valid backed post-only orders for one TTL only.
- A post-only cross rejection is a stop-and-refresh event, never permission to
  chase price.
- Cancel at TTL, stale evidence, user-stream silence, heartbeat failure,
  reconciliation mismatch, unexpected fill state, risk limit, or operator stop.

### Stage 3: evidence and settlement

For every accepted order, retain intent, signed-request hash (never the secret
or raw private key), exchange order ID, stream events, REST reconciliation,
fill/trade IDs, transaction hashes when available, balances, positions,
markouts, fees, rebate estimate, paid rebate, redemption, and final settlement
P&L. Reconcile the paid rebate after the daily cycle; the program's current
minimum payout threshold means one tiny session may produce no payment.

Normalize the official account stream fail-closed. An order cancellation is
`event_type=order`, `type=CANCELLATION`; do not inspect only the first field.
Order and taker events require the exact top-level pilot maker. For maker-side
trades, bind the pilot maker address to its `maker_orders` row; the top-level
`maker_address` can describe the counterparty and must not reject our fill.
Retain `trader_side`. `MATCHED`, `MINED`, and `RETRYING` are pending lifecycle
evidence, not fills for final accounting. Only `CONFIRMED` creates a settled
fill row; `FAILED` creates no fill. Any taker role, out-of-scope token/condition,
unknown status, or maker row that cannot be attributed to the pilot order is a
stop condition.

Position and rebate reconciliation use content-bound official responses. Zero
positions require `GET https://data-api.polymarket.com/positions` with the exact
`user`, `market`, `sizeThreshold=0`, `limit=500`, and `offset=0` scope plus a
recorded response hash. Pagination parameters are part of the proof; an
unbounded or partially inspected result is not an exact zero.
Rebate evidence likewise requires the exact public `/rebates/current` request,
HTTP success, and a response hash; a caller-supplied list is not endpoint proof.

`weather.market.mm_user_stream.OfficialUserStreamReader` is the prepared
account-wide transport boundary. It accepts the already-resolved API values in
memory, journals only an explicit normalized-field allowlist plus a SHA-256 of
the raw server event, and has no CLI or
automatic startup. A transport disconnect, unknown event, malformed JSON, or
out-of-scope maker/token/condition ends the session without reconnecting. PONG
is transport-heartbeat evidence, not an order event; missing inbound server
PONGs fail on their own deadline even if other account events continue to
arrive, and a stopped reader cannot satisfy Stage 0. The caller
must cancel all and reconcile to zero before any new session; silent reconnect
during an outstanding order is forbidden.

Use the public official `GET /rebates/current?date=...&maker_address=...`
response for the completed next payout cycle. Count only rows matching the
pilot's exact date, maker address, and condition ID; sum `rebated_fees_usdc`.
Current reward-campaign metadata is eligibility evidence, not payout evidence.
A completed exact-scope query with no matching row is a reconciled zero, not a
missing value. Before the payout cycle is complete, even a positive current
row remains provisional. Record the query timestamp and query a UTC day only on
a later UTC date; a same-day `/rebates/current` response cannot be labeled a
completed payout cycle. The subsequent wallet cash identity still decides
whether an accrued amount was actually paid, including the `$1` minimum.

The current weather curve implies a useful scale check for the `$1` payout
minimum. At `p=0.50`, the documented `0.05` fee curve and `25%` rebate produce
`$0.003125` per filled share, so roughly `$160` of maker fill notional is needed
to accrue `$1`. At `p=0.10` the corresponding notional is about `$88.89`; at
`p=0.90` it is `$800`. The `$100` pilot envelope is a capital cap, not a claim
that one fill or one session can prove rebate profitability. Turnover and
price mix determine whether the payout threshold is reachable.

Do not call total P&L reconciled merely because settlement, fees, and a rebate
field are present. Require starting and ending balances, zero ending
positions, explicit external cash flows, a settlement-P&L basis that excludes
fees and incentives, and equality of the cash-flow identity to `0.00001`
pUSD. Otherwise the report remains incomplete; it must not infer profit by
adding fields whose accounting bases may overlap.

An empty positions list proves zero only when it is the result of an observed
query explicitly scoped to the exact maker and condition. A configured market
fee rate is not an actual fee measurement. Actual fee evidence must cover every
pilot trade and exit, including any taker or flattening fee, and its maker and
condition scope must equal the position and rebate scopes. A lone current
balance must never be reused as both the starting and ending balance.
The fee amount must be derived from the complete confirmed-trade event set and
bind that set with a SHA-256; a configured rate or an unbound manually entered
amount is not actual fee evidence. Bind each confirmed fill's trade/order IDs,
transaction hash, maker, condition, token, liquidity role, price, size, and fee
rate. Makers pay zero. For every taker or flattening fill, independently compute
`shares * (fee_rate_bps / 10000) * price * (1 - price)` and round to five pUSD
decimal places before summing. The reported amount and content hash must match
that calculation exactly.

`MATCHED` is not settlement. Follow every trade through the authenticated
stream and REST reads until `CONFIRMED` or `FAILED`; a placement response may
return trade IDs before transaction hashes exist. Do not book inventory, fees,
or P&L from an intermediate exchange status alone.

## SDK decision record

The 2026-08-13 adapter audit checked the official CLOB v2 client at tag
`v1.1.0` against the official order and heartbeat documentation. That client
uses `/v1/heartbeats`, accepts `OrderType.GTC` with `post_only=True`, returns a
rotating `heartbeat_id`, and can return trade IDs before settlement hashes.
Its convenience `create_and_post_order` helper owns an internal two-attempt
order-version retry, so the pilot deliberately does not call it. The adapter
calls local `create_order` followed by exactly one network `post_order`; an
order-version rejection is a stop-and-reconcile event, not a retry.
The generic API reference still prints `/heartbeats`; the pinned client's tag
is the contract for this adapter, and the discrepancy must be rechecked before
the first live session.

Polymarket now recommends its unified `polymarket-client` SDK for new projects.
The current unified client has a stronger typed order/user-stream surface, but
the audited public secure-client surface did not expose the maker dead-man
heartbeat required by this pilot. Do not migrate merely because it is newer.
Re-evaluate the unified client immediately before credentialed integration; use
it only if the exact version proves post-only placement, rotating REST
heartbeats, account-wide user events, cancel-all-to-zero, and asynchronous fill
settlement in a keyless contract test.

The isolated wallet model is also unproven. Before funding it, Stage 0 must show
that the exact signer, funder/deposit-wallet, signature type, and API-key owner
are mutually consistent. A balance read is not sufficient: the same identity
must pass authenticated user-stream subscription, heartbeat, a signed-order
preview or non-posting contract probe, and cancel-all. Do not rely on a manual
UI-trade workaround or silently switch wallet/signature models after a failure.

Official references reviewed on 2026-08-13:

- <https://github.com/Polymarket/py-clob-client-v2/tree/v1.1.0>
- <https://github.com/Polymarket/agent-skills/blob/main/order-patterns.md>
- <https://github.com/Polymarket/py-sdk>
- <https://docs.polymarket.com/programs/maker-rebates>
- <https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker>

## Stop conditions

Cancel all and do not resume on any of the following:

- book, source, watcher, execution-capture, user-stream, or heartbeat stale;
- market fee eligibility, min size, tick, wallet, allowance, or platform drift;
- any order is accepted as taker or without post-only protection;
- open orders, positions, reserves, or local lifecycle disagree with exchange
  truth;
- unknown order, unexpected partial fill, unbacked sell, or risk-cap breach;
- cancel-all is not followed by zero open orders;
- host enters the protected capture window or capture health degrades.

## Decision after the pilot

- **Plumbing pass:** all lifecycle and shutdown proofs complete, even with no
  fill. Proceed to repeated bounded maker sessions.
- **Economics pass:** repeated maker fills show spread plus paid rebates exceeds
  adverse-selection markouts, inventory/settlement loss, and all costs under the
  simultaneous counterfactual. Only then consider more time or markets; capital
  remains capped until a new dated operator decision.
- **Fail:** any safety/reconciliation defect, taker execution, unexplained cash
  delta, or incomplete evidence. Fix and repeat Stage 1; do not explain it away
  as a small sample.

## Update when

Update when the approved capital envelope, platform, official SDK integration,
live gates, risk ceilings, probe sequence, or stop conditions change.
