# L2 rung R-L pre-registration: NBS TXN as the 07-12 pre-dawn centre input

Written 2026-10-25, before any NBS row has been joined to an outcome, label, price or market row.

- **Authority:** the owner's decision of 2026-10-25 ("option B"), relayed by the coordinator, who asked for R-L to
  be ready to launch when L12 lands.
- **Evidence class:** development evidence only; no edge claim.
- **Data limits:**
  - Nothing dated after 2026-09-29 is read.
  - Nothing touches MG-2 or L8's branch.
  - L12's fetch is read only. It is never modified or re-run by L2.
- **Code:** `claude/rung0712-20261025`. The R-L joiner, LOYO and score are written after this rule and record its
  sha256 in code (`RL_RULE_SHA256`) before any R-L row exists.

## Why R-L, and why it differs from the tested NBS row

**The register row** (`docs/operations/EXHAUSTION_REGISTER.md` on origin/master @ 46dad240b):
- **S4, NBS, TESTED-NO-INCREMENT** at 00-16: +0.0003 [−0.0004, +0.0011] (SYN §1.3). It is the one precise null
  among the sources.
- 07-12 lies inside 00-16, so **the prior is low**, and this rule says so.

**Why it is still the next 07-12 candidate:**
- **R-H hypothesis 2** (atlas sha `ff7ee231…`, selection evidence): the 07-12 loss is mass on the winning bucket.
  The gap is full size at h07 and flat to h12, so it does not come from intraday observations. NBS TXN ranks above
  HRRR freshness.
- **R-H hypothesis 1** (the gap is spread calibration) was tested as R-I and KILLED at its dev gate (`rungi/ri_summary.md`).
  The precondition R-H set ("after hypothesis 1 has removed the spread component") is therefore discharged:
  hypothesis 1 removed nothing.

**What R-L changes against S4:**

| | S4 (SYN §1.3) | R-L |
| --- | --- | --- |
| Hours | 00-16 pooled | 07-12, the pre-dawn and morning centre |
| What is compared | An increment over MG-1 | A residual input to L2's pooled HGB model P3d (anchored on captured NBM v2_mean), against P3d_N_fix |
| Timing | The SYN candidate form | Point-in-time per row: the newest NBS cycle whose S3 `LastModified` + 10 min ≤ the cutoff h:00 local (L12 corpus, plan `C:\t\l12\fetch_plan.md` sha `22283889…`) |
| Training | One Aug-Sep season (2026 dev) | Blocked LOYO over five seasons (Aug-Sep 2021-25) |

## The feature family (pre-committed, exactly one)

**For a row:** market m (its station from the registry), local target date d, cutoff hour h ∈ {7, …, 12},
t = h:00 local.

**Cycle selection.** Among L12's `nbs` manifest rows for UTC dates d−1 and d (cycles 04Z-19Z):
- keep those with a block for the station whose `status` is `ok`, and `last_modified` + 10 min ≤ t;
- take the newest cycle;
- if none is newer than t − 12 h, the row is missing.

L2 does not apply a stricter margin or other cycle rule.

**Parsing (block bytes as delivered, verified against the manifest `sha256`):**
- `n_txn` = the `TXN` value in the column at **00 UTC of d+1**, read through the block's `DT` and `UTC` rows. This is
  NBS's daytime-maximum slot for local date d. °F, as printed.
- `n_xnd` = the `XND` value in the same column (TXN spread, °F).

**Columns:**
- `n_txn`.
- `n_gap` = `n_txn` − nbm_mean, where nbm_mean is the row's own NBM anchor. In training it is L9's
  `nbm_at_cutoff` (`fh`); on dev it is the captured `usable_v2_mean`.
- `n_xnd`.
- `n_miss` = 1 when there is no eligible cycle, the block's sha256 does not match, the 00 UTC d+1 column is
  absent, or a value is missing or not numeric. Otherwise 0.
  - When it is 1, `n_txn`, `n_gap` and `n_xnd` are NaN.
  - The OLS design maps NaN to 0. HGB takes NaN natively.

**Arms:**
- **B_L** = B_N + `extra_ols` (`n_gap`, `n_miss`).
- **P3d_L** = P3d_N_fix + `extra_hgb` (`n_txn`, `n_gap`, `n_xnd`).
- B_N and P3d_N_fix are R-A's arms, unchanged.
- Fits are per cutoff hour h07-12 on the Aug-Sep 2021-25 training rows, as in R-A.

**Constraints:**
- No other NBS element (TMP, SKY, DPT, P12, …), NBH, cycle rule, margin, column or transform is used.
- Toronto is outside R-A's markets and stays out.

## Data the rung needs

- **Training:** L12's corpus `C:\t\l12\nbs_nbh\` (Aug-Dec 2021-25; only Aug-Sep rows are used), read when L12
  reports the run complete.
