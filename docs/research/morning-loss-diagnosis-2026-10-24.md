# Morning (07-12) loss against the market: what the market has that we lack (lane L5, 2026-10-24)

**Status:** dated research record, **development** evidence only (dates <= 2026-09-29; these dates were already
read by 79a, 81a, 111h and EF §10q, so nothing here is confirmation, edge or promotion evidence). Descriptive
diagnosis; no serving, config or capture change. Code: `tools/research/morning_loss/`.

**Read when:** choosing the next data source or model lever for the morning window; before fetching another
observation source for 07-12.

## Bottom line

1. **The morning loss is the served centre, not width:** the two-ordering Shapley centre share is **76.5%
   [63.1, 88.7]** of the 07-12 served-minus-market Brier excess. Served is cold by **−1.44 F [−2.20, −0.69]**
   on average; the market is unbiased (+0.02 [−0.22, +0.25]).
2. **The cold bias grows with heat.** Split each market's days into terciles of the market centre (ex ante).
   The market-minus-served gap is +0.40, +1.34 and +2.71 F across the three, and the market's bias stays within
   ±0.1 F in each (post-hoc). The top-decile days are mostly hot days in Dallas, Austin, Atlanta and Miami, plus
   Los Angeles; on them served sits 4-6 F below the outcome.
3. **The market's information is priced by midnight, not learned in the morning.** On top-decile days the market
   centre is within 0.64 F of the outcome at 00:00. It moves 0.03 F on average from 00 to 12 h. Served drifts
   *colder* from 00 to 08 h (−0.43 F) and is then pulled up by observations (+1.48 F from 08 to 12 h). The
   pre-declared timing rule fires: the market is a mean **13.2 h [9.6, 14.7]** ahead. That lead is our lag,
   not morning information reaching the market.
4. **Most of what the market has, we already capture.** Over 07-12 the centre MAE to the outcome is: served
   2.26 F, captured NBM v2 mean 1.60, an equal blend of four captured products with walk-forward per-market
   debiasing 1.48, and the market 1.14 (post-hoc). The blend closes about 70% of the served-to-market centre
   gap with no new data. MG-1 (EF §10q, zero parameters) cuts the 07-12 excess from 0.0258 to 0.0117.
5. **No weather regime is a signal.** On the pre-declared rule, all six flags are NO_SIGNAL: frontal/wind
   shift, low cloud, precipitation, overnight-low gap, forecast revision and temperature tendency. The
   remaining ~0.34 F centre residual that no captured product reproduces sits mostly in the marine and coastal
   cities.

## Method

Pre-declared plan: `tools/research/morning_loss/plan.md`, sha256
`a10b172fb1e99e3f3aa268849e58bb4441ea729a233c048acd805aae4425786a`. It was locked at `C:\t\l5\plan.md` after the
positive control and before any other computation.

- **Population:** dev scorecard layout `C:\swarm\v3layout`, scored by the kit's default folds: 43 dates
  (08-15..09-29), 11 US markets, 473 market-days, 21,695 snapshots at local 07-12.
- **Brier and bootstrap:** Brier is computed exactly as `weather.reporting.scorecards.dev_scorecard`
  (branch `claude/integration-20261024-devscorecard-on-master` @ `4be7c077c`). Intervals use one crossed
  date x market weight matrix (2,000 draws, seed 20260921), and the top decile is recomputed inside each draw.
- **Regime inputs:** our captured replay inputs only (`data\inbox\replay-inputs-le0929`). From each folder the
  extractor parses two lines: the first, and the last line captured on the target date. Lines are located from
  timestamp prefixes alone, so no line captured after the target date is parsed.
- **Market centre:** the probability-weighted mean of band representative degrees. The decomposition shifts the
  band pmf by the centre difference (uniform within integer degrees), then applies the kit's floor mask.
- **Positive control** (`dev_scorecard score --candidate served`, output sha `3557f797c6ca…`): pooled R
  **1.774 [1.566, 2.052]** over all hours and **1.526 [1.369, 1.721]** over 00-16. Both match the kit's
  served v2 baseline.
