# 45. Market-Making Position Sizing, Risk Controls, And Live Gate [NEW - RESEARCH AUDIT]

Goal: define the sizing and operational gates that must be green before any
real-money market-making pilot.

Research source: the audit recommends explicit sizing formulas and capped
fractional Kelly only after observed edge is credible. It also flags a live
verification gap: `MARKET_MAKING_PLAN.md` says token persistence shipped, but
the current `data/backtest/data_layer_audit_report.md` still reported
`Market token IDs persisted: False` when the research was written.

- [ ] Represent inventory at event level as settlement P&L if each mutually
  exclusive band wins. Track expected value, standard deviation over the model
  density, worst-case loss, and negative-risk conversion state rather than only
  token counts.
- [ ] Implement a sizing stack:
  `min(rewards_min_size_or_target, per-band cap, per-event expected-loss cap,
  per-event worst-case cap, daily drawdown budget, fractional-Kelly cap,
  available backed balance after open-order reserves)`.
- [ ] Use zero Kelly size until live-forward paper and/or MM-2 fills produce
  statistically credible net edge. When enabled, use heavily fractional Kelly
  only (for example 0.10-0.25x full Kelly) and keep hard loss caps binding.
- [ ] Add daily loss halt, per-band share cap, per-event notional cap, fleet
  notional cap, stale-source halt, stale-book halt, stale-observation-trigger
  halt, heartbeat halt, and manual pause/cancel-all paths to the risk design.
- [ ] Simulate balance and allowance accounting for simultaneous YES/NO orders
  in negative-risk markets, including reserved balances, partial fills, open
  order reductions, pUSD collateral, and redemption after settlement.
- [ ] Make the latest data-layer audit a live gate: no MM-2 start unless CLOB
  token IDs, condition IDs, order-book depth, and trade tapes are verified in
  current active-day artifacts, not just described in roadmap text.
- [ ] Verify the exact operating platform before live keys: Polymarket global
  versus Polymarket US eligibility, current fees, current reward/rebate rules,
  account jurisdiction, wallet type, allowances, and API semantics.
- [ ] Write the MM-2 day-one protocol: heartbeat-lapse drill with a throwaway
  far-from-mid order, min-size/tick/post-only rejection probes, one tiny
  two-sided quote on one band, user WebSocket lifecycle verification,
  balance-reserve verification, and next payout-cycle reward/rebate
  reconciliation before scaling beyond one event.
- [ ] Write the live runbook: start, pause, cancel-all, flatten, redeem,
  reconcile, rotate keys, handle failed user WebSocket, handle CLOB outage,
  handle stale observation watcher, and recover after process death.

Acceptance: no live market-making order is allowed until items 43 and 44 have
passed their acceptance gates, the latest data-layer audit proves token/book
artifacts are current, account/platform eligibility is verified, caps and
balance math are tested, kill-switch drills pass, and the dedicated pilot
wallet is funded only with isolated risk capital.
