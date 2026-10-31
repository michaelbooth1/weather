# B-shaped pair: serial dependence and B's false-PASS rate on dev (ledger rows 83 and 84)

> **Row 84 correction.** Row 83's block-3 resampled rate (0.0692) came from a path-construction bug and is wrong.
> Corrected it is 0.043-0.045 (section 4). Row 83's other numbers stand. Its readings 1 and 4 are superseded by
> section 4, and the digest line at the end replaces row 83's.

**Dated research evidence, 2026-10-31, lane L8. Descriptive only.** This read follows master's ruling on row 82.

**B is unchanged.** B_FORWARD_TEST_DESIGN, `b_scorer`, `dev_scorecard`, `loss_atlas`, `mg2_*` and the MG-2
binding docs were read only. Nothing here alters B or any other bound or sealed design. No number here is an edge
claim.

**Provenance:**
- Ledger row 83 was committed before any computation: `1bbc459ea5df0c9f0f48ed2a70c85b143b37f58a`. That commit is
  also the run env (recorded in the output).
- Driver: `C:\t\l8br\br.py`, sha256 `b3461f7d2cf7aa8fd298c5424e8a21d8f3a6c38b03a17f1e6a1e02ce03d08694`. It ran
  directly as light work (9 s).
- Output: `C:\t\l8br\out\br_out.json`, sha256 `45de19586ebb8a3d209495b476da210f55faf7575671a61037710819e9503ab9`.
  It also holds the per-date d.
- Population: the dev scorecard's default folds on `C:\swarm\v3layout` (manifest `4d53fdbd…5f22`), scored
  2026-08-15..09-29, 43 dates. Dates after 09-29 are refused in code.
- Controls passed first: served R 1.7739 for all hours and 1.5263 for 00-16; MG-1 07-12 excess 0.01196.

**The pair** is MG-1 (`loss_atlas.mg1_frame`) minus the market, on B's estimand (B §3 and §5):
- local hours 07-16;
- B's 10 fixed markets (no Denver);
- only snapshots that both arms cover (32,372 snapshots, all MG-1 covered);
- per-snapshot band Brier, equal snapshot weights within a (date, market) cell, then equal cells;
- computed with `dev_scorecard.score_rows`.

Every date has all 10 cells, so the cell mean equals the mean of the daily d.

## 1. Measured

| Block | Δ (score_rows) | Date-clustered 95% | n | σ_d | lag-1 ρ | SE of ρ (asymptotic / block-5 bootstrap) | SE at block 1 / 2 / 3 / 5 / 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **07-16 (B primary)** | +0.01695 | [+0.0140, +0.0202] | 43 dates, 430 cells | 0.01048 | **+0.219** | 0.149 / 0.147 | 0.00157 / 0.00176 / 0.00173 / 0.00163 / 0.00175 |
| 07-12 | +0.01270 | [+0.0099, +0.0157] | 43, 430 | 0.01011 | +0.118 | 0.151 / 0.148 | 0.00154 / 0.00161 / 0.00153 / 0.00133 / 0.00126 |
| 13-16 | +0.02357 | [+0.0199, +0.0276] | 43, 430 | 0.01270 | +0.310 | 0.145 / 0.138 | 0.00192 / 0.00222 / 0.00235 / 0.00242 / 0.00265 |

- The iid SE at 07-16 is 0.00160.
- At 07-16 the block SEs rise to only about 1.1× the date-clustered SE and do not keep growing. That points to weak
  dependence, consistent with a ρ of +0.22 that is 1.5 SE from zero.
- At 13-16, ρ is +0.31 and the block SE keeps growing to 1.38× at block 7.

## 2. B's rule simulated at the null (N = 45, 20,000 paths)

**B's rule:** a fixed-market, date-clustered percentile 95% interval from `dev_scorecard.crossed_weights` over 45
dates, 2,000 draws, seed 20260921. That is the same weight matrix at every look, because the seed is fixed. PASS
when U < 0.

