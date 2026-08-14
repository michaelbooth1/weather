# 67. Authenticated Exchange Adapter And MM-2 Pilot Harness [PARTIAL 2026-08-14 - INTERNATIONAL BOUNDED PROBE PROOF RUNNING; ELIGIBLE-HOST EVIDENCE OPEN]

Goal: implement the smallest live-order execution path that can run the MM-2
pilot without weakening the existing paper/risk gates.

Source: market-making roadmap items 43-46 and 55-57 built the keyless
policy/orchestration/risk foundation, while item 45 defines the platform and
account gates required before any live order can be submitted.

Why this is missing: items 43-46, 55-57, and 44 build the keyless policy,
orchestration, lifecycle, budget, cockpit, and paper-scoring system. Item 45
defines live gates and platform/account verification. There is still no
roadmap owner for the authenticated exchange adapter that places, cancels,
heartbeats, reconciles, redeems, and proves real order lifecycle behavior.
Item 45's software gates are now ready: live-pilot requires current
live-readiness, data-layer audit, and platform-verification artifacts before
any adapter may submit an order.

Why this matters: authenticated exchange access is the first point where a
software defect can spend real funds or leave live orders open. The adapter and
pilot evidence must prove lifecycle, reconciliation, and paid-vs-predicted
behavior before any size increase.

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

## 2026-06-18 audit disposition

The Python audit found the software harness implemented through keyless safety,
signed request construction with injected signers/transports, live-gate
enforcement, read-only fixture reconciliation, pilot-report emission, and
financial reconciliation reporting. The unchecked MM-2 probe and
paid-vs-predicted boxes require an eligible live account, credentials kept
outside the repo, and real exchange lifecycle/account evidence. They remain
open deliberately; closing them without live-account artifacts would weaken the
acceptance criteria.

## 2026-06-24 evidence-only disposition

No live probe was run. The current host has no eligible live credential refs in
the environment:

- Polymarket US missing: `POLYMARKET_US_KEY_ID`,
  `POLYMARKET_US_SECRET_KEY_STORAGE_REF`.
- Polymarket global missing: `POLYMARKET_API_KEY`,
  `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`,
  `POLYMARKET_FUNDER_ADDRESS`, `POLYMARKET_PRIVATE_KEY_STORAGE_REF`.
- No forbidden direct secret env vars were present.

The existing evidence harness remains healthy:

- `python -m pytest -q tests\market\test_mm_exchange.py` -> 8 passed.

Because no eligible live account or external credential material is available,
the MM-2 heartbeat, post-only/min-size/tick, tiny two-sided quote, cancel-all,
user WebSocket lifecycle, and paid-vs-predicted payout evidence remain blocked.
No market-risk code changes were made.

2026-06-24 continuation check:

- Rechecked the live credential environment; the same Polymarket US/global
  credential references remain absent, and no forbidden direct secret env vars
  are present.
- Inspected the eight newest `data/mm_runs/**/preflight.json` files. They are
  `paper-live-forward` runs rather than `live-pilot` runs, and all report
  `live_readiness.ok = false`.
- No live exchange CLI invocation was run because the existing harness requires
  both an eligible `live-pilot` run folder and external credential references
  before live verbs can be enabled.

## 2026-08-14 International-only pilot disposition

The credential-absence disposition above is historical and is no longer the
owning blocker. The operator approved an International Polymarket pilot from a
separate genuinely eligible execution host. Ontario production remains a
read-only build, capture, and evidence host: do not install or inspect wallet
credentials here and do not place or cancel orders from it. Polymarket US is
outside product scope and must never be used.

The current Stage 0/1 contract is exactly one International condition/token, a
finite non-raisable 100 pUSD-equivalent wallet cap, forced post-only behavior,
no naked sells, and all existing lower risk ceilings preserved. Mutation stays
disabled unless authoritative user-event health, user-event, open-order, and
exact-position readers are present. The official-client adapter must not expose
a generic command-line live-mutation path.

Stage 0/1 remains proof-gated on an immutable exact-tip full suite and a
reviewed source transfer to the eligible host. A separate bounded Stage 2
lifecycle implementation is not integration-ready or live-ready. The two
unchecked live-evidence bullets above remain open until a tiny real lifecycle
and paid-vs-predicted settlement/rebate record are reconciled without weakening
any gate or increasing any ceiling.
