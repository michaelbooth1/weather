# S31 P0 Clarification 2 (2026-10-31): verdict labels per D3, and the X63 note

Status: second clarification to `rule_s31_p0.md` (sha256
`d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e`, **approved by master 2026-10-31**). It sits
beside Clarification 1, `clarification_s31_p0_1.md` (sha256
`b7bb9f2aafb654bd68389c170416f3efae64b33696723a6c54572ce22e177e5d`), which was approved the same day with the
conservative per-date sigma (class SCREEN, N80 = 78). Neither approved file is edited. Lane L14, outcome-free:
no venue price or outcome was read to write this file.

## 1. Verdict labels (master ruling, D3)

These labels replace the bare "KILL" wording in rule §7, §8 and §9 for every arm (KAL-MEAN, KAL-WIDTH,
FEX-MEAN). The survivor test, the BH family (K = 3) and the w gate are unchanged.

| Arm outcome | Label |
| --- | --- |
| BH rejects at q = 0.10 and Δ's lower 95% bound > 0 (rule §7, unchanged) | **Survivor** |
| Not a survivor, and Δ's upper 95% bound < Δ_edge | **KILL at edge size** |
| Not a survivor, and Δ's upper 95% bound ≥ Δ_edge | **screen null; underpowered for information** |
| UNTESTABLE (rule §7 coverage floors not met) | **UNTESTABLE** (unchanged) |

- **Δ_edge = 0.224.** This is EXHAUSTION_REGISTER §6, "Edge size, market-residual P0s". A signal correlated ρ with
  a calibrated market's residual cuts squared error by about ρ², so a 5% Brier gain needs ρ ≥ √0.05 = 0.224. Δ is
  ρ_c − mean ρ_pl, and the placebo mean is near 0 by construction, so this P0 reads the bar on Δ directly. The
  bar is a necessary condition, not a sufficient one, and the label claims nothing beyond it.
- **The bound** is the date-clustered 95% interval that rule §5 reports (B = 10,000, seed 20261024). When the
  block-3 interval of Clarification 1 is wider, the label uses the wider upper bound.
- **Rule §8 "one EXHAUSTION_REGISTER line each":** that line carries the label from this table.
- **Rule §9:** "If all three arms KILL" means "if no arm is a Survivor". The kill-and-reopen text applies to
  arms labelled "KILL at edge size". An arm labelled "screen null; underpowered for information" closes nothing
  for information. Its register line states the upper bound and N80 = 78 (Clarification 1).

## 2. Note on Clarification 1 §5 (OM-GFS = OM-HRRR)

Clarification 1 §5 reported `gfs_seamless == ncep_hrrr_conus` as either provider blending or a capture defect.
Both possibilities had already been addressed:

- EXHAUSTION_REGISTER X63 (master ruling 2026-10-30) closed it as **NOT A DEFECT**: provider blending, "do not
  re-chase".
- Open-Meteo's GFS & HRRR documentation states that the API combines GFS with HRRR, with high-resolution data
  for the United States only. The record, the list of affected rows and the BH arithmetic are in
  `gfs-hrrr-duplication-2026-10-31.md` and the draft findings note `ef_draft_gfs_seamless_is_hrrr.md`.

S31 uses neither column, so nothing in the P0 changes.
