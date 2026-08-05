# Workstation current-replay time frontier — 2026-07-22

## Verdict

Research-only current-code replay evidence: H1 selected weights on tune
only (C=1.0, F=1.0); only those arms and the actual
weight-zero incumbent were opened on untouched holdout. No unselected
holdout arm was discovered or scored.

The primary result averages snapshots within market-date, markets within
fleet-date equally, then fleet dates equally. Raw band/cadence density cannot
dominate. Captured market quotes remain raw and are not normalized post hoc.

## Decision and interpretation

**Do not promote W1 as the under-sharpness fix.** It improves proper
losses in useful slices, but untouched holdout does not support an
all-three improvement in Brier, log loss, and realized-winner probability.

- F: Brier/log-loss improve with 95% paired fleet-date intervals below zero for all-hours, predawn, and evening. Yet winner probability changes by -0.01241 all-hours, -0.00101 predawn, and -0.02367 evening. The all-hours and evening decreases are confidence-supported.
- C predawn is the only directional all-three slice: Brier -0.00569, log loss -0.01065, winner probability 0.00118. Only the two proper-loss intervals exclude zero; winner probability does not.
- The market remains confidence-supported better than selected W1 on
  Brier, log loss, and winner probability in all six C/F major holdout
  slices. Smoothing narrows some loss gaps but does not close the frontier.
- Neither incumbent nor W1 has joint three-metric edge at any observed
  15:00-23:00 hour. Market catch-up is already present at 15:00; it is
  confidence-supported from 16:00 for C W1 and 15:00 for F W1.
- Fixed-composition F coverage retains 13/15 all-hours, 11/14 predawn, and 13/15 evening dates and reproduces the same proper-loss/winner-probability tradeoff.
- Exact final-distribution mechanics classify W1 as `DIFFUSER_ALL_THREE`
  in all six major slices: entropy rises, maximum bucket mass falls, and
  bucket-key standard deviation rises, with every paired interval in the
  diffusion direction. All-hours C changes are entropy 0.26980, max mass -0.14186, and spread 0.11895°C; F changes are 0.20774, -0.12041, and 0.04677°F (0.02599°C-equivalent).
- Fixed ten-minute audit: W1 point Brier/log-loss is lower in C 18/18 and 18/18 slots; F 18/18 and 18/18. Paired intervals support those directions for Brier C 18/18, F 17/18 and log loss C 12/18, F 17/18.
- Winner probability rises at the point estimate in C 11/18 and F 12/18 slots, but 0/36 slot intervals exclude zero in either direction. Under the strict complete F panel, only 2/18 point estimates rise, exposing composition sensitivity.
- Captured market is confidence-supported better than W1 on all three metrics in 36/36 unit-slots. These correlated, unadjusted holdout slices are descriptive and select no slot.

### Useful next experiment

Run a new, predeclared tune/holdout experiment—not a re-read of this
holdout—with family-aware and time-conditioned candidates. H1 sigma=0.75
uses raw native numeric bucket-key distance: 0.75°C for C, but 0.75°F
(0.4167°C) for F, so it is not a common physical bandwidth. Compare
physically equivalent C/F bandwidths and an early-hours-only C arm against
weight zero. Require non-degradation in realized-winner probability as a
constraint while ranking Brier/log-loss; correct any hourly or city search
for multiplicity. The apparent C 00:00-06:00 opportunity and city extremes
below are hypotheses only and cannot select a candidate from this holdout.

| Unit | Slice | Dates | Weight | Disposition | Current Brier | Selected Brier | Market Brier | Δ selected-current (95% CI) | Brier signs F/U/T | Current/selected/market winner P |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| C | all_hours | 14 | 1.00 | MIXED_OR_NOT_SUPPORTED | 0.06535 | 0.06265 | 0.04026 | -0.00270 [-0.00976, 0.00321] | 8/6/0 | 0.39486/0.33913/0.55541 |
| C | predawn_03_05 | 13 | 1.00 | DIRECTIONAL_ALL_THREE | 0.09468 | 0.08900 | 0.06029 | -0.00569 [-0.00895, -0.00227] | 11/2/0 | 0.12084/0.12202/0.33466 |
| C | evening_15_23 | 14 | 1.00 | MIXED_OR_NOT_SUPPORTED | 0.03175 | 0.03010 | 0.00676 | -0.00165 [-0.02138, 0.01394] | 4/10/0 | 0.72884/0.61353/0.90112 |
| F | all_hours | 15 | 1.00 | MIXED_OR_NOT_SUPPORTED | 0.06824 | 0.06581 | 0.03766 | -0.00243 [-0.00359, -0.00150] | 15/0/0 | 0.33581/0.32340/0.59238 |
| F | predawn_03_05 | 14 | 1.00 | MIXED_OR_NOT_SUPPORTED | 0.07950 | 0.07653 | 0.05921 | -0.00297 [-0.00411, -0.00187] | 13/1/0 | 0.22473/0.22372/0.35400 |
| F | evening_15_23 | 15 | 1.00 | MIXED_OR_NOT_SUPPORTED | 0.05665 | 0.05493 | 0.01389 | -0.00173 [-0.00355, -0.00002] | 8/7/0 | 0.45152/0.42784/0.84881 |

