# R-P2 screen verdict: PASS (necessary only; not confirmation)

The verdict landed at WS Get-Date 2026-11-02T14:04:31-05:00. The run launched at 2026-11-02T13:47:14-05:00 via
`workstation_heavy.ps1 -Queue`, after the cleanup pass and on the coordinator's RUN SCREEN.

The prereg is `prereg_rp2.md` (sha256 2a438306…), with `clarification_1.md`. No dev data was read. The screen years
informed the design, so this PASS confirms nothing.

## Run identity

| Item | Value |
| --- | --- |
| Code tip | c38e2c619f0967767a1631b496f29dd81a322c90 |
| Module sha256 | d4947cfe1b02c537ec84fca994ef0c1c26572be0251810eb744b421aae09f0b7 |
| Receipt | `rp2_screen_receipt.json` |
| Report | `rp2_loyo_report.json`, sha256 66f9278e12acc0417a930a4b01a9ef0caee3073731dcbec93bd8b52411884c50 |
| Rows | `rp2_loyo_rows.jsonl` (C:\t\rp2\screen), sha256 fface859ee19263647fac094b8ba626c560caad0d6761b1b3c022250a3553a7f |

## Results

**Controls.** C-0 passes (19,657 of 19,657 rows, max abs diff 0.0 vs R-A). C-b passes (0.0).

**Gate statistic.** d = Brier(P3d_N_cls) − Brier(P3d_N_11m), h07..h12, mean per row. The base Brier mean is 0.85156.

| Quantity | Value | Kill condition |
| --- | --- | --- |
| Point | −0.00390 | 1: ≥ −0.0005? no |
| Date-clustered 95% CI | [−0.00529, −0.00247] | |
| Block-3 95% CI | [−0.00545, −0.00225] | 2: wider upper ≥ 0? no |
| Markets CI-worse | none | 3: no |
| Years with d > 0 | 0 | 4: no |
| Log loss d (reported) | −0.0295 [−0.0432, −0.0180] | |

**Per market (d, 95% CI).**

| Market | d | 95% CI |
| --- | --- | --- |
| chicago | −0.0085 | [−0.0130, −0.0036] |
| miami | −0.0081 | [−0.0123, −0.0039] |
| houston | −0.0079 | [−0.0119, −0.0041] |
| austin | −0.0073 | [−0.0119, −0.0022] |
| denver | −0.0063 | [−0.0125, −0.0004] |
| nyc | −0.0048 | [−0.0091, −0.0006] |
| atlanta | −0.0045 | [−0.0093, 0.0004] |
| dallas | −0.0013 | [−0.0071, 0.0046] |
| san-francisco | −0.0011 | [−0.0056, 0.0047] |
| seattle | +0.0028 | [−0.0007, 0.0066] |
| los-angeles | +0.0041 | [−0.0002, 0.0084] (it was +0.0217 under R-P) |

**Per year.** 2021 −0.0001; 2022 −0.0013; 2023 −0.0053; 2024 −0.0048; 2025 −0.0080.

**Per hour.** h07 −0.0040, h08 −0.0033, h09 −0.0034, h10 −0.0028, h11 −0.0045, h12 −0.0054. Every hour's CI
excludes 0.

**Dose arm P3d_N_cls100 (descriptive only).** d = −0.00329, clustered CI [−0.00450, −0.00203], block-3 CI
[−0.00465, −0.00189]. No market is CI-worse.

**D-x, los-angeles held-out residual.** −0.09 °F under the base arm, −0.28 under P3d_N_cls, against −0.43 under R-P.

## Disposition (master's stated expectation for a PASS)

"screen PASS; confirmation infeasible at size; PARKED as ingredient; reopen trigger: a year-round base model or a
variance reduction bringing the forward length under 1 season". No shadow infrastructure has been built. The season
scope of any shadow is still deferred.
