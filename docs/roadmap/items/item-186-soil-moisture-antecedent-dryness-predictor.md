# 186. Soil-Moisture & Antecedent Land-Surface Dryness Predictor [PARTIAL 2026-06-21 - SOIL ANOMALY FEATURES LIVE, GATE PENDING]

Goal: give the model the single biggest *missing* physical control on hot-day
extremes — antecedent soil dryness — as a settlement-scored feature family.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
Gap 2. Dry soil shifts the surface energy balance from latent (evaporation) to
sensible heat and amplifies the daytime maximum; the land–atmosphere literature
finds this is the dominant non-synoptic driver of hot extremes
([Nat. Commun. 2025](https://www.nature.com/articles/s41467-025-56109-0);
[WACE 2015 — soil moisture & European Tmax extremes](https://www.sciencedirect.com/science/article/pii/S2212094715000201)).
The model currently has **no** soil-moisture, evapotranspiration, or
antecedent-precipitation feature.

Why this matters / why it's distinct from item 32: item 32 wired raw antecedent
`soil_moisture` reanalysis columns into its sidecar, but they are sparse and used
as raw values. The predictive signal is the **anomaly/percentile vs local
climatology**, not the absolute value, plus antecedent precipitation and
evaporative fraction. Soil moisture is slowly varying, so a multi-day data lag is
acceptable.

## Design

1. Add a soil-dryness feature family to `FEATURE_COLUMNS`: root-zone soil-moisture
   **percentile/anomaly** vs the market's own climatology, antecedent 7/14/30-day
   precipitation, and an evaporative-fraction / VPD proxy.
2. Source per market: **NLDAS-2** root-zone soil moisture for US markets
   (operational, ~4-day lag, [Drought.gov/NLDAS](https://www.drought.gov/data-maps-tools/north-american-land-data-assimilation-system-nldas)),
   **ERA5-Land** soil moisture/temperature for Toronto and global coverage, with
   **SMAP L4** as a cross-check. Coordinate the ingestion with item 32's
   reanalysis sidecar so there is one soil feed, not two.
3. Compute the anomaly transform against each market's multi-year climatology, not
   raw m³/m³.
4. Gate through the settlement-scored feature-value gate (item 27) and per-market
   promotion (item 36) before any serving influence.

- [x] Add ERA5/Open-Meteo reanalysis root-zone soil-moisture features coordinated with item 32; NLDAS-2 remains pending.
- [x] Add soil-moisture anomaly/percentile + dry-VPD stress proxy features.
- [ ] Add explicit antecedent-precipitation / evaporative-fraction features.
- [ ] Run the settlement-scored family gate market-by-market.
- [ ] Promote only the markets/subfamily that clear out-of-sample.

## Implementation

The gated `reanalysis_synoptic_features` sidecar now exposes derived
soil-dryness features from the existing ERA5/Open-Meteo reanalysis feed:

- `reanalysis_prev_day_soil_moisture_0_to_7cm_percentile`
- `reanalysis_prev_day_soil_moisture_0_to_7cm_anomaly`
- `reanalysis_prev_day_soil_dryness_percentile`
- `reanalysis_prev_day_dry_vpd_stress_proxy`
- `reanalysis_soil_dryness_available`

The transform compares the antecedent day's root-zone soil moisture against
same-season prior-year local values, so training sees local anomaly/percentile
context rather than raw m3/m3 values. The schema is bumped to
`reanalysis_synoptic_features_v0.4`, with v0.3 retained as legacy.

## Validation

- `python -m pytest tests\sources\test_reanalysis_synoptic.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 30 passed, 1 pre-existing scipy/numpy warning.

Acceptance: a soil-dryness family is available as anomaly-transformed features,
settlement-scored gates are run per market, and any promoted lane shows
non-regressing per-market Brier with measured lift on hot/dry regimes.

Related: items 185, 32, 27, 36; `[[highs-projection-data-gap-2026-06-20]]`.
