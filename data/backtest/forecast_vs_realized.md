# Forecast vs Realized Tracker

Settled days: 7  |  verdict cutoff: 09:00

## Verdict: is the model's morning forecast-skepticism costing or saving?

**SKEPTICISM IS COSTING** -- the morning forecast is reached 71% of the time, but the model gives it only 45% -- it UNDER-calls the high; trusting the forecast more would help.

| Reach-rate (realized >= forecast) | Model gives | Market gives | Consensus bias (realized-forecast) | N |
| :--- | :--- | :--- | :--- | :--- |
| 71% | 45% | 66% | -0.31 C | 7 |

> Bias > 0 means the forecast UNDER-calls the realized high; < 0 means it OVER-calls.

## Cutoff 07:00  (7 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 7 | -0.01 | 0.61 | 57% |
| weather_com | 7 | +0.29 | 0.57 | 43% |
| eccc | 7 | -0.71 | 0.71 | 43% |
| consensus | 7 | -0.24 | 0.39 | 71% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 71% | 41% | 66% | 1.00 | 0.43 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | snapshot_high |
| 2026-05-28 | 20.20 | 20 | 20 | yes | 40% | 53% | snapshot_high |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 37% | 78% | snapshot_high |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 19% | 68% | snapshot_high |
| 2026-06-01 | 20.20 | 20 | 19 | no | 75% | 87% | snapshot_high |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 43% | 67% | snapshot_high |
| 2026-06-03 | 28.50 | 29 | 29 | yes | 37% | 86% | snapshot_high |

## Cutoff 09:00  (7 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 7 | -0.24 | 0.44 | 71% |
| weather_com | 7 | +0.14 | 0.43 | 57% |
| eccc | 7 | -0.71 | 0.71 | 43% |
| consensus | 7 | -0.31 | 0.31 | 71% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 71% | 45% | 66% | 0.86 | 0.43 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | snapshot_high |
| 2026-05-28 | 20.20 | 20 | 20 | yes | 40% | 49% | snapshot_high |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 37% | 78% | snapshot_high |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 20% | 71% | snapshot_high |
| 2026-06-01 | 20.20 | 20 | 19 | no | 75% | 87% | snapshot_high |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 35% | 68% | snapshot_high |
| 2026-06-03 | 29.00 | 29 | 29 | yes | 77% | 84% | snapshot_high |

## Cutoff 11:00  (7 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 7 | -0.06 | 0.49 | 71% |
| weather_com | 7 | +0.14 | 0.43 | 57% |
| eccc | 7 | -1.29 | 1.29 | 14% |
| consensus | 7 | -0.23 | 0.31 | 71% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 71% | 54% | 69% | 0.71 | 0.43 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | snapshot_high |
| 2026-05-28 | 19.70 | 20 | 20 | yes | 52% | 46% | snapshot_high |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 37% | 79% | snapshot_high |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 66% | 82% | snapshot_high |
| 2026-06-01 | 20.10 | 20 | 19 | no | 80% | 94% | snapshot_high |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 32% | 75% | snapshot_high |
| 2026-06-03 | 29.00 | 29 | 29 | yes | 77% | 83% | snapshot_high |

## Cutoff 13:00  (7 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 7 | +0.21 | 0.56 | 71% |
| weather_com | 7 | +0.00 | 0.57 | 43% |
| eccc | 7 | -1.29 | 1.29 | 14% |
| consensus | 7 | -0.21 | 0.30 | 71% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 71% | 56% | 67% | 0.71 | 0.43 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | snapshot_high |
| 2026-05-28 | 19.70 | 20 | 20 | yes | 44% | 54% | snapshot_high |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 23% | 61% | snapshot_high |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 21% | 75% | snapshot_high |
| 2026-06-01 | 20.00 | 20 | 19 | no | 71% | 78% | snapshot_high |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 100% | 86% | snapshot_high |
| 2026-06-03 | 29.00 | 29 | 29 | yes | 100% | 96% | snapshot_high |