| Unit | Slice | Current/selected/market log loss | Δ log loss (95% CI) | Log-loss signs F/U/T | Δ winner P (95% CI) | Winner signs F/U/T |
| --- | --- | --- | --- | --- | --- | --- |
| C | all_hours | 0.23957/0.23462/0.13403 | -0.00495 [-0.03284, 0.01853] | 6/8/0 | -0.05573 [-0.10090, -0.00891] | 3/11/0 |
| C | predawn_03_05 | 0.34727/0.33662/0.20186 | -0.01065 [-0.02054, -0.00168] | 10/3/0 | 0.00118 [-0.00885, 0.00850] | 9/4/0 |
| C | evening_15_23 | 0.11305/0.11385/0.02405 | 0.00081 [-0.06870, 0.05523] | 4/10/0 | -0.11530 [-0.22218, 0.00406] | 3/11/0 |
| F | all_hours | 0.23514/0.22658/0.11769 | -0.00856 [-0.01181, -0.00568] | 14/1/0 | -0.01241 [-0.01764, -0.00683] | 2/13/0 |
| F | predawn_03_05 | 0.28498/0.27333/0.18299 | -0.01165 [-0.01491, -0.00841] | 14/0/0 | -0.00101 [-0.00672, 0.00383] | 8/6/0 |
| F | evening_15_23 | 0.18864/0.18320/0.04449 | -0.00544 [-0.01068, -0.00077] | 8/7/0 | -0.02367 [-0.03363, -0.01409] | 2/13/0 |

## Fixed predawn ten-minute evidence (descriptive, multiplicity-sensitive)

All 18 local slots from 03:00-03:09 through 05:50-05:59 are shown;
none selected the arm or was selected after viewing holdout. The primary
uses aligned snapshot -> market-date -> equal-market fleet-date -> equal
date weighting. Strict-panel columns retain a slot/date only when every
configured market in its native unit is present; missing cities are never
imputed. With 18 correlated slot comparisons per unit and no multiplicity
adjustment, these rows are descriptive and are not a ten-minute gate.

