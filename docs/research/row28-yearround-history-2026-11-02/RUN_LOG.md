# Row 28 — run log (DRAFT, nothing has run)

This log records how the frozen row-28 prereg (`prereg_row28.md` sha256
`cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b`, governed by
`FREEZE_RECORD.md`) is executed. Nothing has run. The first stage starts only on the
coordinator's go after a CLEAN review of the launcher diff and of the runner.

## Exception to workstation_heavy admission

**Master ruling 2026-11-03, option 2, a one-off for row 28.** `scripts\ops\workstation_heavy.ps1`
refused the row-28 fit script, because it admits only offline training/replay modules
(`workstation_heavy.ps1` line 146). Row 28 therefore runs through a guarded one-off launcher
instead.

- **Precedent.** L47's `C:\t\storage-audit\run_walk_guarded_v1.ps1` (sha256
  `0a87f905527500d43fdba039131e09930a5e1557deb3e087fb30159af4809a87`; master ruling 2026-11-02).
- **Launcher.** `C:\t\L59\row28\run_row28_guarded_v1.ps1` is v1 plus items 1–5 of the ruling and
  the OutRoot change, and nothing else. A byte-identical copy is committed here as
  `scripts/run_row28_guarded_v1.ps1`.
- **Additions over v1:**
  1. A kill-on-close Job with no breakaway, using create-suspended → assign → resume.
  2. A memory floor at start: at least 6 GB available and commit at or below 90%.
  3. A disk floor at start: at least 45 GiB free on C:.
  4. A timebox ceiling of 21,600 s.
  5. `PeakJobMemoryUsed` in the receipt.
- **Stage flag.** One further parameter is needed, `-Stage`, which the launcher passes as the
  runner's `--stage`. Order (b) requires stage selection to be an explicit CLI flag. This is flagged
  for the review.

## Pinned files

| File | sha256 |
| --- | --- |
| Launcher `C:\t\L59\row28\run_row28_guarded_v1.ps1` (= `scripts/run_row28_guarded_v1.ps1`) | `34235d44ba637ad8dc0ddae3bb37eaab4034be5fae6a641d6cb644bf41b9415e` |
| Runner `scripts/row28_run_v1.py` (run from `C:\wt\L59row28`) | `e39ce884549b820f3ee5c977bc36d97bfd281371b8d95735f9df9497a2e556b7` |
| R-P2 module copy `C:\t\L59\row28\tools\station_pool_corpus_d4947cfe.py` (= `origin/claude/station-pooled-corpus-s0-20261101` `src/weather/calibration/station_pool_corpus.py`) | `d4947cfe1b02c537ec84fca994ef0c1c26572be0251810eb744b421aae09f0b7` |
| Job helper `C:\wt\L59row28\scripts\ops\windows_kill_on_close_job.ps1` (= origin/master) | `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669` |
| Admission helper `C:\wt\L59row28\scripts\ops\workload_admission.ps1` (memory reading only) | `48786bcb1946ad9b02934da53d5887d8ab49f69a72750c36809bc6d7f160b441` |
| Stage-1 config `C:\t\L59\row28\run_config\stage1_controls_v1.json` | `43b0b310e441652334942967555d6b4e501eca625e4e22b4bddf95f3f16455a8` |

- The runner itself pins every bound module, input and corpus sha256 it reads.
- Each later stage gets a new config file, `stageN_<name>_v1.json`. That file names the previous
  stage's `walk.json` with its sha256 (taken from the table below) and, for stages labels and score,
  the gate commit. Its sha256 is logged here before the stage starts.

## Prerequisite before stage 1 (needs the coordinator's OK)

The bound builder reads `data/` under the importing checkout (`weather.paths.DATA_ROOT`), and the
worktree has none. The proposal is a directory junction from `C:\wt\L59row28\data` to
`C:\Users\Michael\Documents\github\weather\data`, so that the build reads exactly what a
main-checkout run reads. The l9run worktree is the precedent: it junctioned `data\training` and
`data\wunderground`.

- `data/` is git-ignored.
- The runner refuses to start unless `DATA_ROOT` resolves to the main data directory.

## Implementation choices flagged for the review

1. The bound builder writes y to disk under the run root. In stages 1–2 it also holds y in memory
   for a short time. Stage-2 frames have y blanked (`final_bucket` set to NaN) before pooling. Stages
   1–3 never score against y.
2. C-0, C-0b and C-b load labels. The C-0 and C-b labels are Aug–Sep, which is non-deciding. C-0b
   compares Jan 1–15 deciding labels against l2 at 1e-9 and reports counts only.
