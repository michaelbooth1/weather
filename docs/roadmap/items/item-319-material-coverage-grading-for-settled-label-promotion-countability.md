# 319. Material Coverage Grading For Settled-Label Promotion Countability [COMPLETE 2026-06-25 - MATERIAL COVERAGE COUNTABILITY LIVE]

Goal: stop the binary zero-gap intraday-coverage gate from permanently
disqualifying settled-day labels whose settlement value is already confirmed,
so the settled-day analysis barrier can reach `promotion_refresh` and the
live-forward gate instead of fail-closing forever on immaterial snapshot gaps.

Source: 2026-06-25 investigation of why `promotion_refresh` never runs
in-pipeline. A clean `daily_refresh` re-run on current code (after the
`utc_now` step fix and an exchange-economics snapshot publish) passed 17/18
steps, but `settled_day_analysis_barrier` still BLOCKs `target_date=2026-06-24`
because label countability is `diagnostic_only`: of 237 settled labels,
`54 FINALIZED + 179 PROVISIONAL + 2 SOURCE_DISAGREEMENT + 2 SOURCE_REVISION`,
i.e. 183 promotion-blocked. The settlement audit
(`data/backtest/settlement_source_revision_audit.json`) and the labels CSV
(`data/backtest/market_day_labels.csv`) show the 179 PROVISIONAL labels are
blocked purely by `quality_grade=partial`, which the settlement audit then
classifies PROVISIONAL (`settlement_source_audit._classify`: any
`quality_grade != "complete"` -> PROVISIONAL, and `proof_grade_label` requires
`status == "FINALIZED"`).

Current evidence (root cause, not the three suspected causes):

- It is NOT a confirmation-window timing issue: the PROVISIONAL labels span
  `2026-05-30 -> 2026-06-24` with `finalization_lag_hours` up to ~350h (~14.6
  days); they are long past any settlement window.
- It is NOT a settlement-source live-fetch gap: the authoritative source is
  fetched and agrees - e.g. atlanta 2026-06-10 has
  `source_buckets={canonical_ledger: 88, wu_final: 88}`,
  `reconciliation_status=match`, `source_disagreement_count=0`.
- It is NOT the missing-lineage tracking: both FINALIZED and PROVISIONAL labels
  carry the identical `lineage_missing_with_reason_count=2`
  (`weather_com_max_since_7`, `market_resolution`) and `lineage_status=PASS`.
- The real discriminator is intraday snapshot coverage. In
  `weather.backtesting.settlement_ledger.build_label`,
  `coverage = coverage_summary(...)` and
  `quality_grade(..., collection_clean=coverage_clean)`. `quality_grade`
  returns `partial` when `snapshot_count < 6 or not collection_clean`, and
  `weather.collection.collection_health.coverage_summary` sets
  `clean = n >= 2 and not gaps and covers_afternoon`. So a single gap above the
  `interval_minutes=10, tolerance=1.5` threshold (>~15 min) anywhere in the
  afternoon window, or any incomplete afternoon bracketing, flips the whole
  market-day to `partial`.
