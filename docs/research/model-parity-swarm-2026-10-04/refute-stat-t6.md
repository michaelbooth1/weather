# R-STAT-T6: statistics refuter for T6 (NBS latest cycle). Development numbers only.

## Verdict

**As an NBS source lead, T6 is DISQUALIFIED, because the source contributes nothing.** The hunter's attribution
stands: the statistical LEAD conditions reproduce independently, but none of the gain comes from NBS.

- **The LEAD conditions reproduce under my independent computation.** I used my own floor mask, my own Brier and
  my own cell means, with intervals from W and from three of my own bootstraps. The effect is not carried by one
  market or one week.
- **The NBS-specific increment is zero.**
  - 17-23: r2 - c1 (no-source collapse) is -0.00000 [-0.00042, +0.00035]. The per-market differences are all
    below 0.0006 in size.
  - Morning: r2 - c2 (captured NBM v2 centre) is +0.00061 [-0.00049, +0.00218] in 00-05,
    +0.00022 [-0.00110, +0.00163] in 06-09 and +0.00027 [-0.00038, +0.00108] in 00-16.
  - 13-16: r2 equals c2 exactly.
- **What the LEAD is, by block.**
  - 17-23 is the unconditional evening collapse onto the floor band (D-DEFECT / T1-T3 family).
  - 00-09 is the captured NBM v2 Gaussian (81a/111h family, R-T5-INC c1).
  - A refutation of either number belongs to that family, not to NBS.
- **Capture.** NBS capture is not warranted.

Per block (from stratum, all-row):

| Block | Statistical LEAD reproduces? | Survives as an NBS lead? |
| --- | --- | --- |
| 00-05 | Yes for r2 and r3. r2 fails Bonferroni; r3 passes. | No: r2-c2 is +0.0006. |
| 06-09 | Yes for r2 and r3. r2 fails Bonferroni; r3 passes. | No: r2-c2 is +0.0002. |
| 10-12 | No. r2 and r3 are both WEAK; the intervals include 0. | n/a |
| 13-16 | r3 is a fragile LEAD: Bonferroni fails, and leaving out LA brings the upper bound to -0.0003. r2 is WEAK. | No: r3 - t3-r3 is +0.0019 [-0.0021, +0.0060], and r2 equals c2. |
| 17-23 (best) | Yes, strongly: -0.0287 [-0.0404, -0.0193], 11/11 markets, every robustness check passes. | No: r2-c1 is 0.0000; the gain is a collapse that uses no NBS values. |
| 00-16 | Yes. r2 fails Bonferroni and is 9/11; r3 is 11/11 and passes. | No: r2-c2 is +0.0003. |
| all | Yes. | No, for the two reasons above. |

## Method

Code: C:\pt\swarm\tools\research\model_parity\r-stat-t6_refute.py. Output: C:\swarm\out\refute-stat-t6\result_stats.json,
snap_scored.parquet and run.log.

- **Candidate probabilities.** I rebuilt them with the hunter's own builders:
  - t6_nbs_latest.build_candidate for r2, and for r3 with the fitted parameters TXN (-1.0, 1.007) and
    REM (+1.0, 1.386);
  - t6_nbs_controls.build_controls for c1 and c2;
  - t3_baselines.build for t3-r3.
  The PIT refuter owns the input re-derivation.
- **Scoring.** Everything after the probabilities is my own and does not use harness score():
  - floor mask: agreement with the harness flag is 1.0;
  - Brier per snapshot, with served fallback (all-row);
  - (date, market) cell means;
  - intervals from C:\swarm\cache\W.npy (2000x626);
  - my own crossed bootstrap (seed 777), a date-cluster bootstrap and a market-cluster bootstrap;
  - a normal Bonferroni interval over the 69 registry rules at run time (z = 3.38);
  - an 11-market t interval;
  - leave-one-market-out (LOMO), leave-one-week-out (LOWO), and the share of the delta carried by the top
    market and the top week.
- **Checks.** Rows with target > 09-29: 0. HARNESS_SHA256 is 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.

## Independent reproduction (from stratum, all-row, cand - served)

The columns are, in order:
1. Rule and block.
2. Estimate [W 95%].
3. The before-stratum estimate.
4. Markets negative.
5. The market-cluster bootstrap interval.
6. Whether the Bonferroni interval excludes 0.
7. The worst upper bound when one market is left out.
8. The worst upper bound when one week is left out.
9. The share of the summed delta carried by the top market and by the top week.

