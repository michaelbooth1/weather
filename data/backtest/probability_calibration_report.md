# Probability Calibration Report

Generated: 2026-06-03T20:54:26.315467+00:00

## Scope

- Training rows: 4906
- Target dates: 2026-05-27, 2026-05-28, 2026-05-30, 2026-05-31, 2026-06-01, 2026-06-02
- Baseline Brier: 0.0680
- Baseline log loss: 0.2439
- Market Brier: 0.0325
- Market log loss: 0.1047
- Baseline Brier skill vs market: -1.090
- Selected Brier skill vs market: -1.024
- Artifact replay Brier: 0.0680
- Artifact replay log loss: 0.2439
- Artifact replay Brier skill vs market: -1.090

## Selected Deployable Calibrator

- Method: `prior_shrink`
- Parameter: `0.3`
- LOO Brier: 0.0658
- LOO log loss: 0.2249

## Market-Informed Baseline

- Method: `market_shrink`
- Parameter: `1.0`
- LOO Brier: 0.0325
- LOO log loss: 0.1047

## Candidate Comparison

| Method | Param | LOO Brier | LOO Log Loss |
| :--- | :--- | :--- | :--- |
| market_shrink | 1.0 | 0.0325 | 0.1047 |
| market_shrink | 0.9 | 0.0336 | 0.1102 |
| market_shrink | 0.8 | 0.0352 | 0.1162 |
| market_shrink | 0.7 | 0.0373 | 0.1229 |
| market_shrink | 0.6 | 0.0400 | 0.1304 |
| market_shrink | 0.5 | 0.0433 | 0.1388 |
| market_shrink | 0.4 | 0.0471 | 0.1484 |
| market_shrink | 0.3 | 0.0515 | 0.1596 |
| market_shrink | 0.2 | 0.0565 | 0.1734 |
| market_shrink | 0.1 | 0.0620 | 0.1925 |
| prior_shrink | 0.3 | 0.0658 | 0.2249 |
| prior_shrink | 0.2 | 0.0659 | 0.2234 |
| prior_shrink | 0.4 | 0.0664 | 0.2290 |
| prior_shrink | 0.1 | 0.0667 | 0.2260 |
| prior_shrink | 0.5 | 0.0675 | 0.2351 |
| temperature | 1.2 | 0.0678 | 0.2331 |
| identity | - | 0.0680 | 0.2439 |
| temperature | 1.5 | 0.0686 | 0.2286 |
| prior_shrink | 0.6 | 0.0693 | 0.2431 |
| isotonic | - | 0.0709 | 0.3715 |
| temperature | 2.0 | 0.0716 | 0.2341 |
| prior_shrink | 0.7 | 0.0717 | 0.2532 |
| platt | - | 0.0718 | 0.2501 |
| prior_shrink | 0.8 | 0.0747 | 0.2659 |
| prior_shrink | 0.9 | 0.0784 | 0.2821 |
| temperature | 3.0 | 0.0794 | 0.2590 |
| temperature | 4.0 | 0.0872 | 0.2879 |
| temperature | 5.0 | 0.0947 | 0.3168 |

## Exact Distribution Calibration

- Method: `temperature`
- Temperature: `1.2`
- Max deployment temperature: `1.5`
- Unconstrained best temperature: `1.2`
- Exact-row count: 4014

## Context Summaries

The live calibrator falls back through context keys in this order: `kind+hour+distance`, `kind+distance`, `kind+hour`, `kind`, `global`.

