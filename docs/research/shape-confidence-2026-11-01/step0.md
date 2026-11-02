# L47 step 0: what the 07-12 surplus two or more bands from the winner is made of (2026-11-01)

**SELECTION EVIDENCE, descriptive.** Dated research evidence, not instruction. Inputs: the R-H atlas population only
(layout 2026-08-01..09-29, 57 dates, 626 market-days; capture-time market `p_market_yes`; L6 part `07a67425…`,
nowcasts `3806687c…`, P3d_N_fix emissions `cd0034b9…` and `abc43507…`; layout manifest `4d53fdbd…`). Nothing dated
after 2026-09-29 was opened. No new candidate was scored. Ledger row: TBD (coordinator assigns).

Code: `weather.calibration.shape_confidence_l47 step0` (commit `e9a08249f03e0e2d395de37490f4f1c7fc29ba9e`) and
`weather.calibration.shape_confidence_l47_order` (commit `ca919dec5deb5109c7d58f29b14df54c39317227`), both run on the
WS through `scripts/ops/workstation_heavy.ps1 -Kind weather_heavy -Queue`, exit 0. Outputs (WS, not in git):
`C:\t\L47\step0\step0.json` sha256 `ad5802934ea44fc75280355e22437e4b425ec03caadff83b5d85ff07f1cd2df5`,
`C:\t\L47\step0\step0b.json` sha256 `04e1ce8e95e21905b641e1c6c7a22a74ff6a9b50e2602da6a41d44af702aba11`.
Reproduction: the R-H 07-12 position masses (market, L6, P3d) match `rh_atlas.json` `ff7ee231…` to 4 dp.

**Master ruling 2026-11-01:**
- 2a (FLOOR_MIX_CLIM) is PARKED, no LOYO: `C:\archive\ruled-out\l47-floor-mix-clim-parked\`.
- Lever 2 (conditional scale / tail shape) is PARKED at an upper bound of 0.0007 pooled:
  `C:\archive\ruled-out\l47-scale-shape-parked\`.
- The centre-bias step 0 is a GO: `centre_step0.md`.

## Method

Each snapshot's distribution is summarised by its mean, sd and skew in band-index units on its own bands.
Gaussian stand-ins (band k = [k-0.5, k+0.5], open end bands, rule-4 floor mask, renormalised) replace the arm
step by step. Order A goes width first: market, Gaussian market (S2), global width ×c (S3m), the arm's own
width at the market centre (S4), the arm's centre (S5), the arm (S6). Order B goes centre first: S2, the arm's
centre at the market's width (C3), global width (C3m), S5, S6. Predictability = terciles of the market's own sd
(cut points 0.766 / 0.916 bands; T0 = sharpest). Brier excesses are cell-mean, date-clustered 95% intervals.

## Results (07-12, 28,754 common snapshots)

| | P3d_N_fix | L6 |
| --- | --- | --- |
| Excess vs market | +0.0101 [+0.0080, +0.0123] | +0.0081 [+0.0062, +0.0101] |
| Surplus mass <= -2 / >= +2 bands | +0.040 / +0.082 | +0.032 / +0.054 |
| Market non-Gaussian peak (S2 - market) | +0.0018 [+0.0008, +0.0028] | same |
| Centre (width-first / centre-first) | +0.0049 / +0.0077 | +0.0048 / +0.0052 |
| Width (width-first / centre-first) | +0.0038 / +0.0010 | +0.0014 / +0.0010 |
| Arm shape vs same-moment Gaussian | -0.0004 | +0.0001 |
| Global width factor c (sd ratio, pooled) | 1.27 | 1.18 |
| Slope of arm sd on market sd | 0.59 | 0.98 |
| Mean centre offset (arm - market) | +0.13 bands (T2 +0.21) | +0.06 |

- **(i) Global width.** A global 1.27× sd at the market centre keeps ±1 mass equal and gives winner mass 0.316
  (arm 0.293, market 0.415). It has no above-side asymmetry and carries +0.0049 of +0.0101. After the arm's
  centre is applied, global width adds only +0.0008.
- **(ii) Day-specific scale.** P3d's width under-responds to the day. The arm/market sd ratio is 1.47 / 1.31 /
  1.13 from T0 to T2. Mean |error| / sd is flat for the market (0.63 / 0.68 / 0.68) but not for P3d (0.58 /
  0.66 / 0.83). P3d's excess is largest on predictable days: T0 +0.0115, T1 +0.0086, T2 +0.0079. Swapping the
  arm's day-specific width for the global multiple moves Brier by only +0.0005..+0.0015 (T0),
  -0.0007..-0.0010 (T2) and +0.0002..+0.0007 (pooled). L6's width tracks the market's (slope 0.98).
- **(iii) Skew.** None. The above-side surplus comes from a warm centre offset. A Gaussian at the arm's own mean
  and sd reproduces it (+0.045 below, +0.091 above). The arm's actual shape is no worse than that Gaussian.

## Reading

The largest component under either order is the centre: about 50-75% of P3d's excess and about 60% of L6's.
Next comes the market's non-Gaussian peak (at most +0.0018), then width, which is mostly global; day-specific
scale is at most about +0.0007 pooled; skew is about 0. The X27 / R-I reading that about two thirds of P3d's
excess survives re-centring and tempering re-centred by whole bands to the market median. A continuous mean
shift attributes much more to the centre. Once the centre is applied, width barely matters, as R-I found for
tempering after re-centring.

Caveats:
- The centre component is measured with the market's own mean. It is an attribution, not a lever.
- The Gaussian sd is not Sheppard-corrected (discrete variance ≈ σ² + 1/12), so the market-peak term is an upper
  bound.
- Moments use band index as a point value, which understates the open end bands.
- At 13-16 (P3d only, reported in `step0.json`), the arm's own peaked, floor-skewed shape helps by -0.0009
  against a same-moment Gaussian.
