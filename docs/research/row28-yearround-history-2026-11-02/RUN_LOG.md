# Row 28 — run log (DRAFT, nothing has run)

This log records how the frozen row-28 prereg is executed.

- **Prereg:** `prereg_row28.md`, sha256 `cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b`, governed
  by `FREEZE_RECORD.md`.
- **Read with:** `CLARIFICATION_1.md` and `CLARIFICATION_2.md` (both 2026-11-03, committed before any control).
- **Status:** nothing has run, not even the sentinel test. Gate order: the delta review of v3 is CLEAN (against the
  prereg, the freeze record, C1 and C2), then the coordinator's go for the sentinel test, then the sentinel test
  PASSES, then the coordinator's go for stage 1.

## Exception to workstation_heavy admission

**Master ruling 2026-11-03, option 2, a one-off for row 28.** `scripts\ops\workstation_heavy.ps1` refused the row-28
runner, because it admits only offline training/replay modules (`workstation_heavy.ps1` line 146). Row 28 therefore
runs through a guarded one-off launcher.

- **Precedent.** L47's `C:\t\storage-audit\run_walk_guarded_v1.ps1` (sha256
  `0a87f905527500d43fdba039131e09930a5e1557deb3e087fb30159af4809a87`; master ruling 2026-11-02).
- **Launcher v1** (`34235d44…`, reviewed CLEAN-WITH-MINORS) is L47 v1 plus five items, plus the OutRoot change:
  1. a kill-on-close Job with no breakaway, using create-suspended → assign → resume;
  2. a memory floor at start: at least 6 GB available and commit at or below 90%;
  3. a disk floor at start: at least 45 GiB free on C:;
  4. a timebox ceiling of 21,600 s;
  5. PeakJobMemoryUsed in the receipt.
- **The `-Stage` parameter** is allowed by master pre-ruling 1.
- **Launcher v2** is v1 plus the review minors and nothing else:
  - L1: MutexNames must be exactly the 9 default names, or all TEST-ONLY;
  - L2: every Dispose has its own try/catch, and the mutexes are released in their own finally;
  - L3: a failed memory read is recorded as `job_memory_error`, and the receipt is still written;
  - L4: the receipt records whether stdout or stderr was truncated (Stdout/StderrTruncated) and the bytes seen
    (Stdout/StderrBytesSeen).
- **Launcher v3** is v2 plus, and nothing else (Clarification 2):
  - LN1: on the success path the Job is `TerminateAndWait(30000)`-ed before `output.Complete(2000)`;
  - G1: after the child ends, `walker.stdout` / `walker.stderr` are scanned for dates on or after 2026-01-01 (no
    allowlist). A hit HALTs a pre-score stage (exit 6) and is a FLAG for look and score;
  - G2: receipt stamps are ISO 8601 basic format, and the receipt text is guarded before it is written.

## Pinned files

| File | sha256 |
| --- | --- |
| Launcher v3, `C:\t\L59\row28\run_row28_guarded_v3.ps1` (= `scripts/run_row28_guarded_v3.ps1`) | `fb0397829c1fcbc19f124f8bbe76d8824ca406b34bfb1923cea97f11e6856a3c` |
| Runner v3, `scripts/row28_run_v3.py` (run from `C:\wt\L59row28`) | `949464ab987a746f9077294a96ef7cac511b55914f69f336bcded6c5b370c438` |
| Sentinel test, `scripts/test_row28_s7_sentinel_v1.py` (pins runner v3) | `e91cbb468aa9f9ed8dce9ad5754d79bdfe401a15505a6bb263bf32556b1020c0` |
| `CLARIFICATION_1.md` | `d9e70a2f47e05d9046893d3b5f461b7ab3ce658b5166748c5eaedca5d8187495` |
| `CLARIFICATION_2.md` | `a71ba0e87c2d887309be41a57f0aceeccd03039acb1d20532e0dfa61d7df6bdd` |
| R-P2 module copy, `C:\t\L59\row28\tools\station_pool_corpus_d4947cfe.py` | `d4947cfe1b02c537ec84fca994ef0c1c26572be0251810eb744b421aae09f0b7` |
| Job helper, `C:\wt\L59row28\scripts\ops\windows_kill_on_close_job.ps1` | `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669` |
| Admission helper, `C:\wt\L59row28\scripts\ops\workload_admission.ps1` (memory reading only) | `48786bcb1946ad9b02934da53d5887d8ab49f69a72750c36809bc6d7f160b441` |
| L47b 2026 NBP 07Z corpus, `C:\t\l47b\corpus_2026.jsonl` (§7 inputs only) | `d59718a746a68d4745895623bae7760d99d95da647228fa3f8b7e389c8810acf` |
| Stage-1 config, `C:\t\L59\row28\run_config\stage1_controls_v2.json` (no runner-version key; reused for v3) | `66e4b46e9488d95ab32d7d65ab793ab1986de2204045402b1703d47096a439b9` |

