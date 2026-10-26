# L11 rung R-M result: per-market centre bias at 07-12, gate 1 FAILS, lever KILLED (2026-10-25)

The rule is `rule_rm.md` in this directory (sha256 91e25610bf7c56193a040289e16ea21ed5aea53de2d20f7a4ed23033cb4a225b).
It was committed at 78fb338de before any R-M row existed. This is development evidence only, and nothing here is an edge
claim.

## Verdict

**Gate 1 (nested LOYO 2021-25, P3d_N_fix, shift against no shift) FAILS.**
- The shift is worse than no shift by +0.00013 Brier.
- 95% interval [-0.00027, +0.00055], so the upper bound is not below 0.
- 19,657 rows, 300 date clusters, 2,000 draws, seed 20261024.

**Pre-registered kill applies.**
- Per-market centre bias is **closed for every NBM-anchored arm**: P3d_N_fix, L6, the MG-1 family and the P3d_N
  family.
- No other grid, hour block, shrinkage, objective, market grouping or rolling window is to be run under any rung name.
- Gate 2 (dev) and gate 3 (against L6) were **not run**. `rung-m-score` refuses unless gate 1 passed.

This matches the stated prior. P3d_N_fix already carries a (market, season) bias, and MG-1's A1 debias was null.

## Per hour (shift minus no shift, Brier, date-clustered 95%)

| Hour | n | No-shift mean | Δ | 95% |
| --- | ---: | ---: | ---: | --- |
| h07 | 3,275 | 0.8675 | +0.00041 | [+0.00005, +0.00082] |
| h08 | 3,275 | 0.8640 | +0.00031 | [-0.00011, +0.00071] |
| h09 | 3,276 | 0.8598 | +0.00046 | [-0.00000, +0.00092] |
| h10 | 3,277 | 0.8557 | +0.00037 | [-0.00014, +0.00087] |
| h11 | 3,277 | 0.8428 | -0.00019 | [-0.00079, +0.00046] |
| h12 | 3,277 | 0.8207 | -0.00056 | [-0.00124, +0.00013] |
| **07-12** | 19,657 | 0.8518 | **+0.00013** | **[-0.00027, +0.00055]** |

## Per market (07-12)

| Market | n | Δ | 95% | s_m(Y) for Y = 2021..2025 |
| --- | ---: | ---: | --- | --- |
| atlanta | 1,788 | 0 | [0, 0] | 0, 0, 0, 0, 0 |
| austin (R-H three) | 1,788 | +0.00009 | [-0.00196, +0.00203] | +0.2, +0.3, +0.1, +0.2, +0.3 |
| chicago | 1,798 | 0 | [0, 0] | 0, 0, 0, 0, 0 |
| dallas (R-H three) | 1,788 | +0.00043 | [-0.00017, +0.00111] | 0, 0, 0, +0.1, -0.1 |
| denver | 1,758 | 0 | [0, 0] | 0, 0, 0, 0, 0 |
| houston | 1,788 | +0.00036 | [-0.00060, +0.00132] | 0, +0.2, 0, 0, +0.1 |
| los-angeles | 1,788 | -0.00218 | [-0.00511, +0.00052] | -0.4, -0.4, -0.2, -0.4, -0.4 |
| miami | 1,788 | **+0.00252** | **[+0.00092, +0.00421]** (harm) | 0, -0.2, +0.1, -0.2, -0.3 |
| nyc | 1,791 | +0.00051 | [-0.00079, +0.00181] | -0.1, -0.2, 0, -0.1, -0.2 |
| san-francisco | 1,788 | -0.00077 | [-0.00203, +0.00054] | -0.3, -0.3, -0.1, +0.2, +0.2 |
| seattle (R-H three) | 1,794 | +0.00050 | [-0.00055, +0.00175] | +0.1, +0.1, +0.2, +0.2, 0 |

These rows are descriptive only. Nothing is re-selected from them.
- The R-H three (Dallas, Austin and Seattle, the worst against the market on dev) gain nothing from a centre shift on
  2021-25.
- The fitted shifts are all within +/-0.4 °F, so the 2021-25 centre is already unbiased within a fraction of a degree.
- Their dev excess over the market is therefore not a centre bias that the training years can see.

## Controls

- **R-A positive control:** the unshifted, unmasked predictions reproduce R-A `loyo_rows.jsonl` (sha 21cacdaa…) on all
  19,657 rows. Max abs diff 0.0.
- **Training-score check:** no fitted s worsens its own inner Brier (55 of 55, all true).
- **LOYO mask effect (no-shift masked minus raw):**
  - Mean +0.00019.
  - Max abs 1.003, on the rows where the floor mask removes mass the raw pmf placed on the realised key. Both arms carry
    the same mask, so it cancels in Δ.
  - 4 rows have the actual outside the pmf keys. They are scored with the proper Brier term, as the rule requires.
- **NBM:** the training anchor comes from corpus 1ae4bf52…. The 07Z cycle was used on 45,870 rows, and 3 rows were
  imputed from forecast_high.

## Provenance

- Run: wrapper-queued (`workstation_heavy.ps1 -Queue`, OMP/MKL/OPENBLAS 10), checkout `C:\wt\l11pbrun`.
  - That checkout is L2's l2run eb7ff73bc plus this branch, merged locally and never pushed.
  - Module sha 4841e992fd608b2ce143a06c98feae065bd010c9fa9868c0f80f8ecccebb21d3.
- Inputs:
  - records `C:\t\l2\records`;
  - NBM corpus 1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd;
  - R-A rows 21cacdaa….
- Outputs:
  - `C:\t\l11pb\loyo\rm_loyo.json` (sha 0f6a73949f26bbc722f8683788ffb039c785375dbaeb501ad184f2a9e285390f);
  - `rm_loyo_rows.jsonl` (sha 6eee07649964dc0928b14c9624a8dbaa4607969da4225dceee47bd825e63d05a).
