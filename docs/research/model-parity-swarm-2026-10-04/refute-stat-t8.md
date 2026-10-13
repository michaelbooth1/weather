# R-STAT-T8: statistics refuter for T8 (HRRR latest run, Single-Runs) (development)

**Verdict: DISQUALIFIED as an HRRR source lead, in both claimed blocks.** The classifier LEAD labels reproduce
exactly under my independent W computation. Neither block's gain belongs to HRRR, so neither stands as a T8 lead.

- **17-23 (t8-r1 -0.0282):** the LEAD conditions hold, and the effect is robust. It is not carried by one market or
  one week. It does not stand as an HRRR lead, though: the no-source control c1 reproduces it (-0.0286), r1 - c1 is
  +0.0004 [-0.0001,+0.0010], and r2 - c1 is +0.0017 [+0.0007,+0.0029], meaning the calibrated HRRR rule is WORSE
  than having no source, with 1 of 11 markets better. HRRR adds zero to the evening collapse. This block belongs to
  the D-DEFECT serving-defect family, and that family owns it.
- **06-09 (t8-r2 -0.0079 LEAD; r3 and r4 also LEAD):** this is a marginal pass that does not survive refutation.
  - The interval's upper bound is -0.0002.
  - Dropping Los Angeles gives -0.0051 [-0.0116,+0.0012]. LA carries 42% of the summed delta, and LA plus Dallas
    carry about 72%. Dropping any one of Atlanta, Dallas, Denver or Seattle also loses interval exclusion. Dropping
    ISO week 36 or week 38 does the same.
  - The zero-parameter r1 is WEAK, and so is r2 at +2 h availability.
  - There is no increment over the t3-r3 rung: -0.0058 [-0.0117,+0.0008].
  - There is no increment over production's captured hrrr_high (c2): -0.0005 [-0.0058,+0.0039], with 3 of 11
    markets better.
- The hunter's summary numbers are all confirmed. HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.

## Method
- Script: C:\pt\swarm\tools\research\model_parity\r_stat_t8_refute.py. Output:
  C:\swarm\out\refute-stat-t8\result_stats.json. Log: C:\swarm\out\refute-stat-t8_run.log.
- The candidates were rebuilt with T8's own code; no new rules were registered.
  - The candidates are r1-r4, c1 and c2 at run + 3 h, and d1 (r1 and r2 at run + 5 h).
  - t3-r3 was rebuilt with T3's code and is byte-identical to R-STAT-T3's saved candidate (max |diff| = 0 over
    1,157,057 rows).
- The intervals are my own computation.
  - Snapshot Brier is computed from the cache, then market-day cell means.
  - The statistic is a ratio of sums over W.npy columns (2,000 crossed draws). It does not use h.interval or h.score.
  - The alternative intervals are date-only and market-only cluster bootstraps (own RNG).
  - I also ran leave-one-market-out and leave-one-ISO-week-out.
- The LEAD classifier is my own implementation of DESIGN section 1: interval excludes 0, size bar, both strata
  negative, and at least 8 of 11 markets negative.
- Rows with target date >= 2026-09-30: 0 (asserted). No leakage tripwire fired.

## Claimed LEAD blocks, candidate - served, from stratum, all rows (development)

| rule / block | estimate [W 95%] | mkts neg | before | date-only CI | market-only CI | class (mine) |
|---|---|---|---|---|---|---|
| r1 17-23 | -0.02819 [-0.03991,-0.01874] | 11 | -0.03197 | [-0.0322,-0.0244] | [-0.0375,-0.0203] | LEAD |
| r2 17-23 | -0.02689 [-0.03876,-0.01728] | 11 | -0.03008 | | | LEAD |
| c1 17-23 (no source) | -0.02859 [-0.04024,-0.01924] | 11 | -0.03269 | [-0.0325,-0.0246] | [-0.0382,-0.0205] | LEAD |
| d1-r1 17-23 (+2 h) | -0.02794 [-0.03978,-0.01855] | 11 | -0.03171 | | | LEAD |
| r1 06-09 | -0.00801 [-0.01684,+0.00030] | 8 | -0.00780 | | | WEAK |
| r2 06-09 | -0.00794 [-0.01624,-0.00022] | 9 | -0.00917 | [-0.0104,-0.0052] | [-0.0159,-0.0019] | LEAD (marginal) |
| r3 06-09 | -0.00791 [-0.01622,-0.00019] | 9 | -0.00916 | | | LEAD (marginal) |
| r4 06-09 | -0.00825 [-0.01657,-0.00064] | 9 | -0.00914 | | | LEAD (marginal) |
| c2 06-09 (captured hrrr_high) | -0.00739 [-0.01584,-0.00022] | 10 | -0.00935 | | | LEAD (marginal) |
| d1-r2 06-09 (+2 h) | -0.00762 [-0.01577,+0.00009] | 9 | -0.00848 | | | WEAK |

