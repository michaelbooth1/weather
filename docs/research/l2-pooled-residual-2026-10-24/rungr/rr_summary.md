# R-R summary: the HRRR hourly path as a 07-12 centre input

- **Evidence class:** development evidence only. No edge claim.
- **Rule:** L13's `C:\t\l13\rr\rule_rr.md`, sha256 `e3d92e1aa779957db90c9627f3ccdc9052d7f9f2d6f7ae50843ebadbd0f5bb22`,
  scored as registered.
- **Point rule:** RN-1 (`land_3x3.json`, sha256 `22069beb…d7fd6`), applied uniformly.
- **Data limits:** nothing dated after 2026-09-29 was read.
- **Code:** `pooled_residual_model.py`: `rung_r_loyo`, `rung_r_dev_emit` and `rung_r_score`; test `test_rr_point_rule.py`.

## Inputs (sha256 verified in code before reading)

| Input | sha256 |
| --- | --- |
| L13 `hrrr_0712/manifest.jsonl` | `fef6c307…88e6` |
| L13 `hrrr_0712/selections.jsonl` (26,424 rows) | `31bd3d3a…4f67` |
| L13 `hrrr_0712/days.jsonl` | `34af53b0…515e` |
| L13 `hrrr_0712/stations.json` | `52e8bb5f…0abe3` (equals the land file's `stations_json_sha256`) |
| R-A 07-12 LOYO rows (control) | `21cacdaa…7f54d` |

**RN-1 reading:**
- The chosen index was recomputed from (fi, fj) and the LAND block, ties going to the lower index.
- It equals `rn1_chosen_index` for all 11 R0 stations: KSFO 3, every other station 4.
- In every message, the stored `nearest` value equals `block3x3[4]`.
- No station lacks a land cell.

**Absent cycles:** the 2022-08-11 15Z and 2022-09-21 11Z rows have no cycle and enter as `k_miss` = 1, without
imputation. That is 11 training rows in the R0 markets; Toronto is not an R0 market.

## Gates (in the registered order)

| Gate | Result |
| --- | --- |
| 1a parity, training | PASS: coverage 19,646/19,657 (0.9994), with 11 `no_cycle`; zero identity, TMP-range, point-in-time, window or snapshot failures |
| Control: R-A 07-12 LOYO reproduction | PASS: same keys (19,657), max \|Δ\| 0 |
| 2 LOYO, B_H − B_N, 07-12 | **PASS**: −0.0092 [−0.0112, −0.0073] |
| 1b parity, dev | PASS: coverage 28,755/28,755; zero failures |
| Controls: R-F inputs (B_N `83cf9bbe`, P3d_N_fix `cd0034b9`) byte-identical; MG-1 0.012; `mg1.predict` identity 0; L6 controls; R-F blend_l6 vs L6 reproduced (−0.00955) | all hold |
| 3 dev, P3d_H − P3d_N_fix dR, ALL, 07-12, 4-arm covered (21,664 snapshots) | **PASS**: −0.0598 [−0.0813, −0.0401] |
| 4 blend_l6_H vs L6 dR, ALL, covered, 07-12 | **WIN**: −0.0402 [−0.0603, −0.0198]; no hour's lower bound is above 0 |

### Gate 2 detail (LOYO 2021-25, Brier per row, date-clustered)

| Pair | 07-12 | 07-09 | 10-12 |
| --- | --- | --- | --- |
| B_H − B_N | −0.0092 [−0.0112, −0.0073] | −0.0094 [−0.0114, −0.0074] | −0.0090 [−0.0112, −0.0068] |
| P3d_H − P3d_N_fix | −0.0223 [−0.0248, −0.0198] | −0.0216 [−0.0242, −0.0192] | −0.0231 [−0.0260, −0.0201] |

Every single hour from h07 to h12 is negative with its interval excluding 0, for both pairs.

### Gate 4 per hour (blend_l6_H − L6 dR, date-clustered)

| Hour | dR |
| --- | --- |
| h07 | −0.0348 [−0.0546, −0.0152] |
| h08 | −0.0379 [−0.0584, −0.0162] |
| h09 | −0.0396 [−0.0636, −0.0151] |
| h10 | −0.0359 [−0.0603, −0.0120] |
| h11 | −0.0344 [−0.0612, −0.0083] |
| h12 | −0.0578 [−0.0880, −0.0278] |

The crossed 07-12 interval is [−0.0764, −0.0061].

## Reported only

- **P3d_H with L6 fallback against L6, 07-12:** −0.0208 [−0.0528, +0.0122].
- **blend_l6_H against R-F's blend_l6 (the HRRR increment inside the blend):** −0.0307 [−0.0451, −0.0167].
- **Walk-forward w per hour (mean, first, last):**

  | Hour | blend_l6_H | blend_l6 (R-F) |
  | --- | --- | --- |
  | h07 | .54 / .59 / .57 | .35 / .27 / .38 |
  | h08 | .54 / .53 / .56 | .33 / .26 / .33 |
  | h09 | .62 / .64 / .61 | .37 / .34 / .35 |
  | h10 | .58 / .62 / .57 | .28 / .25 / .29 |
  | h11 | .65 / .70 / .60 | .28 / .42 / .27 |
  | h12 | .78 / .88 / .72 | .38 / .60 / .31 |

- **PRIMARY5:**
  - gate 3: −0.0837 [−0.1272, −0.0481];
  - gate 4: −0.0527 [−0.0866, −0.0212].
- **Per market, gate 3:**
  - 10 of 11 point estimates are below 0;
  - houston is +0.0168 [−0.0578, +0.0862];
  - san-francisco is −0.0534 [−0.0948, −0.0151]. It was +0.0954 at 13-16 with nearest-cell inputs in R-K, which is
    consistent with RN-1 fixing KSFO's water cell.
- **Per market, gate 4:**
  - 10 of 11 are below 0;
  - nyc is +0.0053 [−0.0588, +0.0722];
  - no market's lower bound is above 0.
- **MG-2's G2 form (Brier difference against MG-1, 07-12, w_date):**
  - blend_l6_H: −0.0059 [−0.0079, −0.0040];
  - L6: −0.0038 [−0.0059, −0.0018].
- **Gate 5, R against the market at 07-12 (date-clustered).** Every interval lies above 1, so all three arms are still
  worse than the market:

  | Arm | R |
  | --- | --- |
  | P3d_H | 1.131 [1.089, 1.181] |
  | blend_l6_H | 1.112 [1.072, 1.159] |
  | L6 | 1.152 [1.105, 1.208] |

## Caveats carried from the rule

- **Disclosure 2:** the dev window has been read by every rung since R-A, and R-R was chosen because R-K won.
  The LOYO gate is the only gate on data not previously seen with HRRR.
- **Disclosure 3:** the L6 incumbent is in-sample on dev, which favours it.
- **Forward parity** (plan §8) is still required before any promotion.
- **Per rule (WIN):** L2 drafts, but does not apply, a dated MG-2 pre-13 Clarification and the forward-parity plan.

## Artifacts (`C:\t\l2\rungr\`)

| File | sha256 |
| --- | --- |
| `loyo/rr_loyo_audit.json` | `efed1405…596d` |
| `loyo/loyo_rows.jsonl` | `170c61e3…383e` |
| `emit/rr_emit_audit.json` | `205c3c17…f40b` |
| `emit/dev_B_H.jsonl` | `2130932b…2892` |
| `emit/dev_P3d_H.jsonl` | `a2dc30e2…3f3d` |
| `score/rr_score.json` | `577b689b…1dab` |
