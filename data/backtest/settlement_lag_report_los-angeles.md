# Settlement Lag Report

Generated: 2026-06-10T15:34:32.279106+00:00

## Scope

- Training rows: 500
- Lead rows: 95
- Revision rows: 405
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 95 | 99.4% | - | - |
| source=weather_current | 95 | 99.4% | - | - |
| source=weather_current|gap=3_plus | 81 | 99.3% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 24 | 3.8% | 0.00 |
| hour=10 | 18 | 95.0% | 7.22 |
| hour=11 | 13 | 93.3% | 5.92 |
| hour=12 | 17 | 94.7% | 5.18 |
| hour=13 | 17 | 94.7% | 3.35 |
| hour=14 | 18 | 95.0% | 2.67 |
| hour=15 | 18 | 90.0% | 1.53 |
| hour=16 | 16 | 50.0% | 1.00 |
| hour=17 | 18 | 35.0% | 1.00 |
| hour=18 | 16 | 22.2% | 1.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 17 | 5.3% | 0.00 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 1 | 66.7% | 9.00 |
| hour=4 | 12 | 92.9% | 8.50 |
| hour=5 | 11 | 92.3% | 8.36 |
| hour=6 | 12 | 92.9% | 8.00 |
| hour=7 | 11 | 92.3% | 7.91 |
| hour=8 | 15 | 94.1% | 7.80 |
| hour=9 | 18 | 95.0% | 7.83 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