3. Stage 3 reads WU daily_summary rows, but uses only `local_date` and `row_count`
   (`COMPLETE_DAY_MIN_ROWS` = 18).
4. S has integer support: exact buckets B..K−1, plus a gte bucket at K = max(B, ceil(mu+10σ)). It is
   checked against `mg_serve_core.mg1_band_probs` at 1e-12.
5. A pool row with no NBM is dropped and counted in C's imputation numerator.
6. The empty-pool recheck for the pool runs at stage 4.
7. a57e10a6 holds hours 07–12 only. So the Aug–Sep pool rows for hours 13–16 are rebuilt from the
   frozen L48 inputs. A C-pool control compares the rebuilt h07–12 rows against a57e10a6 at 1e-9;
   if it fails, only arm C HALTs.
8. D's WU column is `max_temp_bucket_native`, kept when row_count ≥ 18. The b_recent window may reach
   Nov 19–30 through L9.
9. The §7 V5 gate is NOT COMPUTED, because it conflicts with the rule that dev dates are ≤ 2025. The
   integrity report records this.
10. Some descriptive items are not implemented: S_bound, hours 07–12, and fold 2026.
11. PIT corpora are split into per-season sets, because `PITForecastCorpusUnion` refuses
    overlapping years. A coverage-equality check HALTs on any mismatch.
12. The data junction needs approval (see the prerequisite above).
13. The launcher has one extra parameter, `-Stage`.
14. The per-market kill CIs use κ, not κ_wide.
15. Imputation is computed per arm × YYYY-MM, which is the stricter reading.
16. ρ is computed over calendar-adjacent pairs within one season-year. κ_block3 is the size-weighted
    block variance divided by the number of blocks.
17. D shifts mu only; its scale is unchanged.
18. Training rows are not integrity-filtered, as the design is bound.

## Stage plan (fixed order; one launcher invocation per stage)

| # | Stage (`-Stage`) | Timebox (pre-stated) | Gate before it |
| --- | --- | --- | --- |
| 1 | `controls`: C-0, C-0b, C-0c, C-b | 4 h = 14,400 s | coordinator go after CLEAN review |
| 2 | `build`: every record window, y-free frame, NBM tables, pool feature rows | 6 h = 21,600 s | stage 1 PASS (walk.json sha256 in config) |
| 3 | `integrity`: outcome-blind integrity report | 1 h = 3,600 s | stage 2 PASS |
| — | commit and push `run/integrity_report.json` (= stage-3 walk.json) and record its commit here | — | — |
| 4 | `labels`: label join, y-free parity, pool control and recheck | 2 h = 7,200 s | integrity commit on origin, blob = run file |
| 5 | `look`: folds 2021–23, FUTILE flags | 4 h = 14,400 s | stage 4 PASS |
| — | commit and push `run/look_result.json` (= stage-5 walk.json) before any 2024–25 held-out label is joined | — | — |
| 6 | `score`: folds 2024–25, statistics, §8.2/§8.4 outcomes, §8.3 selection | 6 h = 21,600 s | look commit on origin, blob = run file |

- The launcher's ceiling is 21,600 s, the largest of these timeboxes. Each invocation passes its
  own `-TimeboxSeconds`.
- Launch form (WS, a separate invocation per stage; OutDir is new each time, under
  `C:\t\L59\row28\run`):

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v1.ps1 `
  -OutDir C:\t\L59\row28\run\s1_controls -Stage controls -TimeboxSeconds 14400 `
  -RootsPath C:\t\L59\row28\run_config\stage1_controls_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v1.py `
  -ExpectSha e39ce884549b820f3ee5c977bc36d97bfd281371b8d95735f9df9497a2e556b7
```

- **HALT handling.** A HALT means stop and report. A repair needs a written, reviewed amendment
  made before any arm score has been read. Once any arm score exists, no re-run is allowed.

## Per-stage log

Start and stop times are real Get-Date stamps (WS). Peak RAM is the Job's `PeakJobMemoryUsed`
from `receipt.json`.

| # | Stage | Start | Stop | Exit | Status | Peak RAM (Job) | walk.json sha256 | Other output shas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | controls | | | | | | | |
| 2 | build | | | | | | | |
| 3 | integrity | | | | | | | |
| 4 | labels | | | | | | | |
| 5 | look | | | | | | | |
| 6 | score | | | | | | | |

Gate commits: integrity — (pending); look — (pending).
