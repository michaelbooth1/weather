# R-STAT-T10: statistics refutation of T10 (ECMWF IFS latest run). Development only.

**Verdict: DISQUALIFIED as a source lead. No claimed LEAD block stands as IFS information.**

- **17-23:** the effect against served reproduces exactly and is robust. It is the evening collapse family (D-DEFECT serving defect), not IFS. The IFS increment over the no-source control is null.
- **13-16:** the LEAD against served only just passes. It loses that status when any one of 6 of the 11 markets is dropped, and when any one of 4 of the 7 weeks is dropped. It is worse than the t3-r3 rung, and the r1 sibling rule is WEAK.
- **all:** this is LEAD only because 17-23 carries it.
- **r1 06-09:** the LEAD depends on the rule fork (r2 is WEAK), is just as fragile, and loses to the captured NBM v2_mean.

I agree with the hunter's recommendation to close "capture ECMWF IFS for T+0". All numbers are development reads on previously inspected dates (rule 7).

- HARNESS_SHA256 is 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.
- No row has a target date after 2026-09-29. No leakage tripwire fired.
- Code: C:\pt\swarm\tools\research\model_parity\r_stat_t10_refute.py.
- Output: C:\swarm\out\refute-stat-t10\result_stats.json.

## Method (independent)
- **Candidates:** I rebuilt all of T10's candidates (r1, r2, r3, c1, c2) with the hunter's own builder. I refitted the history parameters (07-25..07-31) and got identical values. I rebuilt t3-r3 with T3's builder. It matches refute-stat-t3\cand_r3.parquet exactly (1,157,057 band rows, max |diff| 0).
- **Intervals:** I computed every interval myself from C:\swarm\cache\W.npy. Each one is a ratio-of-sums bootstrap over market-day cells, written with my own code rather than h.interval. I implemented the LEAD conditions myself from DESIGN section 1.
- **Robustness checks:**
  - a date-only and a market-only cluster bootstrap (own RNG, seed 424242);
  - leave-one-market-out (LOMO) and leave-one-ISO-week-out (LOWO), each re-bootstrapped on W;
  - per-week means;
  - availability-versus-outcome association.
- **Reproduction:** every hunter headline matches to at least 4 decimal places.

## Per claimed LEAD block (from stratum, all rows, candidate - served)

| rule / block | estimate [W 95%] | before | markets negative | LOMO: drops that put the CI across 0 | LOWO: drops that put the CI across 0 | stands? |
|---|---|---|---|---|---|---|
| r2 17-23 | -0.0287 [-0.0403, -0.0193] | -0.0322 | 11/11 | 0/11 | 0/7 | Effect vs served: yes. As an IFS lead: no (see increments) |
| r2 13-16 | -0.0090 [-0.0191, -0.0005] | -0.0071 | 8/11 (exactly the bar) | 6/11 (chicago, denver, houston, LA, nyc, SF) | 4/7 (weeks 35, 36, 39, 40) | no |
| r2 all | -0.0132 [-0.0219, -0.0060] | -0.0138 | 11/11 | 0/11 | 0/7 | Carried by 17-23; no as a source lead |
| r1 06-09 | -0.0088 [-0.0176, -0.0005] | -0.0089 | 9/11 | 4/11 (austin, dallas, denver at 0.0000, LA) | 3/7 (36, 38, 40) | no |

- **Week pattern in 13-16:** the per-week means for weeks 34-40 are +0.0063, -0.0090, -0.0145, -0.0050, -0.0072, -0.0098 and -0.0213. The small partial weeks 34 and 40 have opposite signs.
- **Market concentration in 13-16:** los-angeles alone is -0.041, and dropping it moves the estimate to -0.0059 [-0.0142, +0.0017]. The effect is not one market, but it depends heavily on LA, and its interval is not robust to any single drop.
- **Alternative bootstraps:** the date-only and market-only intervals are narrower than the crossed W interval. W is the binding interval.

## Increments (paired, W intervals, from stratum; before stratum in parentheses)

| pair | 06-09 | 13-16 | 17-23 | 00-16 |
|---|---|---|---|---|
| r2 - t3-r3 | -0.0063 [-0.0124, +0.0004] 8/11 | +0.0026 [-0.0017, +0.0073] 4/11 (+0.0027) | -0.0068 [-0.0083, -0.0053] 11/11 | -0.0026 [-0.0066, +0.0022] |
| r1 - t3-r3 | -0.0067 [-0.0127, -0.0002] 8/11, 3/7 LOWO drops cross 0 | +0.0030 | -0.0069 | -0.0027 |
| r2 - c1 (no source) | -0.0128 | -0.0106 | -0.0003 [-0.0009, +0.0002] 9/11 (+0.0003) | -0.0114 |
| c1 - t3-r3 | +0.0065 | +0.0132 | -0.0065 [-0.0081, -0.0049] 11/11 | +0.0088 |
| r2 - c2 (captured v2_mean) | +0.0055 | -0.0085 [-0.0152, -0.0015] | -0.0369 | +0.0031 [-0.0025, +0.0091] 6/5 |
| r2 - r3 (undersampling) | -0.0010 | +0.0002 | -0.0003 | -0.0006 [-0.0013, -0.00002] |

