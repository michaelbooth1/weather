# 160. Early-Hour Model Skill Remediation To Positive Daily-First Gate [PARTIAL 2026-06-22 - GATE REFRESHED, PROOF BLOCKED]

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

2026-06-20 post-resume refresh: `promotion_refresh` now reruns to completion
inside daily refresh, and progress audit was regenerated afterward. The
candidate promotion verdict is still `BLOCK` with
`candidate_cutover_decision=DO_NOT_CUT_OVER`, while progress audit remains
`DIRECTIONAL` and `claim_allowed=False`. The current comparable-day summary is
still `1` positive-skill day, rolling daily-first skill
`-0.3334277590701413`, and `48` promotion-grade market-days. This keeps the
item partial: the hourly candidate evidence is useful, but it has not produced
an accepted candidate plus non-negative rolling daily-first proof.

Acceptance: a promotion candidate may clear this item only when its
candidate-specific hourly gate passes for the 00:00-08:00 window, daily-first
skill is non-negative over the required rolling window, and the promotion
report preserves the distinction between weather-model lift and market-aware
risk overlay.

## 2026-06-22 Positive Daily-First Gate

Added `weather.reporting.early_hour_positive_daily_first_gate` with schema
`early_hour_positive_daily_first_gate_v0.1`.

Artifacts:

- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`

Command:

`python -m weather.reporting.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md`

Result: **BLOCK** with 6 blockers. The gate now reconciles candidate hourly,
weak-slot, served-distribution, progress-audit, and daily-first trend evidence
before this item can close.

Passing evidence:

- Repaired candidate 10-minute weak-slot gate is `PASS` with
  `delta_vs_market=-0.0089`.

Current blockers:

- Candidate hourly early gate is `BLOCK`; early-hour Brier trails market by
  `+0.0048 > +0.0030`.
- Served-distribution contract is `BLOCK`; repaired evidence is
  `row_export_surrogate`, replay verdict is `BLOCK`, and cutover is
  `DO_NOT_CUT_OVER`.
- Rolling daily-first skill is still negative at `-0.2212`.
- Positive daily-first days are `1`; the gate requires `3`.
- Promotion-grade market-days are `36`; the gate requires `84`.
- Progress audit remains `DIRECTIONAL` and `claim_allowed=False`, with blockers
  for positive-skill day count, daily-first skill, market-day count,
  live-forward SLO, independent baseline evidence, and mixed runtime identity.

Remaining unblock: produce an accepted early-hour candidate whose hourly gate
passes, promote it through active replay-contract evidence, and rerun progress
audit until rolling daily-first skill is non-negative with enough positive days
and promotion-grade market-days.

## 2026-06-22 positive daily-first gate refresh

Regenerated the positive daily-first gate after refreshing the served-
distribution contract:

- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`

The refreshed gate remains `BLOCK` with `6` blockers. The repaired candidate
10-minute weak-slot gate is still the only passing acceptance dependency, with
weak-slot `delta_vs_market=-0.0089`.

Current blockers:

- `candidate_hourly_early_gate`: early-hour candidate Brier trails market by
  `+0.0048 > +0.0030`.
- `served_distribution_contract`: served-distribution evidence remains
  `row_export_surrogate`, replay verdict is `BLOCK`, and cutover is
  `DO_NOT_CUT_OVER`.
- `rolling_daily_first_non_negative`: rolling daily-first skill is still
  `-0.2212`.
- `positive_daily_first_days`: the gate requires `3` positive daily-first days;
  current evidence has `1`.
- `promotion_grade_market_days`: the gate requires `84` promotion-grade
  market-days; current evidence has `36`.
- `progress_claim_allowed`: progress audit remains `DIRECTIONAL` with
  `claim_allowed=False`, blocked by positive-day count, rolling daily-first
  skill, market-day count, live-forward SLO countability, missing independent
  baseline evidence, and mixed runtime identity.

No progress-audit claim was accepted here. Item 160 remains partial until a
served early-hour candidate clears the hourly gate and the daily-first trend
turns non-negative with enough countable evidence.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.broad_claim_gate`.
Acceptance evidence for this item must clear the packet broad-claim field; new
daily-first diagnostics stay diagnostic-only until they change that blocker.
