# Probability Calibration Report

Generated: 2026-05-31T15:26:32.411694+00:00

## Scope

- Training rows: 1760
- Target dates: 2026-05-27, 2026-05-28, 2026-05-30
- Baseline Brier: 0.0954
- Baseline log loss: 0.3705
- Market Brier: 0.0382
- Market log loss: 0.1177
- Baseline Brier skill vs market: -1.500
- Selected Brier skill vs market: -1.031
- Artifact replay Brier: 0.0762
- Artifact replay log loss: 0.2309
- Artifact replay Brier skill vs market: -0.997

## Selected Deployable Calibrator

- Method: `prior_shrink`
- Parameter: `0.6`
- LOO Brier: 0.0775
- LOO log loss: 0.2743

## Market-Informed Baseline

- Method: `market_shrink`
- Parameter: `1.0`
- LOO Brier: 0.0382
- LOO log loss: 0.1177

## Candidate Comparison

| Method | Param | LOO Brier | LOO Log Loss |
| :--- | :--- | :--- | :--- |
| market_shrink | 1.0 | 0.0382 | 0.1177 |
| market_shrink | 0.9 | 0.0392 | 0.1242 |
| market_shrink | 0.8 | 0.0413 | 0.1317 |
| market_shrink | 0.7 | 0.0445 | 0.1405 |
| market_shrink | 0.6 | 0.0487 | 0.1507 |
| market_shrink | 0.5 | 0.0539 | 0.1626 |
| market_shrink | 0.4 | 0.0601 | 0.1769 |
| market_shrink | 0.3 | 0.0674 | 0.1946 |
| market_shrink | 0.2 | 0.0757 | 0.2178 |
| prior_shrink | 0.6 | 0.0775 | 0.2743 |
| prior_shrink | 0.7 | 0.0775 | 0.2771 |
| prior_shrink | 0.5 | 0.0783 | 0.2738 |
| prior_shrink | 0.8 | 0.0784 | 0.2825 |
| prior_shrink | 0.4 | 0.0800 | 0.2759 |
| prior_shrink | 0.9 | 0.0801 | 0.2910 |
| prior_shrink | 0.3 | 0.0826 | 0.2813 |
| market_shrink | 0.1 | 0.0850 | 0.2531 |
| platt | - | 0.0852 | 0.2821 |
| prior_shrink | 0.2 | 0.0860 | 0.2915 |
| temperature | 3.0 | 0.0888 | 0.2746 |
| temperature | 2.0 | 0.0889 | 0.2775 |
| prior_shrink | 0.1 | 0.0903 | 0.3110 |
| temperature | 1.5 | 0.0910 | 0.3003 |
| temperature | 4.0 | 0.0916 | 0.2910 |
| temperature | 1.2 | 0.0932 | 0.3326 |
| identity | - | 0.0954 | 0.3705 |
| temperature | 5.0 | 0.0959 | 0.3136 |
| isotonic | - | 0.0973 | 0.7558 |

## Exact Distribution Calibration

- Method: `temperature`
- Temperature: `1.5`
- Max deployment temperature: `1.5`
- Unconstrained best temperature: `3.0`
- Exact-row count: 1440

## Context Summaries

The live calibrator falls back through context keys in this order: `kind+hour+distance`, `kind+distance`, `kind+hour`, `kind`, `global`.

| Context | N | Smoothed Base Rate |
| :--- | :--- | :--- |
| global | 1760 | 9.2% |
| kind=eq | 1440 | 11.2% |
| kind=eq|distance=at_floor | 157 | 32.3% |
| kind=eq|distance=below_floor | 648 | 0.3% |
| kind=eq|distance=one_above | 160 | 21.3% |
| kind=eq|distance=three_plus_above | 315 | 13.2% |
| kind=eq|distance=two_above | 160 | 23.8% |
| kind=eq|hour=10 | 72 | 13.2% |
| kind=eq|hour=11 | 99 | 12.6% |
| kind=eq|hour=11|distance=three_plus_above | 51 | 23.6% |
| kind=eq|hour=12 | 90 | 12.8% |
| kind=eq|hour=13 | 63 | 13.4% |
| kind=eq|hour=14 | 135 | 12.2% |
| kind=eq|hour=14|distance=below_floor | 62 | 3.0% |
| kind=eq|hour=15 | 162 | 12.0% |
| kind=eq|hour=15|distance=below_floor | 78 | 2.4% |
| kind=eq|hour=16 | 162 | 12.0% |
| kind=eq|hour=16|distance=below_floor | 82 | 2.3% |
| kind=eq|hour=17 | 153 | 12.1% |
| kind=eq|hour=17|distance=below_floor | 82 | 2.3% |
| kind=eq|hour=18 | 153 | 12.1% |
| kind=eq|hour=18|distance=below_floor | 86 | 2.2% |
| kind=eq|hour=19 | 153 | 12.1% |
| kind=eq|hour=19|distance=below_floor | 84 | 2.3% |
| kind=eq|hour=20 | 81 | 12.9% |
| kind=eq|hour=20|distance=below_floor | 46 | 4.0% |
| kind=eq|hour=21 | 54 | 13.8% |
| kind=eq|hour=9 | 54 | 13.8% |
| kind=gte | 160 | 1.2% |
| kind=gte|distance=three_plus_above | 160 | 1.2% |
| kind=lte | 160 | 1.2% |
| kind=lte|distance=below_floor | 157 | 1.2% |
