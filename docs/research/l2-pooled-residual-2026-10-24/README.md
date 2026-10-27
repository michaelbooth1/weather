# L2 pooled residual model — dated research record (2026-10-24/25)

Status: research record, not canonical. The canonical entry is EF §10aa (written 2026-10-25 after
both verdicts; §10z is L1, §10ab L3). The MG-2 afternoon-slot pick is L3's single dev read under
`C:\t\mg2\afternoon_pick_rule.md` (sha256 `5898bfb0…`); L2 supplied the serve-parity check
(`C:\t\l2\p3d_serve_parity.md`) and the P3d vectors (`C:\t\l2\p3d_dev\dev_P3d.jsonl`, sha256 `f3b02bf0…`).

- Code: `weather.calibration.pooled_residual_model` on `claude/pooled-residual-model-20261024`.
- Rule: `rule.md` here, byte-identical to `C:\t\l2\rule.md` at the time of each result
  (original sha256 `e2649f16…bd31`; amendment 1 `6dac6419…f499`; amendment 2 `1a656639…6c28`;
  amendment 3 `09f77d4e…760e`; amendment 4 `53ba558b…3a32`).
- `report.md`: the original decision under amendment 1. **The comparator is raw R0** (the trainer's
  validation HGB blended 0.8 with climatology, with no hard floor and no calibration), which is
  known to be unfair: serving applies both. On that comparator P3 wins by −1.968 nats at 07-12
  [−2.168, −1.786], but raw R0 is worse than its own climatology baseline, and a floored
  bias-corrected forecast alone scores about 2.4 on Atlanta (lane L3). Do not cite this figure as a
  gain over serving. It is not edge: no market price is scored.
- `headline_P3.md` (amendment 2, decided 2026-10-24 22:50): on the same 11,550 rows, **P3 beats L3's
  OLS + floor (a) by -0.147 nats at 07-12 [97.5% -0.195, -0.102] and the floored bias-corrected
  forecast (f) by -0.272 [-0.339, -0.211]**; no market worse beyond its CI; crossed intervals also
  exclude 0. Hour 12: -0.159 vs (a), -0.447 vs (f). Pooling is the lever: the unpooled U0 is worse than
  P3 by +0.174 [+0.141, +0.208] and only ties (a). Still model vs model on development years, not edge.
- `headline_P3_dfloor.md`: the same with lane D's floored leaf-20 R0 rows (5 markets) attached:
  P3 - floored R0 -1.995 [-2.258, -1.745]. Our L3 rows equal C:\t\l3\octdec row for row (ols_floor
  max abs diff 0 over 11,550 rows).
- `dev_verdict.md` (amendment 3, **decisive**, 2026-10-25 00:20): on the dev scorecard (2026-08-15..09-29,
  43 dates, 473 market-days, unchanged dev_scorecard via L3's dev-score), positive control passes
  (`dev_served_positive_control.md`: served R 1.774 all, 1.526 00-16). **P3d beats served:** pooled
  07-12 dR -0.210 [date-clustered 95% -0.256, -0.162; crossed -0.357, -0.091], no standard block
  worse; R 1.273 vs served 1.483; hour 12 -0.210; 00-16 -0.151; 13-16 -0.496. U0d also beats served
  (-0.186) but trails P3d. R_candidate stays above 1 in every block: still worse than the market, so
  this is not edge.
- `headline_P3F.md` (amendment 4): the full-year arm on L1's union 621bcd8e... (23 centres, 245,625
  training rows) also beats (a) -0.151 [-0.200, -0.105] and (f) -0.275 [-0.342, -0.216], but adds
  nothing over P3: P3F - P3 -0.004 [-0.014, +0.006] at 07-12.
- Hook and admission tests (7 files) pass through the wrapper: 83 passed, 15 skipped.
- `p3d_serve_parity.md` (2026-10-25, outcome-blind): the MG-2 pick rule's condition 1 for P3d. Capture parity
  holds for high_so_far, current_temp, cutoff and date; **it fails for forecast_high** (Previous Runs lead 1,
  shared with arm A, not in the capture; served forecast differs by MAE 2.26 °F at 13-16). Byte-identical
  to `C:\t\l2\p3d_serve_parity.md`.
- `p3d_n_serve_parity.md` and rule amendment 5 (2026-10-25, outcome-blind, `rule.md` sha256 `b3f017bb…de68`):
  P3d_N, re-specified under pick-rule Clarification 2 (option N) on the captured NBM 07Z mean and L8's
  METAR-only running max; dev vectors `C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl` (sha256 `721ae2cd…031ec`, the
  same 79,403 snapshots). **Serve parity passes**: the 2026 corpus equals the captured mean on every 13-16
  snapshot. Not scored by L2; L3 runs the pick.