| Unit | Slot | Available dates | Markets/date min-max | Strict complete/dropped | W1-W0 Brier/log-loss/winner-P | Strict W1-W0 Brier/log-loss/winner-P |
| --- | --- | ---: | --- | --- | --- | --- |
| C | 03:00-03:09 | 13 | 1-1 | 13/0 | -0.00623/-0.01270/0.00206 | -0.00623/-0.01270/0.00206 |
| C | 03:10-03:19 | 10 | 1-1 | 10/0 | -0.00711/-0.01433/0.00231 | -0.00711/-0.01433/0.00231 |
| C | 03:20-03:29 | 13 | 1-1 | 13/0 | -0.00600/-0.01192/0.00336 | -0.00600/-0.01192/0.00336 |
| C | 03:30-03:39 | 11 | 1-1 | 11/0 | -0.00642/-0.01266/0.00091 | -0.00642/-0.01266/0.00091 |
| C | 03:40-03:49 | 12 | 1-1 | 12/0 | -0.00627/-0.01268/0.00339 | -0.00627/-0.01268/0.00339 |
| C | 03:50-03:59 | 12 | 1-1 | 12/0 | -0.00567/-0.01072/-0.00069 | -0.00567/-0.01072/-0.00069 |
| C | 04:00-04:09 | 12 | 1-1 | 12/0 | -0.00510/-0.00890/-0.00002 | -0.00510/-0.00890/-0.00002 |
| C | 04:10-04:19 | 11 | 1-1 | 11/0 | -0.00535/-0.00898/-0.00229 | -0.00535/-0.00898/-0.00229 |
| C | 04:20-04:29 | 12 | 1-1 | 12/0 | -0.00517/-0.00909/0.00027 | -0.00517/-0.00909/0.00027 |
| C | 04:30-04:39 | 13 | 1-1 | 13/0 | -0.00468/-0.00788/-0.00134 | -0.00468/-0.00788/-0.00134 |
| C | 04:40-04:49 | 12 | 1-1 | 12/0 | -0.00596/-0.01205/0.00246 | -0.00596/-0.01205/0.00246 |
| C | 04:50-04:59 | 12 | 1-1 | 12/0 | -0.00555/-0.00985/-0.00067 | -0.00555/-0.00985/-0.00067 |
| C | 05:00-05:09 | 13 | 1-1 | 13/0 | -0.00621/-0.01150/0.00198 | -0.00621/-0.01150/0.00198 |
| C | 05:10-05:19 | 12 | 1-1 | 12/0 | -0.00599/-0.01108/-0.00089 | -0.00599/-0.01108/-0.00089 |
| C | 05:20-05:29 | 11 | 1-1 | 11/0 | -0.00695/-0.01299/0.00272 | -0.00695/-0.01299/0.00272 |
| C | 05:30-05:39 | 13 | 1-1 | 13/0 | -0.00573/-0.01010/0.00003 | -0.00573/-0.01010/0.00003 |
| C | 05:40-05:49 | 11 | 1-1 | 11/0 | -0.00576/-0.01020/-0.00178 | -0.00576/-0.01020/-0.00178 |
| C | 05:50-05:59 | 13 | 1-1 | 13/0 | -0.00573/-0.01010/0.00003 | -0.00573/-0.01010/0.00003 |
| F | 03:00-03:09 | 13 | 6-11 | 10/3 | -0.00402/-0.01277/0.00437 | -0.00323/-0.01082/0.00058 |
| F | 03:10-03:19 | 14 | 1-11 | 9/5 | -0.00171/-0.00685/-0.01122 | -0.00331/-0.01100/0.00089 |
| F | 03:20-03:29 | 14 | 1-11 | 10/4 | -0.00336/-0.01196/0.00191 | -0.00291/-0.01071/-0.00200 |
| F | 03:30-03:39 | 13 | 2-11 | 9/4 | -0.00267/-0.00904/-0.00708 | -0.00305/-0.01094/-0.00057 |
| F | 03:40-03:49 | 14 | 1-11 | 10/4 | -0.00305/-0.01251/0.00028 | -0.00285/-0.01019/-0.00182 |
| F | 03:50-03:59 | 13 | 3-11 | 11/2 | -0.00284/-0.01053/-0.00312 | -0.00283/-0.01146/-0.00185 |
| F | 04:00-04:09 | 14 | 1-11 | 10/4 | -0.00299/-0.01226/-0.00090 | -0.00255/-0.01096/-0.00391 |
| F | 04:10-04:19 | 13 | 3-11 | 9/4 | -0.00445/-0.01434/0.00690 | -0.00213/-0.00914/-0.00469 |
| F | 04:20-04:29 | 14 | 1-11 | 10/4 | -0.00274/-0.01117/-0.00479 | -0.00238/-0.01022/-0.00421 |
| F | 04:30-04:39 | 13 | 4-11 | 11/2 | -0.00363/-0.01264/-0.00014 | -0.00297/-0.01191/-0.00262 |
| F | 04:40-04:49 | 14 | 1-11 | 11/3 | -0.00397/-0.01438/0.00455 | -0.00296/-0.01183/-0.00280 |
| F | 04:50-04:59 | 14 | 1-11 | 10/4 | -0.00348/-0.01363/0.00241 | -0.00277/-0.01084/-0.00291 |
| F | 05:00-05:09 | 14 | 1-11 | 10/4 | -0.00364/-0.01241/0.00310 | -0.00303/-0.01139/-0.00162 |
| F | 05:10-05:19 | 13 | 3-11 | 9/4 | -0.00433/-0.01381/0.00487 | -0.00296/-0.01129/-0.00201 |
| F | 05:20-05:29 | 14 | 1-11 | 9/5 | -0.00350/-0.01600/0.00089 | -0.00302/-0.01151/-0.00145 |
| F | 05:30-05:39 | 14 | 1-11 | 10/4 | -0.00378/-0.01391/0.00377 | -0.00301/-0.01152/-0.00207 |
| F | 05:40-05:49 | 13 | 1-11 | 10/3 | -0.00552/-0.01650/0.01215 | -0.00302/-0.01147/-0.00193 |
| F | 05:50-05:59 | 14 | 1-11 | 11/3 | -0.00389/-0.01537/0.00474 | -0.00313/-0.01168/-0.00132 |

W1 versus captured-market deltas for the same fixed slots:

