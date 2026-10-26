# R-U rule: HRRR 3x3 spread anomaly as day-specific width on P3d_H at 13-16 (P0 only, history only)

Lane L2, 2026-10-26. Approved by the coordinator (10-26, after the name and family check) with conditions 1-5,
quoted in section 6. This file is written, hashed and bound to a PENDING DEV_WINDOW_LEDGER row before anything
runs. It governs **P0 only**. Gate 1 is not written here; it exists only if P0 survives and the coordinator
confirms. No dev, capture, price, panel, settlement or 88a row, and nothing dated after 2026-09-29, is read.

## 1. Lever

Day-specific width only, on the 13-16 HRRR arm P3d_H:
s' = s_P3dH · exp(γ_h (z − z̄_{m,h})), γ_h ∈ [0, 1].

- **z** is exactly L3's R-Z definition, by L3's code (`weather.calibration.rz_hrrr_spread`, branch
  `claude/rz-hrrr-spread-20261026` at `d4ac9e414`, functions `hrrr_spread` / `spread_of_cells`, unchanged):
  z = ln(max(sd9, 0.1)), sd9 the population SD (ddof 0, °F) across the 9 cells of the stored HRRR 3x3 block of the
  cell-wise forecast max over the selection's forecast hours (L13's point-in-time cycle choice, window to 17:00
  local). A selection with no cycle, a truncated window, or any message or cell absent gives no z.
- **z̄_{m,h}** is the training-years mean of z per market and hour, so the multiplier carries only the day-specific
  anomaly and cannot act as a per-market or per-hour scale map.
- Centre, floor, band mapping and the P3d_H state are untouched. No global sharpening.

## 2. Population and arm (history only)

- Rows: the P3d_H 13-16 training frame, Aug-Sep 2021-25, as rebuilt by `mg3_freeze_state --block 13-16` (records
  `C:\t\l2\records`, NBM train corpus `1ae4bf52…`, HRRR 13-16 corpus `C:\t\l13\hrrr` manifest `409f6f91…`,
  selections `055add5a…`), local hours 13-16, markets of that frame, CYYZ excluded. Rows without z are excluded.
- **μ (decision): leave-one-year-out.** For held-out year Y and hour h, μ is the pre-floor mean of a P3d_H fit
  on the other four years' rows at hour h, by the R-K LOYO code path (`_rung_entry` with `RK_ARMS["P3d_H"]`,
  the same spec and features as the frozen state). So μ and z̄ are both out of year, as in R-Z's P0
  (coordinator ruling 10-26 under master's delegation: an in-sample μ shrinks |dmax − μ| on training rows, and
  that shrinkage can co-vary with spread, biasing ρ and breaking comparability with R-Z).
- **μ (secondary, reported only):** the pre-floor mean from the frozen P3d_H 13-16 state
  `e891d884e06164a6925f6b2bbf1c7756529cb35222ab0c8c863552cfa7457db7`, which is in-sample on every history row.
  It decides nothing.
- e = |dmax − μ|, dmax the frame's own label.

## 3. P0 (no Brier is read)

Leave-one-year-out over 2021-2025: for held-out year Y, za = z − z̄_{m,h} with z̄ from the other four years.
Spearman ρ(za, e), by L3's `_spearman`:

- pooled over 13-16 (all held-out rows of all five years);
- per held-out year; **per hour (13, 14, 15, 16)**; per market (reported only).

**Thresholds (L3's R-Z, unchanged).** The block CLOSES if pooled ρ < 0.05, or if the per-year ρ has the sign
opposite to the pooled ρ in ≥ 2 of the 5 years. **Precondition (stop, not kill):** z coverage ≥ 0.90 of the
frame's rows.

**If P0 closes, the lever closes** (coordinator condition 4) and is recorded. There is no rescue by hour, market or
alternative e.

### 3a. high_so_far structure (reported, no decision)

Late in the day the observed running max covers most of dmax, so |dmax − μ| is mechanically small and the HRRR
window [h, 17:00] shrinks. Reported beside P0:
- per hour: median e, share of rows with dmax = half-up(high_so_far at the snapshot), median sd9;
- ρ on the "rise" subset (dmax > half-up(high_so_far)) pooled and per hour;
- the reading: whether any pooled signal is carried by h13-14 only.

None of these changes the P0 verdict.

## 4. Inputs (pinned)

| Input | sha256 |
| --- | --- |
| P3d_H 13-16 frozen state (secondary μ only) | `e891d884e06164a6925f6b2bbf1c7756529cb35222ab0c8c863552cfa7457db7` |
| State rule | `9e63899ddcfcbd795f10f0437c7bd9f9b6fc9740767b8d824818ef0f7f95cc5d` |
| NBM train corpus | `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd` |
| HRRR 13-16 manifest / selections | `409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935` / `055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75` |
| L3 R-Z module | `rz_hrrr_spread.py` at `d4ac9e414`; its blob sha256 is recorded in the output |

HRRR selections after 2025-12-31 or outside months 8-9 are not used; any after 2026-09-29 refuses.

## 5. Mechanics

A research-only CLI in `weather.calibration.pooled_residual_model` (`ru-p0`), output outside the repository,
write-once, run once through `scripts/ops/workstation_heavy.ps1 -Queue`. R-U never changes the frozen MG-3 states,
weights, binding or rule; this branch is kept separate from `claude/mg3-freeze-20261026`.

## 6. Family record and prior (quoted as the coordinator relayed them, 10-26)

- **X38 (R-Z):** HRRR 3x3 spread anomaly closed at 00-06 and 07-12 at P0; 13-16 explicitly left to L2. R-Z's P0
  per-year ρ were 0.12/0.12/−0.09/−0.02/+0.02 (00-06) and 0.02/0.09/0.01/0.00/−0.06 (07-12).
- **X37 (R-S):** NBM-published spread into the P3d scale, a different source; its 13-16 secondary failed,
  −0.00023 [−0.00060, +0.00017].
- **X23:** at 13-16 the blend gain was the floor.
- **X19:** fitted temperature and scale maps for NBM arms are closed; spread *information* is allowed under R9.
- **S7:** multi-run HRRR, a different construct.
- **Prior: low.** R-Z's weak P0 and X23 make a null the likely outcome; it will be recorded as such.

### Conditions (coordinator)

1. Day-specific anomaly only: no per-market or per-hour fitted scale, no global sharpening, floor untouched.
2. P0 first at 13-16 with L3's module and thresholds unchanged, against |dmax − μ| of the P3d_H 13-16 arm
   (leave-one-year-out μ decides; the frozen state's μ is reported), by hour with the high_so_far reading.
3. Rule hashed and ledger row PENDING before any run.
4. X23, X37's 13-16 secondary and X38 quoted; if P0 fails, the lever closes.
5. R-U never changes the frozen MG-3; at most a later forward-shadow candidate.
