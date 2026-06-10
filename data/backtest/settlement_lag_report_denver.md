# Settlement Lag Report

Generated: 2026-06-10T15:34:27.497425+00:00

## Scope

- Training rows: 533
- Lead rows: 146
- Revision rows: 387
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 146 | 82.7% | - | - |
| source=weather_current | 146 | 82.7% | - | - |
| source=weather_current|gap=3_plus | 116 | 78.3% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 24 | 3.8% | 0.00 |
| hour=10 | 18 | 95.0% | 20.56 |
| hour=11 | 13 | 93.3% | 15.38 |
| hour=12 | 17 | 94.7% | 16.12 |
| hour=13 | 17 | 94.7% | 13.76 |
| hour=14 | 18 | 95.0% | 10.00 |
| hour=15 | 18 | 95.0% | 8.89 |
| hour=16 | 16 | 94.4% | 6.06 |
| hour=17 | 18 | 85.0% | 4.25 |
| hour=18 | 16 | 50.0% | 2.00 |
| hour=19 | 17 | 21.1% | 2.00 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 5 | 85.7% | 20.00 |
| hour=4 | 7 | 88.9% | 19.00 |
| hour=5 | 11 | 92.3% | 16.82 |
| hour=6 | 12 | 92.9% | 16.50 |
| hour=7 | 11 | 92.3% | 16.18 |
| hour=8 | 15 | 94.1% | 19.40 |
| hour=9 | 18 | 95.0% | 21.33 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

