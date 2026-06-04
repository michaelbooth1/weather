# Replay Backtest (model re-run over captured inputs)

Generated: 2026-06-03 20:20

Days scored: 7  |  Snapshots replayed: 568  |  Band-rows: 6248
Replayed model version(s): v0.4.9 HGBC feature-based ML model
Reconstructed days included: True

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
| Same code version (canary) | 1 | 0.0000 | 0.0000 | FAITHFUL |
| Changed code version (effect size) | 0 | - | - | code change moved the distribution |
| Reconstructed (approximate) | 567 | 0.4448 | - | approximate inputs -- exploratory only |

## Headline: Replayed vs Recorded vs Market

| Scope | Days | Rows | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Replayed Skill | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| All snapshots | - | 6248 | 0.0437 | 0.0571 | 0.0262 | -0.0134 | -0.667 | 9.1% |
| Daily-first equal-day average | 7 | 6248 | 0.0459 | 0.0671 | 0.0282 | -0.0212 | -1.120 | 9.1% |
| Last pre-close | - | 77 | 0.0024 | 0.0363 | 0.0000 | -0.0338 | -534.814 | 9.1% |

## Per Target Day

| Date | Settlement | Source | Snaps | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-06-01 | 19 C | snapshot_high | 85 | 0.0423 | 0.0425 | 0.0332 | -0.0001 | snapshot wu_history_high (daily summary missing/incomplete) |
| 2026-06-02 | 25 C | snapshot_high | 144 | 0.0543 | 0.0610 | 0.0315 | -0.0067 | snapshot wu_history_high (daily summary missing/incomplete) |
| 2026-06-03 | 29 C | snapshot_high | 122 | 0.0163 | 0.0174 | 0.0031 | -0.0011 | snapshot wu_history_high (daily summary missing/incomplete) |
| 2026-05-27 | 25 C | snapshot_high | 45 | 0.0163 | 0.1484 | 0.0100 | -0.1321 | daily_summary=22 (rows=12) disagrees with snapshot high=25 |
| 2026-05-28 | 20 C | snapshot_high | 64 | 0.0509 | 0.0583 | 0.0394 | -0.0074 | snapshot wu_history_high (daily summary missing/incomplete) |
| 2026-05-30 | 20 C | snapshot_high | 51 | 0.1036 | 0.0952 | 0.0614 | +0.0084 | snapshot wu_history_high (daily summary missing/incomplete) |
| 2026-05-31 | 24 C | snapshot_high | 57 | 0.0378 | 0.0469 | 0.0184 | -0.0091 | snapshot wu_history_high (daily summary missing/incomplete) |

## By Capture Hour

| Group | Rows | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Replayed Skill | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | 121 | 0.0639 | 0.0656 | 0.0307 | -0.0017 | -1.084 | 9.1% |
| 1 | 132 | 0.0521 | 0.0552 | 0.0279 | -0.0031 | -0.870 | 9.1% |
| 2 | 132 | 0.0419 | 0.0472 | 0.0273 | -0.0053 | -0.534 | 9.1% |
| 3 | 132 | 0.0598 | 0.0603 | 0.0280 | -0.0005 | -1.131 | 9.1% |
| 4 | 132 | 0.0536 | 0.0565 | 0.0273 | -0.0029 | -0.959 | 9.1% |
| 5 | 132 | 0.0555 | 0.0574 | 0.0263 | -0.0019 | -1.106 | 9.1% |
| 6 | 132 | 0.0566 | 0.0582 | 0.0259 | -0.0016 | -1.184 | 9.1% |
| 7 | 132 | 0.0475 | 0.0510 | 0.0259 | -0.0035 | -0.834 | 9.1% |
| 8 | 165 | 0.0408 | 0.0539 | 0.0293 | -0.0131 | -0.395 | 9.1% |
| 9 | 231 | 0.0504 | 0.0616 | 0.0425 | -0.0113 | -0.184 | 9.1% |
| 10 | 308 | 0.0623 | 0.0603 | 0.0522 | +0.0020 | -0.195 | 9.1% |
| 11 | 374 | 0.0687 | 0.0534 | 0.0464 | +0.0154 | -0.482 | 9.1% |
| 12 | 363 | 0.0624 | 0.0535 | 0.0431 | +0.0089 | -0.446 | 9.1% |
| 13 | 341 | 0.0366 | 0.0441 | 0.0343 | -0.0075 | -0.068 | 9.1% |
| 14 | 418 | 0.0625 | 0.0541 | 0.0330 | +0.0084 | -0.895 | 9.1% |
| 15 | 462 | 0.0564 | 0.0573 | 0.0315 | -0.0010 | -0.792 | 9.1% |
| 16 | 462 | 0.0490 | 0.0778 | 0.0279 | -0.0288 | -0.754 | 9.1% |
| 17 | 451 | 0.0353 | 0.0637 | 0.0190 | -0.0284 | -0.863 | 9.1% |
| 18 | 451 | 0.0301 | 0.0543 | 0.0159 | -0.0242 | -0.899 | 9.1% |
| 19 | 451 | 0.0236 | 0.0570 | 0.0062 | -0.0334 | -2.795 | 9.1% |
| 20 | 264 | 0.0081 | 0.0636 | 0.0002 | -0.0555 | -45.955 | 9.1% |
| 21 | 198 | 0.0041 | 0.0760 | 0.0000 | -0.0719 | -11787.409 | 9.1% |
| 22 | 132 | 0.0027 | 0.0243 | 0.0000 | -0.0216 | -7733.130 | 9.1% |
| 23 | 132 | 0.0025 | 0.0230 | 0.0000 | -0.0205 | -8494.998 | 9.1% |

## By Market-Bin Type

| Group | Rows | Replayed Brier | Recorded Brier | Market Brier | Code Effect | Replayed Skill | Base Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eq | 5112 | 0.0494 | 0.0657 | 0.0315 | -0.0162 | -0.571 | 8.7% |
| gte | 568 | 0.0357 | 0.0369 | 0.0052 | -0.0012 | -5.931 | 21.5% |
| lte | 568 | 0.0003 | 0.0006 | 0.0000 | -0.0003 | -908.574 | 0.0% |

## Replayed Reliability

| Confidence bin | N | Mean predicted | Realized |
| :--- | :--- | :--- | :--- |
| 0.0-0.2 | 5392 | 2.4% | 1.8% |
| 0.2-0.4 | 403 | 27.6% | 39.2% |
| 0.4-0.6 | 147 | 49.8% | 45.6% |
| 0.6-0.8 | 110 | 70.1% | 62.7% |
| 0.8-1.0 | 196 | 89.6% | 91.3% |
