# 55. Market-Making Order Lifecycle And Budget Reconciliation [COMPLETE 2026-06-15 - LIFECYCLE LEDGER LIVE]

Goal: make the paper/live-forward test's budget and open-order state reconcile
to the quote lifecycle that a real Polymarket market-making process would need.

Observed from the running `http://localhost:8501/?market=mm` test on
2026-06-15: run `20260615T145404747277Z` was in `paper-live-forward` mode with
latest preflight `BLOCK` and zero current quote rows, but the run summary still
showed `462.435` / `500.00` USDC reserved from earlier harvest quote intents.
That is a useful fail-closed quote decision, but it is not enough to validate a
date/budget operator workflow. The test needs an explicit lifecycle for quote
reservations, replacements, cancels, expiries, fills, and releases.

This item also owns the Polymarket-specific budget nuance: open orders can
exceed wallet balance when they are across different markets, so the bot must
track operator run budget, event-level worst-case loss, per-market open-order
reserves, platform balance/allowance, and cross-market concurrency separately.

- [x] Give every quote intent a stable lifecycle key: run ID, tick timestamp,
  event/condition/token IDs, side, price, size, policy hash, and quote TTL.
- [x] Add an `order_lifecycle.jsonl` or equivalent ledger that records
  `intended`, `paper_posted`, `live_posted`, `replaced`, `canceled`,
  `expired`, `filled`, `blocked_by_preflight`, and `released` transitions.
- [x] Reconcile `budget_ledger.jsonl` against the lifecycle ledger on every
  tick so current reserved budget equals current open quote risk, not historical
  quote risk that should have been canceled or expired.
- [x] Release or explicitly park reservations when the latest policy no longer
  quotes a band, preflight fails, a quote TTL expires, a market pauses/resolves,
  a cancel-all path runs, or a fill/partial fill changes remaining exposure.
- [x] Model two separate constraints: the operator's total run loss budget and
  Polymarket collateral/balance semantics, including the platform behavior that
  cross-market open orders may be accepted even when their gross notional
  exceeds wallet balance.
- [x] Add reconciliation tests for reservation drift, BLOCK-to-release
  transitions, repeated tick idempotency, partial-fill accounting, same-market
  versus cross-market exposure, and global kill-switch/cancel-all handling.
- [x] Surface stale reservation age, reserved-by-market, reserved-by-event, and
  released budget in run summaries and the MM dashboard.

Acceptance: after any tick, the run summary's reserved USDC can be reproduced
from the lifecycle ledger; a latest-tick preflight `BLOCK` releases or
explicitly parks stale quote reservations; cumulative paper scoring still
preserves historical quote intents; and no live gate can use a budget number
that ignores Polymarket open-order and cross-market collateral semantics.

Implementation update (2026-06-15): `weather.market.market_making_run` now
writes `order_lifecycle.jsonl`, stable quote-leg lifecycle keys, quote TTLs,
replacement/expiry/cancel/preflight release events, and run-summary lifecycle
fields. `budget_ledger.jsonl` now reconciles against current open lifecycle
risk instead of cumulative historical quote risk. `cancel_all.flag` releases
open orders and prevents reposting, partial `filled` lifecycle events reduce
remaining risk, and the summary separates reserved risk by market/event while
recording Polymarket cross-market open-order semantics. Validation:
`pytest tests\market\test_market_making_run.py -q` passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - LIFECYCLE LEDGER LIVE`.
- The file contains 7 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

