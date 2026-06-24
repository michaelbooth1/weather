# 73. Conservative Per-Market Candidate Bridge [COMPLETE 2026-06-16 - PAIRED SHADOW SCORING LIVE]

Goal: test whether current shadow-market pain comes from the pooled candidate
itself or from aggressive per-market cutover policy.

Source: `docs/research/MULTI_VARIANT_SHADOW_TEST_DESIGN_2026-06-15.md`.
The current F-family report shows heterogeneous market behavior: Atlanta,
Denver, and Houston are promote-ready; Dallas and San Francisco are effectively
tied with current serving; Miami is worse than current; Seattle and NYC beat
current but trail market prices badly. A conservative bridge variant can test
operational stability while richer variants mature.

Why this is missing: the existing artifact already has market-level blend
settings, but those settings are embedded in the single candidate artifact and
do not by themselves answer whether a more conservative cutover policy would
improve reliability on future days. This item makes that policy an explicit
shadow variant.

Design:

Build this as a no-market policy overlay, not a new weather model. The bridge
probability is:

`bridge_p = alpha_by_market * pooled_candidate_p + (1 - alpha_by_market) * current_serving_p`

The alpha schedule must be predeclared in code and exported with the shadow
rows. It should not read market prices, CLOB features, outcomes, or same-day
promotion decisions at scoring time. Market-relative evidence can change the
schedule only by a deliberate roadmap/config update before a future evaluation
window.

Initial alpha schedule:

- `0.90`: Atlanta, Denver, Houston.
- `0.00`: Miami, Dallas, San Francisco.
- `0.50`: Austin, Chicago, Los Angeles.
- `0.35`: NYC, Seattle.

The bridge should write item-69-compatible long-form rows with the pooled
candidate as a control and the bridge as a separate variant. The underlying
candidate report must keep by-market, cutoff-hour, settlement-distance, and
source-freshness diagnostics visible so a bridge win cannot be mistaken for a
model-learning win.

- [x] Define a predeclared per-market candidate-alpha schedule before each
  live-forward evaluation window.
- [x] Keep Atlanta, Denver, and Houston near full candidate weight while they
  keep passing promotion gates.
- [x] Keep Miami, Dallas, and San Francisco near current-serving fallback until
  they beat current replay and clear market-relative gates.
- [x] Use partial candidate weight for Austin, Chicago, Los Angeles, NYC, and
  Seattle, with alpha changes tied to item 48 promotion readiness evidence.
- [x] Score the bridge against both pooled F v0.3 and current serving through
  item 69's paired multi-variant report.
- [x] Do not let a bridge win hide model-learning gaps; any bridge promotion
  must preserve the underlying variant diagnostics by market, cutoff hour,
  settlement distance, and source-freshness state.

Acceptance: a conservative bridge variant can be evaluated as an operational
policy candidate with paired replay evidence, while the roadmap still preserves
separate model-improvement work for exact-winner catch-up, source freshness, and
market-aware CLOB overlays.

Implementation update 2026-06-15:

- Added `conservative_bridge_policy_v0.1` with a predeclared alpha schedule:
  Atlanta/Denver/Houston `0.90`, Miami/Dallas/San Francisco `0.00`,
  Austin/Chicago/Los Angeles `0.50`, and NYC/Seattle `0.35`.
- Candidate replay now computes `bridge_candidate_p` without using market
  prices, CLOB features, outcomes, or same-day promotion decisions.
- Candidate replay writes an item-69-compatible CSV at
  `data/backtest/conservative_bridge_shadow_variants.csv` by default.
- The exported family includes `pooled_f_candidate_control` and
  `conservative_bridge_policy_v0_1`; both are marked `uses_market_features =
  false`.
- Candidate replay markdown and promotion-refresh JSON now surface bridge
  aggregate and by-market diagnostics while preserving the underlying candidate,
  CLOB, source-freshness, cutoff-hour, and settlement-distance diagnostics.

Verification 2026-06-15:

- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py -q`
  passed.
- `.\venv\Scripts\python.exe -m src.schema_registry audit --strict --paths src\weather\calibration\pooled_candidate_replay.py src\weather\calibration\pooled_candidate_replay_report.py src\weather\reporting\promotion_refresh.py src\weather\schema_registry.py`
  passed.

Completion update 2026-06-16:

- Ran the conservative bridge export through item 69's paired multi-variant
  report:
  `data/backtest/item73_bridge_multi_variant_shadow_report.md`.
- The report scored `134,860` rows across `44` market-days and `11` F markets
  with status `OK`, `0` errors, and `0` warnings.
- Daily-first bridge Brier was `0.0424` versus pooled candidate control
  `0.0430` and current serving `0.0435`. The bridge still trails market Brier
  `0.0378`, so this is operational bridge evidence, not weather-model
  promotion evidence.
- The item-69 track remains `no-market`; the bridge policy uses only the
  predeclared alpha schedule and current/candidate probabilities, not CLOB or
  market-price features.
- Future alpha changes still require a deliberate roadmap/config update using
  future promotion-readiness evidence.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - PAIRED SHADOW SCORING LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

