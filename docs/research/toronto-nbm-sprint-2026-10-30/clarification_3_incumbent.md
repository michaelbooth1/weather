# Toronto NBM sprint: clarification 3, the incumbent choice (lane L8, 2026-10-30)

This applies `rule_toronto_nbm.md` §2 (sha256 `4af6cb4f…`, @ `06d8df66c`). It is committed and pushed
**before any Arm A or Arm B fit is run**. No dev window, dev label or price has been read. Only the
2021-25 Aug-Sep history labels used by §2 were joined.

## Result

**Incumbent: P3d_N_fix-CYYZ.**

| Arm | Mean held-out band Brier | Mean held-out log loss (descriptive) |
| --- | --- | --- |
| **P3d_N_fix-CYYZ** | **0.614913** | 1.246217 |
| B_N-NBP | 0.619645 | 1.243477 |

- **Difference:** P3d_N_fix − B_N on Brier is −0.00473, date-clustered 95% interval [−0.01645, +0.00664].
  The interval is descriptive only; §2 selects on the point value.
- **Population:** blocked LOYO over Aug-Sep 2021-25, CYYZ, local hours 07..16, the same rows for both arms.
  Hours are equal-weighted within a date, then dates are equal-weighted.
  - 3,049 hour rows on 305 dates.
  - One row was dropped because the 07Z NBP had not been received by h:00 local. No row was missing a label
    or a floor.
  - NBP product versions are V4.0-V4.3.
- **Form:** the rung entry from the run env, `pooled_residual_model._rung_entry` and `_dist_from_fit`.
  - It is fitted per hour with `market_id=False, doy=True, raw_columns=False`.
  - `simple=True` gives B_N and `simple=False` gives P3d_N_fix.
  - MIN_SCALE is 0.5 F = 5/18 C, patched in-process; no repo edit.
  - Climatology support is the training-fold labels ±5 C, with alpha 0.10.
  - Brier is the full band Brier, sum p² − 2p(y) + 1. On every row it equals `feature_model.brier_score`.
- **N:** the NBP 07Z TXNMN of D in C, admitted only if its S3 `last_modified` is at or before h:00 local.
  The floor F is the IEM CYYZ METAR running max to h:00 local. Labels are WU whole C.

## Receipts

The run is light (12.8 s, well under 1 GB), so it ran directly with its sha recorded.

- **Run env:** `claude/loyo-screen-runenv-20261030` @ `cf381f0f34e50ed329990e43a2298235164df43e`.
- **Script:** `C:\t\l8tor\incumbent.py`, sha256
  `c26170b6154dfe9a5673f3e1706c084a2e97831e4967fb0244a2a3783da66e3c`.
- **Receipt:** `C:\t\l8tor\incumbent_out\receipt.json`, sha256
  `dd70ce02f99726ed873c0592e8c9ca285dfeaaee0774aa25f65ce3c9881824ae`.
- **Per-row output (written for both arms):**
  - per-hour rows: `rows_hour.jsonl`, sha256 `e5d131ee3bed0268613d9982e84d4fc6ae31599817d09122b4471530e33302dc`;
  - per-date rows: `rows_date.jsonl`, sha256 `c258a286d4670986e45423876218bcc3778a8dd2a05104a4d66722847b65d9c8`.
- **Inputs:**
  - NBP manifest `8fd73a81…c019`;
  - obs `9f3b2972…a802`;
  - labels `1ced925a…20e1` and `c9e16b1d…433a`.

## Consequence for S2

S2 (§3) scores Arm A and Arm B against **P3d_N_fix-CYYZ**, in the same per-hour rung form, with the same rows
and hours.

The incumbent is P3d_N_fix, not B_N-NBP, so the ruling's B_N near-identity condition does not apply. §1's
note still holds:
- Arm A shares the incumbent's source (NBP TXNMN). It differs only in its cycle (newest received, not 07Z)
  and in TXNSD. So it remains a spec-and-timing test.
- Only Arm B adds a new product (NBS/NBH).