| Unit | Slot | W1-market Brier | W1-market log loss | W1-market winner P |
| --- | --- | ---: | ---: | ---: |
| C | 03:00-03:09 | 0.02970 | 0.14510 | -0.21377 |
| C | 03:10-03:19 | 0.02909 | 0.15489 | -0.20571 |
| C | 03:20-03:29 | 0.02503 | 0.12791 | -0.18997 |
| C | 03:30-03:39 | 0.02833 | 0.13849 | -0.20069 |
| C | 03:40-03:49 | 0.02642 | 0.13132 | -0.20125 |
| C | 03:50-03:59 | 0.02468 | 0.12748 | -0.18824 |
| C | 04:00-04:09 | 0.02616 | 0.12944 | -0.19938 |
| C | 04:10-04:19 | 0.02873 | 0.13753 | -0.20442 |
| C | 04:20-04:29 | 0.02758 | 0.13280 | -0.20797 |
| C | 04:30-04:39 | 0.02684 | 0.12529 | -0.20244 |
| C | 04:40-04:49 | 0.03023 | 0.13974 | -0.21873 |
| C | 04:50-04:59 | 0.03275 | 0.14679 | -0.23628 |
| C | 05:00-05:09 | 0.03146 | 0.14140 | -0.22717 |
| C | 05:10-05:19 | 0.03391 | 0.15315 | -0.24549 |
| C | 05:20-05:29 | 0.03313 | 0.15007 | -0.23811 |
| C | 05:30-05:39 | 0.03229 | 0.14384 | -0.23875 |
| C | 05:40-05:49 | 0.03099 | 0.14878 | -0.23421 |
| C | 05:50-05:59 | 0.03205 | 0.14275 | -0.23329 |
| F | 03:00-03:09 | 0.01731 | 0.06848 | -0.12393 |
| F | 03:10-03:19 | 0.01415 | 0.08030 | -0.11013 |
| F | 03:20-03:29 | 0.01829 | 0.09017 | -0.13492 |
| F | 03:30-03:39 | 0.01721 | 0.07040 | -0.11988 |
| F | 03:40-03:49 | 0.01700 | 0.09036 | -0.12646 |
| F | 03:50-03:59 | 0.01738 | 0.07295 | -0.12569 |
| F | 04:00-04:09 | 0.01750 | 0.09150 | -0.13201 |
| F | 04:10-04:19 | 0.01741 | 0.07223 | -0.12733 |
| F | 04:20-04:29 | 0.01745 | 0.09058 | -0.12918 |
| F | 04:30-04:39 | 0.01609 | 0.06703 | -0.11936 |
| F | 04:40-04:49 | 0.01715 | 0.08993 | -0.13052 |
| F | 04:50-04:59 | 0.01692 | 0.09067 | -0.12889 |
| F | 05:00-05:09 | 0.01729 | 0.09077 | -0.13336 |
| F | 05:10-05:19 | 0.01721 | 0.07139 | -0.12938 |
| F | 05:20-05:29 | 0.01702 | 0.09026 | -0.13151 |
| F | 05:30-05:39 | 0.01795 | 0.09270 | -0.14148 |
| F | 05:40-05:49 | 0.01787 | 0.07087 | -0.13495 |
| F | 05:50-05:59 | 0.01725 | 0.09190 | -0.13700 |

Every slot's 10,000-replicate paired fleet-date interval, sign counts,
per-market row, and strict-panel counterpart is retained in the result
JSON and primary/strict summary CSVs.

## Distribution-sharpness mechanics (descriptive holdout diagnostic)

These are exact replay bucket distributions aligned W1-to-W0, then
weighted snapshot -> market-date -> equal-market fleet-date -> equal date.
Higher entropy, lower maximum-bucket probability, and higher standard
deviation indicate diffusion. This post-selection diagnostic is not a new
gate and did not select an arm. Entropy is compared only within unit; F
standard deviation is also converted to C-equivalent width by multiplying
by 5/9.

| Unit | Slice | Dates | Entropy current/selected/Δ (95% CI) | Max bucket current/selected/Δ (95% CI) | Std native current/selected/Δ (95% CI) | Std C-equivalent current/selected/Δ | Shape |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| C | all_hours | 14 | 1.18188/1.45168/0.26980 [0.20434, 0.33799] | 0.58067/0.43881/-0.14186 [-0.17073, -0.11323] | 1.21061/1.32957/0.11895 [0.08252, 0.15862] | 1.21061/1.32957/0.11895 | DIFFUSER_ALL_THREE |
| C | predawn_03_05 | 13 | 1.91783/2.06153/0.14370 [0.08198, 0.20984] | 0.35602/0.25335/-0.10267 [-0.14726, -0.06157] | 2.17683/2.21323/0.03640 [0.01011, 0.06212] | 2.17683/2.21323/0.03640 | DIFFUSER_ALL_THREE |
| C | evening_15_23 | 14 | 0.40986/0.83013/0.42027 [0.26818, 0.55949] | 0.85883/0.66146/-0.19737 [-0.26069, -0.12907] | 0.37861/0.58824/0.20963 [0.12774, 0.28062] | 0.37861/0.58824/0.20963 | DIFFUSER_ALL_THREE |
| F | all_hours | 15 | 1.74532/1.95306/0.20774 [0.19318, 0.22179] | 0.44149/0.32107/-0.12041 [-0.12840, -0.11181] | 2.40631/2.45309/0.04677 [0.04353, 0.04969] | 1.33684/1.36283/0.02599 | DIFFUSER_ALL_THREE |
| F | predawn_03_05 | 14 | 2.11414/2.29151/0.17737 [0.16666, 0.18790] | 0.35097/0.24692/-0.10406 [-0.11035, -0.09792] | 3.32785/3.36477/0.03692 [0.02799, 0.04388] | 1.84880/1.86932/0.02051 | DIFFUSER_ALL_THREE |
| F | evening_15_23 | 15 | 1.39197/1.61525/0.22329 [0.18795, 0.25361] | 0.53255/0.40417/-0.12838 [-0.14733, -0.10533] | 1.63830/1.68646/0.04816 [0.04363, 0.05255] | 0.91017/0.93692/0.02675 | DIFFUSER_ALL_THREE |