- **Dev:**
  - L12's 2026 run, `C:\t\l12\nbs_nbh_2026dev\` (2026-07-30..09-29), from the same fetcher and configuration,
    with its manifest sha recorded.
  - If it is not delivered, R-L stops after gate 2 as **DEV UNTESTABLE**. That is not a kill.
- **Dev point-in-time:** the selection uses t = h:00 local with availability + 10 min ≤ t. Every layout row used
  has `local_hour ≥ cutoff` h, so no NBS value is newer than the row's capture.

## Gates (in order; each stops the rung if it fails)

### Gate 1: parity, and how it will be proven

Gate 1 is inputs only. It runs in two halves, as R-K's Clarification RK-1: 1a before gate 2, 1b before gate 3.

- **1a, on the h07-12 training rows:**
  - NBS coverage (`n_miss` = 0) ≥ 0.95;
  - every used block's sha256 matches its manifest row;
  - `n_txn` within [−40, 130] °F;
  - column check: the median |`n_txn` − nbm_mean| ≤ 3 °F. This compares two forecasts and shows the
    daytime-maximum slot was read.
- **1b, on the dev h07-12 layout rows:** the same checks.
- Failing either half: R-L stops as "parity failed" (not a kill).

**Later (forward), required before any promotion.** Production does not capture NBS, so captured-forward NBS does
not exist. Parity would need:
- one owned parser and cycle selector, imported by both the research fetcher and a forward recorder;
- the recorder's blocks byte-identical to the archive's on the same cycles;
- recorded retrieval time − `LastModified` under the 10 min margin on almost all rows (otherwise the margin is
  widened and R-L re-fitted);
- a snapshot payload stamping the cycle and block sha256 for captured-input replay and release binding.

**Dev evidence alone cannot promote, bind or enter MG-2.**

### Gate 2: LOYO 2021-25, B_L beats B_N at 07-12

- **Rows:** blocked leave-one-year-out (`rung_loyo`), all four arms on identical rows.
- **Statistic:** the mean per row of Brier(B_L) − Brier(B_N), pooled over h07-12, with a date-clustered bootstrap
  (2,000 draws, seed 20261024).
- **PASS** if the upper 95% bound is below 0.
- **Control (refused otherwise):** B_N and P3d_N_fix LOYO rows must reproduce R-A's
  `C:\t\l2\rung0712\emit\loyo_rows.jsonl` (sha `21cacdaa…`): identical keys, every score within 1e-12.
- **Reported:** each hour, and P3d_L − P3d_N_fix.

### Gate 3: dev, P3d_L beats P3d_N_fix at 07-12

- **Population:** scorecard folds 2026-08-01..09-29, scored 08-15..09-29.
- **Statistic:** dR = mean_cell(Brier_P3d_L − Brier_P3d_N_fix) / mean_cell(Brier_market), ALL markets, h07-12
  pooled, with date-clustered 95% intervals (2,000 draws, seed 20260921).
- **Scope:** snapshots covered by B_N, B_L, P3d_N_fix and P3d_L.
- **PASS** if the upper bound is below 0.
- **Reproduction controls (refused otherwise):**
  - B_N and P3d_N_fix dev files must be byte-identical to R-A's (`83cf9bbe…`, `cd0034b9…`).
  - MG-1's 07-12 control must give 0.012.

### Gate 4: against the MG-2 pre-13 arm (MG-1 + L6 stack)

- **The comparator:** the incumbent pre-13 arm is MG-1 + L6 stack (frozen part `07a67425…`, L6 nowcasts
  `3806687c…`), scored as in R-F and R-G.
- **Statistic:** P3d_L − L6 on gate 3's statistic and scope.
- **Reading:**
  - **WIN** if the 07-12 upper bound is below 0 and no hour h07-h12 has a lower bound above 0.
  - **HARM** if the lower bound is above 0.
  - **NULL** otherwise.
- **Caveat carried from R-F:** L6's frozen coefficients are in-sample on this window.
- **If WIN:** L2 drafts, but does not apply, a dated MG-2 pre-13 Clarification and the forward-parity plan. Nothing
  else.

### Reported only (never a gate)

- Each hour and each market.
- B_L − B_N on dev.
- `n_miss` rates.
- The selected cycle's age distribution.

## PRE-REGISTERED KILL

If gate 2 or gate 3 fails, NBS TXN is closed as a 07-12 centre input.

Concretely, no other TXN or XND transform, cycle rule, margin or column is run as a centre input at 07-12 on B_N,
P3d_N_fix or any NBM-anchored arm under any rung name. Other NBS elements and NBH are not reopened by this rule;
they would need an owner ruling.

A gate 1 failure, or a missing 2026 corpus, stops R-L without a kill.

## Outputs

- `C:\t\l2\rungl\loyo\`: gate 1a and gate 2.
- `C:\t\l2\rungl\emit\`: gate 1b and the dev distributions.
- `C:\t\l2\rungl\score\rl_score.json`.
- `docs/research/l2-pooled-residual-2026-10-24/rungl/` holds this rule and the summary.
