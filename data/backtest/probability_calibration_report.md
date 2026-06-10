# Probability Calibration Report

Generated: 2026-06-10T15:32:27.094504+00:00

## Scope

- Training rows: 4763
- Target dates: 2026-05-28, 2026-06-01, 2026-06-02, 2026-06-07
- Baseline Brier: 0.0536
- Baseline log loss: 0.1748
- Market Brier: 0.0401
- Market log loss: 0.1245
- Baseline Brier skill vs market: -0.336
- Selected Brier skill vs market: -0.336
- Artifact replay Brier: 0.0536
- Artifact replay log loss: 0.1748
- Artifact replay Brier skill vs market: -0.336

## Selected Deployable Calibrator

- Method: `identity`
- Parameter: `None`
- LOO Brier: 0.0536
- LOO log loss: 0.1748

## Market-Informed Baseline

- Method: `market_shrink`
- Parameter: `1.0`
- LOO Brier: 0.0401
- LOO log loss: 0.1245

## Candidate Comparison

| Method | Param | LOO Brier | LOO Log Loss |
| :--- | :--- | :--- | :--- |
| market_shrink | 1.0 | 0.0401 | 0.1245 |
| market_shrink | 0.9 | 0.0405 | 0.1273 |
| market_shrink | 0.8 | 0.0410 | 0.1304 |
| market_shrink | 0.7 | 0.0418 | 0.1338 |
| market_shrink | 0.6 | 0.0428 | 0.1375 |
| market_shrink | 0.5 | 0.0441 | 0.1417 |
| market_shrink | 0.4 | 0.0455 | 0.1463 |
| market_shrink | 0.3 | 0.0472 | 0.1515 |
| market_shrink | 0.2 | 0.0491 | 0.1574 |
| market_shrink | 0.1 | 0.0512 | 0.1645 |
| identity | - | 0.0536 | 0.1748 |
| isotonic | - | 0.0537 | 0.1865 |
| platt | - | 0.0539 | 0.1754 |
| prior_shrink | 0.1 | 0.0540 | 0.1803 |
| temperature | 1.2 | 0.0541 | 0.1784 |
| prior_shrink | 0.2 | 0.0549 | 0.1871 |
| temperature | 1.5 | 0.0563 | 0.1890 |
| prior_shrink | 0.3 | 0.0564 | 0.1951 |
| prior_shrink | 0.4 | 0.0585 | 0.2042 |
| prior_shrink | 0.5 | 0.0611 | 0.2146 |
| temperature | 2.0 | 0.0618 | 0.2113 |
| prior_shrink | 0.6 | 0.0643 | 0.2265 |
| prior_shrink | 0.7 | 0.0680 | 0.2402 |
| prior_shrink | 0.8 | 0.0723 | 0.2565 |
| temperature | 3.0 | 0.0743 | 0.2553 |
| prior_shrink | 0.9 | 0.0772 | 0.2768 |
| temperature | 4.0 | 0.0859 | 0.2946 |
| temperature | 5.0 | 0.0963 | 0.3291 |

## Exact Distribution Calibration

- Method: `temperature`
- Temperature (global fallback): `1.0`
- Temperature by cutoff hour: `{'0': 1.067, '1': 1.067, '2': 1.067, '3': 1.067, '4': 1.067, '5': 1.067, '6': 1.067, '7': 1.067, '8': 1.086, '9': 1.1, '10': 1.0, '11': 1.1, '12': 1.25, '13': 1.0, '14': 1.1, '15': 1.1, '16': 1.25, '17': 1.0, '18': 1.0, '19': 1.0, '20': 1.0, '21': 1.0, '22': 1.0, '23': 1.0}`
- Max deployment temperature: `1.5`
- Unconstrained best temperature: `1.0`
- Exact-row count: 3897

## Context Summaries

The live calibrator falls back through context keys in this order: `kind+hour+distance`, `kind+distance`, `kind+hour`, `kind`, `global`.

