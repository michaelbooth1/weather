# Settlement Lag Report

Generated: 2026-06-10T15:34:20.717951+00:00

## Scope

- Training rows: 566
- Lead rows: 176
- Revision rows: 390
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 176 | 59.2% | - | - |
| source=weather_current | 176 | 59.2% | - | - |
| source=weather_current|gap=1 | 59 | 99.0% | - | - |
| source=weather_current|gap=2 | 28 | 98.0% | - | - |
| source=weather_current|gap=3_plus | 89 | 20.2% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 1 | 66.7% | 15.00 |
| hour=10 | 18 | 95.0% | 9.22 |
| hour=11 | 13 | 93.3% | 6.00 |
| hour=12 | 17 | 94.7% | 5.53 |
| hour=13 | 17 | 94.7% | 4.12 |
| hour=14 | 18 | 80.0% | 3.40 |
| hour=15 | 18 | 65.0% | 2.75 |
| hour=16 | 16 | 66.7% | 1.55 |
| hour=17 | 18 | 45.0% | 1.00 |
| hour=18 | 16 | 11.1% | 1.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 14 | 93.8% | 10.29 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 9.50 |
| hour=4 | 12 | 92.9% | 9.50 |
| hour=5 | 11 | 92.3% | 9.55 |
| hour=6 | 12 | 92.9% | 9.50 |
| hour=7 | 11 | 92.3% | 9.45 |
| hour=8 | 15 | 94.1% | 10.40 |
| hour=9 | 18 | 95.0% | 10.78 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

