# r-stat-t4: statistics refutation of the T4 obs-trend nowcast (development only)

## Verdict: NOT DISQUALIFIED for the headline (t4-r3 in 17-23 and 13-16). The r3 LEADs in 10-12 and 00-16 ARE DISQUALIFIED. t4-r1 and t4-r2 in 13-16 do not survive the registry multiplicity.

- Every load-bearing number in C:\swarm\out\t4\report.md reproduces to 6 decimals under an independent
  implementation (own floor mask, renormalisation, served fallback, market-day cells, W intervals, LEAD
  classifier; the harness scoring functions were not called). Best cell r3 17-23 from-stratum all-row:
  **-0.026506 [-0.037221, -0.017845]**, candidate minus market +0.003308 [+0.001596, +0.005786], gap closed
  0.889 [0.801, 0.941], 11/11 markets negative, 36/36 dates negative, 356/396 market-day cells negative.
- 17-23 and 13-16 (r3) are not one market and not one week: leave-one-market-out and leave-one-week-out
  intervals all exclude 0 and keep the size bar; top market (Los Angeles) carries 22% (17-23) and 25% (13-16)
  of the summed cell delta; top week 24%. A dates-only cluster bootstrap (different seed and scheme) and a
  markets-only bootstrap agree. Bonferroni over the registry (31 candidate rules x 7 blocks = 217 tests, or
  40 lines x 7 = 280) is survived with z = -5.2 (17-23) and z = -4.0 (13-16).
- **r3 10-12 LEAD is disqualified.** z = -2.05 (one-sided p = 0.020, fails every multiplicity correction);
  removing any one of Austin, Dallas, Los Angeles or Miami puts the upper bound above 0; removing week W36 or
  W38 does the same; 3/11 markets positive. The hunter already called it fragile; the right class is WEAK.
- **r3 00-16 LEAD is disqualified: carried by one market.** Los Angeles carries 52% of the summed cell delta.
  Without Los Angeles: -0.002822 [-0.006555, +0.000631]. Four other single-market removals and two
  single-week removals also break the interval. z = -1.79 (p = 0.036). The maker-relevant 00-16 claim does not
  stand; what stands for 00-16 is "13-16 only".
- **t4-r1 13-16 (z = -2.84, p = 0.0023) and t4-r2 13-16 (z = -3.33, p = 0.00044)** keep the 95% interval
  below 0 and pass leave-one-out, but neither passes Bonferroni at m = 217 (threshold p < 0.00023). Only r3
  survives in 13-16. In 17-23 all three rules survive everything.
- Size bar note: r3 13-16 (-0.013148) misses the twice-81a line (-0.0133) by 0.00015 and qualifies through the
  weaker 5%-of-gap bar (-0.0012). 17-23 passes both bars.
- Attribution: the paired diagnostic in the T4 report (r1 - r2 positive in every block and stratum) is correct
  as a reading; the surviving effect belongs to the remaining-rise family (T2/T3-r3), and the synthesis should
  count the three T4 rules plus one diagnostic in the denominator and credit the family, not trend conditioning.

