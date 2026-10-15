# R-STAT-T18: statistics refutation of T18 (t18-r1), development only

## Verdict

**The LEAD classification survives. I found no disqualifying statistical defect (disqualified = false).**

**The "new information" framing is narrower than the hunter states.** The source part of the gain is captured NBM v2_mean. That is the known 79a/81a/111h "served under-uses its own captured v2 guidance" family (EF 10h/10j/10p). It is not a new source. Paired against R-T5-INC's zero-parameter v2-only control, t18-r1 adds nothing in 00-12. In 00-05 it is slightly worse. Its only increment over the v2-only route is the remaining-rise rung, in 13-16 and 17-23.

**Verdict by block** (from stratum, all-row primary, paired W intervals):

| block | r1 vs served | r1 vs t3-r3 rung (source increment) | stands? |
|---|---|---|---|
| 00-05 | LEAD -0.0123 [-0.0186, -0.0068] 11/11 | LEAD -0.0113 [-0.0153, -0.0069] 10/11 | stands |
| 06-09 | LEAD -0.0160 [-0.0231, -0.0092] 11/11 | LEAD -0.0138 [-0.0191, -0.0083] 10/11 | stands |
| 10-12 | LEAD -0.0129 [-0.0188, -0.0072] 11/11 | LEAD -0.0088 [-0.0127, -0.0048] 10/11 | stands |
| 13-16 | LEAD -0.0152 [-0.0219, -0.0096] 11/11 | LEAD by the classifier, -0.0036 [-0.0065, -0.0005] 9/11, but fragile | vs served stands. The increment over the rung does not survive multiplicity (Bonferroni p = 1.0), and its interval crosses 0 once Atlanta is dropped. |
| 17-23 | LEAD -0.0218 [-0.0325, -0.0132] 11/11 | NULL +0.0002 [-0.0014, +0.0021] 7/11 | vs served stands, but it is the rung / D-DEFECT family, not T18 information |
| **00-16** (claimed) | **LEAD -0.013953 [-0.0195, -0.0089] 11/11** | **LEAD -0.0096 [-0.0129, -0.0061] 10/11** | **stands** |

Two checks underpin these numbers:
- **Exact match to the harness.** My scoring (my own floor, renormalisation, served fallback, cell means and W intervals from C:\swarm\cache\W.npy) reproduces the harness r1 - served tables to about 1e-17 in every block.
- **Refit reproduces.** Refitting t18-r1 from the registered procedure reproduces the stored parameters: training NLL 1.409135, theta equal to 4 decimal places.

## What I checked, and what I found

### 1. Independent intervals and the LEAD conditions

These are recomputed from W, with every condition re-derived. In 00-16, r1 - served is -0.01395. The before stratum is -0.01429 [-0.0212, -0.0077], 11/11. The served - market gap is 0.0243, so the 5%-of-gap bar is -0.0012.

The size condition holds through both bars. The -0.0133 line passes only narrowly; the gap bar has wide headroom.

### 2. Increment over the t3-r3 rung (paired, same rows, same floor)

- **00-16:** -0.0096 [-0.0129, -0.0061], 10/11 markets, 36/36 from dates negative. z = -5.5.
- **Attribution:** c1 (rung x v2_mean only) minus the rung is -0.0091. r1 minus c1 is -0.0005 [-0.0013, +0.0004], which is WEAK, and only 6/11 markets are negative in the before stratum. So hrrr_high and forecast_high add nothing. The hunter's attribution is confirmed.
- **No-source control:** c0 minus the rung is NULL in 00-16 (+0.0003). It is HARM in 17-23 (+0.0004 [+0.0004, +0.0005], 0/11). This is minor, but it shows the fitted shift/scale alone slightly hurts the evening.

### 3. Increment over the already-known v2-only route

This compares t18-r1 with r-t5-inc-c1, both registered rules, as a diagnostic pairing. It is not a new rule.

| block | r1 - r-t5-inc-c1 (from) | before |
|---|---|---|
| 00-05 | +0.0019 [-0.0023, +0.0063] 3/11 | +0.0025 |
| 06-09 | -0.0021 [-0.0071, +0.0024] 6/11 | -0.0002 |
| 10-12 | -0.0038 [-0.0091, +0.0009] 10/11 | -0.0003 |
| 13-16 | -0.0147 [-0.0206, -0.0096] 11/11 | -0.0120 |
| 17-23 | -0.0299 [-0.0379, -0.0222] 11/11 | -0.0283 |
| 00-16 | -0.0039 [-0.0084, +0.0002] 9/11 (WEAK) | -0.0021 |

For scale, r-t5-inc-c1 vs served is -0.0100 [-0.0179, -0.0035] in 00-16 and +0.0082 in 17-23.

So t18-r1's 00-16 LEAD decomposes into two parts:
- the known v2 morning read, in 00-12;
- the remaining-rise rung, which is what helps in 13-16.

