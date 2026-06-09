# Replay Backtest (model re-run over captured inputs)

Generated: 2026-06-09 09:06

Days scored: 1  |  Snapshots replayed: 140  |  Band-rows: 1540
Replayed model version(s): v0.5.0 HGBC feature-based ML model
Reconstructed days included: False

> **Code Effect = Replayed Brier - Recorded Brier** (negative = the current
> code is better than what was deployed when the snapshot was captured).
> Recorded/market are the frozen tape values; replayed is today's code re-run
> over the identical stored inputs. Lower Brier is better.

## Replay Fidelity Canary

Replaying a snapshot with the *same* code version that produced it must
reproduce its recorded distribution (L1 ~ 0). A large same-version L1 means
the corpus is not faithfully replayable -- investigate before trusting scores.

| Cohort | Snapshots | Mean L1 | Max L1 | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| Same code version (canary) | 139 | 0.2794 | 0.7822 | CHECK |
| Changed code version (effect size) | 1 | 0.6003 | - | code change moved the distribution |
| Reconstructed (approximate) | 0 | - | - | approximate inputs -- exploratory only |

## Headline: Replayed vs Recorded vs Market

| Scope | Days | Rows | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Replayed Skill | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| All snapshots | - | 1540 | 0.0501 | 0.0506 | 0.0536 | -0.0005 | +0.065 | 9.1% |
| Daily-first equal-day average | 1 | 1540 | 0.0501 | 0.0506 | 0.0536 | -0.0005 | +0.065 | 9.1% |
| Last pre-close | - | 11 | 0.0000 | 0.0007 | 0.0000 | -0.0007 | -69.827 | 9.1% |

## Per Target Day

| Date | Settlement | Source | Snaps | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-06-07 | 24 C | settlement_ledger:daily_summary | 140 | 0.0501 | 0.0506 | 0.0536 | -0.0005 | polymarket_reconciliation=match |

## By Capture Hour

| Group | Rows | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Replayed Skill | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | 66 | 0.0763 | 0.1057 | 0.0870 | -0.0295 | +0.123 | 9.1% |
| 1 | 66 | 0.0197 | 0.0699 | 0.0845 | -0.0502 | +0.767 | 9.1% |
| 2 | 66 | 0.0477 | 0.0621 | 0.0830 | -0.0144 | +0.425 | 9.1% |
| 3 | 66 | 0.0606 | 0.0731 | 0.0783 | -0.0125 | +0.226 | 9.1% |
| 4 | 66 | 0.0960 | 0.0946 | 0.0779 | +0.0014 | -0.232 | 9.1% |
| 5 | 66 | 0.0947 | 0.0877 | 0.0806 | +0.0071 | -0.176 | 9.1% |
| 6 | 66 | 0.1008 | 0.0897 | 0.0789 | +0.0112 | -0.278 | 9.1% |
| 7 | 55 | 0.0991 | 0.0886 | 0.0832 | +0.0105 | -0.191 | 9.1% |
| 8 | 66 | 0.0973 | 0.0875 | 0.0804 | +0.0098 | -0.210 | 9.1% |
| 9 | 66 | 0.0989 | 0.0914 | 0.0797 | +0.0075 | -0.241 | 9.1% |
| 10 | 66 | 0.0790 | 0.0664 | 0.0792 | +0.0126 | +0.002 | 9.1% |
| 11 | 66 | 0.0712 | 0.0651 | 0.0747 | +0.0061 | +0.048 | 9.1% |
| 12 | 66 | 0.0710 | 0.0592 | 0.0731 | +0.0118 | +0.028 | 9.1% |
| 13 | 55 | 0.0648 | 0.0360 | 0.0709 | +0.0289 | +0.086 | 9.1% |
| 14 | 66 | 0.0733 | 0.0607 | 0.0781 | +0.0127 | +0.061 | 9.1% |
| 15 | 66 | 0.0227 | 0.0259 | 0.0463 | -0.0032 | +0.509 | 9.1% |
| 16 | 66 | 0.0093 | 0.0159 | 0.0322 | -0.0066 | +0.712 | 9.1% |
| 17 | 66 | 0.0070 | 0.0082 | 0.0069 | -0.0012 | -0.020 | 9.1% |
| 18 | 55 | 0.0040 | 0.0066 | 0.0015 | -0.0026 | -1.693 | 9.1% |
| 19 | 66 | 0.0026 | 0.0051 | 0.0001 | -0.0025 | -45.733 | 9.1% |
| 20 | 66 | 0.0014 | 0.0021 | 0.0000 | -0.0007 | -2347.370 | 9.1% |
| 21 | 66 | 0.0000 | 0.0008 | 0.0000 | -0.0008 | -51.283 | 9.1% |
| 22 | 66 | 0.0000 | 0.0008 | 0.0000 | -0.0008 | -76.632 | 9.1% |
| 23 | 55 | 0.0000 | 0.0007 | 0.0000 | -0.0007 | -69.827 | 9.1% |

## By Market-Bin Type

| Group | Rows | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Replayed Skill | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eq | 1260 | 0.0613 | 0.0619 | 0.0655 | -0.0006 | +0.065 | 11.1% |
| gte | 140 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | -2.044 | 0.0% |
| lte | 140 | 0.0001 | 0.0001 | 0.0000 | +0.0000 | -292.916 | 0.0% |

## Replayed Reliability

| Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- |
| 0.0-0.2 | 1343 | 2.8% | 3.9% |
| 0.2-0.4 | 75 | 29.8% | 25.3% |
| 0.4-0.6 | 73 | 50.0% | 27.4% |
| 0.6-0.8 | 10 | 74.4% | 100.0% |
| 0.8-1.0 | 39 | 93.4% | 100.0% |
