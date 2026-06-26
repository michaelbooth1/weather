# 45. Market-Making Position Sizing, Risk Controls, And Live Gate [COMPLETE 2026-06-16 - PLATFORM VERIFICATION GATE LIVE]

Goal: define the sizing and operational gates that must be green before any
real-money market-making pilot.

Research source: the audit recommends explicit sizing formulas and capped
fractional Kelly only after observed edge is credible. It also flags a live
verification gap: `MARKET_MAKING_PLAN.md` says token persistence shipped, but
the current `data/backtest/data_layer_audit_report.md` still reported
`Market token IDs persisted: False` when the research was written.

- [x] Represent inventory at event level as settlement P&L if each mutually
  exclusive band wins. Track expected value, standard deviation over the model
  density, worst-case loss, and negative-risk conversion state rather than only
  token counts.
- [x] Implement a sizing stack:
  `min(rewards_min_size_or_target, per-band cap, per-event expected-loss cap,
  per-event worst-case cap, daily drawdown budget, fractional-Kelly cap,
  available backed balance after open-order reserves)`.
- [x] Use zero Kelly size until live-forward paper and/or MM-2 fills produce
  statistically credible net edge. When enabled, use heavily fractional Kelly
  only (for example 0.10-0.25x full Kelly) and keep hard loss caps binding.
- [x] Add daily loss halt, per-band share cap, per-event notional cap, fleet
  notional cap, stale-source halt, stale-book halt, stale-observation-trigger
  halt, heartbeat halt, and manual pause/cancel-all paths to the risk design.
- [x] Add balance, allowance, and open-order reserve accounting primitives.
- [x] Complete full negative-risk market simulation for simultaneous YES/NO
  orders, including conversion, partial fills, open order reductions, pUSD
  collateral, and redemption after settlement.
- [x] Make the latest data-layer audit a live gate: no MM-2 start unless CLOB
  token IDs, condition IDs, order-book depth, and trade tapes are verified in
  current active-day artifacts, not just described in roadmap text.
- [x] Verify the exact operating platform before live keys: Polymarket global
  versus Polymarket US eligibility, current fees, current reward/rebate rules,
  account jurisdiction, wallet type, allowances, and API semantics.
- [x] Write the MM-2 day-one protocol: heartbeat-lapse drill with a throwaway
  far-from-mid order, min-size/tick/post-only rejection probes, one tiny
  two-sided quote on one band, user WebSocket lifecycle verification,
  balance-reserve verification, and next payout-cycle reward/rebate
  reconciliation before scaling beyond one event.
- [x] Write the live runbook: start, pause, cancel-all, flatten, redeem,
  reconcile, rotate keys, handle failed user WebSocket, handle CLOB outage,
  handle stale observation watcher, and recover after process death.

Acceptance: no live market-making order is allowed until items 43 and 44 have
passed their acceptance gates, the latest data-layer audit proves token/book
artifacts are current, account/platform eligibility is verified, caps and
balance math are tested, kill-switch drills pass, and the dedicated pilot
wallet is funded only with isolated risk capital.

Risk-primitives update (2026-06-15 UTC): `weather.market.mm_risk` now provides
pure, side-effect-free risk primitives for item 45. It can score event
inventory as settlement P&L across mutually exclusive outcomes, normalize model
density, compute expected value/stdev/worst-case loss, carry negative-risk
conversion state, size quotes through the explicit cap stack, force zero Kelly
size until live edge is marked credible, emit fail-closed halt reasons for
stale source/book/watcher/heartbeat/manual/cancel-all/daily-loss states, and
account for backed balance minus open-order reserves and pending allowances.
Focused tests: `pytest tests\market\test_mm_risk.py
tests\market\test_mm_policy.py tests\market\test_market_making_run.py -q`
passed (`28` tests). This does not authorize live trading: platform/account
verification, day-one protocol, and live runbook remain open.

Negative-risk simulation update (2026-06-15 UTC): `mm_risk` now includes a
pure negative-risk account lifecycle simulator (`mm_negative_risk_simulation_v0.1`).
It reserves backed balance for YES/NO/covered-YES-ask orders, rejects unbacked
orders, supports partial fills, consumes pUSD collateral into positions, releases
reserves on order reductions and cancel-all, converts complete YES sets across
all mutually exclusive outcomes back to pUSD collateral, and settles remaining
YES/NO positions into final redemption/P&L. Focused tests cover partial fills,
open-order reductions, complete-set conversion, unbacked-order rejection,
cancel-all reserve release, and settlement redemption.

Data-layer live-gate update (2026-06-15 UTC): `market_making_run` now requires
the latest data-layer audit for `live-pilot` preflight. The gate checks that the
audit proves CLOB token IDs, current target-date token rows, CLOB feature rows,
and book-available rows before any live-pilot start can pass. Missing or invalid
audit proof emits the `data_layer_live_gate` preflight blocker and corresponding
remediation root cause. Focused tests prove shadow mode does not require the
gate and live-pilot blocks when the audit lacks current CLOB proof.

Runbook update (2026-06-15 UTC): `docs/research/MARKET_MAKING_LIVE_RUNBOOK_2026-06-15.md`
now records the MM-2 day-one protocol and live operating runbook, with official
Polymarket global and Polymarket US documentation links checked on 2026-06-15.
The account/platform verification checkbox remained open because it depended on
the actual operating account, jurisdiction, wallet type, API base URL,
allowances, fee/reward settings, and live-key semantics immediately before use.

Platform verification gate update (2026-06-16 UTC, tightened 2026-06-26 UTC):
`market_making_run` now requires a current `mm_platform_verification_v0.2`
artifact for `live-pilot`.
The default `data/backtest/mm_platform_verification.json` is a fail-closed
runtime artifact path, with tracked template
`docs/research/mm_platform_verification_template.json`; operators must refresh
the runtime artifact within 24 hours for the target date before preflight can
pass. The gate validates platform surface
(`polymarket_global` versus `polymarket_us`), account jurisdiction, eligibility,
API base URL, CLOB host, wallet type, signature type/funder, allowances,
balance, fee parameters, rebate/reward rules, order/cancel/tick/min-size
semantics, maker-only order field, private user-stream lifecycle/fill/final
state reconciliation, cancel-all zero-open-order confirmation, isolated wallet
cap, backend-only signing, secret hygiene, and source URLs. For
`polymarket_us`, it also requires latency-stopgap order-reject handling, book
refresh before retry, and pure-cancel exemption proof. It emits a
`platform_verification_gate` blocker and `platform_verification_gate_blocked`
remediation incident when missing, stale, target-mismatched, incomplete, or
containing exact secret fields. Shadow and paper-live-forward remain keyless and
do not require the artifact. Supporting doc:
`docs/research/MARKET_MAKING_PLATFORM_VERIFICATION_2026-06-16.md`. Focused
tests: `python -m pytest tests/market/test_market_making_run.py -q` passed
(`17` tests). This completes item 45's software gate; it still does not
authorize live trading unless a real operator-owned verification artifact
passes immediately before use.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - PLATFORM VERIFICATION GATE LIVE`.
- The file contains 10 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

