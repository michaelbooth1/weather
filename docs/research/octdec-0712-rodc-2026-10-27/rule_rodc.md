# Rung R-ODC pre-registration: a season-matched P3d_H for Oct-Dec 07-12, against the frozen blend_l6_H (two gates)

Written 2026-10-27, before any R-ODC row, fit or score exists, and pushed before the 2021-23 HRRR backfill it
needs has finished. Approved by master on 2026-10-27 (relayed by the coordinator) as rung R-ODC, with
DEV_WINDOW_LEDGER row 65. Master's conditions (a)-(d) are bound in sections 3, 5 and 6 below.

This is history-only development evidence. It makes no edge claim.

- No date in 2026 is a training or scoring row (the 2026 settled-day embargo).
- Nothing dated after 2026-09-29 is read.
- A pass can promote only through a separately pre-registered forward test (ruling R10, EF §10ac scope
  paragraph). It never promotes from this history.

## 1. Question

MG-3 serves blend_l6_H at 07-12 all year. X41 (CS-1 part 1c) found that the Aug-Sep-fitted P3d_H does not transfer
to Oct-Dec 2024-25: −0.0063 [−0.0167, +0.0036] against the MG-1 analogue. The blend helps less in Oct-Dec than in
Aug-Sep.

R-ODC asks two questions, in order:

1. Gate 1: does refitting P3d_H on Oct-Dec rows only, inside the same frozen blend, beat the frozen blend_l6_H at
   07-12 in Oct-Dec?
2. Gate 2: if gate 1 passes, do two pre-fixed cool-season columns improve the refit further?

## 2. Rows

### Source records

- L2's trainer records `C:\t\l2\records\records_<market>_<centre>.pkl.gz`, built at `eb7ff73bc`.
  - Their Open-Meteo forecast_high and forecast_gap come from the PIT Previous Runs union.
  - The 2026-10-27 DST audit traced that union clean on a standard-time date in each of its three corpora.
- Oct-Dec centres: 2026-10-10, 10-25, 11-09, 11-24, 12-09.
- Target years 2021-2025.
- Cutoff hours 07, 08, 09, 10, 11, 12.
- Markets: the 11 `R0_MARKETS`.
- The run refuses any row with a target year of 2026 or later, or a target date after 2025-12-31.

### Labels and inputs

- Label: y = final_bucket (WU).
- Floor: F = high_so_far.
- The NBM mean comes from `attach_training_nbm` on the L9 PIT NBM corpus `1ae4bf52…`.
- The serve-parity raw columns are `DEV_KEEP_X` (x_high_so_far, x_current_temp). This is P3d_H's own frame
  (`dev_training_frame`), restricted to the Oct-Dec centres.

### HRRR extras [k_max, k_gap, k_tcdc]

These follow the R-K raw path with the RN-1 land point rule, exactly as CS-1 part 1c computes them:

- `C:\t\l13\land\land_3x3.json`, sha256 `22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6`.
- KSFO uses index 3; every other station uses index 4.

They are read from two sources:

- **2024-25 Oct-Dec:** L13's sealed backfill `C:\t\l13\hrrr_cool0712`, under scope grant (b) in section 6, bound
  to its SHA256SUMS seal `fe2dad2c9b2567ff28a9916f42c51a9196d33fc79f40690332745c2ed2acbc4d`.
- **2021-23 Oct-Dec:** the new backfill in section 5, bound to its own SHA256SUMS seal. That seal is recorded in
  row 65 before any read.

Both sources must use the same `stations.json`, the same point rule and the same fetcher parameters (section 5).

### Missing HRRR extras

A missing extra is never imputed or filled from another cycle.

- The 70 `no_cycle` rows in the sealed backfill (2024-10-15 h07-12 and 2025-10-20 h07-09) keep NaN extras. So does
  any no-cycle row in the new backfill. NaN is the HGB's native missing value and the same input the comparator
  serves.
- These rows are scored on every arm identically.
- Their counts are reported, along with gate 1 recomputed with them dropped. That recomputation is reported only,
  never a gate.

