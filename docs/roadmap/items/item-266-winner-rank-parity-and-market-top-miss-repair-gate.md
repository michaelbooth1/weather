# 266. Winner-Rank Parity And Market-Top-Miss Repair Gate [COMPLETE 2026-06-23 - PARITY GATE LIVE, CURRENT MODEL BLOCKED]

Goal: close the model-vs-market winner-rank gap that lets the model correctly
find the final top bucket late in the day while still trailing market Brier
through the scoring window.

Source: `docs/roadmap/audits/calibration-price-competitiveness-audit-2026-06-23.md`.
The June 16-22 scored window shows model Brier `0.0490` versus market Brier
`0.0406`, even though final top-bucket hit rate is high. Winner rows explain
almost all of the gap: model winner probability averages `48.5%` versus
market `55.7%`. The clearest case class is `model_top_miss |
market_top_hit`: `2,665` snapshots with model Brier `0.0819` versus market
`0.0311`, compared with only `1,267` reverse snapshots where the model tops
the winner and market misses.

Why this matters: existing items own early-hour, exact-band, bottom-location,
current-max, ramp, served-distribution, and market-informed repairs, but none
of them owns the cross-day parity metric that best explains the current
price-competitiveness failure. Without a generated owner, the project can
continue improving final-top recognition or incumbent-relative Brier while
still losing to market prices on the snapshots that dominate settlement Brier.

## Design

1. Add a generated winner-rank parity report with model top-hit rate, market
   top-hit rate, `model_top_miss | market_top_hit` count, reverse count,
   winner probability gap, Brier contribution, and log-loss contribution.
2. Slice the report by market, local hour, cutoff regime, source-health state,
   forecast disagreement, settlement distance, band type, current-max trust
   state, runtime identity, and active candidate/variant.
3. Route each dominant case class to an existing owner when possible:
   Items 160/219/228/230 for early and exact-band failures, Items 194/195/232
   for ramp warm-tail and current-max failures, Item 233 for
   served-distribution calibration-head failures, and Items 156/264 for
   market-informed benchmark/residual evidence.
4. Keep scalar calibration and global sharpening candidates diagnostic-only
   unless they reduce the parity case class without adjacent-band or
   bottom-location regressions.
5. Add a proof-packet input,
   `weather_only_model_proof_packet.gates.winner_rank_parity_gate`, that keeps
   broad weather-only claims blocked while the parity gap remains above
   tolerance.

- [x] Implement the winner-rank parity JSON/Markdown report.
- [x] Add the parity report to daily refresh after proper-scoring and
  settled-day root-cause artifacts are available.
- [x] Add proof-packet fields for model top-hit rate, market top-hit rate,
  market-top/model-miss excess, and parity-gate status.
- [x] Attach each top parity case class to an existing active roadmap owner or
  emit a suggested item only when no owner exists.
- [x] Validate at least one no-market candidate against the parity gate with
  early, exact-band, bottom-location, ramp, late, and broad Brier guardrails.

Acceptance: the active weather-only candidate may only claim progress on this
item when the generated parity report shows the `model_top_miss |
market_top_hit` excess and Brier contribution falling materially versus
current, model top-hit rate closing the gap to market top-hit rate, and no
regression beyond tolerance in the proof-packet early-hour, exact-band,
bottom-location, ramp, late lock-in, and broad-claim gates. Market-informed
improvements must remain in the separate market/residual lane unless the
weather-only proof packet also passes.

## Completion Evidence

Implemented in `src/weather/reporting/winner_rank_parity.py` with schema
`winner_rank_parity_v0.1`, JSON output
`data/backtest/winner_rank_parity.json`, and Markdown output
`data/backtest/winner_rank_parity.md`. The report computes model and market
top-hit rates, `model_top_miss | market_top_hit` and reverse counts, winner
probability gap, Brier contribution, log-loss contribution, and slices by
market, local hour, cutoff regime, source-health state, forecast disagreement,
settlement distance, band type, current-max trust state, runtime identity, and
variant.

Daily refresh now runs `winner_rank_parity` after
`proper_scoring_reliability_scorecard` and `settled_day_root_cause`. The
weather-only proof packet consumes the generated report through
`weather_only_model_proof_packet.gates.winner_rank_parity_gate` and exposes
model top-hit rate, market top-hit rate, market-top/model-miss excess, and the
parity gate status.

The current generated artifact is intentionally blocking: served current model
top-hit rate is `0.5407` versus market `0.6356`, market-top/model-miss excess
is `1390`, and the model-top-miss/market-top-hit Brier contribution is
`0.0092`. Latest available no-market candidates are also evaluated through
broad, early, exact-band, bottom-location, ramp, and late Brier guardrails;
the active item50 candidate remains blocked. Top parity case
classes are routed to existing owners in items 160/219/228/230, 194/195/232,
233, and 156/264 where applicable.

Verification: `python -m pytest tests/reporting/test_winner_rank_parity.py
tests/reporting/test_weather_only_model_proof_packet.py
tests/operations/test_daily_refresh.py tests/operations/test_schema_registry.py
-q` passed on 2026-06-23.

Related: items 35, 48, 115, 156, 160, 194, 195, 219, 228, 230, 232, 233, 262,
264.