### 17-23
The whole margin of r2 over t3-r3 (-0.0068) is the margin of the no-source control (-0.0065). The IFS increment is -0.0003, its interval includes 0, and its sign flips in the before stratum (+0.0003). It is null under every leave-one-week-out drop.

The mechanism shows in the fitted centres. The mean of the IFS centre minus the harness floor in 17-23 is -9.4 F (IQR -12.0 to -6.2), so H = max(B, X) puts almost all mass on the floor band. That is the decided-band / floor-collapse form. D-DEFECT has already traced it to the missing late-day lock-in stages (an owner decision on a serving fix), not to IFS.

The availability association points the same way. 17-23 rows that used the older run (above the median age of 13.9 h) gain more than rows with a younger run (-0.0332 against -0.0268). Fresher IFS information does not help, which fits a collapse that does not depend on information.

### 13-16
r2 is worse than the METAR remaining-rise rung t3-r3 (+0.0026, 4/11 negative, the same sign in both strata). It beats served and v2_mean only because both are worse rungs. As a source lead it fails the marginal test outright.

### 00-16 (the block that matters to the maker)
This block is WEAK against served (7/11 markets, the interval reaches +0.0001). IFS is worse than the captured NBM v2_mean: by +0.0031 overall, by +0.0067 [+0.0008, +0.0133] in 00-05, and by +0.0081 [+0.0006, +0.0169] in 10-12. It adds nothing over what production already captures. This agrees with R-T5-INC and the master-agent framing: the known 79a/81a/111h family.

## Forking paths
- **Registry:** 92 unique ids at 01:58 local, which is the swarm-wide denominator.
- **T10:** 6 ids (3 candidates, 2 controls and 1 diagnostic) plus 2 scored diagnostics.
- **Classifications:** 3 candidates x 7 groups = 21 classifications, and the blocks classed LEAD vary with the rule. r1 is LEAD in 06-09, 17-23 and all. r2 is LEAD in 13-16, 17-23 and all. r3 is LEAD in 13-16, 17-23 and all.
- **Rule fork:** r1 and r2 differ only by a per-block median bias. Under that small fork, the 06-09 and 13-16 LEADs swap between LEAD and WEAK. Both sit on interval upper bounds of about -0.0005, which no multiplicity allowance over 21 (or 92) tests would let through.
- **Hunter's choice of best rule:** naming r2 as best does not change any conclusion here.

## Availability against outcome
- **Coverage:** 99.34% overall. The lowest block is 00-05 at 97.9% (574 fallback snapshots). No date is below 95% coverage.
- **Fallback rows:** these have higher served Brier, for example 0.112 against 0.032 in 17-23 (n = 73) and 0.103 against 0.053 in 13-16 (n = 22). They are scored as served (delta 0) in the all-row estimand, so they cannot inflate the gain. Matched and all-row results differ by less than 0.0002.
- **Run-age split (median):** no block shows a selection pattern that would manufacture the effect.
- **c2 coverage:** identical to r2's because v2 was available on every covered row.

## Per-market and per-stratum signs
- **17-23:** 11/11 markets negative in the from stratum. The before stratum has the same sign.
- **13-16:** 8/11. Atlanta, austin and seattle are positive. The before stratum is negative.
- **06-09 (r1):** 9/11. Houston and SF are positive.
- **Strata:** every claimed block has the same sign in both strata against served. Against the relevant rungs, the IFS increment is null or adverse in both strata.

## Conclusion
Judged block by block:

| block | does it stand? |
|---|---|
| 17-23 | Yes as an effect against served, but not as IFS. It belongs to the evening collapse family that D-DEFECT already owns. |
| 13-16 | No. It is fragile to dropping one market or one week, and worse than t3-r3. |
| all | No. 17-23 carries it. |
| 06-09 (r1) | No. It depends on the rule fork, is fragile, and loses to v2_mean. |

T10 is disqualified as a source lead. "Capture ECMWF IFS for T+0" should be closed. Serveability class: needs new capture, and it is not recommended.

