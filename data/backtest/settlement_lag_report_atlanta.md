# Settlement Lag Report

Generated: 2026-06-10T15:34:18.423373+00:00

## Scope

- Training rows: 623
- Lead rows: 237
- Revision rows: 386
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 237 | 31.5% | - | - |
| source=weather_current | 237 | 31.5% | - | - |
| source=weather_current|gap=1 | 118 | 27.0% | - | - |
| source=weather_current|gap=2 | 29 | 81.9% | - | - |
| source=weather_current|gap=3_plus | 90 | 22.2% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 2 | 75.0% | 7.00 |
| hour=1 | 18 | 95.0% | 8.67 |
| hour=10 | 18 | 95.0% | 7.11 |
| hour=11 | 13 | 93.3% | 6.77 |
| hour=12 | 17 | 94.7% | 3.88 |
| hour=13 | 17 | 94.7% | 2.06 |
| hour=14 | 18 | 80.0% | 1.27 |
| hour=15 | 19 | 23.8% | 1.00 |
| hour=16 | 16 | 5.6% | 0.00 |
| hour=17 | 18 | 5.0% | 0.00 |
| hour=18 | 16 | 5.6% | 0.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 14 | 93.8% | 9.14 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 9.50 |
| hour=4 | 12 | 92.9% | 9.50 |
| hour=5 | 11 | 92.3% | 9.45 |
| hour=6 | 12 | 92.9% | 9.50 |
| hour=7 | 11 | 92.3% | 9.55 |
| hour=8 | 15 | 94.1% | 8.73 |
| hour=9 | 18 | 95.0% | 8.06 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

