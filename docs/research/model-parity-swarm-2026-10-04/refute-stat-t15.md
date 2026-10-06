# R-STAT-T15: statistics refutation of T15 (t15-r2, 17-23), development

**Verdict: the LEAD is NOT DISQUALIFIED on statistical grounds.** t15-r2 in 17-23 holds up under an
independent recomputation, and no single market, week or date carries it. The defects found below are
documentation problems, plus a multiplicity margin that will shrink as the registry grows. None of them
disqualifies the lead. This lens does not cover PIT or leakage; the PIT refuter covers those. Every number
here is development: the from stratum was read before (rule 7).

Independent code: `C:\swarm\out\refute-stat-t15\r_stat_t15_indep.py`. It re-implements the r2 projection,
the discretised Normal, the floor mask and the renormalisation, and computes cell means and W intervals
straight from `C:\swarm\cache` (`W.npy`, W_keys). It does not import the t15 code or `harness.score`.
Output is in `indep.log` and `indep.json` in the same folder. Run at 00:52 local, HARNESS cache unchanged.

## 1. Independent reproduction (from stratum, all rows, served fallback)

| block | cand - served [95%] | before | mkts neg | LEAD conditions |
|---|---|---|---|---|
| **17-23** | **-0.022116 [-0.034265, -0.012507]** | -0.027071 | 11/11 | all hold |
| 00-05 | -0.009444 [-0.016784, -0.003380] | -0.006304 | 10 | hold (but see section 6) |
| 06-09 | -0.008518 [-0.017298, -0.000990] | -0.005308 | 9 | hold (but see section 6) |
| 10-12 | -0.002713 [-0.009021, +0.003716] | -0.002090 | 6 | WEAK |
| 13-16 | +0.003975 [-0.003117, +0.009989] | +0.005896 | 3 | NULL |
| 00-16 (maker) | -0.004865 [-0.011162, +0.000633] | -0.002256 | 9 | WEAK |
| all | -0.009852 [-0.017193, -0.004206] | -0.009539 | 10 | hold |

In 17-23: gap closed 0.742. Candidate - market is +0.0077 [+0.00426, +0.01236], so parity is not reached.
The before-fit sigmas reproduce the hunter's (17-23: 0.269 F). Coverage is 0.9099. Every hunter number I
checked matches to 6 dp. The tail figure (0.79 of tail excess removed) was not recomputed; it is not a LEAD
condition.

## 2. One market, one week, one date? No.

- **Leave one market out:** every estimate stays between -0.0177 and -0.0241, and every interval excludes 0.
  Los Angeles carries the most, 27.2% of the summed delta. Without it the estimate is -0.0177
  [-0.0250, -0.0108], which still clears the -0.0133 line. The other shares: NYC 11.5%, SF 11.0%,
  Dallas 10.8%, and no other market above 10%.
- **Leave one ISO week out (weeks 34-40):** estimates run from -0.0208 to -0.0241, and every interval
  excludes 0. Per-week means are all negative, from -0.0139 to -0.0346.
- **Dates:** all **36/36** from-stratum dates have a negative mean delta.
- **Concentration:** the 10 most negative cells (out of 396) carry 16.3% of the sum. The median cell is
  -0.0042 and the 5%-trimmed mean is -0.0186. The effect is broad but skewed: most cells gain a little and
  decided days gain a lot. That is expected when probability collapses onto the running maximum.
- **Per hour, 17 to 23:** every hour is negative with an interval excluding 0. The effect grows with the
  hour, from h17 -0.0149 (8/11 markets) to h23 -0.0263 (11/11).

## 3. Is coverage selected on outcome? No. If anything, selection works against the candidate.

From stratum, 17-23: 17,711 rows covered and 2,484 not covered. Of the uncovered rows, 2,425 lack
forecast_high and 59 lack a floor. The uncovered rows have the larger served - market gap (+0.0346 vs
+0.0291 on covered rows). Before stratum: 887 rows not covered, gap +0.0258 vs +0.0337 on covered rows.
Missing forecast_high clusters in Denver (52% of rows) and Miami (34%), which is a feed or capture pattern,
not an outcome pattern.

Diagnostic, not a rule: setting P = running max on the rows that lack forecast_high raises coverage to
99.5% and gives -0.0257 [-0.0374, -0.0163] with 11/11 markets. Fallback therefore biases the estimate
toward 0. The matched-row estimand is not needed to rescue the lead.

## 4. Sensitivity: obs lag and the temperature source

Sigma is re-fitted on the before stratum in each row below, as the registered procedure prescribes. Frozen
sigma (0.269) and no-floor results are in `indep.log`.

