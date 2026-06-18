# 101. Live-Forward Gate State Reconciliation [COMPLETE 2026-06-18 - RECONCILED GATE ARTIFACT LIVE]

Goal: make active-day countability reflect the current state of snapshot,
observation-trigger, source-status, CLOB, and market-making loops instead of
leaving operators to reconcile conflicting stale/fresh reports by hand.

Source: `docs/research/MODEL_LIVE_REVIEW_2026-06-16.md`. The June 16
market-making run report showed `Preflight status: STALE`, zero quote rows, and
`counts_toward_live_forward_gate=false` across all 12 markets. Later
observation-trigger status showed a running watcher with fresh heartbeat, but
trade permission remained false and fleet collection still marked all 12
markets as at risk.

Why this is missing: item 57 added preflight remediation reports, but the live
review still required manually comparing run reports, loop status, observation
status, and source-status rows to know whether the day was countable.

## Design

Use the market-making tick as the reconciliation point because it already reads
the latest snapshot rows, source-status rows, CLOB books/features, promotion
state, observation watcher state, and preflight gates for the selected markets.
Do not make operators infer countability from several files.

1. Add a `live_forward_gate.json` artifact beside each run's `preflight.json`.
   Build it from the current tick's preflight payload and policy thresholds, so
   it refreshes every tick and cannot keep a stale verdict after upstream loops
   recover.
2. Preserve `preflight.json` as the raw gate evidence. The new artifact is the
   reconciled view: per market, include all gate rows, first failing gate,
   owner, last-good/current timestamps, stale threshold, and an explicit
   countability verdict.
3. Treat evidence classes separately:
   - model-review evidence needs current model rows plus source-status
     provenance, but may remain allowed when a source family is degraded and
     explicitly recorded.
   - paper-trading/live-forward evidence requires all preflight gates to pass.
   - live-trade-permission evidence additionally requires live-pilot mode and
     live account/platform gates.
4. Use the existing remediation owner map as the source of ownership for
   failing gates. The first failing gate is the first non-ok preflight gate in
   the market row, so the artifact points at the same root cause the run used
   to block quotes.
5. Store the artifact path and summarized verdict in `run_summary.json` and the
   markdown report so the daily roll has a single answer to "does today count?"
   for the current run.

- [x] Add a single live-forward gate summary artifact that joins latest
  snapshot freshness, source-status freshness, observation watcher freshness,
  CLOB freshness, promotion permission, and market-making preflight state for
  every selected market.
- [x] Include first-failing gate, current owner, last-good timestamp, current
  timestamp, stale threshold, and countability verdict per market.
- [x] Make `market_making_run` refresh or consume that gate summary on each
  tick so stale preflight state cannot persist after dependent loops recover.
- [x] Add explicit distinction between model-review evidence, paper-trading
  evidence, and live-trade-permission evidence.
- [x] Add regression coverage for the June 16 pattern: snapshot loop writes all
  markets, observation watcher is running, but trade permission remains false
  and the run must explain why.

Acceptance: a live-forward audit can answer "does today count?" from one
artifact, and any false verdict points to the exact stale or blocked component
without requiring manual cross-file reconciliation.

Verification:

- `python -m pytest tests/market/test_market_making_run.py::TestMarketMakingRun::test_live_forward_gate_explains_fresh_observation_but_stale_clob_block tests/market/test_market_making_run.py::TestMarketMakingRun::test_preflight_remediation_groups_missing_source_status_and_stale_clob`
- `python -m pytest tests/market/test_market_making_run.py`
- `python -m pytest tests/operations/test_import_architecture.py tests/market/test_mm_policy.py`
