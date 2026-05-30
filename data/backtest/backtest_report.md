# Settlement-Scored Backtest

Generated: 2026-05-30 10:26

Market days: 2  |  Total band-rows scored: 1199


> Model resolution = WU CYYZ printed daily high. Results over a handful of
> market days are **illustrative, not conclusive**; intraday snapshots of the
> same day are correlated. The harness scales as more days are captured.


## Settlement (the crux)

| Date | Settlement bucket | Source | Note |
| :--- | :--- | :--- | :--- |
| 2026-05-27 | 25 C | snapshot_high | daily_summary=22 (rows=12) disagrees with snapshot high=25 |
| 2026-05-28 | 20 C | snapshot_high | snapshot wu_history_high (daily summary missing/incomplete) |

## Model vs Market (settlement-scored, all snapshots)

| Metric | Model | Market |
| :--- | :--- | :--- |
| Brier (lower better) | 0.0955 | 0.0273 |
| Log loss (lower better) | 0.4067 | 0.0874 |

**Brier skill score (model vs market): -2.498** (>0 means the model beats the market). N = 1199 band-rows, base rate 9.1%.


### Model reliability

| Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- |
| 0.0-0.2 | 1047 | 1.9% | 5.4% |
| 0.2-0.4 | 54 | 27.3% | 31.5% |
| 0.4-0.6 | 25 | 47.6% | 48.0% |
| 0.6-0.8 | 18 | 65.8% | 27.8% |
| 0.8-1.0 | 55 | 93.0% | 32.7% |

### Market reliability

| Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- |
| 0.0-0.2 | 1028 | 1.6% | 0.2% |
| 0.2-0.4 | 56 | 30.3% | 46.4% |
| 0.4-0.6 | 64 | 46.3% | 46.9% |
| 0.6-0.8 | 1 | 61.0% | 100.0% |
| 0.8-1.0 | 50 | 94.8% | 100.0% |

## Realized edge / P&L (trade when |model - market| > threshold, hold to resolution)

P&L is in shares (max +1 / -1 each). **Per-snapshot** counts every snapshot as a trade (overcounts correlated intraday signals); **first-entry** takes one trade per band at the first snapshot that clears the threshold.

| Threshold | Per-snapshot trades | Per-snapshot P&L | Avg | Hit rate | First-entry trades | First-entry P&L | Avg |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0.05 | 280 | -13.52 | -0.048 | 26.1% | 13 | +0.50 | +0.039 |
| 0.10 | 215 | -14.23 | -0.066 | 22.3% | 11 | +0.58 | +0.053 |
| 0.15 | 160 | -12.35 | -0.077 | 18.8% | 10 | +1.12 | +0.112 |

## Edge persistence per band

| Date | Band | Snapshots | Mean edge | % edge up | % edge down | Settled YES? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-05-27 | 19 C or below | 45 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-27 | 20 C | 45 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-27 | 21 C | 45 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-27 | 22 C | 45 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-27 | 23 C | 45 | -0.00 | 0.0% | 2.2% | 0 |
| 2026-05-27 | 24 C | 45 | -0.06 | 0.0% | 24.4% | 0 |
| 2026-05-27 | 25 C | 45 | -0.72 | 15.6% | 84.4% | 1 |
| 2026-05-27 | 26 C | 45 | +0.76 | 91.1% | 8.9% | 0 |
| 2026-05-27 | 27 C | 45 | +0.02 | 15.6% | 0.0% | 0 |
| 2026-05-27 | 28 C | 45 | -0.00 | 0.0% | 0.0% | 0 |
| 2026-05-27 | 29 C or higher | 45 | -0.00 | 0.0% | 0.0% | 0 |
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
