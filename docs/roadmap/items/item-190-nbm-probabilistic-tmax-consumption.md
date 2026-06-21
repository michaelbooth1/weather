# 190. NBM Native Probabilistic Tmax Consumption [PARTIAL 2026-06-21 - NBP STATION PERCENTILES LIVE, QMD EXCEEDANCE GRID GATE PENDING]

Goal: consume the National Blend of Models' calibrated probabilistic maximum-
temperature distribution, instead of using only its point high.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
section 4. NOAA documents NBM probabilistic MaxT percentiles in the QMD/NBP
product family, and NBM GRIB2/text products are publicly available through
NOMADS and the NOAA Open Data S3 bucket. The model previously ingested NBM only
as a single point high through Open-Meteo's `ncep_nbm_conus` field, discarding
NBM's calibrated uncertainty.

Why this matters: NBM's probabilistic MaxT is a strong, calibrated baseline that
is cheap to obtain for US markets. It can serve both as features (percentile
spread and exceedance probabilities) and as a calibration anchor the model's own
distribution is scored against.

## Design

1. Add an NBM probabilistic-Tmax adapter with provenance/freshness. The live
   first path reads NOMADS `blend_nbptx` NBP station text, which exposes
   station-aligned `TXNP1/TXNP2/TXNP5/TXNP7/TXNP9` daily MaxT percentile rows
   for 10/25/50/75/90 percentiles without requiring per-market GRIB extraction.
2. Features: expose `nbm_prob_tmax_p10/p25/p50/p75/p90`, mean, standard
   deviation, IQR, 10-90 spread, p50/p90 deltas against `forecast_high`, and an
   interpolated exceedance probability against `forecast_high`.
3. Keep native QMD GRIB exceedance grids as a second gate. The station text
   gives percentile curve features now; bucket-edge native exceedance grids and
   historical backfills still need GRIB extraction, archive parity, and
   settlement-scored validation before promotion.
4. Settlement-scored gate per US market. NBM remains US-only in this live path,
   so Toronto stays on the existing non-NBM path.

## Progress 2026-06-21

- [x] Added `weather.sources.nbm_probabilistic_tmax` with NBP station text URL
  construction, recent-cycle candidates, station block parsing, target-day MaxT
  slot selection, percentile payload hashing, and percentile-curve exceedance
  interpolation.
- [x] Added `nbm_probabilistic_tmax` to US live source fetching when official
  US guidance is active, with a 120-minute last-good cache TTL and fallback
  over recent NBM cycles.
- [x] Added live-only `nbm_prob_tmax_*` feature columns and bumped the feature
  schema to `toronto_feature_store_v1.10`; historical training rows default the
  fields to `None` until archives exist.
- [x] Added NBM payload/source visibility to snapshot reconstruction, source
  family inventory, disagreement casebook, and official US guidance ablations.
- [ ] Add native QMD GRIB percentile/exceedance-grid extraction for market
  points and bucket edges.
- [ ] Backfill historical probabilistic NBM features or otherwise prove a
  replay-safe archive path for US markets.
- [ ] Settlement-score NBM-prob as a calibration anchor and gate promotion on
  non-regressing per-market skill.

Acceptance: NBM probabilistic MaxT is ingested for US markets, exposed as
features, and settlement-scored, with non-regressing per-market skill and a
documented comparison against NBM as a calibrated baseline.

Related: items 185, 75, 21, 27; `[[highs-projection-data-gap-2026-06-20]]`.
