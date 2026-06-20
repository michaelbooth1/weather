# 139. Scheduled Active Variant Shadow Refresh [PARTIAL 2026-06-18 - REGISTRY SOURCES OK, INLINE EXECUTION REMAINS]

Goal: make the daily refresh generate a fresh canonical multi-variant shadow
artifact for the active registry instead of reading a stale prebuilt bakeoff
CSV.

Source: 2026-06-18 model-variant data audit. `daily_refresh` currently runs
`model_variant_evidence_growth`, but the default input is the preexisting
`item86_no_market_bakeoff_multi_variant_shadow_long.csv`. If that file is
missing the step skips; if it is stale, the run still reports against stale
variant evidence. The latest local evidence showed `ALERT`: scored variant rows
grew by 269,720 while unique observations and market-days grew by 0.

Why this matters: model improvement depends on knowing how every active
variant performed on the freshest settled corpus. Reusing historical bakeoff
exports makes the learning loop look busier than it is and can mask that no new
independent evidence was collected.

## Design

1. Add a scheduled `active_variant_shadow` step before
   `model_variant_evidence_growth` in `weather.operations.daily_refresh`.
2. Load `config/model_variant_registry.json` and select active variants by
   lifecycle, track, and role.
3. Run/export each active variant against the current promotion corpus or
   replay inputs with stable observation keys.
4. Combine the exported rows through `weather.reporting.multi_variant_shadow`
   with shared-control deduplication enabled.
5. Write canonical outputs under `data/backtest`:
   `active_variant_shadow_long.csv`, `active_variant_shadow.json`, and
   `active_variant_shadow_report.md`.
6. Make `model_variant_evidence_growth` consume the new canonical long table by
   default, with explicit CLI overrides retained for research comparisons.

- [x] Add the daily-refresh runner and CLI flags for active variant shadow
  refresh.
- [ ] Generate active no-market and market-informed shadow rows from the
  current corpus without relying on item-specific historical CSVs.
- [x] Deduplicate shared controls before scoring.
- [x] Preserve current manual `--variant-evidence-current` and
  `--variant-evidence-baseline` override behavior.
- [x] Add tests proving a daily refresh writes fresh active-variant outputs and
  evidence growth reads them by default.

Acceptance: a normal daily refresh produces a fresh active-variant shadow long
table from the current corpus, evidence-growth reporting uses that table by
default, and stale item 86 artifacts are no longer part of the scheduled
evidence path unless explicitly requested.

## 2026-06-18 implementation update

Added `weather.reporting.active_variant_shadow_refresh`, schema
`active_variant_shadow_refresh_v0.1`, and wired a new
`active_variant_shadow` step into `weather.operations.daily_refresh` before
`model_variant_evidence_growth`. The scheduled evidence-growth default now
reads `data/backtest/active_variant_shadow_long.csv`; manual
`--variant-evidence-current` and `--variant-evidence-baseline` overrides are
still preserved.

Generated from the current available June 18 active exports:

- `data/backtest/active_variant_shadow_long.csv`
- `data/backtest/active_variant_shadow.json`
- `data/backtest/active_variant_shadow_report.md`

The generated active-shadow status is `BLOCK`, not `OK`: it canonicalized
221,958 rows across 67,430 unique observations and deduplicated 67,430 shared
control rows, but only three active registry variants were present:
`clob_overlay_gated_taxonomy`, `clob_overlay_raw_oof`, and
`conservative_bridge_policy_v0_1`.

The active registry variants still missing from the canonical output are:

- `item50_pooled_forecast_v3_candidate`
- `pooled_continuous_density_hgb_v0_1`
- `pooled_f_candidate_miami_current_fallback_v0_1`
- `pooled_f_dynamic_source_state_v0_1`
- `pooled_f_exact_winner_catchup_v0_1`

Refreshed `data/backtest/model_variant_evidence_growth.json` and report now use
`data/backtest/active_variant_shadow_long.csv` as current evidence. The result
is still `ALERT`: scored rows increased by 87,098 versus the baseline, while
unique observations and market-days increased by 0, so broad promotion claims
remain blocked.

Follow-up after item 142: registry export contracts now exist for every active
headline variant and the no-argument active-shadow refresh resolves the
registry paths itself. A refreshed run wrote `active_variant_shadow_long.csv`
with status `OK`, 8 active variants reported, 0 missing active variants,
568,557 canonical rows, 76,879 unique observations, and 51 market-days.
`model_variant_evidence_growth` now reports `WARN` with the independent
evidence SLA passing.

Remaining acceptance blocker: the daily step still composes configured active
exports instead of executing every registry prediction function inline from the
current promotion corpus. Stale item 86 is no longer the scheduled default, but
full per-contract execution orchestration remains to close this item.