## 3. Arms (all on identical rows)

### COMP: the frozen blend_l6_H (condition d)

Nothing in COMP is refitted.

| Part | Binding |
| --- | --- |
| P3d_H 07-12 state `C:\t\l2\mg3\state_0712\p3d_h_state.pkl` | sha256 `e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0` |
| blend weights `C:\t\l2\mg3\weights\blend_l6_H_weights.json` | sha256 `c7b8ebc08d31ca30e5289d453ec2260bcc6659b32b379410f58b0d2b9b03530a` |
| L6 partner, canonical part | sha256 `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9` (HGB `0e89b32d…`, coefficients file `4bc51e03…`) |

- The serve math is CS-1 part 1c section 3, unchanged:
  - L6 = Normal(v + a_h + b_h (N − v), max(s, 1)), floored at half-up(F).
  - Blend = w_h · P3d_H + (1 − w_h) · L6, bucket by bucket.
- The run refuses if the weights name a different L6 partner.
- COMP is the same for every year. Its P3d_H was fitted on Aug-Sep 2021-25, so it saw no Oct-Dec row.

### G1: the season-matched P3d_H inside the frozen blend (gate 1)

- The P3d_H arm spec is unchanged (`RK_ARMS["P3d_H"]`: simple = False, extra_hgb = (k_max, k_gap, k_tcdc)).
  - The `_rung_entry` construction is unchanged: the mean model on all training rows, plus the inner-LOYO scale
    model and the z set.
  - Hyperparameters are unchanged (`MEAN_HGB_PARAMS`).
  - There is one fit per cutoff hour.
- The only change is the training rows:
  - Oct-Dec centres only.
  - Blocked leave-one-year-out over 2021-2025: the year-y row is scored by the fit on the other four years.
- The fitted P3d_H replaces COMP's P3d_H. Everything else stays frozen: the same L6 partner, and COMP's weights
  w_h. No weight is refitted.
- Fixed before any fit and not tuned: hyperparameters, columns, hours and centres.

### G2: G1 plus two fixed cool-season columns (gate 2; run only if gate 1 passes) (condition c)

G2 is G1 with exactly these two columns appended to extra_hgb. Nothing is chosen at run time.

- **low_so_far:** the overnight low since local midnight.
  - It is `weather.calibration.ols_floor_ladder.overnight_lows` (master `f5002b086`, file sha256
    `6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e`), first element.
  - It is computed on the same history rows as the record's high_so_far (minute_of_day ≤ cutoff·60).
  - Its assertion (max of that row set = high_so_far) must hold, or the run refuses.
- **dewpoint_c:** the dewpoint at the cutoff, the record's own `dewpoint_c` field. NaN stays NaN.
- No other column, transform, window or interaction is added.
- `DEV_KEEP_X` is unchanged, so x_dewpoint_c stays dropped from the raw columns. dewpoint enters only as this extra.
- Serve parity of both columns is NOT established by this rung. A gate 2 pass requires a separate serve-parity
  check of both columns before any forward test.

## 4. Gates (in order; each stops the rung if it fails)

### Statistic (both gates)

- dR = mean_cell(Brier_arm − Brier_ref) / mean_cell(Brier_ref).
- Cells are (local_date, market), pooled over h07-12 and the 11 markets.
- Brier is the multi-bucket Brier (`brier_from_dist`: Σ p_k² − 2 p_y + 1).
- The interval is date-clustered (`dev_scorecard.ratio_interval` with `r0_ols_floor_challenger._date_weights`):
  2,000 draws, seed 20261027.
- This is the CS-1 part 1c construction with a different reference arm.

### Gate 1: G1 against COMP

- **PASS** if the upper 95% bound of dR(G1 vs COMP) is below 0.
- Reported, never gating:
  - the 5 primary markets;
  - each hour;
  - each held-out year;
  - each month;
  - the absolute Brier difference;
  - the sensitivity with no-cycle rows dropped.
- **If gate 1 fails:** R-ODC stops. The verdict is "season-matched P3d_H does not beat the frozen blend at Oct-Dec
  07-12". Gate 2 is not run.