- Result JSON sha256: `ea79cb0f90707db871ee094d7f91be1ca5555b3e4f7e7fe47ddc0ccd8b07fba6`. Outputs are in
  `C:\t\l5\` on the workstation.

## Analysis 1: decomposition (07-12)

| Quantity | Served | Market | MG-1 |
| --- | --- | --- | --- |
| Excess Brier over market (mean per market-day) | 0.0258 | 0 | 0.0117 |
| Centre share: ordering A (shift served to the market centre) | 55.4% [39.1, 69.8] | | 66.4% [47.1, 87.9] |
| Centre share: ordering B (shift the market to our centre) | 97.6% [68.8, 124.7] | | 81.9% [64.9, 100.3] |
| **Centre share: Shapley (mean of A and B)** | **76.5% [63.1, 88.7]** | | **74.2% [60.3, 87.4]** |
| Centre MAE to outcome, F | 2.40 [1.95, 2.88] | 1.17 [1.03, 1.32] | 1.60 [1.36, 1.87] |
| Centre bias (centre − outcome), F | −1.44 [−2.20, −0.69] | +0.02 [−0.22, +0.25] | +0.84 [0.47, 1.20] |
| Mean SD, F | 2.50 | 1.74 | 1.97 |
| Mean z² (1 = calibrated spread) | 3.01 [1.13, 9.70] | 0.85 [0.58, 1.36] | 2.86 [1.09, 9.83] |

The pre-declared reading is **centre-dominated**, because the Shapley interval lies above 50%. Served is 1.44x
[1.26, 1.60] wider than the market and still under-dispersed against its own errors, because the centre is
wrong. The shift operator moves the served centre to within 0.08 F of the market centre (sanity check).

**Per hour** (served − market Brier, R, Shapley centre share, centre MAE served / market):

| Hour | Excess [95%] | R [95%] | Centre share [95%] | MAE S / M, F |
| --- | --- | --- | --- | --- |
| 07 | 0.028 [0.019, 0.038] | 1.506 [1.329, 1.719] | 73.6% [58.7, 90.2] | 2.80 / 1.24 |
| 08 | 0.028 [0.019, 0.037] | 1.506 [1.322, 1.716] | 78.3% [62.6, 92.1] | 2.81 / 1.22 |
| 09 | 0.026 [0.018, 0.034] | 1.476 [1.305, 1.680] | 77.5% [59.7, 92.1] | 2.55 / 1.20 |
| 10 | 0.025 [0.017, 0.033] | 1.468 [1.302, 1.655] | 78.0% [62.2, 91.1] | 2.35 / 1.17 |
| 11 | 0.024 [0.016, 0.032] | 1.460 [1.296, 1.654] | 79.0% [66.4, 91.0] | 2.14 / 1.13 |
| 12 | 0.024 [0.017, 0.030] | 1.480 [1.320, 1.684] | 71.8% [59.0, 83.3] | 1.77 / 1.06 |

**Per market** (date-clustered; served excess, R, Shapley centre share, MG-1 excess):

| Market | Served excess [95%] | R [95%] | Centre share [95%] | MG-1 excess [95%] |
| --- | --- | --- | --- | --- |
| atlanta | 0.024 [0.015, 0.034] | 1.483 [1.267, 1.786] | 90.9% [76.8, 114.1] | 0.017 [0.009, 0.026] |
| austin | 0.036 [0.026, 0.045] | 1.735 [1.468, 2.114] | 86.1% [74.7, 98.9] | 0.021 [0.011, 0.030] |
| chicago | 0.017 [0.004, 0.029] | 1.278 [1.061, 1.558] | 51.6% [23.6, 76.8] | 0.006 [−0.003, 0.016] |
| dallas | 0.042 [0.026, 0.057] | 1.888 [1.473, 2.465] | 95.6% [85.9, 111.2] | 0.017 [0.007, 0.027] |
| denver | 0.015 [0.007, 0.024] | 1.226 [1.092, 1.393] | 112.4% [84.9, 159.7] | 0.004 [−0.006, 0.013] |
| houston | 0.016 [0.007, 0.024] | 1.314 [1.137, 1.533] | 57.3% [29.9, 80.5] | 0.009 [0.002, 0.016] |
| los-angeles | 0.047 [0.037, 0.057] | 1.988 [1.648, 2.446] | 76.7% [72.2, 82.0] | 0.012 [0.001, 0.023] |
| miami | 0.029 [0.017, 0.039] | 1.543 [1.303, 1.806] | 74.7% [62.5, 85.3] | 0.005 [−0.004, 0.015] |
| nyc | 0.022 [0.012, 0.031] | 1.402 [1.206, 1.679] | 40.2% [21.2, 56.3] | 0.013 [0.003, 0.023] |
| san-francisco | 0.016 [0.009, 0.023] | 1.265 [1.139, 1.409] | 48.8% [27.5, 65.1] | 0.011 [0.003, 0.019] |
| seattle | 0.022 [0.013, 0.031] | 1.427 [1.247, 1.656] | 74.0% [55.3, 99.6] | 0.014 [0.006, 0.021] |

## Analysis 2: concentration

- The top decile (48 of 473 market-days) carries **35.0% [29.3, 45.2]** of the total 07-12 excess and 29.5%
  [26.2, 34.3] of the positive excess. The loss is moderately concentrated, not a thin tail.
- Composition: los-angeles 14, dallas 12, austin 6, miami 4, chicago 3, and 2 each for atlanta, denver, nyc
  and seattle, with houston 1. They fall on 32 dates; San Francisco has none.
- Under MG-1 the top decile carries 58.0% [45.0, 90.5] of a smaller total, and only 10 of its 48 days overlap
  the served top decile. The served top decile is largely what MG-1 removes.

Top decile. E is mean 07-12 excess; centres are 07-12 means, in F. Flags: R1 frontal, R2 cloud, R3 precip,
R4 overnight-low gap, R5 revision, R6 tendency.

| # | date | market | E | E MG-1 | outcome | served c | market c | MG-1 c | flags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-08-20 | dallas | 0.139 | 0.008 | 104 | 99.4 | 104.4 | 104.0 | R4,R6 |
| 2 | 2026-08-19 | dallas | 0.131 | 0.073 | 104 | 99.5 | 104.4 | 103.0 | R4,R6 |
| 3 | 2026-09-21 | los-angeles | 0.111 | 0.058 | 77 | 74.0 | 76.0 | 75.1 | R4,R6 |
| 4 | 2026-09-20 | chicago | 0.110 | 0.013 | 70 | 75.4 | 70.6 | 71.0 | R1,R2,R3 |
| 5 | 2026-09-28 | chicago | 0.107 | -0.001 | 72 | 73.6 | 72.6 | 73.0 | R4,R6 |
| 6 | 2026-08-17 | dallas | 0.105 | 0.006 | 104 | 98.6 | 104.8 | 104.0 | R4,R6 |
| 7 | 2026-08-24 | dallas | 0.104 | 0.051 | 107 | 100.3 | 107.0 | 105.0 | R4 |
| 8 | 2026-08-29 | dallas | 0.099 | 0.011 | 101 | 96.8 | 100.7 | 101.0 | R4 |
| 9 | 2026-08-18 | miami | 0.098 | 0.006 | 99 | 92.3 | 97.9 | 99.0 | R4 |
| 10 | 2026-09-28 | nyc | 0.097 | 0.068 | 63 | 64.2 | 62.6 | 66.0 | R2,R3 |
| 11 | 2026-08-30 | dallas | 0.095 | 0.007 | 100 | 96.3 | 100.5 | 101.0 | R4 |
| 12 | 2026-09-07 | dallas | 0.095 | 0.016 | 100 | 95.9 | 100.4 | 100.0 | R4 |
| 13 | 2026-08-22 | austin | 0.093 | 0.030 | 105 | 98.2 | 104.5 | 105.0 | R1,R4,R6 |
| 14 | 2026-09-24 | miami | 0.093 | -0.014 | 91 | 88.0 | 89.9 | 90.0 | R4 |
| 15 | 2026-09-06 | chicago | 0.093 | 0.028 | 78 | 79.7 | 78.5 | 78.4 | R4,R6 |
| 16 | 2026-09-04 | los-angeles | 0.092 | 0.009 | 77 | 75.3 | 76.8 | 76.1 | R4,R6 |
| 17 | 2026-09-19 | nyc | 0.092 | 0.047 | 70 | 71.6 | 71.0 | 72.4 | - |
| 18 | 2026-08-28 | dallas | 0.091 | 0.003 | 101 | 96.2 | 100.4 | 100.0 | R1 |
| 19 | 2026-09-08 | dallas | 0.090 | 0.030 | 100 | 96.4 | 100.2 | 101.0 | R4 |
| 20 | 2026-08-25 | los-angeles | 0.089 | 0.029 | 84 | 82.4 | 84.4 | 83.5 | R4,R6 |
| 21 | 2026-08-18 | dallas | 0.089 | 0.002 | 104 | 99.3 | 105.0 | 104.0 | R4,R6 |
| 22 | 2026-09-18 | los-angeles | 0.088 | 0.096 | 76 | 75.4 | 76.8 | 74.6 | R4,R6 |
| 23 | 2026-09-16 | seattle | 0.088 | 0.001 | 74 | 71.2 | 74.0 | 74.0 | - |
| 24 | 2026-09-17 | los-angeles | 0.087 | 0.098 | 76 | 74.2 | 75.8 | 73.5 | R4,R6 |
| 25 | 2026-08-15 | los-angeles | 0.087 | 0.010 | 76 | 75.2 | 76.6 | 76.0 | R2,R4,R6 |
| 26 | 2026-09-19 | los-angeles | 0.086 | 0.026 | 77 | 75.2 | 76.9 | 77.1 | R2,R4,R6 |
| 27 | 2026-09-22 | los-angeles | 0.086 | 0.005 | 76 | 74.6 | 76.5 | 76.1 | R4,R6 |
| 28 | 2026-08-24 | austin | 0.086 | 0.029 | 104 | 98.3 | 103.9 | 104.0 | R1,R6 |
| 29 | 2026-09-12 | seattle | 0.084 | 0.052 | 66 | 69.7 | 67.6 | 70.0 | R6 |
| 30 | 2026-09-25 | los-angeles | 0.083 | 0.087 | 77 | 76.5 | 77.1 | 81.0 | R2 |
| 31 | 2026-09-20 | los-angeles | 0.082 | 0.020 | 77 | 74.5 | 76.0 | 77.1 | R1,R2 |
| 32 | 2026-08-17 | atlanta | 0.082 | 0.034 | 98 | 92.6 | 98.1 | 97.0 | - |
| 33 | 2026-09-12 | dallas | 0.082 | 0.036 | 101 | 94.5 | 100.3 | 101.0 | - |
| 34 | 2026-08-20 | austin | 0.081 | 0.033 | 103 | 98.2 | 102.7 | 103.0 | R2,R4 |
| 35 | 2026-09-10 | denver | 0.079 | 0.019 | 89 | 84.8 | 87.8 | 89.0 | R1,R6 |
| 36 | 2026-09-26 | los-angeles | 0.078 | 0.067 | 81 | 79.2 | 80.5 | 84.0 | R6 |
| 37 | 2026-08-17 | austin | 0.077 | 0.028 | 103 | 98.0 | 102.4 | 102.0 | R1,R4 |
| 38 | 2026-08-25 | austin | 0.077 | 0.030 | 102 | 97.8 | 102.4 | 103.0 | R1,R4,R6 |
| 39 | 2026-08-19 | los-angeles | 0.074 | -0.006 | 80 | 79.5 | 80.8 | 81.1 | R4,R6 |
| 40 | 2026-08-17 | los-angeles | 0.073 | 0.051 | 77 | 76.5 | 77.4 | 77.8 | R4,R6 |
| 41 | 2026-09-15 | austin | 0.072 | 0.040 | 102 | 97.7 | 101.4 | 101.0 | R1,R6 |
| 42 | 2026-08-20 | atlanta | 0.072 | 0.016 | 97 | 91.7 | 96.0 | 97.0 | R1,R4 |
| 43 | 2026-08-15 | dallas | 0.072 | 0.011 | 100 | 97.5 | 100.2 | 100.0 | R4 |
| 44 | 2026-08-22 | houston | 0.071 | 0.014 | 100 | 95.5 | 100.0 | 100.0 | R1,R6 |
| 45 | 2026-08-29 | los-angeles | 0.070 | 0.017 | 85 | 84.2 | 85.0 | 83.6 | R4,R6 |
| 46 | 2026-08-23 | miami | 0.070 | 0.027 | 92 | 90.8 | 92.2 | 93.0 | R1,R3,R4 |
| 47 | 2026-08-27 | denver | 0.070 | 0.024 | 91 | 86.8 | 89.7 | 90.0 | R1,R6 |
| 48 | 2026-09-05 | miami | 0.068 | 0.019 | 91 | 88.9 | 90.2 | 90.3 | R3 |

## Analysis 3: weather regimes on high-loss days (our captured data only)

FR = frequency on the top decile / frequency on all days. The interval is crossed, with the decile recomputed
per draw; the Bonferroni interval is 99.17%. "Expected" counts the flagged top-decile days predicted from
per-market base rates.

| Regime | Freq top | Freq all | FR [95%] | FR [Bonferroni] | Flagged top days / markets | Expected | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 frontal / wind shift | 0.271 | 0.249 | 1.09 [0.09, 2.08] | [0.00, 2.49] | 13 / 8 | 10.5 | NO_SIGNAL |
| R2 low cloud / marine layer | 0.146 | 0.161 | 0.91 [0.00, 2.61] | [0.00, 3.58] | 7 / 4 | 6.0 | NO_SIGNAL |
| R3 precipitation | 0.083 | 0.224 | 0.37 [0.00, 1.37] | [0.00, 1.68] | 4 / 3 | 7.8 | NO_SIGNAL (under-represented) |
| R4 overnight-low gap >= 3 F | 0.660 | 0.406 | 1.62 [0.76, 2.23] | [0.50, 2.61] | 31 / 6 | 28.7 | NO_SIGNAL |
| R5 forecast revision >= 2 F | 0.000 | 0.032 | 0.00 [0.00, 3.15] | [0.00, 5.03] | 0 / 0 | 1.8 | NO_SIGNAL |
| R6 tendency anomaly >= 3 F | 0.553 | 0.540 | 1.02 [0.56, 1.44] | [0.36, 1.58] | 26 / 7 | 26.2 | NO_SIGNAL |

R4 is the only high point estimate. Its market-stratified expectation (28.7 of 31) shows it is mostly market
composition: the Los Angeles and Dallas overnight lows run warmer than the Open-Meteo forecast. The MG-1
residual gives the same answer: every flag is NO_SIGNAL, with R4 FR 1.36 [0.77, 1.93]. The intervals are wide
because 48 days fall in 10 markets under crossed resampling. With this panel a regime would need roughly a 2x
over-representation to be detectable.

## Analysis 4: timing

- **Arrival rule.** A centre "arrives" at the first snapshot from which it stays within 1.5 F of the outcome
  through 16:59; a centre that never arrives is scored as arriving at 17:00.
  - Top decile: the market arrives at a mean 01:36 and served at 14:45. Lead **13.2 h [9.6, 14.7]**, median
    14.0 h. The market arrives first on 100% of these days; served has not arrived by 17:00 on 14.6%.
  - All days: lead 6.85 h [5.39, 8.15]; the market arrives first on 82%.
  - **The pre-declared timing rule fires (SIGNAL)**, but the mechanism is that served lags the market. The
    market does not move in the morning.
- **Hourly centre MAE on the top decile, served / market (F):**

  | Hour | 00 | 06 | 08 | 10 | 12 | 14 | 16 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | Served | 3.71 | 3.85 | 4.17 | 3.55 | 2.38 | 1.27 | 0.86 |
  | Market | 0.64 | 0.57 | 0.55 | 0.56 | 0.60 | 0.48 | 0.48 |

  On all days the market goes 1.29 → 1.04 from 00 to 12 h, and served goes 2.59 → 2.81 (08 h) → 1.73.
- **Catch-up.** Regress the served centre change over the next 1+k hours on the market-minus-served gap at
  hours 07-12. Served closes 15% of the gap within the hour, 68% within 4 h and about 100% within 7 h. The
  market's move toward served is 0.00 to 0.01 (all days) and −0.06 (top). Served follows the market; the
  market never follows served.

## Analysis 5: what the market centre tracks (07-12 cell means)

| Product | MAE to market centre, all / top | MAE to outcome, all / top | Bias to outcome, all / top |
| --- | --- | --- | --- |
| served centre | 1.99 / 3.33 | 2.40 / 3.57 | −1.44 / −2.70 |
| MG-1 centre | 1.19 / 0.95 | 1.60 / 0.93 | +0.84 / +0.14 |
| NBM v2 mean | 1.22 / 1.01 | 1.60 / 0.94 | +0.74 / +0.02 |
| NBM v2 p50 | 1.32 / 1.18 | 1.67 / 1.04 | +0.83 / +0.21 |
| NWS grid high (raw) | 1.18 / 1.00 | 1.73 / 1.25 | +0.63 / +0.32 |
| forecast_high | 1.21 / 1.18 | 1.80 / 1.53 | +0.35 / +0.21 |
| HRRR high | 1.85 / 1.95 | 2.25 / 2.05 | +0.03 / −1.00 |
| **market centre** | — | **1.17 / 0.58** | **+0.02 / −0.02** |

Post-hoc and in-sample, labelled as such: an equal blend of NBM v2 mean, NWS grid, HRRR and forecast_high, with
walk-forward per-market debiasing, reaches MAE 1.48 F (market 1.14, served 2.26), and the market is closer on
64.7% of market-days. The residual (market minus blend) correlates 0.62 with the outcome residual, so it is
real information. Its strongest correlate among our regime variables is the overnight-low gap
(fc − obs, r = −0.26). The blend's shortfall is largest in san-francisco (2.03 vs 1.18), seattle (1.74 vs
1.09), los-angeles (1.49 vs 1.18), nyc (1.45 vs 1.08) and miami (1.38 vs 1.04), and smallest in atlanta
(1.04 vs 1.03).

## Ranked list: information the market appears to have that served lacks

1. **The guidance centre on hot days. We capture it and do not serve it, so no fetch is needed.**
   - Evidence: centre share 76.5% [63.1, 88.7]; served bias −1.44 F rising to −2.65 F in the hottest
     tercile, while the market is unbiased in every tercile; the timing lead is 13.2 h with the market right
     at 00:00.
   - On the top decile, NBM v2 mean MAE is 0.94 F against served 3.57 F, and MG-1 removes 55% of the 07-12
     excess.
   - This is the EF §2 cool bias showing up as a heat-conditional centre error. The hypothesis, **not
     tested**, is that tree models cannot extrapolate above the training range.
   - Action: a pre-registered centre lever built on captured v2 / NWS grid, of the MG-1 / EF §10q family,
     plus a trace of why served drifts 0.43 F colder from 00 to 08 h.
2. **A station-specific residual in the marine and coastal cities. Lead, no signal.**
   - About 0.34 F of centre MAE pooled, and 0.3-0.85 F in SF, Seattle, LA, NYC and Miami, is in the market
     but in no captured product or per-market debiasing.
   - R2 (low cloud from METAR ceilings) does not explain it (FR 0.91).
   - Free sources not yet tested (EXHAUSTION_REGISTER S18, S27):
     - **NWS Area Forecast Discussion text** (IEM AFOS archive, `AFDMTR`/`AFDLOX`/`AFDSEW`/`AFDOKX`/`AFDMFL`):
       forecaster reasoning on marine-layer depth, burn-off timing and sea-breeze onset;
     - **NDBC buoy SST and onshore wind** (for example 46026 off San Francisco, 46221 Santa Monica Bay): marine data has been dark
       since 2026-06-13.
   - Priority: AFD first. It is free and archived for years, and it covers the forecaster adjustment that
     the NWS grid point value only partly carries (the NWS grid is already the closest single product to the
     market).
3. **Overnight-low anomaly (observed minus forecast overnight minimum). Lead, no signal.**
   - R4 FR 1.62 [0.76, 2.23], mostly market composition; post-hoc correlation with the market residual
     r = −0.26.
   - We already capture it in METAR. It is a candidate feature for a pre-registration, not a fetch.
4. **Not supported, so do not fetch for 07-12 on this evidence:** frontal/wind shift, precipitation (radar,
   MRMS), forecast revision (multi-run), 1-min ASOS tendency. All four are NO_SIGNAL. The market centre moves
   only 0.03 F from 00 to 12 h, so it is not trading morning observations, which is consistent with the six
   null observation levers.

## Caveats

- These dev dates have been read before, so this is descriptive only. There are 11 US market clusters (no
  Toronto), and no pooled row reaches the 12-cluster power floor. The regime thresholds were pre-declared, and
  three of them have high base rates (R4 41%, R6 54%).
- A tail band's representative degree is an assumption: one band-width beyond the edge.
- The served vector is the vector of record; under EF §10v, a replay of current code differs from it.
- Market prices are captured mids per band, not tradable quotes. The market's lead says nothing about edge.

## Reproduce

```powershell
$py = "C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe"
$env:PYTHONPATH = "src;tools\research\morning_loss"
& $py tools\research\morning_loss\extract_regimes.py --replay-root <...\replay-inputs-le0929\snapshots> --layout C:\swarm\v3layout --out C:\t\l5\regimes.parquet
& $py tools\research\morning_loss\analyse.py --layout C:\swarm\v3layout --regimes C:\t\l5\regimes.parquet --out C:\t\l5\result.json
& $py tools\research\morning_loss\posthoc.py C:\swarm\v3layout
```

## Update when

Do not rewrite this record; add dated addenda.

## Addendum 2026-10-24: the overnight cold drift, traced (defect hunt, master direction 5)

**One instance traced end to end first.** Atlanta 2026-08-21 (settled 94 F). Served centre (layout, hourly
mean) 91.8 F at 00 h, 88.4 F at 07 h, 90.5 F at 12 h; market centre 91.3 → 92.2 → 91.9 F. Snapshots
`20260821T000125642349-0400`, `…T035827305991-0400` and `…T080447456334-0400` were replayed on a detached
worktree at the record's runtime commit `a76ec7b5599d` with every identity-pinned code and artifact file
sha-verified (`tools/research/morning_loss/trace_drift.py`). **Replay vs recorded vector L1 = 0.00 on all
three**, so the stage values below are what production served.

| Stage (snapshot site, `a76ec7b5`) | 00:01 | 03:58 | 08:04 |
| --- | --- | --- | --- |
| climatology_prior | 87.93 | 87.93 | 87.92 |
| **hgb_feature_model** (`model_distribution.py:808`, from `model_features.py:1283` `predict_proba`) | **91.96** | **91.40** | **87.86** |
| feature_blend (`model_distribution.py:817`) | 89.94 | 89.66 | 87.89 |
| post_live_signals (`:949`) | 91.14 | 90.75 | 88.50 |
| settlement_lag_adjusted (`:1111`) … late_day_lockin, pre_calibration | 92.01 | 91.00 | 88.54 |
| overconfidence_calibration (`:547`) = final_model (`:556`) | 92.01 | 91.00 | 88.39 |

Every stage after the HGB passes its centre through within ~0.6 F; **the drift is created inside the HGB
feature model** (−4.1 F from 00:01 to 08:04). One-at-a-time restoration of the 00:01 feature value at the 08:04
cutoff-8 model: `live_reading_temp` 75.92 → 84.02 gives +0.76 F, `high_so_far` 75.92 → 84.02 gives +0.62 F,
`rise_from_7am` +0.52, `hours_at_peak` +0.46; forecast inputs barely move (forecast_high 93.65 → 93.03).

**Mechanism (code-traced): `high_so_far` at serve is not the feature the HGB was trained on.**
- Training (`src/weather/calibration/feature_model.py:990-996`): `high_so_far = max(temps of all day rows
  with minute_of_day <= cutoff)`, the running maximum since midnight from WU history rows.
- Serve (`src/weather/model/model_base.py:46-79`, `effective_observed_high_context`): `history_high` comes from
  the `wu_history` rows (`:58`), which are empty since WU live collection was disabled on 2026-06-30 (EF §10e),
  so `effective_high = max(None, current_temp)` (`:78`): **the current temperature**, and from cutoff 07 on
  `max(current_temp, max_since_7am)` (`:79`). The METAR rows that hold the overnight readings are never
  consulted. `model_features.py:849` binds it as the `high_so_far` feature (`:1180`). Same lines on the branch
  base `4be7c077c` (`model_base.py:78-79`; `model_features.py:864`), so it is live on master.
- In this instance the night cooled from 84 F to 74 F behind a thunderstorm outflow (03:43 SPECI 32014G27KT,
  −RA); training would have shown the model `high_so_far = 84`, serve showed 75.9.

**Structural check, only after the trace (layout, 473 scored market-days):** the served `high_so_far` sits
below its own running maximum by a mean 0.16 / 1.81 / 3.02 / 3.96 / 3.88 / 2.64 / 1.34 / 0.56 F at 00 / 02 /
04 / 06 / 07 / 08 / 09 / 10 h (deficit > 0.5 F on 86-92% of 03-07 h snapshots). Served drift 00 → 08 h is
−0.10 F on days with an 08 h deficit < 1 F (190 days) and −0.92 F where it is >= 3 F (166 days); the market's
drift is −0.03 / +0.09 F on the same splits; correlation of the served drift with the 08 h deficit −0.31.
Development, descriptive, not a scored lever.

**Reading.** The overnight cold drift is a train/serve parity defect on the HGB's strongest live input, a
consequence of the WU-history outage, distinct from (and additive to) EF §2's seasonal-coverage cool bias.
A repair would source the serve-time running maximum since 00:00 from the captured METAR/station rows,
excluding the D-1 report carried in as the 00:00 row (in this instance the 84.02 F "00:00" row is the
2026-08-20 23:52 observation, the M0 `reportTime` defect that the v3 anchor excludes). That is a serving and
parity change for a pre-registration and the roll verdict, not something this lane changes.

**Prior art (master ruling 2026-10-24).** Serving WU was disabled on purpose (`5735b573`); the station
fallback (`2a878d91`) carries only the current temperature and current max (EF §4;
[GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md](../operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md)
§5a), and the `high_so_far` skew itself was measured in August (93.72% of snapshots). What this addendum adds is
the causal chain from that skew to the overnight cold centre on one byte-exact replayed instance, plus the
fleet-wide drift split; an earlier input repair was a precise null (EF §4), so the size of any gain from a fix is
open. The fix is lane L8's (bound shadow variant); this lane does not build it.

## Addendum 2026-10-24: arm A1 result (pre-registration `53fd0bc5…`)

**A1 `l5a_debias_v2_nws`: KILL** (score `49f7ee86a40d…`). 07-12 pooled: A1 − served −0.0139 [−0.0219,
−0.0060]; A1 − MG-1 −0.0001 [−0.0042, +0.0045] crossed (MDE80 0.0062), −0.0001 [−0.0024, +0.0022]
date-clustered; every hour 07-12 spans 0 against MG-1. Its gain over served is MG-1's own (MG-1 − served
−0.0139 [−0.0212, −0.0072]). Same answer as lane G's L4 blend: per-market debiasing of captured guidance adds
nothing over MG-1. For the null ledger.

## Addendum 2026-10-25: hot-day centre lever and AFD screen, all verdicts

Rules: arm A `53fd0bc5…`, arm B addendum `42d30a2f…`, AFD `e146655a…` (all committed before scoring). Every
run went through `workstation_heavy.ps1 -Kind weather_heavy` from this worktree, serially, outside the pregate
hold (L8 given slot priority). Headline 07-12 pooled `ALL`, crossed date x market 95% (date-clustered in the
last column). Development, 43 dates, 11 markets, unpowered at the 12-cluster floor.

| Rule (control) | Score | cand − served | cand − control (MDE80) | cand − control, date-clustered | Verdict |
| --- | --- | --- | --- | --- | --- |
| A1 v2+NWS per-market debias (MG-1) | `49f7ee86` | −0.0139 [−0.0219, −0.0060] | −0.0001 [−0.0042, +0.0045] (0.0062) | −0.0001 [−0.0024, +0.0022] | KILL (null) |
| A2 linear forecasts + overnight-low anomaly (MG-1) | `37710a23` | −0.0154 [−0.0228, −0.0074] | −0.0016 [−0.0059, +0.0033] (0.0068) | −0.0016 [−0.0044, +0.0011] | KILL (null) |
| B1 corpus gfs day-1 linear, full year (MG-1) | `6c2e695d` | +0.0030 [−0.0056, +0.0121] | **+0.0169 [+0.0069, +0.0269]** (0.0139) | +0.0169 [+0.0135, +0.0200] | KILL (harm) |
| B2 (v2 + B1)/2, full year (MG-1) | `47e5793e` | −0.0117 [−0.0181, −0.0053] | +0.0021 [−0.0032, +0.0084] (0.0080) | +0.0021 [−0.0012, +0.0052] | KILL (null) |
| B1 Aug-Sep-only fit (sensitivity, MG-1) | `20990cbc` | −0.0016 [−0.0097, +0.0065] | +0.0122 [+0.0043, +0.0215] (0.0120) | +0.0122 [+0.0091, +0.0151] | reported only (harm) |
| AFD features (matched coastal intercepts) | `81dea30f` | −0.0118 [−0.0192, −0.0045] | +0.0012 [−0.0006, +0.0040] (0.0032) | **+0.0012 [+0.0003, +0.0020]** | KILL (harm on the date-clustered interval) |

Reported, not decided (07-12, candidate − control, crossed):

| Subset | A1 | A2 | B2 | AFD vs matched |
| --- | --- | --- | --- | --- |
| L5 top decile (48, selected on loss) | +0.0017 [−0.0093, +0.0150] | +0.0055 [−0.0121, +0.0234] | +0.0250 [+0.0016, +0.0460] | +0.0061 [−0.0007, +0.0202] |
| Hot days (157, top v2 tercile per market) | −0.0002 [−0.0052, +0.0047] | −0.0020 [−0.0086, +0.0035] | +0.0041 [−0.0036, +0.0124] | +0.0006 [−0.0020, +0.0027] |
| Dallas (43) | −0.0040 [−0.0103, +0.0023] | −0.0019 [−0.0135, +0.0092] | +0.0109 [−0.0048, +0.0260] | 0 (not coastal) |
| Los Angeles (43) | +0.0001 [−0.0080, +0.0091] | −0.0017 [−0.0093, +0.0058] | +0.0055 [−0.0034, +0.0144] | **+0.0112 [+0.0026, +0.0195]** |
| San Francisco (43) | **+0.0120 [+0.0018, +0.0227]** | +0.0116 [−0.0006, +0.0242] | +0.0116 [+0.0009, +0.0230] | +0.0023 [−0.0016, +0.0062] |
| Coastal five (215) | +0.0028 [−0.0036, +0.0103] | +0.0014 [−0.0051, +0.0097] | +0.0033 [−0.0058, +0.0124] | +0.0025 [−0.0015, +0.0087] |

Per hour 07..12 every A1/A2 cell spans 0 against MG-1 (A2 −0.0006 to −0.0020). Full per-market and per-hour
tables: `tools/research/morning_loss/verdicts.py C:\t\l5\scores`.

**Reading.**
- **The hot-day centre lever is MG-1 itself.** Every arm A gain over served is MG-1's (MG-1 − served −0.0139
  [−0.0212, −0.0072] at 07-12; −0.0587/−0.0549 on the top decile for A1/A2 vs served). Neither a per-market
  debias nor a regression adds anything over it, on any subset.
- **The tree-extrapolation explanation is not where the residual is.** A2 predicts above its fold's training
  maximum on 8.8% of its 07-12 snapshots (1,853 of 21,034) and still gains nothing over MG-1 on hot days
  (−0.0020 [−0.0086, +0.0035]). Captured guidance already carries the heat; what served lacks is the guidance
  centre (and the `high_so_far` parity repair, lane L8), not an extrapolating fit.
- **Arm B: full-year coverage does not help this form.** With the one regressor the corpus has (gfs day-1
  high), the full-year fit harms more than the Aug-Sep fit (+0.0169 vs +0.0122 over MG-1); its slopes (0.88-0.95,
  Aug-Sep 0.70-0.85) shrink hot days toward the mean, the opposite of what the hot days need. Arm B says
  nothing about the HGB retrain itself (L1's lane), only that this corpus field is not a centre source.
- **AFD (item 2): KILL.** The text features slightly harm, mostly in Los Angeles; no lead, so no capture case.
  The coastal residual stays unexplained by free text.

For the null ledger: A1, A2, B1, B2, AFD (development, 2026-10-25).
