# 160. Early-Hour Model Skill Remediation To Positive Daily-First Gate [PARTIAL 2026-06-20 - CANDIDATE GATE PASSES, CURRENT GATE STILL BLOCKED]

Goal: close the early-hour model gap that blocks promotion despite directional
all-day progress.

Source: the latest hourly model performance gate. Early-hour model Brier trails
market by `0.0159`, above the `0.0030` tolerance, and early-hour log loss trails
market by `0.1693`, above the `0.0100` tolerance. The progress audit remains
`DIRECTIONAL` with `claim_allowed=False`: only 1 positive-skill comparable day,
rolling daily-first skill `-0.3334`, and current headline skill still negative.

Why this matters: aggregate progress can hide a timing failure. A model that is
competitive late in the day can still be unsafe for early market-making,
promotion, or broad improvement claims if the 00:00-08:00 window remains worse
than market.

## Design

1. Keep the current-serving hourly performance gate blocking until a candidate
   proves early-hour improvement with candidate-specific hourly evidence.
2. Separate no-market weather-model remediation from market-aware risk overlays.
3. Prioritize forecast-centering/current-max validation candidates for the
   early window, because market-blend improvements cannot prove weather-model
   edge.
4. Add daily-first and early-hour gates to candidate promotion reports so a
   candidate cannot pass only on aggregate Brier.
5. Track per-market early-hour blockers to distinguish one-market failures from
   fleet-wide early-window calibration problems.

- [x] Produce a candidate hourly-performance report for the next early-hour
  remediation candidate against the current corpus.
- [x] Add per-market early-hour Brier/log-loss deltas to the remediation
  registry and daily learning.
- [x] Require early-hour candidate Brier/log-loss to clear tolerance before it
  can mitigate the current-serving hourly blocker.
- [x] Keep market-aware overlays classified as quote/risk evidence, not
  no-market promotion evidence.
- [ ] Rerun progress audit after each accepted early-hour candidate to update
  rolling daily-first skill and positive-skill day counts.

## 2026-06-20 Update

Implemented the missing tracking surface rather than relaxing the blocker.
`weather.reporting.hourly_model_performance` now adds
`remediation_registry.early_hour_market_deltas` with per-market early-hour
Brier/log-loss deltas, blocking gates, rows, days, snapshots, and winner
probabilities. `weather.reporting.daily_learning` carries those rows into the
scorecard, report, and learnings.

Current generated evidence:

- Current-serving hourly gate remains `BLOCK` with 2 blockers.
- All 12 markets are early-hour blocked by both Brier and log-loss regression.
  Worst current-serving Brier deltas are `seattle=-0.0393`, `nyc=-0.0251`,
  `austin=-0.0196`, `toronto=-0.0183`, and `miami=-0.0178`.
- `item147_time_split_alpha` candidate-hourly gate is `PASS` with 44
  early-hour market-days, early delta vs market `-0.0008`, and early log-loss
  delta vs market `-0.0027`.
- Promotion-readiness tests verify that only a matching candidate-hourly gate
  `PASS` can mitigate the current-serving hourly blocker, and that
  market-informed candidates remain blocked as core model-promotion evidence.

Remaining blocker: do not close this item until progress audit shows
non-negative rolling daily-first skill after an accepted candidate and the full
promotion report is regenerated from a successful promotion refresh.

Acceptance: a promotion candidate may clear this item only when its
candidate-specific hourly gate passes for the 00:00-08:00 window, daily-first
skill is non-negative over the required rolling window, and the promotion
report preserves the distinction between weather-model lift and market-aware
risk overlay.
