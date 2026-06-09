# Forecast vs Realized Tracker

Settled days: 12  |  verdict cutoff: 09:00

## Verdict: is the model's morning forecast-skepticism costing or saving?

**MODEL CALIBRATED** -- reach-rate 81% ~ model's 67%: the model's morning confidence already matches how often the forecast is reached.

| Reach-rate (realized >= forecast) | Model gives | Market gives | Consensus bias (realized-forecast) | N |
| :--- | :--- | :--- | :--- | :--- |
| 81% | 67% | 64% | +1.78 C | 43 |

> Bias > 0 means the forecast UNDER-calls the realized high; < 0 means it OVER-calls.

## Cutoff 07:00  (45 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 45 | +1.57 | 2.95 | 11% |
| weather_com | 45 | +2.24 | 2.42 | 13% |
| eccc | 12 | -1.08 | 1.08 | 42% |
| consensus | 45 | +1.80 | 2.28 | 27% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 81% | 67% | 69% | 1.27 | 1.00 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | settlement_ledger:snapshot_high |
| 2026-05-28 | 20.20 | 20 | 20 | yes | 40% | 53% | settlement_ledger:daily_summary |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 37% | 78% | settlement_ledger:daily_summary |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 19% | 68% | settlement_ledger:daily_summary |
| 2026-06-01 | 20.20 | 20 | 19 | no | 75% | 87% | settlement_ledger:daily_summary |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 43% | 67% | settlement_ledger:daily_summary |
| 2026-06-03 | 28.50 | 29 | 29 | yes | 37% | 86% | settlement_ledger:daily_summary |
| 2026-06-04 | 29.00 | 29 | 30 | yes | 34% | 86% | settlement_ledger:daily_summary |
| 2026-06-05 | 30.20 | 30 | 31 | yes | 58% | 76% | settlement_ledger:daily_summary |
| 2026-06-06 | 86.55 | 87 | 86 | no | 68% | 6% | settlement_ledger:snapshot_high |
| 2026-06-06 | 86.35 | 86 | 91 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.45 | 75 | 84 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.10 | 75 | 88 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-06 | 84.90 | 85 | 92 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 79.90 | 80 | 88 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 67.45 | 67 | 71 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 78.85 | 79 | 86 | yes | 100% | 100% | settlement_ledger:snapshot_high |
| 2026-06-06 | 91.00 | 91 | 91 | yes | 13% | 49% | settlement_ledger:daily_summary |
| 2026-06-06 | 60.10 | 60 | 63 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 54.30 | 54 | 62 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 25.00 | 25 | 26 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-07 | 83.60 | 84 | 84 | yes | 80% | 20% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.35 | 87 | 90 | yes | 75% | 86% | settlement_ledger:daily_summary |
| 2026-06-07 | 82.40 | 82 | 83 | yes | 79% | 43% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.85 | 88 | 92 | yes | 72% | 92% | settlement_ledger:daily_summary |
| 2026-06-07 | 91.25 | 91 | 93 | yes | 61% | 68% | settlement_ledger:daily_summary |
| 2026-06-07 | 85.00 | 85 | 85 | yes | 57% | 86% | settlement_ledger:daily_summary |
| 2026-06-07 | 70.20 | 70 | 71 | yes | 84% | 79% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.10 | 87 | 88 | yes | 64% | 56% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.90 | 84 | 81 | no | 68% | 63% | settlement_ledger:daily_summary |
| 2026-06-07 | 66.60 | 67 | 67 | yes | 73% | 18% | settlement_ledger:daily_summary |
| 2026-06-07 | 63.10 | 63 | 65 | yes | 44% | 71% | settlement_ledger:daily_summary |
| 2026-06-07 | 25.10 | 25 | 24 | no | 76% | 77% | settlement_ledger:daily_summary |
| 2026-06-08 | 80.10 | 80 | 81 | yes | 85% | 71% | snapshot_high |
| 2026-06-08 | 87.85 | 88 | 88 | yes | 81% | 81% | snapshot_high |
| 2026-06-08 | 83.85 | 84 | 84 | yes | 36% | 34% | snapshot_high |
| 2026-06-08 | 90.05 | 90 | 94 | yes | 44% | 95% | snapshot_high |
| 2026-06-08 | 82.70 | 83 | 82 | no | 33% | 44% | snapshot_high |
| 2026-06-08 | 86.40 | 86 | 90 | yes | 75% | 78% | snapshot_high |
| 2026-06-08 | 70.40 | 70 | 72 | yes | 83% | 95% | snapshot_high |
| 2026-06-08 | 89.05 | 89 | 90 | yes | 64% | 38% | snapshot_high |
| 2026-06-08 | 75.40 | 75 | 74 | no | 72% | 51% | snapshot_high |
| 2026-06-08 | 63.00 | 63 | 64 | yes | 81% | 79% | snapshot_high |
| 2026-06-08 | 60.95 | 61 | 61 | yes | 83% | 36% | snapshot_high |
| 2026-06-08 | 25.00 | 25 | 23 | no | 48% | 32% | snapshot_high |