```
r2 00-05 -0.0136 [-0.0229,-0.0060] bef -0.0153 10/11  mc[-0.0209,-0.0075] Bonf FAIL  LOMO -0.0044(LA)  LOWO -0.0041(W36) 0.28/0.26
r2 06-09 -0.0109 [-0.0190,-0.0038] bef -0.0155  9     mc[-0.0169,-0.0055] Bonf FAIL  LOMO -0.0023(MIA) LOWO -0.0015(W36) 0.22/0.27
r2 10-12 -0.0015 [-0.0098,+0.0080] bef -0.0051  6     WEAK
r2 13-16 -0.0088 [-0.0193,+0.0005] bef -0.0076  9     WEAK (LOMO +0.0026, LOWO +0.0017)
r2 17-23 -0.0287 [-0.0404,-0.0193] bef -0.0327 11     mc[-0.0388,-0.0205] Bonf [-0.0474,-0.0101] ok  LOMO -0.0175(LA) LOWO -0.0182(W39) 0.22/0.23
r2 00-16 -0.0095 [-0.0164,-0.0032] bef -0.0114  9     mc[-0.0154,-0.0045] Bonf FAIL  LOMO -0.0017(LA)  LOWO -0.0012(W36) 0.30/0.25
r2 all   -0.0151 [-0.0228,-0.0086] bef -0.0177 11     Bonf ok  LOMO -0.0073 LOWO -0.0067 0.25/0.23
r3 00-05 -0.0131 [-0.0201,-0.0063] bef -0.0145 11     Bonf ok  LOMO -0.0048 LOWO -0.0047 0.21/0.22
r3 06-09 -0.0146 [-0.0219,-0.0073] bef -0.0159 11     Bonf ok  LOMO -0.0059 LOWO -0.0054 0.22/0.22
r3 10-12 -0.0066 [-0.0137,+0.0008] bef -0.0084  9     WEAK
r3 13-16 -0.0098 [-0.0188,-0.0020] bef -0.0080  9     mc[-0.0174,-0.0029] Bonf FAIL [-0.0248,+0.0053]  LOMO -0.0003(LA!)  LOWO -0.0005(W35) 0.38/0.23
r3 17-23 -0.0286 [-0.0402,-0.0193] bef -0.0324 11     Bonf ok  LOMO -0.0175 LOWO -0.0180 0.22/0.23
r3 00-16 -0.0115 [-0.0175,-0.0057] bef -0.0120 11     Bonf [-0.0219,-0.0010] ok  LOMO -0.0041 LOWO -0.0040 0.26/0.23
r3 all   -0.0164 [-0.0237,-0.0102] bef -0.0180 11     Bonf ok  LOMO -0.0089 LOWO -0.0086 0.24/0.23
```

- **Match with the hunter.** Every estimate and W interval matches the hunter's table to 4 dp.
- **The effect is not concentrated.**
  - Every week is negative in every claimed block. The exception is W34 in 13-16, which is positive: +0.014
    for r2 and +0.010 for r3.
  - No single market or week carries more than 30% of the summed delta, apart from r3 13-16 (38%, LA).
  - Per market in 17-23 (r2), all 11 are negative, from -0.069 (LA) to -0.009 (SEA).
  - Per market in 00-16 (r2), HOU (+0.0018) and SEA (+0.0027) are positive.
- **Time and multiplicity.** The date-cluster intervals are tighter than W, and the market-cluster intervals
  agree with W. The 11-market t interval excludes 0 in every claimed block except r2 13-16.

## Availability-vs-outcome association

- **Coverage (from stratum).**

  | Block | Coverage |
  | --- | --- |
  | 00-05 | 98.0% |
  | 06-09 | 99.8% |
  | 10-12 | 99.9% |
  | 13-16 | 99.9% |
  | 17-23 | 99.7% |

- **Gap on fallback rows versus covered rows.**
  - 00-05: 0.0175 on fallback rows versus 0.0246 on covered rows. The fallback rows are the easier ones, so
    this effect is minor.
  - 17-23: 0.109 on fallback rows versus 0.030 on covered rows. That is 59 snapshots, and keeping hard rows
    as served is conservative.

  Selection on availability does not inflate the estimate.
- **Cycle age.** The delta does not depend on cycle age. The terciles (median ages 0.9 / 1.3-1.5 / 1.7-2.0 h)
  give the same delta within 0.003 in every block. Examples:
  - 17-23: -0.0288 / -0.0284 / -0.0290;
  - 00-16: -0.0095 / -0.0091 / -0.0104.

  A real source-information effect would usually decay with age. A flat profile is consistent with the gain not
  coming from NBS values.

## Mode decomposition (from stratum, r2)

### 17-23

The snapshots split into REM 16,702, REM0 3,434 and absent 59.

| Rows replaced by the candidate | r2 - served | Before stratum | Markets negative | Share of the delta |
| --- | --- | --- | --- | --- |
| REM rows only (REM0 rows served) | -0.0234 [-0.0335, -0.0152] | -0.0263 | 11/11 | 82% |
| REM0 rows | — | — | — | 18% |

- **c1 versus r2.** c1 puts all mass on the floor band in every REM/REM0 row and equals r2. So the NBS
  remaining-hours maximum almost always sits at or below the floor bucket, and r2 in 17-23 is a disguised
  unconditional collapse.
