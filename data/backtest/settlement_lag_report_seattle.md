# Settlement Lag Report

Generated: 2026-06-10T15:34:39.452214+00:00

## Scope

- Training rows: 571
- Lead rows: 166
- Revision rows: 405
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 166 | 78.2% | - | - |
| source=weather_current | 166 | 78.2% | - | - |
| source=weather_current|gap=1 | 53 | 98.9% | - | - |
| source=weather_current|gap=2 | 22 | 97.5% | - | - |
| source=weather_current|gap=3_plus | 91 | 60.6% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 24 | 3.8% | 0.00 |
| hour=10 | 18 | 95.0% | 10.33 |
| hour=11 | 13 | 93.3% | 10.69 |
| hour=12 | 17 | 94.7% | 8.35 |
| hour=13 | 17 | 94.7% | 6.12 |
| hour=14 | 18 | 95.0% | 6.06 |
| hour=15 | 18 | 85.0% | 5.38 |
| hour=16 | 16 | 66.7% | 4.55 |
| hour=17 | 18 | 65.0% | 2.83 |
| hour=18 | 16 | 44.4% | 2.29 |
| hour=19 | 17 | 36.8% | 2.00 |
| hour=2 | 17 | 5.3% | 0.00 |
| hour=20 | 24 | 11.5% | 2.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 1 | 66.7% | 7.00 |
| hour=4 | 12 | 92.9% | 12.00 |
| hour=5 | 11 | 92.3% | 12.45 |
| hour=6 | 12 | 92.9% | 12.00 |
| hour=7 | 11 | 92.3% | 11.36 |
| hour=8 | 15 | 94.1% | 10.80 |
| hour=9 | 18 | 95.0% | 10.33 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

