# Row 28 — Clarification 1 (2026-11-03, before any control runs)

- **Written:** 2026-11-03T03:24 EST (WS Get-Date), by lane L59, before any row-28 stage has run.
- **What it governs:** how the frozen prereg (`prereg_row28.md` sha256 `cb6d4e8d…`, see `FREEZE_RECORD.md`) is read and
  executed. The prereg itself is NOT edited.
- **Source:** master's pre-rulings and master's rulings on the independent v1 review, both relayed by the coordinator
  on 2026-11-03. Quoted text is the relay's wording.
- **Code:** runner `scripts/row28_run_v2.py` encodes each ruling as one marked `RULING_*` constant.

## 1. Per-market CI (F14, Clarification 1 proper, pre-score)

> "the same construction" means the WIDE construction on that market's own per-date series.
> κ_wide,m = max(κ_m, κ_block3,m), with ρ̂ and the blocks computed within that market's series.
> The §8.2 decisions (per-market X−S CI above 0; C/D X−A lower bound > 0) use the wide CI.
> The κ-only per-market CI is reported descriptively.

Runner: `RULING_F14_PER_MARKET_CI = "ci95_wide"`. The κ-only `ci95` is kept in the report as descriptive.

## 2. §7 gate wording correction (F9)

> COMPUTE IT AS FROZEN. Master's "dev dates <= 2025" was mis-worded. The actual constraints:
> Labels and outcomes come only from the frozen deciding, training and control sets.
> Nothing dated 2026-05-27 or later is opened (sealed panel 05-27..07-30; embargo >= 09-30).
> §7 reads inputs only (NBP07 TXN, 07-local WU obs, TXNSD) on 2026-01-01..05-26 and on the same windows in 2023–25.
> That is allowed. It gates only §9, never the history verdict.
> Enforce the 2026-05-26 upper bound in code.

How the runner (`RULING_F9_SECTION7_GATE = "compute"`) implements this:

- **Where.** The gate is computed at stage `integrity`, so it is committed with the pre-score integrity report.
- **Reader.** It uses a separate inputs-only reader capped at 2026-05-26. Any value it returns that is dated later
  HALTs. Every other row and label path keeps its 2025-12-31 limit.
- **Inputs.**
  - The 2026 NBP 07Z rows come from `C:\t\l47b\corpus_2026.jsonl` (sha256 `d59718a7…`, 2026-01-01..05-26, 146 dates).
  - The 2023–25 07Z rows are the build stage's rows from this row's fetch.
  - The WU observation is the last hourly observation at or before 07:00 local on the date.

## 3. Disclosed deviations and their conditions

**F1 — the bound builder writes y to disk. ACCEPTED as a disclosed deviation.**

> y stays only under the run root; no agent opens it.
> The stage-3 integrity inputs ASSERT that no y or final_bucket column exists.
> No stage before `labels` reads y.
> m11: the look stage asserts that its scored set is EXACTLY the first 390 deciding dates (folds 2021–23).
> No 2024–25 score is computed before the look file is committed, even though their y is on disk.

Runner notes:

- The y-free frame is made right after unpickling each record file. The label value is replaced by a *presence*
  marker (R6, below), so no label value survives.
- Pool label presence is computed at stage `build` by the venue-rule routine. Only its `label_complete` flag is
  kept; the computed values are discarded on the spot.

**F2 — the controls load labels. ACCEPTED as frozen; C-0b is review M1's control.**

> Outputs are counts and max-abs-diff only.
> No label value is printed or written outside the run root.
> No comparison against any prediction.
> C-0 and C-b use Aug–Sep non-deciding labels, as frozen.

**Flag 2 — CONFIRMED OK.**

> C-0 and C-b reproduce R-A on NON-deciding Aug–Sep 2021–25 rows, against the frozen values, as §3.5 prescribes.
> Their outputs are counts and max-abs-diff only. C-0b, which uses deciding-date labels, stays equality-only, with
> no comparison against any prediction.

**R7 (disclosure accepted).** `payload_meta.json`'s `bucket_space` is label-derived metadata mandated by §3.6. It has
no influence on any stage-3 decision.

**R13 (disclosure accepted).** S_bound and the hours 07–12 comparison are not implemented. Both are descriptive only
and decide nothing. Fold 2026 and the V5.0 sliver are "not built" (§1.1).

## 4. Rulings on the v1 review (each one constant in the runner)

| Item | Ruling (quoted) | Constant |
| --- | --- | --- |
| R6 | "ADOPT the reviewer's fix. Every HALT must fire before the label join: count label PRESENCE (isna) in stage 2, before blanking; compare the C-pool control against a57e10a6 at stage 3, on input columns without y; run the empty-pool recheck before the join. Presence is outcome-blind; values never are." | `RULING_R6_ALL_HALTS_BEFORE_LABEL_JOIN = True` |
| R9 | "ADOPT. The top bucket K has '>= K' semantics in scoring (y >= K maps to K). Apply this IDENTICALLY to S and to every arm, since they share the bucket space. Report the count of scored rows with y > K; it is expected to be 0 and is descriptive only." | `RULING_R9_TOP_BUCKET_GTE = True` |
| R10 | "ADOPT. The imputation cap is per arm × calendar month, pooled over years; this is the plain reading of §3.3b. Report the YYYY-MM breakdown descriptively." | `RULING_R10_IMPUTE_GROUP = "calendar_month"` |
| R11 | "ADOPT the frozen text. A pool row with no posted NBM is filled from forecast and counted toward the cap. It is not dropped." | `RULING_R11_POOL_NO_NBM = "fill_from_forecast"` |

Implementation notes, stated before any run:

- **R6, market rows.** A built row without a label HALTs the whole run at stage `integrity` (presence only).
- **R6, arm C.** The C-pool control compares the rebuilt Aug–Sep h07–12 pool rows with a57e10a6 on their common input
  columns, with y dropped on load. Only label-complete pool rows count for the empty-pool check. Either failure HALTs
  arm C only, at stage `integrity`.
- **R6, stage `labels`.** This stage only re-asserts consistency; nothing HALTs there.
- **R9.** Each distribution's own top bucket is used: S's K, and each arm's top bucket for that fold. Scored rows only;
  the controls keep the bound scoring form. Counts of y > K (and S's y < B) are reported, descriptive only.
- **R10.** The cap is per calendar month (MM). Arm C adds its label-complete pool rows. The YYYY-MM table is
  descriptive.
- **R11.** `attach_training_nbm` fills a missing NBM with the record's own forecast_high. A pool station has no PIT
  forecast_high, so its filled anchor is NaN, and the bound model then anchors the row on its fitted normal
  (`pooled_residual_model.py` 476–477). These rows count as imputed in arm C's cap. The C-pool control rows keep R-P2's
  frozen rule (no NBM, so dropped), because that is how a57e10a6 was built.

## 5. Other pre-run decisions recorded here

- **Launcher.** The `-Stage` parameter is OK (master pre-ruling 1). The launcher is now `run_row28_guarded_v2.ps1`,
  which adds review minors L1–L4.
- **Junctions.** Approved for exactly `data\wunderground`, `data\marine_water_contrast`, `data\reanalysis` and
  `data\training` in the worktree. Each points to the matching main-checkout subdirectory.
  - The runner refuses unless the worktree's `data\` holds exactly these four and each resolves to its target.
  - Every stage records metadata-only before/after manifests of the four (path, size, mtime). Any difference HALTs.
  - The manifests are metadata only; no file is hashed, because hashing would read the bytes of sealed and embargoed
    dates.
