# MG-3 freeze prep (1c): forward HRRR parity scorer (rule, written before any score)

Written 2026-10-26 by lane L2, **before the scorer has read a recorder row for scoring**. Master's instruction, as
the coordinator relayed it: "a forward-parity scorer comparing recorder rows … against the archive-path HRRR
features P3d_H was trained on (no outcomes). Define parity metric and threshold in its rule."

- **Evidence class:** inputs-only parity.
  - **Read:** HRRR point values, message metadata and selections. These are forward weather inputs, not outcomes.
  - **Never read:** any outcome, label, price, market row, NBM value or layout row.
- **Binds nothing.** The MG-3 forward rule cites this rule's verdict as a precondition for counting. The verdict
  never re-cuts a score.

## 1. Inputs

**Recorder (serve path).** L13's shadow recorder, `claude/hrrr-forward-recorder-20261026`, writing to
`C:\t\l13\hrrr_forward`:
- `snapshots.jsonl`: the once-written per-snapshot rows;
- `messages.jsonl`: the per-message point records, in the research manifest shape;
- `stations.json`;
- `meta.json`.

**Archive (training path).** An L13 research-fetcher corpus for the same forward dates, in the training corpus
format (`manifest.jsonl`, `selections.jsonl`, `stations.json`, as `C:\t\l13\hrrr_0712` / `C:\t\l13\hrrr`):
- read independently from the AWS archive (`noaa-hrrr-bdp-pds`) after the fact;
- selected by the training rule (newest cycle with every needed fh's max(LastModified) + 10 min ≤ h:00, lookback
  4, window [h:00, 17:00 local]).

L13 builds this corpus with its unchanged research fetcher. L2 does not write a fetcher.

**Population.**
- **Rows:** recorder rows with `row_schema` = 2 for the 11 R0 stations (CYYZ excluded), hours 07-16.
- **Dates:** local dates from the first `row_schema` 2 row through `--through`. The MG-3 forward rule sets
  `--through` (D0 − 1 for the pre-count check, then each scored day).
- **Blocks:** 07-12 reads the RN-1 cell; 13-16 reads the nearest cell, as each block was fitted
  (`rule_mg3_p3dh_state.md` §1).
- **Excluded:** no row is dropped for its value. A row whose `paused_at_snapshot` is true is counted, and is
  reported separately.

**Feature function.** Both paths' features are computed by the training function `rk_hrrr_columns`, unchanged:
- `point` = RN-1 indices from `rr_point_rule` for 07-12, or None for 13-16;
- its K→F conversion, TMP range check and `k_miss` reasons.

The recorder's own stamped values (`k_max_f`, `k_max_f_nearest_cell`, `k_tcdc`) are checked against it.

## 2. Metrics and thresholds (each per block; all must hold)

| # | Metric | PASS threshold |
| --- | --- | --- |
| F0 | **Serve-stamp identity.** Recompute every recorder row's features with `rk_hrrr_columns` on the recorder's own `messages.jsonl` and selection. The selection is the row's `cycle_utc` and `fhs`, with `latest_available_utc` = max over its fhs of max(grib, idx LastModified). Compare against the stamped values: `k_max_f` (07-12) or `k_max_f_nearest_cell` (13-16), and `k_tcdc` (07-12; for 13-16, the nearest-cell TCDC is recomputed only). Also, every `hrrr_msg_sha256` in the row must appear in `messages.jsonl` for its (key, variable). | `k_miss` equal on **100%** of rows; max \|Δk_max\| ≤ **1e-9 °F** and max \|Δk_tcdc\| ≤ **1e-9 %** over covered rows; message shas found on **100%** |
| F1 | **Cycle rule (P3).** Recorder `cycle_utc` against its own `training_rule_cycle_utc`. | equal on **≥ 99%** of rows; every disagreement has the recorder on an **older** cycle or `k_miss` = 1, **never newer** |
| F2 | **Latency (P4).** For each message a row uses: `captured_at_utc` − max(`grib_last_modified`, `idx_last_modified`). | ≤ **600 s** on **≥ 99%** of used messages |
| F3a | **Archive selection.** Archive `cycle_utc` and `fhs` against the recorder's, per (market, date, hour) where both exist. | equal on **≥ 99%**; every disagreement has the recorder older, **never newer** |
| F3b | **Archive values (the train/serve parity).** On rows where cycle and fhs are equal and both paths are covered: the recorder's `rk_hrrr_columns` features (F0) against the archive's. | max \|Δk_max\| ≤ **1e-9 °F** and max \|Δk_tcdc\| ≤ **1e-9 %** on **100%** |
| F3c | **Archive bytes.** Each (key, `idx_record`) the recorder used: recorder `msg_sha256` against the archive manifest's. | equal on **100%** |
| F4 | **Coverage.** Recorder `k_miss` = 0 share, per market. | **≥ 0.95** (`RK_COVERAGE_MIN`, gate 1's threshold) |

**Verdict.**
- **PASS:** every metric passes in both blocks.
- **PARTIAL (archive pending):** F0-F2 and F4 pass, and no archive corpus covers the dates. This does not permit
  counting.
- **FAIL:** anything else. The report names the metric, the block and the first failing row.

**On FAIL.** No tolerance, input or code changes to make it pass without a new ruling. The R-T note's reopen clause
("Reopen-if: P3d_H fails forward parity") applies.

**Also reported, not gated:**
- the row and message counts;
- paused-row and gap-event counts;
- the Δ distributions (max, 99th percentile);
- per-market F1 and F4;
- the archive's `stations.json` sha against the recorder's.

## 3. Outputs (outside the repository)

`--out` holds `forward_parity.json`, which records:
- the verdict and metrics;
- the input shas (recorder files, archive files, land file) and module sha;
- this rule's sha256 and the code commit.

Nothing is overwritten.

## 4. Limits

- No outcome, label, price, market or NBM read. `k_gap` = `k_max` − the row's own captured NBM anchor, so its parity
  follows from F3b and the MG-2 input bundle; it is not re-checked here.
- No change to the recorder, MG-2, B, PT-1 or MG-1. Read-only on `C:\t\l13`.
- Dates are forward (≥ 2026-10-26). The ≤ 2026-09-29 limit concerns outcomes, labels, prices and market data, none
  of which is read.
