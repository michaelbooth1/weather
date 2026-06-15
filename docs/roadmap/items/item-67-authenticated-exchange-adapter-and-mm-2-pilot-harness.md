# 67. Authenticated Exchange Adapter And MM-2 Pilot Harness [NEW - BLOCKED BY ITEM 45]

Goal: implement the smallest live-order execution path that can run the MM-2
pilot without weakening the existing paper/risk gates.

Why this is missing: items 43-46, 55-57, and 44 build the keyless policy,
orchestration, lifecycle, budget, cockpit, and paper-scoring system. Item 45
defines live gates and platform/account verification. There is still no
roadmap owner for the authenticated exchange adapter that places, cancels,
heartbeats, reconciles, redeems, and proves real order lifecycle behavior.

- [ ] Keep credentials, private keys, API secrets, wallet addresses, and
  allowance settings outside the repo; add read-only account diagnostics before
  any trading verb can run.
- [ ] Add a signed CLOB adapter for post-only order create, cancel, cancel-all,
  heartbeat/dead-man behavior, order query, balances, allowances, positions,
  and redemption/reward status.
- [ ] Preserve dry-run, read-only, and keyless paper modes as the default; live
  mode must require explicit operator flags plus current item-45 gates.
- [ ] Reconcile user WebSocket fills/order updates and REST open-order queries
  into the existing `order_lifecycle.jsonl`, `budget_ledger.jsonl`, and risk
  event artifacts.
- [ ] Implement the MM-2 day-one probes: heartbeat-lapse throwaway order,
  min-size/tick/post-only rejection checks, one tiny two-sided quote, cancel-all
  verification, balance-reserve reconciliation, and user WebSocket lifecycle
  verification.
- [ ] Add paid-vs-predicted reconciliation for maker rebates, liquidity
  rewards, redemptions, fees, pUSD/USDC balances, and settlement P&L before any
  size increase.
- [ ] Emit a pilot report comparing live fills, markouts, cancellations,
  heartbeat behavior, and rewards/rebates against the simultaneous paper
  counterfactual.

Acceptance: live orders cannot be submitted unless platform/account checks,
paper gates, SLO gates, risk caps, and operator confirmations pass; every live
order has a reconciled lifecycle from intent through cancel/fill/settlement;
and MM-2 remains min-size, bounded, and auditable until its pilot evidence
passes.
