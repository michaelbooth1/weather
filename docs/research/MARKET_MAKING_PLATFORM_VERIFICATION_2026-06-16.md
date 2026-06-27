# Market-Making Platform Verification Evidence

Status: live-pilot gate design. This does not authorize live orders.

Sources checked on 2026-06-16 and tightened on 2026-06-26 after the US
private-stream, cancel-all, and latency-stopgap API-readiness review:

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
fail-closed template for `mm_platform_verification_v0.2`. Copy its structure
to the ignored runtime path `data/backtest/mm_platform_verification.json` and
fill it with current operator-owned evidence before live-pilot. A live-pilot
run must pass `--platform-verification` before preflight can pass.

The artifact must be refreshed within 24 hours of the live-pilot run and must
match the target date. It records the exact operating surface
(`polymarket_global` or `polymarket_us`), account jurisdiction, eligibility,
API base URL, CLOB host, wallet type, signature type/funder address, allowance
and balance checks, current fee/rebate/reward rules, order/cancel/tick/min-size
semantics, user WebSocket/private stream, cancel-all path, and isolated pilot
wallet cap.

The v0.2 artifact also requires structured API-lifecycle evidence:

- `maker_only_order_field` must match the platform (`participateDontInitiate`
  for `polymarket_us`, `postOnly` for `polymarket_global`) and
  `maker_only_order_field_verified` must be true.
- `private_user_stream` must prove connection, order snapshot, order update,
  fill event, and final-state reconciliation.
- `cancel_all` must prove both a cancel-all request and zero open orders after
  the request.
- For `polymarket_us`, `latency_stopgap` must prove order-reject handling,
  book refresh before retry, and pure-cancel exemption behavior.
- `secret_redaction` must prove that status output, source/docs scans, and
  generated artifact scans were run, that the scan scope is recorded, and that
  no unredacted secret-like query values remain in the evidence set.

The artifact must not contain private keys, API secrets, mnemonics, passwords,
or seed phrases. The gate rejects files containing secret fields such as
`private_key`, `api_key`, `api_secret`, `access_token`, or `secret_key`, and it
also rejects unredacted secret-like URL query values such as `apiKey=...` in any
nested artifact field. Redacted placeholders such as `apiKey=<redacted>` are
allowed for diagnostics.

## Gate Behavior

`live-pilot` preflight now requires all three live proof layers:

- `live_readiness`: operator readiness for wallet, allowances, heartbeat,
  user WebSocket, and cancel-all.
- `data_layer_live_gate`: current active-day CLOB tokens, condition IDs,
  CLOB feature rows, and book-available rows from the latest data-layer audit.
- `platform_verification_gate`: current platform/account/fee/reward/API
  evidence from the JSON artifact described above, including structured
  private-stream, cancel-all, maker-only, and US latency-stopgap proofs.

Shadow and paper-live-forward runs do not require this artifact.