The rule is applied to Δ(07-16) only. B's extra condition (neither 07-12 nor 13-16 has its lower bound > 0) can only
lower the rate, so these figures are upper bounds on B's false-PASS rate.

| Path model | ρ used | False PASS | Monte Carlo SE | Times the nominal 0.025 |
| --- | --- | --- | --- | --- |
| AR(1), measured ρ | +0.219 | **0.0685** | 0.0018 | 2.7 |
| AR(1), ρ 0 (reference) | 0 | 0.0282 | 0.0012 | 1.1 |
| AR(1), ρ + 1.96 SE | +0.511 | 0.1423 | 0.0025 | 5.7 |
| Resampled dev dates, iid | none (dependence broken) | 0.0315 | 0.0012 | 1.3 |
| Resampled dev dates, block 3 (**wrong, see section 4**) | dev's own | ~~0.0692~~ | 0.0018 | ~~2.8~~ |

## 3. Readings

1. **B's interval assumes independent dates.** Under the dependence measured on dev, its false-PASS rate is about
   0.068 at the null, roughly 2.7 times the nominal 0.025. Two path models that share nothing but the dev d agree:
   AR(1) at the measured ρ gives 0.0685, and block-3 resampling gives 0.0692.
2. **Even with no dependence the rate is above nominal.** At ρ 0 it is 0.028, and 0.032 with iid resampling. That is
   the small-sample under-coverage of a 45-cluster percentile bootstrap.
3. **The point estimate of ρ is uncertain.** Its SE is about 0.15, so ρ = 0 is not excluded. The rate is 0.028 at ρ 0
   and 0.142 at ρ + 1.96 SE. Dev is one season (Aug-Sep), and B's dates are Oct-Dec.
4. **B's alternative is unaffected.** On dev, MG-1 is clearly worse than the market at 07-16 (+0.017). That is an
   MG-1 fact, not MG-2's alternative, and it does not bear on B's power.

## 4. Row 84: reconciling block-3 and simulating B's full PASS condition

Row 84 was committed before this computation (`0c66d740fd1c6b5ca2a5f21040cb5eb30c487235`).
- Driver: `C:\t\l8br\br84.py`, sha256 `7c6fb17c346847e1aa307f2368dd00a02abb31b29cb631f8cce5269e990be88c`. It reuses
  `br.py` (sha unchanged) for the population and controls. It ran directly as light work (15 s).
- Output: `C:\t\l8br\out\br84_out.json`, sha256 `d8bc293661f9bb4d1bae9585862d616aa30f0f25a1bf8042fb00a29729cb86cb`.
- Controls reproduced as in row 83, on the same 43 dev dates.

### 4.1 Reconcile: the SE table is right; row 83's block-3 paths were wrong

**How one null path was built (traced).**
- Each 45-date path is 15 blocks of 3 consecutive dev dates, with no trimming (45 = 15 × 3).
- Block starts are uniform on 0..40, which is the moving-block scheme. Blocks are re-drawn independently for every
  path. The traced path used 27 distinct dates.
- Values were d − mean(d) over the 43 dates.

**The bug is the centring.** A moving block underweights the series ends: the first and last date get 1/3 of a
middle date's weight, and the second and second-last get 2/3.
- Dev's last two dates are large and positive (centred d +0.0259 and +0.0064), and the first is negative.
- So the expected path mean under plain centring is −0.00031, which is −0.20 of the iid SE at N = 45, not 0.
- That shift pushes U below 0 too often.
- The spread of the paths was fine. Path SD is 1.08 × iid, matching the SE table (VIF about 1.17).

| 07-16, primary-only rule | False PASS | MC SE | Mean path Δ / its SD |
| --- | --- | --- | --- |
| Row 83 construction, rerun (plain centring) | 0.0672 | 0.0018 | −0.18 |
| **Moving block, re-centred on its own expectation (fix, post hoc)** | **0.0454** | 0.0015 | 0.00 |
| **Circular block (fix, post hoc)** | **0.0433** | 0.0014 | 0.00 |
| iid resampled | 0.0332 | 0.0013 | 0.01 |