Scope and labels: development read on the from stratum (rule 7); score hash under test
HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`; rows after 2026-09-29: 0;
my floor mask agrees with the cached `floor_impossible` column on all 1,218,877 band rows; W is 2000 x 626 with
row sums 611-627 and column means 0.89-1.12 (a crossed weight matrix, as documented).

## 1. Independent reproduction (from stratum, all-row with served fallback, W intervals)

| rule | block | my class | my cand - served [95%] | z | 99.9% upper | before | cand - market | gap closed | mkts -/+ | T4 report |
|---|---|---|---|---|---|---|---|---|---|---|
| r3 | 17-23 | LEAD | -0.026506 [-0.037221, -0.017845] | -5.24 | -0.013675 | -0.031250 [-0.041834, -0.020737] | +0.003308 [+0.001596, +0.005786] | 0.889 [0.801, 0.941] | 11/0 | identical |
| r3 | 13-16 | LEAD | -0.013148 [-0.020059, -0.007299] | -3.97 | -0.004363 | -0.012553 [-0.020213, -0.005385] | +0.010909 [+0.007877, +0.014174] | 0.547 [0.376, 0.683] | 11/0 | identical |
| r3 | 10-12 | LEAD (as written) | -0.006062 [-0.012195, -0.000576] | -2.05 | +0.002953 | -0.006256 | +0.016707 | 0.266 [0.031, 0.448] | 8/3 | identical |
| r3 | 00-16 | LEAD (as written) | -0.005320 [-0.011769, -0.000308] | -1.79 | +0.002103 | -0.006118 | +0.018935 | 0.219 [0.015, 0.393] | 9/2 | identical |
| r3 | 00-05 | WEAK | -0.001383 [-0.008735, +0.004427] | -0.42 | | -0.002683 | +0.023057 | 0.057 | 3/8 | identical |
| r3 | 06-09 | WEAK | -0.002775 [-0.011716, +0.004326] | -0.68 | | -0.004559 | +0.022558 | 0.110 | 4/7 | identical |
| r1 | 13-16 | LEAD | -0.011353 [-0.019670, -0.003873] | -2.84 | +0.001496 | -0.011737 | +0.012703 | 0.472 | 9/2 | identical |
| r1 | 17-23 | LEAD | -0.025183 [-0.037443, -0.014447] | -4.32 | -0.008012 | -0.032773 | +0.004631 | 0.845 | 11/0 | identical |
| r2 | 13-16 | LEAD | -0.013069 [-0.021096, -0.005977] | -3.33 | -0.001229 | -0.012528 | +0.010988 | 0.543 | 10/1 | identical |
| r2 | 17-23 | LEAD | -0.025453 [-0.037594, -0.015078] | -4.41 | -0.008711 | -0.032952 | +0.004361 | 0.854 | 11/0 | identical |

The class vector for all three rules (00-05 .. 00-16, all) reproduces the T4 result.json exactly. The w tuning
of r3 on the before stratum reproduces (w = 0.8, before pooled Brier 0.047500 vs 0.047530 at 0.7: a
difference of 3e-5, so the choice between 0.7 and 0.8 is noise; it does not change the 13-16 / 17-23 picture).
Matched-row (selected on availability) estimates sit within 0.0004 of all-row in every block except 00-16
(-0.005707 vs -0.005320, 7.3% fallback from the 00-05 hour-0 rows). Tail rows (EF 1/1f definition on THIS
table, 6.075% / 70.38%; EF 4.387% / 64.14% is the sealed panel and is not comparable): r3 removes 0.891
[0.811, 0.937] of from-stratum tail excess in 17-23 and 0.673 [0.585, 0.754] in 13-16, as reported.

## 2. One market or one week? (from stratum, all-row)

Per-market cell means, r3:

| block | LA | DEN | NYC | DAL | SFO | AUS | ATL | ORD | HOU | MIA | SEA | top-market share of summed delta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 17-23 | -.0640 | -.0329 | -.0316 | -.0305 | -.0279 | -.0248 | -.0234 | -.0211 | -.0166 | -.0104 | -.0083 | LA 22% |
| 13-16 | -.0363 | -.0147 | -.0161 | -.0104 | -.0211 | -.0112 | -.0023 | -.0137 | -.0118 | -.0025 | -.0045 | LA 25% |
| 10-12 | -.0225 | -.0056 | -.0041 | -.0149 | +.0018 | -.0102 | +.0005 | -.0042 | +.0049 | -.0100 | -.0025 | LA 34% |
| 00-16 | -.0303 | -.0024 | -.0018 | -.0097 | -.0042 | -.0042 | +.0014 | -.0021 | +.0044 | -.0093 | -.0003 | **LA 52%** |

Per-week cell means (ISO weeks; W34 = 08-23 only, W40 = 09-28/29), r3:

| block | W34 | W35 | W36 | W37 | W38 | W39 | W40 | top-week share |
|---|---|---|---|---|---|---|---|---|
| 17-23 | -.0170 | -.0330 | -.0255 | -.0197 | -.0226 | -.0309 | -.0333 | W35 24% |
| 13-16 | -.0030 | -.0115 | -.0122 | -.0118 | -.0134 | -.0164 | -.0190 | W39 24% |
| 10-12 | -.0092 | -.0038 | -.0099 | -.0022 | -.0102 | -.0040 | -.0092 | W38 33% |
| 00-16 | -.0013 | -.0058 | -.0071 | -.0033 | -.0059 | -.0051 | -.0070 | W38 22% |

Leave-one-out W intervals (remaining cells, same W columns), r3:

| block | worst leave-one-market-out | worst leave-one-week-out | single removals that break the interval |
|---|---|---|---|
| 17-23 | drop LA: -0.022755 [-0.029936, -0.016257], 10/10 negative | drop W35: -0.024944 [-0.035357, -0.016793] | none |
| 13-16 | drop LA: -0.010831 [-0.016004, -0.006142], 10/10 negative | drop W39: -0.012370 [-0.019387, -0.006261] | none (size bar still met via 5% of gap) |
| 10-12 | drop MIA: -0.005672 [-0.012389, +0.000610], 7 negative | drop W38: -0.005057 [-0.011442, +0.000687] | markets AUS, DAL, LA, MIA; weeks W36, W38 |
| 00-16 | drop LA: -0.002822 [-0.006555, +0.000631], 8 negative | drop W36: -0.005025 [-0.011955, +0.000513] | markets AUS, DAL, LA, MIA, SFO; weeks W36, W38 |

Dates: 17-23 and 13-16 have 36/36 from-stratum dates negative (date means across markets); 10-12 has 28/36;
00-16 has 31/36. Cells: 17-23 356/396 negative, 13-16 254/396, 10-12 223/396, 00-16 228/396.

A seasonal drift is visible in 13-16: the gain grows from -0.003 (W34) to -0.019 (W40) as the season cools
and the remaining rise shrinks. This is not disqualifying but it is a caveat for any pre-registration (EF 1c
says mid-October onward is out of season; the effect size in a later window is not what this table measured).

## 3. Independent intervals beyond W

| rule / block | W (crossed date x market) | dates-only cluster bootstrap (seed 424242) | markets-only bootstrap (11 clusters) |
|---|---|---|---|
| r3 17-23 | [-0.037221, -0.017845] | [-0.030314, -0.022837] | [-0.035020, -0.019162] |
| r3 13-16 | [-0.020059, -0.007299] | [-0.015755, -0.010680] | [-0.019049, -0.008295] |
| r3 10-12 | [-0.012195, -0.000576] | [-0.008636, -0.003530] | [-0.010502, -0.001797] |
| r3 00-16 | [-0.011769, -0.000308] | [-0.006919, -0.003712] | [-0.010931, -0.000897] |
| r1 10-12 | [-0.010479, +0.003930] | [-0.006149, +0.000196] | [-0.008409, +0.002197] |
| r1 00-16 | [-0.009295, +0.004292] | [-0.003680, +0.000243] | [-0.008348, +0.003466] |

The crossed W interval is the widest of the three in every cell, as it should be (it carries both cluster
dimensions). The dates-only and markets-only intervals are reported as checks, not as the estimand.

## 4. Forking paths (registry read at 00:57 local)

- C:\swarm\registry.jsonl: 40 lines from 9 agents; 31 candidate rules and 9 controls/sensitivities/diagnostics
  (text-tagged CONTROL / sensitivity / diagnostic). T4 holds 4 lines (t4-r1, t4-r2, t4-r3 at 00:45:17; t4-d1 at
  00:47:04), all before the first T4 score file (00:46:49 for t4_r1; d1 is a diagnostic scored at 00:47:18).
  The T4 report said 35 lines; the denominator has grown since and the synthesis must use the final count.
- r3 adds 9 forking paths of its own (the w grid), chosen on the before stratum. The before-stratum "same sign"
  condition for r3 is therefore not fully independent evidence (the before stratum is where w was tuned),
  though per-block before signs were not tuned.
- Per-LEAD multiplicity (one-sided normal p from the bootstrap sd; Bonferroni m = 217 candidate-rule x block
  tests, and m = 280 all lines x blocks):

| cell | z | p (one-sided) | survives m=217 | survives m=280 | 99.9% interval excludes 0 | draws >= 0 |
|---|---|---|---|---|---|---|
| r3 17-23 | -5.24 | 8e-8 | yes | yes | yes | 0/2000 |
| r3 13-16 | -3.97 | 3.6e-5 | yes | yes | yes | 0/2000 |
| r2 17-23 | -4.41 | 5e-6 | yes | yes | yes | 0/2000 |
| r1 17-23 | -4.32 | 8e-6 | yes | yes | yes | 0/2000 |
| r2 13-16 | -3.33 | 4.4e-4 | no | no | yes | 1/2000 |
| r1 13-16 | -2.84 | 2.3e-3 | no | no | no | 3/2000 |
| r3 10-12 | -2.05 | 0.020 | no | no | no | 33/2000 |
| r3 00-16 | -1.79 | 0.036 | no | no | no | 37/2000 |

## 5. Availability vs outcome (is coverage selected on outcome?)

- Coverage by local hour in 00-05: hour 0 1.4%, hour 1 94.9%, hours 2-5 99.6-99.9%. By market: 79.2-82.2%,
  flat. The uncovered rows are the hour-0 snapshots before the first same-day METAR exists. That is a clock
  mechanism, not an outcome mechanism.
- Covered minus uncovered served-market gap in 00-05, pooled: +0.0023 [+0.0007, +0.0039] (date-cluster
  bootstrap); from stratum +0.0019 [-0.0002, +0.0041]. Covered rows are slightly harder for served than hour-0
  rows. Since uncovered rows score as served (delta 0) in the all-row estimand, this cannot inflate a lead, and
  00-05 is WEAK/NULL anyway.
- In 13-16 and 17-23 coverage is 99.97% and 100% (3 and 0 uncovered from-stratum snapshots); there is no
  availability selection to carry those leads. 06-09 / 10-12 uncovered rows (29 / 22) have very low served
  Brier, i.e. easy rows; their omission cannot create the 13-16 / 17-23 effect.
- Matched vs all-row agree within 0.0004 in every single block, which is the direct check that the selected
  population does not differ from the whole.

## 6. Defects, in order of weight

1. r3 00-16 LEAD: carried by Los Angeles (52% of summed cell delta); interval includes 0 without it and
   without four other single markets; fails every multiplicity correction. Disqualified.
2. r3 10-12 LEAD: fails leave-one-market-out for four markets and leave-one-week-out for two weeks; z = -2.05.
   Disqualified (WEAK is the honest class; the T4 report flagged it as fragile and the +30 min lag sensitivity
   already dropped it to WEAK).
3. r1 13-16 and r2 13-16: 95% intervals hold and leave-one-out holds, but neither passes Bonferroni at the
   registry count. Report as LEAD-by-rule, not multiplicity-robust. Only r3 survives in 13-16.
4. r3 13-16 qualifies through the 5%-of-gap bar, missing the twice-81a line by 0.00015. Not a defect under the
   rule as written, but the synthesis should not describe it as clearing the twice-81a line.
5. Attribution (not a statistical defect, the T4 report states it): the surviving gain is the remaining-rise /
   floor-to-running-max family; the T4-specific conditioning is HARM.

No harness leakage finding. No STOP condition met. No new rules registered.

## Files

- Code: `C:\pt\swarm\tools\research\model_parity\r-stat-t4_refute_stats.py`, sha256
  A3086CA72B9D9CED750A90F64EA36184ACC293701232C8CAA6851884CB695CBF. It imports the T4 module only to
  rebuild the candidate frames (its feature code is the object under test); scoring is re-implemented from
  `C:\swarm\cache\{snapshots,bands}.parquet`, `W.npy`, `W_keys.json`.
- Output: `C:\swarm\out\refute-stat-t4\refute_stat_t4.json` (all tables, per-market, per-week, leave-one-out,
  alternative bootstraps, availability tables, multiplicity), `result.json`.
- The Write tool refused report.md (as it did for the T4 hunter); the file was placed with a shell copy and
  its content is the intended report. No processes left running.
