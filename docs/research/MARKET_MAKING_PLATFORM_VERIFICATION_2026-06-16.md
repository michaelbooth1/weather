# Market-Making Platform Verification Evidence

Status: live-pilot gate design. This does not authorize live orders.

Sources checked on 2026-06-16:

- Polymarket global authentication:
  https://docs.polymarket.com/api-reference/authentication
- Polymarket global fees:
  https://docs.polymarket.com/trading/fees
- Polymarket global order creation:
  https://docs.polymarket.com/trading/orders/create
- Polymarket global markets and events:
  https://docs.polymarket.com/concepts/markets-events
- Polymarket US fees:
  https://docs.polymarket.us/fees
- Polymarket terms:
  https://polymarket.com/tos

## Required Artifact

`docs/research/mm_platform_verification_template.json` is the tracked
fail-closed template for `mm_platform_verification_v0.1`. Copy its structure
to the ignored runtime path `data/backtest/mm_platform_verification.json` and
fill it with current operator-owned evidence before live-pilot. A live-pilot
run must pass `--platform-verification` before preflight can pass.

The artifact must be refreshed within 24 hours of the live-pilot run and must
match the target date. It records the exact operating surface
(`polymarket_global` or `polymarket_us`), account jurisdiction, eligibility,
API base URL, CLOB host, wallet type, signature type/funder address, allowance
and balance checks, current fee/rebate/reward rules, order/cancel/tick/min-size
semantics, user WebSocket, cancel-all path, and isolated pilot wallet cap.

The artifact must not contain private keys, API secrets, mnemonics, passwords,
or seed phrases. The gate rejects files containing those exact secret fields.

## Gate Behavior

`live-pilot` preflight now requires all three live proof layers:

- `live_readiness`: operator readiness for wallet, allowances, heartbeat,
  user WebSocket, and cancel-all.
- `data_layer_live_gate`: current active-day CLOB tokens, condition IDs,
  CLOB feature rows, and book-available rows from the latest data-layer audit.
- `platform_verification_gate`: current platform/account/fee/reward/API
  evidence from the JSON artifact described above.

Shadow and paper-live-forward runs do not require this artifact.
