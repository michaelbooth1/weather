# Settlement Lag Report

Generated: 2026-06-10T15:33:12.379123+00:00

## Scope

- Training rows: 11851
- Lead rows: 1973
- Revision rows: 9878
- Sources: eccc_swob, metar, weather_current

## Catch-Up Contexts

| Context | N | Catch-up rate | Mean lag min | Median lag min |
| :--- | ---: | ---: | ---: | ---: |
| global | 1973 | 62.4% | 132.0 | 60.0 |
| source=eccc_swob | 698 | 88.5% | - | - |
| source=eccc_swob|gap=1 | 556 | 85.9% | - | - |
| source=eccc_swob|gap=2 | 123 | 97.9% | - | - |
| source=eccc_swob|hour=0 | 25 | 97.8% | - | - |
| source=eccc_swob|hour=0|gap=1 | 20 | 97.3% | - | - |
| source=eccc_swob|hour=1 | 30 | 98.1% | - | - |
| source=eccc_swob|hour=10 | 47 | 98.8% | - | - |
| source=eccc_swob|hour=10|gap=1 | 20 | 97.3% | - | - |
| source=eccc_swob|hour=10|gap=2 | 21 | 97.4% | - | - |
| source=eccc_swob|hour=11 | 62 | 99.1% | - | - |
| source=eccc_swob|hour=11|gap=1 | 38 | 98.5% | - | - |
| source=eccc_swob|hour=11|gap=2 | 21 | 97.4% | - | - |
| source=eccc_swob|hour=12 | 43 | 98.7% | - | - |
| source=eccc_swob|hour=12|gap=1 | 26 | 97.9% | - | - |
| source=eccc_swob|hour=13 | 54 | 98.9% | - | - |
| source=eccc_swob|hour=13|gap=1 | 49 | 98.8% | - | - |
| source=eccc_swob|hour=14 | 43 | 85.3% | - | - |
| source=eccc_swob|hour=14|gap=1 | 38 | 88.5% | - | - |
| source=eccc_swob|hour=15 | 40 | 70.0% | - | - |
| source=eccc_swob|hour=15|gap=1 | 40 | 70.0% | - | - |
| source=eccc_swob|hour=16 | 39 | 71.7% | - | - |
| source=eccc_swob|hour=16|gap=1 | 39 | 71.7% | - | - |
| source=eccc_swob|hour=17 | 27 | 56.6% | - | - |
| source=eccc_swob|hour=17|gap=1 | 27 | 56.6% | - | - |
| source=eccc_swob|hour=1|gap=1 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=2 | 30 | 98.1% | - | - |
| source=eccc_swob|hour=2|gap=1 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=3 | 30 | 98.1% | - | - |
| source=eccc_swob|hour=3|gap=1 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=4 | 30 | 98.1% | - | - |
| source=eccc_swob|hour=4|gap=1 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=5 | 29 | 98.1% | - | - |
| source=eccc_swob|hour=5|gap=1 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=6 | 30 | 98.1% | - | - |
| source=eccc_swob|hour=6|gap=1 | 24 | 97.7% | - | - |
| source=eccc_swob|hour=7 | 29 | 98.1% | - | - |
| source=eccc_swob|hour=7|gap=1 | 23 | 97.6% | - | - |
| source=eccc_swob|hour=8 | 29 | 98.1% | - | - |
| source=eccc_swob|hour=8|gap=1 | 23 | 97.6% | - | - |
| source=eccc_swob|hour=9 | 30 | 98.1% | - | - |
| source=eccc_swob|hour=9|gap=1 | 24 | 97.7% | - | - |
| source=metar | 128 | 66.5% | 132.0 | 60.0 |
| source=metar|gap=1 | 127 | 66.2% | 132.9 | 60.0 |
| source=metar|hour=14 | 29 | 91.6% | 93.3 | 60.0 |
| source=metar|hour=14|gap=1 | 29 | 91.6% | 93.3 | 60.0 |
| source=metar|hour=8 | 27 | 97.9% | 80.0 | 60.0 |
| source=metar|hour=8|gap=1 | 27 | 97.9% | 80.0 | 60.0 |
| source=weather_current | 1147 | 46.1% | - | - |
| source=weather_current|gap=1 | 452 | 33.3% | - | - |
| source=weather_current|gap=2 | 313 | 45.5% | - | - |
| source=weather_current|gap=3_plus | 382 | 61.8% | - | - |
| source=weather_current|hour=0 | 40 | 62.9% | - | - |
| source=weather_current|hour=0|gap=3_plus | 40 | 62.9% | - | - |
| source=weather_current|hour=1 | 48 | 62.8% | - | - |
| source=weather_current|hour=10 | 51 | 97.0% | - | - |
| source=weather_current|hour=10|gap=3_plus | 20 | 92.7% | - | - |
| source=weather_current|hour=11 | 64 | 91.5% | - | - |
| source=weather_current|hour=11|gap=2 | 36 | 85.3% | - | - |
| source=weather_current|hour=11|gap=3_plus | 20 | 97.3% | - | - |
| source=weather_current|hour=12 | 59 | 84.3% | - | - |
| source=weather_current|hour=12|gap=2 | 41 | 77.7% | - | - |
| source=weather_current|hour=13 | 54 | 77.5% | - | - |
| source=weather_current|hour=13|gap=1 | 28 | 98.0% | - | - |
| source=weather_current|hour=13|gap=2 | 21 | 45.2% | - | - |
| source=weather_current|hour=14 | 58 | 62.3% | - | - |
| source=weather_current|hour=14|gap=1 | 30 | 79.4% | - | - |
| source=weather_current|hour=14|gap=2 | 28 | 44.7% | - | - |
| source=weather_current|hour=15 | 61 | 43.5% | - | - |
| source=weather_current|hour=15|gap=1 | 36 | 56.3% | - | - |
| source=weather_current|hour=15|gap=2 | 25 | 27.4% | - | - |
| source=weather_current|hour=16 | 66 | 25.6% | - | - |
| source=weather_current|hour=16|gap=1 | 38 | 38.5% | - | - |
| source=weather_current|hour=16|gap=2 | 24 | 13.1% | - | - |
| source=weather_current|hour=17 | 62 | 10.0% | - | - |
| source=weather_current|hour=17|gap=1 | 40 | 15.2% | - | - |
| source=weather_current|hour=18 | 63 | 2.2% | - | - |
| source=weather_current|hour=18|gap=1 | 46 | 2.9% | - | - |
| source=weather_current|hour=19 | 63 | 2.2% | - | - |
| source=weather_current|hour=19|gap=1 | 46 | 2.9% | - | - |
| source=weather_current|hour=1|gap=3_plus | 48 | 62.8% | - | - |
| source=weather_current|hour=2 | 44 | 59.6% | - | - |
| source=weather_current|hour=20 | 50 | 2.7% | - | - |
| source=weather_current|hour=20|gap=1 | 35 | 3.8% | - | - |
| source=weather_current|hour=21 | 48 | 2.8% | - | - |
| source=weather_current|hour=21|gap=1 | 36 | 3.7% | - | - |
| source=weather_current|hour=22 | 40 | 3.3% | - | - |
| source=weather_current|hour=22|gap=1 | 29 | 4.5% | - | - |
| source=weather_current|hour=23 | 41 | 3.3% | - | - |
| source=weather_current|hour=23|gap=1 | 29 | 4.5% | - | - |
| source=weather_current|hour=2|gap=3_plus | 44 | 59.6% | - | - |
| source=weather_current|hour=3 | 42 | 57.7% | - | - |
| source=weather_current|hour=3|gap=3_plus | 42 | 57.7% | - | - |
| source=weather_current|hour=4 | 42 | 57.7% | - | - |
| source=weather_current|hour=4|gap=3_plus | 42 | 57.7% | - | - |
| source=weather_current|hour=5 | 41 | 59.1% | - | - |
| source=weather_current|hour=5|gap=3_plus | 41 | 59.1% | - | - |
| source=weather_current|hour=6 | 42 | 57.7% | - | - |
| source=weather_current|hour=6|gap=3_plus | 42 | 57.7% | - | - |
| source=weather_current|hour=8 | 27 | 97.9% | - | - |
| source=weather_current|hour=9 | 37 | 98.5% | - | - |