On this table the combination is not distinguishable from the zero-parameter v2 route in 00-16, and the fitted multiplication is not better than v2 alone before 10:00. The synthesis should cite T18 as "rung + known v2 family", not as a new source lead.

### 4. One market or one week?

**No.** The effect is not carried by one market or one week.

- **r1 vs served, 00-16:**
  - All 11 markets are negative. The strongest is LAX at -0.033, which is 22% of the sum.
  - Dropping LAX gives -0.0120 [-0.0160, -0.0076]. That still meets the gap bar but not the -0.0133 line.
  - The worst leave-one-week-out estimate is -0.0136.
  - Every week is negative, from -0.0098 to -0.0169. 35/36 from dates are negative.
- **r1 vs rung, 00-16:**
  - LAX is the only positive market, at +0.0002.
  - Dropping Chicago, the top market, gives -0.0089 [-0.0122, -0.0053].
  - Every week is negative.
- **r1 vs rung, 13-16:**
  - Dropping Atlanta gives -0.0027 [-0.0052, +0.0002], so the interval includes 0.
  - Week 7 is positive.
  - Fragile.

### 5. Forking paths

The registry holds 112 rules at my run time; T18 contributes 4. t18-r1 and t18-c0 were registered at 02:12:42, and the first score came at 02:14 per run.log. c1 and r1s were registered at 02:16:52, after the r1 read. They are disclosed as an attribution control and a sensitivity, not candidates.

I applied a Bonferroni correction over 112 rules x 7 blocks, using normal approximations from the W bootstrap SD:

| comparison | block | z | Bonferroni p |
|---|---|---|---|
| r1 vs served | 00-16 | -5.12 | 2.4e-4 |
| r1 vs served | 00-05 (weakest) | -4.10 | 0.03 |
| r1 vs rung | 00-16 | -5.53 | 2.6e-5 |
| r1 vs rung | 10-12 | -4.44 | 0.007 |
| r1 vs rung | 13-16 | -2.37 | 1.0 (does not survive) |

r1 vs served survives in every block.

### 6. Availability vs outcome

- **Fallback rows are not the easy rows.** Fallback rows (no PIT METAR running max, mostly hour 0) have a served - market gap similar to covered rows: 00-16 from 0.0227 vs 0.0244. The primary all-row estimand counts them as served, at delta 0. The matched estimate is -0.0151 [-0.0211, -0.0097], labelled "selected on availability".
- **v2_mean is available everywhere.** It is PIT-available at all 110,807 snapshots, so there is no v2 availability selection.
- **Missing hrrr_high hurts slightly.** hrrr_high is PIT-missing on only 0.2% of 00-16 rows. On those rows r1 is worse than c1 (+0.0026 from, +0.0040 before), because imputing a missing hrrr value as mu_rr interacts with the -0.27 forecast_high coefficient and the 0.33 hrrr coefficient. This is negligible in the aggregate, but it is another reason a served form should drop hrrr and forecast_high.

### 7. In-sample before stratum

The before-stratum "same sign" condition partly uses r1's own training rows.

As a diagnostic (not a rule), I refit the r1 form on 08-01..08-11 only. The parameters are stable: b_v2 1.08 vs 1.09, sigma 2.39 vs 2.25.

| refit on 08-01..08-11, scored on | vs rung | vs served |
|---|---|---|
| held-out 08-12..08-22, 00-16 | -0.0081 [-0.0125, -0.0028] | -0.0145 |
| from stratum, 00-16 | -0.0090 [-0.0122, -0.0056] | -0.0133 |

So the before-stratum sign holds out of sample.

### 8. Stated caveats

These are not defects:
- **Previously read dates.** The from stratum (08-23..09-29) was already read by 79a/81a/111h. It is a development read on previously inspected dates, not a holdout.
- **Small cluster count.** There are 11 market clusters (EF 10j power cap).
- **The 17-23 gain belongs to D-DEFECT.** It is the D-DEFECT serving-defect family (lock-in stages that do nothing), so T18 should not be credited with it.
- **Serveability is as the hunter states.** It needs a retrain, the v2 parser repair (83a/83b) to land, and a new prospective pre-registration (rule 7). No hour gate was used (rule 8).

## Files

| file | contents |
|---|---|
| C:\pt\swarm\tools\research\model_parity\r-stat-t18_refute.py | the refuter script |
| C:\swarm\out\refute-stat-t18\result_raw.json | all tables: every pair x block x stratum, LOMO/LOWO, per-week, availability, forking, fit-window diagnostic |
| C:\swarm\out\refute-stat-t18\run.log | run log |

HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74. Rows with target > 2026-09-29: 0. No new rules were registered, and every number here is development.

Note: writing report.md (and the docs copy refute-stat-t18.md) was blocked by a subagent tool guard. The orchestrator should write C:\swarm\out\refute-stat-t18\report.md and C:\pt\swarm\docs\research\model-parity-swarm-2026-10-04\refute-stat-t18.md from this text.