| Context | N | Smoothed Base Rate |
| :--- | :--- | :--- |
| global | 4906 | 9.1% |
| kind=eq | 4014 | 11.1% |
| kind=eq|distance=at_floor | 385 | 48.6% |
| kind=eq|distance=below_floor | 1660 | 0.1% |
| kind=eq|distance=one_above | 391 | 18.7% |
| kind=eq|distance=three_plus_above | 1266 | 10.5% |
| kind=eq|distance=two_above | 303 | 18.6% |
| kind=eq|hour=0 | 54 | 13.8% |
| kind=eq|hour=0|distance=three_plus_above | 45 | 14.3% |
| kind=eq|hour=1 | 54 | 13.8% |
| kind=eq|hour=10 | 198 | 11.9% |
| kind=eq|hour=10|distance=three_plus_above | 114 | 15.3% |
| kind=eq|hour=11 | 252 | 11.7% |
| kind=eq|hour=11|distance=below_floor | 57 | 3.3% |
| kind=eq|hour=11|distance=three_plus_above | 112 | 21.6% |
| kind=eq|hour=12 | 243 | 11.7% |
| kind=eq|hour=12|distance=below_floor | 86 | 2.2% |
| kind=eq|hour=12|distance=three_plus_above | 76 | 25.0% |
| kind=eq|hour=13 | 225 | 11.8% |
| kind=eq|hour=13|distance=below_floor | 107 | 1.8% |
| kind=eq|hour=13|distance=three_plus_above | 43 | 6.4% |
| kind=eq|hour=14 | 288 | 11.6% |
| kind=eq|hour=14|distance=below_floor | 141 | 1.4% |
| kind=eq|hour=14|distance=three_plus_above | 55 | 10.2% |
| kind=eq|hour=15 | 324 | 11.6% |
| kind=eq|hour=15|distance=below_floor | 175 | 1.1% |
| kind=eq|hour=15|distance=three_plus_above | 53 | 3.5% |
| kind=eq|hour=16 | 324 | 11.6% |
| kind=eq|hour=16|distance=below_floor | 184 | 1.1% |
| kind=eq|hour=16|distance=three_plus_above | 44 | 4.2% |
| kind=eq|hour=17 | 315 | 11.6% |
| kind=eq|hour=17|distance=below_floor | 184 | 1.1% |
| kind=eq|hour=18 | 315 | 11.6% |
| kind=eq|hour=18|distance=below_floor | 188 | 1.0% |
| kind=eq|hour=19 | 315 | 11.6% |
| kind=eq|hour=19|distance=below_floor | 186 | 1.1% |
| kind=eq|hour=1|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=2 | 54 | 13.8% |
| kind=eq|hour=20 | 189 | 11.9% |
| kind=eq|hour=20|distance=below_floor | 106 | 1.8% |
| kind=eq|hour=21 | 162 | 12.0% |
| kind=eq|hour=21|distance=below_floor | 90 | 2.1% |
| kind=eq|hour=22 | 108 | 12.5% |
| kind=eq|hour=22|distance=below_floor | 60 | 3.1% |
| kind=eq|hour=23 | 108 | 12.5% |
| kind=eq|hour=23|distance=below_floor | 60 | 3.1% |
| kind=eq|hour=2|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=3 | 54 | 13.8% |
| kind=eq|hour=3|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=4 | 54 | 13.8% |
| kind=eq|hour=4|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=5 | 54 | 13.8% |
| kind=eq|hour=5|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=6 | 54 | 13.8% |
| kind=eq|hour=6|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=7 | 54 | 13.8% |
| kind=eq|hour=7|distance=three_plus_above | 54 | 13.8% |
| kind=eq|hour=8 | 81 | 12.9% |
| kind=eq|hour=8|distance=three_plus_above | 72 | 14.5% |
| kind=eq|hour=9 | 135 | 12.2% |
| kind=eq|hour=9|distance=three_plus_above | 80 | 17.9% |
| kind=gte | 446 | 0.4% |
| kind=gte|distance=three_plus_above | 357 | 0.6% |
| kind=gte|distance=two_above | 88 | 2.2% |
| kind=lte | 446 | 0.4% |
| kind=lte|distance=below_floor | 385 | 0.5% |
| kind=lte|distance=two_above | 54 | 3.4% |
