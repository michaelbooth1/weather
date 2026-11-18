# R-ODC and X13 against the market on the released cells: a kill-only P0 (ledger row 103, lane L16, 2026-10-31)

**Status:** DRAFT. Written before any read for this test. It reads no feature, outcome, label or price on any date
after 2026-09-29. It is frozen only when the coordinator approves it, and the run needs main's admission.

**Evidence class:** kill-only, on released dates (DECISION_LOG 2026-10-30; MODEL_IMPROVEMENT_METHOD §5 rule 10).
It can kill or describe. It never supports an edge claim, a promotion or a forward-test shortcut. The words "edge"
and "beats" are used here only as the name of the effect size in EXHAUSTION_REGISTER §6.

## 0. Claim check and kill check (done before this draft; nothing read but documents and code)

**No running test claims these cells for R-ODC.**

- Row 72 (R-ODC forward, P1 only, frozen) is serve parity only. It reads no label and no price, and it is strictly
  forward.
  - Prereg `claude/rodc-forward-prereg-draft-20261029` @ `b6b855b4c14cc58ad98d3ebc797f6a5f3ee550d2`, file
    `docs/research/rodc-forward-prereg-2026-10-29/prereg-draft.md`, sha256
    `f6ae5d798b2ed399272ddbe7df4b037a8af7d900f3eecd012041f4c1fd08f833`.
  - The prereg's line 102 states D0 = freeze + 1 = 2026-10-31, strictly forward, and it reads no dev-window date.
  - Its scorer `claude/rodc-forward-scorer-20261029` @ `2048c2f496680dd705f47dcc962fdd53dcaaa7d7`
    (`rodc_forward_scorer.py` blob `a611bb810a59169ca62672f710033e1cc46d317b`) enforces this. `check_look` refuses
    any date outside [D0, look), and the look is on or after 2026-12-15.
- Claim check `claude/claim-check-0930-1014-20261030` @ `31b9218b1`,
  `docs/research/iterate-faster-2026-10-30/claim-check-0930-1014.md`, records three claims:
  - C11 (L6_G and R-ODC P1): D0 10-31, never backfilled, no claim here.
  - C9 (MG-2 / B-1): no claim on these dates.
  - C8 (PT-1): no MG-2 scoring, nor of its bound components as composed. That is why section 3 builds both arms
    without G1, P3d_H, `blend_l6_H` or SM-L6.
- Rows 65, 69 and 70 are history only (Oct-Dec 2021-25). Row 85 is history only.
- STATE_OF_PLAY line 70 says only "R-ODC P1 (row 72) runs".
- WORKSTATION_STATE 2026-10-30 records the coordinator's ruling (a): R-ODC is untestable against the market on
  Aug-Sep. It also records that master named "an R-ODC kill-only market read on 10-01..10-14" as the path if the
  owner released these dates. The owner released them (DL 2026-10-30), and master dispatched this test on
  2026-10-31.

**Kill check: grepped by name in the register, digest, SoP and WORKSTATION_STATE for `R-ODC` and `X13`.**

- **EXHAUSTION_REGISTER X13** (L9 ladder: overnight low, dewpoint, hour-pooled slopes) is KILL on Aug-Sep and
  pooled history LOYO, against OLS + floor (EF §10ac). It has never been read against the market. Its reopen line
  is "overnight low and dewpoint help in Oct-Dec: an Oct-Dec rung under R10".
- **Row 95 X13** (L17, Oct-Dec LOYO on the SM-L6 residual, receipt 2507dc6d after the D3 rerun) is a sub-edge
  SCREEN: Δ [−0.00169, −0.00058], edge 0.00562. Master accepted the label. It earns only a forward prereg, and it is
  history only, never market.
- **Row 85** (R-ODC-low + t_minus_low on SM-L6) is DROP, redundant with RATE-0712 (Spearman 0.887); register X71.
  That is a history read of a different construction.
- **The findings digest** has no hit.
- **No R-ODC or X13 read against the market exists anywhere.** Rows 74-76 state that R-ODC is untestable on
  Aug-Sep, and the K = 17 sweep of row 78 does not contain them.

**Intake (method §5 rule 14).** This is a single-source (METAR) T+0 read on the US11, so it needs a stated S0
mechanism by which the market lacks the information. The stated mechanism is a hypothesis only, and the rule-14
prior is that the information is priced.

