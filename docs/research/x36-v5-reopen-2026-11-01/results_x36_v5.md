# L47 X36 reopen test on NBM v5.0: results (C row 111, 2026-11-01)

**Evidence, descriptive. Not an edge claim and not a model result.**
- Rule `rule_x36_v5.md` sha256 `ed2f5af7a15240f6a2c93c26df889b1f225876f28d8351fc3d8ac1a6e869037a`, frozen and pushed at
  `d2542fbdbc010955431fe4983f9d19eca066f8ab` before any label read.
- Module `tools/research/x36_v5_reopen/x36_v5.py` sha256 `7804d11d25323a31a83bed0393af297de57941932ed7fd77f8fd3771bacac4d7`, unchanged since that commit.
- Nothing dated >= 2026-05-27 was read.

## Run receipts (WS, direct light runs, outputs not in git)

| Step | Receipt |
| --- | --- |
| Fetch | L9 fetcher `1f9a2724…`, launcher `launch_fetch_v2.ps1` `e5324219…`, PID 62788 / child 62356, 143 dates, 3,780 requests, 199.7 MB, exit clean, stderr empty, RSS about 32 MB. Blocks `C:\t\L47b\nbp07_probe\nbp_station_blocks.jsonl` sha256 `e4a13875fc5d3d7246943bf9e808404aad74f9f3f3850e033f320f39d8244e9b` (146 dates). |
| Corpus | `C:\t\L47b\corpus_2026.jsonl` sha256 `d59718a746a68d4745895623bae7760d99d95da647228fa3f8b7e389c8810acf`, 1,606 rows, parser v2. |
| Count (rule 16) | `C:\t\L47b\count.json` sha256 `6605f57bcd488c1111398a9dd415611f3624815841001598a0666783dd3f2cbe`. **PASS: 1,606 / 1,606 matched**: every market has 146 / 146 NBP rows and WU labels, all labels are °F, and no NBP row is missing. Each market has v4.3 on 125 dates (Jan 31, Feb 28, Mar 31, Apr 30, May 1-5) and v5.0 on 21 dates (May 6-26). |
| Fit | `C:\t\L47b\fit.json` sha256 `6fe1f1239d106d7b9b7500480b392f991e49ab75551e2af612cb2908fe52c82e`. Training-era context comes from L9's corpus `1ae4bf52…`: 7,422 pairs, 2021-25, Aug-Sep and Oct-Dec. |

## Decision line (as frozen): REOPEN

d = NBP 07Z mean − WU high (°F). Intervals are 95% date bootstraps (2000 draws, seed 20261024).

Two markets have |mean d| > 1 °F with an interval excluding 0:
- **Denver +1.86 [+1.13, +2.60]**
- **Los Angeles +1.32 [+0.73, +1.95]**

So X36 reopens by its own condition as frozen. Read disclosure 1 below before acting on it.

## Per market (2026-01-01..05-26)

| Market | All dates | Jan | Feb | Mar | Apr | May | v4.3 block (125) | v5.0 block (21) | Train Aug-Sep (v4.x) | Train Oct-Dec (v4.x) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Atlanta | +0.47 [-0.07, +1.04] | +0.13 | +0.14 | -0.16 | +1.77 | +0.46 | +0.50 [-0.14, +1.13] | +0.29 [-0.71, +1.29] | +0.90 | -0.36 |
| Austin | +0.97 [+0.47, +1.43] | -1.13 | +0.93 | +1.39 | +2.00 | +1.81 | +0.81 [+0.28, +1.33] | +1.90 [+1.05, +2.95] | +0.23 | +0.76 |
| Chicago | +0.17 [-0.63, +0.89] | -2.03 | -1.25 | +0.90 | +2.03 | +1.31 | -0.11 [-0.98, +0.77] | +1.86 [+1.10, +2.57] | +0.43 | -0.78 |
| Dallas | +0.81 [+0.24, +1.34] | -1.16 | +0.18 | +2.68 | +1.47 | +0.85 | +0.80 [+0.20, +1.42] | +0.86 [-0.43, +2.19] | +0.75 | +0.27 |
| **Denver** | **+1.86 [+1.13, +2.60]** | -0.55 | +2.86 | +3.77 | +2.87 | +0.23 | +2.09 [+1.28, +2.95] | +0.52 [-0.24, +1.33] | +0.33 | -1.05 |
| Houston | +0.72 [+0.31, +1.10] | -0.58 | +0.64 | +1.26 | +1.60 | +0.69 | +0.74 [+0.32, +1.17] | +0.62 [-0.43, +1.71] | +0.18 | -0.26 |
| **Los Angeles** | **+1.32 [+0.73, +1.95]** | -0.97 | +0.96 | +5.48 | -0.23 | +1.27 | +1.28 [+0.62, +1.99] | +1.57 [+0.57, +2.71] | -0.13 | -0.57 |
| Miami | +0.73 [+0.46, +1.02] | +0.65 | +0.29 | +1.03 | +0.93 | +0.73 | +0.78 [+0.49, +1.08] | +0.43 [-0.33, +1.05] | -0.54 | +0.24 |
| NYC | +0.08 [-0.62, +0.75] | -1.29 | -2.07 | +0.42 | +2.57 | +0.77 | +0.02 [-0.73, +0.82] | +0.43 [-0.48, +1.33] | +0.15 | -1.02 |
| San Francisco | +0.39 [-0.05, +0.84] | +0.13 | -0.04 | -0.23 | +0.63 | +1.62 | +0.18 [-0.29, +0.66] | +1.62 [+0.33, +2.95] | +1.47 | +0.40 |
| Seattle | +0.61 [+0.25, +1.01] | -0.06 | +0.18 | +0.23 | +1.00 | +1.88 | +0.46 [+0.08, +0.85] | +1.52 [+0.29, +3.05] | +0.61 | -0.10 |
| **Pooled** | **+0.74 [+0.47, +1.04]** | **-0.62** | **+0.26** | **+1.52** | **+1.51** | **+1.06** | **+0.69 [+0.39, +1.02]** | **+1.06 [+0.68, +1.44]** | +0.40 (market mean) | -0.22 (market mean) |

