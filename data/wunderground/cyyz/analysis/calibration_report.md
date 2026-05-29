# Intraday Calibration Report

Generated at: 2026-05-27 21:15:31

## Design

The empirical intraday model is calibrated as a per-cutoff-hour weighted ensemble of six probability components.

- `climatology`: base target-season distribution.
- `intraday_high`: final-bucket distribution conditioned on high so far.
- `current_bucket`: final-bucket distribution conditioned on latest/current bucket.
- `wind_regime`: final-bucket distribution conditioned on live wind group.
- `cloud_regime`: final-bucket distribution conditioned on live cloud group.
- `forecast_cap`: non-leaky forecast-cap proxy from training data; live use maps this weight onto the available forecast cap.

Validation is leave-one-year-out so every target day is scored against years other than its own.

## Exact Bucket Metrics

| Cutoff | Days | Base Log Loss | Opt Log Loss | Base Brier | Opt Brier | Base Top Acc | Opt Top Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 652 | 2.8702 | 2.4394 | 0.9283 | 0.8984 | 16.3% | 14.7% |
| 10:00 | 652 | 2.7990 | 2.2622 | 0.9214 | 0.8805 | 15.6% | 17.3% |
| 12:00 | 652 | 2.5824 | 1.9279 | 0.8915 | 0.8295 | 21.9% | 27.1% |
| 13:00 | 652 | 2.4063 | 1.7042 | 0.8588 | 0.7865 | 21.0% | 26.1% |
| 15:00 | 652 | 1.9529 | 1.0668 | 0.7232 | 0.5441 | 60.1% | 62.3% |
| 16:00 | 652 | 1.5269 | 0.6086 | 0.5751 | 0.2886 | 81.9% | 82.7% |
| 17:00 | 652 | 1.2421 | 0.3156 | 0.4599 | 0.1212 | 90.3% | 94.2% |
| 18:00 | 652 | 1.1439 | 0.1632 | 0.4183 | 0.0459 | 93.7% | 98.2% |
| 20:00 | 652 | 1.0610 | 0.0540 | 0.3923 | 0.0069 | 96.2% | 100.0% |

## Market-Bin Metrics

Market-bin metrics score the cumulative edge cases separately: `19 C or below`, exact buckets between them, and `29 C or higher`.

| Cutoff | Base Group Log Loss | Opt Group Log Loss | Base Group Brier | Opt Group Brier | Base Group Acc | Opt Group Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 1.8673 | 1.5088 | 0.7369 | 0.6206 | 40.8% | 51.8% |
| 10:00 | 1.8239 | 1.3935 | 0.7224 | 0.5815 | 40.8% | 53.1% |
| 12:00 | 1.6925 | 1.1865 | 0.6824 | 0.5241 | 41.6% | 58.7% |
| 13:00 | 1.5775 | 1.0291 | 0.6520 | 0.4873 | 41.9% | 56.6% |
| 15:00 | 1.2560 | 0.6137 | 0.5442 | 0.3100 | 60.7% | 80.1% |
| 16:00 | 0.9887 | 0.3077 | 0.4329 | 0.1347 | 91.6% | 92.9% |
| 17:00 | 0.8162 | 0.1501 | 0.3526 | 0.0509 | 96.2% | 97.5% |
| 18:00 | 0.7676 | 0.0659 | 0.3333 | 0.0116 | 97.5% | 99.5% |
| 20:00 | 0.7417 | 0.0333 | 0.3241 | 0.0018 | 98.6% | 100.0% |

## Learned Weights

| Cutoff | Climatology | Intraday High | Current Bucket | Wind | Cloud | Forecast Cap |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 0.000 | 0.133 | 0.548 | 0.025 | 0.000 | 0.295 |
| 10:00 | 0.000 | 0.188 | 0.549 | 0.000 | 0.000 | 0.263 |
| 12:00 | 0.000 | 0.499 | 0.359 | 0.000 | 0.000 | 0.142 |
| 13:00 | 0.000 | 0.835 | 0.042 | 0.000 | 0.000 | 0.122 |
| 15:00 | 0.000 | 0.873 | 0.000 | 0.000 | 0.000 | 0.127 |
| 16:00 | 0.000 | 0.920 | 0.000 | 0.000 | 0.000 | 0.080 |
| 17:00 | 0.000 | 0.951 | 0.000 | 0.000 | 0.000 | 0.049 |
| 18:00 | 0.000 | 0.956 | 0.000 | 0.000 | 0.000 | 0.044 |
| 20:00 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Component Availability

| Cutoff | Intraday High | Current Bucket | Wind | Cloud | Forecast Cap |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 95.9% | 96.5% | 100.0% | 97.1% | 100.0% |
| 10:00 | 96.6% | 95.7% | 99.8% | 97.5% | 100.0% |
| 12:00 | 95.7% | 96.0% | 100.0% | 97.5% | 100.0% |
| 13:00 | 94.9% | 93.4% | 100.0% | 97.4% | 100.0% |
| 15:00 | 92.2% | 94.6% | 99.8% | 97.5% | 100.0% |
| 16:00 | 95.7% | 94.6% | 99.8% | 97.1% | 100.0% |
| 17:00 | 96.2% | 93.6% | 100.0% | 97.4% | 100.0% |
| 18:00 | 95.6% | 95.2% | 100.0% | 97.7% | 100.0% |
| 20:00 | 96.2% | 97.9% | 99.8% | 97.4% | 100.0% |
