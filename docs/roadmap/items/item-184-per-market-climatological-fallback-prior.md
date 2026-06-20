# 184. Per-Market Climatological Fallback Prior [OPEN]

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

- [ ] Build the per-market climatological fallback prior keyed on `spec`.
- [ ] Keep the wide uniform only as a last resort.
- [ ] Add Miami/Seattle prior-shape tests and confirm no Toronto regression.

Acceptance: the thin-history fallback prior reflects each market's climatology,
Miami and Seattle no longer receive uniform mass across the 8–33 °C-equivalent
band, and Toronto is unchanged.

Related: item 182; `[[model-audit-2026-06-09]]`, `[[multi-market-platform]]`.