## Cutoff 09:00  (45 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 44 | +1.64 | 2.80 | 20% |
| weather_com | 45 | +2.11 | 2.29 | 18% |
| eccc | 12 | -1.00 | 1.00 | 42% |
| consensus | 45 | +1.78 | 2.31 | 27% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 81% | 67% | 64% | 1.20 | 1.00 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | settlement_ledger:snapshot_high |
| 2026-05-28 | 20.20 | 20 | 20 | yes | 40% | 49% | settlement_ledger:daily_summary |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 37% | 78% | settlement_ledger:daily_summary |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 20% | 71% | settlement_ledger:daily_summary |
| 2026-06-01 | 20.20 | 20 | 19 | no | 75% | 87% | settlement_ledger:daily_summary |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 35% | 68% | settlement_ledger:daily_summary |
| 2026-06-03 | 29.00 | 29 | 29 | yes | 77% | 84% | settlement_ledger:daily_summary |
| 2026-06-04 | 29.50 | 30 | 30 | yes | 11% | 42% | settlement_ledger:daily_summary |
| 2026-06-05 | 30.10 | 30 | 31 | yes | 61% | 76% | settlement_ledger:daily_summary |
| 2026-06-06 | 86.55 | 87 | 86 | no | 68% | 6% | settlement_ledger:snapshot_high |
| 2026-06-06 | 86.35 | 86 | 91 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.45 | 75 | 84 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.10 | 75 | 88 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-06 | 84.90 | 85 | 92 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 79.90 | 80 | 88 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 67.45 | 67 | 71 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 78.85 | 79 | 86 | yes | 100% | 100% | settlement_ledger:snapshot_high |
| 2026-06-06 | 91.00 | 91 | 91 | yes | 13% | 49% | settlement_ledger:daily_summary |
| 2026-06-06 | 60.10 | 60 | 63 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 54.30 | 54 | 62 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 25.00 | 25 | 26 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-07 | 81.95 | 82 | 84 | yes | 86% | 62% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.00 | 87 | 90 | yes | 71% | 77% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.05 | 83 | 83 | yes | 60% | 13% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.90 | 88 | 92 | yes | 70% | 90% | settlement_ledger:daily_summary |
| 2026-06-07 | 92.05 | 92 | 93 | yes | 75% | 68% | settlement_ledger:daily_summary |
| 2026-06-07 | 85.45 | 85 | 85 | yes | 39% | 88% | settlement_ledger:daily_summary |
| 2026-06-07 | 70.60 | 71 | 71 | yes | 35% | 23% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.10 | 87 | 88 | yes | 65% | 63% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.40 | 83 | 81 | no | 67% | 57% | settlement_ledger:daily_summary |
| 2026-06-07 | 65.95 | 66 | 67 | yes | 90% | 45% | settlement_ledger:daily_summary |
| 2026-06-07 | 63.75 | 64 | 65 | yes | 84% | 67% | settlement_ledger:daily_summary |
| 2026-06-07 | 25.00 | 25 | 24 | no | 75% | 77% | settlement_ledger:daily_summary |
| 2026-06-08 | 80.50 | 81 | 81 | yes | 65% | 16% | snapshot_high |
| 2026-06-08 | 86.30 | 86 | 88 | yes | 79% | 97% | snapshot_high |
| 2026-06-08 | 82.95 | 83 | 84 | yes | 63% | 37% | snapshot_high |
| 2026-06-08 | 90.40 | 90 | 94 | yes | 73% | 100% | snapshot_high |
| 2026-06-08 | 83.30 | 83 | 82 | no | 62% | 45% | snapshot_high |
| 2026-06-08 | 87.20 | 87 | 90 | yes | 70% | 35% | snapshot_high |
| 2026-06-08 | 70.65 | 71 | 72 | yes | 35% | 34% | snapshot_high |
| 2026-06-08 | 88.70 | 89 | 90 | yes | 42% | 47% | snapshot_high |
| 2026-06-08 | 75.45 | 75 | 74 | no | 64% | 49% | snapshot_high |
| 2026-06-08 | 63.10 | 63 | 64 | yes | 82% | 75% | snapshot_high |
| 2026-06-08 | 61.35 | 61 | 61 | yes | 88% | 29% | snapshot_high |
| 2026-06-08 | 25.10 | 25 | 23 | no | 83% | 27% | snapshot_high |

