# Settlement Lag Report

Generated: 2026-06-10T15:34:29.877804+00:00

## Scope

- Training rows: 629
- Lead rows: 240
- Revision rows: 389
- Sources: weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 240 | 58.0% | - | - |
| source=weather_current | 240 | 58.0% | - | - |
| source=weather_current|gap=1 | 142 | 54.4% | - | - |
| source=weather_current|gap=3_plus | 82 | 56.4% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 24 | 3.8% | 0.00 |
| hour=10 | 18 | 95.0% | 6.83 |
| hour=11 | 13 | 93.3% | 4.23 |
| hour=12 | 17 | 94.7% | 3.88 |
| hour=13 | 17 | 89.5% | 3.06 |
| hour=14 | 18 | 65.0% | 2.33 |
| hour=15 | 18 | 50.0% | 1.56 |
| hour=16 | 16 | 33.3% | 1.00 |
| hour=17 | 18 | 35.0% | 1.00 |
| hour=18 | 16 | 11.1% | 1.00 |
| hour=19 | 17 | 5.3% | 0.00 |
| hour=2 | 14 | 93.8% | 7.57 |
| hour=20 | 24 | 3.8% | 0.00 |
| hour=21 | 24 | 3.8% | 0.00 |
| hour=22 | 22 | 4.2% | 0.00 |
| hour=23 | 22 | 4.2% | 0.00 |
| hour=3 | 12 | 92.9% | 7.00 |
| hour=4 | 12 | 92.9% | 7.00 |
| hour=5 | 11 | 92.3% | 6.82 |
| hour=6 | 12 | 92.9% | 7.00 |
| hour=7 | 11 | 92.3% | 7.18 |
| hour=8 | 15 | 94.1% | 7.80 |
| hour=9 | 18 | 95.0% | 7.89 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