- The hypothesis: the morning boundary-layer state (the overnight minimum and the near-surface moisture) sets the
  day's warming range. A market anchored on forecast highs and the running max may under-use it before the high is
  set.
- The authority for opening the read is master's 2026-10-31 dispatch. Open point 4.

## 1. Population (r80 layout, read only)

- **Layout:** `C:\t\r80\build\layout`, manifest sha256
  `d7601613027d42673ca4259bb4df8526022f68d4286655962178d288fa635c42` (copy in
  `C:\archive\ruled-out\row-80-rise-t3r3-replication\receipts\layout_manifest.json`).
  - It is hashed before and after the run. Any change refuses the receipt.
  - `C:\t\r80` is never written.
  - The dev layout `C:\swarm\v3layout` (manifest `4d53fdbd…`) is read only, for controls C-a and C-b, and is
    re-hashed after the run.
- **Dates:** local target dates 2026-10-01..10-14 (the boundary is the local target date). There are 14 dates.
- **Markets:** the US11 in °F, with **Austin 10-03 dropped** (C7).
- **Snapshots:** local hours **07-12 only**, the hours R-ODC was built and frozen for (row 72 scorer `HOURS`).
  No other block is chosen after the fact.
- **Market, outcome and band geometry:** as row 80 and `rule_mr_sweep.md` §1, run through `mr_sweep` at pin
  `8bb0f9563582885c4d01d34b67476f2563260e43`.
  - The market is m = the layout's `p_market_yes` (Gamma YES), never a CLOB `last_trade_price`.
  - The outcome is y = the band winner. The market error is e = y − m.
  - μ_m, σ_m (floor 0.25 °F²) and z_b are as defined there.
- **Feature inputs:** the snapshot's own captured `sources.metar.data`, from the r80 staged export that row 80 read.
  - Export SHA256SUMS `c0246a6593655da04b7e600385174e5a1d1cd5b36217896cde13c7cceceb73fa` is checked at start.
  - The export is read only. No cache is rebuilt and nothing is downloaded.
- **Validity (mr_sweep §2, METAR):** a value is used only if `fetched_at` ≤ `captured_at_utc`, `report_time` ≤ the
  capture time and `target_date_match` is true. Each METAR row also needs an instant at or before the capture,
  under the odc rule 2 below.
- **Pooling:** the decision pools the 14 dates, as row 80 did.
  - Per-stratum Δ is also reported, never deciding: `pre` 10-01..10-09 and `post` 10-10..10-14 (as the atlas,
    master ruling 2026-10-31 (a)). Open point 5.

## 2. Coverage floor and power at edge (D3, computed first)

