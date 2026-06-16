# 83. Shadow Evidence Accounting And Active Variant Registry [COMPLETE 2026-06-16 - ACTIVE EVIDENCE ACCOUNTING LIVE]

Goal: make every shadow and promotion report distinguish scored variant rows
from independent evidence, and make active versus archived variants explicit.

Source: `docs/research/MODEL_VARIANT_AUDIT_2026-06-16.md`. The audit found
that the multi-variant harness is useful for paired comparison, but most
current variants rescore the same 67,430 market/date/snapshot/band observations
instead of adding new independent labels.

Why this is missing: the item 69 long-form table correctly multiplies rows by
variant, but downstream monitor and promotion summaries can still make raw row
volume look like new evidence. Old alpha, smoke, and full replay files also sit
beside active candidates, which can inflate perceived experiment breadth.

- [x] Add unique observation counters (`market_id`, `target_date`,
  `snapshot_id`, `band_key`) beside raw/scored row counts in multi-variant
  shadow reports, `shadow_ab_monitor`, promotion refresh summaries, and any
  dashboard/Markdown report that claims experiment coverage.
- [x] Add an active variant registry or manifest that classifies variants as
  active, control, archived, smoke, alpha, market-informed, or policy-only.
- [x] Require headline comparisons to show active variant count separately from
  archived historical artifacts, and exclude archived variants unless a report
  explicitly asks for historical context.
- [x] Backfill current item 70, 71, 72, 73, and 82 exports into the registry
  metadata so existing reports have a known lifecycle state.
- [x] Add tests proving raw row count cannot be used as the independent
  evidence count when several variants share the same observation key.

Acceptance: shadow, monitor, and promotion reports make it impossible to
confuse scored variant rows with independent market observations, and active
versus archived variants are auditable from generated artifacts.

Completion update 2026-06-16:

- Added `config/model_variant_registry.json` with active, control, archived,
  alpha/smoke, no-market, market-informed, and policy-only lifecycle metadata.
- `weather.reporting.multi_variant_shadow` now reports `scored_rows`,
  `unique_observation_count`, snapshots, bands, settled labels, row multiplier,
  active headline variant counts, archived/historical counts, and active-only
  track summaries.
- `shadow_ab_monitor` and `promotion_refresh` now surface the same candidate
  replay evidence counters. Current generated evidence:
  `data/backtest/shadow_ab_monitor_report.md` shows 67,430 scored rows and
  67,430 unique observations; `data/backtest/f_family_promotion_refresh_report.md`
  shows 67,430 rows, 67,430 unique observations, 6,130 snapshots, 44
  market-days, and row multiplier `1.0000`.
- Regenerated `item70_71_full_multi_variant_shadow_report.md` with registry
  accounting: `OK`, 134,860 scored rows, 67,430 unique observations, two active
  headline variants, zero warnings, and zero errors.
- Tests:
  `.\venv\Scripts\python.exe -m pytest tests\reporting\test_multi_variant_shadow.py tests\reporting\test_variant_evidence_growth.py tests\reporting\test_shadow_ab_monitor.py tests\calibration\test_promotion_refresh.py tests\operations\test_daily_refresh.py -q`
  passed (`38` tests).
