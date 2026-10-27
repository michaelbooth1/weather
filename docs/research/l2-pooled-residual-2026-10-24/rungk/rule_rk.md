# L2 rung R-K pre-registration: the HRRR 13-16 hourly path as a centre input

Written 2026-10-25, before any HRRR row has been joined to an outcome, label, price or market row.

- **Authority:** the owner's decision of 2026-10-25 ("option B"), relayed by the coordinator, who gave the R-K GO.
- **Evidence class:** development evidence only; no edge claim.
- **Data limits:**
  - Nothing dated after 2026-09-29 is read.
  - Nothing touches MG-2 or L8's branch.
  - L13's fetch is read only. It is never modified or re-run by L2.
- **Code:** `claude/rung0712-20261025` (`rk_hrrr_columns`, the R-K emit and score). This rule's sha256 is recorded
  in code (`RK_RULE_SHA256`) before any R-K row exists.

## Why R-K differs from the tested-underpowered HRRR rows

**The register rows** (`docs/operations/EXHAUSTION_REGISTER.md` on origin/master @ 46dad240b):
- **S6, single run, TESTED-UNDERPOWERED.** HRRR-latest at 06-09: −0.0005 [−0.0058, +0.0039], 3/8 (SYN §1.3).
  The 79a error kernel is 1.308/1.251x the market (EF §10h). The served model selects no HRRR column.
- **S7, multi-run / time-lagged ensemble, TESTED-UNDERPOWERED / NULL.** T9 "adds nothing as centre or spread".

R-K is not a re-run of S6 or S7.

| | S6 / S7 | R-K |
| --- | --- | --- |
| Source | Production's Open-Meteo `hrrr_high` daily value (latency about 2.5-3.5 h) | Native 3 km AWS HRRR `wrfsfc` messages at the station's nearest grid point (L13 corpus, plan `C:\t\l13\hrrr_plan.md` sha `afe24c5f…`) |
| Timing | The captured value | Point-in-time by construction: at snapshot t = h:00 local, the newest hourly cycle whose every needed forecast hour has S3 availability + 10 min ≤ t (plan §3), so typically t − 2 h |
| What the feature describes | The day's high from one run | The **hourly path from t to 17:00 local**: remaining-window maximum and cloud cover, which is what the afternoon decision is about |
| Hours | 06-09 | 13-16 |
| Model | Increment over MG-1 or the served model | A residual input to L2's pooled HGB model **P3d** (anchored on captured NBM v2_mean), against P3d_N_fix |
| Training | One Aug-Sep season (2026 dev) | Blocked LOYO over five seasons (Aug-Sep 2021-25) |

- §10q's "no increment" for HRRR stands at 06-09. R-K tests a different estimand.
- Dev DPT and wind are not fetched (plan §2), so they are outside this rule.

## Selection, stated plainly

R-K was chosen after looking at the dev window:
- R-H's atlas (sha `ff7ee231…`, selection evidence) shows P3d_N_fix's 13-16 excess concentrated on cold-path rows:
  +0.0183 [+0.0139, +0.0225], 47% of the excess.
- R-H also showed that the captured Open-Meteo HRRR high does not localise the loss: HRRR−NBM cold / near / warm
  were +0.0105 / +0.0091 / +0.0074.

The LOYO gate (2021-25) is the only gate on data not yet looked at. The dev gates can only refute.

The R-J kill (trajectory family, afternoon) does not cover HRRR. It is a different source.

## The feature family (pre-committed, exactly one)

**For a row:** market m (station from `stations.json`), local target date d, cutoff hour h ∈ {13, 14, 15, 16}.
- **Selection:** take the L13 selection (d, station, `hour_local` = h) from `selections.jsonl`, with its `cycle_utc`
  c and `fhs`.
- **TMP:** for each fh in `fhs`, take the manifest message (`key` = `hrrr.<c:%Y%m%d>/conus/hrrr.t<c:%H>z.wrfsfcf<fh:02d>.grib2`)
  with `idx_record` starting `TMP:2 m above ground` and its station's `nearest` value. Convert K to °F:
  (K − 273.15) × 9/5 + 32.
- **TCDC:** take the `TCDC:entire atmosphere` messages for the same (c, fh) and their `nearest` values, in %.

**Columns:**
- `k_max` = max over fhs of TMP °F: the HRRR maximum over valid times in [h:00, 17:00 local].
- `k_gap` = `k_max` − nbm_mean, where nbm_mean is the row's own NBM anchor. In training it is L9's
  `nbm_at_cutoff` (`fh`); on dev it is the captured `usable_v2_mean`.
- `k_tcdc` = mean over fhs of TCDC %.
- `k_miss` = 1 when the selection has no cycle, any needed message is absent, or any value is not finite.
  Otherwise 0.
  - When it is 1, `k_max`, `k_gap` and `k_tcdc` are NaN.
  - The OLS design maps NaN to 0, as R-G does. HGB takes NaN natively.

**Arms:**
- **B_H** = B_N + `extra_ols` (`k_gap`, `k_tcdc`, `k_miss`).
- **P3d_H** = P3d_N_fix + `extra_hgb` (`k_max`, `k_gap`, `k_tcdc`).
- B_N and P3d_N_fix are R-A's arms, unchanged: the same inputs, the as-of-capture snapshot rule and WU whole °F.
- Fits are per cutoff hour h13-16 on the Aug-Sep 2021-25 training rows, as in R-A, R-G and R-J with
  `hours=(13, 14, 15, 16)`.

**Constraints:**
- No other HRRR variable, block statistic (the 3x3 block is not used), margin, cycle rule, window end, transform or
  interaction is used.
- L13's selection is used as delivered. A stricter margin is not applied.

## Data the rung needs

