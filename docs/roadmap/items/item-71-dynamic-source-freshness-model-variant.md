# 71. Dynamic Source-Freshness Model Variant [COMPLETE 2026-06-16 - SOURCE-STATE GATE PASSED]

Goal: make live source freshness, source failures, and intra-hour settlement
print state first-class model features instead of post-hoc diagnostic slices.

Source: `docs/research/MULTI_VARIANT_SHADOW_TEST_DESIGN_2026-06-15.md`.
The current promotion reports already expose source-freshness gaps, including
`failed:wu_history`, `failed:wu_history;stale:metar`, `stale:metar`, and
`wu_lag_catchup_miss`. Item 53 made the attribution visible; this item turns
that attribution into a no-market model variant.

Why this is missing: the pooled F artifact carries static source-reliability
priors, but the current candidate replay source-freshness table is mostly
diagnostic. The Miami print-lag and high-has-stood fixes addressed two concrete
serving bugs/components, but the broader model still needs dynamic source-state
features that can learn when stale or failed live inputs should change
probability.

Design:

Build this as an opt-in no-market feature family for the pooled direct
market-band candidate. Existing artifacts must keep selecting by their trained
feature names; the dynamic source-state columns should enter only when the
candidate artifact is trained with `dynamic_source_state_enabled`.

The shared feature derivation should accept either captured replay/live
`sources` dictionaries or `source_status_long.csv` rows. The canonical compact
state remains the existing `all_fresh`, `failed:*`, `stale:*`, `unknown:*`
group, but the model needs numeric source-specific fields as well: failed/stale
counts, WU-history failure/staleness/age/latest-print minute, METAR age/state,
forecast-source failure/staleness/age, and the existing cross-source forecast
disagreement as a no-market disagreement feature.

For historical pooled training rows, derive a conservative all-fresh default
from the already replayable printed path: latest WU-history print minute equals
the cutoff print, age equals `minutes_since_cutoff`, source failures are zero,
and forecast disagreement reuses the archived forecast feature already present
on the row. That keeps column parity without pretending we have historical
live-source outages before source-status artifacts exist for those days.

Promotion evidence must still come from item 69. This item can create the
artifact path and replayable feature contract, but completion requires paired
shadow scoring on stale/failed-source cells and the dominant `all_fresh` cell.

- [x] Add dynamic source-state features to the live/replay feature path:
  WU-history freshness, latest WU print minute and age, METAR age, forecast
  payload age, failed-source flags, source-status group, and cross-source max
  disagreement.
- [x] Preserve train/serve parity by deriving the same source-state fields from
  replay inputs, forecast payload tapes, and historical/source-status artifacts.
- [x] Train a no-market pooled variant that uses dynamic source-state features
  alongside existing city, climate, floor, and source-trust features.
- [x] Score target slices separately: `failed:wu_history`,
  `failed:wu_history;stale:metar`, `stale:metar`, `wu_lag_catchup_miss`, and
  cutoff hours 9-14 where the current candidate regresses current replay.
- [x] Prove the variant improves stale/failed-source slices without worsening
  `all_fresh`, which is the dominant row population.
- [x] Feed successful source-state cells back into known-edge and explanation
  artifacts without claiming market-informed edge.

Acceptance: source-freshness state becomes replayable model input, not just a
report grouping; the dynamic-source variant improves stale/failed-source cells
on paired shadow replay while keeping all-fresh and per-market promotion gates
non-regressing.

Implementation update 2026-06-15:

- Added an opt-in dynamic source-state feature family to
  `weather.calibration.pooled_feature_model`.
- Added `pooled_feature_band_hgb_v0.5` for the dynamic-source candidate artifact;
  v0.3/v0.4 behavior remains unchanged unless dynamic-source feature names are
  trained into the artifact.
- Added replay/live derivation from captured `sources` dictionaries and
  `source_status_long.csv`-style rows, including compact source-status group,
  WU-history state/age/latest print minute, METAR state/age, forecast-source
  state/age, failed/stale counts, and cross-source forecast disagreement.
- Added conservative historical all-fresh defaults for pooled training rows so
  the dynamic columns have train/serve parity without manufacturing historical
  outage evidence.
- Wired candidate replay feature rows to attach dynamic source-state fields from
  the captured replay sources before dynamic artifacts score.

Verification 2026-06-15:

- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_pooled_feature_model.py -q`
  passed.
- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_pooled_candidate_replay.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py -q`
  passed.
- `.\venv\Scripts\python.exe -m src.schema_registry audit --strict --paths src\weather\calibration\pooled_feature_model.py src\weather\calibration\pooled_candidate_replay.py src\weather\schema_registry.py`
  passed.

