# Settlement Lag Report

Generated: 2026-06-10T15:34:16.312912+00:00

## Scope

- Training rows: 571
- Lead rows: 177
- Revision rows: 394
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 177 | 60.0% | - | - |
| source=weather_current | 177 | 60.0% | - | - |
| source=weather_current|gap=1 | 61 | 99.0% | - | - |
| source=weather_current|gap=2 | 32 | 98.2% | - | - |
| source=weather_current|gap=3_plus | 84 | 16.7% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=1 | 18 | 95.0% | 9.67 |
| hour=10 | 18 | 95.0% | 5.50 |
| hour=11 | 13 | 93.3% | 4.46 |
| hour=12 | 17 | 94.7% | 3.65 |
| hour=13 | 17 | 94.7% | 2.71 |
| hour=14 | 21 | 73.9% | 1.56 |
| hour=15 | 24 | 57.7% | 1.00 |
| hour=16 | 18 | 25.0% | 1.00 |
| hour=17 | 18 | 5.0% | 0.00 |
| hour=18 | 16 | 5.6% | 0.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 14 | 93.8% | 8.71 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 8.00 |
| hour=4 | 12 | 92.9% | 8.00 |
| hour=5 | 11 | 92.3% | 8.18 |
| hour=6 | 12 | 92.9% | 8.00 |
| hour=7 | 11 | 92.3% | 7.45 |
| hour=8 | 15 | 94.1% | 7.87 |
| hour=9 | 18 | 95.0% | 7.50 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

