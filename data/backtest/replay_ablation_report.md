# Per-Source Ablation Replay

Generated: 2026-06-09 18:51

Each captured snapshot is replayed with the current code on its
captured sources (baseline) and again with one source knocked out
(`ok: False`, identical to a fetch outage). Delta = ablated Brier
minus baseline Brier on matched rows: **positive = the source was
helping** (removing it hurts), negative = the model scored better
without it.

Days scored: 51  |  reconstructed records included: no

## Source Value Summary

| Variant | Rows | Days | Baseline Brier | Ablated Brier | Delta (source value) | Days helped | Days hurt | Market Brier |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all_forecasts | 53504 | 51 | 0.0570 | 0.0842 | +0.0271 | 40 | 3 | 0.0355 |
| weather_forecast | 53504 | 51 | 0.0570 | 0.0606 | +0.0035 | 26 | 15 | 0.0355 |
| eccc_citypage | 8481 | 7 | 0.0465 | 0.0482 | +0.0017 | 3 | 3 | 0.0396 |
| metar | 53504 | 51 | 0.0570 | 0.0573 | +0.0003 | 18 | 7 | 0.0355 |
| wu_current | 53504 | 51 | 0.0570 | 0.0570 | -0.0000 | 26 | 11 | 0.0355 |
| open_meteo | 53504 | 51 | 0.0570 | 0.0570 | -0.0000 | 20 | 22 | 0.0355 |
| eccc_swob | 8481 | 7 | 0.0465 | 0.0460 | -0.0006 | 3 | 2 | 0.0396 |

## By Family (delta, positive = source helps)

| Variant | toronto | us_f |
| :--- | ---: | ---: |
| all_forecasts | +0.0314 | +0.0263 |
| weather_forecast | +0.0059 | +0.0031 |
| eccc_citypage | +0.0017 | - |
| metar | +0.0000 | +0.0003 |
| wu_current | +0.0003 | -0.0001 |
| open_meteo | -0.0006 | +0.0001 |
| eccc_swob | -0.0006 | - |

## Largest Per-Day Effects

### all_forecasts

| Day | Delta | Rows |
| :--- | ---: | ---: |
| toronto 2026-06-09 | -0.0401 | 781 |
| nyc 2026-06-06 | -0.0041 | 374 |
| atlanta 2026-06-06 | -0.0018 | 264 |
| toronto 2026-06-05 | +0.0525 | 1518 |
| denver 2026-06-07 | +0.0551 | 1540 |
| denver 2026-06-09 | +0.0654 | 638 |

### weather_forecast

| Day | Delta | Rows |
| :--- | ---: | ---: |
| san-francisco 2026-06-08 | -0.0094 | 1474 |
| houston 2026-06-09 | -0.0087 | 704 |
| los-angeles 2026-06-09 | -0.0082 | 616 |
| dallas 2026-06-08 | +0.0150 | 1518 |
| seattle 2026-06-09 | +0.0202 | 616 |
| dallas 2026-06-09 | +0.0359 | 704 |

### eccc_citypage

| Day | Delta | Rows |
| :--- | ---: | ---: |
| toronto 2026-06-07 | -0.0026 | 1540 |
| toronto 2026-06-08 | -0.0016 | 1518 |
| toronto 2026-06-09 | -0.0015 | 781 |
| toronto 2026-06-05 | +0.0029 | 1518 |
| toronto 2026-06-04 | +0.0048 | 1573 |
| toronto 2026-06-06 | +0.0074 | 1320 |

### metar

| Day | Delta | Rows |
| :--- | ---: | ---: |
| nyc 2026-06-06 | -0.0032 | 374 |
| seattle 2026-06-09 | -0.0012 | 616 |
| los-angeles 2026-06-07 | -0.0010 | 1540 |
| denver 2026-06-08 | +0.0021 | 1518 |
| dallas 2026-06-07 | +0.0037 | 1540 |
| los-angeles 2026-06-09 | +0.0041 | 616 |

### wu_current

| Day | Delta | Rows |
| :--- | ---: | ---: |
| chicago 2026-06-09 | -0.0108 | 704 |
| san-francisco 2026-06-07 | -0.0046 | 1540 |
| san-francisco 2026-06-09 | -0.0029 | 616 |
| dallas 2026-06-09 | +0.0033 | 704 |
| atlanta 2026-06-09 | +0.0042 | 770 |
| denver 2026-06-06 | +0.0059 | 385 |

### open_meteo

| Day | Delta | Rows |
| :--- | ---: | ---: |
| nyc 2026-06-08 | -0.0256 | 1518 |
| seattle 2026-06-09 | -0.0227 | 616 |
| toronto 2026-06-09 | -0.0172 | 781 |
| denver 2026-06-08 | +0.0128 | 1518 |
| houston 2026-06-08 | +0.0167 | 1518 |
| chicago 2026-06-08 | +0.0207 | 1518 |

### eccc_swob

| Day | Delta | Rows |
| :--- | ---: | ---: |
| toronto 2026-06-08 | -0.0077 | 1518 |
| toronto 2026-06-06 | -0.0003 | 1320 |
| toronto 2026-06-03 | +0.0000 | 231 |
| toronto 2026-06-07 | +0.0008 | 1540 |
| toronto 2026-06-09 | +0.0020 | 781 |
| toronto 2026-06-04 | +0.0028 | 1573 |