### Gate 2: G2 against G1, under NESTED LOYO (condition c)

#### Selection evidence on the same data (disclosed)

- low_so_far and dewpoint were chosen because X13 (EF §10ac, the L9 ladder) found they help Oct-Dec 07-12. X13
  measured this with LOYO on Oct-Dec 2021-25:
  - the same centres (10-10, 10-25, 11-09, 11-24, 12-09);
  - the same years;
  - the same markets.
- The X13 effects were:
  - overnight low −0.028 nats (11 markets) and −0.031 (5 markets);
  - dewpoint about −0.014;
  - both were CI-worse in Aug-Sep.
- X13 used OLS + hard floor and log loss, not P3d_H and Brier.
- Gate 2's data is therefore not fresh for these two columns. Every year in it has already informed their choice.
- Nested LOYO protects the fitting from the held-out year. It cannot undo that the pair was picked on all five
  years. A gate 2 pass is selection-contaminated history evidence, and only a forward test can confirm it.

#### Nested procedure, fixed now

For each outer held-out year y in 2021-25:

1. On the four other years only, run an inner blocked LOYO of G1 and G2, each in the frozen blend:
   - four inner folds;
   - per-hour fits;
   - the same construction as section 3.
2. Compute the inner pooled mean of Brier(G2) − Brier(G1) over all inner held-out rows, at h07-12 on 11 markets.
3. The outer arm NEST(y) is G2 fitted on the four years if that inner mean is below 0. Otherwise it is G1 fitted on
   the four years.
4. Score NEST(y) on year y.

#### Pass rule

- **PASS** requires both of the following:
  - the upper 95% bound of dR(NEST vs G1) is below 0;
  - the upper 95% bound of dR(NEST vs COMP) is below 0.
- Reported:
  - the number of outer folds in which G2 was selected (0-5);
  - each hour, each held-out year and the 5 primary markets;
  - plain non-nested G2 vs G1, for reference only.
- **If gate 2 fails:** the two columns are closed for P3d_H at Oct-Dec 07-12. G1 alone carries the gate 1 result
  forward.

### Power, stated up front (condition d)

- **Full design:** 11 markets × 75 dates × 5 years × 6 hours ≈ 24,750 rows, in 375 date clusters.
- **Estimate:** MDE80 ≈ 0.0067 on the dR scale for 2021-25 (≈ 0.011 if only 2024-25 were used).
  - This is extrapolated from X41's blend_l6_H interval on 2024-25: 9,830 rows, 150 clusters, half-width ≈ 0.0074.
  - SE ≈ 0.0038 · √(150/375) ≈ 0.0024.
  - MDE80 = 2.8 · SE.
- **Caveats:**
  - X41's denominator was the MG-1 analogue's Brier. Here it is COMP's Brier, which is smaller (COMP beats MG-1 in
    Oct-Dec), so the true MDE on this scale is somewhat larger.
  - For gate 2, the paired G2 − G1 differences are expected to vary less than an arm-vs-COMP difference. Its MDE is
    therefore at most about this size, but it is not estimated in advance.
- A null is reported as a null at this power, never as evidence of no effect.

## 5. The 2021-23 HRRR backfill (condition a)

The backfill uses free official NOAA data from the AWS Open Data bucket `noaa-hrrr-bdp-pds`, read anonymously over
HTTPS. No paid source is used, and no scheduled task is created.

### Fetcher and parameters

- **Fetcher:** L13's `tools/research/hrrr_point_fetch.py` at `9df46b7881ac3e450fabce130dd59249f7f7297f`
  (LF sha256 `5c8e817b4127d8edeb605f7ecf1f508f5569f78dd07091db7a442323ed46adfa`). It runs from a detached worktree
  at that commit.
- **Parameters:** identical to the sealed `hrrr_cool0712` run except --years, --out, --stop-file and the byte cap:
  - --months 10,11,12
  - --first-hour 7 --last-hour 12 --valid-end-local 17
  - --cycle-stride 1 --max-fh 18 --lookback 4 --margin-minutes 10
  - --variables "TMP:2 m above ground,TCDC:entire atmosphere"
  - --seed 20261025 --pause 0.4
  - --years 2021,2022,2023
  - --out `C:\t\l16odc\hrrr_cool0712_2123`
  - the stop file is `STOP` inside that directory