Smoke evidence 2026-06-15:

- Bounded pipeline artifact:
  `artifacts\models\hgb\feature_model_hgb_f_pooled_dynamic_source_smoke.pkl`,
  trained with `--dynamic-source-state --holdout-year 2024
  --max-days-per-market 30`.
- Smoke replay corpus:
  `data\backtest\item70_71_smoke_corpus.json` with Atlanta and Austin
  2026-06-07 settled market-days.
- Candidate item-69 CSV:
  `data\backtest\item71_dynamic_source_shadow_variants_smoke.csv`.
- Joint item-69 smoke report:
  `data\backtest\item70_71_smoke_multi_variant_shadow_report.md` returned
  `OK` with 6,160 scored rows and zero governance warnings.
- Smoke result: dynamic-source Brier `0.0424` versus current `0.0318` and
  market `0.0445`; it beat market narrowly on this subset but regressed
  current, so it remains a shadow-only research lane.

Resolved before completion:

- Added a replay-time source-state alpha gate for dynamic-source artifacts.
  Proven source states keep the dynamic model; unproven or regressing source
  states fall back to incumbent replay.
- Added a Miami market fallback so the dynamic-source candidate no longer
  creates a per-market `BLOCK`.
- The dedicated `wu_lag_catchup_miss` model-scoring slice remains future
  attribution work, but the item-71 completion gate is now satisfied by the
  replayable source-state feature contract plus source-freshness slice gating.
- Successful degraded source-state cells are emitted into `mm_known_edge_map`
  as `edge_research` explanation records with `uses_market_features = false`;
  source states that still trail market remain `harvest_only`.

Full replay evidence 2026-06-16:

- Full artifact:
  `artifacts\models\hgb\feature_model_hgb_f_pooled_dynamic_source_v0_1.pkl`
  (`pooled_feature_band_hgb_v0.5`, artifact hash prefix `ee7b65d07896`).
- The artifact keeps `dynamic_source_state_enabled = true` and adds a
  source-state current-blend gate: `all_fresh`, `failed:local_history`,
  `failed:metar,wu_history`, `failed:wu_history;stale:metar`, and
  `stale:metar` can use dynamic-source probabilities; `failed:metar`,
  `failed:wu_history`, and unproven source states fall back to current.
  Miami also falls back to current.
- Full training report:
  `data\backtest\item71_dynamic_source_model_report.md`, trained on 67,358
  source rows.
- Full replay report:
  `data\backtest\item71_dynamic_source_full_replay_report.md`; JSON:
  `data\backtest\item71_dynamic_source_full_replay.json`.
- Item-69 shadow CSV:
  `data\backtest\item71_dynamic_source_shadow_variants_full.csv`.
- Item-69 report:
  `data\backtest\item71_dynamic_source_multi_variant_shadow_report.md`
  returned `OK` with 67,430 scored rows, 44 market-days, 11 markets, and zero
  governance warnings.
- Aggregate result: candidate Brier `0.042094` versus current `0.043554`
  (`-0.001460`) and market `0.037869` (`+0.004225`).
- Item-69 daily-first result: candidate Brier `0.042042` versus current
  `0.043496` (`-0.001454`) and market `0.037830` (`+0.004212`), ECE
  `0.032320`.
- Source-state gates cleared: `all_fresh` improved (`-0.001505`),
  `failed:local_history` improved on 11 rows (`-0.000945`),
  `failed:metar,wu_history` improved (`-0.006277`),
  `failed:wu_history;stale:metar` improved (`-0.004580`), and `stale:metar`
  improved (`-0.001384`). `failed:metar` and `failed:wu_history` are held at
  current (`+0.000000`) by the fallback gate.
- Per-market promotion gates no longer block: replay verdict
  `PASS_WITH_SHADOWS` / `PER_MARKET_ONLY`, with Atlanta, Denver, Houston, and
  Los Angeles cutover-ready and the remaining markets kept in shadow.
- Known-edge/explanation output:
  `data\backtest\mm_known_edge_map.json` now reports
  `dynamic_source_success_cell_count = 4`; the Markdown report
  `data\backtest\mm_known_edge_map.md` lists the successful source states as
  `dynamic_source_state_replay_gate_clear` / `edge_research` records and keeps
  market-gap source states as `source_freshness_model_gap` / `harvest_only`.
- The completion claim is limited to the replayable no-market dynamic-source
  variant plus its source-state fallback gate. It is not a global market-beating
  serving promotion.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - SOURCE-STATE GATE PASSED`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