| Context | N | Smoothed Base Rate |
| :--- | :--- | :--- |
| global | 4763 | 9.1% |
| kind=eq | 3897 | 11.2% |
| kind=eq|distance=at_floor | 307 | 51.1% |
| kind=eq|distance=below_floor | 1117 | 0.2% |
| kind=eq|distance=one_above | 377 | 20.7% |
| kind=eq|distance=three_plus_above | 1757 | 10.3% |
| kind=eq|distance=two_above | 321 | 6.2% |
| kind=eq|hour=0 | 108 | 12.5% |
| kind=eq|hour=0|distance=three_plus_above | 80 | 14.3% |
| kind=eq|hour=1 | 108 | 12.5% |
| kind=eq|hour=10 | 216 | 11.8% |
| kind=eq|hour=10|distance=three_plus_above | 132 | 14.7% |
| kind=eq|hour=11 | 198 | 11.9% |
| kind=eq|hour=11|distance=three_plus_above | 106 | 17.3% |
| kind=eq|hour=12 | 216 | 11.8% |
| kind=eq|hour=12|distance=below_floor | 57 | 3.3% |
| kind=eq|hour=12|distance=three_plus_above | 87 | 19.8% |
| kind=eq|hour=13 | 207 | 11.8% |
| kind=eq|hour=13|distance=below_floor | 75 | 2.5% |
| kind=eq|hour=13|distance=three_plus_above | 63 | 9.0% |
| kind=eq|hour=14 | 216 | 11.8% |
| kind=eq|hour=14|distance=below_floor | 88 | 2.2% |
| kind=eq|hour=14|distance=three_plus_above | 58 | 3.2% |
| kind=eq|hour=15 | 216 | 11.8% |
| kind=eq|hour=15|distance=below_floor | 97 | 2.0% |
| kind=eq|hour=15|distance=three_plus_above | 53 | 3.5% |
| kind=eq|hour=16 | 216 | 11.8% |
| kind=eq|hour=16|distance=below_floor | 102 | 1.9% |
| kind=eq|hour=16|distance=three_plus_above | 48 | 3.8% |
| kind=eq|hour=17 | 207 | 11.8% |
| kind=eq|hour=17|distance=below_floor | 104 | 1.9% |
| kind=eq|hour=17|distance=three_plus_above | 40 | 4.5% |
| kind=eq|hour=18 | 207 | 11.8% |
| kind=eq|hour=18|distance=below_floor | 111 | 1.7% |
| kind=eq|hour=19 | 207 | 11.8% |
| kind=eq|hour=19|distance=below_floor | 108 | 1.8% |
| kind=eq|hour=1|distance=three_plus_above | 96 | 14.0% |
| kind=eq|hour=2 | 108 | 12.5% |
| kind=eq|hour=20 | 162 | 12.0% |
| kind=eq|hour=20|distance=below_floor | 78 | 2.4% |
| kind=eq|hour=21 | 162 | 12.0% |
| kind=eq|hour=21|distance=below_floor | 78 | 2.4% |
| kind=eq|hour=22 | 162 | 12.0% |
| kind=eq|hour=22|distance=below_floor | 78 | 2.4% |
| kind=eq|hour=23 | 153 | 12.1% |
| kind=eq|hour=23|distance=below_floor | 75 | 2.5% |
| kind=eq|hour=2|distance=three_plus_above | 96 | 14.0% |
| kind=eq|hour=3 | 108 | 12.5% |
| kind=eq|hour=3|distance=three_plus_above | 96 | 14.0% |
| kind=eq|hour=4 | 108 | 12.5% |
| kind=eq|hour=4|distance=three_plus_above | 96 | 14.0% |
| kind=eq|hour=5 | 108 | 12.5% |
| kind=eq|hour=5|distance=three_plus_above | 96 | 14.0% |
| kind=eq|hour=6 | 108 | 12.5% |
| kind=eq|hour=6|distance=three_plus_above | 96 | 14.0% |
| kind=eq|hour=7 | 99 | 12.6% |
| kind=eq|hour=7|distance=three_plus_above | 89 | 14.0% |
| kind=eq|hour=8 | 117 | 12.4% |
| kind=eq|hour=8|distance=three_plus_above | 100 | 14.4% |
| kind=eq|hour=9 | 180 | 12.0% |
| kind=eq|hour=9|distance=three_plus_above | 115 | 16.8% |
| kind=gte | 433 | 0.5% |
| kind=gte|distance=three_plus_above | 375 | 0.5% |
| kind=gte|distance=two_above | 56 | 3.3% |
| kind=lte | 433 | 0.5% |
| kind=lte|distance=at_floor | 70 | 2.7% |
| kind=lte|distance=below_floor | 307 | 0.6% |
| kind=lte|distance=two_above | 54 | 3.4% |
