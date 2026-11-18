# Lane L11 rung R-N pre-registration: GEFS 30-member mean daily max as a CENTRE input at 07-12 (inventory row 21 / F6)

Written 2026-10-25 (lane L11), before any GEFS member value has been fetched or decoded. The coordinator relayed this
lever (F6) after R-M. It is development evidence only and makes no edge claim.

- Nothing dated after 2026-09-29 is read.
- No 88a, panel or settlement data for 2026-09-30..10-15 is read.
- No oracle.
- No paid data. No new dependency in the production venv. No pyproject or requirements change.
- Nothing touches MG-2's frozen files or L8's branch.
- **The spread side of GEFS is out of scope (lane L15).** No member dispersion enters any arm.

## Selection evidence and boundary

- **Why it is untested:**
  - F4 (EF §10y) scored the served "GEFS mean": +0.0054 [+0.0016, +0.0100] at 00-12, a harm.
  - That column is the GEFS **control run**, not the member mean (EF §10s; S0 receipts section (d)).
  - So the 30-member mean has never been scored. This is inventory row 21.
- **Prior (stated now): null is the most likely result.**
  - The ECMWF ENS 51-member mean, bias-adjusted and recentred halfway, was null at 00-12: -0.0000 [-0.0033, +0.0031]
    (EF §10y, G2-a).
  - R-M showed that the 2021-25 centre of P3d_N_fix has no per-market bias left (gate 1 failed, +0.00013).
  - Any gain must therefore come from day-specific information in the GEFS mean beyond NBM.
- **Boundary:**
  - R-I closed width recalibration.
  - R-M closed per-market centre bias.
  - The family below therefore has **no per-market term and no width, scale or spread term**.

## Input definition (fixed now)

- **Source:**
  - NOAA GEFS v12 operational, AWS open bucket `noaa-gefs-pds` (no key).
  - Product `pgrb2sp25` (0.25°), members `gep01..gep30`; `gec00` is fetched for the parity check only.
  - Message `TMP:2 m above ground`, located by its `.idx` line and fetched with an HTTP range read.
- **Cycle (point in time):**
  - The **06Z cycle of the target date D**, used only if every message the row needs has S3 `LastModified` (the max of
    the `.grib2` and its `.idx`) at or before the row's cutoff instant (h:00 local, zoneinfo).
  - Otherwise the row has no GEFS value.
  - No other cycle is used. The probe measured 06Z f030 at 09:55-10:01Z in 2021-2026, which is before 07:00 local in
    every US market (11Z or later).
- **Steps:**
  - f006, f009, …, f024, i.e. valid 12Z D .. 06Z D+1 (7 steps).
  - In local time this covers Eastern 08:00-02:00 and Pacific 05:00-23:00 in summer time.
- **Point:** bilinear interpolation of the four surrounding 0.25° grid points at the market's registry lat/lon (the same
  coordinates the captured Open-Meteo request uses). Values are converted from K to °F.
- **Feature:**
  1. Each member's max over the 7 steps whose valid local date is D: `h_m`.
  2. G = the mean of `h_m` over the members present.
  3. G requires at least 25 of 30 members; otherwise the row has no GEFS value.
- **Decoder:** a pure-numpy GRIB2 decoder (grid template 3.0, product 4.1, packing 5.3), extending L13's decoder. It
  must reproduce eccodes bit-exactly on a probe sample (scratch venv only) before any corpus row is accepted.
- **Disclosed definition differences against the capture:**
  - The capture's `day_member_high_*` take a max over Open-Meteo's hourly values on the full local day, from whatever
    run Open-Meteo held.
  - This feature takes a max over the 3-hourly nodes from one fixed cycle.

## Precondition P: parity with what the capture saw (inputs only, dev dates 2026-07-30..09-29)

- **What the capture recorded.**
  - On the workstation copy (`data/inbox/replay-inputs-le0929`), the capture recorded, per snapshot:
    - `day_member_high_p10` / `day_member_high_p90`: the 10th/90th percentiles of the 30 perturbed members' local-day
      highs;
    - `day_max_native`: the control's high.
  - It did **not** record the member mean, and the raw member columns are not in the workstation inputs. S0 says the
    full payloads exist on the capture host under `data/snapshots/<event>/forecast_payloads/`; they are not read here.
- **Comparison.**
  - On every covered 07-12 snapshot, compare this corpus's p10 and p90 of `h_m` (the same interpolation rule as
    `model_sources.percentile`) and its control high against the captured values.
  - This uses the snapshot's own cutoff and the PIT cycle rule above.
- **PASS if all three hold, pooled over markets and hours:**
  - |mean diff| <= 1.0 °F for each of p10, p90 and control;
  - the median absolute diff is at most 1.0 °F for each;
  - Pearson r >= 0.95 for each, over (market, date) means.
