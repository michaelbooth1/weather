# Settlement Lag Report

Generated: 2026-06-10T15:34:25.116004+00:00

## Scope

- Training rows: 594
- Lead rows: 201
- Revision rows: 393
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 201 | 84.4% | - | - |
| source=weather_current | 201 | 84.4% | - | - |
| source=weather_current|gap=1 | 70 | 58.9% | - | - |
| source=weather_current|gap=2 | 27 | 97.9% | - | - |
| source=weather_current|gap=3_plus | 104 | 97.5% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=1 | 4 | 83.3% | 19.00 |
| hour=10 | 18 | 95.0% | 13.67 |
| hour=11 | 13 | 93.3% | 13.31 |
| hour=12 | 17 | 94.7% | 9.35 |
| hour=13 | 17 | 94.7% | 8.18 |
| hour=14 | 18 | 95.0% | 7.50 |
| hour=15 | 18 | 95.0% | 6.00 |
| hour=16 | 16 | 94.4% | 4.88 |
| hour=17 | 18 | 80.0% | 2.47 |
| hour=18 | 16 | 33.3% | 1.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 14 | 93.8% | 14.86 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 15.50 |
| hour=4 | 12 | 92.9% | 15.50 |
| hour=5 | 11 | 92.3% | 15.73 |
| hour=6 | 12 | 92.9% | 15.50 |
| hour=7 | 11 | 92.3% | 15.27 |
| hour=8 | 15 | 94.1% | 14.40 |
| hour=9 | 18 | 95.0% | 13.67 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

