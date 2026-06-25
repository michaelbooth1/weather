# 279. Maker Clustered Statistical Promotion Gate [COMPLETE 2026-06-23 - MARKET-DAY CLUSTER GATE LIVE]

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

- [x] Add cluster-count and cluster-bootstrap fields to maker paper JSON and
  Markdown reports.
- [x] Block maker improvement claims when independent market-day cluster count
  is below the configured minimum.
- [x] Add multiple-testing-aware summaries for maker model/policy bakeoffs.
- [x] Add tests showing raw quote-row growth cannot by itself open promotion.

Acceptance: maker paper reports and trading evidence can say whether the
current maker evidence is statistically countable, using market-day clusters and
confidence intervals. A positive raw P&L or large quote-row count cannot open a
promotion gate without sufficient independent clusters.

Completion evidence (2026-06-23):

- Added `model_variant_clustered_promotion_gate`, which groups maker
  model-version evidence by independent `(target_date, market_id)` clusters.
- The gate reports deterministic cluster-bootstrap intervals for net P&L,
  adverse-selection markout, settlement P&L, fill rate, and queue-estimated fill
  quality.
- Candidate model/policy pairs are compared against `served_current` on paired
  market-day clusters with a Bonferroni-adjusted alpha over the pre-registered
  model/policy family.
- Maker paper JSON, Markdown, and trading-evidence summaries now expose the
  clustered gate status, method, pair counts, pass counts, adjusted alpha, and
  failed gates.
- Tests prove 40 quote rows from one market-day still block promotion, while a
  paired positive candidate can pass only when evidence repeats across
  independent market-days.

Validation:

- `python -m pytest tests\market\test_mm_paper.py -q`

Related: items 44, 117, 163, 260, 275, 278.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - MARKET-DAY CLUSTER GATE LIVE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

