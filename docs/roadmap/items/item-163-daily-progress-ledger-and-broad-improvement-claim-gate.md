# 163. Daily Progress Ledger And Broad Improvement Claim Gate [COMPLETE 2026-06-20 - LEDGER AND CLAIM GATE LIVE, CLAIM BLOCKED]

Goal: create one durable daily progress row after daily refresh so improvement
claims use the same model, evidence, operations, and trading gates every day.

Source: the June 20 audit recommendation. The current evidence is spread across
`progress_audit`, `daily_learning`, `fleet_observability`,
`snapshot_evaluation`, `promotion_refresh`, trading reports, and raw loop
diagnostics. The project can say it is directionally improving, but broad model
improvement remains unproven until the claim gates all pass.

Why this matters: without one daily ledger, progress discussions drift between
model metrics, data availability, operational health, and trading anecdotes.
The ledger should make the north-star claim binary and auditable while still
preserving directional sub-metrics.

## Design

1. Append one row after daily refresh to a machine-readable daily progress
   ledger, even when daily refresh is blocked.
2. Source model fields from progress audit and promotion refresh:
   `claim_allowed`, rolling daily-first Brier skill, positive-skill days,
   model-minus-market gap slope, candidate delta vs current, and candidate
   delta vs market.
3. Source evidence fields from labels and promotion corpus: complete labels,
   promotion-grade market-days, corpus snapshots, and independent evidence
   baseline status.
4. Source operations fields from fleet observability: fleet status,
   live-forward SLO status, snapshot gap count/max gap, source-status blocked
   free/headroom.
5. Source trading fields from market-making and taker reports: evidence mode,
   countable markets, quote rows, live-trade permission rows, fills, P&L, and
   root-cause class.
6. Compute a single broad-improvement claim gate.

- [x] Define `daily_progress_ledger_v0.1` as JSONL and CSV.
- [x] Add the ledger writer to daily refresh after daily learning.
- [x] Make the row append even when the run status is `error`, with blockers
  and missing artifacts explicit.
- [x] Add a Markdown rollup showing 7-day and 14-day trends for the fields
  above.
- [x] Teach progress audit to consume the ledger or cross-check it.

2026-06-20 update: `weather.reporting.daily_progress_ledger` writes
`data/backtest/daily_progress_ledger.jsonl`,
`data/backtest/daily_progress_ledger.csv`,
`data/backtest/daily_progress_latest.json`, and
`data/backtest/daily_progress_ledger_report.md`. The writer is wired into
daily refresh finalization after daily learning, records blockers on error, and
upserts by `run_date` so reruns keep exactly one daily row. Progress audit now
loads `daily_progress_latest.json` and renders a cross-check section.

Latest generated row: `run_date=2026-06-20`,
`broad_improvement_claim_allowed=false`,
`model_rolling_daily_first_brier_skill=-0.3334277590701413`,
`model_positive_skill_days=1`, `evidence_promotion_grade_market_days=48`,
`ops_live_forward_slo_status=BLOCK`,
`evidence_independent_baseline_status=MISSING`,
`ops_snapshot_gap_count=71`, `ops_source_status_blocked_markets=0`,
`ops_disk_preflight_status=PASS`, `ops_disk_headroom_bytes=128886111744`,
`trading_mm_evidence_mode=operator_drill`,
and `trading_taker_quality_status=SAMPLE_PENDING_NEGATIVE_LATEST`.

Current broad-improvement claim failures are:
`core_model_trend_claim_not_allowed`, `positive_skill_days_below_3`,
`rolling_daily_first_skill_negative`,
`promotion_grade_market_days_below_84`, `live_forward_slo_not_pass`, and
`independent_baseline_missing`.

Acceptance: each daily refresh produces exactly one progress ledger row with
model, evidence, operations, and trading metrics. The row sets
`broad_improvement_claim_allowed=true` only when all of these are true:
at least 3 positive-skill comparable days, rolling daily-first skill is
non-negative, at least 84 promotion-grade market-days exist, live-forward SLO
is `PASS`, and independent baseline evidence is present.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - LEDGER AND CLAIM GATE LIVE, CLAIM BLOCKED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

