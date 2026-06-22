# 186. Soil-Moisture & Antecedent Land-Surface Dryness Predictor [PARTIAL 2026-06-22 - GATE LIVE, PRECIP/SETTLEMENT BLOCKED]

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
- [x] Add explicit antecedent-precipitation / ET0 water-balance features.
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
context rather than raw m3/m3 values. The original soil-dryness sidecar shipped
as `reanalysis_synoptic_features_v0.4`; the current antecedent-water extension
is `reanalysis_synoptic_features_v0.5`.

## Validation

- `python -m pytest tests\sources\test_reanalysis_synoptic.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 30 passed, 1 pre-existing scipy/numpy warning.

## 2026-06-22 Gate Rerun

The first refreshed `data/backtest/source_family_inventory.json` kept
`reanalysis_synoptic` blocked for promotion parity:
`decision=BLOCK_PARITY`, `train_serve_parity_status=MISSING_FEATURE_COLUMNS`.
That was an inventory false positive: parity compared every catalogued
reanalysis feature against sidecar columns even when the active artifact's
imputer had dropped all-missing new soil-dryness fields.

I updated `weather.reporting.source_family_inventory` so train/serve parity
requires the active artifact's retained feature columns when an active artifact
is present. After regenerating the inventory at `2026-06-22T04:13:52Z`,
`reanalysis_synoptic` reports `train_serve_parity_status=PASS`,
`promotion_decision=PROMOTION_CANDIDATE`, and no missing required parity
columns for the retained `40` active reanalysis columns. Source-family promotion
preflight is now `PASS` with `0` blocking families, and the bounded promotion
refresh at `2026-06-22T04:14:28Z` no longer lists `source_family_preflight` as a
readiness blocker.

This does not close item 186. The child still needs raw precipitation backfill
for the refreshed sidecar columns, then isolated settlement-scored
soil/antecedent-dryness gates before those fields can influence promotion.

## 2026-06-22 Antecedent Water Feature Wiring

The reanalysis sidecar now requests raw Open-Meteo historical `precipitation`
for rich reanalysis refreshes and exposes explicit antecedent water features:

- `reanalysis_prev_day_precipitation_sum`
- `reanalysis_prev_7d_precipitation_sum`
- `reanalysis_prev_14d_precipitation_sum`
- `reanalysis_prev_30d_precipitation_sum`
- `reanalysis_prev_7d_precipitation_minus_et0`
- `reanalysis_prev_14d_precipitation_minus_et0`
- `reanalysis_prev_30d_precipitation_minus_et0`

The water-balance fields are strict windows over prior dates only:
precipitation sum minus ET0 sum. They remain `None` if any required raw day in
the window is missing, avoiding a falsely dry partial-window value. The
reanalysis sidecar schema is now `reanalysis_synoptic_features_v0.5`, and the
shared feature schema is now `toronto_feature_store_v1.14`; old artifacts keep
serving by selecting their trained feature names.

I rebuilt the reanalysis sidecar files for all 12 markets. Each summary now
reports `9661` rows, `9660` rows with antecedent reanalysis, and schema
`reanalysis_synoptic_features_v0.5`. Current precipitation feature coverage is
still `0` rows because the cached raw ERA5/Open-Meteo payloads predate the
`precipitation` request.

After fixing source-family inventory missingness to score parity on required
active-artifact columns, the refreshed
`data/backtest/source_family_inventory.json` at `2026-06-22T04:53:12Z` is
`PASS`: `reanalysis_synoptic` has `52` catalog columns, `40` active retained
columns, and `train_serve_parity_status=PASS`. The high family-wide missingness
from diagnostic/null columns no longer blocks current promotion preflight.

Next unblock:

```powershell
python -m weather.sources.reanalysis_history --market <market> backfill --start <start> --end <end> --skip-existing --refresh-missing-hourly-variables --required-hourly-variables precipitation
python -m weather.sources.reanalysis_synoptic --market <market> build
```

Run that for the 12 market roots, regenerate `source_family_inventory`, then run
the isolated soil/antecedent-water settlement gate market-by-market.

Verification:

- `python -m pytest tests\sources\test_reanalysis_synoptic.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 36 passed, 1 pre-existing scipy/numpy warning.

## 2026-06-22 Fail-Closed Item 186 Gate

I added `weather.reporting.item186_soil_antecedent_gate` with schema
`item186_soil_antecedent_gate_v0.1` and generated:

- `data/backtest/item186_soil_antecedent_gate.json`
- `data/backtest/item186_soil_antecedent_gate_report.md`

The live gate is `BLOCK` with disposition `KEEP_SHADOW_DIAGNOSTIC` and
`promotion_allowed=false`. Passing checks:

- `sidecar_file_inventory`: all 12 market sidecars are present, non-empty, and
  on `reanalysis_synoptic_features_v0.5` (`115932` total rows).
- `soil_anomaly_feature_coverage`: soil anomaly / dry-VPD features have `8916`
  complete rows across all 12 markets.
- `source_family_inventory`: `reanalysis_synoptic` has train/serve parity
  `PASS`, required Item 186 columns, and `PROMOTION_CANDIDATE` status.

Blocking checks:

- `antecedent_water_balance_backfill`: precipitation-backed water-balance fields
  still have `0` complete rows in every market.
- `settlement_scored_family_gate`: the isolated soil/antecedent-water settlement
  gate has not been run.
- `positive_market_promotion_policy`: no positive-market promotion lane exists
  for this subfamily.

This keeps the item partially complete: the feature family is wired and audited,
but it remains shadow-only until precipitation backfill and market-by-market
settlement evidence are available.

Verification:

- `python -m pytest tests\reporting\test_item186_soil_antecedent_gate.py tests\operations\test_schema_registry.py -q` -> 5 passed.

Acceptance: a soil-dryness family is available as anomaly-transformed features,
settlement-scored gates are run per market, and any promoted lane shows
non-regressing per-market Brier with measured lift on hot/dry regimes.

Related: items 185, 32, 27, 36; `[[highs-projection-data-gap-2026-06-20]]`.