- The 179 PROVISIONAL labels have healthy tapes (`snapshot_count` 29-232, all
  >= the 6 floor) and `coverage_reason` values that are overwhelmingly minor:
  "1 gap(s), max 36 min", "2 gap(s), max 46 min", single 20-30 min gaps. The 54
  FINALIZED labels all have `coverage_reason=ok`. A handful of partials have
  genuinely large gaps ("2 gap(s), max 512 min", "afternoon window not fully
  covered"), but the large majority are immaterial.

Why this matters: settlement correctness (the daily-high bucket) is established
independently of intraday cadence and is already confirmed/matched for these
days, yet the binary zero-gap coverage rule marks 179/237 (76%) of settled
labels non-countable. Because the intraday tape for historical days cannot be
re-collected, those labels are permanently `partial`, so
`settled_day_analysis_barrier` (item 305) blocks `promotion_refresh` and the
`live_forward` readiness gate indefinitely. This is the actual gate standing
between a market-beating model (item 224 repair, `delta_vs_market=-0.0293` on
the consistent corpus) and serving - not the model, the corpus, or item-312
supervisor code.

Why it is not already covered: item 25 built the coverage-aware partial grading
and the "exclude/downweight partial days" policy - it is the origin of this
gate, not a fix for its over-strictness. Item 212 makes cadence a graded
confidence and trading-permission haircut for live-forward serving, a different
consumer than the settled-label promotion-countability grade. Item 305 enforces
the barrier that fail-closes on partial labels and propagates partial-label
status, which is correct given the current grade, but it does not change the
underlying grading. No item makes settled-label promotion countability a
material/graded decision that distinguishes confirmed-settlement correctness
from intraday-coverage completeness.

## Design

1. Add a material-coverage grade for settled labels that separates settlement
   correctness (confirmed bucket, reconciled source) from intraday-coverage
   completeness, instead of collapsing both into a single binary `complete`.
2. Replace the binary `clean = not gaps` rule for promotion countability with a
   materiality test: e.g. `capture_ratio` above a threshold, `max_gap_minutes`
   below a material bound, and no gap overlapping the peak-heating window that
   determines the settlement bucket. Keep the strict `ok` definition available
   for any consumer that needs zero-gap tapes.
3. Make `settled_day_analysis_barrier` / label countability count a label as
   promotion-countable when settlement is confirmed (reconciled, lineage PASS,
   no disagreement) and coverage is materially complete, while still excluding
   labels with genuinely decisive gaps (e.g. the 512-min / afternoon-not-covered
   cases).
4. Preserve a transparent downgrade trail: record the material-coverage grade,
   the reason, and which window the gap fell in, so promotion evidence stays
   auditable and the strict-`complete` count is still reported.
5. Backfill the grade for existing labels and confirm the barrier reaches
   `promotion_refresh` for a recent settled target date once materially-complete
   labels count.

- [x] Add a material-coverage grade that separates settlement correctness from
  intraday-coverage completeness, with thresholds for capture ratio, max gap,
  and settlement-window overlap.
- [x] Make settled-label promotion countability use the material grade while
  still blocking labels with decisive gaps, keeping strict-`complete` reported.
- [x] Update `settled_day_analysis_barrier` label countability to consume the
  material grade and re-evaluate `promotion_countable` for a recent target date.
- [x] Record and report the material grade, reason, and gap window for audit.
- [x] Add tests proving a confirmed-settlement day with a single minor gap is
  promotion-countable while a day with a decisive afternoon gap is not, and that
  the barrier reaches `promotion_refresh` once materially-complete labels count.

## Completion Notes

Completed on 2026-06-25.

Implemented material coverage as an additive label contract in
`weather.backtesting.settlement_ledger`: strict `quality_grade` remains
zero-gap, while `material_coverage_grade`, material gap-window details, and
`promotion_countable` record whether a reconciled settled label can count for
promotion. The material gate requires the afternoon settlement window to be
covered, capture ratio >= 80%, max gap <= 60 minutes, and peak-window gaps <=
45 minutes.

`settled_day_analysis_barrier` now consumes material promotion-countability
when available, reports strict partial counts separately, and preserves the old
strict partial-label fallback for older labels without the new fields. The
settled-day freshness and daily-learning summaries now carry material coverage
counts and promotion-countable totals for audit.

Verification:

- `.\\venv\\Scripts\\python.exe -m pytest tests\\market\\test_market_day_labels.py tests\\operations\\test_daily_refresh.py tests\\operations\\test_settled_day_freshness.py tests\\reporting\\test_daily_learning.py tests\\reporting\\test_model_scoring_liveness.py -q`
  - 115 passed
- `.\\venv\\Scripts\\python.exe -m pytest tests\\operations\\test_nightly_retrain.py tests\\reporting\\test_daily_progress_ledger.py -q`
  - 18 passed

Acceptance: a settled-day label whose settlement bucket is confirmed and
reconciled but whose intraday tape has only minor, non-decisive gaps is
promotion-countable, the `settled_day_analysis_barrier` reaches
`promotion_refresh` for a recent settled target date instead of fail-closing on
the binary zero-gap rule, labels with genuinely decisive coverage gaps remain
non-countable, and the material grade plus reason is recorded and reported for
audit, proven by tests.

Related: items 20, 25, 157, 161, 212, 224, 305, 312, 315.
