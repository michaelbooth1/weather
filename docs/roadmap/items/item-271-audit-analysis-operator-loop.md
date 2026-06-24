# 271. Audit Analysis Operator Loop [COMPLETE 2026-06-23 - DASHBOARD OPERATOR LOOP LIVE]

Goal: turn the saved model-market disagreement audit snapshots and the periodic
`model_market_disagreement_analysis` recommendations into an operator workflow
that reliably drives model-improvement work without silently changing model or
trading behavior.

Owner/package: weather.reporting

Source: the audit snapshot layer now auto-saves latest top-edge rows when
`abs(model_probability - market_yes) >= 50` full percentage points, and the
periodic analysis task emits JSON/Markdown recommendations. Those
recommendations are currently advisory files under `data/backtest`; they are
not yet visible in the dashboard, routed to roadmap/model repair owners, or
converted into replay experiments after settlement.

Why this matters: the disagreement audits capture exactly the cases where the
model and market disagree most. If the recommendations remain buried in a
generated Markdown file, we will miss recurring market-closer slices, pending
high-gap watchlist cases, and concrete repair candidates. The next step should
make the analysis actionable while preserving the rule that no model or trading
change happens automatically from an unsettled or unreviewed recommendation.

## Design

1. Add an Audit Analysis dashboard section that reads
   `data/backtest/model_market_disagreement_analysis.json` and shows:
   top recommendations, pending watchlist, resolved market/model closer counts,
   by-market/direction patterns, and latest generation time.
2. Add stale/missing analysis status indicators so operators know when the
   scheduled analysis task has stopped or the audit log has not produced fresh
   qualifying snapshots.
3. Route resolved market-closer priority patterns to existing repair lanes:
   exact-band/winner-centering, warm-tail dampening, source-state reliability,
   or market-specific residual repair, with explicit owner item references.
4. Keep pending recommendations as settlement watchlist only. After settlement
   labels are available, rerun the audit/analysis and only then count the case
   toward repair evidence.
5. Add an export or review queue format that lets an operator promote a
   recommendation into a tracked experiment/backlog note without editing the
   generated analysis artifact by hand.
6. Add tests for dashboard rendering, stale/missing artifact handling, and
   recommendation-to-owner routing.

- [x] Render Audit Analysis in the dashboard with priority recommendations and
      pending watchlist.
- [x] Add stale/missing analysis warnings and generation timestamp display.
- [x] Map recommendation categories/directions to owner roadmap items and
      repair lanes.
- [x] Keep pending-settlement cases visibly separate from resolved evidence.
- [x] Add an operator review/export queue for accepted recommendations.
- [x] Add regression tests covering JSON read, dashboard table shape, stale
      status, and owner-route mapping.

Acceptance: operators can see the latest audit-analysis recommendations in the
dashboard, distinguish pending watchlist from resolved evidence, and route a
resolved recurring pattern to a named repair lane or roadmap item. The system
must not automatically alter model parameters, promotion gates, or trading
policy from these recommendations without a separate reviewed experiment.

Completion notes (2026-06-23): the Overview dashboard now renders an Audit
Analysis section from `data/backtest/model_market_disagreement_analysis.json`,
including artifact/audit-log freshness, generation time, resolved
model-versus-market closer counts, priority recommendations, the pending
settlement watchlist, by-market/direction patterns, and an operator review queue.
The analysis payload now attaches deterministic repair routes for
exact-band/winner-centering, warm-tail dampening, source-state reliability, and
market-specific residual repair. Pending recommendations are routed to a
settlement-watchlist lane and marked non-countable until settlement.

The periodic analysis writer now also exports
`data/backtest/model_market_disagreement_review_queue.json` with
`automatic_model_or_trading_change_allowed=false` and no automatic model,
promotion-gate, or trading-policy side effects. Verified with focused reporting,
dashboard-helper, Streamlit overview, compile, and schema-registry unit tests.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - DASHBOARD OPERATOR LOOP LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

