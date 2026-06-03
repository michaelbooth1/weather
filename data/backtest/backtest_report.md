# Settlement-Scored Backtest

Generated: 2026-05-31 12:56

Market days: 1  |  Total band-rows scored: 704
Quality filter: complete, manual_override

> Model resolution = WU CYYZ printed daily high. Results over a handful of
> market days are illustrative, not conclusive. Intraday snapshots from the
> same day are correlated, so use the daily-first, last-pre-close, and
> fixed-cutoff sections as the safer accuracy gates.

## Model Card

| Metric | Value |
| :--- | :--- |
| Market days | 1 |
| All-snapshot band rows | 704 |
| Model versions | v0.3 empirical intraday, v0.4.1 HGBC feature-based ML model, v0.4.2 HGBC feature-based ML model, v0.4.3 HGBC feature-based ML model, v0.4.4 HGBC feature-based ML model, v0.4.5 HGBC feature-based ML model, v0.4.6 HGBC feature-based ML model, v0.4.7 HGBC feature-based ML model, v0.4.9 HGBC feature-based ML model |
| All-snapshot Brier skill vs market | -0.478 |
| Daily-first Brier skill vs market | -0.478 |
| All-snapshot log-loss delta (market - model) | -0.0620 |
| Model ECE | 0.0203 |
| Market ECE | 0.0394 |

## Run Inputs And Settlement

| Date | Snapshot tape | Snapshots | Bands | Model versions | Settlement | Source | Quality | Note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-28 | data\snapshots\highest-temperature-in-toronto-on-may-28-2026\snapshots_long.csv | 64 | 11 | v0.3 empirical intraday, v0.4.1 HGBC feature-based ML model, v0.4.2 HGBC feature-based ML model, v0.4.3 HGBC feature-based ML model, v0.4.4 HGBC feature-based ML model, v0.4.5 HGBC feature-based ML model, v0.4.6 HGBC feature-based ML model, v0.4.7 HGBC feature-based ML model, v0.4.9 HGBC feature-based ML model | 20 C | snapshot_high | complete | snapshot wu_history_high (daily summary missing/incomplete) |

## Feature Vector Coverage

| Rows | Rows with features | Coverage | Feature schemas |
| :--- | :--- | :--- | :--- |
| 704 | 0 | 0.0% | - |

## Score Summary

| Scope | Days | Rows | Model Brier | Market Brier | Brier Delta | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| All snapshots | - | 704 | 0.0583 | 0.0394 | -0.0188 | -0.478 | 0.1850 | 0.1230 | -0.0620 | 9.1% |
| Daily-first equal-day average | 1 | 704 | 0.0583 | 0.0394 | -0.0188 | -0.478 | 0.1850 | 0.1230 | -0.0620 | 9.1% |
| Last pre-close | - | 11 | 0.0036 | 0.0000 | -0.0036 | -472.419 | 0.0282 | 0.0019 | -0.0263 | 9.1% |

## Model Vs Market By Target Day

| Date | Rows | Model Brier | Market Brier | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-28 | 704 | 0.0583 | 0.0394 | -0.478 | 0.1850 | 0.1230 | -0.0620 | 9.1% |

## Model Vs Market By Capture Hour

| Hour | Rows | Model Brier | Market Brier | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 8 | 11 | 0.0813 | 0.0554 | -0.466 | 0.2650 | 0.1698 | -0.0952 | 9.1% |
| 9 | 66 | 0.1023 | 0.0615 | -0.663 | 0.3641 | 0.1837 | -0.1804 | 9.1% |
| 10 | 66 | 0.0982 | 0.0637 | -0.540 | 0.3450 | 0.1896 | -0.1554 | 9.1% |
| 11 | 55 | 0.0914 | 0.0676 | -0.354 | 0.2812 | 0.1983 | -0.0829 | 9.1% |
| 12 | 66 | 0.0771 | 0.0691 | -0.115 | 0.2154 | 0.2014 | -0.0140 | 9.1% |
| 13 | 66 | 0.0354 | 0.0439 | +0.194 | 0.1196 | 0.1352 | +0.0156 | 9.1% |
| 14 | 66 | 0.0360 | 0.0290 | -0.243 | 0.1264 | 0.1041 | -0.0223 | 9.1% |
| 15 | 66 | 0.0549 | 0.0363 | -0.515 | 0.1570 | 0.1193 | -0.0377 | 9.1% |
| 16 | 66 | 0.0877 | 0.0433 | -1.027 | 0.2221 | 0.1294 | -0.0927 | 9.1% |
| 17 | 55 | 0.0400 | 0.0071 | -4.607 | 0.1119 | 0.0392 | -0.0727 | 9.1% |
| 18 | 66 | 0.0037 | 0.0022 | -0.678 | 0.0287 | 0.0202 | -0.0085 | 9.1% |
| 19 | 55 | 0.0036 | 0.0001 | -60.476 | 0.0282 | 0.0038 | -0.0244 | 9.1% |

