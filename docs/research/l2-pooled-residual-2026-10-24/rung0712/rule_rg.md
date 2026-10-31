# L2 rung 07-12 R-G pre-registration (trajectory and floor features in the 07-12 pool) — PROPOSAL, NOT RUN

Written 2026-10-25 after R-F (rule cca30734..., result aa88b7e9...) and before any R-G feature, row or score exists.
Approved only as "proposal and rule first; tell me before running": nothing below runs until the coordinator says so.
Development evidence only; no edge claim; nothing after 2026-09-29; nothing touches MG-2 or L8's branch.

## Features (all capture-time, METAR-only, from the same latest-snapshot-at-or-before rule as P3d_N_fix)

Per row at cutoff hour h (07..12), one function `trajectory_features(rows, capture_time, tz)` over METAR reports
with observation time <= capture time. Dev rows: the snapshot's own captured METAR rows. Training rows (2021-25,
the P3d_N training records, which hold no per-report rows): the same function on lane L6's IEM market-station
parquet `data/research/upstream_obs/obs.parquet` (sha256 37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2,
role = market, already used for Clarification 3 (c)) at the record's own cutoff time; 2026 rows of that parquet are
read only by the parity gate, only at or before each capture time, never after 2026-09-29 local:

- **trend3:** OLS slope in F per hour of the last 3 METAR temperatures (T-group precision when present, else whole),
  requiring all 3 within the last 3 h; clipped to [-10, +10]; missing otherwise (the HGB handles missing; the OLS
  baseline imputes 0 and adds a missing indicator).
- **overnight_min:** minimum METAR temperature from local midnight to capture time, WU whole F half_up as in
  Clarification 3 (c); amplitude feature **amp = nbm_mean - overnight_min**.
- **path_gap:** running max (P3d_N_fix's high_so_far) minus the NBM-implied path value at the capture time,
  path(t) = overnight_min + amp * s(market, month, local hour of t), where s is the mean diurnal fraction
  (T_t - Tmin) / (Tmax - Tmin) over the 2021-25 IEM market rows (same parquet) of that market and month (hours with Tmax - Tmin < 2
  F excluded). No NBM hourly path is used: the corpus has the 07Z daily max only (EF section 10l); an NBS/NBH hourly
  path (lane L12) would be a separate rung.

## Arms (identical rows, the R-A population)

- **B_G (simple baseline, first):** B_N's OLS (use_hgb=False, ConstantScale) with trend3 (+ missing indicator),
  amp, path_gap added to [1, g, max(g, 0)]. Same kernel, floor, climatology mix.
- **P3d_G:** P3d_N_fix with the three features added to the HGB residual and scale models (OLS part unchanged).
- **blend_l6_G:** R-F's walk-forward per-hour blend with P3d_G in place of P3d_N_fix and L6 as base (same frozen L6,
  same sha checks).

## Gates, in order (each stops the rung if it fails)

1. **Parity gate (before any score, inputs only):** on the dev 07-12 rows, the function on captured METAR vs on the
   IEM parquet at the same capture time: overnight_min exact on >= 95% of rows and trend3 within 1 F/h on >= 90%
   (L3 row 30 measured current-temp exact 78%, 99.5% excluding reports < 10 min old); IEM coverage of the training
   rows (>= 3 reports in the 3 h before cutoff) >= 95%. Any miss: refused and reported, nothing scored.
2. **LOYO (2021-25, blocked by year):** B_G - B_N Brier date-clustered upper < 0, else STOP (R-A rule: the baseline
   must beat the simple baseline first).
3. **Dev (PRIMARY: ALL, covered, 07-12, date-clustered):** B_G - B_N upper < 0, else STOP. Then P3d_G - P3d_N_fix
   and P3d_G - B_G reported; P3d_G proceeds only if P3d_G - P3d_N_fix upper < 0.
4. **Incumbent:** P3d_G vs L6 and blend_l6_G vs L6, read as R-F (WIN if upper < 0 and no hour lower > 0; HARM if
   lower > 0; else NULL), with R-F's controls (L6 sha checks, MG-1 control 0.012, R-D and R-F reproduced to 1e-9).
   blend_l6_G vs R-F's blend_l6 reported only.

## Population, intervals

Same as R-A / R-D / R-F: scored 08-15..09-29, 43 dates, 473 market-days; crossed and date-clustered 95%, 2,000 draws,
seed 20260921; dR = mean_cell(Brier_arm - Brier_ref) / mean_cell(Brier_market). Per hour h07..h12, PRIMARY5 and per
market descriptive. Caveat carried from R-F: L6's frozen coefficients are in-sample on this window.

## Multiplicity

Each of B_G, P3d_G, blend_l6_G is a K row in the dev-window ledger (three candidates), rows added as pending before
scoring. If a blend WINS vs L6, L2 drafts (does not apply) the MG-2 Clarification, binding and L8 re-run plan as in R-F.
