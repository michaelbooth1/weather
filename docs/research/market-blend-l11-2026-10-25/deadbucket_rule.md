# Rule L11-deadbucket (lane L11, 2026-10-25): is the 13-16 dead-bucket mispricing worth money?

Written 2026-10-25 before any dev row of this check is read and before any historical rate is computed.
Research only: no orders, no live-readiness work, International Polymarket venue only. Development window
only (nothing dated after 2026-09-29 is read; no 88a, panel or settlement data for 2026-09-30..10-15).
Code: `weather.calibration.dead_bucket` on branch `claude/market-blend-l11-20261025`, using lane L8's
`weather.model.observed_running_max.running_max_since_midnight` (cherry-picked unchanged from
`claude/mg2-composite-binding-20261025` commit `f3b49fabb`). Nothing below changes after this file's sha256 is
recorded; any change is a dated clarification written before the rows it affects.

Signal (L11 market-blend run, rows `1d9fc6d366170e91d66d67ce4229c663dd590514c83a3582c5cf00290aaa91b7`): the
model-free market + rule-4 floor control beats the market at 13-16, PRIMARY5 R 0.9776 [0.962, 0.989]. The market
keeps pricing buckets already below the observed running high.

## Data availability (listed before this scope was written)

- Order-book and trade tapes for the 11 US markets: none on the workstation for any dev date (only Toronto
  2026-08-10 in `data\inbox\toronto-0810-trace`). The capture-host tapes are not fetched by this lane.
- `data\inbox\cftape-20261017` (counterfactual maker tape from sealed 88a evidence, UTC days 09-25..09-29,
  top-of-book only): NOT used (coordinator ruling: option B skipped).
- Layout `C:\swarm\v3layout` (manifest-checked by the dev scorecard loader): `p_market_yes` per band about
  every 8 minutes, bands, snapshots, labels (`settlement_high`, `winner`), 2026-08-01..09-29, 11 US markets.
- IEM ASOS/METAR (L6's fetch, read-only): `data\research\upstream_obs\obs.parquet` (sha256
  `37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2`), market stations, Aug-Dec 2021-2025 and
  2026-07-30..09-29 (rows on local dates after 2026-09-29 are dropped at read).