**Coverage floor (row 80's).** An arm needs at least 10 scored dates and at least 1,000 population snapshots, or it
is UNTESTABLE. An UNTESTABLE arm keeps p = 1, still counts in K, and is never topped up with other dates.

**Projected power at edge** = Φ(Δ_edge / SE − 1.96), with Δ_edge = √0.05 = 0.2236 (EXHAUSTION_REGISTER §6, market
residual). Inputs:

- **SE:** row 80's per-date SE on the same 14 dates and the same layout. The source is label receipt
  `C:\archive\ruled-out\row-80-rise-t3r3-replication\label\label.json` (sha256 `235736c9…`), which is computed
  from look receipt `a91915e52cbbfebf12ab650d4ae07d95082415727c767120f52f757fd4e8feda`.
  - Date-clustered SE: 0.034994.
  - REV-2 circular block-3 SE (B 2000, seed 20261024): 0.032194.
  - The wider of the two, 0.034994, is used.
- **Projected power:** Φ(0.2236 / 0.034994 − 1.96) = **0.99999**. It is ≥ 0.5, so the result is not forced to
  UNTESTABLE.
- **Caveat:** row 80 measured hours 13-16, and these arms read 07-12. Power falls below 0.5 only if the 07-12 SE
  exceeds 0.2236 / 1.96 = **0.114**, which is 3.26 times row 80's. At SE 0.07 the power is still 0.89.
- **Sizes the read can see:** at row 80's SE, power is 0.8 only for Δ ≥ 0.098 and 0.5 for Δ ≥ 0.069. Every effect
  in the R-ODC / X13 family so far is sub-edge on history: row 69 dR −0.000876, row 95 X13 |Δ| ≤ 0.00169. So the
  expected informative outcome is "KILL at edge size". A sub-edge effect cannot be detected here and is not claimed
  either way.

**Binding in-run power gate.** The module recomputes the power from the run's own two bootstrap SDs, using the
larger, before any label is assigned. If that power is < 0.5, the arm's only possible labels are **UNTESTABLE at
edge** or **UNTESTABLE at sub-edge**. In that case no KILL or SCREEN is assigned, and the arm is not re-run.

## 3. Arms (K = 2, fixed; no arm added or removed after row 103)

Both arms are **market-anchored type C tilts** (mr_sweep §4): x = μ_m + g, so s_b = g · (z_b − μ_m) / σ_m², and
c_b = Σm · m̃_b · exp(s_b/σ_s) / Σ m̃ exp(s/σ_s).

- **g** is a frozen linear increment in °F. It is fitted **once, on history only**, never on any 2026 date.
- σ_s is the sd of s over the arm's covered fit-table entries. No outcome enters c.
- Neither arm composes G1, P3d_H, `blend_l6_H`, SM-L6, MG-1 or MG-2 (C8). This is why R-ODC enters as its linear
  increment and not as row 69's HGB G2. Open point 1.

**Arm 1, R-ODC** (the two R-ODC columns, as frozen in row 72's serve code)

- **Columns:** (low_so_far, dewpoint_c).
  - Built by `weather.calibration.odc_metar_features.odc_features` from
    `claude/rodc-odc-metar-features-20261029` @ `0e11b018fda76125425c8ebdd21560ee10289d70`.
  - Its blob is `1cc4d565468bf4959137a8f6f6cec5b10adfce24`. It is merged read-only into the run branch, and its
    sha is checked at start.
  - Arguments: cutoff_hour = h, now = the snapshot's `captured_at_utc`, and the market's tz and native unit.
  - `check_bounds` must pass for every (market, date) over 07-12, or the run refuses. This is odc rule 6.
- **Snapshot choice:** each layout snapshot at local hour h, with now = its own capture time (`as_of_capture`).
  The P1 `last_in_hour` rule is not used, because the P0 population is the layout's snapshots.
- **Denver** is uncovered for this arm, as frozen in row 72 (KDEN vs KBKF, DL 10-23).
- **Increment:** g = β_h,k · (low_so_far − L̄_h,k) + γ_h,k · (dewpoint_c − D̄_h,k).
  - β and γ come from one OLS per (market k, hour h) of the BASE residual r = final WU high − BASE.
  - The two regressors are centred on their training means.
  - **BASE** is L3's `ols_floor` per (market, centre, hour), bit for bit. It is the base of row 69 / L9 rung 1,
    fitted in sample.
  - The rows are the L9 ladder's Oct-Dec rows: 2021-2025, centres 10-10, 10-25, 11-09, 11-24 and 12-09, hours
    07-12. The training columns are the history construction of row 69's `rodc_gate2` (at
    `188d5c382ac041a6ae276eebcac2b957463f885a`).
  - BASE is used only to form the training residual. At serve time g needs only the two columns and the frozen
    (β, γ, L̄, D̄).

**Arm 2, X13** (overnight lows plus dewpoint, the L9 construction)

- **Columns:** (low_so_far, low_prev_evening, dewpoint_c).
  - The two lows come from `ols_floor_ladder.overnight_lows` (`claude/stack-l9-20261025` @
    `8167b89a898699c2103cd6be136cc09ee9702c85`, blob `eedd3d32f5044cf797ba0b053afec83d580974be`).
  - At serve time the function is fed the snapshot's captured METAR rows of D and D−1 with an instant ≤ the
    capture, converted in memory to (`minute_of_day`, temperature). This is the row 95 A2 adapter pattern, and no
    other source is opened.
  - dewpoint_c is the odc value of arm 1.
  - A snapshot without a D−1 evening row is uncovered for X13.
- **Markets:** all of the US11 (X13 has no Denver exclusion).
- **Increment:** g = Σ_j β_j,h,k · (col_j − mean_j,h,k), with the same OLS, rows, BASE and centring as arm 1.
- **The two arms share** low_so_far and dewpoint_c and are positively dependent. Disclosed.

**Fit stage, first and separately admitted (history only).**

- `fit` writes `coef.json`: every (k, h) β, mean, n and residual sd, plus the input manifest shas.
- Its sha256 goes to the coordinator and into a row 103 note before the look stage may run.
- `look` refuses unless `--coef-sha` matches.
- Fit controls (section 5, C-f) run inside `fit`.

## 4. Statistic and decision (one look)

- **Statistic:** `rule_mr_sweep.md` §5 unchanged, through `mr_sweep` at pin `8bb0f956…`, as row 80 did.
  - **Disagreement placebo:** 20 derangements, seeds 20260921 + j, donors within (market, local hour).
    Fit table = score table = the 14 dates. This is label-free, as in row 80 §2.
  - **Correlations:** ρ_c and ρ_pl,j over the population P.
  - **Primary statistic:** Δ = ρ_c − mean_j ρ_pl,j.
  - **p:** one-sided, from 10,000 date-cluster draws (seed 20261024; draw b uses placebo j = b mod 20).
- **D3 interval (C3 REVISION-2 §2, as row 80's label):**
  - The date-clustered interval (as above) and the REV-2 circular block-3 interval are both computed.
  - The block-3 construction is `c3_kill_tier.block_counts`, BLOCK_LEN 3: ⌈n/3⌉ blocks of 3 consecutive present
    dates, wrapping, truncated to n; B 2000, seed 20261024. The module is on
    `claude/c3-t1-fv-kill-tier-20261031` @ `b1d8e65fd577b16da8f3a278cb80fa7ea1e0f4ad`, blob
    `8f4f9d194dc62cb4cd481e20005ce6ae75d1f879`, imported only.
  - **The wider interval is used:** the min of the two lower bounds and the max of the two upper bounds. SE is the
    larger bootstrap SD (ddof 1).
- **BH (Benjamini-Hochberg)** at q = 0.10 over the K = 2 one-sided p-values. An UNTESTABLE arm keeps p = 1.
- **Labels per arm, assigned in this order:**
  1. **UNTESTABLE:** the coverage floor fails.
  2. **UNTESTABLE at edge / at sub-edge:** in-run power < 0.5.
  3. **KILL at edge size:** the wider upper bound < 0.2236.
  4. **SCREEN (descriptive, forward prereg only):** BH rejects and the wider lower bound > 0. This label earns at
     most a forward pre-registration to master. For R-ODC that path already exists (row 72).
  5. **NOT KILLED at edge (descriptive):** anything else.
  None of these labels is an edge claim.
- **Reported, not deciding:**
  - ρ_c and mean ρ_pl with their intervals;
  - the c-deranged diagnostic (mr_sweep §5);
  - per-market Δ;
  - per-hour Δ (07..12);
  - per-stratum Δ (pre / post);
  - coverage per arm;
  - for R-ODC, the n of `no_metar_row` and of skipped rows.
- **One look.** There is no second look, extension, re-fit, hour change or arm change. A KILL closes the arm *as a
  market-residual tilt on these cells only*.
  - It does not close row 72 (serve parity), which tests something else.
  - Register wording is per rule 15. A kill of arm 1 measures R-ODC's linear increment, not row 69's HGB G2. The
    G2 form is labelled CLOSED-BY-RULE (reopenable) only if master extends the kill to it.

## 5. Controls (all must pass before the look stage reads any r80 label or price; any miss refuses the run)

| id | control | target | source |
| --- | --- | --- | --- |
| C-a | served positive control on `C:\swarm\v3layout` (dev 08-15..09-29, read only) | served R 1.774 / 1.526 to all printed digits | MR gate `rule_mr.md` `37cb46be…` controls; atlas row 101 |
| C-b | MG-1 07-12 excess on the same dev layout | 0.0120 | `37cb46be…` controls (MG-1 on dev ≤ 09-29 is not C8) |
| C-c | w = 0 / zero-tilt identity: g ≡ 0 gives c = m on every r80 band to 1e-15, and every derived placebo equals m | exact | `37cb46be…` "w = 0 identity"; label-free |
| C-d | D3 machinery: from row 80's archived `rows.jsonl` (sha256 `54fd5966…`), reproduce `label.json`'s date-clustered and block-3 intervals and SEs | to 1e-12 | row 80 label (`235736c9…`) |
| C-e | synthetic: fit = score P0 check (row 80) and a planted-signal toy (c − m = κ·e on synthetic rows → Δ lower bound > 0; κ = 0 → covers 0) | both pass | row 80 §5 / C3 toys |
| C-f | fit stage: BASE equals L3 `ols_floor` per-row on identical Oct-Dec rows at centre 11-24 (EF §10ac positive control, 5.3e-13); placebo N(0,1) column gives g with fitted |β| reported | ≤ 1e-9 | EF §10ac |
| C-g | feature sanity on r80 (label-free): odc `check_bounds` passes; low_so_far ≤ layout high_so_far where both exist | no violation | odc rule 6 |

## 6. Module contract (built after this rule is approved; not written yet)

- **Path:** `tools/research/released_window/rodc_released_p0.py` (new) with
  `tests/reporting/test_released_window_rodc_released_p0.py`.
  - It is built on a run branch `claude/rodc-released-p0-run-20261031`, off this rule's tip.
  - The run branch merges, read-only, `0e11b018f` (odc), `8167b89a8` (ladder), `b1d8e65fd` (c3_kill_tier), the
    `8bb0f9563` mr_sweep pin and `d155a665a` (released-window tools). Every imported blob is sha-checked at start.
- **B-bound files:** none is edited (mg2_*, r0_*, l6_stack, mg1, dev_scorecard*, loss_atlas, mg_serve_core,
  b_scorer and the rest).
  - B-bound imports are named and sha-checked at start: `mg_serve_core.wu_whole_f` via odc, and
    `r0_ols_floor_challenger` via the ladder BASE.
- **No network:** the module imports no `socket`, `urllib`, `http`, `requests`, `ssl` or `ftplib`, and a test
  asserts it statically.
- **Writes only under `--out`:**
  - `--out` must not exist and must sit below `C:\t\l16\rodc\`;
  - the receipt is exclusive-create;
  - nothing is written to production paths, `data/`, `C:\t\r80` or the layouts.
- **Origin assertion, in module:** the run refuses unless `PYTHONPATH` equals `<run tree>\src` and
  `weather.__file__` resolves under it (the editable-.pth trap). The run uses cwd = RepoRoot = the run tree.
- **Stages:** `fit` (history only) and `look` (requires `--coef-sha`, refuses a second look, refuses any date
  outside 10-01..10-14 or Austin 10-03).
- **Allowlist entry on the run branch:** in the three places used for `served_market_blocks` (`ba26d795e`), which
  are `.codex/hooks/pre_tool_use_host_load.py`, `scripts/ops/workload_admission.ps1` and
  `tests/operations/test_r0_full_year_admission.py`. **Main admits. The lane never self-admits.**
- **Heavy work:** both stages run only through `scripts\ops\workstation_heavy.ps1 -Queue`.
  - Pytest uses `--basetemp` under `C:\t\l16`, deleted afterwards.
- **Archive:** everything goes under `C:\archive\ruled-out\row-103-rodc-released-p0\`, exclusive-create with
  SHA256SUMS, whatever the label: rule, coef, receipts, rows, logs and the code bundle.
- **Outputs:**
  - `receipt.json`: code head, dirty flag (dirty refuses), every sha, coverage, the statistics, the BH table, the
    power and the labels;
  - `rows.jsonl`: one row per (arm, date) with the sufficient sums for (c − m, e) and each (c_pl,j − m, e), so that
    D3 can be re-derived.

## 7. Open points (for the coordinator)

1. **The R-ODC arm form.** Row 69's G2 is HGB columns inside P3d_H / `blend_l6_H`. Scoring it, or G1, against the
   market on these dates would compose bound components (C8), and the l6 stack is B-bound. This rule therefore
   tests R-ODC's frozen serve columns as a linear increment on L3's OLS + floor residual. Accept, or rule
   otherwise.
2. **Capture-time feasibility.** If the r80 export's captured METAR lacks D−1 rows, X13 is UNTESTABLE by the floor.
   If it lacks `obsTime` or the raw group, R-ODC is UNTESTABLE the same way.
   - This is checked by the module's coverage count, not by reading values before approval.
3. **The 07-12 SE is unmeasured.** The projected power uses row 80's 13-16 SE. The binding power gate is the in-run
   one (section 2).
4. **Rule-14 intake.** The mechanism in section 0 is a hypothesis. Opening the read rests on master's dispatch.
5. **Pre / post.** The decision pools 10-01..10-14 as row 80 did, and the strata are reported only. If master's
   ruling (a) for the atlas (never pooled; order 6 excludes 10-10..10-14) is meant to bind candidate reads too,
   the decision population becomes 10-01..10-09 (9 dates). That is below row 80's 10-date floor, so both arms
   would be UNTESTABLE.
6. **Ledger number.** Row 103: 102 is L14's S31 v2 row, seen on L14's local worktree and not yet pushed. No row
   above 101 was on any remote branch at 2026-10-31.
