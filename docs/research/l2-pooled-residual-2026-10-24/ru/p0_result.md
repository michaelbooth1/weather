# R-U P0 result (rule `9441cc94…`): CLOSED

Run 2026-10-26 through `workstation_heavy.ps1 -Queue`, code `0d2602109`, output `C:/t/l2/ru/p0/ru_p0.json`
sha256 `cacdf2c84987865358444de1a63f29cac903d4ae8b738de804fb570a4adc5264` (L3 `rz_hrrr_spread.py` blob sha256
`7d82fd2c…`, unchanged from `d4ac9e414`). History only: Aug-Sep 2021-25, 13,108 rows, z coverage 1.00.

| Statistic (μ leave-one-year-out; decides) | ρ(za, \|dmax − μ\|) |
| --- | --- |
| pooled | −0.0007 (n 13,108) |
| per year 2021-25 | +0.022 / −0.012 / +0.043 / −0.026 / −0.030 (2 opposite-sign years) |
| per hour h13 / h14 / h15 / h16 | +0.011 / +0.029 / −0.026 / −0.050 |
| rise subset (dmax > half-up(high_so_far)), reported | pooled +0.029 (n 6,378) |
| frozen-state μ, reported | pooled −0.006 |

**Verdict: CLOSED** (pooled ρ < 0.05 and 2 opposite-sign years). Per the rule the lever closes; gate 1 is not run.

**high_so_far structure (reported).** The share of rows with dmax = half-up(high_so_far) is 0.22 / 0.38 / 0.61 /
0.84 at h13-16, and median |dmax − μ| falls from 0.83 to 0.16 °F while median sd9 stays near 0.6 °F. By h15-16
most of the error is mechanically gone, so a late-day spread signal could not show; but the h13-14 and rise-subset
ρ (≤ 0.044) are also below the threshold, so the closure does not rest on the late hours.