Within May, pooled: v4.3 (5 dates) +1.05 [+0.24, +1.87]; v5.0 (21 dates) +1.06 [+0.68, +1.44]. **The v5.0 − v4.3
contrast is +0.00 pooled.** Per market it ranges from -1.88 (Seattle) to +2.86 (Chicago), on 5 v4.3 dates, so it is
descriptive only. Training-era pooled by version (Aug-Dec, market means): v4.0 -0.07, v4.1 +0.00, v4.2 +0.06, v4.3
(2025) +0.35.

## Season control (canon, no new reads) and which reading holds

| Piece | Version | Season | Raw NBM − outcome | Source |
| --- | --- | --- | --- | --- |
| 2021-25 Aug-Sep | v4.0-v4.3 | Aug-Sep | X36 fitted residual shifts within ±0.4 °F. Raw NBP d, market mean +0.40 (this run's context table) | Register X36; `fit.json` |
| 2026 dev Aug-Sep | v5.0 | Aug-Sep | NBM v2 mean +0.74, p50 +0.83 (MG-1 +0.84) | Morning-loss Analysis 5 |
| 2026 Jan-Apr | v4.3 | winter-spring | Pooled +0.67 (Jan -0.62, Feb +0.26, Mar +1.52, Apr +1.51) | this run |
| 2026 May | v4.3 (5 dates) vs v5.0 (21) | late spring | +1.05 vs +1.06 | this run |

**Reading that holds: a 2026 / year effect, not a version effect.**
- v4.3 in 2026 is already warm: pooled +0.69 on its 125 dates, +1.5 in Mar-Apr.
- Within May, v5.0 is no warmer than v4.3 (contrast +0.00).
- The version-effect pattern (v4.3 Jan-Apr not warm, May v5.0 warm) is not seen.

This run cannot separate a year effect from a slow drift across versions (training-era v4.0 -0.07 → v4.3 +0.35).
Raw d is also strongly seasonal within one version:
- 2026 v4.3 runs from -0.62 in Jan to +1.5 in Mar-Apr;
- training-era v4.x per-market Oct-Dec values reach -1.05 (Denver) and -1.02 (NYC);
- SF Aug-Sep reaches +1.47.

The 2026 Aug-Sep dev figure (+0.74) is about 0.3 °F above the training-era Aug-Sep raw figure (+0.40). That gap is
smaller than the month-to-month swings above.

## Disclosure 1 decides how to read the REOPEN

X36's quantity is a fitted shift on the P3d_N_fix residual. That model carries day-of-year and the NBM anchor, so it
absorbs the training-era raw NBM bias, including its season.
- The raw criterion here would also fire inside the v4.x training era: Denver Oct-Dec -1.05 [-1.37, -0.68] and NYC
  Oct-Dec -1.02 [-1.24, -0.80] already exceed ±1 °F.
- The two firing markets are driven by v4.3 months, not by v5.0. Denver's v4.3 block is +2.09 and its v5.0 block
  +0.52. LA's figure is dominated by March (+5.48).

So the literal REOPEN shows that raw NBM bias in 2026 is large, warm and market-specific. It does not show that the
model residual shifts by more than 1 °F, which is what X36 measured. The model was trained on Aug-Dec only and has no
Jan-May coverage. Master should rule whether the reopen stands. The drafted rule (`rule_x36_v5_correction_DRAFT.md`)
tests the residual quantity directly, as an excess over the training-era raw bias, and its gate is unchanged dev.

## Not claimed

Any Brier effect, any edge, that v5.0 is the cause (the evidence points the other way), or anything about Toronto.
