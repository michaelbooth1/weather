# Section 5 power and futility inputs on dev (ledger row 82)

**Dated research evidence, 2026-10-30, lane L8. Descriptive only.** This read informs
[MODEL_IMPROVEMENT_METHOD](../../operations/MODEL_IMPROVEMENT_METHOD.md) §5 rules 6-7 and the checklist's
(f) power gate and (g) futility sections ([PREREGISTRATION_CHECKLIST](../../operations/PREREGISTRATION_CHECKLIST.md)).
It is not a rule. It adds nothing to the multiplicity denominator, and no number from it enters B, MG-1, L6_G,
R-ODC or any other bound or sealed design.

**Provenance:**
- Ledger row 82 was committed before any computation: `5ea9de8c207522a3f51a03bb98911bce42a5c95e`. That commit is
  also the run env (this branch's `src/`, recorded in the output).
- Driver: `C:\t\l8s5\s5.py`, sha256 `ded44abd82928308fe1a148e7318e5091f5913544825e3ad477ff6990ad9616e`.
  Output: `C:\t\l8s5\out\s5_out.json`, sha256 `b1a504bcf9e55bdd7de3f1a6e2481075c4078cab53203c7652276cd9e2f63f05`.
  The output also holds the per-date d.
- Sensitivity: `C:\t\l8s5\s5b.py`, sha256 `20e0757d670931d786deea21529577ca36cfc39c36802f35cb7019994e018358`, was
  added after `s5.py` and is disclosed as such. Output: `C:\t\l8s5\out\s5b_out.json`, sha256
  `52a34240f46d6e294b3c3788aad23496a84e44c8e4187a4d6361dd943a107d1b`.
- Population: the dev scorecard's default folds on `C:\swarm\v3layout` (manifest `4d53fdbd…5f22`, read only). Scored
  2026-08-15..09-29: 43 dates × 11 US markets = 473 market-days. Dates after 09-29 are refused in code.
- Controls ran first and both passed. The served positive control gave R 1.7739 for all hours and 1.5263 for 00-16
  (expected 1.774 and 1.526). The MG-1 07-12 excess over the market was 0.01196 (expected 0.012).
- MG-1 is `loss_atlas.mg1_frame` (rule r-t5-inc-c1) with the scorecard's floor mask and served fallback. Coverage:
  83,306 snapshots from MG-1 and 495 missing a floor.
- Loss: band Brier. d_t is the mean over a date's equal market cells of (arm A − arm B); negative means arm A is
  better. Lag-1 ρ is taken over the date-ordered scored sequence; 08-16, 09-01 and 09-02 are not scored. Moving-block
  bootstrap: 4,000 draws, seed 20261030. Simulation: 20,000 paths, final N = 45.

## 1. Measured inputs

SE b1 is the date-clustered SE. MDE80 uses the plan SE, which is max(SE b1, SE b3).

| Pair | n | mean d | σ_d | lag-1 ρ | SE at block 1 / 2 / 3 / 5 / 7 | VIF: block 3 / (1+ρ)/(1−ρ) / block 7 | MDE80 (block-3 plan) at N = 14 / 21 / 31 / 45 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1 candidate vs served: MG-1 − served, 00-16 | 43 | −0.01201 | 0.01101 | **+0.419** | 0.00163 / 0.00197 / 0.00216 / 0.00253 / 0.00286 | 1.74 / 2.44 / 3.07 | 0.0106 / 0.0087 / 0.0071 / 0.0059 |
| P1b MG-1 − served, 07-12 | 43 | −0.01386 | 0.01202 | **+0.373** | 0.00181 / 0.00210 / 0.00234 / 0.00265 / 0.00295 | 1.68 / 2.19 / 2.65 | 0.0115 / 0.0094 / 0.0077 / 0.0064 |
| P2 MG-1 − market, 07-12 | 43 | +0.01196 | 0.00946 | +0.080 | 0.00141 / 0.00151 / 0.00141 / 0.00130 / 0.00123 | 1.00 / 1.17 / 1.00 | 0.0069 / 0.0057 / 0.0047 / 0.0039 |
| P3 MG-1 − market, 13-16 | 43 | +0.02339 | 0.01263 | +0.279 | 0.00191 / 0.00219 / 0.00228 / 0.00243 / 0.00272 | 1.43 / 1.77 / 2.04 | 0.0112 / 0.0092 / 0.0075 / 0.0063 |

Market band Brier is 0.0534 at 07-12 and 0.0283 at 13-16; served is 0.0742 at 00-16. The iid SE agrees with the
block-1 bootstrap (P1: 0.00168 against 0.00163).

## 2. Rule B simulated (plan VIF from block 3, as registered in row 82)

Rule B:
- Look 7: stop for HARM if t > 3.143.
- Look 14: FUTILE if z > +0.5.
- Look 21: FUTILE if z > 0.
- Look 31: FUTILE if z > −0.5.
- Final PASS if z_45 < −1.96.

Here z_k = mean_k / (s_k × √VIF / √k). "Cum. stop" is the cumulative share of runs stopped by looks 7 / 14 / 21 / 31.
Power is the final PASS rate with futility looks, with the no-futility rate in brackets. The declared δ is:
- the pair's MDE80 at 45;
- the rule-6 value: half the dev point for P1; R ≈ 0.95, i.e. 0.05 × market Brier, for P2 and P3.

| Pair | Path model | Null: harm stop at 7 | Null: cum. stop | Null: final false PASS | δ = MDE80(45): cum. false stop by 31 | δ = MDE80(45): power | rule-6 δ: power | rule-6 δ: cum. false stop by 31 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 (δ 0.0059 / 0.0060) | AR(1), ρ 0.42 | 0.021 | 0.021 / 0.34 / 0.54 / 0.71 | **0.051** | 0.101 | 0.732 (0.748) | 0.750 (0.765) | 0.094 |
| P1 | AR(1), ρ 0 | 0.003 | 0.003 / 0.26 / 0.52 / 0.76 | 0.008 | 0.015 | 0.841 (0.842) | 0.851 (0.852) | 0.015 |
| P1 | empirical block 3 | 0.005 | 0.005 / 0.31 / 0.54 / 0.73 | 0.032 | 0.067 | 0.733 (0.742) | 0.752 (0.760) | 0.061 |
| P1b (δ 0.0064 / 0.0069) | AR(1), ρ 0.37 | 0.019 | 0.019 / 0.33 / 0.53 / 0.71 | 0.044 | 0.088 | 0.754 (0.767) | 0.810 (0.823) | 0.065 |
| P1b | AR(1), ρ 0 | 0.003 | 0.003 / 0.26 / 0.51 / 0.75 | 0.007 | 0.017 | 0.842 (0.844) | 0.900 (0.901) | 0.010 |
| P1b | empirical block 3 | 0.012 | 0.012 / 0.32 / 0.55 / 0.75 | 0.031 | 0.053 | 0.767 (0.775) | 0.836 (0.844) | 0.035 |
| P2 (δ 0.0039 / 0.0027) | AR(1), ρ 0.08 | 0.015 | 0.015 / 0.33 / 0.53 / 0.72 | 0.036 | 0.083 | 0.745 (0.759) | **0.471** (0.484) | 0.211 |
| P2 | AR(1), ρ 0 | 0.010 | 0.010 / 0.32 / 0.53 / 0.72 | 0.027 | 0.058 | 0.773 (0.782) | 0.473 (0.482) | 0.183 |
| P2 | empirical block 3 | 0.019 | 0.019 / 0.27 / 0.46 / 0.66 | 0.037 | 0.044 | 0.845 (0.857) | 0.570 (0.581) | 0.137 |
| P3 (δ 0.0063 / 0.0014) | AR(1), ρ 0.28 | 0.016 | 0.016 / 0.33 / 0.53 / 0.72 | 0.042 | 0.082 | 0.760 (0.774) | **0.119** (0.125) | 0.545 |
| P3 | AR(1), ρ 0 | 0.006 | 0.006 / 0.28 / 0.52 / 0.75 | 0.012 | 0.025 | 0.830 (0.833) | 0.063 (0.064) | 0.527 |
| P3 | empirical block 3 | 0.011 | 0.011 / 0.29 / 0.50 / 0.68 | 0.041 | 0.046 | 0.828 (0.836) | 0.132 (0.135) | 0.492 |

What the harm stop does when the true effect equals the dev point (MG-1 worse than the market):

| Pair | True harm | Stopped at look 7 | Stopped by look 14 |
| --- | --- | --- | --- |
| P2 | +0.0120 | 0.54 to 0.61 | 1.00 |
| P3 | +0.0234 | 0.82 to 0.84 | 1.00 |

### Sensitivity: plan VIF from the AR(1) long-run factor or from block 7 (`s5b.py`, disclosed)

| Pair | Plan VIF | Path model | Null: harm stop at 7 | Null: false PASS | Null: cum. stop by 31 | MDE80(45) | Power at it (no futility) | Cum. false stop by 31 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | (1+ρ)/(1−ρ) = 2.44 | AR(1) ρ 0.42 | 0.013 | 0.029 | 0.72 | 0.0072 | 0.802 (0.810) | 0.048 |
| P1 | 2.44 | empirical block 3 | 0.000 | 0.016 | 0.76 | 0.0072 | 0.812 (0.816) | 0.027 |
| P1 | block 7 = 3.07 | AR(1) ρ 0.42 | 0.008 | 0.018 | 0.74 | 0.0081 | 0.828 (0.830) | 0.029 |
| P1b | 2.19 | AR(1) ρ 0.37 | 0.013 | 0.026 | 0.73 | 0.0074 | 0.799 (0.807) | 0.049 |
| P1b | 2.19 | empirical block 3 | 0.006 | 0.017 | 0.76 | 0.0074 | 0.818 (0.821) | 0.024 |
| P2 | 1.17 | AR(1) ρ 0.08 | 0.009 | 0.030 | 0.72 | 0.0043 | 0.783 (0.792) | 0.058 |
| P2 | 1.17 | empirical block 3 | 0.016 | 0.026 | 0.67 | 0.0043 | 0.879 (0.887) | 0.026 |
| P3 | 1.77 | AR(1) ρ 0.28 | 0.011 | 0.028 | 0.72 | 0.0070 | 0.798 (0.806) | 0.053 |
| P3 | 1.77 | empirical block 3 | 0.007 | 0.027 | 0.70 | 0.0070 | 0.859 (0.864) | 0.028 |
| P3 | block 7 = 2.04 | AR(1) ρ 0.28 | 0.009 | 0.022 | 0.73 | 0.0075 | 0.814 (0.819) | 0.041 |

## 3. Readings

1. **The candidate-vs-served pair is serially correlated on dev.** P1 has ρ +0.42 at 00-16 and +0.37 at 07-12, against
   −0.06..+0.07 on every history pair in row 73. The block SE keeps growing out to block 7, with no plateau.
   - ρ has an SE of about 1/√43 ≈ 0.15, so +0.42 is about 2.7 SE from zero.
   - P2 (+0.08) is compatible with zero. P3 (+0.28) is borderline.
2. **A block-3 VIF under-corrects that dependence.** With the plan VIF from block 3 (1.74) and AR(1) paths at the
   measured ρ, Rule B's final false PASS is 5.1%, twice the nominal 2.5%, and the look-7 harm stop is 2.1%.
   - Planning with VIF = (1+ρ)/(1−ρ) restores both. False PASS is 1.6% to 3.0% across pairs and models; the look-7
     harm stop is at most 1.6%; power at the pair's own MDE80 is 0.80 to 0.88.
   - The (f) gate therefore takes VIF ≥ max(1, (1+ρ)/(1−ρ), (SE b3 / SE b1)²), and prereg_check enforces it.
3. **Under the null, Rule B stops 66% to 77% of runs by look 31.** Its harm stop at look 7 is 0.3% to 2.1%; it is
   above 1% only where ρ > 0.2 and the VIF comes from block 3.
4. **Futility costs little at the declared δ = MDE80.** Power drops by 0.2 to 1.6 points. Cumulative false stops are
   10% at most with the block-3 VIF, and 5.8% at most with the long-run VIF.
5. **The rule-6 δ against the market is underpowered at 45 dates.**
   - At 07-12, R ≈ 0.95 is a δ of 0.0027, and power is 0.47 to 0.57. That is at or below the 0.5 launch floor, and
     N80 is about 115 dates.
   - At 13-16 the market's Brier is only 0.028, so R ≈ 0.95 is a δ of 0.0014. Power is 0.06 to 0.13, and N80 is about
     1,100 dates.
   - No 45-date test can be powered on a 5% relative edge over the market at 13-16. This matches B's own §(d) limitation.
6. **MG-1 vs served at half the dev effect (0.0060) is a SCREEN at N = 45 under the long-run VIF.** Its MDE80 is
   0.0072, power is about 0.65 and N80 is about 65 dates. Under the block-3 VIF the same δ looks POWERED (MDE80
   0.0059). That reversal is why the VIF floor matters.
7. **The harm stop works where it should.** At MG-1's dev excess over the market it stops 54% to 61% of runs at look 7
   for 07-12, and 82% to 84% for 13-16. Every run is stopped by look 14.

Limits:
- Dev is one season (Aug-Sep), 43 dates. Oct-Dec dependence may differ; the history pairs showed none.
- The empirical paths resample this dev d, so they share its tails.
- None of this is an edge claim.