The from-stratum served - market gap is 0.0253 in 06-09 and 0.0298 in 17-23. The 5% bars are -0.0013 and -0.0015,
so both size conditions pass easily.

The before-stratum read is in-sample for r2, r3, r4 and c1, because their fit window (07-25..08-22) contains the
before stratum. For r1 and c2 it is out of sample.

## One market or one week?

**17-23, r1.** The effect is not carried by one market or week.
- Leaving out any single market gives an estimate between -0.0241 (without LA) and -0.0301, and every interval
  excludes 0.
- Leaving out any single week gives an estimate between -0.0269 and -0.0301, and every interval excludes 0.
- All 11 markets are negative, from Seattle at -0.0089 to LA at -0.0691. LA carries 22% of the sum.

c1 shows exactly the same robustness profile. This is the evening collapse, not HRRR.

**06-09, r2.** The effect is concentrated.
- Per-market deltas:
  - Los Angeles -0.0367
  - Dallas -0.0258
  - Atlanta -0.0088
  - Denver -0.0080
  - NYC -0.0057
  - Seattle -0.0036
  - San Francisco -0.0033
  - Miami -0.0032
  - Chicago -0.0003, effectively 0
  - Austin +0.0042
  - Houston +0.0039
- LA carries 42% of the summed delta, and LA plus Dallas carry about 72%.
- Leave one market out:

  | market dropped | estimate [W 95%] |
  |---|---|
  | Los Angeles | -0.0051 [-0.0116,+0.0012] |
  | Dallas | -0.0062 [-0.0150,+0.0011] |
  | Atlanta | -0.0079 [-0.0172,+0.0004] |
  | Denver | -0.0079 [-0.0168,+0.0003] |
  | Seattle | -0.0084 [-0.0173,+0.0002] |

  Dropping any one of these five markets loses interval exclusion.
- Leave one week out: without ISO week 36 the result is -0.0070 [-0.0159,+0.0008]; without week 38 it is
  -0.0073 [-0.0168,+0.0013]. Week 37's own mean is only -0.0022.
- The 9/11 market count includes Chicago at -0.0003, which is a sign on noise.

## Paired marginals, from stratum (W 95%, markets a<b / a>b; before stratum beside)

| pair | 00-16 | 06-09 | 13-16 | 17-23 |
|---|---|---|---|---|
| r1 - t3-r3 (rung) | -0.0017 [-0.0064,+0.0033] 7/4 | -0.0059 [-0.0121,+0.0005] 7/4 | +0.0044 [-0.0008,+0.0101] 3/8 | -0.0063 [-0.0080,-0.0045] 11/0 |
| r2 - t3-r3 | -0.0020 [-0.0063,+0.0028] 9/2; bef -0.0016 | -0.0058 [-0.0117,+0.0008] 8/3 | +0.0036 [-0.0012,+0.0086] 3/8 | -0.0050 [-0.0069,-0.0030] 10/1 |
| c1 - t3-r3 | +0.0093 [+0.0062,+0.0127] | +0.0078 | +0.0133 | -0.0067 [-0.0083,-0.0050] 11/0 |
| c2 - t3-r3 | +0.0003 [-0.0043,+0.0051] | -0.0053 [-0.0113,+0.0007] | +0.0120 | +0.0140 |
| r1 - c1 | -0.0110 [-0.0155,-0.0062] | -0.0137 | -0.0089 | **+0.0004 [-0.0001,+0.0010] 5/6** |
| r2 - c1 | -0.0113 | -0.0137 | -0.0097 | **+0.0017 [+0.0007,+0.0029] 1/10** |
| r2 - c2 | -0.0023 [-0.0074,+0.0018] 6/5 | **-0.0005 [-0.0058,+0.0039] 3/8** | -0.0085 [-0.0151,-0.0025] 9/2 | -0.0190 [-0.0279,-0.0113] 10/1 |
| d1-r2 - c2 (+2 h) | -0.0021 | -0.0002 [-0.0056,+0.0044] | -0.0081 | -0.0187 |
| r3 - r2 (precipitation) | -0.0002 [-0.0005,+0.0000] | +0.0000 | -0.0002 [-0.0006,+0.0003] | +0.0000 |
| r4 - r2 (cloud) | -0.0002 [-0.0005,+0.0001] | -0.0003 [-0.0007,+0.0001] | +0.0001 [-0.0005,+0.0005] | -0.0000 |
| r2 - r1 (calibration) | -0.0004 | +0.0001 [-0.0029,+0.0029] | -0.0009 | +0.0013 [+0.0006,+0.0020] 0/11 |