Paired fleet-date sign counts, all 24 hourly slices, per-market rows,
reader bounds, probability-mass error, and 10,000-replicate intervals
are preserved in `sharpness_mechanics.json`.

## Complete configured-market panel sensitivity

This secondary check holds city composition fixed at all 12 configured markets, evaluated inside native units: C requires 1 (toronto); F requires 11 (atlanta, austin, chicago, dallas, denver, houston, los-angeles, miami, nyc, san-francisco, seattle).
A date/slot is retained only when every configured market for that unit is
present. Missing cities are dropped and counted; no imputation or partial
panel substitution is allowed. This sensitivity does not replace the
aligned equal-market/equal-date primary result.

| Unit | Slice | Available dates | Complete dates | Dropped | Δ Brier | Δ log loss | Δ winner P | Disposition |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| C | all_hours | 14 | 14 | 0 | -0.00270 | -0.00495 | -0.05573 | MIXED_OR_NOT_SUPPORTED |
| C | predawn_03_05 | 13 | 13 | 0 | -0.00569 | -0.01065 | 0.00118 | DIRECTIONAL_ALL_THREE |
| C | evening_15_23 | 14 | 14 | 0 | -0.00165 | 0.00081 | -0.11530 | MIXED_OR_NOT_SUPPORTED |
| F | all_hours | 15 | 13 | 2 | -0.00271 | -0.00924 | -0.01158 | MIXED_OR_NOT_SUPPORTED |
| F | predawn_03_05 | 14 | 11 | 3 | -0.00291 | -0.01133 | -0.00231 | MIXED_OR_NOT_SUPPORTED |
| F | evening_15_23 | 15 | 13 | 2 | -0.00216 | -0.00702 | -0.02233 | MIXED_OR_NOT_SUPPORTED |

Focused hourly coverage and Brier sensitivity:

| Unit | Hour | Available dates | Complete dates | Missing-panel dates | Δ selected-current Brier | Selected-market Brier Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C | 03:00 | 13 | 13 | 0 | -0.00596 | 0.02658 |
| C | 04:00 | 13 | 13 | 0 | -0.00512 | 0.02775 |
| C | 05:00 | 13 | 13 | 0 | -0.00606 | 0.03212 |
| C | 15:00 | 14 | 14 | 0 | -0.00284 | 0.01716 |
| C | 16:00 | 14 | 14 | 0 | -0.00197 | 0.02469 |
| C | 17:00 | 14 | 14 | 0 | 0.00737 | 0.01837 |
| C | 18:00 | 14 | 14 | 0 | 0.00283 | 0.02732 |
| C | 19:00 | 14 | 14 | 0 | -0.00366 | 0.02661 |
| C | 20:00 | 14 | 14 | 0 | -0.01017 | 0.02656 |
| C | 21:00 | 14 | 14 | 0 | -0.01068 | 0.02606 |
| C | 22:00 | 13 | 13 | 0 | -0.00040 | 0.02553 |
| C | 23:00 | 13 | 13 | 0 | -0.00085 | 0.02493 |
| F | 03:00 | 14 | 11 | 3 | -0.00286 | 0.01781 |
| F | 04:00 | 14 | 11 | 3 | -0.00284 | 0.01791 |
| F | 05:00 | 14 | 11 | 3 | -0.00309 | 0.01857 |
| F | 15:00 | 15 | 13 | 2 | -0.00253 | 0.01748 |
| F | 16:00 | 15 | 13 | 2 | 0.00038 | 0.01991 |
| F | 17:00 | 15 | 13 | 2 | -0.00296 | 0.02911 |
| F | 18:00 | 15 | 13 | 2 | -0.00465 | 0.03678 |
| F | 19:00 | 15 | 13 | 2 | -0.00468 | 0.04451 |
| F | 20:00 | 15 | 13 | 2 | -0.00196 | 0.05356 |
| F | 21:00 | 15 | 12 | 3 | -0.00172 | 0.05983 |
| F | 22:00 | 14 | 11 | 3 | -0.00088 | 0.05496 |
| F | 23:00 | 14 | 12 | 2 | 0.00039 | 0.05484 |

All 24 hourly coverage rows, exact retained/dropped dates, strict-panel
summaries, and strict-panel breakpoints are preserved in the JSON and
dedicated CSV/coverage artifacts. Slots with zero complete dates remain
explicitly unsupported.

## Snapshot identity collision handling

The H1 identity contract keeps the first repeated key only when replayed
probability, outcome, market quote, and native unit are canonically
identical (NaN-safe). Any scoring-field conflict blocks; non-scoring
`recorded_p` is ignored for current replay.

| Split | Raw rows | Unique keys | Equivalent extras | Affected market-dates |
| --- | ---: | ---: | ---: | --- |
| tune | 218427 | 218405 | 22 | atlanta 2026-06-16, toronto 2026-06-19 |
| holdout | 268059 | 268059 | 0 | none |

