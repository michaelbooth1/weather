# 184. Per-Market Climatological Fallback Prior [COMPLETE 2026-06-21 - MARKET-SPECIFIC FALLBACK PRIOR LIVE]

Goal: replace the fixed Toronto-summer uniform prior used for every city with a
per-market climatological fallback prior.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding M5 (also the
2026-06-09 audit finding #6). When local climatology is thin the prior is uniform
over `range(round(c_to_native(8)), round(c_to_native(33)))`
([model_distribution.py:162-164](../../../src/weather/model/model_distribution.py#L162))
— an 8–33 °C Toronto-summer band imposed on Miami (rarely < 20 °C) and Seattle
(rarely > 30 °C).

Why this matters: the fallback only bites when history is sparse, but for newer
markets that is exactly when the prior matters most, and a mis-centred uniform
prior puts mass on buckets the market essentially never settles to.

## Design

1. Derive the fallback support and shape from the market's own daily-summary
   percentiles, or a season-aware Gaussian around the climatological normal, per
   `spec`.
2. Fall back to the wide uniform band only when the market has no usable summary
   at all.
3. Test that Miami and Seattle priors concentrate in their real ranges rather
   than spreading uniformly across the Toronto band.

- [x] Build the per-market climatological fallback prior keyed on `spec`.
- [x] Keep the wide uniform only as a last resort.
- [x] Add Miami/Seattle prior-shape tests and confirm no Toronto regression.

## Implementation

`DistributionMixin._estimate_distribution_result` now calls
`climatology_fallback_prior()` when local history is missing or too thin. The
helper lives in `ClimatologyMixin` and returns native-unit priors:

- Toronto keeps the legacy 8-32 C uniform fallback exactly unchanged.
- Non-Toronto markets read their own `daily_summary.csv`, filter prior-year rows
  by target-season date window and row count, and expand the date window only
  when the first window is too sparse.
- The shaped fallback is a smoothed empirical distribution over a
  percentile-clipped support, with true historical outlier buckets retained by
  the smoothing helper.
- If a market has no usable daily summary at all, the code falls back to the
  legacy wide uniform band.

## Validation

- `python -m pytest tests\model\test_climatology_cache.py tests\model\test_estimate_distribution.py tests\model\test_market_units.py -q` -> 52 passed.
- Miami 2026-06-21 fallback prior: zero mass below 75 F, more than 80% mass on
  85-93 F, and peak bucket in the upper-80s/low-90s F.
- Seattle 2026-06-21 fallback prior: peak bucket in the 60s F, more than 40%
  mass on 66-75 F, and lower sub-65 F mass than the converted Toronto uniform.
- Toronto 2026-06-21 fallback prior is exactly the legacy 8-32 C uniform.

Acceptance: the thin-history fallback prior reflects each market's climatology,
Miami and Seattle no longer receive uniform mass across the 8–33 °C-equivalent
band, and Toronto is unchanged.

Related: item 182; `[[model-audit-2026-06-09]]`, `[[multi-market-platform]]`.
