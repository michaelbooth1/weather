# 220. CLOB Overlay Quote-Risk Lane Separation [COMPLETE 2026-06-22 - CLOB QUOTE-RISK LANE SEPARATED]

Goal: keep market-informed CLOB overlays out of weather-only model promotion
claims while still using them for quote-risk sizing, permission, or kill
switches where coverage and taxonomy gates are valid.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
`clob_overlay_raw_oof` is the only tested variant that closes the bottom-cohort
gap, improving Brier by `-0.0228` versus current and beating market by
`-0.0017`. It uses market features and only covers 19,668 rows, while the
no-market candidate still trails market by `+0.0181` in the bottom cohort.

Why this matters: mixing market-informed overlay performance into no-market
weather-model promotion would overstate core model skill. The same overlay can
still be valuable for trading permission if it is labeled as quote-risk
evidence.

## Design

1. Add an explicit claim lane to reports: `weather_only_core_model` versus
   `market_informed_quote_risk`.
2. Require CLOB overlay reports to show coverage, taxonomy, spread/liquidity
   thresholds, and whether a row is eligible for quote-risk use.
3. Allow CLOB overlay outputs to affect sizing or kill switches only through
   the market-informed lane.
4. Add report assertions that weather-only promotion summaries cannot include
   market-informed Brier deltas.

- [x] Add claim-lane metadata to CLOB overlay shadow outputs.
- [x] Wire eligible CLOB overlay evidence into quote-risk permission only.
- [x] Add tests that market-informed rows are excluded from weather-only
  promotion claims.
- [x] Regenerate CLOB coverage and active shadow reports with the claim lanes.

## Completion Notes

CLOB shadow exports now carry explicit lane metadata:
`claim_lane`, `counts_toward_weather_model_promotion`,
`quote_risk_eligible`, and `quote_risk_gate_reason`. Weather-only rows default
to `weather_only_core_model`; CLOB rows are `market_informed_quote_risk`, never
count toward weather-only promotion, and become quote-risk eligible only when
the taxonomy gate allows the row and the overlay probability is present.

`pooled_candidate_replay_latest_report.md` now renders the microstructure lane,
coverage threshold, taxonomy gate policy, spread/liquidity threshold note, and
quote-risk eligible row count. The regenerated CLOB shadow CSV has `67,111`
market-informed quote-risk rows and `71` quote-risk eligible rows.

The canonical active-shadow report now includes a `Claim Lane Separation`
section. The regenerated `data/backtest/active_variant_shadow_report.md` shows
`67,111` CLOB rows in `market_informed_quote_risk`, `0` weather-promotion rows
for that lane, and `71` quote-risk eligible rows; weather-only rows remain in
`weather_only_core_model`.

Promotion refresh now reports `model_skill_claims` separately for
`weather_only_core_model` and `market_informed_quote_risk`. Only the
weather-only claim carries the core Brier delta; the market-informed lane is
marked as quote/permission evidence and does not count toward core model skill.
The old `market_informed_clob_overlay` lane label is absent from regenerated
promotion and replay artifacts.

Verification:

- `python -m pytest tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py tests\reporting\test_multi_variant_shadow.py tests\operations\test_daily_refresh.py::TestDailyRefresh::test_active_variant_shadow_step_writes_canonical_outputs_and_missing_ids tests\market\test_mm_paper.py::TestMMPaper::test_clob_overlay_gate_feeds_market_informed_known_edge_permissions tests\market\test_mm_policy.py::TestMmPolicy::test_clob_overlay_market_informed_record_does_not_enable_edge_quote -q`
- `python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl --out data\backtest\pooled_candidate_replay_latest_report.md --json-out data\backtest\pooled_candidate_replay_latest.json --replay-report data\backtest\pooled_candidate_current_replay_latest_report.md --disable-long-job-guard`
- `python -m weather.reporting.candidate_lifecycle.active_variant_shadow_refresh data\backtest\item50_pooled_candidate_shadow_variants.csv data\backtest\item70_exact_winner_shadow_variants_full.csv data\backtest\item71_dynamic_source_shadow_variants_full.csv data\backtest\conservative_bridge_shadow_variants.csv data\backtest\item82_miami_fallback_shadow_variants.csv data\backtest\clob_overlay_shadow_variants.csv data\backtest\item35_density_full_shadow_variants.csv`
- `python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_candidate_replay_latest.json --precomputed-candidate-report data\backtest\pooled_candidate_replay_latest_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --skip-serving-gauntlet`
- `python -m weather.reporting.candidate_lifecycle.shadow_ab_monitor --promotion-refresh data\backtest\f_family_promotion_refresh.json --candidate-replay data\backtest\pooled_candidate_replay_latest.json --json-out data\backtest\shadow_ab_monitor.json --report-out data\backtest\shadow_ab_monitor_report.md`

Acceptance: CLOB overlays can inform quote-risk controls only when coverage and
taxonomy gates pass, and no weather-only promotion report can count
market-informed rows as core model skill.

Related: items 38, 72, 144, 156, 218.