## WU Revision Contexts

| Context | N | Revision-up rate | Mean positive gap |
| :--- | ---: | ---: | ---: |
| hour=0 | 41 | 97.7% | 7.39 |
| hour=1 | 48 | 98.0% | 7.38 |
| hour=10 | 718 | 92.5% | 4.18 |
| hour=11 | 720 | 89.1% | 3.27 |
| hour=12 | 724 | 83.5% | 2.45 |
| hour=13 | 721 | 71.5% | 1.98 |
| hour=14 | 730 | 57.1% | 1.63 |
| hour=15 | 731 | 37.1% | 1.39 |
| hour=16 | 728 | 17.8% | 1.31 |
| hour=17 | 726 | 7.4% | 1.32 |
| hour=18 | 724 | 2.5% | 1.41 |
| hour=19 | 724 | 1.5% | 1.70 |
| hour=2 | 44 | 97.8% | 7.50 |
| hour=20 | 716 | 0.3% | 2.00 |
| hour=21 | 57 | 1.7% | 0.00 |
| hour=22 | 52 | 1.9% | 0.00 |
| hour=23 | 52 | 1.9% | 0.00 |
| hour=3 | 42 | 97.7% | 7.57 |
| hour=4 | 42 | 97.7% | 7.57 |
| hour=5 | 41 | 97.7% | 7.63 |
| hour=6 | 42 | 97.7% | 7.57 |
| hour=7 | 40 | 97.6% | 7.65 |
| hour=8 | 703 | 93.6% | 6.69 |
| hour=9 | 712 | 93.1% | 5.39 |

## Live Use

WU history remains the only hard settlement floor. When SWOB leads WU, live inference uses the learned catch-up rate to decide how strongly to suppress buckets below the SWOB-observed bucket.