## Model Vs Market By Market-Bin Type

| Bin Type | Rows | Model Brier | Market Brier | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eq | 576 | 0.0711 | 0.0482 | -0.476 | 0.2244 | 0.1498 | -0.0746 | 11.1% |
| gte | 64 | 0.0006 | 0.0000 | -19.644 | 0.0155 | 0.0044 | -0.0111 | 0.0% |
| lte | 64 | 0.0000 | 0.0000 | +1.000 | 0.0000 | 0.0005 | +0.0005 | 0.0% |

## Fixed-Cutoff Performance

Each row uses the first available snapshot at or after the cutoff hour for each day-band.

| Cutoff | Rows | Model Brier | Market Brier | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 11 | 0.0813 | 0.0601 | -0.353 | 0.2650 | 0.1806 | -0.0844 | 9.1% |
| 10:00 | 11 | 0.1020 | 0.0642 | -0.589 | 0.3807 | 0.1904 | -0.1904 | 9.1% |
| 12:00 | 11 | 0.0807 | 0.0831 | +0.029 | 0.2148 | 0.2417 | +0.0269 | 9.1% |
| 13:00 | 11 | 0.0713 | 0.0552 | -0.293 | 0.1907 | 0.1617 | -0.0290 | 9.1% |
| 15:00 | 11 | 0.0183 | 0.0254 | +0.281 | 0.0789 | 0.0941 | +0.0152 | 9.1% |
| 16:00 | 11 | 0.0781 | 0.0276 | -1.826 | 0.2013 | 0.1025 | -0.0988 | 9.1% |
| 17:00 | 11 | 0.0946 | 0.0192 | -3.918 | 0.2337 | 0.0724 | -0.1613 | 9.1% |
| 18:00 | 11 | 0.0043 | 0.0053 | +0.182 | 0.0311 | 0.0350 | +0.0040 | 9.1% |

## Realized Edge / P&L

P&L is in shares (max +1 / -1 each). Per-snapshot overcounts correlated
intraday signals; first-entry takes one trade per day-band at the first
threshold crossing; last-pre-close takes one trade per day-band at the
last available snapshot.

| Threshold | Per-snapshot trades | Per-snapshot P&L | First-entry trades | First-entry P&L | Last-pre-close trades | Last-pre-close P&L |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0.05 | 171 | -15.36 | 8 | -0.33 | 2 | -0.01 |
| 0.10 | 114 | -16.44 | 7 | -0.24 | 2 | -0.01 |
| 0.15 | 64 | -14.21 | 7 | +0.26 | 0 | +0.00 |

## Overall Reliability

### Model Reliability

| Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- |
| 0.0-0.2 | 600 | 2.8% | 3.2% |
| 0.2-0.4 | 51 | 27.4% | 33.3% |
| 0.4-0.6 | 25 | 47.6% | 48.0% |
| 0.6-0.8 | 14 | 65.2% | 14.3% |
| 0.8-1.0 | 14 | 85.2% | 100.0% |

### Market Reliability

| Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- |
| 0.0-0.2 | 591 | 2.2% | 0.3% |
| 0.2-0.4 | 42 | 30.3% | 57.1% |
| 0.4-0.6 | 54 | 46.1% | 38.9% |
| 0.6-0.8 | 1 | 61.0% | 100.0% |
| 0.8-1.0 | 16 | 91.1% | 100.0% |

## Reliability By Capture Hour

### Model By Hour

