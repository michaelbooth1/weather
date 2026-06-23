# 279. Maker Clustered Statistical Promotion Gate [OPEN 2026-06-23 - 34 FILLS ACROSS 3 MARKET-DAYS CANNOT PROVE IMPROVEMENT]

Goal: make maker improvement and promotion claims use independent market-day
clusters instead of raw quote-row or fill-row counts.

Source: the June 21-23 maker paper audit found `82,302` quote rows, `2,314`
quote legs, `34` conservative fills, and `+1.5145` USDC net after estimated
fees/incentives. The fill-level bootstrap interval still crossed zero, and the
evidence was concentrated in only three filled market-days: Atlanta, Houston,
and Austin.

Why this matters: quote rows inside one market-day are highly autocorrelated.
Treating thousands of quote rows as independent evidence would overstate
confidence and could promote a maker policy on noise. The statistical unit for
maker improvement should be target-day by market, with policy/model variants
pre-registered.

## Design

1. Add a maker promotion scorecard that reports independent cluster counts by
   `(target_date, market_id)`, not just quote/fill rows.
2. Compute cluster-robust or clustered bootstrap intervals for net P&L,
   adverse-selection markout, settlement P&L, fill rate, and queue-estimated
   fill quality.
3. Require a minimum number of independent market-day clusters before any
   broad improvement claim or promotion.
4. Separate exploratory slices from confirmatory gates, with
   multiple-testing-aware thresholds for model-version and policy bakeoffs.
5. Record the claim scope explicitly: selected-market proof, all-market
   evidence, market-specific permission, or live-pilot readiness.

- [ ] Add cluster-count and cluster-bootstrap fields to maker paper JSON and
  Markdown reports.
- [ ] Block maker improvement claims when independent market-day cluster count
  is below the configured minimum.
- [ ] Add multiple-testing-aware summaries for maker model/policy bakeoffs.
- [ ] Add tests showing raw quote-row growth cannot by itself open promotion.

Acceptance: maker paper reports and trading evidence can say whether the
current maker evidence is statistically countable, using market-day clusters and
confidence intervals. A positive raw P&L or large quote-row count cannot open a
promotion gate without sufficient independent clusters.

Related: items 44, 117, 163, 260, 275, 278.