- **c1 is not a no-information control.** No snapshot in 17-23 is in TXN mode. That makes c1 an unconditional
  collapse in that block: it is the D-DEFECT / T1 serving-stage effect, not information.

### 00-16

The snapshots split into TXN 25,033 and REM 24,648.

| Rows | r2 - served | Markets negative | Share of the delta |
| --- | --- | --- | --- |
| TXN rows | -0.0068 [-0.0111, -0.0029] | 10/11 | 71% |
| REM rows | -0.0028 [-0.0069, +0.0012] | 6/11 | 29% (null) |

On the TXN rows, the captured NBM v2 Gaussian (c2) gives the same result.

## Marginal value over the remaining-rise rung t3-r3

Paired, from stratum, all-row, W intervals:

```
            00-05                      06-09                      10-12    13-16                      17-23                       00-16
r2-t3r3  -0.0126[-0.0178,-0.0074]11  -0.0088[-0.0149,-0.0019]10  +0.0026  +0.0028[-0.0024,+0.0085]4  -0.0068[-0.0085,-0.0051]11  -0.0052[-0.0093,-0.0010]9
r3-t3r3  -0.0121                     -0.0125                     -0.0025  +0.0019[-0.0021,+0.0060]4  -0.0067[-0.0082,-0.0052]11  -0.0071[-0.0108,-0.0034]10
r2-c1    -0.0136                     -0.0422                     -0.0898  -0.0322                    -0.0000[-0.0004,+0.0004]6   -0.0386
r2-c2    +0.0006[-0.0005,+0.0022]    +0.0002[-0.0011,+0.0016]    +0.0000  0 (identical)              0 (identical)               +0.0003[-0.0004,+0.0011]
```

- **17-23.** The gain over the rung is real, but c1 reproduces it exactly, so none of it is NBS. In 00-16 the
  r2-c1 differences only show that a blind collapse is harmful, which is trivial.
- **00-09.** The gain over the rung is the guidance Gaussian. Captured NBM v2 delivers it equally, so NBS adds
  nothing over what production already captures.
- **13-16.** The NBS candidate is no better than the rung, so the afternoon falsifier held. r3's 13-16 LEAD is
  the remaining-hours form plus a fitted +1 F REM bias. It is also fragile under Bonferroni and
  leave-one-market-out.

## Forking paths (registry.jsonl, 69 rules at run time)

- **T6 registered 6 ids.**
  - r1, r2, r3 and d1 were registered at 01:12:20, before the first score at 01:13:36. I verified this from the
    timestamps of the files in out\t6\v1_bug_rem0.
  - c1 and c2 were registered at 01:25:53, after r2 and r3 were scored but before their own scores (01:31).
    They are post-hoc attribution controls, which is legitimate for attribution and is how I use them here.
- **The REM0 fix (01:17) changed r2 17-23 from +0.0021 to -0.0287.** It is consistent with the registered text
  "X = -inf (all mass on the floor band)", which was written before any score, and only the REM0 rows changed.
  So this is not an outcome-driven rule change.
- **The fix is still a selection event that favours the candidate.** It is moot for the verdict, because c1
  shows the 17-23 effect needs no NBS.
- **Multiplicity.**
  - Bonferroni over 69 rules: 17-23 survives, and so does all-hours for r2 and r3.
  - r3 survives in 00-05, 06-09 and 00-16.
  - The r2 morning blocks and r3 13-16 do not survive.

## Tail and serveability (not re-derived in full)

- **Tail.** The hunter's tail shares come from harness score(), on this table's 6.075% / 70.38% definition.
  EF's 4.387% / 64.14% belongs to a different panel and is shown beside it only. I did not re-derive the tail,
  and it is not load-bearing for this verdict.
- **Serveability.** As NBS, it would need new capture, and the zero increment means that capture is not worth it.
  - 17-23: a zero-parameter serving-stage collapse. That is the D-DEFECT fix shape, and it interacts with the
    81a floor mask, because the collapse target is the floor bucket.
  - 00-09: a zero-parameter guidance read on captured v2. It depends on the parser-v2 repair landing, and rule 8
    forbids an hour gate on this table.

## Disqualifying finding

**The source candidate fails the source-increment test in every claimed LEAD block.**

- r2-c1 in 17-23 is 0.0000.
- r2-c2 is +0.0003 in 00-16, and +0.0006 / +0.0002 in 00-05 / 06-09.

The hunter's own NULL attribution is confirmed independently. Nothing should be credited to NBS in the synthesis
or the parity ladder. The statistical LEAD conditions themselves are not refuted: no single market or week carries
them, there is no availability selection, and there is no PIT-age signature.

Note: the subagent tool guard blocked writing report.md, so this report is in result.json under report_md. The
docs copy refute-stat-t6.md was not written for the same reason.