**HRRR over the remaining-rise rung (t3-r3).**
- 00-16: null.
- 06-09: null.
- 13-16: HRRR is worse than the rung, with 3 of 11 markets better.
- 17-23: negative, but the no-source control c1 beats the rung by more (-0.0067). The HRRR value therefore
  contributes nothing beyond the evening collapse.
- 00-05: r2 - t3-r3 is -0.0056 [-0.0104,-0.0002]. That block is not a claimed LEAD; it is WEAK against served. The
  captured hrrr_high c2 gives the same result (-0.0052), and r2 - c2 there is -0.0004 [-0.0053,+0.0036]. It is not
  a Single-Runs increment.

**Calibration.** In 17-23 the fitted bias makes the rule worse in all 11 markets (r2 - r1 +0.0013). It is not a
real gain.

## Forking paths (registry)

- C:\swarm\registry.jsonl holds 92 registered rules. T8 contributes 7, of which 4 are candidates (r1-r4) scored in
  every block.
- The sibling HRRR family T9 adds 7 more. The HRRR source family therefore offers at least 8 candidate rules across
  5 blocks.
- The 06-09 LEAD for r2, r3 and r4 is a near-duplicate (r3 - r2 ~ 0, r4 - r2 ~ 0): it is one effect counted three
  times.
- Its upper bound of -0.0002 would not survive any multiplicity adjustment. A Bonferroni adjustment over just the
  4 T8 candidates x 5 blocks would need a 99.75% interval. The 97.5% market-only interval is already near 0.
- The zero-parameter version (r1) does not pass. The pass appears only after fitting.

## Availability vs outcome

- **Coverage is 99.3%, so fallback selection cannot drive the result.**
  - 06-09: 39 fallback snapshots. 17-23: 73. 00-05: 574.
  - Fallback rows carry a higher served Brier (17-23: 0.112 vs 0.032), but there are too few of them to matter. They
    count as delta 0 in the all-row estimand.
  - No date has coverage below 95%.
- **Run age**, split at the median age.
  - 06-09: the r2 delta is -0.0089 with young runs and -0.0078 with old runs. c2 gives -0.0089 and -0.0072, the same
    pattern without any Single-Runs input.
  - By run hour, 12Z runs give -0.0124, 09Z -0.0085 and 06Z -0.0048. That fits fresher information, but c2 matches
    it.
  - 17-23: older runs do BETTER (-0.0326 against -0.0235). That is the signature of the collapse mechanism, where
    later hours have less remaining day, not of HRRR information.
- **+2 h availability (d1)**: 17-23 is unchanged (LEAD), and 06-09 becomes WEAK (upper bound +0.0001).

## Per-block judgement

| block | classifier | stands as an HRRR/T8 lead? | reason |
|---|---|---|---|
| 17-23 | LEAD (reproduced, robust) | **No** | No-source control c1 equals it (r1 - c1 +0.0004); calibrated HRRR is worse than c1. This is D-DEFECT's serving defect (lock-in S1-S7 no-op); report it under that family only. |
| 06-09 | LEAD (reproduced, marginal) | **No** | No increment over the rung (CI includes 0) or over the captured hrrr_high c2 (-0.0005). The interval exclusion is lost when any one of 5 markets or either of 2 weeks is dropped; LA plus Dallas carry about 72%. WEAK at +2 h and for the zero-parameter r1. |

disqualified = true. I found no harness defect and no leakage. The hunter's own attribution is correct. The
06-09 gain belongs to the known "served under-uses captured guidance" family (EF 10h/10j/10p). It is not
a reason to capture Single-Runs, and its LEAD label itself is fragile.

(report.md and the docs copy were blocked by the subagent tool guard; this text is the full report.)
