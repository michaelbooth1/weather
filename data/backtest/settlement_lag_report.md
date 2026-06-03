# Settlement Lag Report

Generated: 2026-06-03T20:54:23.962283+00:00

## Scope

- Training rows: 9797
- Lead rows: 836
- Revision rows: 8961
- Sources: eccc_swob, metar, weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 836 | 57.8% | 132.0 | 60.0 |
| source=eccc_swob | 282 | 80.8% | - | - |
| source=eccc_swob|gap=1 | 234 | 76.9% | - | - |
| source=eccc_swob|gap=2 | 46 | 98.8% | - | - |
| source=eccc_swob|hour=10 | 22 | 97.5% | - | - |
| source=eccc_swob|hour=11 | 27 | 97.9% | - | - |
| source=eccc_swob|hour=12 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=13 | 23 | 97.6% | - | - |
| source=eccc_swob|hour=13|gap=1 | 23 | 97.6% | - | - |
| source=eccc_swob|hour=15 | 23 | 73.6% | - | - |
| source=eccc_swob|hour=15|gap=1 | 23 | 73.6% | - | - |
| source=eccc_swob|hour=16 | 20 | 70.0% | - | - |
| source=eccc_swob|hour=16|gap=1 | 20 | 70.0% | - | - |
| source=metar | 128 | 66.5% | 132.0 | 60.0 |
| source=metar|gap=1 | 127 | 66.2% | 132.9 | 60.0 |
| source=metar|hour=14 | 29 | 91.6% | 93.3 | 60.0 |
| source=metar|hour=14|gap=1 | 29 | 91.6% | 93.3 | 60.0 |
| source=metar|hour=8 | 27 | 97.9% | 80.0 | 60.0 |
| source=metar|hour=8|gap=1 | 27 | 97.9% | 80.0 | 60.0 |
| source=weather_current | 426 | 40.0% | - | - |
| source=weather_current|gap=1 | 177 | 25.9% | - | - |
| source=weather_current|gap=2 | 163 | 38.4% | - | - |
| source=weather_current|gap=3_plus | 86 | 73.2% | - | - |
| source=weather_current|hour=10 | 22 | 93.3% | - | - |
| source=weather_current|hour=11 | 28 | 81.3% | - | - |
| source=weather_current|hour=12 | 26 | 76.4% | - | - |
| source=weather_current|hour=12|gap=2 | 24 | 74.6% | - | - |
| source=weather_current|hour=13 | 25 | 75.6% | - | - |
| source=weather_current|hour=14 | 30 | 57.5% | - | - |
| source=weather_current|hour=15 | 33 | 32.6% | - | - |
| source=weather_current|hour=16 | 36 | 8.9% | - | - |
| source=weather_current|hour=17 | 35 | 3.8% | - | - |
| source=weather_current|hour=17|gap=1 | 21 | 6.1% | - | - |
| source=weather_current|hour=18 | 35 | 3.8% | - | - |
| source=weather_current|hour=18|gap=1 | 24 | 5.4% | - | - |
| source=weather_current|hour=19 | 35 | 3.8% | - | - |
| source=weather_current|hour=19|gap=1 | 23 | 5.6% | - | - |
| source=weather_current|hour=20 | 21 | 6.1% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 5 | 85.7% | 10.00 |
| hour=1 | 6 | 87.5% | 10.00 |
| hour=10 | 677 | 92.0% | 4.14 |
| hour=11 | 683 | 88.5% | 3.21 |
| hour=12 | 682 | 82.9% | 2.45 |
| hour=13 | 680 | 70.7% | 1.96 |
| hour=14 | 687 | 56.2% | 1.65 |
| hour=15 | 691 | 35.9% | 1.41 |
| hour=16 | 691 | 15.9% | 1.35 |
| hour=17 | 690 | 6.8% | 1.37 |
| hour=18 | 690 | 2.6% | 1.41 |
| hour=19 | 690 | 1.6% | 1.70 |
| hour=2 | 6 | 87.5% | 10.00 |
| hour=20 | 677 | 0.3% | 2.00 |
| hour=21 | 18 | 5.0% | 0.00 |
| hour=22 | 12 | 7.1% | 0.00 |
| hour=23 | 12 | 7.1% | 0.00 |
| hour=3 | 6 | 87.5% | 10.00 |
| hour=4 | 6 | 87.5% | 10.00 |
| hour=5 | 6 | 87.5% | 10.00 |
| hour=6 | 6 | 87.5% | 10.00 |
| hour=7 | 6 | 87.5% | 10.00 |
| hour=8 | 664 | 93.2% | 6.68 |
| hour=9 | 670 | 92.7% | 5.36 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

