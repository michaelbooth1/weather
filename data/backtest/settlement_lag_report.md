# Settlement Lag Report

Generated: 2026-05-31T15:42:08.255934+00:00

## Scope

- Training rows: 9045
- Lead rows: 369
- Revision rows: 8676
- Sources: eccc_swob, metar, weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 369 | 63.7% | 132.0 | 60.0 |
| source=eccc_swob | 88 | 99.3% | - | - |
| source=eccc_swob|gap=1 | 79 | 99.3% | - | - |
| source=metar | 128 | 66.5% | 132.0 | 60.0 |
| source=metar|gap=1 | 127 | 66.2% | 132.9 | 60.0 |
| source=metar|hour=14 | 29 | 91.6% | 93.3 | 60.0 |
| source=metar|hour=14|gap=1 | 29 | 91.6% | 93.3 | 60.0 |
| source=metar|hour=8 | 27 | 97.9% | 80.0 | 60.0 |
| source=metar|hour=8|gap=1 | 27 | 97.9% | 80.0 | 60.0 |
| source=weather_current | 153 | 40.9% | - | - |
| source=weather_current|gap=1 | 75 | 36.9% | - | - |
| source=weather_current|gap=2 | 53 | 60.7% | - | - |
| source=weather_current|gap=3_plus | 25 | 16.3% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=10 | 663 | 91.9% | 4.13 |
| hour=11 | 666 | 88.2% | 3.21 |
| hour=12 | 665 | 82.5% | 2.46 |
| hour=13 | 662 | 69.9% | 1.99 |
| hour=14 | 670 | 55.7% | 1.66 |
| hour=15 | 673 | 36.1% | 1.42 |
| hour=16 | 673 | 16.3% | 1.35 |
| hour=17 | 672 | 7.0% | 1.37 |
| hour=18 | 672 | 2.7% | 1.41 |
| hour=19 | 672 | 1.6% | 1.70 |
| hour=20 | 665 | 0.3% | 2.00 |
| hour=21 | 6 | 12.5% | 0.00 |
| hour=8 | 656 | 93.2% | 6.64 |
| hour=9 | 661 | 92.6% | 5.35 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

