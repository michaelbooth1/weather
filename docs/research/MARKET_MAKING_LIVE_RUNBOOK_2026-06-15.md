# Market-Making Live Readiness Protocol And Runbook

Status: operational design only. This document does not authorize live orders.
Live trading remains blocked unless items 43 and 44 pass, the live-readiness
file is true, the latest data-layer audit gate passes, and the current
platform-verification artifact passes.

Sources checked on 2026-06-15:

- Polymarket global trading overview:
  https://docs.polymarket.com/trading/overview
- Polymarket global order creation:
  https://docs.polymarket.com/trading/orders/create
- Polymarket global authentication:
  https://docs.polymarket.com/api-reference/authentication
- Polymarket global CLOB market info:
  https://docs.polymarket.com/api-reference/markets/get-clob-market-info
- Polymarket global order book:
  https://docs.polymarket.com/api-reference/market-data/get-order-book
- Polymarket global liquidity rewards:
  https://docs.polymarket.com/market-makers/liquidity-rewards
- Polymarket global changelog:
  https://docs.polymarket.com/changelog
- Polymarket US orders API overview:
  https://docs.polymarket.us/api-reference/orders/overview
- Platform verification gate design:
  docs/research/MARKET_MAKING_PLATFORM_VERIFICATION_2026-06-16.md

Relevant current facts from those docs:

- Global Polymarket CLOB trading is hybrid: offchain matching, onchain
  settlement, non-custodial order signing, and EIP-712 signed orders.
- Trading endpoints require CLOB authentication, and order creation still
  requires locally signed order payloads.
- Orders are limit orders; market orders are marketable limit orders.
- GTC/GTD rest; FOK/FAK execute immediately against resting liquidity.
- CLOB market info exposes tokens, tick size, minimum order size, fee fields,
  reward config, and taker-delay/Blockaid flags.
- Order book snapshots expose token ID, condition/market ID, hash/timestamp,
  bids, asks, and last trade metadata.
- Liquidity rewards depend on configured min incentive size and max spread;
  they are distributed daily, but live reward economics must be reconciled from
  actual account earnings and markouts before scaling.
- Polymarket global and Polymarket US documentation are distinct surfaces.
  The operating account, jurisdiction, API base URL, reward rules, and wallet
  semantics must be verified immediately before any live key is used.

## Required Gates

No live-pilot order may be attempted unless all of these are true:

- Items 43 and 44 have passed their acceptance gates.
- `python -m weather.market.market_making_run ... --mode live-pilot` preflight is `PASS`.
- `--pilot`, `--confirm-live-orders`, `--live-readiness`, and
  `--platform-verification` are supplied.
- The live-readiness JSON proves:
  `account_platform_verified`, `wallet_ready`, `allowance_ready`,
  `heartbeat_ready`, `user_websocket_ready`, and `cancel_all_ready`.
- The `data_layer_live_gate` proves the current target date has CLOB token IDs,
  condition IDs, CLOB feature rows, and book-available rows in the latest
  data-layer audit.
- The `platform_verification_gate` proves the current target date has fresh
  platform/account eligibility, jurisdiction, wallet/signature/funder,
  allowance/balance, fee/rebate/reward, order/cancel/tick/min-size, user
  WebSocket, cancel-all, and isolated-wallet evidence.
- Fleet SLO is pass/fresh for weather snapshots, CLOB book capture, and the
  observation-trigger watcher.
- The dedicated pilot wallet is funded only with isolated risk capital.
- The run budget, event caps, band caps, daily loss halt, Kelly gate, and
  cancel-all path are configured and tested.

## MM-2 Day-One Protocol

Use one market, one central band, and one dedicated pilot wallet.

1. Pre-open read-only check:
   - Run `python -m weather.reporting.data_quality.data_layer_audit --fleet --json`.
   - Run `python -m weather.reporting.fleet.fleet_observability report --strict`.
   - Run `python -m weather.market.market_microstructure audit --strict`.
   - Run a shadow `market_making_run` tick for the target market.
   - Confirm the live-pilot preflight would pass except for deliberate
     `--confirm-live-orders` absence.

2. Account and platform check:
   - Confirm whether the pilot is Polymarket global or Polymarket US.
   - Record API base URL, account jurisdiction, wallet type, signer/funder,
     collateral token, minimum order size, tick size, maker/taker fee fields,
     reward settings, balance endpoint, allowance endpoint, and cancel-all
     endpoint in the platform-verification evidence file.
   - Confirm read-only order/book/user/order-query calls work before any
     mutating call.

3. Heartbeat-lapse drill:
   - Start live-pilot with no quote permission and a false heartbeat gate.
   - Verify `NO_QUOTE_STALE_WATCHER` or equivalent fail-closed reason.
   - Place no order during this step.
   - Restore heartbeat readiness and verify preflight returns to `PASS`.

