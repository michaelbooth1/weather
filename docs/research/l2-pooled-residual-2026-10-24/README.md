# L2 pooled residual model — dated research record (2026-10-24, in progress)

Status: research record, not canonical. The canonical findings entry is held until the fair
comparisons (rule amendment 2) and the dev-window test against served (amendment 3) have verdicts;
it will then go in as EF §10z (coordinator, 2026-10-24).

- Code: `weather.calibration.pooled_residual_model` on `claude/pooled-residual-model-20261024`.
- Rule: `rule.md` here, byte-identical to `C:\t\l2\rule.md` at the time of each result
  (original sha256 `e2649f16…bd31`; amendment 1 `6dac6419…f499`; amendment 2 `1a656639…6c28`;
  amendment 3 `09f77d4e…760e`).
- `report.md`: the original decision under amendment 1. **The comparator is raw R0** (the trainer's
  validation HGB blended 0.8 with climatology, with no hard floor and no calibration), which is
  known to be unfair: serving applies both. On that comparator P3 wins by −1.968 nats at 07-12
  [−2.168, −1.786], but raw R0 is worse than its own climatology baseline, and a floored
  bias-corrected forecast alone scores about 2.4 on Atlanta (lane L3). Do not cite this figure as a
  gain over serving. It is not edge: no market price is scored.
- Pending: P3 vs L3 OLS + floor and vs bias-corrected forecast + floor; the unpooled U0 arm; the
  dev scorecard against the served vector.