| variant | sigma 17-23 | from est [95%] | before | mkts | LEAD |
|---|---|---|---|---|---|
| +10 min, tmpf (T-group) = rule | 0.269 | -0.0221 [-0.0343, -0.0125] | -0.0271 | 11 | yes |
| +10 min, tmpf rounded to integer | 0.263 | -0.0219 [-0.0342, -0.0122] | -0.0270 | 11 | yes |
| +10 min, METAR body whole °C to °F | 0.727 | -0.0119 [-0.0247, -0.0010] | -0.0177 | 9 | yes (gap bar) |
| **+70 min**, tmpf | 0.453 | -0.0192 [-0.0317, -0.0097] | -0.0235 | 9 | yes |
| **+130 min**, tmpf | 0.747 | -0.0131 [-0.0262, -0.0037] | -0.0159 | 9 | yes (gap bar; misses -0.0133 by 0.0002) |
| +70 min, body °C | 0.805 | -0.0092 [-0.0223, +0.0008] | -0.0146 | 8 | no (WEAK) |
| +130 min, body °C | 0.981 | -0.0054 [-0.0187, +0.0041] | -0.0099 | 8 | no (WEAK) |

What this shows:
- The lead survives a +1 h and a +2 h observation lag, and rounding tmpf to an integer.
- The body-°C variant fits settlement much worse than T-group tmpf (the before-fit sigma rises from 0.27 to
  0.73). The tenths carry real information for the settlement proxy. This is not a defect.
- Only the combination of whole-°C body values and a lag of 60 minutes or more breaks the LEAD.
- From the hunter's question: the sigma of 0.27 F is fragile. It roughly triples under a +2 h lag. The
  sign and the LEAD are not fragile.

## 5. Multiplicity (forking paths)

`C:\swarm\registry.jsonl` held **35 distinct rule ids** at 00:54. That count includes sensitivity and
control lines, and T15 contributes 4. The observed z of the 17-23 delta from W is -3.95; 0 of 2,000 draws
are >= 0.

Normal-approximation Bonferroni upper bounds:

| tests | upper bound | excludes 0? |
|---|---|---|
| 28 (T15 only: 4 rules x 7 groups) | -0.0046 | yes |
| 245 (35 rules x 7) | -0.0013 | yes |
| 420 (60 x 7) | -0.0006 | yes |
| 700 (100 x 7) | +0.0001 | no, borderline |

Bonferroni is conservative here: the 7 groups overlap and the rules are strongly correlated. Still, the
synthesizer must recompute this with the final registry count. **T1 and T15-r2 17-23 are one mechanism**
(collapse onto the running maximum) and must be counted as one family, not as two independent
confirmations.

## 6. Defects found (none disqualifying)

1. **Sigma is floored in code.** The code at `t15_diurnal_projection.py` line 166 does
   `sg = max(Sk[j], 0.5)`. The registered rule text ("sigma_block = RMS(...)") and the report ("sigma
   0.27 F puts nearly all mass on round(P)") do not mention the floor. The scored 17-23 candidate therefore
   uses sigma = 0.5, not 0.27. Without the floor the estimate is -0.0234 [-0.0358, -0.0136], 11/11, so the
   floor is conservative. The rule text and the report still need correcting before any draft
   pre-registration.
2. **The r2 LEADs in 00-05, 06-09 and all are not T15 evidence.** I reproduced them, but as the hunter
   states, the no-diurnal r4 control matches or beats them. That is the closed recalibration/sharpening
   thread. Only 17-23 should be carried forward.
3. **Partly in-sample.** The before-stratum estimate (-0.0271) is in-sample for the 5 sigmas. The
   both-strata-same-sign condition therefore rests partly on an in-sample number. This is allowed by the
   design. I did not independently verify that no undisclosed variant was scored before r1-r3 were
   registered (00:45:04). r4 was registered at 00:46:32, before its first score at 00:47:16.
4. **For the maker:** 00-16 is WEAK, -0.0049 [-0.0112, +0.0006], and is not attributable to the diurnal
   shape. The surviving effect lies in 17-23, where the market Brier is about 0.0008 and the gain is
   cosmetic for the maker.

## Summary for the synthesizer

- t15-r2 17-23 survives the statistics lens.
- It is robust to dropping any one market, week or date, to coverage selection, to a +1 h or +2 h obs lag,
  and to tmpf rounding.
- It is the T1 decided-band family, so count it once.
- Its multiplicity margin goes to borderline at about 100 registered rules.
- Fix the undocumented sigma floor of 0.5 in the rule text and the report.