- **Superseded, never run:** runner v1 `e39ce884…`, launcher v1 `34235d44…`, config `stage1_controls_v1.json`,
  runner v2 `0a74bb3d…` and launcher v2 `8bfea248…`. They stay in the branch as review history.
- **Pins inside the runner:** it pins every bound module, input and corpus sha256 it reads. It also pins the run root
  `C:\t\L59\row28\run` and the main data root.
- **Later stages:** each gets a new config, `stageN_<name>_v3.json`. That config names the previous stages'
  `walk.json` files with their sha256 values (from the table below) and, for stages labels and score, the gate commit.
  The config's own sha256 is logged here before its stage starts.

## Data junctions (created 2026-11-03T03:15:04 EST, approved by master)

The worktree's `C:\wt\L59row28\data\` holds exactly four directory junctions, each pointing to the same-named
subdirectory of `C:\Users\Michael\Documents\github\weather\data`. Nothing else is in it, and the main data is
untouched.

| Junction | Read by (static trace) | If absent |
| --- | --- | --- |
| `wunderground` | daily summary: `feature_model_training_inputs.py` 276–278, `model_climatology.py` 102/116; hourly obs: `model_climatology.py` 140–153; §7 reader | daily: fail; hourly: silent skip |
| `marine_water_contrast` | `marine_water_contrast.py` 48–49/671–674, read at 445 → 147 | silent skip (features become None) |
| `reanalysis` | `reanalysis_history.py` 27/155; `reanalysis_synoptic.py` 222–224, read at 1184 | silent skip (features become None) |
| `training` | PIT corpora by explicit manifest path (`pit_forecast_corpus\corpora\<id>\`) | fail |

- **Not read.** `resolve_artifact_path` (`artifacts.py` 395–407, called from `toronto_model.py` 231) resolves only
  under `artifacts/` or the legacy `src/`, never `data/`.
- **R-P2 spc copy.** The functions the runner calls (`station_candidate`, `station_files`, `station_labels`,
  `station_all_reports`, `cutoff_features`, `nbm_pool_rows`, `control_cd_blocks`, `base_frame`, `load_pool_frame`,
  `load_rp2_classes`, `season_dates`) read only the paths passed to them. They neither read nor write under DATA_ROOT.
  The copy's only writes are in `build`, `loyo`, `precheck` and `loyo_rp2`, which are never called.
- **No writes.** None of the traced paths writes under DATA_ROOT.
- **Bytecode.** The runner sets `sys.dont_write_bytecode`, so no `__pycache__` is written outside the run root.
- **Junction manifests.** Each stage writes `junction_manifest_{before,after}.json.gz`: metadata only, one row per
  file under the four junctions, `[subdirectory, sha256(relative path), size, mtime_ns]` (v3, N6: no dated path name
  in any output). A difference since the previous stage ended HALTs at stage start. A difference within a stage
  HALTs in controls, build, integrity and labels. In look and score it is a FLAG, classified per subdirectory, with
  master's pre-stated rule (Clarification 2 §4, N1).

## Stage plan (fixed order; one launcher invocation per stage)

| # | Stage (`-Stage`) | Timebox (pre-stated) | Gate before it |
| --- | --- | --- | --- |
| 0 | sentinel test (`scripts/test_row28_s7_sentinel_v1.py`, synthetic only) via `workstation_heavy.ps1 -Kind pytest -Queue` | the wrapper's own | v3 delta review CLEAN + coordinator go |
| 1 | `controls`: C-0, C-0b, C-0c, C-b | 4 h = 14,400 s | sentinel PASS + coordinator go |
| 2 | `build`: every record window, the y-free frame with label presence, NBM tables, pool feature rows with presence | 6 h = 21,600 s | stage 1 PASS |
| 3 | `integrity`: outcome-blind integrity report; every HALT (R6); the C-pool control; empty pool; S; the §7 gate; restated n, MDE and §8.4 thresholds (N2) | 2 h = 7,200 s | stage 2 PASS |
| — | commit and push `run/integrity_report.json` (= the stage-3 walk.json) and record its commit here | — | — |
| 4 | `labels`: label join, y-free parity, consistency asserts | 2 h = 7,200 s | integrity commit on origin, blob = run file |
| 5 | `look`: folds 2021–23 (the integrity-committed kept dates of those folds, N2), FUTILE flags | 4 h = 14,400 s | stage 4 PASS |
| — | commit and push `run/look_result.json` (= the stage-5 walk.json) before any 2024–25 held-out score | — | — |
| 6 | `score`: folds 2024–25, statistics, §8.2/§8.4 outcomes, §8.3 selection | 6 h = 21,600 s | look commit on origin, blob = run file |

- **Timeboxes.** The launcher's ceiling is 21,600 s, the largest timebox. Each invocation passes its own
  `-TimeboxSeconds`. Stage 3's timebox rises from 3,600 s to 7,200 s because it now also runs the §7 gate and the
  a57e10a6 control, both pre-stated here.
- **Launch form.** One invocation per stage on the WS. OutDir is new each time, under `C:\t\L59\row28\run`:

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v3.ps1 `
  -OutDir C:\t\L59\row28\run\s1_controls -Stage controls -TimeboxSeconds 14400 `
  -RootsPath C:\t\L59\row28\run_config\stage1_controls_v2.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v3.py `
  -ExpectSha 949464ab987a746f9077294a96ef7cac511b55914f69f336bcded6c5b370c438
```

- **Sentinel test form (stage 0).** It goes through the WS's standard pytest route, so no new exception is needed. The
  arguments are a JSON array passed as canonical base64; the basetemp is deleted afterwards. Arguments:
  `-m pytest <abs path of scripts\test_row28_s7_sentinel_v1.py> -q -p no:cacheprovider --basetemp C:\t\L59\row28\sentinel_bt`.

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\wt\L59row28\scripts\ops\workstation_heavy.ps1 -Kind pytest `
  -Queue -PythonPath C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe `
  -RepoRoot C:\wt\L59row28 -ArgumentsBase64 <canonical base64 of the JSON argument array>
```

- **HALT handling.** A HALT means stop and report. A repair needs a written, reviewed amendment made before any arm
  score has been read. Once any arm score exists, no re-run is allowed. The runner itself refuses the look stage if any
  look or final rows already exist, and refuses the score stage if any final rows already exist.

## Disclosures and resolved flags (details in CLARIFICATION_1.md and CLARIFICATION_2.md)

| Flag | Resolution |
| --- | --- |
| F1: the bound builder writes y to disk | Accepted as a disclosed deviation, with conditions. y stays under the run root; the stage-3 inputs are asserted y-free; no stage before labels reads a label value; the look asserts its set equals the integrity-committed 2021–23 kept dates (C2, N2, superseding "exactly 390"). |
| F2: the controls load labels | Accepted as frozen. Outputs are counts and max-abs-diff only; C-0b is equality-only. |
| F9: §7 gate | Computed as frozen at stage 3, inputs only, by a separate reader capped at 2026-05-26. |
| F14: per-market CI | Wide CI (κ_wide on the market's own series) for the §8.2 decisions; the κ-only CI is descriptive. |
| R6 / R9 / R10 / R11 | Adopted. See Clarification 1 §4 and the `RULING_*` constants. R11's operative meaning is fill-from-normal (C2, N5). |
| Sealed-window rulings 1–2 | §7 raw-prefix skip; daily_summary raw-prefix filter; the output guard. See Clarification 2 §1–2. |
| N1 / N2 / N5–N8 / LN1 | Adopted or acknowledged. See Clarification 2 §4. |
| R7 / R13 | Disclosures accepted. |
| `-Stage` | OK. |

Resolved by Clarification 2 (formerly open):

1. **§7 reader and the 2026-05 WU hourly file:** option (a), a raw byte-prefix test before any decode (C2 §1).
2. **WU `daily_summary.csv` read whole:** a disclosure for the bound builder only; the runner's own reads filter on the
   raw line prefix (C2 §2).
3. **§7 observation rule:** the last hourly observation at or before 07:00 local (C2 §3).

Open for master: `RULING_GUARD_POST_SCORE = "withhold_and_flag"`, which covers a guard hit once a score exists (C2 §2).

Kept from v1 (no ruling changed them):

- the S support (exact B..K−1 plus gte K, with K = max(B, ceil(mu+10σ)));
- D's WU column and its b_recent window;
- the statistics formulas (ρ over calendar-adjacent same-season-year pairs; κ_block3 size-weighted);
- D shifts mu only;
- training rows are not integrity-filtered.

## Per-stage log

Start and stop are real Get-Date stamps (WS). Peak RAM is **PeakJobMemoryUsed (peak committed private bytes)** of the
stage's Job, from `receipt.json` `job_memory.peak_job_memory_bytes`.

| # | Stage | Start | Stop | Exit | Status | PeakJobMemoryUsed (peak committed private bytes) | walk.json sha256 | Other output shas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | controls | | | | | | | |
| 2 | build | | | | | | | |
| 3 | integrity | | | | | | | |
| 4 | labels | | | | | | | |
| 5 | look | | | | | | | |
| 6 | score | | | | | | | |

Gate commits: integrity — (pending); look — (pending).
