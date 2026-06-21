# 191. Lake/Sea Surface-Temperature Contrast Feature [PARTIAL 2026-06-21 - STATION WATER-FORECAST CONTRAST LIVE, GLSEA/OISST GATE PENDING]

Goal: give the lake/sea-breeze signal the water temperature contrast it depends
on, so the model can anticipate shoreline-cooling days instead of only flagging
onshore wind.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
Gap 5. Item 78 already added live CO-OPS/NDBC marine context with water
temperature, air temperature, wind, onshore/offshore flow, and breeze-risk
diagnostics. This item extends that live source with the missing daily
water-minus-forecast-air contrast that sets lake/sea-breeze strength and inland
penetration. For Toronto, Chicago, and coastal markets, the next richer source
layer remains gridded/satellite SST such as GLSEA for the Great Lakes or OISST
for broader coastal markets.

Why this matters / distinct from item 78: item 78 captures whether a market is
near water, whether live wind is onshore, and whether local marine observations
show cool water/air. Item 191 adds the model-facing magnitude: how far the water
temperature is below the forecast high, and how much of that cooling contrast is
active under onshore flow.

## Design

1. Reuse the existing marine-context registry's station selection and nearest-
   water distance, so the contrast only applies to lake/coast-influenced
   markets.
2. Feature: `marine_water_minus_forecast_high` from live station water
   temperature minus the resolved serving `forecast_high`.
3. Feature: `marine_onshore_water_minus_forecast_high`, an onshore-gated
   contrast that is zero when wind is not onshore and equal to the contrast when
   wind is onshore.
4. Feature: `marine_onshore_cooling_potential`, the positive cooling magnitude
   available only under onshore flow.
5. Keep GLSEA/OISST gridded SST as a follow-up adapter for markets where a
   single station is sparse, missing, or not representative.

## Progress 2026-06-21

- [x] Added water-minus-forecast-high, onshore-gated contrast, and onshore
  cooling-potential fields to `MARINE_CONTEXT_FEATURE_COLUMNS`.
- [x] Passed the resolved live `forecast_high` into marine-context feature
  derivation, so the contrast uses the same forecast consensus as serving.
- [x] Bumped the feature schema to `toronto_feature_store_v1.11`; historical
  rows keep these live-only fields nullable until backfills/replay gates exist.
- [x] Added focused source and live-feature tests for the contrast fields.
- [ ] Add GLSEA Great Lakes SST and/or OISST gridded SST adapters with
  market-point extraction and provenance.
- [ ] Backfill or replay-gate the station/gridded water-contrast features for
  lake/coast-influenced markets.
- [ ] Settlement-score the onshore-wind/breeze-day slice and require no
  aggregate regression before promotion.

Acceptance: a daily lake/sea surface-temperature contrast feature is available
and settlement-scored, with measured improvement on onshore-wind/breeze days for
lake- and coast-influenced markets and no aggregate regression.

Related: items 185, 78, 32, 27; `[[highs-projection-data-gap-2026-06-20]]`.