- **If P fails:**
  - Gate 2 is not run, and R-N stops BLOCKED (not killed).
  - The parity table is reported.
  - A faithful extraction (for example the capture host's raw payloads) would need a new ruling.
  - Gate 1 is still run and reported, because it does not depend on the capture.
- **If P passes:** dev gates use the **history values** (this corpus), with the disclosure that serving would read the
  Open-Meteo capture.

## The family (exactly one)

- **Shift.** At row r with arm anchor N_r and GEFS value G_r: s_r = a_h + b_h (G_r - N_r).
  - N_r is the arm's own NBM anchor at that row:
    - for P3d_N_fix, the `fh` column after `attach_training_nbm` in training and the dev NBM in dev;
    - for L6, `v2_mean`.
  - The coefficients are pooled over all markets, one (a_h, b_h) per cutoff hour h07..h12.
  - s = 0 when G_r or N_r is missing.
- **Grid.** a in {-3.0, -2.9, …, +3.0}, b in {0.00, 0.05, …, 1.00}, so b is clipped to [0, 1] by construction.
  - The choice minimises the population's own mean Brier.
  - Ties go to the smallest |a| + b, then the smaller b, then the smaller |a|.
  - (0, 0), the unshifted arm, is in the grid.
- **How the shift is applied:** exactly as R-M (`rule_rm.md`, sha 91e25610…).
  - P3d_N_fix: piecewise-uniform pmf translation by s_r, then the rule-4 / LOYO floor mask.
  - L6: mu + s_r before `mg1` band probabilities.
  - Width and spread are unchanged. At s = 0 each arm is byte-identical to its registered vector.
- **Exclusions.** No other cycle, step set, interpolation, member subset, objective, hour grouping, market term, shrinkage
  or spread feature is tried.

## Gates (in order)

### Gate 1: nested LOYO 2021-25 (P3d_N_fix)

- **Rows:** the R-A / R-M LOYO population: Aug-Sep 2021-25 at h07-h12, records `C:\t\l2\records`, NBM corpus 1ae4bf52….
- **Fitting, strictly nested:**
  - For each held-out year Y and each hour h, (a_h, b_h)(Y) is the grid minimiser over the inner out-of-sample
    predictions of the years other than Y (as R-M).
  - It is then applied to Y's plain LOYO prediction.
- **Positive control:** the unshifted predictions reproduce R-A `loyo_rows.jsonl` (sha 21cacdaa…) to 1e-9.
- **Statistic and PASS:**
  - The statistic is the mean per row of Brier(shift) - Brier(none), pooled over markets and h07-12.
  - Date-clustered bootstrap, 2,000 draws, seed 20261024.
  - PASS if the upper 95% bound is below 0.
- **Coverage disclosed:** rows without G are kept at s = 0.

### Gate 2: dev 07-12 (only if gate 1 PASSED and P PASSED)

- **Population:** as R-M gate 2.
  - Scorecard folds 08-01..09-29, scored 08-15..09-29.
  - Layout `C:\swarm\v3layout`, the common covered snapshots of P3d_N_fix (sha cd0034b9…) and L6 (part 07a67425…,
    nowcast 3806687c…).
- **Arms:**
  - **P3d_N_fix_G** uses (a_h, b_h) fitted once on all 2021-25 LOYO-inner predictions, with no dev fitting.
  - **L6_G** uses (a_h, b_h) fitted walk-forward on common covered dev snapshots dated in [08-01, d). L6 has no
    2021-25 history. Before any prior date, s = 0.
- **Statistic:** dR = mean_cell(Brier_arm_G - Brier_arm) / mean_cell(Brier_market), date-clustered (2,000 draws, seed
  20260921).
- **PASS per arm:** the upper bound is below 0 and no hour h07..h12 has a lower bound above 0.
- **Controls:**
  - MG-1 control 0.012;
  - s = 0 reproduces each registered vector to 1e-9;
  - mass preserved to 1e-9;
  - L6 - P3d_N_fix is reported.

### Gate 3: against MG-2 (L6) at 07-12, read as R-F

- **Comparisons:** P3d_N_fix_G against L6, and L6_G against L6.
- **Reading:**
  - **WIN** if the upper bound is below 0 and no hour has a lower bound above 0;
  - **HARM** if the lower bound is above 0;
  - **NULL** otherwise.
- **Caveat:** L6 is in-sample on this window.
- **If WIN:** a dated MG-2 pre-13 Clarification text is drafted, not applied.

### Against the market: reported only, never a gate

The excess of each G arm over the capture-time market at 07-12, per hour, as in R-H.

## PRE-REGISTERED KILL

- **Gate 1 fails:** the GEFS member-mean centre input is **closed for every NBM-anchored arm** (P3d_N_fix, L6, the MG-1
  family and the P3d_N family).
- **Gate 2 fails for both arms:** closed.
- **Gate 2 fails for one arm only:** closed for that arm.
- **"Closed"** means no other cycle, step set, interpolation, grid, hour grouping, objective, shrinkage or member
  statistic (median, trimmed mean, and so on) is run as a centre input under any rung name.
- **P failing is not a kill.** It is BLOCKED, as stated above.

## Outputs

- Corpus `C:\t\l11pb\gefs\corpus\` (station values only; no raw GRIB kept), with a manifest of every object key, byte
  range, ETag, LastModified and decoded value hash.
- `rn_parity.json`, `rn_loyo.json`, `rn_score.json`.
- A summary on the branch.

## Clarification 1 (2026-10-27): the capture side of precondition P uses history's node definition

Written by lane L2 on 2026-10-27, on master's ruling (option C), **after** P's first result. That result was
`rn_parity.json` sha256 176e9ed0e6f03fced63da6e535e735e79b9a975a5f49853fce3c678f13a2139e: p10 -0.904, **p90 -1.027
(FAIL)**, control -0.939 °F. Gate 1 had passed (`rn_loyo.json` 496ed1a5…) and is not re-run. Everything above this
section is unchanged; its sha256 is a9ca45f0….

**Why.** The definition difference disclosed under "Input definition" is that history takes each member's max over
3-hourly nodes of one fixed cycle, while the capture's `day_member_high_*` take a max over all hourly values of the
local day. That difference alone makes the capture warmer, and P measured about 0.9-1.0 °F on all three statistics.
Train/serve parity needs one definition. The trained one is the node max, so the capture side is recomputed to it.
This is a parity repair. It is not a threshold change and adds no free parameter.

**Capture side (replaces the captured `day_member_high_p10/p90` and `day_max_native` as P's comparison values).**
- **Source.** The capture host's raw Open-Meteo ensemble payload blobs, `data/snapshots/<event>/forecast_payloads/`.
  - Ensemble blobs are identified by `hourly` keys `temperature_2m_member01..30`; no other blob is used.
  - The per-member hourly values come from those keys. The control is `temperature_2m`, as the rule's original P.
  - Labels are naive local times with one `utc_offset_seconds`. Each label's instant is label - offset, as in
    `weather.time.provider_hourly_local_times`.
- **Node maximum.** For each member, take the max over exactly history's nodes:
  - the 06Z cycle of the target date D, fh 6, 9, …, 24, i.e. valid instants 12Z D .. 06Z D+1;
  - kept only when the valid local date is D;
  - every node is required, otherwise that member has no value.
  - This mirrors `ro_member_highs` (`src/weather/calibration/pooled_residual_model.py` lines 4922-4939 at
    bab6ff810).
- **Statistics.**
  - p10 and p90 are `model_sources.percentile` over the members' node maxima, with at least 25 of 30 members. This
    mirrors lines 5035-5044 at bab6ff810.
  - The control is `temperature_2m`'s node maximum.
- **Linking a blob to a snapshot.** The workstation inputs do not record the payload hash. A blob is linked to a P
  snapshot of the same event when it reproduces that snapshot's captured `day_member_high_p10`, `day_member_high_p90`
  and `day_max_native`.
  - "Reproduces" means: full-local-day member maxima, then `percentile`, exactly as `model_sources.fetch_global_ensemble`
    (`src/weather/model/model_sources.py` lines 2431-2520 at bab6ff810), within 1e-6.
  - Snapshots with no linked blob, or whose linked blobs disagree on the node statistics, are excluded and counted.
  - The link reproducing the captured day values is the positive control that the right payload was read.
- **Unchanged.** History side, population, cutoff hours 07-12, window 2026-07-30..09-29, and the PASS limits
  (|mean diff| <= 1.0 °F, median |diff| <= 1.0 °F, r >= 0.95 for each of p10, p90 and control).

**Residual difference (disclosed, not a parameter).**
- The cycle cannot be pinned on the capture side. Open-Meteo serves its latest run at fetch time, and the payload
  carries no run id, only `generationtime_ms`. The capture's run may therefore differ from history's 06Z D cycle.
- Open-Meteo's `temperature_2m` is read as the control, as in the original P. The capture code's docstring calls it
  the ensemble mean, and that is not resolved here.

**Consequence.** P is re-run once against the extracted capture values.
- If P fails, R-O is KILLED at P. There is no further clarification.
- If P passes, gates 2 and 3 run exactly as declared above.
