# 296. Impact- And Confidence-Aware Daily Prioritization And Model Promotion Gating [OPEN 2026-06-24 - POINT-ESTIMATE PROMOTION AND ORDINAL-ONLY ACTION RANKING]

Goal: rank the daily action queue by estimated impact, not just ordinal priority
and alphabetical area, and gate model promotion on a statistically-confident
delta instead of a bare point estimate.

Source: 2026-06-24 audit of the daily analysis script. `daily_flow_analysis._dedupe_actions`
sorts by `(PRIORITY_ORDER, area)`
(`src/weather/reporting/daily/daily_flow_analysis.py:206`), so within a priority
tier the queue is ordered alphabetically by area with no notion of magnitude.
Learnings carry a priority but no quantified impact even when one is available
(`excess_brier_rows`, market gap, taker net PnL at risk). Separately,
`daily_learning._retrain_plan` decides `promotion_ready` from a single point
estimate `delta_vs_current <= 0` (`daily_learning.py:1284-1292`) with no
confidence interval or minimum independent-sample requirement, even though the
taker side already uses clustered bootstrap promotion (item 275).

Why this matters: an operator working top-down should see the highest-impact
action first, and a promotion flag that flips on an unstable point estimate over
a handful of correlated market-days is exactly the false-confidence failure the
clustered taker gate was built to prevent on the trading side.

Why it is not already covered: item 36 owns production promotion gating and item
275 owns the clustered statistical promotion gate for the taker, but the model
promotion path in `daily_learning` still uses a point delta, and no item adds an
impact-weighted ranking to the daily action queue.

## Design

1. Attach a normalized `estimated_impact` to each learning/action from available
   magnitude fields (excess Brier-rows, market Brier gap, PnL at risk), with a
   documented default when no magnitude exists.
2. Re-rank the deduped action queue by `(priority, estimated_impact)` and show
   impact in the report so the top of the queue is the highest-leverage action.
3. Replace the point-estimate `promotion_ready`/`training_ready` delta check with
   a confidence-gated decision: require a minimum number of independent
   market-days and a bootstrap (or clustered) confidence interval on
   `delta_vs_current` (and report the same for `delta_vs_market`), reusing the
   item 275 clustered approach where practical.
4. Keep the change fail-closed: missing magnitude defaults to lowest impact, and
   missing confidence inputs block promotion rather than allowing it.

- [ ] Add `estimated_impact` to learnings/actions and rank the queue by
  `(priority, impact)`.
- [ ] Add a confidence-gated `promotion_ready`/`training_ready` decision with a
  minimum independent-sample requirement and a delta confidence interval.
- [ ] Report impact and promotion confidence in the daily analysis outputs.
- [ ] Add tests proving point-estimate-only deltas and tiny correlated samples
  cannot flip promotion ready, and that the queue orders by impact within
  priority.

Acceptance: the daily action queue is ordered by estimated impact within each
priority tier, and model `promotion_ready`/`training_ready` requires a
confidence-gated delta over a minimum number of independent market-days rather
than a bare point estimate, proven by tests including a small correlated sample
that must not pass.

Related: items 36, 117, 163, 262, 275.
