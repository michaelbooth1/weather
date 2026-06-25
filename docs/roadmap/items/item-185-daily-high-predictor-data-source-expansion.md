# 185. Daily-High Predictor Data-Source Expansion [PARTIAL 2026-06-22 - SOURCE PREFLIGHT CLEARED, CHILD GATES OPEN]

Goal: integrate the highest-value weather data sources the daily-high research
audit found the model is physically blind to, each earning its place by
settlement-scored validation rather than feature-importance charts. Parent
tracker for items 186–191.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`.
That audit mapped the model's live feature set onto the physics of the daytime
maximum and the statistical-post-processing literature. Verdict: the model is
already strong on the observed temperature path, the multi-model forecast
ensemble, analogs, and per-source bias, but is blind to several drivers the
literature ranks at or near the top for Tmax.

Why this matters: the missing drivers are not redundant with what the model has.
Antecedent soil dryness (Bowen ratio), surface insolation, and smoke dimming each
move the high by degrees and produce one-sided busts the current inputs cannot
see.

## Children (new items)

- [ ] **186** — Soil-moisture & antecedent land-surface dryness predictor.
- [ ] **187** — Forecast shortwave-radiation & peak-window insolation features.
- [ ] **188** — Aerosol & wildfire-smoke suppression features.
- [ ] **189** — ECMWF & ML-NWP ensemble forecast members.
- [x] **190** — NBM native probabilistic Tmax consumption.
- [ ] **191** — Lake/sea surface-temperature contrast feature.

## Already owned elsewhere (referenced, not duplicated)

- **850 hPa temperature / 1000–500 thickness / mixing temperature** — the classic
  Tmax predictor — is **item 32**'s scope (pressure-level cache + reanalysis
  synoptic sidecar, currently blocked on per-market promotion and the stale 2026
  NOAA pressure file). The audit's one *new* angle for item 32 is to also pull
  **live forecast-side** 850 hPa temperature from a forecast pressure-level API so
  serving is not left with empty synoptic features when the antecedent reanalysis
  lags. Tracked as a note on item 32.
- **Continuous predictive distribution + CRPS/PIT scoring** — the audit's
  methodological recommendation — is **item 35**'s scope. CRPS + PIT reliability
  should be added to that item's verification harness.

## Discipline (applies to every child)

1. Add each source as a gated feature family behind the model harness (item 36);
   do not let it influence serving until settlement-scored gates show
   out-of-sample skill (the item 27 / source-family preflight pattern item 32
   uses).
2. Validate market-by-market — a family that helps Houston can hurt Toronto.
3. Keep the data feed in Track A's collection/robustness model (retries, freshness,
   provenance) so a new source cannot become a silent data-loss surprise.

## Status

- [x] Child roadmap items 186-191 created and linked from this tracker.
- [x] Research-audit ownership mapped to existing items 32, 35, and 78 where the
  recommendation is not a new data-source family.
- [ ] Resolve or explicitly reject each child with settlement-scored evidence.
- [ ] Promote only non-regressing per-market feature families.

## 2026-06-22 Child-Gate Triage

Refreshed `data/backtest/source_family_inventory.json` and
`data/backtest/item138_weak_input_family_disposition.json` again after the
current promotion/retrain artifacts. The parent gate is still
validation-pending; none of the 186-191 children has enough settlement-scored
evidence for promotion. The first refresh showed source-family promotion
preflight `BLOCK` with two parity blockers, `forecast_baseline` and
`reanalysis_synoptic`, both `MISSING_FEATURE_COLUMNS`.

I fixed the inventory preflight to evaluate train/serve parity against the
active artifact's retained feature columns instead of every catalogued family
column. That matters because the current artifact retained `4` forecast-baseline
columns and `40` reanalysis columns; catalog-only or imputer-dropped columns
were incorrectly counted as promotion blockers. Regenerating
`data/backtest/source_family_inventory.json` at `2026-06-22T04:13:52Z` now
reports source-family promotion preflight `PASS` with `0` blocking families.
The bounded promotion refresh at `2026-06-22T04:14:28Z` also dropped the
`source_family_preflight` blocker from readiness.

| Child | Current Generated Evidence | Next Unblock |
| :--- | :--- | :--- |
| 186 soil/reanalysis dryness | Source-family parity is now `PASS` for the active artifact's retained `40` reanalysis columns, and promotion preflight no longer blocks. The catalog-only soil-dryness columns are still absent from historical sidecars, and the child still lacks isolated settlement-scored soil/antecedent-dryness lift. | Add remaining antecedent precipitation / evaporative-fraction fields or explicitly keep them diagnostic, then run per-market soil-dryness settlement gates before promotion influence. |
| 187 forecast radiation | `open_meteo_forecast_profile` is served and positive at broad family level, but the weak-family report still has `46` features with `44` low-coverage/sparse rows; the radiation subset has not cleared its own morning/midday settlement gate. | Run an isolated radiation-feature gate and require no late-day regression. |
| 188 aerosol/smoke | Open-Meteo AQ live features exist, but the child still lacks historical AQ backfill/retrain support and a high-AOD/high-PM smoke-day slice. | Backfill AQ or prove replay-safe live history, then score the smoke slice. |
| 189 ECMWF/ML-NWP members | `official_multimodel_guidance` is `regime_backfill` with `33` low-coverage and `19` near-constant/unanalyzable features; lineage/parity is incomplete. | Archive/backfill the global-model members and rerun predawn/morning settlement gates. |
| 190 NBM probabilistic Tmax | Complete 2026-06-25: station percentiles are live, QMD extraction/replay-safe station-archive paths are proven, and the settlement-scored calibration-anchor artifact covers `50,611` rows across `33` US market-days. The gate is `DO_NOT_CUT_OVER` because NBM-prob regresses current in daily-first validation and all `11` US market slices. | No implementation unblock remains for item 190; keep it diagnostic/shadow-only until future evidence clears the non-regression gate. |
| 191 lake/sea contrast | `marine_microclimate` is `regime_backfill` with `17` low-coverage and `8` near-constant/unanalyzable features, no positive broad family gate, and incomplete lineage/parity. | Add GLSEA/OISST or enough station history, then score the onshore/breeze-day slice. |

Acceptance: each child item is resolved or explicitly rejected with
settlement-scored evidence, and any promoted family shows non-regressing
per-market Brier/log-loss on the pinned replay corpus.

Related: items 32, 35, 27, 36, 74, 75, 78; `[[highs-projection-data-gap-2026-06-20]]`.