The rerun reproduces row 83's 0.0692 within Monte Carlo error. The two fixes give 0.043-0.045, which is master's
prediction from the SE table (VIF ≤ 1.21 gives about 0.04, plus about 0.005 percentile liberality). Both fixes
are **post hoc**: row 84 named the cause and the fixes before computing, but they were chosen after row 83's number
was seen.

**Why AR(1) and block-3 still differ.** AR(1) at the point ρ of 0.219 implies VIF (1 + ρ)/(1 − ρ) ≈ 1.56 for the
mean. Dev's own moving-block SEs show at most about 1.21 out to block 7. The two models disagree on dependence beyond
lag 1, not on arithmetic. Dev cannot separate them: ρ has an SE of 0.15, and dev has 43 dates. So the honest range
at the null is 0.043-0.045 (dev's own short-lag dependence) to 0.065-0.069 (AR(1) at the point ρ).

### 4.2 B's full PASS condition at the null

B §6 PASS, quoted: "U < 0, and neither Δ(07-12) nor Δ(13-16) has its lower bound > 0". This is master's paraphrase.
`b_scorer.decide` applies it with one `w_date` matrix for all three ranges, and the simulation does the same.

The model is a joint three-range VAR(1):
- diagonal AR coefficients at the measured ρ: 07-16 +0.219, 07-12 +0.118, 13-16 +0.310;
- the measured SDs, 0.0105 / 0.0101 / 0.0127;
- the measured correlations of the daily d: 07-16 with 07-12 0.956, 07-16 with 13-16 0.927, 07-12 with 13-16 0.777.

Disclosure: at the measured ρ the implied innovation covariance had a minimum eigenvalue of −8.4e-08. It was
clipped to PSD, which is negligible against σ² ≈ 1e-4.

All rows below use N 45, 2,000 draws, seed 20260921 and 20,000 paths.

| Path model | Primary only | **Full B §6** | MC SE | Splits veto a primary PASS |
| --- | --- | --- | --- | --- |
| VAR(1), measured ρ | 0.0651 | **0.0651** | 0.0017 | 0 of 1,302 |
| VAR(1), ρ 0, same correlations | 0.0299 | **0.0299** | 0.0012 | 0 |
| Joint resample, iid | 0.0293 | **0.0293** | 0.0012 | 0 |
| Joint resample, block 3, re-centred (post hoc fix) | 0.0464 | **0.0464** | 0.0015 | 0 |
| Joint resample, block 3, circular (post hoc fix) | 0.0413 | **0.0413** | 0.0014 | 0 |

**The split veto never binds at the null.** Δ(07-16) is close to an average of the two splits (correlations 0.93 and
0.96), so a path whose 07-16 upper bound is below 0 never has a split lower bound above 0. Row 83's upper bounds are
therefore B's actual false-PASS rates. The VAR's 0.0651 against row 83's univariate 0.0685 is Monte Carlo noise
(different seed, about 1.4 combined SE).

### 4.3 Readings (replace row 83's readings 1 and 4)

1. B's false PASS at the null on dev's dependence is 0.041-0.046 from the data's own short-lag structure
   (block 3, fixed), and 0.065 under AR(1)/VAR(1) at the point ρ. Against the nominal 0.025 that is 1.7-2.6×.
   With independent dates it is 0.029-0.033.
2. B's full §6 condition gives the same rate as U < 0 alone. The split veto does not bind at the null.
3. ρ is uncertain (SE 0.15), and dev covers Aug-Sep while B runs Oct-Dec. Nothing here changes B.

**Digest line (row 84, replaces row 83's):** dev MG-1 − market on B's estimand (07-16, 10 markets, equal cells)
has daily lag-1 ρ +0.22 (SE 0.15). B's full §6 PASS rule (date-clustered percentile, 2,000 draws, N 45) then
false-PASSes 0.065 at the null under AR(1)/VAR(1) at that ρ, and 0.029-0.030 with independent dates, against a
nominal 0.025. The 07-12/13-16 veto never binds at the null (rows 83-84).