- **Training:** L13's corpus `C:\t\l13\hrrr\`, Aug-Sep 2021-25, read when L13 reports the run complete.
- **Dev (08-01..09-29 2026):**
  - The current L13 run covers 2021-25 only.
  - Gates 3 and 4 need the same fetcher, configuration and point-in-time rule run for 2026-07-30..2026-09-29
    (`--years 2026 --months 7,8,9`; the fetcher refuses dates after 2026-09-29).
  - The output goes to its own directory, with its manifest sha recorded.
  - That run is L13's, on the coordinator's word. L2 does not fetch.
  - Captured Open-Meteo `hrrr_high` is **not** a substitute: it is a different product and timing.
  - If no 2026 corpus is delivered, R-K stops after gate 2 as **DEV UNTESTABLE**. That is not a kill.
- **Dev point-in-time:** the selection is made at t = h:00 local with availability + 10 min ≤ t. Every layout row
  used has `local_hour ≥ cutoff` h, so its capture is ≥ h:00. No HRRR value is newer than the row's capture. The
  rest of the inputs are P3d_N_fix's as-of-capture inputs.

## Gates (in order; each stops the rung if it fails)

### Gate 1: parity, and how it will be proven

- **Now (dev): mechanical checks.** Train and dev come from one fetcher and one selection rule. The gate requires,
  on the h13-16 rows:
  - HRRR coverage (`k_miss` = 0) ≥ 0.95 of the training rows;
  - HRRR coverage ≥ 0.95 of the dev rows;
  - every used message's identity (variable, cycle, fh) matches its key;
  - TMP within [−60, 130] °F.
  - Failing any of these: R-K stops as "parity failed" (not a kill).
- **Later (forward), required before any promotion.** Captured-forward HRRR does not exist yet.
  - Parity is proven only by L13's plan §8:
    - one owned implementation of the decoder, geometry and `select_cycle`, imported by both the research fetcher
      and a forward recorder;
    - the recorder's point records byte-identical to the research fetcher's on archived cycles;
    - recorded `retrieved_at_utc` − `LastModified` under the 10 min margin on almost all rows (otherwise the
      training margin is widened and R-K is re-fitted);
    - a snapshot payload stamping `hrrr_cycle_utc` and `hrrr_msg_sha256[]` for captured-input replay and release
      binding.
  - **Dev evidence alone cannot promote, bind or enter MG-2.** A gate-4 WIN gives only a drafted proposal.

### Gate 2: LOYO 2021-25, B_H beats B_N at 13-16

- **Rows:** blocked leave-one-year-out (`rung_loyo`), all four arms on identical rows.
- **Statistic:** mean per row of Brier(B_H) − Brier(B_N), pooled over h13-16, with a date-clustered bootstrap
  (2,000 draws, seed 20261024).
- **PASS** if the upper 95% bound is below 0.
- **Reported:** each hour, h13-14 and h15-16, and P3d_H − P3d_N_fix.

### Gate 3: dev, P3d_H beats P3d_N_fix at 13-16

- **Population:** the same as R-J. Scorecard folds 2026-08-01..09-29, scored 08-15..09-29.
- **Statistic:** dR = mean_cell(Brier_P3d_H − Brier_P3d_N_fix) / mean_cell(Brier_market), ALL markets, h13-16
  pooled, with date-clustered 95% intervals (2,000 draws, seed 20260921).
- **Scope:** snapshots covered by B_N, B_H, P3d_N_fix and P3d_H.
- **PASS** if the upper bound is below 0.
- **Reproduction controls (refused otherwise):**
  - B_N and P3d_N_fix at 13-16 must be byte-identical to R-H's (`bab9cac7…`, `abc43507…`).
  - MG-1's 07-12 control must give 0.012.

### Gate 4: against the composite's post-13 arm on as-of-capture inputs (C7)

- **The comparator:** MG-2's post-13 half on as-of-capture inputs. On dev this is P3d_N_fix where the scorecard
  uses it, and MG-1 otherwise. The diagnostic `diag_summary.md` showed this equals the as-of-capture path's input
  semantics.
- **The candidate:** P3d_H, with the same MG-1 fallback.
- **Statistic and scope:** gate 3's statistic on gate 3's scope, plus the Brier difference against MG-1 at 13-16
  (MG-2's G2 form), reported.
- **Reading:**
  - **WIN** if the 13-16 upper bound is below 0 and no hour h13-h16 has a lower bound above 0.
  - **HARM** if the lower bound is above 0.
  - **NULL** otherwise.
- **If WIN:** L2 drafts, but does not apply, a dated MG-2 post-13 Clarification and the gate 1 forward-parity
  plan. Nothing else.

### Reported only (never a gate)

- h13-14 and h15-16 pooled, each hour, and per market.
- B_H − B_N on dev.
- `k_miss` rates.

## PRE-REGISTERED KILL

If gate 2 or gate 3 fails, HRRR is closed as a 13-16 centre input.

Concretely, no other HRRR feature, transform, cycle rule, margin, window or block statistic is run as a centre input
at 13-16 on B_N, P3d_N_fix or any NBM-anchored arm under any rung name. DPT and wind were never fetched and are
not reopened by this rule; they would need an owner ruling.

The kill does not cover HRRR at 07-12, which was not fetched and needs its own ruling and rule.

A gate 1 failure, or a missing 2026 corpus, stops R-K without a kill.

## Outputs

- `C:\t\l2\rungk\emit\`: `rk_emit_audit.json`, `loyo_rows.jsonl`, `dev_*.jsonl` and `rk_columns.parquet`.
- `C:\t\l2\rungk\score\rk_score.json`.
- `docs/research/l2-pooled-residual-2026-10-24/rungk/` holds this rule and the summary.
