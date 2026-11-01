# Pre-registration template: (f) power gate and (g) futility (DRAFT)

Status: DRAFT by lane L8, 2026-10-30. Master owns the final location and wording. This draft changes no
sealed scorer design and no bound test. B_FORWARD_TEST_DESIGN.md, the B binding package, and the frozen
R-ODC and L6_G preregs are untouched. Nothing here applies to them retroactively.

Evidence: DEV_WINDOW_LEDGER row 73 (type D, descriptive, committed at `e42e01e2f` before any read).
- Script: `C:\t\l8pf\pf.py`, sha256 `3cc273fde31549e5cef0b3505f1a574ebaac0206f73abdd54fb42354c1cdcc54`.
- Output: `C:\t\l8pf\pf_out.json`, sha256 `3234287b6a93c438e06df3b0cb793ab29d9253bfa2fbdde529f8a7c1a89fe3c2`.
- Run env: `claude/loyo-screen-runenv-20261030` @ `a395031a0094cb22808c829a07bcd0f6c657b38d`, recorded
  in the output.
- Inputs: dates on or before 2026-09-29 only, checked in code. Seed 20261030; 4,000 bootstrap draws;
  20,000 simulation paths.

## Measured inputs

d is the paired daily loss difference (candidate minus incumbent; negative means the candidate is better).
It is the mean over a date's equal (market, hour) cells. Block length 3 days was fixed before reading. The
MDE80 is one-sided 2.5% (the "upper 95% bound < 0" rule) at 80% power:
MDE80(N) = 2.802 x SE_block3 x sqrt(n / N).

**History and dev blocks are never pooled.**

### History blocks: per-row loss files

| Pair (block) | n dates | mean d | sigma_d | lag-1 rho | SE block 1 / 3 / 7 | MDE80 N=14 / 21 / 31 / 45 |
| --- | --- | --- | --- | --- | --- | --- |
| R-ODC NEST − G1, row 69 WU (Oct-Dec 2021-25, 07-12), Brier | 375 | −0.00070 | 0.00462 | −0.05 | 0.00023 / 0.00024 / 0.00027 | 0.0035 / 0.0028 / 0.0023 / 0.0019 |
| R-ODC NEST − G1, row 70 METAR proxy, Brier | 375 | −0.00082 | 0.00472 | −0.04 | 0.00025 / 0.00024 / 0.00025 | 0.0035 / 0.0029 / 0.0024 / 0.0020 |
| HRRR R-K P3d_H − P3d_N_fix (Aug-Sep 2021-25 LOYO, 13-16), Brier | 300 | −0.0123 | 0.0259 | +0.01 | 0.0015 / 0.0015 / 0.0014 | 0.019 / 0.016 / 0.013 / 0.011 |
| the same, log loss | 300 | −0.044 | 0.080 | +0.00 | 0.0046 / 0.0046 / 0.0048 | 0.060 / 0.049 / 0.040 / 0.033 |
| HRRR R-R P3d_H − P3d_N_fix (Aug-Sep 2021-25 LOYO, 07-12), Brier | 300 | −0.0219 | 0.0246 | −0.06 | 0.0014 / 0.0013 / 0.0012 | 0.017 / 0.014 / 0.011 / 0.0095 |
| the same, log loss | 300 | −0.140 | 0.165 | +0.07 | 0.0096 / 0.0100 / 0.0105 | 0.130 / 0.106 / 0.087 / 0.072 |

Notes on the history blocks:
- The R-ODC files carry no log loss.
- 10 of 24,744 R-ODC cells have a blank nest or G1 value in both files; they are skipped.
- sigma_d varies by season. For R-ODC it ranges 0.0040 to 0.0054; for R-R Brier, 0.019 to 0.033 (2023 is the
  outlier). See `per_season_sigma` in the output.

### Dev blocks (2026-08-15..09-29, 43 dates): no per-date rows on disk

The scorers wrote only aggregate rows, so sigma is backed out of the recorded interval:
SE = width / 3.92, and sigma = SE x sqrt(43). **Lag-1 rho cannot be measured on dev.**

