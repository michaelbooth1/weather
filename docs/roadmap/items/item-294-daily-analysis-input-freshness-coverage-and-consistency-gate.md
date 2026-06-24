# 294. Daily-Analysis Input Freshness, Coverage, And Cross-Artifact Consistency Gate [OPEN 2026-06-24 - INPUTS CONSUMED WITHOUT FRESHNESS, COVERAGE, OR CONSISTENCY CHECKS]

Goal: stop the daily analysis from drawing conclusions from a stale, partial, or
internally inconsistent set of upstream artifacts. Validate every input's
freshness against the run date, score input coverage, and assert cross-artifact
invariants before emitting learnings or readiness flags.

Source: 2026-06-24 audit of the daily analysis script. `daily_learning.load_inputs`
reads ~21 artifacts and `_artifact_record` captures each input's
`generated_at_utc` (`src/weather/reporting/daily/daily_learning.py:95,135`), but
`_build_learnings` never compares those timestamps to `run_date` or to each
other, so yesterday's `promotion_refresh` sitting next to today's
`fleet_observability` is consumed as current. A missing artifact silently becomes
`{}` and yields no learnings from that source, and `daily_learning` has no
input-coverage check (the only gap check is `daily_flow_analysis`'s narrow
five-input `_add_artifact_gap_actions`). There is also no invariant check that
the inputs agree, for example promotion corpus `market_day_count` versus settled
label `total`, or `candidate_brier - current_brier` versus the reported
`delta_vs_current`.

Why this matters: the daily learning artifact feeds retrain and promotion
readiness and the operator runbook. Mixing stale and fresh inputs, or silently
losing a source, produces confident but wrong conclusions, and a silent upstream
sign/definition drift (delta convention flips) would invert the promotion logic
with no signal.

Why it is not already covered: item 120 enforces settled-day finalization
freshness, item 199 recovers stale daily rollups, and item 291 reconciles the
schema registry, but none validate the freshness, coverage, or mutual
consistency of the full daily-analysis input set at aggregation time. The
existing `rollup_freshness` covers only specific rollups.

## Design

1. Add a per-artifact freshness check comparing each input's `generated_at_utc`
   to the run date and to the newest input, emitting a WARN/BLOCK learning when
   an input is older than a configured skew threshold.
2. Add an input-coverage score to `daily_learning` ("present X/N; missing: [...]")
   and treat a configured set of critical missing inputs as WARN/BLOCK rather
   than silently producing no learnings.
3. Add cross-artifact consistency invariants and emit a P0 "input inconsistency"
   learning when they fail: corpus `market_day_count` versus settled label
   `total`; `trading_evidence` run date versus `run_date`; and
   `candidate_brier - current_brier` approximately equal to `delta_vs_current`
   (and the same for market) within tolerance, to catch sign/definition drift.
4. Surface freshness, coverage, and consistency status in the daily learning and
   daily flow reports, and fail the overall status closed when a critical input
   is stale, missing, or inconsistent.

- [ ] Add per-artifact freshness validation against run date with a configurable
  skew threshold.
- [ ] Add an input-coverage score and critical-missing-input fail-closed
  handling to `daily_learning`.
- [ ] Add cross-artifact consistency invariants (corpus vs labels, run-date
  alignment, Brier delta sign-convention) with a P0 inconsistency learning.
- [ ] Surface freshness/coverage/consistency in the reports and overall status.
- [ ] Add tests with stale, missing, and inconsistent input sets.

Acceptance: the daily analysis reports input coverage and per-artifact
freshness, fails closed when a critical input is stale/missing/inconsistent, and
emits a P0 inconsistency learning when corpus-vs-label counts, run-date
alignment, or the Brier delta sign-convention invariant is violated, proven by
tests with stale/missing/inconsistent fixtures.

Related: items 31, 120, 157, 163, 199, 291.
