# MG-3 freeze prep (1a-i): frozen P3d_H states, 07-12 and 13-16 (rule, written before the fit)

Written 2026-10-26 by lane L2, **before any freeze fit**, on master's instruction relayed by the coordinator ("MG-3
FREEZE PREP … a sha-bound frozen P3d_H state fitted on 2021-25 … each needs its own rule and ledger row pushed BEFORE
its fit"). It follows L3's frozen-L6 pattern: rule `03b2eacd…`, then DEV_WINDOW_LEDGER row 36, then the fit.

- **Evidence class:** a freeze and an identity control. Nothing is scored. No outcome, label, price or market row is
  read: 2021-25 training labels only, plus 2026 inputs (≤ 2026-09-29) for the control.
- **Binds nothing.** MG-3 binds only under its own forward rule (draft `mg3_design_DRAFT.md`). This rule fixes how the
  states are fitted, what they contain and how they are checked.

## 1. What is fitted (exactly the dev arms already scored)

Two states, one per block. Each is the P3d_H arm that the block's rung emitted on dev, refitted deterministically on the
same rows:

| Block | Rung (rule sha256) | Hours | HRRR point rule | Training HRRR corpus | Dev reference (identity control) |
| --- | --- | --- | --- | --- | --- |
| 07-12 | R-R `e3d92e1aa779957db90c9627f3ccdc9052d7f9f2d6f7ae50843ebadbd0f5bb22` | 7-12 | RN-1 (`e4869491…`): `rr_point_rule` on land `22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6`, KSFO index 3, every other station 4 | `C:\t\l13\hrrr_0712` (manifest `fef6c307…`), days ≤ 2025-12-31 (`_rr_train_day`) | `C:\t\l2\rungr\emit\dev_P3d_H.jsonl` `a2dc30e2b0790ad4cf4ed167c329c00a6c87d4245fb1d6a55d0f80ffdfc14f3d` |
| 13-16 | R-K `21b5dfe1870c03bcab143903b8fccc37a446c49de97b3889377039c7c8327221` + RK-1 `c825b277…` | 13-16 | nearest cell (R-K as fitted) | `C:\t\l13\hrrr` (manifest `409f6f91…`) | `C:\t\l2\rungk\emit\dev_P3d_H.jsonl` `e5195945cd8a24db178cd8b85e0af8914c95321b581a65897e8cac59eb451da1` |

**Arm.** `P3d_H` = `_rung_entry(train, simple=False, extra_hgb=("k_max", "k_gap", "k_tcdc"))`. That is P3d_N_fix (pooled
mean model: in-fold bias by (market, season), OLS on [1, g, max(g, 0)], HGB residual; HGB scale model on [X, floor gap];
standardised errors z) with the three HRRR columns appended to the HGB input. The model is fitted per local hour,
pooled over the 11 R0 markets.

**Training rows.** These are identical to the rung's dev emit:
- `dev_training_frame(C:\t\l2\records)`, Aug-Sep 2021-25;
- `attach_training_nbm` with the L9 corpus `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd`;
- the block's hours;
- `rk_training_columns` from the block's training HRRR.

No 2026 row is used. A training year ≥ 2026 refuses the fit.

**Code.** `weather.calibration.pooled_residual_model` at the commit recorded in the state's provenance, run through
`workstation_heavy.ps1`. Nothing about the arm, its inputs or its hyperparameters changes. A fit whose control fails
(§3) is not repaired by retuning; it stops.

## 2. What is frozen (schema `mg3_p3d_h_state/1`)

The state is one pickle (protocol 4) per block, with a JSON sidecar carrying its sha256 and provenance. It uses the key
layout of the MG-2 P3d_N state (`mg2_p3d_n_state/1`), so `state_features` / `mg_serve_core.state_features` read it
unchanged:
- `schema`, `arm` "P3d_H", `block`, `markets`, `centres` (the four Aug-Sep centres);
- `season_of`, `coords`, `buckets`;
- `constants`: floor mix 0.02, kernel bandwidth 0.25, min scale 0.5, clim alpha 0.10, level columns;
- `conversion`: **disabled**. The dev arms read raw `high_so_far` / `current_temp`, and no WU rounding is applied, as
  fitted.
- per hour: `mean` (`state_mean_dict`, plus `extra_hgb` and `extra_ols`), `scale` (the fitted HGB), `z`, `train_y`.

It also carries:
- `extra_hgb` = ["k_max", "k_gap", "k_tcdc"], appended to the state X row in this order (after the day-of-year
  columns, as `MeanModel.features` does);
- `point_rule`: the block's rule, with the land sha, chosen indices and the R-K nearest-cell flag;
- `provenance`:
  - commit, module sha256, this rule's sha256;
  - the training row count and years;
  - input shas (NBM corpus, HRRR manifest / selections / stations);
  - the training-NBM and HRRR-coverage stats;
  - package versions.

**Serve math (one definition).** For a row (market, target date, hour h, high_so_far F, current temp, NBM mean, k
columns):
- X = `state_features(…)` X row + [k_max, k_gap, k_tcdc];
- yhat = mu0 + [1, g, max(g, 0)]·ols + hgb(X);
- s = max(0.5, scale([X, yhat − F]) · √(π/2));
- the distribution is `predictive_distribution(yhat, s, F, z, buckets[market], p_clim)`, with p_clim =
  `smoothed_dist(train_y[market], buckets[market], 0.10)`.

**Loader.** The serve-side loader is L3's `mg_serve_core` (`claude/mg-serve-core-20261026`). L2 does not add a second
serve loader. The research-side control verifies the file sha256 before unpickling, as `load_l6_own_state` does. The
one extension `mg_serve_core` needs is to append `state["extra_hgb"]` values to its `state_features` X row; L2 hands
that to L3 rather than copying the loader.

## 3. Identity control (must hold before the state is reported as frozen)

1. **Export parity.** On up to 200 sampled training rows per hour, the state's serve math reproduces the in-process
   fitted mean model's X and yhat to 1e-9 (as `forward_fit`).
2. **Dev re-emit.**
   - The block's dev emit is re-run with the same layout (`C:\swarm\v3layout`), the same replay root, the same row hook
     (the block's 2026 HRRR, same point rule) and the same eligibility.
   - Every P3d_H distribution is computed **from the frozen state by the serve math above**, not from the in-process
     fit.
   - **PASS** if every (market, snapshot_id) row of the reference file is present with the same keys, and
     max |p_state − p_ref| ≤ **1e-12** over all bands, with no extra or missing rows.
   - Byte identity of the file sha is reported, not required: the JSON float repr may differ in the last digit.
3. **FAIL** of 1 or 2 stops the freeze for that block. The state is not used, and the failure is reported with the
   first differing row. No tolerance, input or code is changed to make it pass without a new ruling.

## 4. Outputs (outside the repository)

`C:\t\l2\mg3\state_{0712,1316}\`:
- `p3d_h_state.pkl` and `p3d_h_state.json` (sha256 and provenance);
- `export_parity.json`;
- `control\dev_P3d_H.jsonl`;
- `control.json`: per-block max |Δp|, row counts and pass.

Nothing is overwritten: an existing file refuses.

## 5. Limits

- Data ≤ 2026-09-29.
- No paid data, no new dependency, no change to MG-2, B, PT-1, MG-1, L3's or L8's branches.
- The states are research artifacts until MG-3's forward rule binds their sha256 in `release-binding.json`.
