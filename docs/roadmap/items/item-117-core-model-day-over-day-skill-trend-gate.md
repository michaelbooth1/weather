# 117. Core Model Day-Over-Day Skill Trend Gate [COMPLETE 2026-06-17 - TREND CLAIM GATE LIVE]

Goal: make "is the core model improving day by day?" a strict generated claim,
not a manual interpretation of noisy progress reports.

Source: the 2026-06-17 audit of `daily_learning_report.md`,
`progress_audit_report.md`, `f_family_promotion_refresh_report.md`, and recent
model-history scoring. The latest artifacts show real directional progress:
the F-family candidate beats current replay by `-0.0015` Brier on both
aggregate and daily-first scoring, and 2026-06-16 was the first comparable
12-market day with positive model-vs-market Brier skill. But the broader
evidence is not yet promotion-grade: only 1 of the 11 comparable full-market
days from 2026-06-06 through 2026-06-16 had positive skill, and the 14-day
headline model still trails market Brier (`0.0510` model versus `0.0391`
market).

Why this matters: progress audit can currently say "yes, partially," but the
roadmap has no dedicated owner for preventing one strong day, row-multiplied
variant scores, or incumbent-relative lift from being described as hard
day-over-day core-model improvement.

## Design

1. Add a generated `core_model_trend_claim` section to progress audit and
   daily learning with statuses such as `UNPROVEN`, `DIRECTIONAL`, and
   `PROVEN`.
2. Separate comparable full-market days from partial, Toronto-only, or
   provisional-label days before computing trend statistics.
3. Report the exact daily sequence: model Brier, market Brier, model-minus-
   market gap, Brier skill, daily-first skill, final-top hit rate, sample size,
   and whether the day counts toward the trend claim.
4. Define promotion-grade trend thresholds: minimum independent market-days,
   minimum number of positive-skill days, non-negative rolling daily-first
   skill, no unresolved P0 collection blockers, and no row-multiplier-only
   evidence growth.
5. Make the generated report say what evidence would change the claim tomorrow,
   such as "need N additional complete full-market days with positive
   daily-first skill" or "blocked by live-forward SLO."

- [x] Add a strict trend-claim object to progress audit output.
- [x] Surface the trend claim and threshold failures in daily learning.
- [x] Exclude non-comparable partial/provisional days from day-over-day trend
  slope calculations by default.
- [x] Add tests for the June 17 pattern: directional positive slope, one
  positive day, but no hard day-by-day improvement claim.
- [x] Gate broad "core model is improving day by day" language on the generated
  claim status.

Acceptance: a daily audit can answer the improvement question from one generated
section, with hard numbers, comparable-day filtering, and an explicit
`PROVEN`/`UNPROVEN` status rather than relying on manual narrative judgment.

## Completion Notes

Implemented on 2026-06-17:

- `progress_audit.json` now includes `core_model_trend_claim` with status,
  `claim_allowed`, thresholds, threshold failures, directional signals, next
  evidence needed, and a daily sequence showing model Brier, market Brier,
  model-minus-market gap, Brier skill, daily-first skill, final-top hit rate,
  sample size, quality counts, and countability flags.
- The trend gate separates full-market directional days from stricter
  promotion-grade complete/manual-override days. Current evidence is
  `DIRECTIONAL`, not `PROVEN`: 11 comparable full-market days, 1 positive-skill
  day, rolling daily-first skill `-0.3300`, 48 promotion-grade market-days
  versus the 84-day threshold, live-forward SLO not countable, and variant rows
  grew without independent observations.
- `daily_learning.json` and `daily_learning_report.md` surface the same claim,
  threshold failures, and next evidence needed. A directional but unproven
  trend is a retrain input, not a permission to claim hard day-over-day
  improvement.

Verification:

- `.\venv\Scripts\python.exe -m pytest -q tests\reporting\test_progress_audit.py tests\reporting\test_daily_learning.py`
- `.\venv\Scripts\python.exe -m weather.reporting.progress_audit --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md`
- `.\venv\Scripts\python.exe -m weather.reporting.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md`
