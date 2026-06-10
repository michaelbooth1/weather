# Settlement Lag Report

Generated: 2026-06-10T15:34:22.947820+00:00

## Scope

- Training rows: 630
- Lead rows: 237
- Revision rows: 393
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 237 | 49.1% | - | - |
| source=weather_current | 237 | 49.1% | - | - |
| source=weather_current|gap=1 | 66 | 52.1% | - | - |
| source=weather_current|gap=2 | 64 | 35.5% | - | - |
| source=weather_current|gap=3_plus | 107 | 56.3% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 4 | 83.3% | 15.00 |
| hour=10 | 18 | 95.0% | 12.06 |
| hour=11 | 13 | 93.3% | 8.54 |
| hour=12 | 17 | 94.7% | 7.00 |
| hour=13 | 17 | 94.7% | 4.06 |
| hour=14 | 18 | 80.0% | 2.93 |
| hour=15 | 18 | 35.0% | 2.67 |
| hour=16 | 16 | 33.3% | 1.00 |
| hour=17 | 18 | 35.0% | 1.00 |
| hour=18 | 16 | 38.9% | 1.00 |
| hour=19 | 17 | 21.1% | 1.00 |
| hour=2 | 14 | 93.8% | 14.57 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 14.50 |
| hour=4 | 12 | 92.9% | 14.50 |
| hour=5 | 11 | 92.3% | 14.27 |
| hour=6 | 12 | 92.9% | 14.17 |
| hour=7 | 11 | 92.3% | 13.64 |
| hour=8 | 15 | 94.1% | 13.80 |
| hour=9 | 18 | 95.0% | 13.39 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

