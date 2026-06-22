# 221. Market Source/Missingness Location Gates [COMPLETE 2026-06-22 - MARKET SOURCE/MISSINGNESS GATE LIVE]

Goal: add market-by-source and market-by-missingness gates so candidate
promotion cannot pass by averaging away weak bottom-location data states.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
Bottom locations remain `+0.0203` Brier worse than market even on `all_fresh`
rows, while failed WU history increases the gap to `+0.0314`. The same
missingness hash can be good in top markets and harmful in bottom markets:
`469d0c0f...` is `-0.0039` vs market in the top cohort but `+0.0256` in the
bottom cohort. Source-state dynamic ablation improves aggregate Brier but still
leaves NYC `+0.0179` and Seattle `+0.0213` vs market.

Why this matters: source freshness and missingness are not global effects.
Promotion needs to know whether the candidate works in the exact market/data
states that drive the location gap.

## Design

1. Decode frequent `feature_missingness_hash` values into the underlying missing
   feature sets.
2. Add `market_id x source_freshness_state x feature_missingness_hash` and
   `market_id x forecast_source_count_bucket` tables to active candidate
   reports.
3. Add market-level promotion blockers for all-fresh, two-source, and high
   impact missingness states.
4. Preserve source-state ablation as a diagnostic, not a promotion pass, until
   weak markets clear market tolerance.

- [x] Implement missingness-hash decoding in the reporting path.
- [x] Add the new market/source/missingness slices to active shadow or promotion
  refresh output.
- [x] Add blocker rules for Seattle, NYC, and Miami all-fresh/two-source slices.
- [x] Add fixtures that prove the same hash can pass in one market and block in
  another.

## Completion Notes

Promotion refresh now builds `source_missingness_location_gate` from the active
candidate shadow-variant CSV. The gate decodes frequent
`feature_missingness_hash` values into missing feature names, emits
`market_id x source_freshness_state`, `market_id x forecast_source_count_bucket`,
and `market_id x feature_missingness_hash` tables, and feeds any blocker into
promotion readiness as `source_missingness_location_gate`.

The regenerated `data/backtest/f_family_promotion_refresh.json` blocks the
active candidate with `15` bottom-location blockers across Miami, NYC, and
Seattle. The report now shows the decoded bottom-market source freshness,
two-source, and feature-missingness slices; the first blocker is Miami
all-fresh at `+0.0215` Brier versus market tolerance `0.0030`.

Fixtures cover a shared missingness hash that blocks in Miami while passing in
Atlanta, plus the readiness blocker category and rendered report section.

Verification:

- `python -m pytest tests\calibration\test_promotion_refresh.py tests\operations\test_schema_registry.py -q`
- `python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_candidate_replay_latest.json --precomputed-candidate-report data\backtest\pooled_candidate_replay_latest_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --skip-serving-gauntlet`

Acceptance: promotion reports show decoded market/source/missingness slices and
block a candidate if bottom locations fail market tolerance in all-fresh,
two-source, or high-impact missingness states.

Related: items 48, 53, 105, 136, 208, 218.