4. Min-size, tick, and post-only probe:
   - Use a far-from-mid, nonmarketable order on one band.
   - First submit invalid tick/min-size probes only where a preview or staging
     endpoint is available; otherwise run client-side validation only.
   - Submit one valid tiny GTC far-from-mid order at the configured tick and
     minimum size.
   - Confirm the order appears in open-order query/user stream.
   - Cancel it immediately and verify open-order count returns to zero.

5. One-band two-sided quote:
   - Quote one central band in harvest mode only.
   - Use the smallest valid size.
   - Post both sides as backed orders: YES bid plus complementary NO-side
     exposure, never a naked short.
   - Verify reserves equal the simulator's expected pUSD/backed-balance usage.
   - Cancel both sides after one quote TTL or immediately on any stale gate.

6. Fill lifecycle verification:
   - If a tiny fill occurs, reconcile fill size, fill price, position, open
     reserve release, and markout against `fills_long.csv`,
     `order_lifecycle.jsonl`, and `risk_events.jsonl`.
   - Do not scale if user stream/order query and local lifecycle disagree.

7. Next-cycle reward/rebate reconciliation:
   - Wait for the next reward/rebate accounting cycle.
   - Compare expected reward score, realized maker fee-equivalent, actual
     reward/rebate, adverse-selection markout, and settlement P&L.
   - Keep Kelly disabled until live-forward paper or MM-2 fills establish
     statistically credible net edge.

## Live Runbook

Start:

1. Confirm the current target date and market list.
2. Regenerate data-layer audit, fleet observability, promotion refresh, and
   snapshot evaluation.
3. Confirm live-readiness JSON, data-layer live gate, and platform-verification
   gate are current.
4. Run one shadow tick.
5. Run live-pilot only with explicit `--pilot --confirm-live-orders`.
6. Monitor `run_report.md`, `preflight.json`, `risk_events.jsonl`,
   `order_lifecycle.jsonl`, and CLOB loop status.

Pause:

1. Create the run folder's `cancel_all.flag` or set the operator pause switch.
2. Run one `market_making_run` tick.
3. Confirm all local quote intents are `NO_QUOTE_CANCEL_ALL`.
4. Confirm exchange open-order query returns zero remaining pilot orders.

Cancel All:

1. Use the exchange cancel-all endpoint for the pilot account.
2. Verify local `order_lifecycle.jsonl` records cancellation/release events.
3. Verify open-order reserves return to zero.
4. Do not resume until preflight, heartbeat, book freshness, source freshness,
   and observation-trigger freshness are all pass/fresh.

Flatten:

1. Prefer canceling resting orders over crossing the spread.
2. Use FAK/FOK only for explicit risk-reduction, never to chase stale edge.
3. Record flatten reason, expected fee/slippage, and post-flatten position.
4. Verify positions and reserves against the account API.

Redeem:

1. After settlement finalizes, reconcile winning positions, residual losing
   positions, pUSD collateral, and realized P&L.
2. Redeem only through the verified account/platform flow.
3. Record redemption transaction or platform reference in the run folder.
4. Compare final cash against the negative-risk simulator's settlement summary.

Rotate Keys:

1. Pause and cancel all orders first.
2. Revoke old credentials/allowances where applicable.
3. Generate new API credentials from the verified signer.
4. Run read-only checks, then min-size/tick probes before any quote resumes.

Failed User Stream:

1. Pause quoting immediately.
2. Fall back to authenticated open-order polling only for reconciliation.
3. Cancel all if stream freshness cannot be restored inside one quote TTL.
4. Do not count the run toward live-forward evidence.

CLOB Outage Or Stale Books:

1. Require `NO_QUOTE_STALE_BOOK`.
2. Cancel all resting orders if the stale condition persists beyond one TTL.
3. Preserve raw diagnostics and book-loop status.
4. Resume only after strict CLOB audit passes.

Stale Observation Watcher:

1. Require `NO_QUOTE_STALE_WATCHER`.
2. Cancel all weather-sensitive resting orders.
3. Restart `weather.operations.observation_trigger ensure`.
4. Resume only after watcher heartbeat and triggered fair value are fresh.

Process Death:

1. Do not infer that local process death cancels exchange orders.
2. Restart in reconciliation mode.
3. Query open orders, positions, balances, and allowances.
4. Rebuild local lifecycle state from exchange truth.
5. Cancel unknown orders before quoting resumes.

Daily Close:

1. Cancel all open orders before the configured close cutoff.
2. Export order, fill, position, balance, reward, and audit artifacts.
3. Reconcile local and exchange state.
4. File a run summary with markout, settlement P&L, reward/rebate, incidents,
   and whether the day counts toward the next gate.
