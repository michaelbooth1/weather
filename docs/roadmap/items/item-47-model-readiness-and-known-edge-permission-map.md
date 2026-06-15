# 47. Model Readiness And Known-Edge Permission Map [COMPLETE 2026-06-15 - POLICY-CONSUMED MAP]

Goal: turn "how close is the model to market-make?" into a generated permission
artifact consumed by the quote engine and live gates.

Research source: `docs/research/MM_MODEL_READINESS_GAP_PLAN.md`. The current
answer is phase-specific: shadow/paper can start without beating Polymarket;
live harvest requires positive paper markouts under market-mid quoting; and
model-skewed edge quoting requires per-slice evidence that the model beats
Polymarket and survives execution costs.

- [x] Generate a `data/backtest/mm_known_edge_map.json` plus Markdown report
  from promotion refresh, paper-trading markouts, and casebook taxonomy; attach
  gap decomposition, CLOB overlay scores, and live-pilot markouts as those
  feeds mature.
- [x] Emit explicit permissions by market, cutoff hour, band distance, band
  type, casebook taxonomy, regime, and source-freshness state:
  `no_quote`, `harvest_only`, `edge_research`, `edge_allowed`, or
  `take_research_only`.
- [x] Keep PASS/SHADOW/BLOCK as the base permission system: PASS slices may
  become edge candidates, SHADOW slices stay harvest-only, and BLOCK slices do
  not quote.
- [x] Require market-or-better Brier/log-loss evidence, held-out or
  live-forward confidence intervals, and positive post-fill markouts before any
  slice can move from `edge_research` to `edge_allowed`.
- [x] Track the active model gap burn-down for the economically relevant cells:
  US morning/overnight rows, at-settle and one-off central bands, CLOB
  `market_lead`, CLOB `book_liquidity_artifact`, `market_overreaction`,
  stale-source cases, and WU lag/catch-up cases.
- [x] Expose the known-edge map to `mm_policy` so model-skewed quoting cannot be
  enabled by hand-editing policy parameters or relying on aggregate model
  optimism.

Acceptance: every quote-intent row can be traced to a generated permission
record; broad fleet edge mode remains disabled while aggregate evidence trails
Polymarket; a promoted market such as Atlanta can be considered for edge mode
only where the permission map and paper markouts both clear; and the report
shows exactly which model-market gap cells must improve next.

Implementation status (2026-06-15): `src.mm_paper` now emits the initial
known-edge artifact at `data/backtest/mm_known_edge_map.json` plus
`data/backtest/mm_known_edge_map.md` as a consumer of promotion refresh state
and paper markout slices. PASS markets remain harvest-only until conservative
paper fills have positive markout/net evidence; positive but under-seasoned
slices become `edge_research`; `edge_allowed` requires market evidence plus the
14-day locked live-forward paper gate. SHADOW remains `harvest_only`, BLOCK
remains `no_quote`, and the JSON includes active model-gap cells.

Policy consumption update (2026-06-15 UTC): `src.mm_policy` /
`weather.market.mm_policy` now loads `data/backtest/mm_known_edge_map.json`,
resolves the best generated permission record for each quote input, and emits
`known_edge_permission`, `known_edge_reason`, and `known_edge_record_key` in
the quote-intent tape. `edge_allowed` is the only map permission that can enable
model-skewed edge quoting; `edge_research` and `harvest_only` stay in harvest
mode, and `no_quote` fails closed with `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
`src.market_making_run` accepts the same `--known-edge-map` input and records
map diagnostics in run preflight artifacts. Validation:
`pytest tests\market\test_mm_policy.py tests\market\test_market_making_run.py tests\market\test_mm_paper.py -q`
passed (16 tests).
