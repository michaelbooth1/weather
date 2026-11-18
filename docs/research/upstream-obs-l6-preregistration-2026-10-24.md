# Lane L6 pre-declared rule: upstream and nearby observation features at 07-12

Written 2026-10-24 before any score or validation metric of this lane exists. Development evidence only
(dates <= 2026-09-29, previously read by earlier lanes). Code: branch `claude/upstream-obs-screen-20261024`,
`weather.calibration.upstream_obs_screen` (features, LOYO, nowcasts) and
`weather.reporting.scorecards.free_source_candidates.l6_stack` / `l6_upstream_candidate` / `l6_own_candidate`.
Nothing below is changed after this file's sha256 is recorded.

## Data

- IEM ASOS/AWOS (`asos.py`, free, serial), fetched by `weather.sources.free_screens.iem_upstream` into
  `data\research\upstream_obs\` with per-request receipts: the 11 US market stations plus a ring of 50-150 km
  per market (per 45 deg sector the station nearest 90 km, plus up to 3 extra in the prevailing morning
  upwind arc +- 60 deg), online and archived since 2021-06-01. Selection was fixed from station metadata
  and the market station's own Aug-Sep 2021-2025 07-12 wind (`selection.json`), before any feature or score.
- Windows: Aug-Dec 2021-2025 and 2026-07-30 .. local midnight ending 2026-09-29. Nothing later.

## Features (as of cutoff t; observation instant, station-local date)

- Usable: market station row from valid + 10 min, ring row from valid + 20 min; "latest" must be <= 90 min
  old; 3-hour-ago value = latest usable at t - 3 h; running max R over the market station's same-local-date
  usable rows (and >= current T); previous-day max from the complete previous local date. COR rows dropped.
- OWN (twin): local hour, day of year, station (categorical), T, Td, R, T - R, 3 h T and Td tendency, wind
  u/v/speed, cover, log ceiling, previous-day max, previous-day max - T.
- UPSTREAM (added for the candidate): ring count; ring-mean T - T_s, Td - Td_s, cover, log ceiling, 3 h
  tendency difference; flow = vector mean of station and ring winds; flow-upwind weighted (w = max(0,
  cos(flow_from - bearing))) T - T_s, Td - Td_s, cover, log ceiling, tendency difference; advection proxy
  adv = upwind dT x flow speed (km/h) / weighted distance (F/h); prevailing-upwind group mean dT, dTd, cover.
- History cutoffs: local H:30 for H = 7..12. Serve cutoffs: each layout snapshot's `captured_at_utc`
  (snapshots with local hour 7..12 only).

## Nowcast model (fixed a priori)

- y = dmax - R, dmax = half-up max of routine non-COR market-station rows (T-group F, else tmpf; routine =
  station-year modal minute), >= 20 rows. sklearn HistGradientBoostingRegressor(max_iter 300, learning_rate
  0.05, max_leaf_nodes 15, min_samples_leaf 40, l2 1.0, random_state 0), station categorical, pooled hours
  7-12. Two models: OWN, OWN + UPSTREAM. Nowcast N = R + y_hat.
- Validation (reported, not the verdict): blocked leave-one-year-out over 2021-2025, Aug-Sep (primary) and
  Oct-Dec (secondary): MSE(up) - MSE(own) per hour and pooled 07-12 with date-clustered bootstrap 95% CIs
  (2,000 draws, seed 20260921), per station and per year.
- Serve models: refit on all Aug-Sep 2021-2025 rows (no 2026 data, no labels).

## Candidate and controls on the C dev scorecard

- Candidate `l6_upstream_stack`: MG-1 with mu = v2_mean + a_h + b_h (N_up - v2_mean) at local hours 07-12;
  per fold (training snapshots only) and hour h: OLS of (y - v2_mean) on (N - v2_mean), y = settled band
  centre (eq mid, lte high, gte low), b clipped to [0, 1] (a refitted), >= 200 snapshots else MG-1;
  sigma = max(v2_stddev, 1); floor as MG-1. Elsewhere and without N: MG-1 exactly.
- Twin `l6_own_stack`: identical with N_own (attribution control: what upstream adds).
- Control of record: `control_mg1` (MG-1, `r-t5-inc-c1`).
- Runs (through `scripts\ops\workstation_heavy.ps1`, layout `C:\swarm\v3layout`, 2026-08-01..09-29,
  default folds, `--hourly`): (1) candidate vs `control_mg1`; (2) candidate vs `l6_own_stack`;
  (3) twin vs `control_mg1` (reported).

## Decision (headline: pooled `ALL` row, block 07-12)

- **KEEP** only if all three 95% crossed date x market intervals exclude zero on the improving side:
  candidate - served, candidate - MG-1, and candidate - twin. Otherwise **KILL** (upstream not shown).
- If candidate - MG-1 and twin - MG-1 exclude zero but candidate - twin does not, the verdict is still
  KILL for upstream; the own-observation stack is reported as a separate development lead.
- Reported, not decisive: per-hour rows h07..h12, date-clustered intervals, per-market rows, other blocks
  (identical to MG-1 by construction), the LOYO table, MDE80. 11 market clusters: unpowered.
- One decided rule. No feature, parameter, station, hour window or threshold changes after the sha is
  recorded; a code defect fix that changes no rule text is recorded as such.
