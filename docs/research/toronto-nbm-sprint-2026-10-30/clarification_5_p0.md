# Toronto NBM sprint: clarification 5, the P0 and w-gate implementation (lane L8, 2026-10-30)

This records the coordinator's rulings of 2026-10-30 on row 77's P0. It is committed and pushed **before any
dev-window read** (no Toronto dev snapshot, price or label has been opened under the sprint). It
**supersedes the placebo text of `clarification_toronto_mr.md` §2 and the placebo-detail table of
clarification 2 §2.** Everything else stands.

## 1. Run env and code

- **Pin:** `claude/loyo-screen-runenv-20261030` @ `8bb0f9563582885c4d01d34b67476f2563260e43`. It carries L3's
  `mr_sweep` (disagreement placebo) and the replay-reader fix that skips malformed lines.
- **Malformed lines:** a replay line that does not parse is skipped and listed in the receipt (file, line
  number, length, snapshot ids), as `mr_sweep.extract_features` does.
- **Driver:** a lane script outside the repo. It uses only in-process additions, with no repo edit:
  - the Toronto table is built in memory as a `dev_scorecard_data.Layout`, then wrapped in
    `dev_scorecard.Table`;
  - `mr_gate.BLOCKS["07-16"] = (7, 16)` is registered so that `gate_candidate` runs on the sprint's hours;
  - `pooled_residual_model.MIN_SCALE` = 5/18 C, as in S2.

## 2. Placebo and P0: L3 §5 exactly

The source is `rule_mr_sweep.md` §5, sha256 `85f8192c…1956` (@ `d43d90a4a`). The code is
`mr_sweep.donor_positions`, `disagreement_placebo`, `date_sums`, `boot_counts` and `paired_delta`.

- **Placebo:** c_pl,j = m + (c − m)[donor], from `market_blend.placebo_vector`.
  - It is a derangement of dates within (market, local hour) on the **full fit table** (burn-in + scored).
  - Donor snapshot min(k, n − 1); **a band-count mismatch refuses the run.**
  - Clip to [`market_blend.EPS`, 1], then renormalise each snapshot to sum(m).
- **Seeds:** J = 20, seeds 20260921 + j, j = 0..19.
- **Bootstrap:** dates resampled, B = 10,000, seed 20261024. Draw b uses derangement b mod 20, and Δ*_b is
  paired on the same draw.
- **Population:** scored snapshots (08-15..09-29, hours 07..16) where the arm is covered and every donor is
  covered.
- **Statistics:** pooled Pearson over (snapshot × band) entries:
  - ρ_c = ρ(c − m, y − m);
  - Δ = ρ_c − mean_j ρ_pl,j.
- **P0 PASS iff both** (decision as in `clarification_toronto_mr.md` §3, now on these draws):
  1. the lower 95% bound of ρ_c > 0;
  2. the lower 95% bound of Δ > 0.
- **No multiplicity correction across the two arms.** L3's BH over K = 17 belongs to its own sweep family.
  Both arms' one-sided p-values are reported.
- **Diagnostic only:** the date-deranged (c itself) placebo with seed 20260921, its interval and whether it
  covers 0.

## 3. w gate (only for an arm whose P0 passes)

- **Machinery:** `mr_gate.gate_candidate(name, "07-16", fit_t, score_t, c_fit, cov_fit, p_placebo_fit=c_pl,0)`,
  the 37cb46be machinery.
  - Placebo seed 20260921.
  - `market_blend` walk-forward log pool, w on grid 0..1, gap 1 day, fit on dates <= d − 2 including burn-in.
- **PASS iff all four hold:**
  - mean w >= 0.05;
  - the date-clustered upper bound of blend R < 1;
  - the paired upper bound of blend − placebo Brier < 0;
  - the paired upper bound of blend − floor-only Brier < 0.
- `gate_candidate`'s internal P0 uses the old placebo, which §2 supersedes. It is ignored.
- **Controls:**
  - 37cb46be's C1 (served R 1.774 / 1.526) and C2 (MG-1 excess) are values of the US 11-market table and
    do not exist for Toronto. They are not run.
  - C3 is run per arm and refuses on a miss: the w = 0 pool equals m to 1e-12, and R = 1.

## 4. The Toronto table

- **Snapshots:** Toronto replay snapshots (`replay-inputs-le0929`, SHA256SUMS `d9c2ed46…8b82`) whose
  `captured_at_local` date equals the target date D. D is in 08-01..09-29 and the local hour is in 07..16.
- **Market vector m:** per clarification 2 §1.
  - The latest tape group with captured_at at or before t_c and at most 10 minutes old, every bin's
    `book_time_utc` <= t_c, falling back to earlier groups within 10 minutes; otherwise the snapshot is
    dropped and counted.
  - YES displayed price: the midpoint when both sides exist and spread <= 0.10, else `last_trade_price`,
    else the tape midpoint. If YES is absent, 1 − the same quantity on NO.
  - Bins must partition the integers.
  - m is as captured, not renormalised.
- **Bands:** the tape bins in C, taken from `parse_temperature_band` and cross-checked against
  bin_kind/value/value_hi/unit, with a failing bin dropping the snapshot.
  - kind lte/eq/gte;
  - `high` is X for lte, hi for eq, and 999 for gte.
- **Label:** the WU whole-C high from L14's two label files (sha256 `1ced925a…`, `c9e16b1d…`). The winner is
  the band that contains it.
- **Floor:** F(t_c) is the max over the snapshot's own `sources.metar.data.rows` with `report_time` <= t_c
  and local date D. Temperature is the raw T-group when present, else `temp_c`. F goes in `high_so_far`, so
  the table's rule-4 impossible mask is floor(F + 0.5).
- **Served:** `p_served` is the served `recorded_distribution` mapped to the bins. It is not used by any
  statistic here.
- **Fit and score tables:** fit table 08-01..09-29 (burn-in 08-01..08-14); score table 08-15..09-29.

## 5. Arms at serve time (frozen)

- **Fitting:** each arm (clarification 4 spec) is fitted once per hour on every row of its S2 Aug-Sep 2021-25
  frame. Climatology support is the training labels ±5.
- **Serving:** the snapshot at t_c uses the model for its local hour h. Every input must be received by t_c:
  - **N:** the newest NBP with `last_modified` <= t_c among D-1 13Z, D-1 19Z, D 01Z, D 07Z. Source: the L14
    corpus manifest, parser v2.
  - `nbp_sd`.
  - **NBH:** the newest cycle with `last_modified` <= t_c, from `C:\t\l12\nbs_nbh_2026dev`.
    `nbh_rest_max` is taken over valid times in (t_c, 23:00 local of D].
  - **F** = F(t_c).
- **Output:** the integer-C distribution is mapped to the bins by summing (lte: k <= X; eq: lo <= k <= hi;
  gte: k >= Y), giving c.
- **Coverage:** a snapshot with any missing arm input is uncovered (c = m there; excluded by §2's
  population).
- **Version shift:** the dev NBP/NBH are V5.0, while training was V4.0-V4.3. Disclosed, not corrected.

## 6. Outputs

- **Receipt:** run-env HEAD (must be 8bb0f9563), script sha, input shas, skipped lines, drop counts,
  coverage, every statistic and the verdict per arm.
- **Per-date rows:**
  - P0: per (arm, date), n entries, n snapshots, and the six sufficient sums for c and for each of the 20
    placebos;
  - w gate: `gate_candidate`'s per-date paired differences and w by date.
- **Execution:** run once.