| Hour | Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- | :--- |
| 8 | 0.0-0.2 | 10 | 7.2% | 10.0% |
| 8 | 0.2-0.4 | 1 | 27.9% | 0.0% |
| 9 | 0.0-0.2 | 59 | 5.7% | 10.2% |
| 9 | 0.2-0.4 | 3 | 27.0% | 0.0% |
| 9 | 0.4-0.6 | 4 | 45.2% | 0.0% |
| 10 | 0.0-0.2 | 54 | 4.6% | 11.1% |
| 10 | 0.2-0.4 | 11 | 28.1% | 0.0% |
| 10 | 0.4-0.6 | 1 | 44.7% | 0.0% |
| 11 | 0.0-0.2 | 49 | 5.4% | 10.2% |
| 11 | 0.2-0.4 | 3 | 32.1% | 0.0% |
| 11 | 0.4-0.6 | 3 | 46.7% | 0.0% |
| 12 | 0.0-0.2 | 53 | 2.2% | 1.9% |
| 12 | 0.2-0.4 | 7 | 27.2% | 57.1% |
| 12 | 0.4-0.6 | 5 | 46.6% | 20.0% |
| 12 | 0.6-0.8 | 1 | 61.4% | 0.0% |
| 13 | 0.0-0.2 | 55 | 2.6% | 0.0% |
| 13 | 0.2-0.4 | 5 | 27.1% | 20.0% |
| 13 | 0.4-0.6 | 5 | 51.4% | 80.0% |
| 13 | 0.6-0.8 | 1 | 64.3% | 100.0% |
| 14 | 0.0-0.2 | 53 | 3.1% | 0.0% |
| 14 | 0.2-0.4 | 8 | 25.4% | 12.5% |
| 14 | 0.4-0.6 | 5 | 46.9% | 100.0% |
| 15 | 0.0-0.2 | 55 | 2.1% | 0.0% |
| 15 | 0.2-0.4 | 5 | 26.7% | 60.0% |
| 15 | 0.4-0.6 | 2 | 49.8% | 100.0% |
| 15 | 0.6-0.8 | 4 | 63.1% | 25.0% |
| 16 | 0.0-0.2 | 54 | 0.7% | 0.0% |
| 16 | 0.2-0.4 | 6 | 27.5% | 100.0% |
| 16 | 0.6-0.8 | 6 | 65.9% | 0.0% |
| 17 | 0.0-0.2 | 48 | 1.1% | 0.0% |
| 17 | 0.2-0.4 | 2 | 26.5% | 100.0% |
| 17 | 0.6-0.8 | 2 | 69.8% | 0.0% |
| 17 | 0.8-1.0 | 3 | 84.2% | 100.0% |
| 18 | 0.0-0.2 | 60 | 1.5% | 0.0% |
| 18 | 0.8-1.0 | 6 | 85.4% | 100.0% |
| 19 | 0.0-0.2 | 50 | 1.4% | 0.0% |
| 19 | 0.8-1.0 | 5 | 85.6% | 100.0% |

### Market By Hour

| Hour | Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- | :--- |
| 8 | 0.0-0.2 | 9 | 3.3% | 0.0% |
| 8 | 0.2-0.4 | 1 | 35.5% | 100.0% |
| 8 | 0.4-0.6 | 1 | 40.5% | 0.0% |
| 9 | 0.0-0.2 | 54 | 3.4% | 0.0% |
| 9 | 0.2-0.4 | 6 | 31.4% | 100.0% |
| 9 | 0.4-0.6 | 6 | 41.7% | 0.0% |
| 10 | 0.0-0.2 | 54 | 3.6% | 0.0% |
| 10 | 0.2-0.4 | 6 | 30.5% | 100.0% |
| 10 | 0.4-0.6 | 6 | 42.3% | 0.0% |
| 11 | 0.0-0.2 | 45 | 3.6% | 0.0% |
| 11 | 0.2-0.4 | 5 | 27.9% | 100.0% |
| 11 | 0.4-0.6 | 5 | 42.8% | 0.0% |
| 12 | 0.0-0.2 | 54 | 3.4% | 3.7% |
| 12 | 0.2-0.4 | 6 | 29.6% | 66.7% |
| 12 | 0.4-0.6 | 6 | 45.5% | 0.0% |
| 13 | 0.0-0.2 | 54 | 1.9% | 0.0% |
| 13 | 0.2-0.4 | 3 | 35.2% | 0.0% |
| 13 | 0.4-0.6 | 9 | 45.3% | 66.7% |
| 14 | 0.0-0.2 | 54 | 1.9% | 0.0% |
| 14 | 0.2-0.4 | 6 | 28.5% | 0.0% |
| 14 | 0.4-0.6 | 6 | 53.2% | 100.0% |
| 15 | 0.0-0.2 | 53 | 1.6% | 0.0% |
| 15 | 0.2-0.4 | 7 | 28.9% | 14.3% |
| 15 | 0.4-0.6 | 6 | 51.7% | 83.3% |
| 16 | 0.0-0.2 | 55 | 1.6% | 0.0% |
| 16 | 0.2-0.4 | 2 | 35.2% | 50.0% |
| 16 | 0.4-0.6 | 8 | 47.6% | 50.0% |
| 16 | 0.6-0.8 | 1 | 61.0% | 100.0% |
| 17 | 0.0-0.2 | 49 | 1.5% | 0.0% |
| 17 | 0.4-0.6 | 1 | 43.0% | 0.0% |
| 17 | 0.8-1.0 | 5 | 84.7% | 100.0% |
| 18 | 0.0-0.2 | 60 | 1.1% | 0.0% |
| 18 | 0.8-1.0 | 6 | 90.4% | 100.0% |
| 19 | 0.0-0.2 | 50 | 0.2% | 0.0% |
| 19 | 0.8-1.0 | 5 | 98.3% | 100.0% |