## Cutoff 11:00  (45 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 45 | +1.45 | 2.75 | 20% |
| weather_com | 45 | +1.93 | 2.11 | 29% |
| eccc | 12 | -1.42 | 1.42 | 25% |
| consensus | 45 | +1.59 | 2.17 | 31% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 77% | 74% | 65% | 1.00 | 0.87 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | settlement_ledger:snapshot_high |
| 2026-05-28 | 19.70 | 20 | 20 | yes | 52% | 46% | settlement_ledger:daily_summary |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 37% | 79% | settlement_ledger:daily_summary |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 66% | 82% | settlement_ledger:daily_summary |
| 2026-06-01 | 20.10 | 20 | 19 | no | 80% | 94% | settlement_ledger:daily_summary |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 32% | 75% | settlement_ledger:daily_summary |
| 2026-06-03 | 29.00 | 29 | 29 | yes | 77% | 83% | settlement_ledger:daily_summary |
| 2026-06-04 | 30.00 | 30 | 30 | yes | 46% | 47% | settlement_ledger:daily_summary |
| 2026-06-05 | 30.00 | 30 | 31 | yes | 72% | 74% | settlement_ledger:daily_summary |
| 2026-06-06 | 86.55 | 87 | 86 | no | 68% | 6% | settlement_ledger:snapshot_high |
| 2026-06-06 | 86.35 | 86 | 91 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.45 | 75 | 84 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.10 | 75 | 88 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-06 | 84.90 | 85 | 92 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 79.90 | 80 | 88 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 67.45 | 67 | 71 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 78.85 | 79 | 86 | yes | 100% | 100% | settlement_ledger:snapshot_high |
| 2026-06-06 | 91.00 | 91 | 91 | yes | 13% | 49% | settlement_ledger:daily_summary |
| 2026-06-06 | 60.10 | 60 | 63 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 54.30 | 54 | 62 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 25.00 | 25 | 26 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-07 | 82.40 | 82 | 84 | yes | 91% | 35% | settlement_ledger:daily_summary |
| 2026-06-07 | 89.90 | 90 | 90 | yes | 84% | 45% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.45 | 83 | 83 | yes | 68% | 14% | settlement_ledger:daily_summary |
| 2026-06-07 | 88.35 | 88 | 92 | yes | 76% | 85% | settlement_ledger:daily_summary |
| 2026-06-07 | 92.20 | 92 | 93 | yes | 76% | 75% | settlement_ledger:daily_summary |
| 2026-06-07 | 85.95 | 86 | 85 | no | 84% | 81% | settlement_ledger:daily_summary |
| 2026-06-07 | 70.85 | 71 | 71 | yes | 37% | 22% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.60 | 88 | 88 | yes | 97% | 67% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.30 | 83 | 81 | no | 65% | 41% | settlement_ledger:daily_summary |
| 2026-06-07 | 66.05 | 66 | 67 | yes | 84% | 53% | settlement_ledger:daily_summary |
| 2026-06-07 | 63.85 | 64 | 65 | yes | 84% | 61% | settlement_ledger:daily_summary |
| 2026-06-07 | 25.00 | 25 | 24 | no | 34% | 76% | settlement_ledger:daily_summary |
| 2026-06-08 | 80.05 | 80 | 81 | yes | 81% | 79% | snapshot_high |
| 2026-06-08 | 88.95 | 89 | 88 | no | 68% | 41% | snapshot_high |
| 2026-06-08 | 83.60 | 84 | 84 | yes | 63% | 39% | snapshot_high |
| 2026-06-08 | 90.10 | 90 | 94 | yes | 59% | 100% | snapshot_high |
| 2026-06-08 | 81.85 | 82 | 82 | yes | 74% | 72% | snapshot_high |
| 2026-06-08 | 87.35 | 87 | 90 | yes | 74% | 35% | snapshot_high |
| 2026-06-08 | 70.25 | 70 | 72 | yes | 84% | 91% | snapshot_high |
| 2026-06-08 | 89.40 | 89 | 90 | yes | 66% | 64% | snapshot_high |
| 2026-06-08 | 75.90 | 76 | 74 | no | 79% | 45% | snapshot_high |
| 2026-06-08 | 63.60 | 64 | 64 | yes | 89% | 78% | snapshot_high |
| 2026-06-08 | 62.05 | 62 | 61 | no | 88% | 28% | snapshot_high |
| 2026-06-08 | 24.90 | 25 | 23 | no | 80% | 31% | snapshot_high |

