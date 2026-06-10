# Settlement Lag Report

Generated: 2026-06-10T15:34:37.124279+00:00

## Scope

- Training rows: 638
- Lead rows: 234
- Revision rows: 404
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 234 | 56.5% | - | - |
| source=weather_current | 234 | 56.5% | - | - |
| source=weather_current|gap=1 | 96 | 34.1% | - | - |
| source=weather_current|gap=2 | 25 | 86.7% | - | - |
| source=weather_current|gap=3_plus | 113 | 69.0% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 24 | 3.8% | 0.00 |
| hour=10 | 18 | 95.0% | 10.78 |
| hour=11 | 13 | 93.3% | 10.23 |
| hour=12 | 17 | 94.7% | 7.76 |
| hour=13 | 17 | 94.7% | 4.65 |
| hour=14 | 18 | 95.0% | 4.28 |
| hour=15 | 18 | 85.0% | 2.88 |
| hour=16 | 16 | 50.0% | 1.00 |
| hour=17 | 18 | 5.0% | 0.00 |
| hour=18 | 16 | 5.6% | 0.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 17 | 5.3% | 0.00 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=4 | 12 | 92.9% | 13.00 |
| hour=5 | 11 | 92.3% | 13.18 |
| hour=6 | 12 | 92.9% | 13.00 |
| hour=7 | 11 | 92.3% | 12.82 |
| hour=8 | 15 | 94.1% | 11.80 |
| hour=9 | 18 | 95.0% | 11.00 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

