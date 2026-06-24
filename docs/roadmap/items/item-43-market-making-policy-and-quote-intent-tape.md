# 43. Market-Making Policy And Quote Intent Tape [COMPLETE 2026-06-14 - SHADOW POLICY LIVE]

Goal: convert the market-making research into a pure, auditable shadow quote
policy before any live order adapter exists.

Research source: `docs/research/MARKET_MAKING_RESEARCH_AUDIT_2026-06-13.md`.
The audit's strongest conclusion is that the current plan is right to separate
harvest quoting from model-edge quoting, but the quote engine needs explicit
permission, latency, and reason-code semantics before paper trading is useful.

- [x] Build a pure `mm_policy` decision function whose inputs are fair value,
  uncertainty, promotion state (`PASS` / `SHADOW` / `BLOCK`), known-edge slice,
  CLOB book state, source freshness, observation-trigger health, simulated
  inventory, reward config, and risk caps.
- [x] Encode the permission matrix from the research audit:
  `BLOCK` -> no quotes; `SHADOW` -> market-mid-anchored harvest only when
  books and sources are fresh; `PASS` slices -> model-skewed quotes; any stale
  watcher/heartbeat/book/source state -> pull/stand down; near decisive
  observation windows -> widen or stand down; FAK/taking remains paper-only
  until proven.
- [x] Keep harvest and edge regimes mechanically separate. Harvest uses the
  model as a veto, not as the quote center. Edge mode uses model fair value
  only where the promotion gauntlet and known-edge map say the slice is proven.
- [x] Write a complete `quotes_long.csv` intent tape for every tick: policy
  version/hash, model version, market/band/token IDs, promotion state, fair
  probability, market mid, uncertainty, edge, bid/ask/size, inventory summary,
  event-level risk, book spread/depth/imbalance/age, source freshness, latency
  budget status, expected reward/rebate value, adverse-selection buffer,
  final size limiter, and reason code.
- [x] Treat latency as a first-class input: model age, book age, source age,
  observation-trigger age, and intended order age must all be visible in the
  quote row and able to fail quote permission closed.
- [x] Unit-test policy reason codes, regime transitions, cap precedence,
  stale-input stand-down, and no-cross/post-only price generation.

Acceptance: the policy can run keyless in shadow across all registered weather
markets, emits an auditable quote/no-quote reason for every eligible band, and
never emits a trade-permissioned quote when source, book, model, or watcher
freshness violates configured latency budgets.

Implementation update (2026-06-14 local): `src.mm_policy` / `weather.market.mm_policy`
now implements the pure policy and a keyless shadow tape writer. It consumes
`f_family_promotion_refresh.json`, latest snapshot/CLOB rows, and
`observation_trigger_status.json`; writes `data/backtest/quotes_long.csv` plus
`data/backtest/mm_policy_shadow.json`; and always keeps
`live_trade_permission=false`. The first live-forward shadow run emitted 132
band decisions: 3 harvest quote intents, 129 no-quote rows, zero live-trade
permission rows. No-quote reason counts were missing book 89, stale book 28,
blocked promotion 11, and shadow disagreement 1. Focused tests
cover BLOCK fail-closed, SHADOW harvest, disagreement stand-down, PASS
known-edge model-skewed quotes, stale watcher stand-down, and tape writing.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-14 - SHADOW POLICY LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

