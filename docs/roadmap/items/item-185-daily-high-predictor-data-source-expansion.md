# 185. Daily-High Predictor Data-Source Expansion [PARTIAL 2026-06-21 - CHILD ITEMS SCOPED, VALIDATION PENDING]

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
- [ ] **190** — NBM native probabilistic Tmax consumption.
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

Acceptance: each child item is resolved or explicitly rejected with
settlement-scored evidence, and any promoted family shows non-regressing
per-market Brier/log-loss on the pinned replay corpus.

Related: items 32, 35, 27, 36, 74, 75, 78; `[[highs-projection-data-gap-2026-06-20]]`.
