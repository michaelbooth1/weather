# 67. Authenticated Exchange Adapter And MM-2 Pilot Harness [PARTIAL 2026-06-16 - FINANCIAL RECONCILIATION ADDED]

Goal: implement the smallest live-order execution path that can run the MM-2
pilot without weakening the existing paper/risk gates.

Why this is missing: items 43-46, 55-57, and 44 build the keyless policy,
orchestration, lifecycle, budget, cockpit, and paper-scoring system. Item 45
defines live gates and platform/account verification. There is still no
roadmap owner for the authenticated exchange adapter that places, cancels,
heartbeats, reconciles, redeems, and proves real order lifecycle behavior.
Item 45's software gates are now ready: live-pilot requires current
live-readiness, data-layer audit, and platform-verification artifacts before
any adapter may submit an order.

- [x] Keep credentials, private keys, API secrets, wallet addresses, and
  allowance settings outside the repo; add read-only account diagnostics before
  any trading verb can run.
- [x] Add a signed CLOB adapter for post-only order create, cancel, cancel-all,
  heartbeat/dead-man behavior, order query, balances, allowances, positions,
  and redemption/reward status.
- [x] Preserve dry-run, read-only, and keyless paper modes as the default; live
  mode must require explicit operator flags plus current item-45 gates.
- [x] Reconcile user WebSocket fills/order updates and REST open-order queries
  into the existing `order_lifecycle.jsonl`, `budget_ledger.jsonl`, and risk
  event artifacts.
- [ ] Implement the MM-2 day-one probes: heartbeat-lapse throwaway order,
  min-size/tick/post-only rejection checks, one tiny two-sided quote, cancel-all
  verification, balance-reserve reconciliation, and user WebSocket lifecycle
  verification.
- [x] Add report-side paid-vs-predicted reconciliation for maker rebates,
  liquidity rewards, redemptions, fees, pUSD/USDC balances, and settlement P&L
  before any size increase.
- [ ] Collect real paid-vs-predicted evidence from an eligible live account
  across maker rebates, liquidity rewards, redemptions, fees, pUSD/USDC
  balances, and settlement P&L before any size increase.
- [x] Emit a pilot report comparing live fills, markouts, cancellations,
  heartbeat behavior, and rewards/rebates against the simultaneous paper
  counterfactual.

Acceptance: live orders cannot be submitted unless platform/account checks,
paper gates, SLO gates, risk caps, and operator confirmations pass; every live
order has a reconciled lifecycle from intent through cancel/fill/settlement;
and MM-2 remains min-size, bounded, and auditable until its pilot evidence
passes.

Exchange harness update (2026-06-16 UTC): `weather.market.mm_exchange`
introduces the keyless item-67 adapter boundary. The CLI wrapper
`python -m src.mm_exchange --run-folder ...` reads a live-pilot run folder,
verifies item-45 live-readiness/data-layer/platform gates, reports credential
environment presence without logging values, refuses live trading verbs unless
`--allow-live` and a future concrete trading adapter are present, and writes
`exchange_reconciliation.json` plus `exchange_reconciliation.md`. A read-only
fixture adapter reconciles exchange open orders and user-stream fill/cancel/
reject events into `order_lifecycle.jsonl`, `budget_ledger.jsonl`,
`fills_long.csv`, and `risk_events.jsonl`, so the artifact plumbing is testable
without keys or network side effects. The harness also emits MM-2 probe status
rows for heartbeat/dead-man, min-size/tick/post-only, tiny two-sided quote,
user-stream lifecycle, balance-reserve, and reward/rebate checks. Remaining
open work: concrete signed global/US exchange clients, real heartbeat and
post-only probes, read-only account endpoint implementations, redemption and
paid-vs-predicted reward/rebate reconciliation, and the live-vs-paper pilot
report. Focused tests:
`python -m pytest tests/market/test_mm_exchange.py tests/market/test_market_making_run.py tests/market/test_mm_risk.py tests/market/test_mm_policy.py tests/market/test_mm_paper.py tests/operations/test_schema_registry.py -q`
passed (`53` tests).

Request-plan and pilot-report update (2026-06-16 UTC): `mm_exchange` now emits
platform-specific adapter request diagnostics. For Polymarket US, the harness
builds redacted signed-request plans for preview/create post-only orders,
cancel, cancel-all, open-order query, positions, balances, rewards, and
redemption-status reads using the documented `X-PM-*` header shape and
`timestamp + method + path` signature payload. For Polymarket global, it builds
redacted CLOB request plans for heartbeat, post-only order submit, cancel,
cancel-all, open-order query, positions/balances, rewards, and redemption
status, while explicitly blocking order placement until a pre-signed EIP-712
order payload from the official CLOB client and an injected L2 header signer are
present. Reconciliation now also writes `mm2_probe_status.json`,
`mm2_pilot_report.json`, and `mm2_pilot_report.md`; the pilot report compares
live fill count/size/notional, cancellations/rejections, markouts, actual
reward/rebate evidence, and paper counterfactual expected reward/rebate fields,
and marks missing evidence explicitly. Updated focused tests:
`python -m pytest tests/market/test_mm_exchange.py -q` passed (`6` tests).
Remaining open work is intentionally live-adapter work: concrete signed
global/US clients, real heartbeat/post-only/cancel-all probes against an
eligible account, authenticated account endpoint reads, redemptions, and final
paid-vs-predicted settlement P&L reconciliation.

Signed-adapter software update (2026-06-16 UTC): `mm_exchange` now includes
`PolymarketUSHTTPAdapter` and `PolymarketGlobalHTTPAdapter` classes with
injected signers and transports, so tests exercise real request construction
without environment secrets or network side effects. The US adapter signs
post-only order create/preview, cancel, cancel-all, order query, balances,
positions, rewards, and redemption-status request paths through the documented
`X-PM-*` shape. The global adapter signs CLOB heartbeat, post-only submit,
cancel, cancel-all, order query, balances/positions, rewards, and redemption
request paths through `POLY_*` headers and refuses order placement unless the
caller provides a pre-signed EIP-712 order payload. Updated focused tests:
`python -m pytest tests/market/test_mm_exchange.py -q` passed (`8` tests).
Remaining item-67 work is now live-evidence and reconciliation work: real
eligible-account probes, user WebSocket lifecycle evidence, paid-vs-predicted
redemption/reward/settlement P&L, and final MM-2 acceptance.

Financial-reconciliation software update (2026-06-16 UTC): `mm_exchange` now
adds `financial_reconciliation` to `mm2_pilot_report.json` and renders a
`Financial Reconciliation` section in `mm2_pilot_report.md`. The payload
compares paper-expected rebate/reward score against actual reward/rebate
snapshots, fees, redemption status, settlement P&L, starting/ending pUSD/USDC
balances, balance delta, and total P&L after fees/incentives. Missing balance,
fee, redemption, settlement-P&L, or reward evidence is explicitly listed as
`financial:*` missing evidence, so a pilot cannot silently look complete before
post-settlement account data exists. The fixture-backed test proves the complete
path with read-only evidence and no committed secrets:
`python -m pytest tests/market/test_mm_exchange.py -q` passed (`8` tests).
Remaining open work is live evidence: real heartbeat/post-only/cancel-all
probes, user WebSocket lifecycle evidence from an eligible account, and actual
paid-vs-predicted payout/redemption/P&L snapshots.