## Dated historical comparator (post-hoc, noncomparable context)

The read-only `hourly_model_performance_v0.3` artifact spans 2026-05-28 through 2026-07-18 (384 market-days), gate `BLOCK`. historical v0.3 uses first market-day-band checkpoint per local hour; H1 frontier uses aligned replay snapshots, then market-date/fleet-date equal weighting. It is never pooled with H1 and cannot select or validate an H1 arm.

| Hour | Market-days | Historical model/market Brier | Model-market Δ | Historical model/market winner P |
| ---: | ---: | --- | ---: | --- |
| 03:00 | 351 | 0.08007/0.06127 | 0.01881 | 0.21823/0.33180 |
| 04:00 | 351 | 0.07954/0.06161 | 0.01793 | 0.22092/0.33265 |
| 05:00 | 363 | 0.07813/0.06047 | 0.01765 | 0.22734/0.34112 |
| 15:00 | 384 | 0.05854/0.04351 | 0.01503 | 0.39693/0.52133 |
| 16:00 | 384 | 0.05473/0.03246 | 0.02227 | 0.44696/0.62486 |
| 17:00 | 384 | 0.04690/0.02201 | 0.02489 | 0.52220/0.74181 |
| 18:00 | 384 | 0.04495/0.01189 | 0.03306 | 0.55427/0.85734 |
| 19:00 | 384 | 0.03707/0.00697 | 0.03010 | 0.61920/0.91971 |
| 20:00 | 382 | 0.03695/0.00129 | 0.03566 | 0.63086/0.97889 |
| 21:00 | 378 | 0.04128/0.00005 | 0.04123 | 0.61257/0.99526 |
| 22:00 | 366 | 0.03660/0.00003 | 0.03657 | 0.65603/0.99784 |
| 23:00 | 354 | 0.03442/0.00000 | 0.03442 | 0.66774/0.99903 |

Directional reproduction against H1:

- C: predawn model-trails-market pattern reproduced; H1 selected-market Brier 0.02870, winner-P -0.21265.
- F: predawn model-trails-market pattern reproduced; H1 selected-market Brier 0.01732, winner-P -0.13028.
- Historical SHA-256: `115fe6a241ef58855cb4b9ca186cd75cdc273e5697379f788b7f08c86ee36fed`.

## Predawn hourly frontier (untouched holdout)

| Unit | Hour | Dates | Markets/date min-max | Current/selected/market Brier | Current/selected/market winner P |
| --- | ---: | ---: | --- | --- | --- |
| C | 03:00 | 13 | 1-1 | 0.09465/0.08868/0.06210 | 0.11949/0.12194/0.32077 |
| C | 04:00 | 13 | 1-1 | 0.09348/0.08837/0.06061 | 0.12271/0.12314/0.32931 |
| C | 05:00 | 13 | 1-1 | 0.09647/0.09041/0.05828 | 0.11744/0.11855/0.35223 |
| F | 03:00 | 14 | 1-11 | 0.08025/0.07718/0.05970 | 0.22069/0.22070/0.34924 |
| F | 04:00 | 14 | 1-11 | 0.07959/0.07632/0.05893 | 0.22569/0.22540/0.35624 |
| F | 05:00 | 14 | 1-11 | 0.07978/0.07599/0.05849 | 0.22121/0.22511/0.36227 |

## Evening collapse, catch-up, and thresholds

A sustained condition must hold through every later observed evening hour;
confidence-supported catch-up additionally requires the paired fleet-date
interval to support the market rather than only a point crossover.

| Unit | Model | First joint failure | Sustained collapse | First catch-up | Sustained catch-up | Confidence-supported catch-up |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| C | current | — | — | 15 | 15 | 18 |
| C | selected | — | — | 15 | 15 | 16 |
| F | current | — | — | 15 | 15 | 15 |
| F | selected | — | — | 15 | 15 | 15 |

Exact selected-model hour sets:

- C: joint edge none; catch-up 15:00, 16:00, 17:00, 18:00, 19:00, 20:00, 21:00, 22:00, 23:00; confidence-supported catch-up 16:00, 17:00, 18:00, 19:00, 20:00, 21:00, 22:00, 23:00.
- F: joint edge none; catch-up 15:00, 16:00, 17:00, 18:00, 19:00, 20:00, 21:00, 22:00, 23:00; confidence-supported catch-up 15:00, 16:00, 17:00, 18:00, 19:00, 20:00, 21:00, 22:00, 23:00.

| Unit | Series | ≥40% | ≥50% | ≥80% | ≥90% |
| --- | --- | ---: | ---: | ---: | ---: |
| C | current | 15 | 15 | 22 | — |
| C | selected | 15 | 16 | — | — |
| C | market | 15 | 15 | 17 | 18 |
| F | current | 16 | — | — | — |
| F | selected | 22 | — | — | — |
| F | market | 15 | 15 | 18 | 19 |

### Evening hourly scores