| Pair | Scale | Estimate | SE (n=43) | Implied sigma_d | MDE80 N=14 / 21 / 31 / 45 |
| --- | --- | --- | --- | --- | --- |
| HRRR R-K gate 3, P3d_H vs P3d_N_fix 13-16 | dR (ratio to market Brier) | −0.072 | 0.0130 | 0.085 | 0.064 / 0.052 / 0.043 / 0.036 |
| HRRR R-R gate 3, P3d_H vs P3d_N_fix 07-12 | dR | −0.060 | 0.0105 | 0.069 | 0.052 / 0.042 / 0.035 / 0.029 |
| L6_G vs L6 (`rn_score.json` gate 3), 07-12 | dR | −0.0093 | 0.0049 | 0.032 | 0.024 / 0.020 / 0.016 / 0.0135 |
| F4 `gefs_mean` − MG-1 (row 12), 00-12 | raw band Brier, crossed interval | +0.0054 | 0.0021 | 0.014 | 0.0105 / 0.0086 / 0.0070 / 0.0058 |

Notes on the dev blocks:
- **L6_G has no dev per-date rows.** The gates 2/3 scorer computes them in memory. The pair is kept only as
  this back-out, which reproduces the frozen prereg's own §8 figures (SE 0.00493, sigma about 0.0323).
- The R-ODC P1 parity rate has no loss pair. The killed GEFS spread modulator (row 71) is excluded.

### What the inputs show

1. **Daily d is close to serially uncorrelated** wherever it can be measured: rho is between −0.06 and +0.07
   on every history pair. Block-3 SE is within 0.86x to 1.11x of the iid SE (VIF from 0.86 to 1.11).
2. A 45-date look resolves only effects of roughly 2.8 x sigma_d / sqrt(45), which is about 0.42 sigma_d.
   On R-ODC that is 0.0019 Brier, against a measured history effect of −0.0007 to −0.0008. **A 45-date
   forward test of R-ODC is about 0.4 of its own MDE**, so even a true effect of that size is badly
   underpowered.
3. **Loss scales differ** between scorers: raw band Brier, dR ratio, and the crossed F4 Brier. An MDE must
   be stated on the scale of the test's own primary estimand.

## (f) Power gate (template section)

A pre-registration states, before D0:

1. **Estimand scale and sigma source.** State the scale (raw band Brier, or dR). State sigma_d from the
   newest block of the *same pair on the same scale*, labelled as history or dev, with its date range and
   file sha256. Never pool history and dev sigmas. If only a dev back-out exists, say so: rho is then
   unknown, and the gate uses VIF = max(1, measured history VIF of the nearest pair).
2. **Serial-dependence allowance.** State the lag-1 rho and the block-3 moving-block SE (block length fixed
   before reading). Use SE_block3 if it is larger than the iid SE.
3. **MDE80 at the planned N**: MDE80 = 2.802 x sigma_d x sqrt(VIF) / sqrt(N), one-sided 2.5%.
4. **Gate:**
   - **POWERED** if the pre-stated effect of interest is at least MDE80(N).
   - Otherwise a **SCREEN**. A screen's PASS earns only a powered confirmation on fresh dates, never a
     promotion. The pre-registration must state the N it would need: N80 = (2.802 x sigma_d x sqrt(VIF) / effect)².
   - The effect of interest must not be the dev point estimate alone, because that estimate is in-sample
     and optimistic. Use the dev point and half of it, and report the power at both.
5. **Misspecification guard.** If true rho is 0.3 but the plan assumes 0, the false-pass rate under the
   null rises from 2.5% to about 8% (simulated, AR(1)). So the final interval must use the scorer's
   date-clustered interval *and* report a block-3 interval alongside. If the two disagree on the verdict,
   the verdict is the more conservative one.

## (g) Futility (template section)

Looks are at 7, 14, 21 and 31 countable dates after D0; the final look is at N = 45. At each look,
z_k = mean_k / (s_k x sqrt(VIF) / sqrt(k)), with positive z meaning harm. The interim looks never declare
a PASS. The final test is unchanged by them.

