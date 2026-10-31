# B-shaped pair: serial dependence and B's false-PASS rate on dev (ledger row 83)

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
| Resampled dev dates, block 3 | dev's own | **0.0692** | 0.0018 | 2.8 |

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

**Digest line (for master):** dev MG-1 − market on B's estimand (07-16, 10 markets, equal cells) has daily lag-1
ρ +0.22 (SE 0.15); at that ρ, B's date-clustered percentile rule (2,000 draws, PASS = U < 0, N = 45) false-PASSes
0.068 at the null (block-3 resampling 0.069; ρ 0 gives 0.028), against a nominal 0.025 (row 83).