| Unit | Hour | Dates | Markets/date min-max | Current/selected/market Brier | Current/selected/market winner P |
| --- | ---: | ---: | --- | --- | --- |
| C | 15:00 | 14 | 1-1 | 0.04638/0.04355/0.02639 | 0.53362/0.49817/0.64808 |
| C | 16:00 | 14 | 1-1 | 0.04395/0.04197/0.01728 | 0.60245/0.51593/0.74441 |
| C | 17:00 | 14 | 1-1 | 0.01862/0.02598/0.00762 | 0.74377/0.61926/0.87063 |
| C | 18:00 | 14 | 1-1 | 0.02497/0.02779/0.00047 | 0.73476/0.62012/0.96811 |
| C | 19:00 | 14 | 1-1 | 0.03072/0.02705/0.00045 | 0.75943/0.64198/0.98520 |
| C | 20:00 | 14 | 1-1 | 0.03673/0.02656/0.00000 | 0.77859/0.65726/0.99825 |
| C | 21:00 | 14 | 1-1 | 0.03673/0.02606/0.00000 | 0.77909/0.66245/0.99909 |
| C | 22:00 | 13 | 1-1 | 0.02593/0.02553/0.00000 | 0.83825/0.67030/0.99927 |
| C | 23:00 | 13 | 1-1 | 0.02578/0.02493/0.00000 | 0.83887/0.67485/0.99938 |
| F | 15:00 | 15 | 1-11 | 0.06138/0.05888/0.04276 | 0.38651/0.37441/0.53267 |
| F | 16:00 | 15 | 1-11 | 0.05310/0.05321/0.03435 | 0.45729/0.42828/0.63620 |
| F | 17:00 | 15 | 1-11 | 0.05340/0.05056/0.02333 | 0.47663/0.46545/0.76188 |
| F | 18:00 | 15 | 1-11 | 0.05406/0.04938/0.01627 | 0.47913/0.48136/0.84761 |
| F | 19:00 | 15 | 1-11 | 0.05120/0.04772/0.00428 | 0.49876/0.48093/0.94462 |
| F | 20:00 | 15 | 1-11 | 0.05631/0.05479/0.00215 | 0.46090/0.43283/0.97509 |
| F | 21:00 | 15 | 1-11 | 0.06355/0.06248/0.00009 | 0.42376/0.39335/0.99507 |
| F | 22:00 | 14 | 1-11 | 0.05821/0.05845/0.00002 | 0.45676/0.41033/0.99804 |
| F | 23:00 | 14 | 1-11 | 0.05720/0.05788/0.00000 | 0.44736/0.40300/0.99911 |

## Tune-to-holdout selection check

Tune is exploratory selection context. A tune sign that does not repeat
on untouched holdout is not evidence for the selected arm.

| Unit | Slice | Tune/holdout Δ Brier | Tune/holdout Δ log loss | Tune/holdout Δ winner P |
| --- | --- | --- | --- | --- |
| C | all_hours | -0.00228/-0.00270 | -0.00674/-0.00495 | -0.01507/-0.05573 |
| C | predawn_03_05 | -0.00133/-0.00569 | -0.00878/-0.01065 | -0.01538/0.00118 |
| C | evening_15_23 | -0.00057/-0.00165 | 0.00005/0.00081 | -0.01725/-0.11530 |
| F | all_hours | -0.00315/-0.00243 | -0.01106/-0.00856 | 0.00381/-0.01241 |
| F | predawn_03_05 | -0.00681/-0.00297 | -0.02087/-0.01165 | 0.01653/-0.00101 |
| F | evening_15_23 | -0.00206/-0.00173 | -0.00798/-0.00544 | 0.00432/-0.02367 |

## Per-market holdout extremes

Negative selected-minus-market Brier is better. These localize fleet
results; they are not separately selected arms.

| Unit | Slice | Side | Market | Dates | Selected-market Brier Δ | Selected-current Brier Δ |
| --- | --- | --- | --- | ---: | ---: | ---: |
| C | predawn_03_05 | only | toronto | 13 | 0.02870 | -0.00569 |
| C | evening_15_23 | only | toronto | 14 | 0.02334 | -0.00165 |
| C | all_hours | only | toronto | 14 | 0.02239 | -0.00270 |
| F | predawn_03_05 | best | houston | 13 | -0.00123 | -0.00569 |
| F | predawn_03_05 | best | seattle | 12 | 0.00712 | -0.00489 |
| F | predawn_03_05 | worst | denver | 13 | 0.02454 | -0.00071 |
| F | predawn_03_05 | worst | los-angeles | 13 | 0.03236 | -0.01049 |
| F | evening_15_23 | best | seattle | 13 | 0.01603 | -0.00039 |
| F | evening_15_23 | best | austin | 14 | 0.02587 | 0.00246 |
| F | evening_15_23 | worst | atlanta | 13 | 0.05334 | -0.00477 |
| F | evening_15_23 | worst | nyc | 13 | 0.05572 | -0.00603 |
| F | all_hours | best | seattle | 13 | 0.01369 | -0.00280 |
| F | all_hours | best | houston | 14 | 0.01756 | -0.00195 |
| F | all_hours | worst | nyc | 13 | 0.03476 | -0.00334 |
| F | all_hours | worst | dallas | 14 | 0.03776 | -0.00292 |