- Its seeded date shuffle spreads any stop across years.

### Order of operations

1. **Request list first.** A planner lists every candidate cycle and plans each day exactly as the fetcher does. It
   downloads each needed `.idx` once, and sums the HTTP Range lengths of both variables over the unique
   (cycle, fh) messages. That total, T, is recorded in row 65.
2. **Disk precondition.** The fetch starts only if the workstation's free disk is at least 2 × T. The fetcher keeps
   only station points, never raw messages, so T is a network total. The precondition is applied to it anyway. The
   byte cap is 1.15 × T. --min-free-gb is 60, so the fetcher pauses itself if free disk falls below that.
3. **Allowlisted and batched.**
   - Only the planned keys are fetched: the fetcher's own plan, which is identical to the planner's plan.
   - The run is three batches, one per year (2021, then 2022, then 2023). Each batch is checked before the next
     starts.
4. **HRRR v4 asserted per file.**
   - HRRR v4 has been operational since 2020-12-02 12Z, so every 2021-23 cycle is v4. The planner asserts
     cycle ≥ 2020-12-02T12Z for every key.
   - Per file, the file's own `.idx` must have the v4 inventory size for its forecast hour: 170 records at f00-f01
     and 173 at f02-f18.
   - The anchors, fetched 2026-10-27, are cycles 2020-12-09 12Z (v4: 170/173) and 2020-11-25 12Z (v3: 148/151).
   - Record names differ between idx generator versions (for example LTPINX vs LTNGSD, or `var discipline=…`
     placeholders). So the per-file check is the record count, plus exactly one TMP:2 m and one TCDC:entire
     atmosphere record. It is not a name hash.
   - Each fetched message's `idx_sha256` must equal the planner's idx for that key.
   - Any failure refuses the corpus.
5. **Seal.** After completion, a `SHA256SUMS` over manifest.jsonl, selections.jsonl, days.jsonl, stations.json and
   status.json is written. Its sha256 goes into row 65 before any read of the extras.
   - stations.json must equal the sealed 2024-25 corpus's.
6. **Pause and launch rules.** The fetch is a network fetcher, so it runs directly, outside `workstation_heavy.ps1`
   (HOST_LOAD_POLICY, master ruling 2026-10-23).
   - It is stopped through its stop file by Wednesday 2026-10-28 11:00 EDT for the maker pilot. It is not restarted
     until the coordinator clears it.
   - It is the only process this lane launches, and it is tracked and terminated by this lane.

### Order of runs

- Nothing is fitted or scored on 2024-25, or on any year, before the 2021-23 seal exists.
- Every fit in this rule runs once, on 2021-25 together.

## 6. Scope entry: the sealed 2024-25 Oct-Dec backfill (condition b)

Master granted (2026-10-27) R-ODC read access to `C:\t\l13\hrrr_cool0712`.

- The scope is the HRRR extras for R-ODC's 2024-25 Oct-Dec rows, under this rule only.
- The seal is SHA256SUMS sha256 `fe2dad2c9b2567ff28a9916f42c51a9196d33fc79f40690332745c2ed2acbc4d`. Every file must
  hash to its line, or the run refuses.
- The sealed files are never written.
- A dated line recording this grant is appended to the append-only `C:\t\l13\hrrr_cool0712_ACCESS.txt` (outside the
  sealed directory) before any read.

## 7. Mechanics and outputs

- **Code:** a module on branch `claude/octdec-0712-rodc-20261027`.
  - It reuses, unchanged, the P3d_H fit (`pooled_residual_model`, MG-3 freeze), CS-1 part 1c's serve math and HRRR
    reader (`cool_season_audit`), and the ladder's `overnight_lows`.
  - The exact commit it runs at is recorded in row 65 before the run.
