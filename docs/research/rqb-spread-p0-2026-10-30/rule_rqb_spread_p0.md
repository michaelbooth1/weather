# R-Q B captured GEFS spread market-residual P0 rule (ledger row 88)

Status: pre-declared before any computation (2026-10-30, lane L3). Evidence class: dev-window kill-only P0
screen. It is its own arm with its own K. It is not pooled with the marine P0 (row 87) or the MR sweep (row 78).
Only a survivor earns the ap5 recorder question. Nothing here is a release, serving, capture or scheduling
decision.

## 1. Machinery

The rule is identical to `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`
(sha256 `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), sections 1-5, except where this
file says otherwise.

- Data:
  - layout `C:/swarm/v3layout`;
  - burn-in 2026-08-01..08-14;
  - scored dates 2026-08-15..09-29;
  - e = y - m.
- Signal:
  - market moments with the sigma^2 floor 0.25;
  - the exponential tilt;
  - type S band signal s_b = g_z * ((z_b - mu_m)^2 - sigma_m^2) / sigma_m^2, where g_z is z-scored within market
    over the covered fit snapshots.
- Placebo and bootstrap:
  - the calibration-matched disagreement placebo (`market_blend.placebo_vector`, derangement within
    (market, hour), J = 20, seeds 20260921+j);
  - Delta = rho_c - mean rho_pl;
  - B = 10,000 date-cluster draws with seed 20261024;
  - one-sided p.
- Thresholds and outputs:
  - UNTESTABLE below 20 covered dates or 1,000 snapshots;
  - per-date rows with the six sufficient sums.

## 2. Population

The sweep's fit and score tables. That is every layout market except toronto, as in the sweep. Only snapshots
whose local hour is 00..06 inclusive are used. No data after 2026-09-29 is read.

## 3. Candidate (K = 1)

| id | value | type | sign | mechanism |
| --- | --- | --- | --- | --- |
| GEFS-SPREAD80 | captured `global_ensemble.day_member_high_spread_80` (the p90 - p10 of the member daily highs on the serve grid) | S | + | wider member disagreement means the market's distribution is too narrow early in the day |

- `day_mean_member_spread` is not tested. It is a mean of hourly member spreads, not the spread of the member
  daily highs that R-Q B is about.
- The value comes from the captured replay inputs (`data/inbox/replay-inputs-le0929`).
- A snapshot is covered only when the `global_ensemble` source is `ok`, its `fetched_at` is <= `captured_at_utc`,
  and the value is finite.
- EF §10w is not engaged. The dev window 2026-08-15..09-29 contains no DST change.

## 4. Decision

- With K = 1, BH at q = 0.10 reduces to p <= 0.10.
- GEFS-SPREAD80 SURVIVES iff all three hold:
  - it is testable;
  - p <= 0.10;
  - the Delta 95% lower bound is > 0.
- Otherwise it is a KILL, or UNTESTABLE if it is untestable.
- Only for a survivor:
  - the w = 0 identity control;
  - then the sweep's w gate in a new block 00-06 (hours 0..6), with c_pl,0 as the placebo.
- One run. Outputs:
  - a receipt JSON;
  - per-date rows JSONL plus per-market per-date rows;
  - the extracted capture-time feature file.
