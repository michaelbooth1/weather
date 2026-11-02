# K row 112, G0 result: PASS (marginal, T14 only) (2026-11-01)

**Descriptive, no model.**
- Rule `rule_x36_trailing_final.md` sha256 `032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2`, frozen and
  pushed at `76bb74911117c8832c2318b7038cec606fd38205` before this run.
- Module `x36_trailing_g0.py` `e42afef76299b5fbb59b6fa76aa6f8223e8a7895b2e793e1be9efe0d15ee4e2f`, with base `x36_v5.py`
  `7804d11d…`.
- Output `C:\t\L47b\g0.json` sha256 `5416dd9512f486da317ed310f9239c434aa3b2d4706ff9428e868edfbc9b2e39`.
- Rows: 1,452 (11 markets × 2026-01-15..05-26). No new fetch, and nothing dated >= 2026-05-27.

## Pooled

| Arm | MAE °F | Mean error °F |
| --- | ---: | ---: |
| RAW (NBP 07Z mean) | 2.359 | +0.906 |
| SEAS (− training-era all-season mean) | 2.415 | +0.854 |
| T7 (− trailing 7-day bias) | 2.307 | +0.187 |
| T14 (− trailing 14-day bias) | 2.282 | +0.171 |

Paired ΔMAE, 95% date bootstrap:
- **T14 − RAW: −0.077 [−0.153, −0.005] (passes the G0 line)**
- T7 − RAW: −0.052 [−0.134, +0.034] (does not)
- T14 − SEAS: −0.133 [−0.207, −0.063]
- T7 − SEAS: −0.108 [−0.186, −0.028]

The training-era seasonal baseline is worse than RAW: it does not transfer to 2026.

## Where it helps and where it hurts

| Market | MAE RAW / SEAS / T7 / T14 | ME RAW / T7 / T14 |
| --- | --- | --- |
| Atlanta | 2.20 / 2.20 / 2.42 / 2.29 | +0.50 / +0.00 / −0.05 |
| Austin | 2.14 / 2.07 / 2.23 / 2.17 | +1.06 / +0.13 / +0.10 |
| Chicago | 2.82 / 2.90 / 3.05 / 3.11 | +0.48 / +0.28 / +0.34 |
| Dallas | 2.55 / 2.46 / 2.32 / 2.28 | +0.95 / +0.05 / +0.08 |
| Denver | 3.31 / 3.59 / 2.69 / 2.69 | +2.23 / +0.70 / +0.51 |
| Houston | 1.80 / 1.83 / 1.72 / 1.70 | +0.77 / +0.03 / +0.06 |
| Los Angeles | 2.89 / 3.05 / 2.76 / 2.66 | +1.66 / +0.72 / +0.68 |
| Miami | 1.38 / 1.44 / 1.40 / 1.38 | +0.76 / +0.02 / +0.03 |
| NYC | 3.22 / 3.31 / 3.02 / 2.98 | +0.25 / +0.02 / +0.04 |
| San Francisco | 2.02 / 2.06 / 2.06 / 2.11 | +0.61 / −0.04 / +0.02 |
| Seattle | 1.64 / 1.66 / 1.71 / 1.71 | +0.68 / +0.14 / +0.08 |

| Month (pooled) | MAE RAW / SEAS / T7 / T14 | ME RAW / T7 / T14 |
| --- | --- | --- |
| Jan (15-31) | 2.34 / 2.39 / 2.56 / 2.48 | −0.45 / −0.11 / +0.04 |
| Feb | 1.93 / 2.01 / 1.92 / 1.99 | +0.26 / +0.22 / +0.32 |
| Mar | 3.09 / 3.17 / 2.90 / 2.84 | +1.52 / +0.62 / +0.59 |
| Apr | 2.31 / 2.34 / 2.08 / 2.00 | +1.51 / +0.19 / +0.15 |
| May (mostly v5.0) | 2.02 / 2.06 / 2.12 / 2.13 | +1.06 / −0.18 / −0.37 |

## Reading

- The trailing correction removes most of the mean error: pooled +0.91 → +0.17. Every market's |ME| falls.
- The MAE gain is small and concentrated. It comes mostly from Denver, Los Angeles, Dallas and NYC, in March and
  April, the months and markets with a persistent bias.
- MAE gets worse in Atlanta, Chicago, Austin, SF and Seattle, and in Jan and May. Only **24 of 60** market-months
  improve under T14 (26 under T7).
- In May, the version-change month that matters most for serving, T14 over-corrects (ME −0.37) and its MAE is
  worse than RAW.
- The noise a 14-day mean adds is comparable to the bias it removes, except where the bias is large and
  persistent. A shrunken λ < 1, which G1 selects, is the natural response, and the G1 grid already holds it.

G0 passes by its frozen line, so G1 is allowed. It is marginal: the pooled upper bound is −0.005, and the T7
interval spans 0. The X30 caveat applies with extra force. Most of the gain is an intercept-like bias removal in a
few market-months.
