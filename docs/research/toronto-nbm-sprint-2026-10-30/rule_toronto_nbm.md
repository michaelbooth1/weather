# Toronto NBM text sprint rule (lane L8, 2026-10-30)

Committed with DEV_WINDOW_LEDGER row 77 **before any outcome read**: no history label, dev label or price.
Coordinator rulings of 2026-10-30, (1) to (4) and (b), are written in below. Any change after this file's
commit is a dated clarification, committed before the rows it affects.

Scope:
- Research only, development evidence only.
- Nothing dated after 2026-09-29 is read. No 88a, panel or settlement data for 09-30..10-15 is read.
- No B-bound file is edited.
- Run env: `claude/loyo-screen-runenv-20261030` @ `cf381f0f34e50ed329990e43a2298235164df43e`. Every receipt
  records the git HEAD and the input sha256 values.
- Every scorer writes per-date rows (master rule 2026-10-30).
- Interim cache rule: no re-download or rebuild of the forecast_history, open_meteo_archives or reanalysis caches.

## 0. Inputs

All inputs are already held. Nothing is fetched.

- **S1 receipt:** `C:/t/l8tor/s1_out2.json`, sha256
  `e8ad4435e4f43ab894412b2c927f1fca620b89c2ab60cbc76871f5ca4581d255`. It records CYYZ coverage in 100% of the
  fetched cycles.
- **NBP CYYZ** (01/07/13/19Z, 2021-07-31..2026-09-29): `C:\t\l14\nbp\manifest.jsonl` plus the raw blocks
  (L14 corpus). Parsed with `weather.sources.nbm_probabilistic_tmax.parse_nbp_station_tmax` (parser v2).
  The fields are TXNMN and TXNSD, converted once from F to C.
- **NBS/NBH CYYZ** (04-19Z): `C:\t\l12\nbs_nbh` (Aug-Dec 2021-25) and `C:\t\l12\nbs_nbh_2026dev`
  (07-30..09-29). The hourly TMP is converted to C.
- **Availability:** a cycle counts at instant t only if its S3 `last_modified` <= t. This is a pure
  receipt-time rule; there is no fixed-cycle assumption.
- **Labels:** WU CYYZ `max_temp_native`, whole C, from the same two files and sha256 values as L14's rule
  (`1ced925a…`, `c9e16b1d…`).
- **Floor:** the IEM CYYZ METAR running max, as in L14's rule. The inputs are
  `C:\t\l11\toronto_obs\toronto_obs.parquet` `9f3b2972…a802`, the L14 IEM Oct-Dec csv files, and the
  dev observations `bb85d7a5…`.
- **Units:** native C throughout. A 1 F constant is carried as 5/9 C.

## 1. Arms

All arms use the same rows: CYYZ, local hours 07..16, the snapshot at h:00 local. Every arm is emitted in
served form, through `pooled_residual_model.fit_pooled` and `predictive_distribution` with the floor and the
2% climatology mix. All arms are fitted on CYYZ rows only, because the US frame is in F and Toronto is in C.

| Arm | N (centre) | Extra regressors | Role |
| --- | --- | --- | --- |
| **B_N-NBP** | NBP 07Z TXNMN of D (L2 R-A / L14 B_N form, `simple=True`) | none | incumbent candidate |
| **P3d_N_fix-CYYZ** | NBP 07Z TXNMN of D (the PIT NBM corpus convention, EF "PIT NBM corpus") | none (`simple=False`, R-A spec) | incumbent candidate |
| **Arm A** (primary) | the newest NBP cycle received by t (D-1 13Z, D-1 19Z, D 01Z or D 07Z, by `last_modified`) | TXNSD (C) | candidate |
| **Arm B** | as Arm A | TXNSD; the max of the NBS/NBH hourly TMP over the rest of local day D, from the newest NBH cycle received by t | candidate |
| no-NBM reference | climatology mean of the training years | none (`simple=True`) | descriptive only, never gating |

**Note on P3d_N_fix-CYYZ.** P3d_N_fix's N on history is itself the NBP text TXNMN from the 07Z cycle, not an
NBM grid value. So P3d_N_fix-CYYZ and B_N-NBP share Arm A's source. **Arm A differs from the incumbent only
in its cycle (newest received, not 07Z only) and in TXNSD. Arm A is therefore a spec-and-timing test of NBP
against itself. Only Arm B adds a new product (NBS/NBH).** This holds whichever incumbent is chosen, and if
B_N-NBP is chosen it is stated again in the selection clarification.

## 2. Incumbent selection (history only, before any candidate is scored)

- **Method:** blocked leave-one-year-out over Aug-Sep 2021-25, hours 07..16, with the same rows for both
  incumbent candidates.
- **Choice:** the incumbent is the one with the lower mean held-out band Brier. Rows are equal-weighted
  within a date, then dates are equal-weighted.
- **Recording:** the choice and both numbers are recorded in a rule clarification, which is committed and
  pushed before any Arm A or Arm B fit is run.
- **Tie:** within 1e-9, P3d_N_fix-CYYZ wins.
- **Per-date rows:** written for both incumbent candidates.

## 3. S2: history gate (kill only)

- **Population:** nested LOYO over Aug-Sep 2021-25, hours 07..16. Each held-out year is predicted from the
  other four, and inner choices are made in an inner LOYO only.
- **Statistic:** d = Brier(arm) − Brier(incumbent), per date (the mean over that date's hour rows). Intervals
  are date-clustered percentile, 2,000 draws, seed 20261024.
- **Holm over the two arms:** order the two one-sided p-values (bootstrap share of draws >= 0). The smaller
  must be < 0.025 and the larger < 0.05. Each arm passes only on its own Holm-adjusted test.
- **Outcome:** an arm that fails S2 is **KILLED**, and its dev window is never read.
- **Descriptive blocks (never gating):**
  - Aug-Dec 2021-25, the same statistics;
  - log loss;
  - per hour;
  - the no-NBM reference against the incumbent.
- **Version disclosure:** the training blocks are V4.0-V4.3, and the 2026 dev window is V5.0 (S1). That is a
  train/serve version shift, disclosed and not corrected.

## 4. P0: Toronto dev window (only for an arm that passes S2)

- **Rule:** MR gate `rule_mr.md` sha256 `37cb46be8d8ddb272ac69638d71de8d023eddff2384e0a6824e00a18417f34ac`,
  unchanged, with the Toronto clarification `clarification_toronto_mr.md` committed alongside this file.
  That clarification sets a single-market population with date-clustered intervals, and the
  calibration-matched placebo (review 2026-10-30, adopted in the L3 sweep rule). P0 needs the lower bound of
  rho_c > 0 and the lower bound of rho_c − rho_pl > 0; the date-deranged placebo is a diagnostic only.
- **Fit:** the arm is frozen as fitted on all of Aug-Sep 2021-25.
- **Market vector m:** the capture-time arm, as in 37cb46be.
- **Dates:** burn-in 08-01..08-14; scored 08-15..09-29.
- **Outcome:** an arm that fails P0 is KILLED, and the w gate is reported only.

## 5. Futility (Rule B thinking)

Each tier is cheaper than the next and kills before it: S1, then the incumbent choice, then S2 (history),
then P0 (dev). No interim look can produce a PASS. A KILL at any tier is final for this rule.