- **Runs:** fits and scoring run through `scripts/ops/workstation_heavy.ps1 -Queue -MinAvailableMemoryGB 3`,
  serially.
- **Outputs:** `C:\t\l16odc\rodc\` holds `gate1.json`, then `gate2.json` if gate 1 passes, plus per-row files.
  Every output is write-once.
- **Ledger:** DEV_WINDOW_LEDGER row 65 is written `pending` before the run (the coordinator routes ledger text).

## Clarification 1 (2026-10-27, master ruling relayed by the coordinator; written before any fit)

This clarification does two things only. It pins the run environment and it states the positive control's
configuration. It changes no scope, arm, gate, statistic or headline: section 2's headline stands as declared,
with no-cycle rows kept with NaN HRRR extras, and the dropped version as the sensitivity.

### C1.1 Run environment (pinned)

- Branch `claude/rodc-run-env-20261027`, a research-only environment that is never landed. Its tip is
  `6d53385b12d6490e336ff1dc96bf7ea436703021`. It was built from this rule's commit
  `b0bd4c3af1b5db4f92b6541d0711ac1f3e9143df` by real merges:
  1. `5879e82d83fac5b9df64be2cfdb2d4f60d8849e6`, the cool-season-audit commit that CS-1 part 1c (row 47) and row 49
     ran at. That commit is recorded in rows 47 and 49 and in L3's clarification `31512de0…`. The branch head
     `6a8b00755` is not used. The merge was clean; its commit is `49388fa0f379b50a8548457f5ad5626470a63032`.
  2. `b750df1634b969a5317d9aaa3ee4905af9fcb1b5`, the MG-3 freeze.
     - There was no `src/` conflict.
     - No `src/` file changed on both sides relative to either merge base (`850696870…` for merge 1, `58be2ef79…`
       for merge 2), so git combined no `src/` edits.
     - The three conflicting non-src files took the 5879e82d8 side wholesale: `docs/operations/FINDINGS_DIGEST.md`,
       `tests/calibration/test_pooled_residual_model.py` and `tests/calibration/test_r0_ols_floor_challenger.py`.
- R-ODC's code is added on top of this tip. The code commit is recorded in row 65 before gate 1.
- An import-closure scan of the R-ODC entry point runs before any run.

### C1.2 Positive control (before any refit)

- **What it reproduces:** X41's frozen blend_l6_H Oct-Dec 2024-25 result, the row-47 output
  `C:\t\l3\coolseason\part1c.json`.
- **Configuration:** X41's own. It runs `python -m weather.calibration.cool_season_audit part1c` from the env tip,
  through `workstation_heavy.ps1 -Queue`, with L3's inputs unchanged:
  - the CS-1 rule `ac9c7433…`;
  - the 1c addendum `2b7c4c3f…`;
  - L3's clarification `31512de0…`, which sets the paired, cycle-present key set, with the 63 no-cycle keys dropped;
  - the sealed backfill `fe2dad2c…`;
  - L2's state_0712, the weights `c7b8ebc0…`, the coefficients `C:\t\mg2\freeze_cap\mg2_coefficients.json`
    (`4bc51e03…`), the L6 HGB `0e89b32d…`, the land rule `22069bee…`, the NBM corpus `1ae4bf52…` and the
    records `C:\t\l2\records`.
  - The output is `C:\t\l16odc\control\part1c.json`.
- **Expected:** the module sha256 is `33a96f17…`, and `blend_l6_h_0712.headline` equals the row-47 receipt exactly:
  - estimate −0.01634938182470121;
  - ci95 [−0.023824563528186724, −0.009037275953557012];
  - n_rows 9,830, n_dates 150, n_cells 1,649;
  - Oct-Dec key-set sha256 `3a12f74a2544dae35fec6ed03d76a0f4969e9ff5d6de3da9bebc0ec9821f825a`.
- **Pass rule:** exact equality. Anything else stops R-ODC and is reported.
- **Reads:** the control reads the sealed 2024-25 backfill under grant (b). A dated access line records this
  master-directed control read.
- **No fit before the seal:** gate 1 still runs once, only after the 2021-23 backfill's SHA256SUMS seal.

## Clarification 2 (master ruling 2026-10-27): shared bucket support; code and env pinned

Appended before gate 1 and before the 2021-23 backfill seal. No scope change: the arms, the statistic, the
gates and the pass rule are unchanged.

### C2.1 Code and final run environment (pinned)

- Code commit on the env branch: `2092745ab157b826520958c3374cb27cd405ea2b`. It adds
  `src/weather/calibration/rodc_octdec.py` and the `rodc-gate1` subcommand of `cool_season_audit`.
- Support commit on top of it: `6286465b2fdc20657ee8a7d5f176f82bda0bdb76`. This is the **final env tip** that gate 1
  runs at. `rodc_octdec.py` at that tip has sha256
  `9575f1b8fb36dd32b578edd757bd965478003ac3ae2a8bd2fb3e61c7e52b9378`, and it is the only file the commit changes.

### C2.2 Shared support (both arms, every fold)

- **Rule:** in each LOYO fold, COMP (the frozen blend_l6_H) and G1 score on the same bucket support. A G1 gain
  that comes only from a wider support is not admissible.
- **Source:** no outcome-free per-market, per-date support exists for 2021-25 Oct-Dec.
  - The registry (`config/locations.json`, `config/venue_rule_stations.json`) carries no bucket spaces.
  - Venue bands exist only for live events, and there were none on these historical dates.
  - The records' `bucket_space` is the observed label set over all years (`model_climatology.py:189` on
    origin/master), so it includes the held-out year.
- **Construction:** the support is therefore built per fold from the training years only.
  `fold_support(frame, year, markets)` (`rodc_octdec.py:61-76` at `6286465b2`) gives, per market, every integer from
  the minimum to the maximum of the settled label `y` over the Oct-Dec G1 training rows (hours 07-12) of the four
  years other than the held-out `year`. It refuses if the held-out year is present.
- **Both arms get it:**
  - G1's fold state carries it (`fold_state`, :87-108).
  - COMP is `comp_state(frozen, support)` (:79-84): the frozen P3d_H state with only `buckets` replaced. The frozen
    `train_y`, mean, scale, z, centres and constants are unchanged.
  - `gate1` builds both per fold (:252-254) and refuses if the two lists differ (:255-256).
  - `score_rows` scores COMP with the fold's state (:163).
- **Where support enters:** only P3d_H's 2% climatology mix (`smoothed_dist` over the support) and its support
  points. The kernel range is independent of the support, and the L6 partner's support is its own, so it is
  unchanged.
- **Consequence, stated:** COMP is the frozen blend_l6_H except for its support. The frozen state's own support is
  the Aug-Sep 09-07 grid, which is item 341. The output records each fold's support per market as
  `[min, max, count]` (`fold_support`).
- This replaces 2092745ab's union of the five Oct-Dec centres' `bucket_space`, which used held-out-year outcomes.

### C2.3 Positive control: unaffected

The C1.2 control runs `cool_season_audit part1c`, whose static import closure (171 modules, scan
`closure_control.json` `cefb5472…`) does not include `rodc_octdec`. `cool_season_audit` imports `rodc_octdec`
lazily, only inside the `rodc-gate1` dispatch (`cool_season_audit.py:1157`). The support commit changes no other
file, so the control's code path and its exact result (`8d87027a…`) stand without a rerun.

### C2.4 Open-ended support edges (master's check, before the seal); env re-pinned

- **Finding at 6286465b2:** the edges were NOT open-ended.
  - `smoothed_dist` (`mg_serve_core.py:451-458`) puts climatology mass only on in-support integers; a
    training label beyond an edge dropped out of the numerator.
  - `brier_from_dist` (`cool_season_audit.py:75-77`) scored an out-of-support held-out `y` against whatever
    kernel mass sat at that integer.
  - Held-out labels outside the training-years support (labels only, 2021-25 Oct-Dec records, hours 07-12,
    24,744 rows; `C:\t\l16odc\edge_counts.py` `d05f42f2…`, output `f2b6d9a1…`), below min / above max:
    2021 12/0; 2022 0/12; 2023 6/18; 2024 6/36; 2025 66/12; 288 rows in all, about 1.2%.
- **Change** (env commit `701b7bb5d554a75914d224b4f2058431e5c4de50`, now the **final env tip**;
  `rodc_octdec.py` sha256 `14472030ae3827f174b751cda8c04d573fb905e578ede06182ad8d14494445de`, the only file
  changed):
  - `open_edges` (`rodc_octdec.py:79-93`) clips each hour's `train_y` into [min, max] in both state copies:
    COMP through `comp_state` (:96-99) and G1 through `fold_state` (:134). Climatology mass beyond an edge
    lands on the `<= min` or `>= max` edge bucket.
  - `edge_brier` (:102-110) folds every scored distribution (both blends, both P3d_H arms and the reported
    MG-1) onto the support, with `<= min` and `>= max` edge buckets, and clips `y` the same way.
    `score_rows` uses it for every arm (:207-210) and refuses if the two arms' supports differ (:202-204).
  - The per-row counts `y_in_support`, `y_below_support` and `y_above_support` are recorded in the output's
    `row_stats`.
- **Scope:** both arms are scored identically on the same open-edged partition, which mirrors the venues'
  open-ended end bands. The statistic, gates and pass rule are otherwise unchanged. The C2.3 control
  argument still holds, because `rodc_octdec` remains outside the control's import closure.
- **Supersedes:** gate 1 runs at `701b7bb5d…`, not at `6286465b2`, and C2.1's "final env tip" is
  superseded by this line.

### C2.5 Output-format fix (master-approved, before the run); env re-pinned

- **Bug:** at `701b7bb5d`, `fold_state` keyed its per-hour training-row counts by int hour next to the string
  key `export_parity_max_abs`. `gate1` writes them into `counts.fold_training_rows`, and the write-once JSON
  (`cs._write_once`, `json.dumps(sort_keys=True)`) raised `TypeError` on the mixed key types after the full
  run. No output would have been written.
- **Found by:** the synthetic end-to-end test on `claude/rodc-gate1-test-20261027` at
  `27c49d0a2b5a72267ac958b9c427a030a5d045e8` (test-only; synthetic data, no real 2021-25 rows and no
  backfill data).
- **Change:** exactly one line, `rodc_octdec.py:129`, `rows[str(hour)] = int(len(train))`.
  - This is OUTPUT FORMAT ONLY: the JSON key type.
  - It has no effect on the fit, the support, the scoring or the statistic.
- **Pins:**
  - Env commit `9403d87bca6156613e7507ffe7fb45fda758e1a4`, now the **final env tip** (it supersedes C2.4's
    `701b7bb5d`).
  - `rodc_octdec.py` sha256 `9c9752b82b0a3e8dd2721b464710b1616fce6e9441d3c654705c1dd05347f8d8`, the only file
    changed.
- **Test at the new tip:** the test branch merges this tip (`5451e8f3c…`), and the full synthetic end-to-end
  test passes there, run through `workstation_heavy.ps1 -Queue`.

## Clarification 3 (2026-10-28, master ruling relayed by the coordinator): gate 2 comparator and pass rule

- **Written after the gate 1 result, disclosed.** It follows gate 1 (PASS, dR(G1 vs COMP) −0.0248
  [−0.0276, −0.0220], `gate1.json` `6f26c5a2…`, ledger row 65) and master's 10-28 ruling that G2 must use a
  comparator fit for the season it scores. No G2 code has run, and no outcome, label or price after 2026-09-29 is
  read. This Clarification changes the file's sha256. Gate 1's pin `40ea3a94…` stays as recorded for gate 1.
- **Source:** master accepted option (i) of
  [the gate 2 design](gate2-design-2026-10-28.md) (design file sha256 `ee98d9fd…`), with the terms below.

### C3.1 Gate 2 pass rule (narrows section 4, "Gate 2", "Pass rule")

- **PASS** iff the upper 95% bound of dR(NEST vs G1) is below 0. This is the only gating condition.
  - G1 is the gate 1 arm: the Oct-Dec P3d_H refit under blocked LOYO, inside the frozen blend. It is
    season-fit, and it is G2's exact parent.
- The second condition of the declared pass rule, dR(NEST vs COMP) < 0, **no longer gates**. COMP's P3d_H is
  Aug-Sep-fitted (section 3), so under the ruling it is not a comparator fit for Oct-Dec.
- The nested procedure, the statistic, the interval, the population (gate 1's scored key set) and the fail
  consequence are unchanged.

### C3.2 Reported, never gating

- **dR(NEST vs COMP),** labelled "vs the Aug-Sep-centred frozen blend (item 341)".
  - COMP's L6 partner is the HGB `0e89b32d…` named in section 3, because the rule text governs. Gate 1 ran with
    it (`cool_season_audit.L6_STATE_SHA256`).
- **dR(NEST vs COMP-800072c7):** COMP with its L6 nowcasts from the season-matched HGB `800072c7…`
  (`cool_season_audit.SM_STATE_SHA256`) instead.
  - The P3d_H state `e9276477…`, the weights `c7b8ebc0…` and the part `07a67425…` are unchanged.
  - Labelled IN-SAMPLE: `800072c7` was trained on every Oct-Dec 2021-25 history row, and the weights were fitted
    with the `0e89b32d` partner.
  - It is reported because ledger row 49 names `800072c7` beside the same part. The discrepancy is noted on
    row 49.
- **dR(NEST vs MG-1),** the MG-1 analogue on the same keys.
- **Also reported:** the G2-selection count (0-5); each hour, held-out year and the 5 primary markets; plain
  non-nested G2 vs G1; the inner-fold means; and the per-fold out-of-support counts (inner and outer).

### C3.3 Disclosed limitation

- The blend weights w_h `c7b8ebc0…` were fitted on Aug-Sep. They are shared, frozen, by G1, G2 and NEST.
  - So no arm is season-fit in the blend layer.
  - In the paired G2 − G1 difference, the shared weights cancel to first order. They remain only through how the
    two P3d_H arms interact with the same w_h.
  - Master accepts this for a column test.

### C3.4 Inputs for the two columns

- **`low_so_far`:** `ols_floor_ladder.overnight_lows` (file sha256 `6e6d100f…`), first element.
  - The records carry no raw history rows. The value is therefore read from L9's ladder caches, which are built by
    `ols_floor_ladder build`, the function that calls `overnight_lows` with its high_so_far assertion. The caches
    are `C:/t/l9/cache/cache_<market>_<centre>.json`; the run pins a manifest sha over the cache files.
  - It is joined on (market, centre, date, hour).
  - The run refuses unless the cache's `high_so_far` equals the record's high_so_far to 1e-9 on every joined row.
    This is the section 3 assertion, checked against the records the arms use.
  - A row with no cache entry also refuses the run.
- **`dewpoint_c`:** the L2 record's own `dewpoint_c` field, on the same join. NaN stays NaN.
- Only Oct-Dec 2021-25 rows are kept from either source. Nothing dated 2026 is used.

### C3.5 Control and determinism (VOID if either fails)

- **Gate 1 reproduction control:** before anything is scored, the run re-executes gate 1's own code path
  (`rodc_octdec.fold_state`, `comp_state`, `score_rows`, unchanged at module `9c9752b8…`).
  - It must reproduce `gate1_rows.csv.gz` (`5239e6a1…`): columns comp, g1, mg1, p3d_comp and p3d_g1, on the
    same keys, to 1e-12, with identical NaN patterns.
  - G1 in gate 2 is exactly these reproduced fold states.
- **Determinism:** the first outer G2 fit is repeated, and its mean-model predictions on its training rows must
  be identical.
- **Code placement:** gate 2 lives in a new module, `weather.calibration.rodc_gate2`, so `rodc_octdec.py` stays
  byte-identical. It is reached through `cool_season_audit rodc-gate2`.
- **Run:** one run only, after master's pin of the env commit, the module shas and the argv.