| Look | Proposed stop rule (rule "B, t7") | Purpose |
| --- | --- | --- |
| 7 | z_7 > 3.143 (t, 6 df, one-sided 1%) | gross-harm stop |
| 14 | z_14 > +0.5 | futility |
| 21 | z_21 > 0 | futility |
| 31 | z_31 > −0.5 | futility |

Simulated operating characteristics: 20,000 paths, final N = 45, design effect = the MDE80 at 45. Cumulative
stop rates are given at looks 7 / 14 / 21 / 31. Rule A is z > 0 at all of 14, 21 and 31.

| Rule (look-7 bound) | Path model | Null: cumulative stop | Null: final false pass | True MDE: cumulative false stop | True MDE: final pass (no-futility pass) |
| --- | --- | --- | --- | --- | --- |
| A (z 2.326) | AR(1), rho 0 | 0.029 / 0.49 / 0.59 / 0.66 | 0.028 | 0.002 / 0.058 / 0.067 / 0.068 | 0.780 (0.803) |
| B (z 2.326) | AR(1), rho 0 | 0.029 / 0.31 / 0.53 / 0.72 | 0.029 | 0.002 / 0.021 / 0.039 / 0.056 | 0.793 (0.803) |
| A, t7 (t 3.143) | AR(1), rho 0 | 0.010 / 0.49 / 0.59 / 0.66 | 0.028 | 0.001 / 0.057 / 0.066 / 0.068 | 0.780 (0.803) |
| B (z 2.326) | R-ODC row 69 empirical blocks | 0.039 / 0.34 / 0.56 / 0.75 | 0.026 | 0.002 / 0.023 / 0.044 / 0.067 | 0.756 (0.766) |
| B (z 2.326) | HRRR R-K empirical blocks | 0.026 / 0.34 / 0.57 / 0.77 | 0.020 | 0.002 / 0.027 / 0.050 / 0.074 | 0.734 (0.743) |
| B (z 2.326) | HRRR R-R empirical blocks | 0.024 / 0.35 / 0.58 / 0.76 | 0.024 | 0.001 / 0.017 / 0.036 / 0.062 | 0.766 (0.773) |
| B (z 2.326) | true rho 0.3, plan 0 | 0.073 / 0.37 / 0.54 / 0.70 | 0.075 | 0.012 / 0.068 / 0.105 / 0.140 | 0.702 (0.732) |

Readings:
- **Look 7 with a normal bound stops about 3% of nulls, not 1%.** At k = 7, s_k is noisy and z has t-like
  tails. Using the t bound 3.143 brings the null harm-stop to about 1% (0.6% to 1.6% across path models),
  and the false-stop rate at a true MDE effect to 0.1% or less.
- **Rule B is preferred.** It stops 72% to 77% of null runs by look 31, against 66% to 70% for rule A. It
  falsely stops 5.6% to 7.4% of true-MDE runs, against 6.8% to 9.0%. It costs 0.7 to 1.0 points of final
  power, against 1.7 to 2.4.
- Futility stops cannot raise the final false-pass rate. They only lower power, and that loss is the
  false-stop rate among runs that would have passed.
- The empirical-block final power at a nominal MDE is 0.74 to 0.77, not 0.80. The history daily d has
  heavier tails than a Gaussian. A template that wants a true 80% should inflate the MDE by about 4% to 7%,
  or state the empirical power.
- **If rho is misspecified**, every rate degrades: a 7.5% false pass and a 14% false stop. This is why
  (f)5 requires the block-3 interval alongside.

Template wording for (g):

> Futility looks at 7, 14, 21 and 31 countable dates after D0. Stop for gross harm at look 7 if
> mean_7 / SE_7 > 3.143. Stop for futility at look 14 if z > +0.5, at 21 if z > 0, and at 31 if z > −0.5.
> SE_k uses the pre-stated VIF. A stop is recorded as FUTILE (or HARM at look 7) and is final for this
> pre-registration. No interim look can produce a PASS, change N, change the estimand or start a refit. The
> interim reads use only countable dates on or before the look date, and the ledger row for each look is
> committed before it is read.