## Denver 2026-07-19 bounded case

Denver 2026-07-19 is outside both predeclared H1 splits, so this experiment does not manufacture a post-hoc H1 score. The dated taker report localizes cool-tail leakage only as motivation, not evidence about the H1 selected arm.

## Provenance and safety

- Tracked and scratch paths in this section are relative to the bound
  worktree. A `data/` path denotes the same repository-relative location
  within the explicitly supplied ignored, read-only runtime mirror; its exact
  resolved root is bound in the machine artifacts. Ignored `data/` evidence is
  local runtime state and is not assumed to exist in a clean checkout.
- H1 result:
  `scratch/workstation-research-output/workstream_a/h1/ordinal_smoothing_sweep_repaired.json`
- H1 result SHA-256: `0ba6c2567a805615d5488cb062182546ce2729392335852967c89e13fd897ab8`
- H1 corpus: `data/backtest/promotion_corpus.json`
- H1 corpus contract hash:
  `d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f`
- H1 corpus file SHA-256:
  `4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5`
- Tune dates: 2026-06-03, 2026-06-04, 2026-06-05, 2026-06-07, 2026-06-08, 2026-06-09, 2026-06-10, 2026-06-11, 2026-06-12, 2026-06-13, 2026-06-14, 2026-06-15, 2026-06-16, 2026-06-17, 2026-06-19, 2026-06-20, 2026-06-21
- Holdout dates: 2026-06-22, 2026-06-26, 2026-06-27, 2026-06-28, 2026-06-29, 2026-06-30, 2026-07-01, 2026-07-02, 2026-07-03, 2026-07-04, 2026-07-05, 2026-07-07, 2026-07-08, 2026-07-09, 2026-07-10
- Raw caches were opened read-only with fixed streaming bounds; no full
  cache/replay array was loaded, and the identity index is capped at 500000.
- Cache fingerprints, SHA-256 values, reader high-water marks, complete
  panel coverage, and output hashes are preserved in machine artifacts.
- Mirrored `data/` remained read only. No serving, release, promotion,
  artifact, trading, or live state changed.

### Current-replay artifact ledger

All paths are relative to the worktree. These hashes bind the exact machine
outputs used for the numerical claims above.

| Artifact | SHA-256 |
| --- | --- |
| `scratch/workstation-research-output/workstream_a/time_frontier/current_replay_time_frontier.json` | `360feb421b58cffbd0396e244ec5006595d0c94da05b6aae8c6891245ccb0a08` |
| `scratch/workstation-research-output/workstream_a/time_frontier/breakpoints.json` | `6b12a0db0f9cc1101584ed1236e311a0b04db26cd475e7d1dc42c5f623c3e9af` |
| `scratch/workstation-research-output/workstream_a/time_frontier/sharpness_mechanics.json` | `1c7c0ccef0e75b05cc5ee3562d7d2fbd9864a6b1bff37301510bc4ef53c149c4` |
| `scratch/workstation-research-output/workstream_a/time_frontier/complete_panel_coverage.json` | `4ad8f63d6dcf863868420e2ec6fc70157ec4dc702020b4b9929b82e890691a4e` |
| `scratch/workstation-research-output/workstream_a/time_frontier/market_date_metrics.csv` | `a8a0630c54bd88c8d8645660d2cb2403d1bd1ac256ee8f1f0b94e8e69ee84690` |
| `scratch/workstation-research-output/workstream_a/time_frontier/fleet_date_metrics.csv` | `5a171646d61144d42e287764b0a67cfa6965af9941a29f17aa0e55b43a1a8230` |
| `scratch/workstation-research-output/workstream_a/time_frontier/summary_metrics.csv` | `d885cb22ba70d3da4db15fc3c68ce3cec8c3dfd2359842cf2e26bf8bdc67827e` |
| `scratch/workstation-research-output/workstream_a/time_frontier/complete_panel_fleet_date_metrics.csv` | `ae17e8f2556bb5805e041d72ca1286da04e6b1901a85e2778904693ecd27419f` |
| `scratch/workstation-research-output/workstream_a/time_frontier/complete_panel_summary_metrics.csv` | `469e46e3045485964bf803bb1da172a2cc7c864fdfc2dc4da33fd2196fe2d2b9` |
| `scratch/workstation-research-output/workstream_a/time_frontier/integrity_manifest.json` | `89885a7d7da9788f1e337116865a6a9f9aa6b3092e2b1af46a68bb3a531a354d` |

The integrity manifest was generated before this documentation-only
repository-relative path and population-label normalization. Its machine-output
receipts remain exact, but its embedded report-leaf receipt identifies the
pre-normalization Markdown bytes and does not attest this edited report.
