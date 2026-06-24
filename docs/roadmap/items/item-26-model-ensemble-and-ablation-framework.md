# 26. Model Ensemble And Ablation Framework [COMPLETE - AWAITING MORE CLEAN DAYS]

Goal: improve accuracy by combining complementary signals only when they add
out-of-sample value.

- [x] Treat empirical climatology, HGB, forecast-error model, lag model, and
  market price as separate candidate forecasters.
- [x] Report each component's standalone performance by cutoff hour and band.
- [x] Learn ensemble weights under leave-one-day-out or rolling-day validation.
- [x] Add a fast sampled or cached research mode so component ablations and
  ensemble tests do not require multi-hour full leave-one-out retrains.
- [x] Keep a no-market-input model and a market-informed model separate, so
  "edge over market" remains interpretable.
- [x] Add guardrails against adding components that improve in-sample metrics
  but hurt settlement-scored market performance.

Acceptance: ensemble weights are justified by ablation tables and item-20
market-relative metrics.

Codex implementation status (2026-06-01): complete as an executable framework,
with promotion correctly blocked by sample size. Live inference now exposes
`distribution_components` with schema `toronto_distribution_components_v0.1`;
`src.snapshot_tracker` persists market-bin component probabilities to
`components_long.csv` and `components.jsonl` for future settled days. Component
names include climatology prior, HGB/LR feature model, feature blend,
forecast-error/cap distributions, post-live-signal distribution,
settlement-lag-adjusted distribution, pre-calibration model, and final model
when those components are present.

`src/model_ensemble.py` reads settled tapes, filters by market-day quality,
joins future component probability tapes, reports standalone forecasters
overall/by cutoff/by market-bin type, and learns simple leave-one-day tuned
pairs. It keeps no-market candidates separate from market-informed candidates
and writes the promotion guardrail directly into
`data/backtest/model_ensemble_report.md`. The current strict clean sample has
only May 28, so the report scores deployed model versus market but refuses to
fit leave-one-day ensembles:

- Rows scored: 704.
- Market price Brier/log loss: 0.0394 / 0.1230.
- Deployed model Brier/log loss: 0.0583 / 0.1850.
- No-market and market-informed ensembles: insufficient clean target days.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_model_ensemble.py tests\test_feature_store.py -q`: 7 passed.
- `.\venv\Scripts\python.exe -m src.model_ensemble data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`: wrote `data/backtest/model_ensemble_report.md` and correctly refused ensemble promotion with only one clean day.

Follow-up now unlocked: item 27 should add new weather-regime features only
behind this harness, and only promote features that improve clean
settlement-scored no-market validation.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - AWAITING MORE CLEAN DAYS`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