- WU daily history (the trainer's label source: `feature_model` takes `max_temp_native` from it):
  `data\wunderground\<station>\daily\daily_summary.csv`, Aug-Sep 2021-2025 rows only. The PIT corpus union
  `621bcd8e…` and its season members carry forecasts, not labels; the trainer's labels are this WU history.
- Usable windows: stage C (now) 2026-08-01..09-29 (57 layout dates); stage A when the US tapes arrive:
  their dates within 2026-08-01..09-29, stated in a dated clarification before any A row is read.

## Definitions

- Markets in scope: the 11 US markets (atlanta KATL, austin KAUS, chicago KORD, dallas KDAL, denver KBKF,
  houston KHOU, los-angeles KLAX, miami KMIA, nyc KLGA, san-francisco KSFO, seattle KSEA), minus the excluded set.
  PRIMARY5 = atlanta, austin, chicago, dallas, denver (secondary pool).
- METAR-only running max R(t): `running_max_since_midnight(None, {"rows": rows}, target_date, tz, unit="F",
  cutoff_hour=17, now=t)` (station rows never added: metar_only), where rows are the market station's
  obs.parquet rows with `obs_time` = `valid_utc` and `temp_native` = `tgroup_f` when present else `tmpf`;
  COR rows dropped (as L6).
- Rounded running max H(t) = floor(R(t) + 0.5) (the scorecard's rule-4 rounding).
- Dead bucket at t: a bucket of kind `lte` or `eq` whose upper edge `high` < H(t) (wholly below the running max;
  `gte` buckets are never dead).
- First-dead time of a bucket: the valid time of the first observation at which H first exceeds its upper edge,
  plus 10 minutes (METAR availability, L6's market-station usable rule). Only buckets dead by 16:59 local count.
- Entry window (cutoffs): local 13:00-16:59. Entry instant = max(first-dead + 60 s latency, 13:00 local).
- Settlement-proxy violation (history, day level): WU `max_temp_native` < H(16:59). A superset of bucket-level
  violations (a 1 F shortfall can sit inside a non-dead 2 F bucket), so the rate is conservative.

## 1. Exclusion rule (history only, computed before any dev row)

- Days: Aug-Sep 2021-2025 per market, kept when WU `row_count` >= 20 and >= 12 METAR rows are observed by
  16:59 local; rates per cutoff 13:00, 14:00, 15:00, 16:00 and 16:59 (decisive: 16:59, the largest).
- **X = 2.0%**: a market whose 16:59 day-level violation rate exceeds 2.0% is EXCLUDED. The excluded set is fixed
  from these rates and recorded before any dev row of this check is read.

## 2. Causes (history and dev, same classifier, first match wins)

Each violation (or dev dead bucket that settled YES) is classified by recomputing H with variants:
(a) `tgroup_rounding` — gone when R uses `tmpf` only (whole-degree reported temperature);
(b) `non_routine_max` — gone when R uses routine rows only (minute = the station-year modal minute);
(c) `rounding_and_non_routine` — gone only with both (a) and (b);
(d) `report_timing` — the max-setting observation is in local minute < 60 or after WU's `last_time` (history);
(e) `unexplained` — station or WU data mismatch, none of the above.

## 3. Executable reality — stage A design (runs unchanged when the tapes arrive)

- Per dead bucket in a non-excluded market (one entry per bucket): at the first book snapshot at or after the
  entry instant, buy NO by walking NO asks (direct NO asks, plus 1 - YES bid levels when only YES books exist)
  at prices q with per-share value 1 - q - fee(q) >= 0.005, up to the fill size.
- Fee (EF §10o): taker fee per share = 0.05 * q * (1 - q) on the NO price q; maker fee 0; no rebate counted.
- Fill-size ladder: $5, $25 (primary), $100 per dead bucket; partial fills count at what depth allows.
- Latency: the first tape snapshot >= 60 s after first-dead (first-dead already includes the 10-minute METAR
  availability).
- Mispricing duration: from the entry instant to the first snapshot where no NO ask has value >= 0.005 (or the
  bucket's market closes / 16:59 local), in minutes.
- P&L per bucket: NO wins (bucket not settled YES under WU, layout labels): shares * (1 - q) - fees; bucket
  settled YES: - stake - fees.

## 4. Settlement-proxy risk

- Every dev dead bucket (dead by 16:59) that settled YES under WU (layout `winner`), per market, with its cause
  from section 2. Realised losses are inside the P&L of sections 3 and 5 (labels decide). Also reported: an
  expected-loss variant that replaces each traded bucket-day's realised outcome by the market's historical
  16:59 violation rate (loss = rate x stake per traded bucket).

## 5. Primary metric

- **Stage A primary:** fee- and loss-adjusted $/day at the $25 size, summed over non-excluded markets per date,
  mean over the A window's dates, with a date-clustered bootstrap 95% CI (2,000 draws, seed 20260921).
- Secondary: per-market $/day, per entry hour (13, 14, 15, 16), the fill-size ladder, mispricing duration, PRIMARY5.
- **Stage C (now), GROSS UPPER BOUND — NOT EXECUTABLE:** the same P&L with q = 1 - p_market_yes + 0.01 (an assumed
  2-cent full spread, half paid), entry at the first layout snapshot at or after the entry instant within 13:00-16:59
  local, unlimited depth at every ladder size, labels from the layout; entry only when 1 - q - fee(q) >= 0.005.
  Duration from layout snapshots (about 8-minute resolution). Same $/day statistic and CI over 2026-08-01..09-29.

## Reading rule

- Stage A: **lower CI bound > 0 ⇒ worth an owner decision on a forward paper test; otherwise not worth pursuing.**
- Stage C: an upper bound only. If its $25 upper CI bound <= 0, or its point $/day at $100 < $1, the signal is
  not worth pursuing even before the tapes (A would still run if the tapes arrive, for the record). Otherwise
  "not excluded by the upper bound; A decides". Stage C never supports a money claim.

## (a) Positive control

The dev scorecard's served vs market pooled R 1.774 (all hours) and 1.526 (00-16) must reproduce on the layout
(`loss_atlas.positive_control`), and the rule-4 floor-only control 13-16 PRIMARY5 R 0.9776 (4 dp, L11 market-blend
`floor_only_rows`) must reproduce, before any dead-bucket row is written; L8's running-max tests
(`tests/model/test_high_so_far_parity_shadow.py`) must pass on this branch.

## (b) Comparator fairness

The comparator is not traded at all: value is measured against $0 (no position), with the same floor (METAR-only
running max, rule-4 rounding) for every market and day, no calibration of the market price, the same fee rule,
latency and sizes in every market; labels are the WU settlement proxy that the market itself settles on.

## (c) Targeted loss slice

L11 market-blend rows `1d9fc6d366170e91d66d67ce4229c663dd590514c83a3582c5cf00290aaa91b7` and loss atlas
`535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4`: the 13-16 dead-bucket slice, expected size
0.0224 in R (1 - 0.9776, PRIMARY5 floor-only) and 0.0155 (ALL).

## (d) MDE and clusters

Stage C: 57 date clusters and 11 market clusters (10 or fewer after exclusion); stage A: the A window's dates
(stated in its clarification). The MDE80 in $/day is computed from the date-clustered bootstrap
(`dev_scorecard.mde80`, centred) and reported; reference effect size 0.0224 in R.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md across branches: 29 rows before L11 plus L11's 2 market-blend rows = 31 rows, 21 of type K;
this check adds 1 K row (dead-bucket NO taker): K candidate 22 on 2026-07-31..09-29.
