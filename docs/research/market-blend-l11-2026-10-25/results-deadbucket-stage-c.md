# Dead-bucket check, stage C and history (lane L11, 2026-10-25)

Development evidence only. Stage C is a **gross upper bound and is NOT EXECUTABLE**: layout prices, an assumed
2-cent spread and unlimited depth. It cannot support a money claim. Stage A, with the real books and trade
prints, decides.

- Rule: `deadbucket_rule_r2.md`, sha256 `177e9acfd7dc50b60d53bdd236ecef971ebcdf767f9dbf4cd0bd241579b17774`.
  It is the original rule `a17ed258…9663` plus dated clarification 1 (`f6d21bdd…07cb`, which on its own lacks
  the five prereg sections). The r2 file passes prereg_check. The clarification sets the stage-A window to
  08-10..09-29 and takes fills from trade prints. Both were written before any row below.
- Code: `weather.calibration.dead_bucket` at `682851ca9`, run through `workstation_heavy.ps1`. The local W2
  merge is not pushed.
  - History JSON sha256: `564e6d8b656893fa622ef273ce307800da68c06541e0224ddff33ee64fa87861`.
  - Stage-C JSON sha256: `0975d2996baf48a1fa7923766d344108f0412b2f64bf36dd1fc02759f70e29d4`.
  - Both are in `C:\t\l11\db_hist` and `C:\t\l11\db_c`, and are not committed.

## Controls

- Served vs market R: 1.7739 (all hours) and 1.5263 (00-16). PASS.
- Floor-only 13-16 PRIMARY5: R 0.9776. PASS.
- L8 running max: `observed_running_max.py` is byte-identical to L8 `f3b49fabb`, where L8's 69 tests pass.
  - Those tests import L8's `model_base` change, which is not on this branch. They therefore run at
    `f3b49fabb`, not on this branch.
  - **Deviation from the rule's "must pass on this branch"** (section (a)). The coordinator accepted it on
    2026-10-25, together with the rule-r2 join (the clarification alone fails prereg_check).

## 1. Exclusion (history, Aug-Sep 2021-2025, fixed before any dev row)

- Kept days: 298-305 per market.
- Day-level violation rate at 16:59 (WU max < H): **0.00% in 10 markets**. Houston is 0.33% (1 day: 2022-09-23,
  H 97 against WU 96, cause `non_routine_max`).
- Every market is below X = 2.0%, so the **excluded set is empty**.

## 2. Dev dead buckets that settled YES

- There were 3,106 dev dead buckets, defined as an lte/eq bucket dead by 16:59 local under the METAR-only H.
  They span 11 markets and 08-01..09-29.
- **None settled YES**, so there are no causes to classify.

## 3. Gross upper bound ($/day, summed over 11 markets, date-clustered 95% CI)

Outcomes for the 3,106 dead buckets:

| Outcome | Count |
| --- | --- |
| No value at entry (NO price q = 1 − p + 0.01 leaves value < 0.005; the market already priced it dead) | 2,934 |
| No layout snapshot in 13:00-16:59 after entry | 89 |
| Traded | 83 |

Of the 83 trades, 61 are Denver. The median mispricing duration is 15 minutes (mean 25, p90 60), measured
from about-8-minute layout snapshots.

| Window | $25 | $5 | $100 | $25 expected-loss | $25 PRIMARY5 |
| --- | --- | --- | --- | --- | --- |
| 08-01..09-29 (57 dates) | **18.35 [7.74, 34.73]** | 3.67 | 73.40 | 18.34 | 16.44 |
| 08-10..09-29 (48 dates) | 21.72 [9.43, 42.01] | 4.34 | 86.87 | 21.71 | 19.46 |

- MDE80 is $20.8/day ($25, 57 dates).
- By entry hour, $25 earns $1.51 at 13, $3.63 at 14, $3.18 at 15 and $10.03 at 16 (per day).

**Reading (pre-registered):** NOT EXCLUDED BY THE UPPER BOUND; A decides. The $25 upper CI is above 0 and the
$100 point is at least $1/day.

**Concentration (descriptive, not pre-registered):**
- Denver is 89% of the gross. Every other market is under $1/day.
- The largest single trade is 41% of the gross: Denver 2026-08-21, eq 98-99 priced YES 0.955 at 16:10, 12
  minutes after the 15:58 METAR put H at 100 or above.
- The top 5 trades are 58% of the gross.
- Without the largest trade the bound is about $10.8/day.

These are short latency races. The bucket stays mispriced for about 10-15 minutes after the assumed 10-minute
METAR availability. Whether the book holds size at those prices, and whether prints occur, is the stage-A
question.
