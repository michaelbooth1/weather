# 69. Multi-Variant Shadow Harness And Experiment Governance [COMPLETE 2026-06-15 - LONG-FORM HARNESS LIVE]

Goal: run multiple model variants per location as paired, pre-registered shadow
forecasts without turning the promotion loop into noisy hyperparameter search.

Source: `docs/research/MULTI_VARIANT_SHADOW_TEST_DESIGN_2026-06-15.md`.
The research conclusion is that multi-variant testing is useful only when every
variant sees the same snapshots, source state, market prices, and settlement,
and when no-market weather variants stay separated from market-informed quote
variants.

Why this is missing: `pooled_candidate_replay` and `promotion_refresh` already
support one shadow candidate artifact plus the current-serving control. That is
enough for promotion gates, but not enough to collect paired counterfactuals for
several clearly different candidate hypotheses on the same active days.

Design:

The first implementation should be a reporting/governance harness over a
canonical long-form prediction table, not a refactor of every candidate trainer.
Each variant producer writes or exports rows with stable identity columns
(`variant_id`, `variant_family`, `market_id`, `target_date`, `snapshot_id`,
`band_key`), the candidate probability, baseline probabilities
(`current_probability`, `recorded_probability`, `market_yes`), the settled
outcome, and immutable metadata (`uses_market_features`, `is_control`,
`artifact_hash`, `postprocess_config_hash`, `experiment_start_date`). The
harness validates those rows, enforces the predeclared variant-count limit, and
emits JSON/Markdown reports plus a normalized long table.

The harness is deliberately separate from `promotion_refresh`: promotion still
selects at most one candidate per market, while the multi-variant report decides
which variant has earned the right to become that single candidate. This keeps
current serving safe and lets items 70-73 plug in one variant at a time.

Scoring uses two levels:

- Primary: daily-first equal-day Brier/log-loss deltas, averaged by
  `variant_id` and market-day so correlated band rows do not dominate.
- Secondary: row-weighted aggregate Brier/log-loss, ECE, market slices, cutoff
  slices, and track separation by `uses_market_features`.

- [x] Define a stable `variant_id` / `variant_family` schema that records
  whether a variant uses market features, its artifact hash, postprocess config
  hash, and frozen experiment start date.
- [x] Add a multi-variant shadow prediction table keyed by market, snapshot,
  band, and variant, with one row per candidate probability and no serving-side
  effect.
- [x] Extend replay/reporting to pivot the long-form table into paired deltas
  versus current serving, recorded tape, and market prices.
- [x] Score daily-first equal-day Brier as the primary promotion evidence, with
  row-weighted aggregate Brier kept as secondary diagnostics only.
- [x] Keep no-market and market-informed tracks separate in reports, gates, and
  dashboard labels so CLOB/price-aware variants cannot support independent
  weather-model edge claims.
- [x] Enforce predeclared experiment limits: at most four non-control shadow
  variants per family in a live-forward window, frozen before collection, with
  no winner picked from same-day retuning.
- [x] Keep `promotion_refresh` promoting at most one candidate per market while
  the multi-variant report decides which variant graduates into that single
  promotion slot.

Implementation update (2026-06-15): `weather.reporting.multi_variant_shadow`
now owns the long-form harness and `src.multi_variant_shadow` exposes the
compatibility CLI. It reads CSV/JSON/JSONL prediction rows, normalizes them to
schema `multi_variant_shadow_v0.1`, writes
`data/backtest/multi_variant_shadow_long.csv`, and emits JSON/Markdown reports
with daily-first scores, aggregate diagnostics, per-market slices, track
separation, metadata warnings, and the four-non-control-variant governance
limit. The harness does not change serving or promotion behavior; it is the
evidence layer that items 70-73 can feed.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\reporting\test_multi_variant_shadow.py -q`
  passed (`5` tests).
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py -q`
  passed (`6` tests).
- Scoped schema audit passed:
  `.\venv\Scripts\python.exe -m src.schema_registry audit --strict --paths src\weather\reporting\multi_variant_shadow.py src\weather\schema_registry.py`.
- Full schema audit currently fails on unrelated dirty worktree literal
  `item27_feature_value_gate_v0.1` in
  `src/weather/calibration/feature_model.py`; item 69's new schema is
  registered and clean in the scoped audit.

Acceptance: the project can collect and replay multiple candidate probabilities
per location/day with paired evidence, explicit no-market versus market-informed
separation, and promotion reports that cannot mistake correlated band rows or
retuned variants for independent out-of-sample proof.
