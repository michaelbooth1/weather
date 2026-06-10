# Settlement Lag Report

Generated: 2026-06-10T15:34:34.622909+00:00

## Scope

- Training rows: 523
- Lead rows: 140
- Revision rows: 383
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 140 | 93.9% | - | - |
| source=weather_current | 140 | 93.9% | - | - |
| source=weather_current|gap=1 | 50 | 98.8% | - | - |
| source=weather_current|gap=3_plus | 80 | 89.5% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=1 | 18 | 95.0% | 8.00 |
| hour=10 | 18 | 95.0% | 3.33 |
| hour=11 | 13 | 93.3% | 3.00 |
| hour=12 | 17 | 94.7% | 2.12 |
| hour=13 | 17 | 73.7% | 1.77 |
| hour=14 | 18 | 35.0% | 1.50 |
| hour=15 | 18 | 15.0% | 1.00 |
| hour=16 | 16 | 5.6% | 0.00 |
| hour=17 | 18 | 5.0% | 0.00 |
| hour=18 | 16 | 5.6% | 0.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 14 | 93.8% | 8.50 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 8.50 |
| hour=4 | 12 | 92.9% | 8.50 |
| hour=5 | 11 | 92.3% | 8.45 |
| hour=6 | 12 | 92.9% | 8.50 |
| hour=7 | 11 | 92.3% | 8.55 |
| hour=8 | 15 | 94.1% | 7.20 |
| hour=9 | 18 | 95.0% | 4.72 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