## Cutoff 13:00  (45 days)

### Forecast source calibration

| Source | N | Bias (realized-fc) | MAE | Exact-bucket hit |
| :--- | :--- | :--- | :--- | :--- |
| open_meteo | 45 | +1.55 | 2.71 | 29% |
| weather_com | 45 | +1.84 | 2.24 | 20% |
| eccc | 12 | -1.42 | 1.42 | 25% |
| consensus | 45 | +1.58 | 2.20 | 24% |

### Reach calibration & point error

| Reach-rate | Model reach | Market reach | Model median MAE | Market median MAE |
| :--- | :--- | :--- | :--- | :--- |
| 73% | 76% | 67% | 1.02 | 0.71 |

### Per-day

| Date | Forecast(cons) | FcBucket | Realized | Reached? | Model reach | Market reach | Settle src |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 25.80 | 26 | 25 | no | 35% | 22% | settlement_ledger:snapshot_high |
| 2026-05-28 | 19.70 | 20 | 20 | yes | 44% | 54% | settlement_ledger:daily_summary |
| 2026-05-30 | 20.00 | 20 | 20 | yes | 23% | 61% | settlement_ledger:daily_summary |
| 2026-05-31 | 24.00 | 24 | 24 | yes | 21% | 75% | settlement_ledger:daily_summary |
| 2026-06-01 | 20.00 | 20 | 19 | no | 71% | 78% | settlement_ledger:daily_summary |
| 2026-06-02 | 25.00 | 25 | 25 | yes | 100% | 86% | settlement_ledger:daily_summary |
| 2026-06-03 | 29.00 | 29 | 29 | yes | 100% | 96% | settlement_ledger:daily_summary |
| 2026-06-04 | 30.00 | 30 | 30 | yes | 89% | 63% | settlement_ledger:daily_summary |
| 2026-06-05 | 30.20 | 30 | 31 | yes | 98% | 86% | settlement_ledger:daily_summary |
| 2026-06-06 | 86.55 | 87 | 86 | no | 68% | 6% | settlement_ledger:snapshot_high |
| 2026-06-06 | 86.35 | 86 | 91 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.45 | 75 | 84 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 75.10 | 75 | 88 | yes | - | - | settlement_ledger:daily_summary |
| 2026-06-06 | 84.90 | 85 | 92 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 79.90 | 80 | 88 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 67.45 | 67 | 71 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 78.85 | 79 | 86 | yes | 100% | 100% | settlement_ledger:snapshot_high |
| 2026-06-06 | 91.00 | 91 | 91 | yes | 13% | 49% | settlement_ledger:daily_summary |
| 2026-06-06 | 60.10 | 60 | 63 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 54.30 | 54 | 62 | yes | 100% | 100% | settlement_ledger:daily_summary |
| 2026-06-06 | 26.00 | 26 | 26 | yes | 27% | 41% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.30 | 83 | 84 | yes | 58% | 36% | settlement_ledger:daily_summary |
| 2026-06-07 | 88.15 | 88 | 90 | yes | 96% | 84% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.50 | 84 | 83 | no | 77% | 44% | settlement_ledger:daily_summary |
| 2026-06-07 | 88.65 | 89 | 92 | yes | 61% | 63% | settlement_ledger:daily_summary |
| 2026-06-07 | 92.55 | 93 | 93 | yes | 39% | 21% | settlement_ledger:daily_summary |
| 2026-06-07 | 85.85 | 86 | 85 | no | 92% | 87% | settlement_ledger:daily_summary |
| 2026-06-07 | 70.25 | 70 | 71 | yes | 84% | 88% | settlement_ledger:daily_summary |
| 2026-06-07 | 87.90 | 88 | 88 | yes | 100% | 98% | settlement_ledger:daily_summary |
| 2026-06-07 | 83.35 | 83 | 81 | no | 65% | 26% | settlement_ledger:daily_summary |
| 2026-06-07 | 66.40 | 66 | 67 | yes | 84% | 60% | settlement_ledger:daily_summary |
| 2026-06-07 | 63.75 | 64 | 65 | yes | 84% | 63% | settlement_ledger:daily_summary |
| 2026-06-07 | 25.00 | 25 | 24 | no | 27% | 73% | settlement_ledger:daily_summary |
| 2026-06-08 | 82.15 | 82 | 81 | no | 91% | 72% | snapshot_high |
| 2026-06-08 | 89.75 | 90 | 88 | no | 87% | 49% | snapshot_high |
| 2026-06-08 | 81.70 | 82 | 84 | yes | 86% | 77% | snapshot_high |
| 2026-06-08 | 89.95 | 90 | 94 | yes | 87% | 93% | snapshot_high |
| 2026-06-08 | 80.95 | 81 | 82 | yes | 55% | 58% | snapshot_high |
| 2026-06-08 | 88.25 | 88 | 90 | yes | 98% | 56% | snapshot_high |
| 2026-06-08 | 70.65 | 71 | 72 | yes | 30% | 34% | snapshot_high |
| 2026-06-08 | 88.20 | 88 | 90 | yes | 100% | 100% | snapshot_high |
| 2026-06-08 | 75.20 | 75 | 74 | no | 84% | 22% | snapshot_high |
| 2026-06-08 | 64.05 | 64 | 64 | yes | 85% | 64% | snapshot_high |
| 2026-06-08 | 61.85 | 62 | 61 | no | 92% | 22% | snapshot_high |
| 2026-06-08 | 24.90 | 25 | 23 | no | 73% | 28% | snapshot_high |

