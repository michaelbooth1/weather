# Toronto NBM sprint: clarification 4, the exact arm specification for S2 (lane L8, 2026-10-30)

This sets the implementation choices that `rule_toronto_nbm.md` §1 and §3 leave open. It is committed and
pushed **before any Arm A, Arm B or no-NBM fit**. The incumbent is P3d_N_fix-CYYZ (clarification 3,
`5dc5f1935`).

## Common to every S2 arm

- **Form:** the per-hour rung form, as in clarification 3: `_rung_entry`, `market_id=False`, `doy=True`,
  `raw_columns=False`, MIN_SCALE 5/18 C, climatology support of training labels ±5, full band Brier.
- **Rows:** CYYZ, Aug-Sep 2021-25, local hours 07..16, t = h:00 local.
  - A row enters only if every arm's inputs exist at t: the 07Z NBP, the newest NBP, the newest NBH with at
    least one TMP valid in (t, 23:00 local of D], the label, and the floor.
  - The incumbent is refitted and rescored on exactly these rows.
- **Nested LOYO:**
  - The outer loop leaves one year out.
  - Each arm, and the incumbent, is fitted on the other four years per hour. The fit includes
    `fit_pooled`'s own inner leave-one-year-out for the scale and z set.
  - No other tuning or selection is made.

## Arms

| Arm | fh (N) | `simple` | `extra_ols` | `extra_hgb` |
| --- | --- | --- | --- | --- |
| incumbent P3d_N_fix-CYYZ | NBP 07Z TXNMN of D | False | none | none |
| **Arm A** | newest NBP received by t among D-1 13Z, D-1 19Z, D 01Z, D 07Z | False | none | `nbp_sd` |
| **Arm B** | as Arm A | False | `nbh_gap` | `nbp_sd`, `nbh_gap` |
| no-NBM a1 | none (fh = NaN, so mu0 = the training centre normal) | True | none | none |
| no-NBM a2 | none | False | none | none |

**Column definitions:**
- **Newest NBP:** the one with the latest `issued_at` among those whose S3 `last_modified` <= t, for target D.
- `nbp_sd`: the TXNSD of the arm's NBP, in C.
- `nbh_rest_max`: the max NBH TMP, converted to C, over valid times strictly after t up to 23:00 local of D,
  from the NBH cycle with the latest issue time whose `last_modified` <= t.
  - The NBH TMP row is read by fixed-width alignment with the UTC row.
  - Valid times step one hour from the issue hour plus 1.
- `nbh_gap`: `nbh_rest_max` − fh, where fh is the arm's N.
- **no-NBM reference:** a1 or a2, whichever has the lower mean held-out Brier, is reported. It is
  descriptive only.

## Decision (unchanged from §3, written out)

- **Statistic:** d(date) = mean over hours of Brier(arm) − mean over hours of Brier(incumbent).
- **Bootstrap:** dates are resampled with replacement, 2,000 draws, seed 20261024. The same draw indices are
  used for Arm A and Arm B.
- **p-value:** p = the share of draws whose mean d is >= 0.
- **Holm step-down:**
  - With p(1) <= p(2): the arm with p(1) passes iff p(1) < 0.025.
  - The other arm passes iff that first arm passed and p(2) < 0.05.
  - A non-pass is a KILL.

## Descriptive only (a separate script, never gating)

- Aug-Dec 2021-25, with the same arms.
  - Oct-Dec rows use the nearest `OCT_DEC_CENTRES` centre and season `oct_dec`.
  - Oct-Dec observations come from the L14 IEM Oct-Dec files, checked against their receipts.
- Log loss.
- Per hour.
- The no-NBM reference against the incumbent.