## Reliability By Market Band

### Model By Band

| Band | Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- | :--- |
| 13 C or below | 0.0-0.2 | 64 | 0.0% | 0.0% |
| 14 C | 0.0-0.2 | 64 | 0.0% | 0.0% |
| 15 C | 0.0-0.2 | 64 | 0.0% | 0.0% |
| 16 C | 0.0-0.2 | 64 | 0.6% | 0.0% |
| 17 C | 0.0-0.2 | 60 | 1.4% | 0.0% |
| 17 C | 0.2-0.4 | 4 | 23.9% | 0.0% |
| 18 C | 0.0-0.2 | 62 | 2.4% | 0.0% |
| 18 C | 0.2-0.4 | 1 | 37.5% | 0.0% |
| 18 C | 0.4-0.6 | 1 | 40.8% | 0.0% |
| 19 C | 0.0-0.2 | 20 | 3.3% | 0.0% |
| 19 C | 0.2-0.4 | 20 | 29.1% | 0.0% |
| 19 C | 0.4-0.6 | 12 | 47.8% | 0.0% |
| 19 C | 0.6-0.8 | 12 | 65.5% | 0.0% |
| 20 C | 0.0-0.2 | 19 | 9.4% | 100.0% |
| 20 C | 0.2-0.4 | 17 | 27.5% | 100.0% |
| 20 C | 0.4-0.6 | 12 | 48.0% | 100.0% |
| 20 C | 0.6-0.8 | 2 | 63.7% | 100.0% |
| 20 C | 0.8-1.0 | 14 | 85.2% | 100.0% |
| 21 C | 0.0-0.2 | 59 | 12.2% | 0.0% |
| 21 C | 0.2-0.4 | 5 | 23.8% | 0.0% |
| 22 C | 0.0-0.2 | 60 | 6.3% | 0.0% |
| 22 C | 0.2-0.4 | 4 | 23.0% | 0.0% |
| 23 C or higher | 0.0-0.2 | 64 | 1.5% | 0.0% |

### Market By Band

| Band | Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- | :--- |
| 13 C or below | 0.0-0.2 | 64 | 0.1% | 0.0% |
| 14 C | 0.0-0.2 | 64 | 0.1% | 0.0% |
| 15 C | 0.0-0.2 | 64 | 0.1% | 0.0% |
| 16 C | 0.0-0.2 | 64 | 0.1% | 0.0% |
| 17 C | 0.0-0.2 | 64 | 0.5% | 0.0% |
| 18 C | 0.0-0.2 | 62 | 4.3% | 0.0% |
| 18 C | 0.2-0.4 | 2 | 21.5% | 0.0% |
| 19 C | 0.0-0.2 | 23 | 4.7% | 0.0% |
| 19 C | 0.2-0.4 | 8 | 32.1% | 0.0% |
| 19 C | 0.4-0.6 | 33 | 44.0% | 0.0% |
| 20 C | 0.0-0.2 | 2 | 19.5% | 100.0% |
| 20 C | 0.2-0.4 | 24 | 31.4% | 100.0% |
| 20 C | 0.4-0.6 | 21 | 49.5% | 100.0% |
| 20 C | 0.6-0.8 | 1 | 61.0% | 100.0% |
| 20 C | 0.8-1.0 | 16 | 91.1% | 100.0% |
| 21 C | 0.0-0.2 | 56 | 12.0% | 0.0% |
| 21 C | 0.2-0.4 | 8 | 27.7% | 0.0% |
| 22 C | 0.0-0.2 | 64 | 1.8% | 0.0% |
| 23 C or higher | 0.0-0.2 | 64 | 0.4% | 0.0% |

## Edge Persistence Per Band

| Date | Band | Snapshots | Mean edge | % edge up | % edge down | Settled YES? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-28 | 13 C or below | 64 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-28 | 14 C | 64 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-28 | 15 C | 64 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-28 | 16 C | 64 | +0.00 | 3.1% | 0.0% | 0 |
| 2026-05-28 | 17 C | 64 | +0.02 | 12.5% | 0.0% | 0 |
| 2026-05-28 | 18 C | 64 | -0.01 | 3.1% | 12.5% | 0 |
| 2026-05-28 | 19 C | 64 | +0.03 | 31.2% | 28.1% | 0 |
| 2026-05-28 | 20 C | 64 | -0.13 | 9.4% | 70.3% | 1 |
| 2026-05-28 | 21 C | 64 | -0.01 | 18.8% | 28.1% | 0 |
| 2026-05-28 | 22 C | 64 | +0.06 | 46.9% | 0.0% | 0 |
| 2026-05-28 | 23 C or higher | 64 | +0.01 | 3.1% | 0.0% | 0 |
