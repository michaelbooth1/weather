# Row 28 — run log (sentinel PASSED; no stage has run)

This log records how the frozen row-28 prereg is executed.

- **Prereg:** `prereg_row28.md`, sha256 `cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b`, governed
  by `FREEZE_RECORD.md`.
- **Read with:** `CLARIFICATION_1.md`, `CLARIFICATION_2.md` and `CLARIFICATION_3.md` (all 2026-11-03, committed
  before any control).
- **Status:** the v6 final delta review was CLEAN on every file. Sentinel test v4 (stage 0) PASSED on
  2026-11-03 (see the per-stage log). Stage 1 (`controls`) attempt 1 HALTed (R4 junction check plus the launcher
  v5 G2 self-hit); no control was computed. Master accepted launcher v6 and OutDir `run\s1_controls_a2` (same
  attempt). The launcher v6 smoke (stage 0b) PASSED, and the v6 delta review was CLEAN (04:55:30). The a2 relaunch
  then ended PARTIAL (walker ERROR): the worktree's 26 `artifacts/models/hgb` files were Git LFS pointers. After a
  local-only LFS checkout (the oids were verified), a3 computed C-0, C-0b, C-0c and C-b, and all PASS. The stage
  still HALTed (run scope) on the runner's output guard (276 hits), and the guard detail was withheld. It is waiting
  on a ruling. Build has not started.

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
- **Launcher v4** is v3 plus, and nothing else (Clarification 3 §1):
  - F3 (h): the log guard also masks the exact token `centre=<label>` for a label in the arm centre set (the same
    rule as the runner's `GuardedStream`); the launcher's 24 labels must hash to `GUARD_CENTRE_SET_SHA256`
    (`38a17ec2a04d764bac8ea43c8add0f89eb3fa542480eec73aaf0ab12febf6d83`) or it refuses before any child starts;
  - F4: a withheld receipt's minimal replacement records `receipt_guard_hits`;
  - F6: in look and score a withheld receipt keeps the stage status and adds `output_guard_flag` (a FLAG, not HALT);
  - F7: the receipt's `exception` string is reverted to the v2 text (C2 §5); G2 masks exactly that one string,
    because it contains a 2026 date. The v3 exception-string change is therefore undone. The masked string,
    verbatim (G6; also in the C3 addendum):
    "one-off exception to workstation_heavy admission, master ruling 2026-11-02, read-only metadata walk".
- **Launcher v5** is v4 plus one change (G4, C3 addendum): the minimal receipt that replaces a guarded receipt also
  carries `job_memory` (guarded first), so every stage's receipt records `job_memory.peak_job_memory_bytes`.
- **Launcher v6** is v5 plus one change (K1, C3 third addendum): the receipt writes `output_guard.from` in basic
  format (`$GuardFrom.Replace("-", "")` = `20260101`). `$GuardFrom` stays ISO, because it is the guard's
  comparison bound.

## Pinned files

| File | sha256 |
| --- | --- |
| Launcher v6, `C:\t\L59\row28\run_row28_guarded_v6.ps1` (= `scripts/run_row28_guarded_v6.ps1`) | `8a2f8759047845a3c67f373faf43b86db459aeda15f243ef8d8e996298374405` |
| Smoke child v1, `scripts/row28_smoke_noop_v1.py` (reads nothing) | `a8a53010dbecf3bb4a2199a043f3ac86ef67629aa3898e067137eae8d23d0864` |
| Smoke verifier v1, `scripts/row28_smoke_verify_v1.py` (runner v6 `verify_prev` source, unchanged) | `7370c58de6999a2a1cc495b5fc45c6d9835d692e0893627d0c26d349c3c28493` |
| Runner v6, `scripts/row28_run_v6.py` (run from `C:\wt\L59row28`) | `fd4464744e729cb8ed27eb68aa998d528ac4d2bfe5075d9837b9b02b7e2cae1b` |
| Sentinel test v4, `scripts/test_row28_s7_sentinel_v4.py` (pins runner v6) | `331692850750b3016aaac8d51630523cffbae57e68beacc754169c08c3611fca` |
| `CLARIFICATION_1.md` | `d9e70a2f47e05d9046893d3b5f461b7ab3ce658b5166748c5eaedca5d8187495` |
| `CLARIFICATION_2.md` | `a71ba0e87c2d887309be41a57f0aceeccd03039acb1d20532e0dfa61d7df6bdd` |
| `CLARIFICATION_3.md` (with its four 2026-11-03 addenda) | `9c8822a2300952d2143cbc1e358b4959ae2c34ff6e9738038f3f6d0909a326c1` |
| R-P2 module copy, `C:\t\L59\row28\tools\station_pool_corpus_d4947cfe.py` | `d4947cfe1b02c537ec84fca994ef0c1c26572be0251810eb744b421aae09f0b7` |
| Job helper, `C:\wt\L59row28\scripts\ops\windows_kill_on_close_job.ps1` | `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669` |
| Admission helper, `C:\wt\L59row28\scripts\ops\workload_admission.ps1` (memory reading only) | `48786bcb1946ad9b02934da53d5887d8ab49f69a72750c36809bc6d7f160b441` |
| L47b 2026 NBP 07Z corpus, `C:\t\l47b\corpus_2026.jsonl` (§7 inputs only) | `d59718a746a68d4745895623bae7760d99d95da647228fa3f8b7e389c8810acf` |
| Stage-1 config, `C:\t\L59\row28\run_config\stage1_controls_v2.json` (no runner-version key; reused for v3 and v4) | `66e4b46e9488d95ab32d7d65ab793ab1986de2204045402b1703d47096a439b9` |

- **Superseded, never run:** runner v1 `e39ce884…`, launcher v1 `34235d44…`, config `stage1_controls_v1.json`,
  runner v2 `0a74bb3d…`, launcher v2 `8bfea248…`, runner v3 `949464ab…`, launcher v3 `fb039782…`, sentinel
  test v1 `e91cbb46…`, runner v4 `059cb05b…`, launcher v4 `3f356f38…`, sentinel test v2 `2cc67424…`, runner v5
  `e138d9af…` and sentinel test v3 `1f5be86c…`. They stay in the branch as review history.
- **Superseded after one run:** launcher v5 `0b0d0f97…` ran controls attempt 1 only (HALT; see the per-stage log).
- **F2 pins (runner v4 `CALIBRATED_WEIGHTS_PINS`, checked at every stage before it starts).** The one allowlisted
  key path is `["calibrated_weights"]["metadata"]["generated_at"]`, in `records_*.pkl.gz` only, with a pinned value.
  It is copied by `src/weather/calibration/pooled_residual_model.py` 249 and loaded by
  `src/weather/model/toronto_model.py` 145 and 227–238 from `artifacts/calibration/calibrated_weights*.json`, line
  1147 of each file. The 12 values differ per file (all 2026-06-07, 22:05:46 to 22:15:56), so each file has its own
  pinned value. Runner v5 (G3) accepts in a records file only the value of `calibrated_weights_<payload market>.json`
  (`MarketSpec.artifact_suffix` = `_<id>`, `market_registry.py` 78-80); with no mapping it is a hit:

| `artifacts/calibration/` file | sha256 | `metadata.generated_at` (line 1147) |
| --- | --- | --- |
| `calibrated_weights.json` | `433c20508af04f1685946dcfce23308ef9e6830595980a49a220a4177d8e675d` | `2026-06-07T22:05:46` |
| `calibrated_weights_atlanta.json` | `bb0a01b702170cbde1f7c064aebce92657a11c603c2b7adbeaa71c2e935948c4` | `2026-06-07T22:08:48` |
| `calibrated_weights_austin.json` | `98584b0ae3726c36c7f29b52b88204a6387a8d7b15ed9e48dc21c7184f69143a` | `2026-06-07T22:09:31` |
| `calibrated_weights_chicago.json` | `88a210f6fcedcc016c9f08b4fdcc292b56dabde8412598c716051669c731a5be` | `2026-06-07T22:10:17` |
| `calibrated_weights_dallas.json` | `e7826c63da806608f3016054ea855f17a67bf3b33ce6402355a1b3a59ad545fa` | `2026-06-07T22:11:16` |
| `calibrated_weights_denver.json` | `a503c8887491614ea692fa67768476cbeac3cf4ebc6c1647f39b4d915d1eb9a4` | `2026-06-07T22:12:03` |
| `calibrated_weights_houston.json` | `e27acdbfe14029eca9a200f7ead77c05705e1201b1c5e0fb98d751a1dad0c388` | `2026-06-07T22:13:18` |
| `calibrated_weights_los-angeles.json` | `32fb8fac11ac64a08baeb2105467cc7d956e22362f3248aa1aa00f06a605dcb4` | `2026-06-07T22:13:55` |
| `calibrated_weights_miami.json` | `a9f2b44974125a3a870c99b8dbc40c3796b8f8b3cd58d0140279fd71163eeec1` | `2026-06-07T22:14:35` |
| `calibrated_weights_nyc.json` | `8435625628c2a3bf729c98bf0b5b27a94cdba769fa46fd6d296906a97392ffd9` | `2026-06-07T22:07:50` |
| `calibrated_weights_san-francisco.json` | `063d0743aa3441e10c9e200c86ca23aba1f6f3f0691001da3642565218fe79ce` | `2026-06-07T22:15:04` |
| `calibrated_weights_seattle.json` | `0fba075beea00a76074bed0b719e19e39f50af01b1e9011f05922218fbabee10` | `2026-06-07T22:15:56` |

- **Pins inside the runner:** it pins every bound module, input and corpus sha256 it reads. It also pins the run root
  `C:\t\L59\row28\run` and the main data root.
- **Later stages:** each gets a new config, `stageN_<name>_v6.json`. That config names the previous stages'
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
| 0 | sentinel test v4 (`scripts/test_row28_s7_sentinel_v4.py`, synthetic only) via `workstation_heavy.ps1 -Kind pytest -Queue` | the wrapper's own | coordinator go (v5 GO given) |
| 0b | launcher v6 smoke: `row28_smoke_noop_v1.py` into `run\s0_smoke`, `-Stage controls`; PASS = receipt COMPLETE, no receipt guard hit, `output_guard.hits_total` 0, and `verify_prev` accepts it | the controls timebox (14,400 s) | master's order (reads no data) |
| 1 | `controls`: C-0, C-0b, C-0c, C-b (attempt 1 HALT in `run\s1_controls`; relaunch into `run\s1_controls_a2`) | 4 h = 14,400 s | sentinel PASS, smoke PASS, v6 review CLEAN + coordinator go |
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
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s1_controls_a2 -Stage controls -TimeboxSeconds 14400 `
  -RootsPath C:\t\L59\row28\run_config\stage1_controls_v2.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v6.py `
  -ExpectSha fd4464744e729cb8ed27eb68aa998d528ac4d2bfe5075d9837b9b02b7e2cae1b
```

- **Sentinel test form (stage 0).** It goes through the WS's standard pytest route, so no new exception is needed. The
  arguments are a JSON array passed as canonical base64; the basetemp is deleted afterwards. The process environment
  sets `PYTHONDONTWRITEBYTECODE=1` (F8; the test also sets `sys.dont_write_bytecode`). Arguments:
  `-m pytest <abs path of scripts\test_row28_s7_sentinel_v4.py> -q -p no:cacheprovider --basetemp C:\t\L59\row28\sentinel_bt`.

```
$env:PYTHONDONTWRITEBYTECODE = "1"
powershell -NoProfile -ExecutionPolicy Bypass -File C:\wt\L59row28\scripts\ops\workstation_heavy.ps1 -Kind pytest `
  -Queue -PythonPath C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe `
  -RepoRoot C:\wt\L59row28 -ArgumentsBase64 <canonical base64 of the JSON argument array>
```

- **HALT handling.** A HALT means stop and report. A repair needs a written, reviewed amendment made before any arm
  score has been read. Once any arm score exists, no re-run is allowed. The runner itself refuses the look stage if any
  look or final rows already exist, and refuses the score stage if any final rows already exist.
- **F9, a HALT inside `score_folds`.** Only the pre-listed structural checks `SCORE_FOLDS_HALT_CHECKS` (SF1, SF2;
  Clarification 3 §3) may HALT there, and the HALT carries its code only; any other exception is an ERROR carrying
  only its type name. In-memory partial results are discarded, never written or logged. Any repair after such a
  HALT is a reviewed, committed amendment made before any re-run, recorded here with the HALT code.
- **F4 / G2.** Each stage refuses a previous stage whose `receipt.json` is not `COMPLETE` with
  `output_guard.hits_total == 0`, no `receipt_guard_hits` and no `output_guard_flag`, or whose `stage` and
  `walker_sha256` do not equal the stage name and the report's `runner_sha256`.

## Disclosures and resolved flags (details in CLARIFICATION_1.md, CLARIFICATION_2.md and CLARIFICATION_3.md)

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

## v4 rulings (master, 2026-11-03; runner v4 constants)

Master's rulings on the three v3 calls. C1 and C2 stay as committed; C2's global centre-label allowlist is
superseded by ruling 2 (Clarification 3 §4).

| # | Ruling | Runner v4 constant(s) |
| --- | --- | --- |
| 1 | ACCEPTED: a guard hit once a score exists withholds the output and FLAGs. A withheld file marks that arm's result INCOMPLETE until master rules; no verdict (and no futility decision) is recorded for it meanwhile. For look_rows / final_rows that is every arm. The score stage refuses a look that carries INCOMPLETE arms. | `RULING_GUARD_POST_SCORE = "withhold_and_flag"`, `RULING_V4_INCOMPLETE_ON_WITHHOLD = True`, `apply_incomplete` |
| 2 | NOT ACCEPTED, the global centre-label allowlist; the allowlist is scoped by context. A centre label passes only as the whole value of a centre field in a structured output (or a whole key under a declared parent), and only if it is in the arm centre set; the same string anywhere else is a hit. In logs it passes only as the exact token `centre=<label>`. §7's constants pass only in §7's own field. | `RULING_V4_ALLOWLIST_SCOPE = "context"`, `CENTRE_FIELDS = ("centre", "payload_centre", "rule_l_2024_02_29")` + `*_centre`, `CENTRE_KEYED_PARENTS = ("by_centre",)`, `GUARD_CENTRE_SET_SHA256 = 38a17ec2…` (24 labels), `LOG_CENTRE_TOKEN`, `S7_SECTION_KEY = "v5_gate_section7"`, `S7_CONSTANT_FIELDS = ("cap",)` |
| 3 | ACCEPTED, strict scanning of `records_*.pkl.gz`. The one non-data 2026 string the builder writes, found by reading the code, is allowlisted at its exact key path only, with pinned values (the F2 pins above). | `RULING_V4_RECORDS_GENERATED_AT = ("calibrated_weights", "metadata", "generated_at")`, `CALIBRATED_WEIGHTS_PINS` |

- **Named output type (ruling 2).** Record file names, `records_<market>_<centre>.pkl.gz`
  (`pooled_residual_model.py` 155–156), carry a centre label. They pass only under the configured `records_root`, as
  the whole value of `file`, or as a key directly under `records_sha256` (`RECORD_FILE_FIELDS`,
  `RECORD_KEYED_PARENTS`); anywhere else, and in logs, they are a hit (F3 a).
- **The arm centre set.** It is arm A's 24 labels; B's 11 are a subset and C = D = A. Outputs are not arm-tagged, so
  the per-field check uses this union.
- **The v3 delta review F1–F9**, as accepted by master, are folded into runner v4, launcher v4 and sentinel test v2:
  F1 (the walk keeps every visited object alive), F2 (pins above), F3 (a)–(i) (Clarification 3 §4; the report keeps
  the centre set as `guard_arm_centre_set` = sha256 + count), F4, F5 (no stats or futility from rows whose file was
  withheld), F6/F7 (launcher v4), F8 (sentinel test v2, `PYTHONDONTWRITEBYTECODE=1`), F9 (`post_score` stays where
  it is; the conditions above).

## v5 (the v4 delta review, master GO 2026-11-03; runner v5 constants; C3 addendum)

| Item | Change | Runner v5 constant / function |
| --- | --- | --- |
| G1 | Ruling 1, "withheld, never written": every Writer output is serialised first; the walk and the byte cross-check of the serialised bytes run before any write; a hit HALTs pre-score and withholds (not on disk) post-score. The walk covers all categorical categories. | `RULING_V5_WRITER_BYTE_CHECK = True`, `Writer._put` |
| G2 | `verify_prev` binds the receipt to its report: `receipt.stage == name`, `receipt.walker_sha256 == report.runner_sha256`. | `verify_prev` |
| G3 | A records file's `generated_at` must be the pin of its own market's `calibrated_weights_<market>.json`; no mapping is a hit. | `RULING_V5_GENERATED_AT_OWN_MARKET = True`, `records_generated_at_for` |
| G4 | Every receipt records `job_memory.peak_job_memory_bytes` (launcher v5 keeps it in a minimal receipt too). | launcher v5 |
| G5 | Confirmed by code: no child process inside `score_folds` (sklearn HGB OpenMP threads in-process; no n_jobs / joblib / multiprocessing; the runner's only subprocess is `git` in `verify_committed_gate`, at stage start). The "capped at 10" wording is corrected by v6 H4 below. | — |
| G6 | The masked launcher string, verbatim, is in the C3 addendum and above. | — |
| Item 9 | `set_guard_centres` asserts B ⊆ A (non-empty) and union = A; a `B_*centre*` field is checked against B's set. No written output carries an arm-specific centre today. | `RULING_V5_B_CENTRE_FIELDS = "B_*centre*"`, `centre_set_for` |

## v6 (the v5 review, final round 2026-11-03; runner v6 constants; C3 second addendum)

| Item | Change | Runner v6 constant / function |
| --- | --- | --- |
| H1 | Sentinel only: `{"B_note": "2026-01-08"}` gives `{"in_2026_before_05_27": 1}`; B's one sealed label, `2026-12-24`, is a HIT in `B_note` and passes in `B_centre`. | — |
| H2 | Ruling 1: `walk.json` gets the walk and the byte cross-check of its exact serialisation before it is written; on a hit the offending keys are withheld (HALT pre-score; arms INCOMPLETE post-score); if it still hits, only a minimal report is written. `output_guard.from` is now basic format (`20260101`). | `RULING_V6_REPORT_BYTE_CHECK = True`, `guard_report`, `report_guard_hits` |
| H4 | `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` are set (overriding) to 10 as the first statements of the runner, before numpy / sklearn / any bound module is imported. | `RULING_V6_THREADS = 10` |
| H3, H5 | Notes only; no change. | — |

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
| 0 | sentinel test v4 | 2026-11-03T04:40:49.2872160-05:00 | 2026-11-03T04:40:51.8190510-05:00 | 0 | PASS: 20 passed, 0 failed (0.98 s) | n/a (wrapper route) | n/a | wrapper stdout `2fd2e2b9666ee7b32d8254c7021785bc078d2eb6c872e633d0b77e0c3c4dd384`; queue events `3b0c25b5621cb16465f50042ef8f94660418ea66cec75f6bbdd883553bcf24a0` |
| 0b | launcher v6 smoke | 2026-11-03T04:49:42.0447358-05:00 | 2026-11-03T04:49:42.8680856-05:00 | 0 | PASS: COMPLETE, receipt guard 0, log guard 0, `verify_prev` accepts | 8,200,192 | `c2cd0e8f457f61a60b01efbe9d7a68b9e6e0feb67fd1a169cd720adaebcd7c52` | receipt `113fed54a73390d235e143c4d769dbd927ed0dd6306289e807c3143ccef04c1d`; walk.csv `d0eed41164ce99563bcd9c877001a3051c873bcffb944b60f5208951ec192816`; walker.stdout and walker.stderr empty |
| 1 | controls, attempt 1 (a3 OutDir) | 2026-11-03T04:59:32.4937137-05:00 (launch); walker 20261103T045933.185998-0500 | walker 20261103T050659.661172-0500 | 5 (walker 10) | HALT (run scope): runner output guard, 276 hits (detail withheld); C-0, C-0b (2 of 2), C-0c and C-b all PASS; launcher log guard 0, receipt guard 0, no FLAG | 2,213,126,144 | `f273414055f66542584b9c24422451c90a214fb0244c1c5bc4a86c6ee8a0236d` | receipt `a59473affb9663db96cfafac0b21101b29d62e136fe138930bbe51314d31b784`; walk.csv `c6f206e741f7fc4f9190a579e18f91c31c9d677fbb29ade85073615ed40f86c7`; walker.stdout `80194b7406dae5607849c03373eb08794b1923d037423d006183bfe02f30e5f7`; junction manifest before = after `f93c2ad2…`; 66 records files written to `run\records` |
| 1 | controls, attempt 1 (a2 OutDir) | 2026-11-03T04:56:15.7003831-05:00 (launch); walker 20261103T045616.401716-0500 | walker 20261103T045703.174957-0500 | 5 (walker 11) | PARTIAL: walker ERROR, `ColumnAllowlistError` (served artifact is an LFS pointer); no control computed; guard 0, receipt guard 0, no FLAG | 860,798,976 | `153d2af424271cd905d895536e09c72fdb5e12034fc717fe01839be9381d5d53` | receipt `2037644ebcdbf18f48c6440207d376fc1c008e8161116b3f594ff80ffc39ecc1`; walk.csv `7d48e52450407c4d661e2c6f0d83287f6c54c81b7a23fe960b2e3789297c4019`; junction manifest before = after `f93c2ad2…`; walker.stdout `9dfcd16a3dadb2e3668ba3b4d1fe08d05b290e953c63d729dcb9e48a2ba667fe` |
| 1 | controls, attempt 1 | 2026-11-03T04:44:06.8117678-05:00 (launch); walker 20261103T044407.510313-0500 | walker 20261103T044419.855352-0500 | 6 | HALT (R4 + G2 self-hit): no control computed; receipt withheld by its own guard (1 hit), peak 0.13 GB | 131,993,600 | `131c02110c447019085168213e77c1c69aa676177a115880701bb14b3f8f1a4f` | receipt `aa525676f5008b7e020d3524b0fc030831e838d6f43923c7016c4431832f6073`; walk.csv `c0813fac922f17b9c9ee86e8b2a09982b8afd87979e87f69f12dbcb77e66ef5d`; junction manifest before = after `f93c2ad20efdd85f90278cf4cfa7dae6bbbfa4201c30b649a01b30cf2b5318a7`; walker.stdout `eb9978c8ed451dc3c517d04d6deba01bd2049cd98129118ae966e23ca23224c3` |
| 2 | build | | | | | | | |
| 3 | integrity | | | | | | | |
| 4 | labels | | | | | | | |
| 5 | look | | | | | | | |
| 6 | score | | | | | | | |

Stage 0 detail: `workstation_heavy.ps1 -Kind pytest -Queue`, `PYTHONDONTWRITEBYTECODE=1`, args exactly the form
above; queue ticket 1, admitted to slot 2 of 3 with no busy slots, thread cap 10 of 32 logical processors; the
wrapper's stderr was empty. The queue events are the wrapper's own `data\logs\heavy_workload_queue.jsonl` in the
worktree (git-ignored; the wrapper created it). The basetemp `C:\t\L59\row28\sentinel_bt` was deleted and
`git status` was clean afterwards; the only ignored bytecode is a pre-existing `scripts/__pycache__/` from
2026-11-02 (fetch scripts), older than the run.

Stage 1 attempt 1 detail. The launcher form was exactly the RUN_LOG form above (launcher v5, runner v6, config
`66e4b46e…`); the launcher was pid 48060, and no process from it remains. The walker HALTed in run scope because
`C:\wt\L59row28\data` held `logs` beside the four approved junctions. The wrapper had created `logs` during the
stage-0 sentinel run. The walker computed no control. Its log guard was CLEAN (0 hits), the junction manifest was
unchanged, and walk.json and walk.csv hold no dated string (count-only check first).

- **Pre-approved remediation, steps 1–2 done.** The slot2.lock holder, pid 29232, is not alive, and no
  workstation_heavy process runs. On 2026-11-03T04:45:40-05:00 I *moved* (did not delete)
  `C:\wt\L59row28\data\logs\` to `C:\t\L59\row28\sentinel_wrapper_logs\`. The files and their sha256 were
  identical before and after the move:
  - `heavy_workload.slot2.lock`: 608 bytes, `b8c1e2cfd0fbb82ed02ed766f5344bd0fc11b71f8afcbae46cd9fb2527a50286`
  - `heavy_workload_queue.jsonl`: 1,066 bytes, `3b0c25b5621cb16465f50042ef8f94660418ea66cec75f6bbdd883553bcf24a0`

  `data\` now holds exactly the four junctions.
- **Attempt 1's folder** `C:\t\L59\row28\run\s1_controls` stays in place, untouched, as evidence.
- **Step 3 (relaunch) was held; master has now ruled** (C3 third addendum): launcher v6 fixes (a), and the new
  OutDir `run\s1_controls_a2` resolves (b). There were two blockers.
  - **(a) The launcher always fails its own receipt guard.** Launcher v5's G2 receipt guard scans the receipt
    JSON. That JSON embeds `output_guard.from = "2026-01-01"` (`$GuardFrom`), and that string matches the guard
    pattern. Every receipt therefore has at least 1 receipt-guard hit and is replaced by the minimal HALT receipt
    (exit 6). In a pre-score stage this HALTs even a clean walk, and verify_prev (F4/G2) can never accept it.
    This attempt's `receipt_guard_hits` is 1, consistent with that constant alone.
  - **(b) The OutDir already exists.** The launcher refuses an OutDir that already exists, so an unchanged
    relaunch into `run\s1_controls` would be refused.

Stage 0b (launcher v6 smoke) detail.
- **Run.** The child was `scripts/row28_smoke_noop_v1.py` (`a8a53010…`, committed in `c5121ebb4` before the run),
  started by launcher v6 with `-Stage controls`, the stage-1 config and `-TimeboxSeconds 14400`.
- **Receipt.** Status COMPLETE, exit 0. `output_guard` was `from` `20260101` with `hits_total` 0. There is no
  `receipt_guard_hits` field, because the full receipt is written only when G2 counts 0. The receipt does hold 2 raw
  dated strings; both are masked (the exception text and the folder token in `walker`).
- **Peak.** `peak_job_memory_bytes` was 8,200,192.
- **verify_prev.** `scripts/row28_smoke_verify_v1.py` runs runner v6's `verify_prev` source, extracted by ast and
  unchanged; it does not import the runner. Its output: `PASS verify_prev accepted controls`. Every check in
  `verify_prev` was exercised, including the stage and `walker_sha256` = `runner_sha256` binding. Negative control:
  on `run\s1_controls` (attempt 1) the same call refuses, with "status HALT is not ('PASS',)".

Stage-launch dated-string scans (reviewer note 4; repeated before every stage launch). The scan looks for ISO dates
on or after 2026-01-01 in the `--roots` config's contents and in its file name.
- **Before controls a2** (2026-11-03T04:56:06-05:00): `stage1_controls_v2.json` (`66e4b46e…`) had 0 dated strings
  in its contents and 0 in its name (0 on or after 2026-05-27, 0 in 2026 before 05-27). It names neither
  `cap_counts_v2.json` nor `r4_deciding_dates_receipt.json`.
- **Pre-launch state:** `data\` held exactly the four junctions, and no workstation_heavy, wrapper or row-28
  launcher process was running.

Stage 1, attempt 1 (a2 OutDir) detail.
- **Launch.** Launcher v6 started as pid 22924 in the RUN_LOG form, with OutDir `run\s1_controls_a2` and without
  `PYTHONWARNINGS`. Its stderr was empty, and none of its processes remain.
- **Receipt.** The full receipt (not the minimal one) shows status PARTIAL, launcher exit 5 and walker exit code 11
  (runner status ERROR). `output_guard` has `hits_total` 0 and `from` `20260101`. There are no receipt guard hits
  and no `output_guard_flag`.
- **walk.json.** It holds 3 raw dated strings, all of them the masked folder token in the traceback paths, and
  nothing else dated. Its report guard is CLEAN. The junction manifest is unchanged, and the only junction read is
  `training`.
- **Cause.** The error came in `stage_controls` at the first `extract(prm.AUG_SEP_CENTRES)`, through
  `pooled_residual_model.extract_market`, then `resolve_column_allowlist`, then `served_feature_names`. It raised
  `ColumnAllowlistError`: "served artifact is an LFS pointer: `C:\wt\L59row28\artifacts\models\hgb\feature_model_hgb_atlanta.pkl`".
  - In the worktree, all 26 LFS-tracked files (`artifacts/models/hgb`) are 133-byte pointers, never checked out.
  - All 26 objects are present in the shared local LFS store (the worktree's git common dir).
  - The main checkout has them materialised.
- **Results.** No control check (C-0, C-0b, C-0c, C-b) ran, so there are no counts and no pass/fail.
- **Folder.** `run\s1_controls_a2` stays in place as evidence. Nothing was repaired.

LFS repair before a3. The checkout was local only: `git -C C:\wt\L59row28 lfs checkout artifacts/models/hgb`, with
`lfs.url` and `remote.origin.lfsurl` set to an unroutable address. 26 of 26 objects came from the shared local store
(0 B/s); the main checkout was not touched, and `git status` stayed clean. Every file's sha256 and size equal the oid
and size of its pointer committed at HEAD. The second `.gitattributes` LFS pattern (`docs/roadmap/...*.zip`) matches
no file in this tree, and no pointer remains under `artifacts/`, `src/` or `config/`. Table sha256 (the 26 rows
below, joined by LF): `f39da351331bbec8c8e9051ef937fa7fcdb6153f7405abda28a02dcf29abd1cf`.

| Path | LFS oid (sha256) | Size (bytes) |
| --- | --- | --- |
| `artifacts/models/hgb/feature_model_hgb.pkl` | `bf53fd60db1a8b28cbfc2ae7844370246884e90dab7d63a558fd477a262d732a` | 29230281 |
| `artifacts/models/hgb/feature_model_hgb_atlanta.pkl` | `9f045926126ab37bbc71b2c7db97b79cda8061c36c0fae93f2e12495493c9b9f` | 15149102 |
| `artifacts/models/hgb/feature_model_hgb_austin.pkl` | `98f5b72b23814f8886acee79d029de475b834322ad7d89631d7423a443586765` | 13495031 |
| `artifacts/models/hgb/feature_model_hgb_chicago.pkl` | `be24eab615a9c6375a369537a9ed1dd8e650d49cdca35e941184f524cf1401a2` | 19713433 |
| `artifacts/models/hgb/feature_model_hgb_dallas.pkl` | `5ee8722d86105067af92838fe4660e757ee26366d06acfe500532691f2152862` | 14798766 |
| `artifacts/models/hgb/feature_model_hgb_denver.pkl` | `2047b667fce7654e4879553c237d8561721f12f56eb746874fc0a241347ea7e8` | 22704111 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled.pkl` | `47687e207a8e3ffd22e994d460cc37bdd83d6284776540dd4c00ad5525d087c1` | 103734643 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_clob_overlay_v0_1.pkl` | `24cd6b19115aa55f48885d1d7cda241e69900941a53291dafd02a208ce57746a` | 191225 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl` | `c4eaa40df23a43702cbf3fdecd5be0d190235b0e832653e690b3e8196aabe3bc` | 211935 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_dynamic_source_smoke.pkl` | `0a53dc001930d616759eebf3d301216e99c31afe9094b00e392a776d9d0daf10` | 4958646 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_dynamic_source_v0_1.pkl` | `ee7b65d078961bf21c3f89ff6e359d0acca5f3fedc90e456bf0192e4656867e9` | 5460537 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_exact_winner_smoke.pkl` | `6fbbe100c3df3533fbc9033b4c13d1eaf811479996a77013526c0a5aa7643992` | 5021537 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_exact_winner_v0_1.pkl` | `cf1a385b2f92810ba31c7974ce0511cb42653dbab4325599bb29e199a17e7d4d` | 5432706 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_exact_winner_v0_1_alpha005.pkl` | `6783d8fc4b066fdf22fcd71e5dbd9c57f8f021655f525c3fc513cc1877e56959` | 5432466 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_exact_winner_v0_1_alpha01.pkl` | `a7670f04e2b66d0e535e3bf4b5fe19de8b7708060d1ea6f2e2fd5b39e1bab96e` | 5432466 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_exact_winner_v0_1_alpha02.pkl` | `da75d415104644c1c88811cf0cec8d3580f00ff28385cef117db4b34fc1f8956` | 5432466 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_2.pkl` | `b7933690c80ec9c34e220992de615361e6904518e7792ccf0c705983276b6e89` | 5028078 |
| `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl` | `3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c` | 6310781 |
| `artifacts/models/hgb/feature_model_hgb_houston.pkl` | `19999a254056ae009fd65089747e158a0b722cbead541d20b3d39cee295c49ba` | 10575344 |
| `artifacts/models/hgb/feature_model_hgb_los-angeles.pkl` | `8d9aba849cf95f676be1ec0183431dfe5b04db0e55f8cfca9adadb08ad167b5c` | 11152210 |
| `artifacts/models/hgb/feature_model_hgb_miami.pkl` | `7b59bc1175108d08eb3163cac9b31cedd6ac174ec9ffe4cd296c4c4bea15fd9f` | 20742776 |
| `artifacts/models/hgb/feature_model_hgb_nyc.pkl` | `a8efd8067b2ff19249fdf125fb56dd4bd25f7b1db9454e81f70cf21dd82201d4` | 18735619 |
| `artifacts/models/hgb/feature_model_hgb_san-francisco.pkl` | `c9b77d8326bff055466631e413e810c61f428416c5b9f1aad549c5e0bc17972f` | 18096992 |
| `artifacts/models/hgb/feature_model_hgb_seattle.pkl` | `ad6229d851484f30c4caaf5f77fd16a018ed5af11bccb67351311f6f3872bfa1` | 19800416 |
| `artifacts/models/hgb/item35_density_full_candidate.pkl` | `56b03f8d5769d76d28aaad78752d78869c0dc816f906e091f10e2ca98c6c88ab` | 7594227 |
| `artifacts/models/hgb/item50_feature_model_hgb_f_pooled_v0_3_candidate.pkl` | `befe90ef947396b26c24a5f30bc8886624b4bbef23af7270fd84a43a6649f4f5` | 5978191 |

Pre-launch scan before controls a3 (2026-11-03T04:59:26-05:00):
- The OutDir name `run\s1_controls_a3`, the stage `controls`, and the config's name and contents (`66e4b46e…`) each
  hold 0 dated strings on or after 2026-01-01.
- `data\` held exactly the four junctions, and no wrapper or launcher process was running.

Stage 1, attempt 1 (a3 OutDir) detail.
- **Launch.** Launcher v6 started as pid 34908 in the RUN_LOG form, with OutDir
  `run\s1_controls_a3`. Its stdout sha is `b331b84b…` and its stderr was empty; no process remains.
- **Receipt.** The full receipt shows status PARTIAL, launcher exit 5 and walker exit code 10 (runner status HALT,
  scope run). It records `output_guard.hits_total` 0 for the logs, no receipt guard hit and no `output_guard_flag`.
- **Runner HALT.** walk.json gives the reason "output guard: 276 hit(s)". The runner withheld its own `output_guard`
  block (`report_keys_withheld_bytes: ["output_guard"]`), so where the hits fell is not in the report.
  `halted_arms` is empty.
- **Controls, at the permitted level (pass/fail and counts only):**
  - C-0: PASS, 19,657 rows, identical keys, max abs diff 0.0 for brier and log.
  - C-0b: 2 of 2 centres PASS, identical keys.
  - C-0c: PASS, 4,125 compared, 0 mismatched, 0 L9-only.
  - C-b: PASS, 660 rows, max abs diff 0.0.
- **Dated strings in the outputs (count only; values not read).**
  - walk.json holds 158, all under context-scoped keys: `records_sha256` (66 keys), `outputs_sha256` (66 records
    paths), `covered_years` (24 centre fields) and `C_0b` (2 centre fields).
  - walk.csv holds 66, the records paths.
- **Other state.** The junction manifest was unchanged, and the only junction read was `training`. The 66 records
  files stay in `run\records`, so the controls stage's empty-records-root check would refuse a rerun into it. The
  a2 and a3 folders stay in place as evidence.

Gate commits: integrity — (pending); look — (pending).

## Appended 2026-11-03T05:25-05:00: d1 diagnostic, root cause, runner v7 (append only)

- **d1 guard diagnostic.**
  - Script `scripts/row28_guard_diag_v1.py`, sha256 `adad5ce6903cc629d077dbcd6bad6524602fb3f77463ddfdf55af926c3bda08e`, committed in `9b663b95e` before it ran.
  - It ran under launcher v6 (pid 25656, from 05:13:40, `-Stage controls` as the launcher's label) into
    `run\d1_guard_diag`, after the dated-name scan found 0.
  - Receipt `3bc30bd065fc20fabba6f21c85e0dc8a0fde81b2222fda1f82c792c9435c01c9`: COMPLETE, exit 0, log guard 0,
    receipt guard 0, peak 800,739,328 bytes.
  - walk.json `a2c8c56f63e9ebd1866fcead0eb5d1517c3b1c5bdc8cf5c14def005a8cb40f36`; walk.csv
    `ab8f8a316c827132760d1678df9b9aaf2121f4c749f5662a81f32737dab71d35`.
  - RECONCILED: 276 / 276 / 276, walk.json 158 / 158, walk.csv 66 / 66, 0 trace mismatches.
  - Rule (c) count 276, so it STOPPED.
- **Verdict.** BENIGN, per master: the 276 are the `r0_scope.py:51-52` decision constants at
  `plan/column_differences_from_served/decision` (C3 fifth addendum). d2 was not run.
- **Quarantine.** `run\records`, `run\s1_controls_a3` and `run\d1_guard_diag` are in place. None has been moved,
  opened or copied since. The records folder moves to `run\records_a3_evidence` only on the coordinator's go after
  the v7 review.

### A(i): the "33 of 68" (code only)

The d1 diagnostic keys `per_file` by the class-tagged file name (`row28_guard_diag_v1.py`, `templ(relpath)`).
"33" is therefore a count of distinct tagged names, not of files.
- **The scope.** The runner's own `output_guard_scan` scanned 68 real files: the 66 records files plus a3's
  `junction_manifest_before.json.gz` and `junction_manifest_after.json.gz`. walk.json, walk.csv, the logs and
  receipt.json are excluded.
- **The 33 tagged names.** Each market has 6 records files: the four `AUG_SEP_CENTRES` (08-08, 08-23, 09-07, 09-22)
  are all GAP, 12-09 is EMBARGO and 01-08 is Y26_PRE0527. That is 3 tagged names per market, 11 × 3 = 33, plus 2
  manifest names, so 35 in all.
- **Every records file has hits.** The manifests are clean: their sha `f93c2ad2…` is identical to a2's, which
  scanned CLEAN. So the 33 names with hits are all 33 records names. A market's plan is
  `resolve_column_allowlist(f"r0:{market}")` (`pooled_residual_model.py:224`), which depends on the market only,
  so all 6 files of a market carry the same `column_differences_from_served`. Every market therefore has at least
  one decision row in all 6 of its files: 66 of 66 real files have hits.
- **Consistency.** 276 = 6 × 46, i.e. 46 dated decision tokens per market set, summed over the 11 markets.
- **No coverage hole.** All 66 records files were scanned (68 = 66 + 2).

### v7 (runner v7, sentinel v5; not run)

| File | sha256 |
| --- | --- |
| Runner v7, `scripts/row28_run_v7.py` (from v6 by `make_v7.py`, 12 exact replacements) | `85f50b9ca10063d7b8e05370d6cbd9c4cf5b2c5825708fdc6ba7d1ebc8c688a3` |
| Sentinel test v5, `scripts/test_row28_s7_sentinel_v5.py` (pins runner v7) | `f596c8537a4de7ac370b6e4bd858df02f7ae9518ec8e5262405ac1be79366532` |
| `CLARIFICATION_3.md` (five addenda) | `e57a2d6d6a1537ffd53c2bf6468ac499f364ea9c8df3d81f692e8a06f032f998` |
| `src/weather/calibration/r0_scope.py` (pinned by runner v7 K1) | `e8bb0683ed7c252b4f07e18f83709c9e0a5fcfd4c835d803b80c5c531f18607b` |

- **K1.** The records decision allowance described above: pinned, whole value, exact path, counted in walk.json
  `output_guard.decision_allowance`.
- **K2.** tz-aware datetime arrays are walked as `isoformat` strings.
- **K3.** pandas `Period` values are walked as `str(o)`.
- **Sentinel v5** is v4 plus four tests:
  - K1 at exact path and whole value: altered strings, wrong paths, non-records files and non-constant dates are
    all hits, and the firings are counted;
  - K1 pins fail closed on a sha or string change;
  - K1 firings are reported by `output_guard_scan`;
  - every temporal type.
- **Static checks.** ast parse, symtable undefined names (only `__file__`, as in v6) and control bytes: clean.
  Nothing was run.
- **a4 targets** (after the v7 review is CLEAN and on the coordinator's go):
  - C-0 19,657 / 0.0; C-0b 2 of 2; C-0c 4,125 / 0; C-b 660 / 0.0;
  - the records sha manifest equal to a3's;
  - output guard 0, with the allowance firing `dated_tokens` = 276.
  Any deviation STOPs.

## Appended 2026-11-03T05:46:52-05:00: records move, controls a4 (STOP: records manifest deviation) (append only)

- **Quiesce** (05:37:42). `data\` held exactly the four junctions. No wrapper, launcher or runner of mine was
  running; the only matching processes were two `tail.exe` log followers on `fetch\*.log`.
- **Move** (05:38:06). `run\records` was moved to `run\records_a3_evidence` (a rename; afterwards `run\records`
  was absent). a2, a3 and d1 were not touched. The sha manifest below was computed from the moved files.
- **Pre-launch scan** (05:38:17). The OutDir name `s1_controls_a4` and its full path, the stage `controls`, and the
  config's name and contents (`stage1_controls_v2.json`, `66e4b46e…`, unchanged) each have 0 ISO dates on or
  after 2026-01-01. The config names neither `cap_counts_v2.json` nor `r4_deciding_dates_receipt.json`. Launcher v6
  is `8a2f8759…`, runner v7 is `85f50b9c…`, and `run\s1_controls_a4` did not exist.
- **Launch.** Launcher v6 started as pid 2972 at 05:38:23.79 in the RUN_LOG form, with OutDir
  `run\s1_controls_a4`, runner v7 and `-ExpectSha 85f50b9c…`. Launcher stdout is `adc641d5…`; launcher stderr,
  walker.stderr and the walker log are empty. Walker pid 45356 ran from 20261103T053833 to 20261103T054555.
  No process remains.
- **Receipt.** Status COMPLETE, walker exit code 0, receipt guard 0, no FLAG.
  - receipt.json is `9c288c9f44de36c76aa804bfd0f64387cd34840e21c1244b753644ed2bc2c0d2`.
  - walk.json is `198e15c78b1f423b5bb7aa946021fc9465a02171e1c2c3425924c33a81c5c0f8`.
  - walk.csv is `54ec62e57ad19fe1542ac94c22bb1856c5e5e75ab30383dd593c3b0a5f792d38`.
  - walker.stdout is `941b9c6c…`.
  - Peak Job memory is 2,215,063,552 bytes.
  - The junction manifest is unchanged (before = after `f93c2ad2…`).
- **Runner.** Status PASS. The output guard is CLEAN: 68 files scanned, 0 hits, nothing withheld.
  - `decision_allowance` is `dated_tokens` 276 and `values` 144.
  - `decision_pins` holds r0_scope `e8bb0683…`, 2 values.
- **Controls, all equal to a3.**
  - C-0: 19,657 of 19,657 rows, identical keys, max abs diff Brier 0.0 and log 0.0.
  - C-0b: 2 of 2 PASS.
  - C-0c: 4,125 compared, 0 mismatched.
  - C-b: 660 rows, 0.0, no arm halted.
- **DEVIATION: the records sha manifest is not a3's.** Names and sizes are equal for 66 of 66 files, but the sha256
  differs on 66 of 66. walk.json's `records_sha256` equals the a4 files on disk, and `records_a3_evidence`
  re-hashes to its move-time manifest, so neither side changed after it was written.
  - **Cause (byte comparison only, nothing parsed):** each a3 file and its a4 file are byte-identical except the
    gzip header MTIME field (bytes 4-8), which differs in all 66. Their decompressed payloads are equal in all 66.
  - **Why the MTIME differs:** `pooled_residual_model.py:256` writes records with `gzip.open(tmp, "wb")`, which
    stamps the header with the write time. The runner's own Writer uses `gzip.compress(data, mtime=0)` (runner
    v7:392), but records are not written through it.
  - **Disclosure:** to locate the cause, the a3 evidence bytes were read for byte comparison and gzip-decompressed
    for a sha comparison. Nothing was parsed or logged beyond counts.
- **walk.csv vs a3 (sha only).** The whole-file shas differ (`54ec62e5…` vs a3's `c6f206e7…`). a4's walk.csv has 68
  rows: the 66 records rows, whose shas differ for the reason above, and 2 other rows. a3's walk.csv was not opened.
- **STOP** per the brief. Runner v8 and sentinel v6 were not written. Build was not started.

Records sha manifest (`run\records_a3_evidence` at the move, and the a4 `run\records`). The year (2026) is elided
from the centre in each name:

| File (`records_<market>_2026-<MM-DD>.pkl.gz`) | Size | a3 sha256 (`records_a3_evidence`) | a4 sha256 (`records`) |
| --- | --- | --- | --- |
| `atlanta` `01-08` | 140377 | `eb44e776c6af55c7d809b4edffff53372d1905b8d6efacedd35add6339bebeae` | `164611fd0edf6459d4731f46126e8fd17d7acd197b456d79fe02efd68e74c68c` |
| `atlanta` `08-08` | 222250 | `1df980e455930e9edfbbe6ba07b540bb76eac515d353625fe0355099f0936c5d` | `ab16f87e7a863268a7b06b57aa0d3bf0b7cfe6753cc52cfaab70df129f36fec1` |
| `atlanta` `08-23` | 219394 | `7ef8e10660099825bb28b15f8eed54c8ea351eb39f72542787a1156fcba6db8e` | `549bd782fd4707a7cb344ca9aaae23d4f2b013dcfe1da0a5bef48ab165fdc47c` |
| `atlanta` `09-07` | 216409 | `58759de168caf2fc2da069f684a54547a8edb0e578ed4deb0d1473542cb0dd95` | `eb80390939b3a1d143c83e747a862c0dfd08af6ea2672748f58d29e15ac88a80` |
| `atlanta` `09-22` | 222892 | `16a8556bb5b08262caa49b3f3922a84c95b61d3cfcdf7d1788e7b67b55be212a` | `2bc17558b8f2b12fa55cf0f4db5c4e501825904affdc351bc2e1c09fad9641cb` |
| `atlanta` `12-09` | 231395 | `37aeb249615e234b563015b23197d9273d508ac0d34e6f8954e8510590bd4b3b` | `f0ddd005d0023d54bd30d45e58e54610140980416589dc7367e5e37ad0ebddbb` |
| `austin` `01-08` | 140482 | `6586946dd1affcddc4882dac8fe1781df1f28f996f852ae5bd655ee493dfc3ab` | `4ec9a9acb3688ad8631adff6df438474fa2f46ab7a1ac18652912c2a58678697` |
| `austin` `08-08` | 214164 | `d96064173c5cb2bd1a3314f0dc8589d92f867265064c9f824e1663cf866e3836` | `b18944dc4e0cd179aa1a77f0733ef9ecfe5ce5c9a809ba1ebf98efc50938eca8` |
| `austin` `08-23` | 219352 | `5bd420acb1450d15b4d55386576b37b44dfa558f14aae70cae6b8fa9c97d4165` | `d5208482e4310add24b42f972ad05db73a21ea6803341f82d2f9d5ffe56344a9` |
| `austin` `09-07` | 216983 | `387b2cc01e96d92f540d9addeeddf553fd4629c75b53a882699057f05c77254d` | `9d107e41a713a3f1b3306a73919a2aeca810b00ac94ee71eaed044df40a71a99` |
| `austin` `09-22` | 216446 | `72169d86972fb038d1c5273a67fcd19f0751116698d83faf32832381d6ac8861` | `0ffe40ec9ab0abb7a93c7aec93cbb1d42a0087cb9bdbaef1aed3b9491d83b863` |
| `austin` `12-09` | 233397 | `81f5bca9b33f8ac9fcc8398036e0c54ed97ac683ad2c6b988495e6e3e76c4599` | `d19ae554c5845750dff57869343a43252780d5bb9a4bcaa7d728a4b4d8d87fce` |
| `chicago` `01-08` | 140743 | `5379d294144b9d9db08398a1843867acd35f9849f4de98570ca69da40538899a` | `d0d2ec36d6a604b7265876d6f62ae52e43d2eb7b60c3b940985f4241446b0ef7` |
| `chicago` `08-08` | 224626 | `ae95e56fc146514f5c7dfbb5fcddb7e7fdb6b60bcc43320ada9a85b871a0e815` | `de1a4ebdae419f915285a6633be101cda4c8002293bc46724c1ba9cea367deb9` |
| `chicago` `08-23` | 225775 | `6fba44875fa7f7fa15cb1b0725559720ed02a1ea8b8f1de3dd56c89bb1a142a2` | `b2e5123e20101374f3fb2da2779b991b06ed1fdf8eb206cf4cbee6ea32ff5ae9` |
| `chicago` `09-07` | 225567 | `f4a9e1a92fde4909c66a5186e95f99a693f0422ceea930512a1998d3a73c5e06` | `1c6d8f8b0f77ad0f0ee85a608a971f44fff13392252843fa9a77b84f2086bd85` |
| `chicago` `09-22` | 225610 | `ffd74a3e0e48742ac9fcad8b4cc26be43799d94a0abf9b2f8bed16ffbe08ed36` | `d22bd08b689622b1952a000a5d326dff515749cef641427a03882c6a5cbb8f68` |
| `chicago` `12-09` | 231724 | `be008ee82e8e4e39107d923beb72c9b1f0c91354bd71290a167ebff8dedb8f3d` | `99cb67270243fdeed9a9b139b9c5df9f6c4e819b6387292da1b08868547087b3` |
| `dallas` `01-08` | 141932 | `5d3d73fb76cfc01edfe13937ef1549766256e8054ff0da3660682170859d227a` | `164e4bf5faf5a47e5f622ac582b5d68003c4679ac1f16fdac84910b5c0fcca55` |
| `dallas` `08-08` | 216161 | `87db13adaf8ead57507187138853da0f2b110d1cb1166fc9c1ed18a001a590a2` | `003ee54fd67dfd8dc105b5607dcecead33370a497dbddfba539868ff1a0d60c4` |
| `dallas` `08-23` | 220558 | `2dea83c48a9b169c7eea9fc46c116b140f63add3cfb1322184467b5bf7a07e98` | `69f6c41dc0b4bebe4cfd7521a7e376a772ac1d6ec79762ffa09c18d3b89b412e` |
| `dallas` `09-07` | 218378 | `03fdf0e640d06e590b7c56edaa78c8a63f5e73bfe9a0b48c77520e926b7ee089` | `91ad9b8b84e2c5309ad4095e078838114dcc52e968a4e5d0d5fc1ce6cf27df11` |
| `dallas` `09-22` | 220450 | `fcb3bc99fb9a7f626d18d12bcf26f5fda6d9a90d0c5970af26d4c73ebb2023fa` | `cdcf12eaa7909ad2d9f4ccf33c384ad4159a73bcc61a3bea021a1195551b348f` |
| `dallas` `12-09` | 233736 | `4fb414a569132c9c010f0e9151cf9efa567c106ede516fae0c3518e9109ee696` | `dbff0c79446752d8e65a6ca188109fc1e5e9bf995854d4d64c0aaf0b5c2df6e4` |
| `denver` `01-08` | 135819 | `568c7e9253b9e549b279b00d51b330cb8e58db720bd82055cb92f631cd790858` | `5ddb0c0ea060d1b762304a9895991b706938ff72989edefbad58ab771a586f31` |
| `denver` `08-08` | 225928 | `b885cc2d98bc12f48d375e034eecbee6664d078793aca2771d8a35c984dd68e8` | `eaaff24324340651078f74bb8fa182f6d10ecd75d406acd51ef702bf08b0f5d4` |
| `denver` `08-23` | 220772 | `1f2913cb6b4917432825b8ef86122f044d0109d3dcc6fc3ca531417f597c7397` | `a36b59bc2aa13034e8a50c83d1132fdab11b69e69936d06e8de8558be68bd4a9` |
| `denver` `09-07` | 207926 | `cfeadba77a2c2ca04c7b32145ed1209b8c8d339ac27c4a92296c790b5c594a2a` | `9ab2ea29bbe33ff664a7e48aed95f0220d26c1126216379dfb16d728f3f065c8` |
| `denver` `09-22` | 221630 | `693581d5bd42985a192d6ba29ed4ee94110f8b6b44b03f19024b0b192dd2a812` | `74c100ad4fd14e8498addc1bccf5e93a6493b690f96203c59820e4007465f587` |
| `denver` `12-09` | 225562 | `9fb0b2e3bce8a296de90d559d47a94daa7817b521bc8d38576258134c00d07d4` | `0642651dc7dcc382288fecab2daf0e6751d0c5585e605525c7ea3b38b9f2a3d9` |
| `houston` `01-08` | 143411 | `537af6deb1cedd41a68641fa0196034550527c1a384b681ee8a8aa0e6d077c48` | `0ed04798892abec38ae02414ec535b7500e87fb9c79df324eb65b8020f16565e` |
| `houston` `08-08` | 215191 | `f9bc10ecf5c83b117f369bf20dcdca0e35ba7fa88b3d467cf289c02d2ca856ee` | `f1c105903f5798dd02a611c0c0c927e2a98eb4ef97279975027967cff130281d` |
| `houston` `08-23` | 218969 | `a5318723975bce79e0e40fcc2a3f3e65ca3eb48ad6bbeb1f7936b7f51a0fb356` | `fb6ff75e388a77c5ee53986df3ae262700289fcd2a223bcbcd90af55fab79a09` |
| `houston` `09-07` | 217622 | `eda3a7954766db8554950a3d6822859d903cceaab1c474c643938a4cba813033` | `6bb6c8002fc3a16c52f574995fcbc0fa545b91356a250c165ced89f52d31481e` |
| `houston` `09-22` | 218086 | `fb19456676400ea40d45816a638142486e4167b4a22065b8399d2d24957de9ad` | `f267c863c4f08d3d973ba00d1baa0e7d3afe17f8058d480e9bab9cae9582627f` |
| `houston` `12-09` | 231673 | `108580b4b4df76f5fddc01f794e6912f9142ee8391cebda4f6972f9a9bc1401e` | `7e405ecce4a64a44ab8b69a69b937624ccf740cce641f4842199857b07bbbfa9` |
| `los-angeles` `01-08` | 135195 | `d4cf8f70bd6a881467a766e3af68e88cebe84bc6b57d257f9882cb9b20457d11` | `05629aab893698dcee4c63a12411715c14110641d0f7fb178c88cc442c4f7352` |
| `los-angeles` `08-08` | 208092 | `d3d7a68eb1dbb9fb84989a99c58be0ac0337e1ad581c8981bfe186f0c31799c8` | `b29be56e7d710822e2e651f6718d79de4bbdc7eda44965f2a08a2d4f88e9b5b8` |
| `los-angeles` `08-23` | 211511 | `e4863af37733a1ca8341cf46e26f3105ac41502a82b0af656dc3222b504fb2a9` | `a92678ea7b0259910d63575a8fd9bc390216417c9fee47b42c6dce1c83948af8` |
| `los-angeles` `09-07` | 209733 | `edeb3a2d60b3655952be19cf7b221007042d14c406e3cc9509696e2f3e7a8998` | `c8affe5d874955c81b2d28b9c52ab4870abd10ccb398c4ef189ad06b65041854` |
| `los-angeles` `09-22` | 213927 | `5371f46d4db6a9f240b65bda6803ca7eff66399aceb4cd26c141b488f940c6c6` | `6e7e2d6bb4076462fbe1d4d4a47ead0c0652d46f06f1a2c700de4dceacd61aa7` |
| `los-angeles` `12-09` | 215475 | `88f33c264fa4da638d044374026b420aadb4047856c6dc36e67023561313d459` | `4387b550bdc344a50a7794678e4d51f8e8ee7e191ac3fd54d70ae9993069e285` |
| `miami` `01-08` | 135579 | `d68c8d46f5ab2e693d105b1d1186b214eccb28add1c73057c5b27668e4163208` | `6f232badbe99d71fcdf3e88b9bb40d41ced8258ce66e8b866a06b29e517f58c0` |
| `miami` `08-08` | 208305 | `daa31f46e4061f7dae9777d36b60a11807aad7818b3bc78eab5fdc924f083ddc` | `5d8d247389f8e24bce538b248029952690c5bc07bc01609c36d7f8923c5a33ec` |
| `miami` `08-23` | 209860 | `270839aaede43ae948db52de06d9eb00a02ba836b4be1d9743a86c7a8751d680` | `a22d1bb5fe50fd0361b770fb62521b60239237ae08a8b474bcfd5123d2d9d5de` |
| `miami` `09-07` | 208060 | `80fb9e7229d624b890cde49496b6b8ba5bc21eaee41c54f0064750933ec1ce72` | `4070c1e924442bc90496f0cd900191e95b082f775eca6b114af81f82480aeae1` |
| `miami` `09-22` | 214530 | `dfe389ea257171c457d1242e5996f72c102601f6e8942268c85fbc34abd24c9c` | `c9bb3d6bf97eeaeb4174b13f78a0a25290442a7499c81584ba51cc7fdf5ab8f0` |
| `miami` `12-09` | 215437 | `f7f9dff959d13653cafb3c8be7f12f5446ca2bda2ee30a62d1348f21c2d388fc` | `797c6ad56374076a261ca49cefc2870be9d5cd3195649573ea5b713e37dfdedd` |
| `nyc` `01-08` | 137855 | `b5441b7f99adafd2ecf7ded7e137c8d05323692948bbd7fc7cadfdfcd4d7ac42` | `154ee1fcc4a95068ba784098421e4bb89eaf8efaa19a6d48e5ceea8f43b6bf42` |
| `nyc` `08-08` | 224704 | `ed376c3beac42cf16a0835551daf0eb283f22fb01e137269cc8408aba324605b` | `4ea37afb677cc60569f4e58c6d5c79e9538e1c701fa811c5e9cb3eb0724d36ba` |
| `nyc` `08-23` | 225720 | `0674d49456a62ef6e75975b00c0a6757c09ecd7325d1f42f8191ba16e4ee725d` | `70832be10afa98c1e8c25cc0ece1c421497884eb963182756929185c430455b0` |
| `nyc` `09-07` | 222216 | `f9c3f77ee9bdd819cfb07ded0263bff7cea4ffc3dc2a4ef242360fb9f85e3672` | `d067798a0e75d31b0a6759378c64458943fbed24d24a6df58fe09c17299eda1e` |
| `nyc` `09-22` | 225307 | `5046009e1fa8a72a5aaca04539f5fcbb75a0788badc27a29c1afd9237017fa3b` | `ddea9f7f02b62e738343c96de056585dd4c536e527b0084773de9c646972f8a4` |
| `nyc` `12-09` | 230199 | `224755dc99f655dd61673028e1035f3b76addb15bb00cd7c3a1b0f4cbb854722` | `57d9fefaaa736ec728b7db0afb05276efcf93305461348bf178117c462a30b6c` |
| `san-francisco` `01-08` | 135132 | `596df8ff76f6fc0d1c71817100370b696bf396bd9d419065f98fa60a5e07b92a` | `7eead4fe27892fe60e8afcdf55bb1a3f1367854702d577262002e7ec9b66db0d` |
| `san-francisco` `08-08` | 215875 | `45603008179e83831caf37e630ec209b5a532d2ad44e74b6cb92dfef176876eb` | `9226d9475bae28f359300948e72bc13d5874cf028d22d181eaca300afe295780` |
| `san-francisco` `08-23` | 215647 | `d9b095d149a04380464fb149ecc00cb6af262b8f1c77b7434859f8346fc7c1c3` | `0e3ef5b2851cc48f511507a84d7dce5d5c9d109ddea1f76715ce7332b712322d` |
| `san-francisco` `09-07` | 214429 | `6896ec49c1eadc7a62c37a8c5f1d060b0e17dad85a0ea07e25289513954a8edd` | `808dd14d2747300501ee38b9eb36897acf9e4a08b26da963b6fc3b47ee72df3d` |
| `san-francisco` `09-22` | 221236 | `c20d0004390854f4e9c1e678dce71ed4f7a2ff9f16d992392a939df3e9d62071` | `852bb9402214f8f992e1d281526ade60e58f3b36f5fdda7e66595ea98e818d44` |
| `san-francisco` `12-09` | 219369 | `f951f3723e687a40d701fe1576b8a696538599885e5b027cf76adcdd6402a04b` | `dacbff24af00f7ba6d53d844c543e8c84e249950c5235e17a05b7804a182fbad` |
| `seattle` `01-08` | 137082 | `0978cf7af0d134c0d4dbc49bf8e0c3ceeaff2726d17d9c1363cc03349e2ec55b` | `bbcbc6768fc7f8008caf77e3b8c4d3a40cc03bacea3683648b48ca93bd24982f` |
| `seattle` `08-08` | 225967 | `c3d1521704e7e297ac0948df8ced4ef013ac61f8d36acc0e06fa88c29f3c00aa` | `8db1a89a78b5e8fea84c5ab324bf3f5c0e4947b5f67eff2dc51401948d513ba2` |
| `seattle` `08-23` | 226906 | `fbe013756b926db0e03da55c93e0f3da3f9f92a8e98dfc01f118658d0fe8bac7` | `e83f72c27f40fc8c7dd16b43bb990a0faed78653ccb4aeb50ba187cbf0de4f11` |
| `seattle` `09-07` | 220539 | `7550681604d2b01e838533057edb3607cc96fb3820b0f355948114393e3998a9` | `2b572f636848016ca0ae0dddbeb38e6595b385116d04dbf5b6cf35f6ff526b0d` |
| `seattle` `09-22` | 226880 | `3c3bd80a72b4b01e35fae6206aa6d275634ec7895d1885941d5207e114e3c1f6` | `d8ecf3d34ce3f1653da8e81d31861203ab28f1323a41d38aa46f0461a1f0c1b1` |
| `seattle` `12-09` | 223491 | `2f9785a8c888067fd693456eb424d75d6fbb35f349ddba1b07561139e5eb7e20` | `2859d1c7d040b2529723ce04ff83ad0ff530a8813c5fe7e70ce0f8b1196bae50` |

## Appended 2026-11-03T05:59:14-05:00: a4 records identity established, runner v8 (not run), a5 targets (append only)

- **Master ruling on a4: BENIGN.** The cause is the gzip MTIME at `pooled_residual_model.py:256`, which is B-bound
  and unchanged.
  - **ESTABLISHED:** a4 = a3 on the decompressed payload sha256, 66 of 66.
  - The lane's decompress-and-hash of `records_a3_evidence` is accepted as disclosed.
  - Receipt `9c288c9f…` is accepted.
- **Records identity, from v8 on:** the sha256 of the decompressed payload. The raw sha256 is cross-checked with
  gzip MTIME bytes 4-8 masked. walk.csv rows: records rows compare on `payload_sha256`, other rows on `sha256`.
- **Runner v8** `row28_run_v8.py` = `7bb10f0559d48b1cfd64eba19b2bbbdf6f679e82eca9a4bb2c507985ffe9ef46`, and **sentinel
  test v6** `test_row28_s7_sentinel_v6.py` = `06aed91fa7260dc90e83efde8d84299377655293a71642e0be57b655541953e3`. Both
  are new files; v7 and v5 are unchanged. The detail is in the C3 sixth addendum: M1 byte cuts, M2 pandas
  surfaces, the identity helpers, and the confirmation (by line) that the v7 stage-end guard decompresses every
  `.gz`. Not run.
- **a5** goes into `run\s1_controls_a5` on v8, after the v8 delta review is CLEAN and the coordinator's go.
  1. Move `run\records` to `run\records_a4_evidence`. The raw and decompressed manifests go here.
  2. Run the pre-scans.
  3. Launch.
- **a5 targets, all equal to a4:**
  - C-0 19,657 / 0.0; C-0b 2 of 2; C-0c 4,125 / 0; C-b 660 / 0.0;
  - the decompressed records manifest;
  - the non-records walk.csv rows;
  - `decision_allowance` `dated_tokens` 276;
  - output guard 0;
  - `m1_summary.remaining_total` 0, with 0 remaining on each of the 66 records files.
  Any deviation STOPs.

## Appended 2026-11-03T06:07:23-05:00: count-only M1 pre-check of a4, runner v9 (not run) (append only)

- **The v8 delta review is CLEAN** (no B or M findings, 4 minors, disclosed in the C3 seventh addendum).
- **M1 pre-check (master GO), count only.**
  - **Callers** (scratch, outside the repo, run directly; light):
    - `l59_m1_precheck_v1.py` `000a30df6554793502cc5fdfba89e117e1d653d78dbe50385f9e94b732f43ff2`: its peak-memory
      read returned 0 (a ctypes signature fault), so it was rerun as v2;
    - `l59_m1_precheck_v2.py` `bde132a49a61d055fc75f96503c579e7c25d0593ff6e64c2fe1ffdbb5dfbd4a8`.
    Both import `m1_records_bytes` unchanged from `row28_run_v8.py` (`7bb10f05…`), verify that sha256 first, and
    print counts only, with each file named by market, class tag and index. Nothing was written.
  - **Result over the 66 a4 records in `run\records`:**
    - remaining 0 on 66 of 66, span_mismatch 0, pickle protocol 5, 28,716 str opcodes;
    - cuts: centre 66, generated_at 66, decision 72 (60 files at 1, 6 at 2).
  - **Cost (m-d):** peak working set 32,468,992 bytes, peak pagefile 24,129,536 bytes, 6.88 s wall in all
    (import, decompress and genops over 66 files). Well under 1 GB and 1 min.
  - `run\records` was not moved.
- **Runner v9** `row28_run_v9.py` = `bac1d678a60760071476379e42052855680e645816c769bb206e43a328f81b68`: v8 plus the
  raw gzip header scan (C3 seventh addendum).
- **Sentinel test v7** `test_row28_s7_sentinel_v7.py` =
  `dbde6bcda4180a8670f2835fecf4821da98583bb1535c4d7063dbeae2cd31335`.
- v8 and sentinel v6 are unchanged. Not run.
- **a5 runs on v9** after its review is CLEAN and the coordinator's go:
  1. Move `run\records` to `run\records_a4_evidence`, with the raw and decompressed manifests.
  2. Run the pre-scans.
  3. Launch `run\s1_controls_a5`.
- **The a5 targets** are those of the 05:59 append, plus:
  - `gz_header_allowance` `fname_own_tmp` 66 and `dated_tokens` 66;
  - `gz_header_summary.hits` 0.

## Appended 2026-11-03T06:12:02-05:00: runner v10 (v9 review m-1), a5 targets (m-3) (append only)

- **The v9 review is CLEAN** (no B or M findings). The coordinator adopted m-1 to m-3 (C3 eighth addendum).
- **Runner v10** `row28_run_v10.py` = `dc58715ca4f8834746051e3aa8c5408f115e384a63cbf512ef1940cfea82abaa`: v9 plus m-1
  (any FCOMMENT or FEXTRA on any `.gz` is a hit).
- **Sentinel test v8** `test_row28_s7_sentinel_v8.py` =
  `1807e3d488c025732867c3ef29e514512934202c79eb82aa98f236c710a6add9`.
- v9 and sentinel v7 are unchanged. Not run.
- **a5 runs on v10** after its delta review is CLEAN and the coordinator's go:
  1. Move `run\records` to `run\records_a4_evidence`, with the raw and decompressed manifests.
  2. Run the pre-scans.
  3. Launch `run\s1_controls_a5`.
- **a5 targets (m-3).** These supersede the header lines of the 06:07 append; everything else in the 05:59 list
  stands:
  - **Controls:** C-0 19,657 / 0.0; C-0b 2 of 2; C-0c 4,125 / 0; C-b 660 / 0.0.
  - **Records:** equal to a4 on the decompressed manifest (66 of 66).
  - **Walk-side guard:** output guard 0; `decision_allowance` `dated_tokens` 276.
  - **M1:** `m1_summary.remaining_total` 0, with 0 remaining on each of the 66 records files.
  - **gz header summary:** files 68 and members 68 (66 records plus 2 junction manifests), fname 66,
    fname_own_tmp 66, fcomment 0, fextra 0, hits 0. `gz_header_allowance`: fname_own_tmp 66, dated_tokens 66.
  - **walk.csv:** `compare_walk_csv(a4, a5)` returns `equal: False` BY DESIGN. a4's walk.csv was written by runner
    v7 and has no `payload_sha256` column, so its 66 records rows count as unverified (`records_unverified` 66).
    a5 is judged on two things:
    - the non-records rows: `other_equal`, with an empty `differing` list;
    - the records: equal on the decompressed manifest (`compare_records_identity`).
    An `equal: False` from `compare_walk_csv` is NOT a STOP on its own; any other deviation STOPs.

## Appended 2026-11-03T06:15:16-05:00: v10 review CLEAN, m-A / m-B, the a5 launch form and full targets (append only)

- **The v10 / sentinel v8 review is CLEAN.**
- **m-A.** The two in-place edits to the C3 seventh addendum were reverted.
  - The file up to the eighth addendum now equals CLARIFICATION_3.md at `149393482` (`aa3844d7…`) byte for byte.
  - Both corrections are carried append-only in the eighth addendum.
  - CLARIFICATION_3.md is now `8826cd273fb07f811c23a4d6aca0ab810386ae40ac36c835a421cafeae93b610`. The 06:12 append
    listed no C3 sha; the C3 at that tip was `5729eb81…`.
- **Disclosure (reviewer item 5).** The reviewer's item-5 check ran one ast-parse one-off on TEMP copies of runner v6
  and runner v10. It hashed definition segments only and did not import or execute either file.
- **a5 launch form, exact.** Launcher v6's default `-ExpectSha` is stale, so it is passed explicitly:

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s1_controls_a5 -Stage controls -TimeboxSeconds 14400 `
  -RootsPath C:\t\L59\row28\run_config\stage1_controls_v2.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v10.py `
  -ExpectSha dc58715ca4f8834746051e3aa8c5408f115e384a63cbf512ef1940cfea82abaa
```

- **a5 targets, the complete list** (this list together with the 06:12 append; any deviation STOPs):
  - **Launcher:** receipt COMPLETE, walker exit 0; log guard 0; receipt guard 0; no FLAG; junction manifest
    before = after `f93c2ad2…`.
  - **Runner and controls:**
    - status PASS;
    - C-0 19,657 / 0.0; C-0b 2 of 2; C-0c 4,125 / 0; C-b 660 / 0.0.
  - **Output guard:**
    - `files_scanned` 68, `hits_total` 0, nothing withheld;
    - `decision_allowance` `dated_tokens` 276 and `values` 144.
  - **M1:** `m1_summary` remaining_total 0 (0 on each of the 66 records files), span_mismatch_total 0, cut_total
    {centre 66, generated_at 66, decision 72}, protocols [5].
  - **gz headers:**
    - `gz_header_summary`: files 68, members 68, fname 66, fname_own_tmp 66, fcomment 0, fextra 0, hits 0;
    - `gz_header_allowance`: fname_own_tmp 66, dated_tokens 66.
  - **Records:** equal to a4 on the decompressed manifest, 66 of 66.
  - **walk.csv:** `compare_walk_csv(a4, a5)` gives records_unverified exactly 66, records_equal_on_payload 0,
    other_equal 2 (a4's non-records rows: its two junction manifests) and differing []. Its `equal: False` is by
    design.

## Appended 2026-11-03T06:18:19-05:00: a4 records moved to evidence, raw and payload manifests (append only)

- **Quiesce before the move.** `data\` held exactly 4 junctions; no wrapper, runner, launcher or pytest process was running.
- **Move.** `runecords` was moved to `runecords_a4_evidence` at 2026-11-03T06:16:35-05:00. 66 files moved;
  `runecords` is now absent.
- **Manifests.** Below are the raw sha256 and the decompressed-payload sha256 for each file, with names masked as before.
  - The raw column equals the a4 column of the 05:46 table, 66 of 66.
  - The payload column is the a5 comparison baseline: a5 records must equal it, 66 of 66.

| File (`records_<market>_2026-<MM-DD>.pkl.gz`) | Size | raw sha256 | decompressed-payload sha256 |
| --- | --- | --- | --- |
| `atlanta` `01-08` | 140377 | `164611fd0edf6459d4731f46126e8fd17d7acd197b456d79fe02efd68e74c68c` | `5e2408a1cb13f65735eab1ed3e56792048f5fa665872a143df242e15aae5e2c0` |
| `atlanta` `08-08` | 222250 | `ab16f87e7a863268a7b06b57aa0d3bf0b7cfe6753cc52cfaab70df129f36fec1` | `4ebb5a8f40086776cda8ef6516e0995b6386264aebf611ef5f8e29e34f0e5114` |
| `atlanta` `08-23` | 219394 | `549bd782fd4707a7cb344ca9aaae23d4f2b013dcfe1da0a5bef48ab165fdc47c` | `c900a5f1fa2efe32731a623cb4e4e2597d79934d705359ec99b9dcba9a84ebe7` |
| `atlanta` `09-07` | 216409 | `eb80390939b3a1d143c83e747a862c0dfd08af6ea2672748f58d29e15ac88a80` | `45ac9b0e2662acf5cfbef9414983850546e97478fb6a9b954d6cb4c5d99b1f2b` |
| `atlanta` `09-22` | 222892 | `2bc17558b8f2b12fa55cf0f4db5c4e501825904affdc351bc2e1c09fad9641cb` | `5854d7633aa3df53dbc44637c31d406629f073da8eec7bce504f26c92fa99db7` |
| `atlanta` `12-09` | 231395 | `f0ddd005d0023d54bd30d45e58e54610140980416589dc7367e5e37ad0ebddbb` | `a3db72a460f0f240a69cde2f0f7c1f1d86f5c52dde5cfd75e47b246c9adb0d9b` |
| `austin` `01-08` | 140482 | `4ec9a9acb3688ad8631adff6df438474fa2f46ab7a1ac18652912c2a58678697` | `751879b77c24b745f69a40cc3790876b814e55b12fa8b68c6cb02bd9f2c101c3` |
| `austin` `08-08` | 214164 | `b18944dc4e0cd179aa1a77f0733ef9ecfe5ce5c9a809ba1ebf98efc50938eca8` | `795d2d812235c7ad105ba4552d9c48e88ce9be1786b4e3a2a0ca5a0f4bf24e64` |
| `austin` `08-23` | 219352 | `d5208482e4310add24b42f972ad05db73a21ea6803341f82d2f9d5ffe56344a9` | `e3f1e885154349746790bbced0557ec341b318d064c66a02b9285d7928b78b6a` |
| `austin` `09-07` | 216983 | `9d107e41a713a3f1b3306a73919a2aeca810b00ac94ee71eaed044df40a71a99` | `56cc8c8bcbaa4cde4d08e245c9807e5d1c700dca606d270bbb60762880f7914e` |
| `austin` `09-22` | 216446 | `0ffe40ec9ab0abb7a93c7aec93cbb1d42a0087cb9bdbaef1aed3b9491d83b863` | `04da66417cac367ca3a7b6bb72b758f4faa867f4a0e4be6f5d0c08ab83235fd3` |
| `austin` `12-09` | 233397 | `d19ae554c5845750dff57869343a43252780d5bb9a4bcaa7d728a4b4d8d87fce` | `27bc80c3ac72af0bed0fe43bd0535b7ffb3359e2261f2ca945d9023872c59308` |
| `chicago` `01-08` | 140743 | `d0d2ec36d6a604b7265876d6f62ae52e43d2eb7b60c3b940985f4241446b0ef7` | `2ef1cbc9f0493efefa9cc1ba944e1b323efc92bdf9db0dd9e87376f2381f930c` |
| `chicago` `08-08` | 224626 | `de1a4ebdae419f915285a6633be101cda4c8002293bc46724c1ba9cea367deb9` | `6757e578a84118bc5a8d4bd42a989b39543822f2d09db627bd5a50914694a5ba` |
| `chicago` `08-23` | 225775 | `b2e5123e20101374f3fb2da2779b991b06ed1fdf8eb206cf4cbee6ea32ff5ae9` | `de42cfab4a3db78efd4565f01da6a528d6e3580fd91f3d5adc678fad18db7664` |
| `chicago` `09-07` | 225567 | `1c6d8f8b0f77ad0f0ee85a608a971f44fff13392252843fa9a77b84f2086bd85` | `c4e40fbc09a67d20a7dc03ab76811d04887d34995f7df3d1cdc4e5b33ef5ed77` |
| `chicago` `09-22` | 225610 | `d22bd08b689622b1952a000a5d326dff515749cef641427a03882c6a5cbb8f68` | `746ab9cb58f293023c99558d940cc52fd937e37323b5d2b34753aa446a0fbdb8` |
| `chicago` `12-09` | 231724 | `99cb67270243fdeed9a9b139b9c5df9f6c4e819b6387292da1b08868547087b3` | `fa1394489366eb4d5135aa8b16b75a06d9680381edeb369d57c5d437d3607e8f` |
| `dallas` `01-08` | 141932 | `164e4bf5faf5a47e5f622ac582b5d68003c4679ac1f16fdac84910b5c0fcca55` | `eba2adafdec6179c2e529f4e57276fc5d9169c40c10823adb50eb84cf1bec462` |
| `dallas` `08-08` | 216161 | `003ee54fd67dfd8dc105b5607dcecead33370a497dbddfba539868ff1a0d60c4` | `750ece1c8d19787876c48662a51f86fca07b1d0a51912ef801461c017adb2612` |
| `dallas` `08-23` | 220558 | `69f6c41dc0b4bebe4cfd7521a7e376a772ac1d6ec79762ffa09c18d3b89b412e` | `25f83ef1e01b7435145c3a719c0f8f9e749684fbde8279cd57cf01a343acfdc2` |
| `dallas` `09-07` | 218378 | `91ad9b8b84e2c5309ad4095e078838114dcc52e968a4e5d0d5fc1ce6cf27df11` | `f0ec5b327df20a3a489f281c528ef27fdcddcf4c855ea30ce6ae4670b640dc3f` |
| `dallas` `09-22` | 220450 | `cdcf12eaa7909ad2d9f4ccf33c384ad4159a73bcc61a3bea021a1195551b348f` | `2aa42caf6ed6b3940de6dc855e7cf7012b220d5834bbde0722f81dfec4253564` |
| `dallas` `12-09` | 233736 | `dbff0c79446752d8e65a6ca188109fc1e5e9bf995854d4d64c0aaf0b5c2df6e4` | `79fb3e97114132c8b324717cb0ac954789ea61c81bc578d26caffff5c638ae12` |
| `denver` `01-08` | 135819 | `5ddb0c0ea060d1b762304a9895991b706938ff72989edefbad58ab771a586f31` | `7d29c4cc72d92300dbbef584da9f10e473d4424d3b5c33e112b15f625df2457c` |
| `denver` `08-08` | 225928 | `eaaff24324340651078f74bb8fa182f6d10ecd75d406acd51ef702bf08b0f5d4` | `74fa7bcd9827b4539b4a552c6a9b4e1ce7c359ec999f1a0cfbd7b78b630bfb51` |
| `denver` `08-23` | 220772 | `a36b59bc2aa13034e8a50c83d1132fdab11b69e69936d06e8de8558be68bd4a9` | `6d8da8cf7de1ca6437d61261fc41c86ac87243cbad7826953a30a3335a1fcbe2` |
| `denver` `09-07` | 207926 | `9ab2ea29bbe33ff664a7e48aed95f0220d26c1126216379dfb16d728f3f065c8` | `bbf45cd9141b1e497fe73fce9e06caccc57b48a731baa0e4315dac48fff30ab3` |
| `denver` `09-22` | 221630 | `74c100ad4fd14e8498addc1bccf5e93a6493b690f96203c59820e4007465f587` | `df5befb24ccfc3260a67b581b5a93488fc50e6159cb731c29842d1b9f44a1d89` |
| `denver` `12-09` | 225562 | `0642651dc7dcc382288fecab2daf0e6751d0c5585e605525c7ea3b38b9f2a3d9` | `4dca00c8af8758dd2e4443e780113a21e93321120eff8973552d372a8d530e9d` |
| `houston` `01-08` | 143411 | `0ed04798892abec38ae02414ec535b7500e87fb9c79df324eb65b8020f16565e` | `f00737c7efcfc993fc3d9d5cee76abd189b7d210d4f4174c3991379d4183bdc5` |
| `houston` `08-08` | 215191 | `f1c105903f5798dd02a611c0c0c927e2a98eb4ef97279975027967cff130281d` | `2e7a0f4f24bbf2a0ebfc878493cc5c738bfadd6a805fb99f8ec3b046b0a8b211` |
| `houston` `08-23` | 218969 | `fb6ff75e388a77c5ee53986df3ae262700289fcd2a223bcbcd90af55fab79a09` | `0c7d408f4614b8d657da345667d805732d780a1c94001e759d3dd470ceee40a6` |
| `houston` `09-07` | 217622 | `6bb6c8002fc3a16c52f574995fcbc0fa545b91356a250c165ced89f52d31481e` | `97f50de01c553b1eb0d927a513b16326e592d9b28269799e827c5ee0ccbc1678` |
| `houston` `09-22` | 218086 | `f267c863c4f08d3d973ba00d1baa0e7d3afe17f8058d480e9bab9cae9582627f` | `91c58a4a1fa8a8136be421c27a3091081f8468de54fa5988e0b12afdd80b86b1` |
| `houston` `12-09` | 231673 | `7e405ecce4a64a44ab8b69a69b937624ccf740cce641f4842199857b07bbbfa9` | `c08e63e1ec88ae0419c4c8303bed413003610cd35191b3d3827abc994004805b` |
| `los-angeles` `01-08` | 135195 | `05629aab893698dcee4c63a12411715c14110641d0f7fb178c88cc442c4f7352` | `9893614dba050433744653c53fab89def6332e04b95629fe8d40ea8143a05480` |
| `los-angeles` `08-08` | 208092 | `b29be56e7d710822e2e651f6718d79de4bbdc7eda44965f2a08a2d4f88e9b5b8` | `23009c3bec230f3a295a2ce63769435d7ab6e25f09046324f7f8a2e27668a7be` |
| `los-angeles` `08-23` | 211511 | `a92678ea7b0259910d63575a8fd9bc390216417c9fee47b42c6dce1c83948af8` | `ab93adf2487b1dd6cb00f084492dd9e90971165d818b636524eeb3835e8d389e` |
| `los-angeles` `09-07` | 209733 | `c8affe5d874955c81b2d28b9c52ab4870abd10ccb398c4ef189ad06b65041854` | `d639c639cb558221b7a26ec18b6dff21ff887843105062f69e2d29a91d22262a` |
| `los-angeles` `09-22` | 213927 | `6e7e2d6bb4076462fbe1d4d4a47ead0c0652d46f06f1a2c700de4dceacd61aa7` | `b9e81acb9c1517ce2b2963aba59af0c428f604ea99ce70c4ccdb3bbd98570a69` |
| `los-angeles` `12-09` | 215475 | `4387b550bdc344a50a7794678e4d51f8e8ee7e191ac3fd54d70ae9993069e285` | `c98c7fdeed127fd93e9feb83e55afa6550b039bc7fd6223f2403c00f1761e363` |
| `miami` `01-08` | 135579 | `6f232badbe99d71fcdf3e88b9bb40d41ced8258ce66e8b866a06b29e517f58c0` | `b4e961ef86832412a8ce38afe1dcee31b0ea34eaca52d108871f4d276b490fde` |
| `miami` `08-08` | 208305 | `5d8d247389f8e24bce538b248029952690c5bc07bc01609c36d7f8923c5a33ec` | `c7c2ef9777741d26330a64d76be3ff33b5b5aa2b7265539568a2de0d4046a823` |
| `miami` `08-23` | 209860 | `a22d1bb5fe50fd0361b770fb62521b60239237ae08a8b474bcfd5123d2d9d5de` | `280056f7ceb6159fa224c182889c7454fa131e3c231621b1fd054034d486dd8e` |
| `miami` `09-07` | 208060 | `4070c1e924442bc90496f0cd900191e95b082f775eca6b114af81f82480aeae1` | `e0fd586a592aee23a4f0087233b110b60f6fce303e08c540abf1e7ef99be9930` |
| `miami` `09-22` | 214530 | `c9bb3d6bf97eeaeb4174b13f78a0a25290442a7499c81584ba51cc7fdf5ab8f0` | `dcb1e6759285895c02457db35ce406d72ffbbb19e82e5dc33a40a55de4996800` |
| `miami` `12-09` | 215437 | `797c6ad56374076a261ca49cefc2870be9d5cd3195649573ea5b713e37dfdedd` | `d4aa1ae7be24dee5ed74a8e47fcf9255774bc617fb84721758adc7e95fa1d877` |
| `nyc` `01-08` | 137855 | `154ee1fcc4a95068ba784098421e4bb89eaf8efaa19a6d48e5ceea8f43b6bf42` | `49479ae1c0c2d04ad1189963d646a00b4fcc7880ceb41dbf97b3f7939fef5dd3` |
| `nyc` `08-08` | 224704 | `4ea37afb677cc60569f4e58c6d5c79e9538e1c701fa811c5e9cb3eb0724d36ba` | `26188058ff9461efde6149d139224ad4b074385e3a6ad66788fa4513f154d9d4` |
| `nyc` `08-23` | 225720 | `70832be10afa98c1e8c25cc0ece1c421497884eb963182756929185c430455b0` | `df310baf127b4adafd9ebad76ab3259499bd4cc5a7031a137bed1d7f83ae4a9f` |
| `nyc` `09-07` | 222216 | `d067798a0e75d31b0a6759378c64458943fbed24d24a6df58fe09c17299eda1e` | `4c3aa7e4b650481602632676cd988a3a8202f9a9162e8164b91fc6ce14594079` |
| `nyc` `09-22` | 225307 | `ddea9f7f02b62e738343c96de056585dd4c536e527b0084773de9c646972f8a4` | `aeacfc2ff483eb4401cd09525224ca37ff8198f51dc6088872057c800e119e5f` |
| `nyc` `12-09` | 230199 | `57d9fefaaa736ec728b7db0afb05276efcf93305461348bf178117c462a30b6c` | `cd3fff58d23db46e4466bd9d01940165cb13e840b15e292d693bd7cd83c0d2c8` |
| `san-francisco` `01-08` | 135132 | `7eead4fe27892fe60e8afcdf55bb1a3f1367854702d577262002e7ec9b66db0d` | `f5f067ed2bbd579f3d3505a26231e1bd73601908d7366a0002437a6b7708575f` |
| `san-francisco` `08-08` | 215875 | `9226d9475bae28f359300948e72bc13d5874cf028d22d181eaca300afe295780` | `38e12f3b83868a389a9bc643f02442b192fdaf42a735f0fa636da7244bd0f3bc` |
| `san-francisco` `08-23` | 215647 | `0e3ef5b2851cc48f511507a84d7dce5d5c9d109ddea1f76715ce7332b712322d` | `b469729c96058b13de578ebf078684ce38f3f5effc9d569ce4bf0a1c4889ac8f` |
| `san-francisco` `09-07` | 214429 | `808dd14d2747300501ee38b9eb36897acf9e4a08b26da963b6fc3b47ee72df3d` | `c44012d1e1619151b77bdfe6466e968e65e6db66e78e3e0ff94fd0495bf33208` |
| `san-francisco` `09-22` | 221236 | `852bb9402214f8f992e1d281526ade60e58f3b36f5fdda7e66595ea98e818d44` | `934469f43b8f7224bfde5c7afa2e8c3131af57e8c1c522dc1449dd7a91eb1b6c` |
| `san-francisco` `12-09` | 219369 | `dacbff24af00f7ba6d53d844c543e8c84e249950c5235e17a05b7804a182fbad` | `bdbfb13ca98d93e47183d626e041e5a538bd6c0d61d045b9f198428d9b5c6561` |
| `seattle` `01-08` | 137082 | `bbcbc6768fc7f8008caf77e3b8c4d3a40cc03bacea3683648b48ca93bd24982f` | `ac43952bad03c1c83c0ecfb01aff2c2b43853068068e9063f8bf65eec48e5f74` |
| `seattle` `08-08` | 225967 | `8db1a89a78b5e8fea84c5ab324bf3f5c0e4947b5f67eff2dc51401948d513ba2` | `da398e6c630292e60bb13732cf8b1bf6c11ff5d2d00a8e1b8bc63e36430df3b2` |
| `seattle` `08-23` | 226906 | `e83f72c27f40fc8c7dd16b43bb990a0faed78653ccb4aeb50ba187cbf0de4f11` | `91a56a3c15c73c4070ef865d65be9a4fe4b2a0b77796f21610f11ee896f7578e` |
| `seattle` `09-07` | 220539 | `2b572f636848016ca0ae0dddbeb38e6595b385116d04dbf5b6cf35f6ff526b0d` | `54fcb56c39e2595ce2fa7e453fe7897de4660fe522a832226878f14a9ce72350` |
| `seattle` `09-22` | 226880 | `d8ecf3d34ce3f1653da8e81d31861203ab28f1323a41d38aa46f0461a1f0c1b1` | `ad19cea1d1127852cd776edbf2d77a5b636c55d9bbf6331f84959aed9fc8187f` |
| `seattle` `12-09` | 223491 | `2859d1c7d040b2529723ce04ff83ad0ff530a8813c5fe7e70ce0f8b1196bae50` | `5fc6271acd0be6c7c6669732944793209d0a530810306818f0816e7675c2e5ef` |

## Appended 2026-11-03T06:19:30-05:00: a5 pre-launch scans and sentinel v8 (append only)

- **Dated-string scan (ISO >= 2026-01-01).** 0 hits in each of the following:
  - the config's contents;
  - the config's name and path (`stage1_controls_v2.json`);
  - the OutDir name and path (`s1_controls_a5`);
  - the stage (`controls`);
  - the log directory (`ctl_a5_logs`);
  - the sentinel basetemp path (`sentinel_bt8`).
- **Forbidden roots.** Neither `cap_counts_v2.json` nor `r4_deciding_dates_receipt.json` is referenced by the config or
  passed as a root.
- **Pinned input shas, verified:**
  - config `66e4b46e…`;
  - launcher v6 `8a2f8759…`;
  - runner v10 `dc58715c…`;
  - sentinel v8 `1807e3d4…`.
- **State before launch.** OutDir `s1_controls_a5` is absent and `run\records` is absent. `data\` holds exactly 4
  junctions; no wrapper is running.
- **Sentinel v8.** Run through `workstation_heavy.ps1 -Kind pytest -Queue` with `PYTHONDONTWRITEBYTECODE=1` and
  `--basetemp C:\t\L59\row28\sentinel_bt8`, from 06:19:03 to 06:19:05: **34 passed**, exit 0.
  - The basetemp was deleted afterwards, and no new bytecode was written.

## Appended 2026-11-03T06:20:24-05:00: a5 STOP, runner HALT on an extra data\ entry (append only)

- **Result.** a5 was launched at 06:19:31 with the exact form. The receipt is PARTIAL: walker exit 10, runner status
  HALT, halt_scope run.
  - The runner refused before reading anything. Its reason: the worktree `data\` held 5 entries, not the 4 approved
    junctions.
  - Every output guard reads 0, and the junction manifest is unchanged: before = after `f93c2ad2…`.
  - The receipt guard is 0 and the log guard is 0. Peak job memory was 132,591,616 bytes.
- **Cause.** The 5th entry is a plain directory, `data\logs`, created at 06:19:04 by the sentinel's
  `workstation_heavy.ps1 -Queue -RepoRoot C:\wt\L59row28` run. It holds the wrapper's queue and slot-lock state:
  2 files, names only, not opened.
  - The 06:18 junction check came before the sentinel, so the "4 junctions" line in the 06:19:30 append was stale
    at launch.
- **State.**
  - `data\logs` is left in place pending a ruling.
  - `run\s1_controls_a5` exists with its HALT outputs, so launcher v6 will refuse it as an OutDir.
  - `run\records` is still absent; a5 wrote no records.

## Appended 2026-11-03T06:31:03-05:00: data\logs moved, a6 (the a5-equivalent attempt) full PASS (append only)

- **Master's ruling (relayed).** Master gave GO on three items:
  - (1) move `data\logs` out of the worktree;
  - (2) keep `s1_controls_a5` untouched as HALT evidence (receipt `9b418ad8…`) and relaunch with the same exact
    command into `run\s1_controls_a6` against the a5 targets;
  - (3) no sentinel re-run.
- **a6 counts as the a5-equivalent attempt.** a5 halted at the run-scope precondition, before any stage computed
  anything.
- **Move.** First, the shas of the 2 wrapper-state files were recorded without opening them:
  - `heavy_workload.slot2.lock`, 608 bytes, `7d5fa0121dd7fb006f6ee6c0d6b5d1556abf4b8efa86f8e88a8cba96df872d15`;
  - `heavy_workload_queue.jsonl`, 1066 bytes, `23c2a228507f2d213812fbfe304df281a45095482d25c310c954b04e13093a67`.
  - Then `data\logs` was moved to `C:\t\L59\row28\sentinel_wrapper_logs\a5\logs` at 2026-11-03T06:22:28.10-05:00.
- **Pre-launch checks, in the same command block as the launch.** Nothing ran between the move and the launch.
  - `data\` held 4 entries, all junctions: marine_water_contrast, reanalysis, training, wunderground.
  - The dated scan of the OutDir, stage and log dir found 0 hits.
  - No wrapper, runner or pytest process was running, and `s1_controls_a6` was absent.
  - From now on, any wrapper run uses a `-RepoRoot` outside the worktree.
- **a6 run.** Launched at 06:22:28 with the exact form, the OutDir being `s1_controls_a6` (logs in `ctl_a6_logs`).
  - The walker ran from 20261103T062228.8103963-05:00 to 20261103T063000.9314598-05:00.
  - Output shas: receipt `13f4d96a9b5354959448cbd887157ac6d1aecdb3a3f5c0fff6dd4f423bb67d3c`, walk.csv `42d8d0e0…`,
    walk.json `46c621f7…`, walker.stdout `941b9c6c…`.

| Target | a6 result |
| --- | --- |
| Launcher | COMPLETE, walker exit 0; log guard 0; receipt guard 0 (full receipt written); no FLAG |
| Junction manifest | before = after `f93c2ad2…`; manifest_changed False |
| Runner | PASS |
| C-0 | 19,657 / 0.0 (Brier and log), identical keys |
| C-0b | 2 of 2 |
| C-0c | 4,125 / 0 mismatched |
| C-b | 660 / 0.0 |
| Output guard | files_scanned 68, hits_total 0, nothing withheld; decision_allowance dated_tokens 276, values 144 |
| m1_summary | files 66; remaining_total 0 (0 on each of 66); span_mismatch_total 0; cut_total {centre 66, generated_at 66, decision 72}; protocols [5] |
| gz_header_summary | files 68, members 68, fname 66, fname_own_tmp 66, fcomment 0, fextra 0, hits 0 |
| gz_header_allowance | fname_own_tmp 66, dated_tokens 66 |
| Records vs a4 | payload_equal 66 of 66 vs the 06:18 manifest; `compare_records_identity(a4_evidence, a6)`: payload_equal 66, raw_mtime_masked_equal 66, raw_equal 0, equal True, differing [] |
| walk.csv | `compare_walk_csv(a4, a6)`: rows 68 / 68, records_unverified 66, records_equal_on_payload 0, other_equal 2, differing [] (equal False by design) |
| Peak memory | job 2,212,745,216 bytes |

- **Verdict: full PASS on every a5 target.** STOP; the build waits for master's go.

## Appended 2026-11-03T06:33:11-05:00: build (stage 2) GO, config, pre-launch checks and exact command (append only)

- **GO (relayed).** a6 is accepted as a full PASS. GO for the build stage on runner v10 with launcher v6, under the
  40% rule: peak memory at most 12.8 GB, i.e. 40% of 32 GB; above that the run STOPs. STOP after the build either
  way. Integrity, labels, look and score each wait for a separate go.
- **Config.** `C:\t\L59\row28\run_config\stage2_build_v1.json`, sha256
  `31a751a468d0c8a333369acb6ab7046cd662988c9bf5f81716607bb239125197`. It is new; no existing config was edited.
  It differs from `stage1_controls_v2.json` (`66e4b46e…`) only in `stage: build` and in `prev`:
  `prev.controls = {path: C:\t\L59\row28\run\s1_controls_a6\walk.json, sha256: 46c621f7…}`.
- **Pre-launch dated scan (ISO >= 2026-01-01).** 0 hits in each of the following:
  - the config's contents, name and path;
  - the OutDir name and path (`s2_build`);
  - the stage (`build`);
  - the log dir (`ctl_s2_logs`).
  - Neither `cap_counts_v2.json` nor `r4_deciding_dates_receipt.json` is referenced or passed as a root.
- **verify_prev binding to a6, checked read-only before launch:**
  - a6's walk.json sha equals the config value; report status PASS;
  - receipt `13f4d96a…` COMPLETE, output-guard hits 0, no receipt guard hits, no FLAG;
  - receipt stage `controls`, `walker_sha256` = report `runner_sha256` = `dc58715c…`.
- **Records.** `run\records` holds 66 files, and their raw shas equal a6's `records_sha256` (66 of 66), as
  `stage_build` requires.
- **Pinned input shas:** launcher v6 `8a2f8759…` and runner v10 `dc58715c…`. OutDir `s2_build` is absent.
- **Launch-block checks.** The data\ junction check (exactly the 4 junctions, nothing else) and the process check run
  in the same command block, immediately before the launch. Nothing runs between that check and the launch. Logs go
  to `C:\t\L59\row28\ctl_s2_logs`.
- **Exact command:**

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s2_build -Stage build -TimeboxSeconds 21600 `
  -RootsPath C:\t\L59\row28\run_config\stage2_build_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v10.py `
  -ExpectSha dc58715ca4f8834746051e3aa8c5408f115e384a63cbf512ef1940cfea82abaa
```

## Appended 2026-11-03T07:13:59-05:00: build (stage 2) STOP, runner output-guard HALT (append only, counts and classes only)

- **Run.** Launched at 06:33:23 with the exact 06:33 form. In the same block immediately before launch, `data\` held
  exactly the 4 junctions and nothing else, and no wrapper was running.
- **Receipt.** PARTIAL, `8ff0d20bfc12f58e6c8c272f7e449a1a8f812115045a1fbb2faa200d38f11977`.
  - Walker exit 10; launcher log guard 0; receipt guard 0; no FLAG.
  - Walker time 20261103T063324.2552317-05:00 to 20261103T071315.0990749-05:00 (39 min 51 s).
  - Peak job memory 4,756,045,824 bytes; the 40% line (12.8 GB) was never crossed.
- **Runner.** status HALT, halt_scope run, reason class "output guard".
  - Output guard result HIT: files_scanned 3,206, hits_total 11, all in 1 file, class Y26_PRE0527 (11). The file
    is `nbm_market_new\nbm_pit_corpus_rows.jsonl`, the L9 NBM corpus tool's output.
  - One further write was refused and not written: 300 disallowed date strings, all class Y26_PRE0527.
  - `writes_withheld` [], log writes withheld 0 / 0.
  - decision_allowance: dated_tokens 828, values 432.
- **M1 and gz headers (the records part passed).**
  - m1_summary: files 198, remaining_total 0, span_mismatch_total 0, cut_total {centre 198, generated_at 198,
    decision 216}, protocols [5].
  - gz_header_summary: files 202, members 202, fname 198, fname_own_tmp 198, fcomment 0, fextra 0, hits 0.
  - gz_header_allowance: 198 / 198.
- **Junction manifest.** before = after (payload `9dff281c…`), manifest_changed False.
- **State, left as is.**
  - `run\records` now holds 264 files: a6's 66 plus 198 extracted by build.
  - `run\s2_build` holds the HALT outputs.
  - No hit content was opened or logged. The build report has no `records_sha256`, because the HALT came after
    extraction and before the report merge.
- **STOP.** Waiting for a ruling.

## Appended 2026-11-03T07:19:11-05:00: d3 diagnostic, build-1 evidence moves, rebuild targets (append only)

- **Master's ruling (relayed).** The build HALT is a guard-scope gap. 2026-01-01..05-26 rows are in scope as
  descriptive rows for all arms; deciding stays 2021-25; sealed starts at 05-27. The build config is unchanged
  (`31a751a4…`).
- **d3 script.** `scripts/row28_guard_diag_v3.py`, sha256
  `5606a287be3c6261a7b024155cc3d2d7d2ebc4e69e49bb5a2f5fac5f02411054`, committed in `420cf7bc2` before it ran.
  - Method: d1's. It imports runner v10 (sha-checked; main() not run) and uses the runner's own load_context,
    set_guard_centres, guard_file and _walk. It reports counts and class tags only, and reads exactly one file in
    place: the build-1 hit file.
- **d3 run.** Under launcher v6 (`-Stage controls` as the label, timebox 3,600 s) into `run\d3_guard_diag`.
  - Before the launch, in the same block: the dated scan found 0, `data\` held exactly the 4 junctions, and no
    wrapper was running.
  - Receipt `5c220e6afdd4545784f94d15eeb57f13530633af9782af302744eef32ec95d12`: COMPLETE, exit 0, log guard 0,
    receipt guard 0.
  - Walker time 20261103T071737.7847330-05:00 to 20261103T071740.6665642-05:00 (3 s). Peak job memory 767,741,952
    bytes.
  - walk.json `0f6dde46…` and walk.csv `a9ad280b…`, each with 0 dated strings.
- **d3 result.** RECONCILED: the runner's guard_file 11 = the runner's per-row _walk 11 = 11 attributed tokens = 11
  expected. 12,672 rows were scanned; 11 rows have hits.

| File | Key path | Field kind | Token format | Literal class | Market-local class | Count |
| --- | --- | --- | --- | --- | --- | --- |
| `nbm_market_new/nbm_pit_corpus_rows.jsonl` | `valid_time_utc` | row-date field | ISO-with-offset | Y26_PRE0527 | PRE2026 | 11 |

- **Fields and buckets.**
  - Row-date fields by name: target_date, date, utc_date, valid_time_utc, issued_at. The object-instant field
    (last_modified) is listed separately; it has 0 hits.
  - Month bucket min = max = Y26-M01.
  - At or after 2026-05-27: literal 0, market-local 0.
- **The refused write (300 tokens, Y26_PRE0527): attributed from the code, not measured.**
  - In `stage_build`, the first Writer call after `frame_inputs.pkl.gz` (on disk) is
    `w.jsonl("pool_nbm_rows.jsonl", nbm_pool)` (`row28_run_v10.py:2181`). It is not on disk, and `pool_iem` (written
    before it, outside the Writer) is on disk. So the refused output is `pool_nbm_rows.jsonl`.
  - Its producer is `spc.nbm_pool_rows` (`station_pool_corpus_d4947cfe.py:146-171`). Its rows have the L9 schema:
    the same `valid_time_utc`, `issued_at`, `target_date` and `last_modified` keys as
    `ols_floor_ladder._nbm_corpus_command` (`ols_floor_ladder.py:163-199`).
  - It reads c07, addon, the full gap blocks file and the L48 pool blocks: about 2.0 GB, parsed for 300 stations.
  - The pool-row target_date check (2179-2180, Halt after 2025) passed before the write.
  - 300 = the 300 pool stations, one token each, which is consistent with the market finding (one block day whose
    `valid_time_utc` is literally 2026-01). That consistency is an inference; it is not measured.
  - **Not reproduced.** Isolating the producer is not light (over 1 min and over 1 GB on about 2 GB of input), so
    d3 does not force it.
- **Evidence moves (c), done after d3, 07:18:13 to 07:18:18; no process was running.**
  - The 198 build-extracted records went from `run\records` to `run\records_build1_evidence`. Raw and payload
    manifests are below; they were re-verified equal after the move.
  - `run\s2_build` went to `run\s2_build_halt1_evidence` with a sha-only manifest of all 3,013 files. 13 top-level
    files are listed below. The 3,000 `pool_iem` CSVs (1,781,377,476 bytes, station paths only) are listed in
    `s2_build_halt1_evidence_manifest.md`, sha256 `ac761541a7f3b8420ca172a7d45eef50d9b27b9f487e9046b260d828e8fa0e2f`,
    committed with this append. The manifest was re-verified equal after the move.
  - `run\records` now holds exactly a6's 66 names, raw-equal 66 of 66 to a6's `records_sha256`, so verify_prev
    still binds to a6. `run\s2_build` is absent.
- **Rebuild targets** (stated before any rebuild; any difference is a FLAG and a STOP):
  - **M1:** files 198, remaining_total 0, span_mismatch_total 0, cut_total {centre 198, generated_at 198,
    decision 216}, protocols [5].
  - **gz headers:** files 202, members 202, fname 198, fname_own_tmp 198, fcomment 0, fextra 0, hits 0; allowance
    198 / 198.
  - **Decision allowance:** dated_tokens 828, values 432.
  - **Records identity:** the 198 build-extracted records equal `records_build1_evidence` on decompressed payload,
    198 of 198.
  - **Guard:** hits_total 0, with the new scoped allowance counted. Expected: 11 at
    `nbm_market_new/nbm_pit_corpus_rows.jsonl` `valid_time_utc`, plus the `pool_nbm_rows.jsonl` count, which is
    unmeasured (300 refused in build 1).
  - **Launcher:** COMPLETE, log guard 0, receipt guard 0, no FLAG; junction manifest before = after `f93c2ad2…`;
    peak memory at most 12.8 GB.
- **Status of (b).** d3 measured only row-date fields, all Y26_PRE0527, in the market NBM corpus output. The refused
  pool output is attributed from the code but not measured. Runner v11 is held until the coordinator rules on
  whether the code attribution satisfies the (b) condition for `pool_nbm_rows.jsonl`.

### Records moved to `run\records_build1_evidence` (198)

| File (`records_<market>_2026-<MM-DD>.pkl.gz`) | Size | raw sha256 | decompressed-payload sha256 |
| --- | --- | --- | --- |
| `atlanta` `01-23` | 140819 | `60b6531b2b75ad25a35b203551d3fd09a84d23d9700528ed08577ef1f7e946e2` | `0e2756d7ca436b0fdb5f88f306c9bf3eccb06af900543cb8f055524cf1dd7b9d` |
| `atlanta` `02-07` | 195281 | `dd865aff371c227148c2c2af4eaa09327c61f4d976fe84e2707dc7bba5ff2ebb` | `7b3225b1ee31c8b143a5271594638ca6c6e13a0062bdf4da9b998e981850a9d8` |
| `atlanta` `02-22` | 188618 | `c02b1b9a7cd314d6baabe137d50f6b60e079421f0d8daf1b4f80a7986dc8a991` | `76758c31248e9f571561fb65a99e265f0d7dd59a1e11d47c9227a15da76e427e` |
| `atlanta` `03-09` | 183226 | `7853c9ba276049d3ef86e91888914abc9ecbeb48593bccab90d623ab0d8f7894` | `81c639fdd07a5b68f4a4c10c9c0d2109a395b175dd4414b36a70f7c9fc770747` |
| `atlanta` `03-24` | 194312 | `af986cecf02c3d3112caa51b02699e7c4c2c738a9b4e9216688e834e408580c6` | `694d5fd924740076502294447de956d7bf972a220c3249c3878476b297b8c56f` |
| `atlanta` `04-08` | 233327 | `407ea1ca959a1d30ac2418efa22005678446da9e5527a265ed5324e1fd2182f3` | `a3cff1171af4f0b862419cd25e30b4cc4a15e06f363e851d2166b438061c2cb6` |
| `atlanta` `04-23` | 229309 | `db4cd4230a9e27cd033da2a9d5020d31a58e899b5cadedac1087e932d69505d9` | `c2f977adc027a298c2a5bde1058ae5dcd02d0c1af162d1ed65699793dc188ade` |
| `atlanta` `05-08` | 232853 | `f6d89e61477e235aa32dab7bbc297e5380c5e7b133443021f149aec372ec44d4` | `ddd5fce15e1b34d2e7f7384963b90b20195533c84a023e3cc4f108144687a5e7` |
| `atlanta` `05-23` | 227558 | `a785943804ed97788c00765791b4be83065c2ccd2b234f0a846fee14731e284c` | `092b7507379c51aab2612ed2e42e1f63812d8272a7b97f3b4ba471af24e33981` |
| `atlanta` `06-07` | 225203 | `271ac4a48fcf1401eaaf85c4db2afddb1a3e0de5e94365043d92689c4347fdf4` | `b2229886d9ae1d0c37a33b42eb95967da8008e9969a440dd99c5c5f8f607b121` |
| `atlanta` `06-22` | 223231 | `71168f7cc099caa4bf74c393fce532289492c1ce40ca357940b7668439d27caa` | `10368411e3802d78a4ae50b58d686b8649a1aaf56f6f632f83c9b476ff4e4d41` |
| `atlanta` `07-07` | 220938 | `6ed147e61940388b7a4fd19b6978416c5f6f6f2c7d2c3149b0afbc150e3e09dd` | `3fb908d3cbad44727ee8ad952bf8927d466c38cc4906b3bd3241430398eba0e6` |
| `atlanta` `07-22` | 219288 | `30d8fb4cbb13198682de6e08eadfb62dff42c62a1cc72ac38e10cfef3647a740` | `829aa8506353e062f8dbb06ff7f986f45531b3c848835b149b555ce85cba65dc` |
| `atlanta` `10-10` | 224141 | `3e3771ad8db1daf7b123214755a03b00afe234cbf524d2bf2b9dd576c54e8aec` | `ded0ad01541f75c49d630cec05c14b54f4943f9dd0a5e3af40795c581987ce5b` |
| `atlanta` `10-25` | 224219 | `dcf8078949ddaa34b5dd697128046f9b773d057753038617a29600f4b2da599e` | `23b4839617fa89405e39e2061da878d76d677932bc6a640061f0c3e74a41ba97` |
| `atlanta` `11-09` | 231913 | `fccf6147e87f69e3c3a4c6b2646dd1dbb4aa21b1238b3b191c5e1bb6fa00e8c8` | `996573218c11cc1717c5e0228a8cc7c9e7046322ce1835eef1e15bd59f2c4ea5` |
| `atlanta` `11-24` | 228895 | `77b5d754f456e5cd01e30e2aad4f0416f9e9ebcd63a8f8c56414ae51807cd58e` | `287645901b24056e3b760963ef02c307d86bbc5b624606bbe3d1f6ffabe716be` |
| `atlanta` `12-24` | 83875 | `e29d861759d21e8d1a08a298ef22172ca516bc48b04a5cdd28912075d27d332f` | `2234f6a1359eb3f92b8332ee59ff9cbd8e352aadd940cd796311990ac85d5314` |
| `austin` `01-23` | 138337 | `66e7614b09af4e4269a5e79899511bec953a4754a60a62a9e06f0b168d726303` | `3e5fca1fa641597643bff67caca3ef2786209dd9c2ea37a96dd065cf2a2468ec` |
| `austin` `02-07` | 194765 | `1606cd5f3656a10fafb75d744054dc5bf7beebf2bc249e1b2ba57c7742be762d` | `85139784422ac785f92853a6975e64e0c4e3db03bc68cb640377a1dd34c45f0c` |
| `austin` `02-22` | 190063 | `731fbdae662b1e05096230b60b8bb9911ee63636ae16656a6f7234265dd0395f` | `7232d10ef564faa7422be1e008bf16b089df35a3a7bf8659c220db531564e28b` |
| `austin` `03-09` | 181534 | `f2958d3e2a074dfa6430f3d187e7c82c7710478c31f9507d9195ff937d7201bf` | `a0c6ebd37609fa4ef7217b8f6f376b733857eb0c70e2ba0db5a1f6726979d005` |
| `austin` `03-24` | 194432 | `04493f8e42a6c7674f11309121f7f80ccbc1d282573db4953f5f9b3882c0f84f` | `b33441e712ae1dd8b91f3d69fdc63b5582dfce06c52e7b6b1bb9e941de4a3b8d` |
| `austin` `04-08` | 230409 | `c78b3365c9ba4a39d6eab03a3a76d2d701a23e716097e0087a308ac9ca35053c` | `d44627151c738da93394cc02162d95a13f779422d2886b2c9f42b365957c96c8` |
| `austin` `04-23` | 229704 | `65557c751f00364547c6bb633bb5209abacc6f02e976de0172016f393d06a534` | `e48abb7973932bb159381993a9133c3fc5bbc0b1a375a52329ae482132e7f651` |
| `austin` `05-08` | 232164 | `f063a4bb3ca745ed5b468c36499f5e2794b2d2d06f99e280ab882f43e4a050cd` | `12b63b3b9b46dc2362c5f45a5654bb4bfd2cfe8ef7737ad53535e4a84f047f19` |
| `austin` `05-23` | 224197 | `cf5ba6ac93c35c1f7107dd104e3f883835ed7a97a5d37a3dceca353566fd1185` | `9102fe54d9be3874c038a2c8176ff58b9b0e09ebd1d43baedd9788a8599b3ec1` |
| `austin` `06-07` | 227102 | `d587537d26fcd529e51993607d79db6f6ebf4af0d96105017ea30a29a2305cef` | `d988fda397c09ff5641959d618dd27fec8d9509cb5149bb6dc31c917d8bddc4a` |
| `austin` `06-22` | 221321 | `a541d69c8df00abdcc66ddf6aa808df132ef32bb4606c74f545e7b225db4fa73` | `50d093fa48eeee6842b95cb2d8877ad2992178b5c1b3327ca14b614f847b687f` |
| `austin` `07-07` | 219338 | `7a1b18b5930b31abd0094e550c7d71580e8763f4486517fe9b44ff04aed051fb` | `0b9113f4ddf70f4e69f5827bf86c78740863e839f07cc93190a9725bc3c37de0` |
| `austin` `07-22` | 217843 | `1ef85d825ced0e2fc1f404d07c16229b321094d67d25463b7284c1d688b5efab` | `9281e2813f2c78878536d7b48c04a54b48723583d780a8ffbff4c89f48c185fe` |
| `austin` `10-10` | 219633 | `1e2550e1cb5d56b57bf8405b956b558897c2d92bc10ea175a1d533be0ea49ea5` | `8111781a1e703ebd49b363389b809c98dab1084d5c3ff36cbc0eeebda12adeb8` |
| `austin` `10-25` | 228580 | `c8e01afe20542af60dbbd2986eb7e7a6718c4c97b6f247efe31436e9ff31a4b7` | `3131bc96391837ef03867922b4c24b983237ac11b4a6a7687818bad3ba86bd06` |
| `austin` `11-09` | 229363 | `40cc81351e6af37a84096eb4a33f133b1e49a27113fa566f35821853654833cd` | `bd768f53144757e84f687e1d3d54131f082cabf952b981f63a4bfa49669dfd0f` |
| `austin` `11-24` | 233651 | `96890b26c364c6d73634d80a7aa45c0fb10b640fbec45d868a7dd5679c098002` | `cab2965cf769bd9c8bff51b744c8095c7da61c976f44e39c95dcb906651df40d` |
| `austin` `12-24` | 83838 | `7d77caa3ba3e085fb6c0add9abcf005d0bffcedb033b55e7dcaadec826a2f206` | `d6e0e4a4236b4f23e98b5074583118e77d4f234b2cdcfc8b0c95f298884ef471` |
| `chicago` `01-23` | 140639 | `808646f11c19e5f302ff0646d892cadfa3a033eb60f864a2a77267d1356a86eb` | `a18ec0aef17781b039e9c4566bdcc45be1c9369241955f07ffeb99a8bb2ca5aa` |
| `chicago` `02-07` | 195939 | `0e96661b3cdd3f4abd2fc2724fc25ab0689d30d1c0e00567ae29220395bed72a` | `f499937e5fda4fc4adceea1e3b8e98b6c557843ce856eabbfd3f2e2258b83ffa` |
| `chicago` `02-22` | 188426 | `bceb381c49c745c09cbcaf35eae837c5b0e276ed91f380dfccbc427c14f1da0d` | `364c6bb366601a2325ab18c94de922f052ea7e32735a00322712a3d4e1115fd4` |
| `chicago` `03-09` | 184563 | `ce56ed7e8fd2f568e6dd174e8792bee9148d6681568c3a107ad09125d838e7c8` | `4fe04aba88e484c001b5fe344452e79f4b73d81e5bac9b671010b7c397c381f2` |
| `chicago` `03-24` | 197382 | `23d4a86b2e57db2107a0f917e9a9f2e4eba09c3e430ad139b42061d562abfcca` | `6a5476d23961504df165f6ca3e9f9320aa81a00e59cc02331bb3b029b4d61f08` |
| `chicago` `04-08` | 236450 | `d9c07f136d2516de4d74421a01ebf0572e6216ceb012ab967b396678d3d80f71` | `372cbc05526a584510138012e89dd116a66b0eba7a0c31b8658542b83c407257` |
| `chicago` `04-23` | 238537 | `830d6c773d14fc89dd92fdc0993b3366bdaccb811c341dfea4c86b34cda2ddc8` | `04a574c3a5ede5e58e2239356336681c1d6bccd4a6216de4225a1a7219d68029` |
| `chicago` `05-08` | 236752 | `a588eaea05f060baf2733cf6d490373951d1295ac410009d3fb8f1fe569de985` | `79cfdc516ca7696073e38bca5f8df6c7da7bb05ec32bb0a5133d90813b1043bb` |
| `chicago` `05-23` | 233736 | `64320ecd5cfee6825aabf422167eb29ba3e2ea3d9435f28e1967e870d7879fe6` | `47c8d439d751da3752d982623c956ab413360afb98d2295970527dc5c2936c59` |
| `chicago` `06-07` | 232694 | `15c448886326e4c80902a7949ae0f929246ab61390bfa27a9a0f3c5fe30a801e` | `26a5459f6127b3845e1b740819250f38c3c2a5ba0326bb4dff380412c1eaee83` |
| `chicago` `06-22` | 230988 | `c02508ecb158f339b73f49854427271f7f89aa8bfe6fa1841905f7b1d316bcd2` | `17a2ff7716b2c617c5a19c83c9da27c43a1380d017279186e359a56b5a529ad3` |
| `chicago` `07-07` | 227551 | `b1de5edecb0837cc3ebcdb1cbf513f36f8fec4662c6335a0e155d68bcacbe190` | `7a4b8593b9b3ed98b96a981982f96ccc8ba434004516ccaacc9535b8e34a766e` |
| `chicago` `07-22` | 225047 | `951113d2c7cb837f2694237bdefb7df379e9036f03d22e69ddc842b84846b35e` | `6b3ecfecbc84c379822b472548875857466a7b9dcc881ac0aaef8a1f76b4a38a` |
| `chicago` `10-10` | 230586 | `c807979c00c0bd071ddab445d50b0d235556cc457e895a66b8c779369f7daf5f` | `373e5ba97b0623ac8a03e0254d57a6c7db5d49a20ccff28088ee6acd654fc6c7` |
| `chicago` `10-25` | 230702 | `a7aec3c60bdcbb08442a6c8cb684cd2e9f066518335561027f4ec37bac741b14` | `6049c2d22ca3cf79711dba537d02112dd26e2e880b614d8abfcdb530738f16e3` |
| `chicago` `11-09` | 231136 | `003b97181282559ede9146613ae41604f09f6f6805a417390718ec5727c34c98` | `1af8c05fae65fc3bf1a5cb9427075cc0b7b67a90b67f880eebfc89a251a5b3c7` |
| `chicago` `11-24` | 229309 | `d1052aded555b4592297ba8fd367a98eb121c530d7c528b6bd59ac5dc42529cd` | `55870f00b4f7c995e7fa1c6993e6bf92d4726bab46cc379c33047a5263bd4cfd` |
| `chicago` `12-24` | 83015 | `4d4b064fc900edee225888285086f512c1d5d3a58a291ecfae5472eb7af309a3` | `6bb9d250a5317dd3b86df6b516211e6079718d649559c0c91b9e242b439a2024` |
| `dallas` `01-23` | 140743 | `d282e82614f70e8f05b00e4d6695fb83f0efdb1106cb7feb9ebd00b6c9d3e0e0` | `ec572d03c543ea4c0891ecc1de38e9acc78dd1b81b319d7337a532368f503c93` |
| `dallas` `02-07` | 198837 | `f0c7aa53cb01c5365a8b8fb2ef529bb3c1073ff20f99e2c14f0cdfcf8b31aa18` | `6e6d5ee481eef09b9937e9e29be0e693c23931f8521a2d86ef493e0cc17c1fa4` |
| `dallas` `02-22` | 189728 | `b493bb1a3deb3c54b21fe6662847fa83f82959a2a97dc7d77ad66aedea2cca4e` | `3b5944dfc9f758327d8b13a14ec95aed2ba746697b25505c451c4a524b37d6ab` |
| `dallas` `03-09` | 185332 | `5a38aeb2ac1e36ad8cc33e671dfdd67c7a0bcee362c1630899d1bb67b3c8e377` | `8d4b5dbbccd25589981dcc3076abfff70615c84940b9d602f6fbb4d967965329` |
| `dallas` `03-24` | 193603 | `0df60149e1940b3502ee664f2167549a4b22da897c5d4cbcf408bc6c25f44a2c` | `8854aa54a24fbfa6180a6e9695b463aa826cffa97df16a6aba73eb1be89f8c70` |
| `dallas` `04-08` | 231355 | `96225fa639a0c96861c2c24f03ea4e0f40c5d675be35c0e95fc4fb28e2adf644` | `a37a55b3ba80a82d132c7544d837dc5737971c2270af537538eacd201cd00e06` |
| `dallas` `04-23` | 229852 | `30a6b6875b8eb500654263a4c101311f7838cc3e9ea823bb15524025d370263d` | `d4a64f767807b35e01c7f3c5662f5ab80f1e06a0f22685ff4eaaa9030be1da09` |
| `dallas` `05-08` | 230937 | `6cf521af84175109d60ddd430ca58bd2e3c90f130a680895140979d29365c323` | `e52465a7d35233dadc8c633ae5772be6c3843396fc303f0758d6dae23e80312e` |
| `dallas` `05-23` | 228162 | `fb0ace5a9af551c4e4c50c27eadd5458d84502dd8c84c78cdc7f9e307f8961ea` | `738492c05687baaaf35113740e739b0facf93a9885a3eab5cc3a403bb3f7b6c9` |
| `dallas` `06-07` | 228818 | `f9424e0637b3c21d0b72814638570be4b5a8de69d013b92f3a88cb8725c50f2d` | `f7c95b2ffc0b014abf649fe0bd822a8f32b0ba7773117a0c31678f22f454f55b` |
| `dallas` `06-22` | 220289 | `e561561005e028dc3fab483fa5c98119269335777946f299d8aa14bf87ca974f` | `f6bfd6abb6925553f4055cc0f57c870d17dd6f077bbe29019dac42909d926ebe` |
| `dallas` `07-07` | 219707 | `c5adb4ff6716d5b8eda5f2f1b36ebcdde212fc62d5e6c1831b14d406146a185e` | `3a641b6c233b22009d7591ab76132b04782d0fcd2f9f7823021847661e45db4d` |
| `dallas` `07-22` | 218702 | `51ea10a2cd853a1ed36d01b9da009b189f195c05cce089d16cc6aa0a79cea022` | `bcb400c718a0fbbf7bc34e2b3d8217b366e2714f84adc5abb46ee3cd302a1126` |
| `dallas` `10-10` | 219246 | `ee030b03bf533a0408ba2285d82ed342c8a2f195649cbc19e29d117a9c01ddd6` | `8bba97540b6e3f781b67b54b8932bda74f6709dc16c6805a3fec855b5114908b` |
| `dallas` `10-25` | 228747 | `04ad6724c795426626b719b562cf879fc90c939c241c8405c46d4fc11dab7934` | `ff9ffc227b67a72c8a63efb95475c4bee73203ee051564068360ab3688360a14` |
| `dallas` `11-09` | 231063 | `7491a73504f01205631ca559d53fa289cbb8363d48c55eddb0559917c84f3528` | `d3ced210806918904d71ea28b74b6b018becb8b56c2ea05336e6fdcdc67ff112` |
| `dallas` `11-24` | 232619 | `d58ada6e9bc981da6a9400faeebd2277abb471efb88cd0e72ce9d19bca2cef54` | `645988de08eb94e6ee6d7ab718384c684d15dfcee23232f41a2b1396c79c4290` |
| `dallas` `12-24` | 83130 | `fb674f89e43056a7eba5a56509f7e10a7de06517d40e358e2900f7b8cdb387a6` | `a98a2b8f2b210b852929fa2006e9ec8251fd5770fea17758bbf5a6942681f999` |
| `denver` `01-23` | 141072 | `2871a7eab45fcc4476e5a5d6293aadd798a6b35bd4ecd71006be90e200698035` | `8dfd332a83289f4c083c2333201090a0b9f7b79ba7610d723d9cc89b205cfa5d` |
| `denver` `02-07` | 196071 | `347cd9e0d3a8c31fcbe4710daf31ac757e8a457eced8c1b03c2fc94c5391660e` | `af13a8fbfbba97c3c384f1c552c2ed509865e30573c2e2b91e74251d131079ae` |
| `denver` `02-22` | 189835 | `47d92016450d042e12fcbebbd334648ed746bc4c126971372a6d6034494c1500` | `7e9fe69e110721603798cb9752e1244a82eaaa4875fd05e0666968fb7e4bab84` |
| `denver` `03-09` | 184486 | `3a95617066fbcca910c9f14dbccbafbd1c4f96bf529bf0631a9900e175d16451` | `ed0e77a638dc6a9973bc3dcddcb4ecf2e929a9a45974ad55af03931cb4537288` |
| `denver` `03-24` | 191350 | `e5ea3a3cbcdf6b402f0648f4d271954a7dc217bf3491af50fd968b145bdcb785` | `6f7599d1040f53b38188c97e397ac97cdc79053114d33c27649a49db94a71b0c` |
| `denver` `04-08` | 237180 | `35588eff3238dbac4053966033e5fe200c4d296f9b704c2e5f0f2aec999ed70a` | `3f221c3dc377ba20c545b2621878256e23f60aaa63d095d1d6386f7273e82286` |
| `denver` `04-23` | 239105 | `0ee833fabaa15caebbb1a83bb307eecc000ef502e65cbbaf68ef858e41e31e4f` | `4c4f15d9cc6f7a12cca10641a59589ec1f5df0e0def2e6ba7d0cd211e24e9087` |
| `denver` `05-08` | 234831 | `c256be639cf34895cf2957adb6c8fd4d884e3ad4aaa8969734a5bdaabdc93c24` | `7fe6bffdce1edabc9dd1d232e1834400e4e3905cac91225b842cc9c349d5eff6` |
| `denver` `05-23` | 233464 | `d4a44d6bccff47baff56910c4c0ea2d22ce828d8eff39273a9a0ddfa421bc879` | `a6420a932a742b4e8dc930dba6a0733fc31e40c7803476c65251b9bae8cad2f4` |
| `denver` `06-07` | 234238 | `a544dc981d541d651654badb8b3cdddbe9e710f16c4dbf677d3f6d08a3a37c57` | `f77a9d4164b2bf766ff4c113d8a204fea9f015cb11c6fca6de086158ee4193cf` |
| `denver` `06-22` | 231585 | `4f9b885315e0260abf637c9f6d6a8f3ce3c4646d60926cd5b7d0cec4f46bd57f` | `e1546745624ec3d3b07d3a7e7bdc4b0a696e55dbc9eca427a6355a73f1abf45c` |
| `denver` `07-07` | 224635 | `13a15e69e7119a14325b22a3a0baffc5763e9e4624716eb79b9da5bedf196719` | `e3d06220b68087f2a4643e4754d43acb882d11acea3fdccc02b05002228e7005` |
| `denver` `07-22` | 217090 | `291f4000319e7a8c51e0c27f00f40b6ae0d3915c9de11e927f344a0b24429370` | `7b5fec6d081bedb4af4138a24a18a99725011685349d157ab250197d43c293ac` |
| `denver` `10-10` | 225939 | `03f47eb88179aa5094c6f9db62db659dec27eafd595e1db50ad0eddb904162c0` | `f0b4e52ce81fc8fd19a472f6f842241ce76e91ebf8dbc8b49fa5dc58a8f7d1a0` |
| `denver` `10-25` | 228295 | `94298cf28ad49f4dc937bf06896492c5e9bd7d05247f3f662f7d99e4043110f5` | `47bfcce079393e1834dbc65c47465cfe86e21e65b37bf7f74bf1599b3bc619c9` |
| `denver` `11-09` | 228242 | `a1788da9d5a5d032fe6930b315e85403d517f3bf2af7c8f3cdb77c4244e007d3` | `e75fb48ae4daa223339f646a6264a01e9a44d3800b30a812acc0ea0f8647e29c` |
| `denver` `11-24` | 227167 | `33cf903f7df1fcace45a162cfde480eb89148b6c04c2844324ae4247504a21b5` | `0608148e5ccaa1d6b6d7f3caaa88c624daa3f0b9ab7f3fb191ee5414a1e2ea16` |
| `denver` `12-24` | 83208 | `7402d0173cf6d26891d9771e587e42e9ac7e8b416074621c0843997a183c1535` | `b3de079af0e48cab10263ad450f8a5f6063a102d00d4bf5e8fc36e02b452f895` |
| `houston` `01-23` | 142011 | `c12ca4d0bbd124d56207b51a5ad0e17b89d18f6feeeac4eac3d8b48331cfb19b` | `9218e1c81c932b892c4beb7d3cb2a0aa2439c3edb0485ab739e7b1dafd9def58` |
| `houston` `02-07` | 195755 | `82964972f88b86ccaaae3c9716d1e535664ff5b62cab93355c6fcff67f85fd04` | `5d68a5cde98082063093d3c4a489f7992ed17790a75af6f9e59be4d02c8dfde7` |
| `houston` `02-22` | 188987 | `ce06e3982ecef24cb9b0188a433a90bd3904727150be9c32f6885b29d90a7d6e` | `8e8871a108e2ed5955224bfc52f9436e85e1b6709dfadc08fec7124e513843a2` |
| `houston` `03-09` | 184419 | `82a73fb645fe417277bb727c751fc8c2338fb20ff6ea0b58362a3a44ef105389` | `acc374c70ca817f5b5ad69461ca7853586fbd6e0785d688a8a3588463b36f149` |
| `houston` `03-24` | 196369 | `8de9eb8b488ba213895e5c7fe8238a5a5b34370d101b147ebd3079bdbabebad6` | `650a68b60669a154002184765becf7f4b2662d6bf7d3fb7c50cc2dee886f079a` |
| `houston` `04-08` | 229463 | `51b8fdfb6a08bdfdb33fd091404ee2ccea58da579360fb3e46ce29217fdf7618` | `05034d6678632e67d220560921da4fdede34faf5df5a0f86b464a52602ca523f` |
| `houston` `04-23` | 225940 | `6927fb6ae345bc12a056e501c8cdae3b03dc0852b5b853ae40c65aa37d7ed2a1` | `3b78ec3dc51eef165820c42ad81e26621973ae707f9eefab003e285cdfb73bb5` |
| `houston` `05-08` | 228531 | `26a0495b95ec37499008f54e2a4544462780413735c664b1bb0ab6f0e2dcb5d6` | `268714cd7fd9390e110569e8eec57b60d310175901996d3d68e94074b6b7fc94` |
| `houston` `05-23` | 221975 | `981876212fd1d8ee77fbf0ae7583d9a4c08e2c088026ffa3044dcb23726e9744` | `0be7273a1f901b98b7017234642fe2414cdb8cde93a68134d52b432fc2a0f312` |
| `houston` `06-07` | 223286 | `ce052a91b715275819302aba9b9c3a9652d8ef5a0e4d463ff6377e141b13c5ae` | `e3a19e30282ab117f7a38127341d5aa09a5481a11cd741a772e3811ea2502597` |
| `houston` `06-22` | 231815 | `4b4cce2ecb87c04d77ac4b39769ea49d14182cbab8a5b907401bf95582d0e9e1` | `7d053ebba51da44b35a147192e7a493a7556f436c5da0a23ebf4d96ca7395f66` |
| `houston` `07-07` | 222316 | `9225a7684891d336fa438db8178df40c67d9faae9c7272142418bc29ed382007` | `a63cc13aff35ac6e8066c4471959790612c186b5044f24c9704fdb20b4579871` |
| `houston` `07-22` | 213492 | `aaa1e9dd519a8a97b587ec5bef2911f78aa3e6296530deb702dbc92d1dfaaaff` | `ad1d755051f3dcfb3b015216ac735665bfe2668fc4204ba81ef27c63d623df59` |
| `houston` `10-10` | 220167 | `cca8f1e61163462345d85c7e1da770465801c5aa40d6cf5bdef36a547271f1aa` | `b90682562a43e108fb17043a6b250353494708aec31a5a4e504b30dac7fbfbd7` |
| `houston` `10-25` | 226548 | `d12c1d0008892ddccfd97174657cda3ce52f576b23a44da6758cd3692120ab6f` | `a7ed79eb2d5b81079fbb81a9e29ea21fcd0e763da78d2857f24a7222eadf72b3` |
| `houston` `11-09` | 227920 | `525ace2adfada14f846855fe87ab76899b59d73e3eaf23615e6428e79739c078` | `cc2158efcb1655bd54bfaf56d52fe7c3ddc459610f98756213094462857d2d96` |
| `houston` `11-24` | 233096 | `9d3cd2b910a4abcc661f87df6623511bd8d5ecbbbd1d07c63eb63d85a6807cc1` | `3d6c7555cf0ab8e33f75397e5428430acb18c5e3d65f14354572bec4d5cded62` |
| `houston` `12-24` | 83044 | `000f1fa04ba2600eb1862f25f5a85d8d59d6f7514d36219b62dacbde17d54ffa` | `a0926390129ebb0c145e203a8e4b1647b6963dfff729bdb67adae97f47229fbf` |
| `los-angeles` `01-23` | 133185 | `68f6a6b0cb7073decf4eb5a8ef695b937dbbd1501c97cc8b9eac156dd3e29418` | `ef3ca6584510d966e2dcec25d0fcddd25129b6e78b88285d8b65a55c83d8d396` |
| `los-angeles` `02-07` | 188343 | `b34fbd55e1bf0bb21ee88915451f2ad25f9bd0784d09b2e4685c2337d97aba67` | `cc3b933665774e4b44cf81bb0a6358404d9c47169981f2c55eff7b73845e6027` |
| `los-angeles` `02-22` | 178948 | `674c4e5a07da0ffc2453b45ac7b69c543197829d8adeec3a254beb09b80f7924` | `76a09875bc9c61fb935c1f81872dfd70a45b078761d6653d0799e0390b18115a` |
| `los-angeles` `03-09` | 174169 | `47cc6ae40738b465cb4943186a08932aa643250b9c1d4181e65e3be78bb39469` | `0c9d7dcf6c8f610b8ba9105722a5d771feb6a055f9f6d21ebbe7a8a42890b098` |
| `los-angeles` `03-24` | 186658 | `83f781bf1ae8a162455a0038480b261d7edfe800c97c77ab95be68f856ff075c` | `a648fa20651cef081f1f99b2d01e8b4668752265ba1e099165843724e8af1817` |
| `los-angeles` `04-08` | 216327 | `a65860d3bace2e2c850acb129809990fcfe46b22219781b5cb73b6e18763909a` | `eff004f9265bba6c11f09298eb5327bac3c6fc80c45c8a5afc98210d2c96de24` |
| `los-angeles` `04-23` | 218199 | `22a335a9ae51c4ac8a6e446cc86b921d7444374fbd630c24400e1eb2369dfa81` | `c4150bb61373f53a7001b7e60ed9b4fb7f833f4a2ffd00255daea1cadca8384f` |
| `los-angeles` `05-08` | 218725 | `ecb39ac5d18904a4c01826924ecfe1f0d5aa26f139fba73064b4b76406d83122` | `6737fd86a556b7c74b7579c3858547094336978d7e4dfd2264339f52d468bab2` |
| `los-angeles` `05-23` | 211406 | `15a7737addc7033f845a227f9e5e68505867909650b5155a756e321d17f1bd56` | `461a18b243fa8d38210b1882e854b3af05de89d63eea420477a617ec91e1f2f9` |
| `los-angeles` `06-07` | 213158 | `8c1726baf8b0e9c4fcd20e724aea457540c65c73e7a263ae15e6de2262962880` | `bc4047ceca60e9ccdcef40d3cd667220d3cfad3b0ec5d8e3a2b6e08841f793ca` |
| `los-angeles` `06-22` | 214952 | `4f735b4dfee1f0440180d00e660a7aecb5f2f28e2d83eae52dbb802b57afa3a4` | `e677f950570806fcbaae57d4b2ab47f31ce187bfecac375c2bb9992324b8eca5` |
| `los-angeles` `07-07` | 208119 | `2a06a587a9476dc6fe0434515d8e3c2166f65974afafd48d87a5acab61de9837` | `f91bba33efa5e8ea22a3ce804e8d54106a275176e4dc05f840733a64877c6cc6` |
| `los-angeles` `07-22` | 208702 | `ab8e91f10e383005d245c22d3ebc6b218848389661a2da3f67898e9169339993` | `67ef18bd1d1b04d2a6226fdf87f4348ca5b5b9e76dccbdfcd31f9c50133b1e18` |
| `los-angeles` `10-10` | 217665 | `8010fe3cc5aede3dd6c4f81ea55bdb452fbb9c46e3df4300f4cf12ad3797916d` | `862818404a6b5a704be339a7c2056243ca9ab1fc09381fce901d444c758fcbde` |
| `los-angeles` `10-25` | 215407 | `bacde8a12d2b0b16706d7fb48d913ab73d12c8cc22b1a328977eefd7fff35a6b` | `f5e299a1d234c6a2e634c6bc7cdebedcde629218d2ed84a4774de926f805ef4a` |
| `los-angeles` `11-09` | 217076 | `6afbca14942bd9e9b95e0fbd9ffa26255ae99f8408c72bf7517da357b5139c34` | `84c414394d4db4cd6696b7eaa49228792af648f846f3cf04687ab27c4947e187` |
| `los-angeles` `11-24` | 217298 | `dbfee0b9ffe5221bf1d2bab8249d73341579add88b7ff0e0b476f3e52eba78ef` | `f546a9658dc2033eddb68491c48ac7b258111e3db259a7d82064161ae92b7c4e` |
| `los-angeles` `12-24` | 78273 | `57d29ee356d13d190e8883ed22307de376941101e73d7a78cac656f2810dc016` | `bf951c78e05dc49ba2bc672e4949186f827371a748d660c6e72b2a0c2c67eb89` |
| `miami` `01-23` | 138730 | `aa5b5a6e831f6c5fa1d7aa95d6788d0564de8c7dca4e55b1d8994905f6d18deb` | `49195c162140b47378b3f85185f473c5276f8388c81476e851855b038ea26973` |
| `miami` `02-07` | 184868 | `5c92b623e3d2b7b7c218c4fe1893d752cf7123ded0a24370fbc3360effbde2f4` | `b57eba3e5c7842285c06499d1b5f38890b3fe8dd4210a4fbe423fd54cf5515bd` |
| `miami` `02-22` | 175462 | `a7b61f40c2b34101040dbbdf67c4d09d526abfe78d6da442293498a206173dde` | `2fa061ee6e2d097f9790aa8ebe2dc484b5ff5598d30607a198364753f2089074` |
| `miami` `03-09` | 172659 | `3115bc56a40de27f1067e17566ff9e14981f062059e16baf0f736e34f9efe52e` | `5e5efbd5957b88070418dfa21e29df3bbc780000ed405b09858360674d210e43` |
| `miami` `03-24` | 185412 | `40e8c30c74521638963fb04ef9823f0dcf5a0efa8f3c29e35062577453c5841a` | `600d322c6d74c12b237e7409557481adc9c3ccb17a7ae99f804e5b0082c1c8db` |
| `miami` `04-08` | 220600 | `5bd28685e4102acea3c98d9bbd4f2549477b1fac1dea85a9fc32a710ca0ce696` | `376d407b6667de104d34d599b5434f43bfb72e3627c73902b33cdd701ab9be80` |
| `miami` `04-23` | 213813 | `0528975ebd3e64a6f6acdd6629fb2ace7f860df4949e6614671052c323e404f9` | `bb7be2637fd8de46e3fa0e9ae8fae6e1c3ed8a955c28cb3ae5f94ae4abb14992` |
| `miami` `05-08` | 218901 | `ad5c990068d083c0ea899ffeb91b362e71ef828978ce5674995e9f3e2eb1bef5` | `3167030898f79f5d98f3a79de415ab6b333b553131072805d6f8ac66a6e254bc` |
| `miami` `05-23` | 214316 | `fdd0f043b861f1886b4f6e88e038580f2cae0976b467faf8681d07fa9cb26f9d` | `4ddce811423f74764999a739733755b660981f292bf264ae4c498055ae212852` |
| `miami` `06-07` | 219336 | `44ed91601487622b62da0ba79465933b896784b9dc11dc2023344ce0769ee1c7` | `cd6c2aa61418167c2957153318af2432ae2f65a4f772b20f18272e468ef4e5ef` |
| `miami` `06-22` | 228412 | `faf9471cf0be946fadc5bec6167be9ddc6b45877b5ee4e39f428a6f8b080d8db` | `0063fbd0ff632a86ba86adc088d1be7e420668ccd073bf68f0cafcc9b16d88ba` |
| `miami` `07-07` | 216481 | `5955da247911528f381037e58ee8508166e1b31f28a5c5237e8dfef0e602075f` | `a3c2be02dd7453359adc7e6ab577ee29bcd5ac0bc4073422fb895c2637c19ec0` |
| `miami` `07-22` | 209916 | `0d96dcd4d916355bd1d1953443e39984b75e312cb03e697766d8ad00f561d4f6` | `c745d976ac923c3b4195f87b74d342494d4db4961a487a770625a363914ce25c` |
| `miami` `10-10` | 216230 | `47c71b4236dbfde7e905e4a08e688dcdde21fbc23b257b1a7340bc3e5120f489` | `6f62d0cf6553c286cf12c6bd3bbf054fbe5a3e076dd8f4a9added92a184f1151` |
| `miami` `10-25` | 214093 | `c66995a2fe275a2e5c716a953685ce25769a04af3c40a7a9e50eb5402b7416c9` | `c242d5386db4c915ba499a7dcedcb616191410d685be4e6d386f07bc34baa659` |
| `miami` `11-09` | 216622 | `45f752eacd492708e8eae7eaf8f2ec4171e8e16fe1220fe91c3db3d5a2de11a9` | `3fd87ea0461887376b06101749c3d2fe8c0c3f356080f5b1f2232804a97bf93b` |
| `miami` `11-24` | 216114 | `8ddf1c84f84a7992d7b1dfbdad231631b2812d294232f70dd951de0160c4b699` | `f1bbde7c7e55125b3367bfd51bc098bd5f0b744132b0f89b2f812ed592305436` |
| `miami` `12-24` | 78866 | `e93d9ac649e201005700c874a4660109da8835bc6a15cfd7b652cd15c5748a5b` | `ebb755161725fd7b68588fde8fbd227bed4cc8ea9cce0d44a95ec52ad31e3e2f` |
| `nyc` `01-23` | 138110 | `a44ac8f9b95f3fafdfec522748b660deb7a7ca7385f9f8d7e85d1bb0958b5718` | `b5b783b4ad865be30265cd9cb874b76f74f32139796b9c39f3eed4c1bcf535ef` |
| `nyc` `02-07` | 196600 | `6e2ed219ec3e7e4e4e006cf1ea6dad2cf69aae5117d024b0e2a275152f2d5097` | `c8467fcf10f10c293fa0837a422fefbcddc595e15ec9d18aecffd527e7ce76de` |
| `nyc` `02-22` | 189667 | `9ab4d0df6dc745d22f568fa5fa88d064f7625ced670cfcda1ddaeb0517dbd30c` | `e0d6f23793e5e68b5c443bcdf8ef44af22092568d40dedf773440f366ff87398` |
| `nyc` `03-09` | 183834 | `2c30f75525514c4016ee2a0fa499a3fb4710229e8c17e8e846d74e67f8016281` | `f85f6868284e489c9a3c4a642801306cf68075e11d0b062517a6e09b6c50e2bd` |
| `nyc` `03-24` | 197485 | `c014e7ad7674bfc681fe6f13af1f897217414aa9fc8d4a75c6735c3aff3f3cf4` | `dd8ea97029ef5eb4e06ef41922a5bbbee324936ee0fd7d4f42b80a6efa5955f6` |
| `nyc` `04-08` | 237833 | `7cf1f6028d723fe0c1b2145afbd4eb1c7968b65d26cb6e4018efef87030b4968` | `945b7fa06c5cae634c9f50c2df8a1e37f227681760f2b053947f23bdbb5ec4e8` |
| `nyc` `04-23` | 236344 | `31711048d025f756f59c988948c9839b5361e8ba1c22e994ba14f3f64ee0be36` | `0073aeb1f950de50e88d15f271f75cb1b9719d7136d35029d233cbd8db051e77` |
| `nyc` `05-08` | 235166 | `d71720c59fa53061565735ff6698ba96ac5aa49068f3f84fffe7656e752b6b0b` | `efe481a38ef817a6ea0f184f971ac10e04e23c8da388da3fd753b0046c6d0870` |
| `nyc` `05-23` | 234279 | `96a63ce818d48ab5571d1c3b97186a5413d0fa5c15b920419a2651e2e9df86fa` | `84f94e3e946e53225e478b61eddb8f397e8558ed62a32759223b39b1562361c3` |
| `nyc` `06-07` | 232739 | `fe3a8d572c5af7754e59d7d9fc9aa8f5119e4c68a61cad73b9b150df1a6901fc` | `f2e83935e209d8b473f8213228905c7675ca7ebb3b00487e775234061032c397` |
| `nyc` `06-22` | 246087 | `4f554f4f2fde6d5dbed372999a1087b2b3bbf39eee06dfa80f2c5dd431e01904` | `dd52034a27063796dd4f3b04fb83e9ebf884f588a7f0355a7a95784f0bd91b49` |
| `nyc` `07-07` | 229663 | `af0792719373a47c19300e78d1b0d2c33e20cb78649e8e20c5deb8294cec4eaf` | `627b51d541c5d75dea2af8d33d6fba7c089e970effb226804083faabc3f47ba6` |
| `nyc` `07-22` | 225651 | `ea38c9f6b031ba297dd5d66d03a11a9175527ef655be7cc02dad081f88d946ac` | `97b473ca5ab3eb5b33bfbf46d778d6f41df99cdfdfd6f7ceb4fda3c115c3792f` |
| `nyc` `10-10` | 228783 | `5b41c9782026adf1d405322133b44084db762d10c22dba3829453ab4e1579744` | `45d506c076e2665e75d0c0e8da37fb8aefec7c0836ac4fbafa53d61b6e6d816d` |
| `nyc` `10-25` | 223631 | `3868bf2461cd41c7ddd1d00ce06c568615fa37084159ab7a7f9b530760edcdb1` | `88985ef7f836bbf59ac789ec006a46e936b33dd4c80626fa73ee86add870fecc` |
| `nyc` `11-09` | 226741 | `d9c06c3721b752e2adb9cdf5f0c47108bf94c055d38ee144d63f18ce147aa9fd` | `f31258e1240e8101e2b010e7a89eb6fe7192e12e89839380dcb89c513403a544` |
| `nyc` `11-24` | 227583 | `170476437e8fc3ef902fee0994e90a302e10cbef494adb8edca7d5fb8764f2de` | `fdc57b424fe3544018e4d7c69250e6e54213b782251de85a809b30638d6b1824` |
| `nyc` `12-24` | 83377 | `038a5668d830f32f64e2b7dde5bb7f50e6ac3c383192877b40888d478034ffbd` | `a492d07b7ec76937b022a94e8c57b7c5c66cd2c8caad305b0aeeb3660f0bad1a` |
| `san-francisco` `01-23` | 131386 | `6acff7aa54d803d757521034dd030e0341ce36a39488e1209fa21bd095465a86` | `8919bb9a5ed6f9633dc444c23d1aa384396c43805199423a8d6c92abbc8ac83f` |
| `san-francisco` `02-07` | 191171 | `f850cd7381ad780ad3228f013fec3f06217072e56de5270965434757d7f8c172` | `88025130d8274612ae1788e57a879a7974fdbd7b0ef16390b0b2db9f68cff90f` |
| `san-francisco` `02-22` | 182275 | `3ae7c0239effe03819dc7217216ddf6e598c1be9e28c453b8611829a438a17b6` | `d1d5ce92b641262ab916a4d259ed9cd2421de41edc3bdb4454dcf0b9535d6392` |
| `san-francisco` `03-09` | 180261 | `646231ab58b1d5ecf698d29329c591f7251037160800734e7364702e5fe82faf` | `8fadd601fc77bff114de0d07b611c0b1d6d6a47a70e08786b46bdadeea202af1` |
| `san-francisco` `03-24` | 188632 | `20934325417033fc88cedc893f574d23c747498ce452ab3a7b038ed655f09fc9` | `22d8d14d46b8348a00b2ce83b4036e8409803551f2492861734d1558673bf3e8` |
| `san-francisco` `04-08` | 226673 | `fc12203125ed76cdc5d45d8e1c887b2d06de85b1f3b970d886892fa80f6f74f0` | `1290db9c3f9434aec46a7b498654809bc758b1e53d8de3f2401980ac12e3db2f` |
| `san-francisco` `04-23` | 227255 | `467670b2544b47a40eaec3b028505f008d2aba7869b5c87bed53b4e885765e09` | `ea877ee201d6a79d7faf792723def0bfffd8a006de68832977e8d657d8836493` |
| `san-francisco` `05-08` | 228209 | `f1160725922c7ac83e4714d8d479565b1fecdbde8fb769b9620517a674517a12` | `76c0e7a482725910c79704ec43280b0ee7ab995ded6353c0fcb1a2f0eddfee08` |
| `san-francisco` `05-23` | 218222 | `347e58c93fd9adf410d307e4e4806a762d0a3e4a12bca6c52cd466abd86af243` | `f8fa546ba1f8f1674813cca6b8ad794eb2d551b91fab9435663152f1dc709deb` |
| `san-francisco` `06-07` | 223000 | `115009a6f1df89188df459e7144238ca09dac9bdad4c67f086596375d770e614` | `e95d838847be840c0d47437205d002061ed62680314ca2f48179a8bf5b77debb` |
| `san-francisco` `06-22` | 231801 | `992ae2fd96363c26ffaf250f89a38d3b7a747582aef282aa3e6de12ed4dc3f79` | `26e481b25580e87c2a64211e545d74a394389316529e344fe1ca14e025ed23d2` |
| `san-francisco` `07-07` | 218512 | `fb7e11ea2540473b5e2016d5e4c8605c2dded402b605e46025477dd266bb7aff` | `6c759a883023237a662f1187e479a4dc59ac23e60b82cc3edf71bbe979f2bbeb` |
| `san-francisco` `07-22` | 216813 | `9f8ca3b36554e7eaabc07d87586c8ed9a202312d1fe257c5f9b94437e07e6eff` | `c75ea1c61859e6171f2401ffbe99fd712d785e9488c5978db05588a6c2abc369` |
| `san-francisco` `10-10` | 220384 | `e094e422db69d83ff1ad7f03a2f062b1a4fdfde4c3c924592ade35b876bf841b` | `7a005304566f77d4d10d2e230ae87cfe4b480589d4e3394483cb2afcd0409a1b` |
| `san-francisco` `10-25` | 220157 | `43610e02f6738750cdf0c828b837be27337473d9d0b074c3f1b207c27147596c` | `4a21edfdd8f50ab0ffa9708de2f5830c963ec024b4c8861643ae49f3284638fb` |
| `san-francisco` `11-09` | 221807 | `d60f07c1d116b3164a156c9e3e88678ca9d1bd356c5c88914ce295e2cf04181e` | `1ec3e3395bf65b37063c4c97805718474604ee379f64a0b02116825be3e6b10f` |
| `san-francisco` `11-24` | 222489 | `a25cd6d8f76c0bc2acc3e381d6d6683cad1b99d4e1b09d3a03f760a50a58ae37` | `e17f2135a93c3efbd85e237f9458488ba107f39b2301f7b77e4fae8e216fbdb1` |
| `san-francisco` `12-24` | 79466 | `6be38ca5801cce9d244f3c5519150cc64b05c85e1cde89d3dd72a07bb56e7a11` | `0b00b78335d9fa0103fa37f0059bd48ff74520ba7ece11acca333fadebb16d4e` |
| `seattle` `01-23` | 131598 | `7914bf8e68c4bdf4cbf0b75ad6e74da329b792b03fc41bf4a85f48bea597a46e` | `60f8554926b9dec0fe0bab7f0ed06a4ee5f8ea77100f43416a9f9b90dc2f5866` |
| `seattle` `02-07` | 189366 | `e5c07d969451fc831f2edd6f620272a50a1ff31a68395d4478faac3a97d7beca` | `5c4fab310b4cf8d2c7edb9f2c993c3a59a37c3c17b3a370a099b916e24479255` |
| `seattle` `02-22` | 184685 | `58325755f12d4bab935158a8882db8756e1cf154f5f8239be6e9314f5cfa0569` | `6189952700e582cc6eb449aa7cfed17def66fa6a85ff7c496a023296810b9936` |
| `seattle` `03-09` | 178773 | `632fb4dd764bef1a4a87475b6db017fca669d56c0478c38bdaf229e145d0ff5f` | `6de81f287b9f16c801f55f5cce4de3c13da88e10910a6f55506697d7c6a8c423` |
| `seattle` `03-24` | 190101 | `c1190b69c820238469b16c198d7436f4f0a14ee86b48b4dbac752a7323494acb` | `e531a2e897562e7094fc8ab40f0bf26fa2d742a8234767187706ed9c4d0e4dff` |
| `seattle` `04-08` | 228217 | `3337c172c010ae3bfec61524122be161570639b52931388c9d5f91c8fc800b9b` | `d8691fe7e57afd7fb80eb00054d2cc2b34b7c88f5b45b0b367cadfd619b41760` |
| `seattle` `04-23` | 232870 | `bd622b5c42dc73a50e2abbba0484496524dca137407d78d4d5df90b5943bbd9a` | `a33ec5616eb097c1ed9f12533fd2a317250a8bed5629f7b9f6dbe31777255a84` |
| `seattle` `05-08` | 231572 | `c5c6f9696e0f58981bcdba3c02a6d6daa31069c655bf7eced74f5f7df16164dc` | `7563d3ebdfe9602fc7c930de4737b325d2c931e388a8ce547065e74a086f48ff` |
| `seattle` `05-23` | 229170 | `527152b7ee048481560a4edb1c1d7a1af6abec73207e985610aeacb153bcfc33` | `126bcc4e6514ad12ce8e5e66df917d273cf6631a8c36392edc44f1ea2934c48f` |
| `seattle` `06-07` | 230107 | `defd1e86103894754e51960255c4b109ddd52ee8ed7c7dea9e0c8b18c639aceb` | `1cfa40441b589af4eb1290fcb2523e7225563bd26b6a0363aa64c9a9d6127819` |
| `seattle` `06-22` | 231009 | `fa5f771c23e46d7440070b9681037d6f86a6328128ff078f08354903d3079f85` | `4718c8874e901e5c4123f8fac49f4cd10adb21c8bb2713454e8150680448f5e1` |
| `seattle` `07-07` | 220423 | `f7d650235bfcdc96f45b40658289f6cd8897a596a8f263a0f46e681c09f1741c` | `965d546c0edbf0acec3080ed92e999b534ad2f920dfc86cbb1f02cc6af4156a6` |
| `seattle` `07-22` | 222057 | `091c4eb6cb823103bc4768706185203102aef25ae1fa885036fd0f73552ddeb5` | `6866acffed0dc92f08e14dea66149daec0fb6983a9157af766d6974fc564a564` |
| `seattle` `10-10` | 227597 | `6eac587644c75bf3c782cc1c8837d26035da26d1f1191fe020641892c4d61cfc` | `dd841a2aefeb52e709bff908a8c8140cb4c7a07cde016caeae4332c10b7615ba` |
| `seattle` `10-25` | 229520 | `4c33b655e7e130fab31e0a043666bb25c2ba01eb5559c4275c68c8ce9b9c4d94` | `2c24742dd57596dd38643160b8f34272b99efb6757074d252e54830c62f2d2b4` |
| `seattle` `11-09` | 225373 | `17641714671a6174309d318a3b2ed8a6dc9926685192f94081720250185930e6` | `70354c20a35a43b4e681f67b18798d4fd5798de27dc70d6abc44a400e3772ec2` |
| `seattle` `11-24` | 225114 | `db6accf580698e8c6db9259a0c5a942bd456e483ed20cabf50927b161e2ee692` | `c509c92939d9943ae96aa20b266aebb5ec196477ba8a2cb79f7acbf68677f6b5` |
| `seattle` `12-24` | 82430 | `cf49fcc52f950f0fcde442f6246d8018a879b6629dba2cb56a517ed52cfb466d` | `d66dd62e7836a244d08f93fb47348ff6d071a9fcc784f58b63915873ed9ac604` |


### `run\s2_build_halt1_evidence` top-level files (13; `pool_iem` in the manifest file)

| `s2_build_halt1_evidence` relative path | Size | sha256 |
| --- | --- | --- |
| `frame_inputs.pkl.gz` | 2267997 | `3d6c171c7537ad0ff20beff9a6a680fa88f8bacf247646648af460a0d21e531d` |
| `frame_noy_raw.pkl.gz` | 1921486 | `163f2c4880bc78a055a8742c09c24eacd734505071647047a50b25b8471be3f6` |
| `gap_blocks_jun_jul.jsonl` | 338682065 | `14b82e5429f451b4cac508bddbe33ee02bb92ca3ce2218a512c6076642c91271` |
| `junction_manifest_after.json.gz` | 4198083 | `f93c2ad20efdd85f90278cf4cfa7dae6bbbfa4201c30b649a01b30cf2b5318a7` |
| `junction_manifest_before.json.gz` | 4198083 | `f93c2ad20efdd85f90278cf4cfa7dae6bbbfa4201c30b649a01b30cf2b5318a7` |
| `nbm_market_new\manifest.json` | 15924 | `c61bf3e98daf72ff9dace2fb307e666f6236165c2a1dd0b430d56ac0aaccaf77` |
| `nbm_market_new\nbm_pit_corpus_rows.jsonl` | 7367197 | `642d928ccc3f05dae559bf72dcaad262b642e641eab176ce0142172a5ed76ecc` |
| `payload_meta.json` | 94212 | `bfb08fd63e1e9d177191f40bdfaa1649db1bdd349d1542f0cacdab77e47fb3c3` |
| `receipt.json` | 3236 | `8ff0d20bfc12f58e6c8c272f7e449a1a8f812115045a1fbb2faa200d38f11977` |
| `walk.csv` | 414090 | `96b9e2d7e95a9b7586bd2aed0c088682e4ac227ca0d246e6f43833ca7795f2f1` |
| `walk.json` | 566046 | `f3cb9124db5d515e393e6e3419190a64329bcd54827ba88621a4a970ecefa560` |
| `walker.stderr` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `walker.stdout` | 5929 | `0ed0b87e69326507ce08808a0e06b381e1eb69def7e1b2d287815ccc1a2a5ccd` |

## Appended 2026-11-03T07:27:29-05:00: runner v11 and sentinel v9 (option (i), both files), rebuild launch form and targets (append only)

- **Master's ruling (relayed).** Option (i), both files, with the tighter value rule. The allowance applies only to
  `valid_time_utc` in exactly `nbm_market_new/nbm_pit_corpus_rows.jsonl` and `pool_nbm_rows.jsonl`. It passes a
  value only when all three hold:
  - the literal class is Y26_PRE0527;
  - the local date is ≤ 2025-12-31, in the pinned registry tz (market rows) or the pinned pool station list tz
    (pool rows); an unknown or unresolvable tz is a HIT;
  - the instant is ≤ 2026-01-01T12:00Z.
  - Everything else is still a HIT. The byte side cuts the same exact spans, with remaining 0. CLARIFICATION_3.md
    ninth addendum (append-only) records the rule and the pins.

| File | sha256 |
| --- | --- |
| Runner v11, `scripts/row28_run_v11.py` (from v10 by `make_v11.py`, 15 exact replacements) | `84976be4fc7239ff90de7a3118b64f28d6336964e93a64fe7808bc819b01f0c5` |
| Sentinel v9, `scripts/test_row28_s7_sentinel_v9.py` (from v8 by `make_test_v9.py`; 44 tests, v8's 34 plus 10 for v11; pins v11) | `618ddeef32dd19341665983d44ec3fd4ff503405f701f78ab0581ed13f946d7c` |

- **Static checks.** Both files: symtable undefined names [`__file__`] only, the same as the v10 baseline; no control
  bytes; no CR. v10 and v8 are unchanged.
- **Before the rebuild (each step waits for the delta review CLEAN plus the coordinator's go):**
  1. Sentinel v9 via `workstation_heavy.ps1 -Kind pytest -Queue` with `PYTHONDONTWRITEBYTECODE=1` and
     `--basetemp C:\t\L59\row28\sentinel_bt9`. `-RepoRoot` must be OUTSIDE the worktree:
     `C:\t\L59\row28\wrapper_root`. The basetemp is deleted afterwards. The target is 44 passed.
  2. The dated pre-scan, the verify_prev binding to a6, and `run\records` = a6's 66, raw-equal 66 of 66.
  3. In the same block, immediately before the launch: `data\` holds exactly the 4 junctions, and no wrapper is
     running.
- **Rebuild launch form.** The config `stage2_build_v1.json` (`31a751a4…`) is unchanged. The OutDir is new:

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s2_build_a2 -Stage build -TimeboxSeconds 21600 `
  -RootsPath C:\t\L59\row28\run_config\stage2_build_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v11.py `
  -ExpectSha 84976be4fc7239ff90de7a3118b64f28d6336964e93a64fe7808bc819b01f0c5
```

- **Rebuild targets.** These are the 07:19 targets plus the following; any difference is a FLAG and a STOP.
  - **Pins:** `v11_pins` = {markets 11, market_tz_sha256 `5ea728ab…`, stations 300, pool_tz_sha256 `4bf76e7a…`}.
  - **Allowance:** `v11_nbm_allowance`:
    - `stage_end|nbm_market_new/nbm_pit_corpus_rows.jsonl|Y26_PRE0527|Y26-M01` = 11;
    - `writer|pool_nbm_rows.jsonl|Y26_PRE0527|Y26-M01` = about 300, measured prospectively (expected 300);
    - `stage_end|pool_nbm_rows.jsonl|Y26_PRE0527|Y26-M01` = the same count as the writer phase;
    - no other key.
  - **If the pool count is not 300, it is reported.** A HIT halts the run anyway.
  - **Bytes:** `v11_nbm_bytes`: remaining 0 and span_mismatch 0 for each phase × file, with spans_cut equal to its
    allowance count.
  - **Guard:** hits_total 0.
  - **gz header files and members: 204, not 202.** This corrects the 07:19 target "202 / 202". Build 1 HALTed at
    the `pool_nbm_rows.jsonl` write, before `stage_build`'s last two Writer outputs, `pool_noy.pkl.gz` and
    `pool_ctrl_noy.pkl.gz` (`row28_run_v11.py`, `w.pickle_gz`; gzip.compress with mtime 0, no FNAME). A full build
    therefore has 198 records + 2 junction manifests + `frame_noy_raw.pkl.gz` + `frame_inputs.pkl.gz` + those 2 =
    204 `.gz`, each with 1 member.
  - **files_scanned** is larger than build 1's 3,206: it adds `pool_nbm_rows.jsonl` and the 2 pool pickles, so it
    is reported, not targeted.
  - **Unchanged from 07:19:**
    - M1: 198 files, remaining 0, cuts {198, 198, 216}, protocols [5];
    - gz headers: fname 198, fname_own_tmp 198, fcomment 0, fextra 0, hits 0, allowance 198 / 198;
    - decision allowance 828 / 432;
    - the 198 records payload-equal to `records_build1_evidence`;
    - launcher COMPLETE, both guards 0, no FLAG;
    - junction manifest `f93c2ad2…`;
    - peak memory ≤ 12.8 GB.

## Appended 2026-11-03T07:37:21-05:00: v11 review NOT CLEAN, runner v12 and sentinel v10, rebuild launch form and targets (append only)

- **The v11 review was NOT CLEAN: 1 blocker and 4 minors.** v12 and sentinel v10 are new files; v11 and v9 are not
  edited. CLARIFICATION_3.md's tenth addendum (append-only) records them.
  - **B-1:** the v11 ruling text held a guard-range instant; the rebuild would have HALTed on its own report.
  - **m-1:** the parser tz agreement.
  - **m-2:** more sentinels.
  - **m-3:** dict rows at the line root only, the Writer row by row, and non-dict lines are HITs.
  - **m-4:** the addendum itself.

| File | sha256 |
| --- | --- |
| Runner v12, `scripts/row28_run_v12.py` (from v11 by `make_v12.py`, 9 exact replacements) | `9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b` |
| Sentinel v10, `scripts/test_row28_s7_sentinel_v10.py` (from v9 by `make_test_v10.py`; 48 tests; pins v12) | `f5d90516e587d1c2aacdf0875f70f4d2a465b12e06d1d6a3022ea73f2dda15c3` |

- **Static checks.**
  - Undefined names: [`__file__`] only, the same as the v10 baseline.
  - No control bytes, no CR.
  - The AST dated-constant pass: v11 FAILs (`RULING_V11_NBM_ROLLOVER`), as the review found. v12 PASSes: 0 of 33
    `RULING_*`. Its other dated constants are not reported as values (tenth addendum).
- **Rebuild launch form.** The config `stage2_build_v1.json` (`31a751a4…`) is unchanged. The OutDir is new. This
  supersedes the 07:27 form, which used v11:

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s2_build_a2 -Stage build -TimeboxSeconds 21600 `
  -RootsPath C:\t\L59\row28\run_config\stage2_build_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v12.py `
  -ExpectSha 9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b
```

- **Before the rebuild.** The order is the 07:27 one, with sentinel v10 (target 48 passed) and
  `--basetemp C:\t\L59\row28\sentinel_bt10`. The wrapper's `-RepoRoot C:\t\L59\row28\wrapper_root` is outside the
  worktree. Each step waits for review CLEAN plus the coordinator's go.
- **Rebuild targets** (these add to and supersede the 07:27 list; any difference is a FLAG and a STOP):
  - **`v11_pins`:**
    - markets 11, `market_tz_sha256` `5ea728ab…`, stations 300, `pool_tz_sha256` `4bf76e7a…`;
    - `registry_sha256` {`market_registry.py` `b738b286…`, `config/markets.json` `25a3db6d…`};
    - `files` = the 2 allowed names;
    - `parser_sha256` `c469229b…`, `parser_tz_agreements` {market 11, pool 0}.
  - **`v11_nbm_bytes`:** exactly 3 keys: `writer|pool_nbm_rows.jsonl`, `stage_end|pool_nbm_rows.jsonl` and
    `stage_end|nbm_market_new/nbm_pit_corpus_rows.jsonl`. Each has remaining 0, span_mismatch 0, and spans_cut equal
    to its allowance count.
  - **`v11_nbm_allowance`:**
    - market `stage_end` = 11;
    - pool `writer` count = pool `stage_end` count = each one's spans_cut; no other key.
    - **The pool count is reported, not targeted.** Build 1 refused 300. An upper bound from code and file names
      only: the block inputs are c07 (cycle 07), addon_01_00 (cycles 01 and 00), gap_c07 (07) and the L48 pool
      blocks. The runner HALTs on any duplicate (station, date, cycle) (`stage_build`), and only a 12-31 target
      rolls into 2026. So it is at most 300 × 3 cycles = 900.
  - **Report:** `report_keys_withheld_bytes` is absent, so `rulings` is not withheld. Guard hits_total 0.
  - **gz headers:** files 204, members 204; fname 198, fname_own_tmp 198, fcomment 0, fextra 0, hits 0; allowance
    198 / 198.
  - **Unchanged:**
    - M1: 198 files, remaining 0, span_mismatch 0, cuts {198, 198, 216}, protocols [5];
    - decision allowance 828 / 432;
    - the 198 records payload-equal to `records_build1_evidence`;
    - launcher COMPLETE, both guards 0, no FLAG;
    - junction manifest `f93c2ad2…`;
    - peak memory ≤ 12.8 GB.

## Appended 2026-11-03T07:45:42-05:00: the pool bound restated after the v12 review (append only)

- **The v12 review was CLEAN** (runner v12, sentinel v10, C3). It found one wording minor in the 07:38 append. That
  append's statement "at most 300 × 3 cycles = 900" is superseded by the following:
  - pool count bound = 300 × |distinct cycles across c07/addon/gap/L48 on 12-31 rows|. ≤900 holds only if the L48
    blocks carry cycles within {07,01,00}, which is not established by code. A pool count above 900 is a FLAG to
    investigate, not a STOP, since the count is reported, not targeted.
- **L48 cycle evidence, by name only.** The blocks file was not opened.
  - `C:\t\l48\corpus\receipts_nbp.jsonl` (sha256 `87a2b36f53c809b11a791f51c206990dc6ffd0cb56281d1f6841f5bca079a7c3`) has
    300 receipts. Its fields carry no cycle. Every receipt's object `key` has the one shape
    `blend.<date>/<HH>/text/blend_nbptx.t<HH>z`, and the cycle named in it is `07` in 300 of 300.
  - The L48 run log (`nbp_run.log`) header gives dates 300. This matches 300 receipts.
  - So, by the receipt names, the L48 blocks carry cycle 07 only, which lies within {07,01,00}. The 900 bound is
    therefore supported by the receipts, not by code. It remains a FLAG threshold, not a target.

## Appended 2026-11-03T07:50:51-05:00: v12 CLEAN, sentinel v10 run, rebuild pre-launch checks (append only)

- **GO (relayed).** The review found runner v12, sentinel v10 and C3 CLEAN. GO for sentinel v10, then GO for the
  rebuild using the 07:38 launch form into `run\s2_build_a2`. STOP after the build either way. Integrity waits for
  a separate go.
- **Sentinel v10.** Run through `workstation_heavy.ps1 -Kind pytest -Queue` with `-RepoRoot C:\t\L59\row28\wrapper_root`,
  `PYTHONDONTWRITEBYTECODE=1` and `--basetemp C:\t\L59\row28\sentinel_bt10`, from 07:48:14 to 07:48:16:
  **48 passed**, exit 0, stderr 0 bytes. Run scripts: `C:\t\L59\row28\sentinel_v10_run_v2.ps1`; logs in
  `sentinel_v10_logs2`.
  - **Wrapper root.** The wrapper requires that `-RepoRoot` own its exact copy. It also reads
    `config\international_live_execution_host.json`. So `wrapper_root` holds sha-equal copies of
    `scripts\ops\workstation_heavy.ps1` (`145ff745…`), `workload_admission.ps1` (`48786bcb…`),
    `windows_kill_on_close_job.ps1` (`05f362cd…`) and that tracked config (`111367a1…`).
  - **First attempt.** `sentinel_v10_run_v1.ps1` lacked the config. The wrapper refused before admission
    ("execution-host assignment is not readable exact JSON"). Nothing ran, and no basetemp was created.
  - The slot mutexes are global named mutexes, so admission still coordinates with other roots. The queue ticket
    files live under `wrapper_root\data\logs`.
  - The basetemp was deleted. The worktree's `data` still holds the same 4 entries. No new bytecode was written:
    the scripts' `__pycache__` is the earlier one.
- **Pre-launch checks** (read-only, `l59_prelaunch_a2_v1.py`):
  - **Config and dated scan.** The config sha equals `31a751a4…`. The dated scan (ISO >= 2026-01-01) finds 0 hits in
    the config's contents and path, the OutDir `s2_build_a2`, the stage, the log dir `ctl_s2a2_logs` and the
    launcher path.
    - The walker path has 1, the doc directory name, the same as in every earlier launch. The runner masks it
      (`DOC_DIR` → `GUARD_MASK_TOKEN`).
    - The forbidden roots are referenced 0 times.
  - **Pinned shas.** The walker equals `9e97c892…` and the launcher `8a2f8759…`. OutDir and log dir are absent.
  - **verify_prev binding.** `prev.controls` is a6's `walk.json`, and its sha is equal. The report is PASS (stage
    controls). The receipt `13f4d96a…` is COMPLETE, with output-guard hits 0 and no FLAG. The receipt's stage is
    controls, and its walker sha equals the report's `runner_sha256`.
  - **Records.** `run\records` holds 66 files, raw-equal to a6's `records_sha256` 66 of 66, with no other entries.
- **Launch block.** `C:\t\L59\row28\launch_s2_build_a2_v1.ps1`. It runs the data\ check (exactly the 4 named
  junctions) and the no-wrapper process check, then Start-Process with the exact 07:38 form. Nothing runs in
  between. Logs go to `ctl_s2a2_logs`, and memory is monitored by `mon_s2_v1.ps1` (STOP above 12.8 GB).

## Appended 2026-11-03T08:54:11-05:00: rebuild s2_build_a2 PASS, every target met (append only, counts and classes only)

- **Run.** Launched at 07:50:55 with the exact 07:38 form. Walker 07:50:56 → 08:53:21, about 62m25s.
  - Launcher: COMPLETE, exit 0, stderr 0 bytes. Walker exit 0, stderr 0 bytes.
  - Receipt `eb60509b0ae59398a28ba7ccedc5df2c6f9b73ddafb737fd29858554a0e5ed85`; walk.json `80c70b2f4260be0405f875f8cc01a049224fe420971936621e17ad8824070ec5`; walk.csv `26ddb688dbb076f0856bf44d56006a12757d9527818b0d2a11dfe02fae00520a`.
  - Peak job memory 5,060,091,904 bytes, under 12.8 GB. The monitor never fired.
  - No process of the run remains. The worktree `data` still holds the same 4 junctions.

| Target | Observed | Met |
| --- | --- | --- |
| Runner status / stage / runner sha | PASS / build / `9e97c892…`; launcher `8a2f8759…` | yes |
| Receipt guard, output guard, FLAG | receipt output-guard hits 0, no receipt guard hits, no FLAG; output_guard CLEAN, hits_total 0, files_with_hits 0, 3,209 files scanned, writes_withheld none, log writes withheld 0/0, post_score false | yes |
| `report_keys_withheld(_bytes)` | absent (both) | yes |
| M1 | 198 files, remaining 0, span_mismatch 0, cuts {centre 198, generated_at 198, decision 216}, protocols [5] | yes |
| Decision allowance | dated_tokens 828, values 432 | yes |
| gz headers | files 204, members 204, fname 198, fname_own_tmp 198, fcomment 0, fextra 0, hits 0; allowance 198 / 198 | yes |
| Records vs `records_build1_evidence` | 198 of 198 payload-equal, and raw-equal with the gzip mtime masked; raw bytes differ only by gzip mtime. `run\records` holds 264 = those 198 + a6's 66 controls files (66 of 66 raw-equal to a6's `records_sha256`) | yes |
| Junction manifest | the before and after files' sha `f93c2ad2…`, as before; the report's json-bytes sha is `9dff281c…` before and after, as in a6 and build 1; manifest_changed false | yes |
| `v11_pins` | markets 11, market_tz `5ea728ab…`, stations 300, pool_tz `4bf76e7a…`, registry {`market_registry.py` `b738b286…`, `config/markets.json` `25a3db6d…`}, files = the 2 allowed names, parser `c469229b…`, agreements {market 11, pool 0} | yes |
| `v11_nbm_bytes` | exactly 3 keys; each has remaining 0 and span_mismatch 0; spans_cut 11 / 300 / 300 equal to the allowance counts | yes |
| `v11_nbm_allowance` | market stage_end 11; pool writer 300 = pool stage_end 300; no other key | yes (pool reported) |

- **The allowance counts, per file × class × month bucket:**
  - `nbm_market_new/nbm_pit_corpus_rows.jsonl`, Y26_PRE0527, Y26-M01: 11 (stage_end).
  - `pool_nbm_rows.jsonl`, Y26_PRE0527, Y26-M01: 300 (writer) and 300 (stage_end).
  - The pool count, 300, is within the 900 bound; no FLAG.
- **STOP.** Integrity waits for the coordinator's go.

## Appended 2026-11-03T08:56:49-05:00: integrity (stage 3) GO, wrapper_root copies, config, pre-launch checks and exact command (append only)

- **GO (relayed, 08:54:43).** The rebuild `s2_build_a2` PASS is accepted: receipt `eb60509b…`, tip `6aa9c6c0`. The
  `wrapper_root` copies are accepted.
  - GO for integrity, outcome-blind: no label join, no label or settlement read, no score, no 390 look. STOP after
    it. Labels, look and score each need master's go.
- **`C:\t\L59\row28\wrapper_root`.** These are byte copies of tracked files at this worktree's tip. Each sha equals
  the worktree file. It is used only as the `-RepoRoot` of `workstation_heavy.ps1`, outside the worktree:

| Path under wrapper_root | sha256 |
| --- | --- |
| `scripts\ops\workstation_heavy.ps1` | `145ff7453ac44cfd563f24d9ab5852b6b3019b855c1fdeb65295f64de87b4c1e` |
| `scripts\ops\workload_admission.ps1` | `48786bcb1946ad9b02934da53d5887d8ab49f69a72750c36809bc6d7f160b441` |
| `scripts\ops\windows_kill_on_close_job.ps1` | `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669` |
| `config\international_live_execution_host.json` | `111367a167628fcd78753f341beac119f81d9b87380989a9299d165daad80a5b` |

  - The wrapper's own state is under `wrapper_root\data\logs`: 2 entries, names only.
  - The integrity stage itself runs under launcher v6, not this wrapper.
- **Config.** `C:\t\L59\row28\run_config\stage3_integrity_v1.json`, sha256
  `acf75737674239dfc00391760ad69c729fe9a3dfc73767911c52f4c9e6b89db5`. It is new, and no existing config was edited.
  It differs from `stage2_build_v1.json` only in `stage: integrity` and
  `prev = {build: {path: run\s2_build_a2\walk.json, sha256: 80c70b2f…}}`.
- **Pre-launch checks** (read-only, `l59_prelaunch_s3_v1.py`):
  - **Dated scan** (ISO >= 2026-01-01). It finds 0 in the config path, the OutDir `s3_integrity`, the stage, the
    log dir `ctl_s3_logs` and the launcher path. The walker path has 1, the doc dir name; the runner masks it, as at
    every launch.
    - The config contents had 1 raw match of the crude pattern. It lies inside the `prev.build.sha256` hex, and it
      is not a valid calendar date (0 valid). The runner's own `guard_text` and `guard_obj` on the config are
      clean.
    - The forbidden roots are referenced 0 times.
  - **verify_prev binding to s2_build_a2.**
    - The walk.json sha equals the config's. The report is PASS, stage build.
    - The receipt `eb60509b…` is COMPLETE, with output-guard hits 0, no receipt guard hits and no FLAG.
    - The receipt's stage is build, and its walker sha equals the report's `runner_sha256`.
    - `frame_inputs`, `pool_noy`, `pool_ctrl_noy` and `payload_meta` each equal their sha in the build report.
    - The junction manifest after the build is `9dff281c…` (json-bytes form).
  - Walker `9e97c892…`, launcher `8a2f8759…`. OutDir and log dir are absent.
- **Launch block** `C:\t\L59\row28\launch_s3_integrity_v1.ps1`. The data\ check (exactly the 4 named junctions)
  and the no-wrapper process check run, then Start-Process immediately, with nothing in between. Peak memory is
  monitored by `mon_s2_v1.ps1` (STOP above 12.8 GB). Timebox 7,200 s, as in the stage plan.
- **Exact command:**

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s3_integrity -Stage integrity -TimeboxSeconds 7200 `
  -RootsPath C:\t\L59\row28\run_config\stage3_integrity_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v12.py `
  -ExpectSha 9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b
```

## Appended 2026-11-03T08:58:57-05:00: integrity (stage 3) PASS, outcome-blind counts; wrapper_root manifest; integrity report committed (append only)

- **Run.** Launched at 08:56:52 with the exact form. Walker 08:56:52 → 08:57:24, about 32 s.
  - Launcher: COMPLETE, exit 0, stderr 0 bytes. Walker exit 0, stderr 0 bytes.
  - Receipt `fa5b5243494ac1bf0412ea279473b477c59767a1ebac3e7a7181a14db3189f1b`; walk.json (= the integrity report)
    `d840406447dd9d70b8f2603e32363b06daa93d5532500e478fc84032acede71e`; walk.csv
    `f78487ec93d51b1e4d1388fbfe86a56cfe5d8e540c0527b655b70c6ab9dbaabb`.
  - Peak job memory 3,169,021,952 bytes, under 12.8 GB.
  - **Guards:** output_guard CLEAN, hits 0, 4 files scanned, nothing withheld (`report_keys_withheld(_bytes)` absent),
    post_score false. Receipt guard 0, no FLAG.
  - **Junctions:** manifest `9dff281c…` before = after, manifest_changed false. Junction subdirectories read: declared
    `wunderground`, observed `training` and `wunderground`, reported as their union.
  - halted_arms none.
- **Outcome-blind counts.** No label join, label value, settlement, score or look was read.
  - **label_presence:** rows 250,245, without a label 0. This is presence only, the R6 check.
  - **kept:** n_dates 657 (frozen 660). Look dates 388 (frozen 390). Folds: 2021 61, 2022 163, 2023 164, 2024 120,
    2025 149. us10 rows 26,278; denver rows 2,612.
  - **drops:** by reason, no_built_row 120 and missing_F_or_current_temp 2. us10 dropped 122 of 26,400 market-hours
    (pooled share 0.00462); denver dropped 28.
  - **duplicate_keys** 0. **pool_empty** none.
  - **realised_population** per arm A–D, hours 13/14/15/16: 6,568 / 6,570 / 6,570 / 6,570.
  - **fill_from_normal_by_calendar_month:** month 01, market rows 0, pool rows 1,116.
  - **C-pool control:** PASS. Rows 528,503 = 528,503, identical keys, 15 columns compared, no one-sided columns.
  - **S check:** PASS. 28,890 scored and 50 synthetic rows, max-abs-diff 0.0 for both.
  - **wrap / Rule L:** deciding_differ 0 and training_differ 0 in every arm.
  - **§7 gate:** n V4 630, V5 210, V43_ref 1,250. markets_over none. It governs section 9 only. Per-market input
    statistics are in the committed report.
  - **restated:** n 657 and n_look 388, against frozen 660 and 390. The table 6.3 values are in the committed report.
- **The integrity report** is committed as `run/integrity_report.json`, a byte copy of the stage-3 walk.json. It was
  screened: 0 control bytes, 0 `0x`+40-hex, 0 secret patterns. The commit is recorded in the next append.
- **wrapper_root manifest** (master's condition (a)). Every file under `C:\t\L59\row28\wrapper_root`, with its
  sha256 and bytes. The copies are compared with their blob at master `99fff6c480efc6131d00e887ca5e43ed1fff02c1`
  (blob content hashed with sha256) and with their blob at this branch's tip `c2d98a8af33af80fa84b08d8c5b2ca29ca279837`:

| File | sha256 (bytes) | = master 99fff6c48 blob | = branch tip blob |
| --- | --- | --- | --- |
| `scripts\ops\workstation_heavy.ps1` | `145ff7453ac44cfd563f24d9ab5852b6b3019b855c1fdeb65295f64de87b4c1e` (10,890) | **no**: master blob `2393162d`, sha `acaf87e1880e7c7aacfac36cc73149286ecdb1f1ae3e8b0cdbc8e793769e037f`; not a line-ending difference | yes, blob `f8ecc677` |
| `scripts\ops\workload_admission.ps1` | `48786bcb1946ad9b02934da53d5887d8ab49f69a72750c36809bc6d7f160b441` (165,706) | **no**: master blob `2f8e5849`, sha `4f7940662726027ac4fcdd44e75b6ad5a666cb29d98972678573738ad370e636`; not a line-ending difference | yes, blob `e23b75f9` |
| `scripts\ops\windows_kill_on_close_job.ps1` | `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669` (31,571) | yes, blob `a55997db` | yes |
| `config\international_live_execution_host.json` | `111367a167628fcd78753f341beac119f81d9b87380989a9299d165daad80a5b` (491) | yes, blob `133915f1` | yes |
| `data\logs\heavy_workload.slot2.lock` (created by the wrapper) | `f45a51d1bfcda8675db04deb5efff3aeb7c2f6be00dd5cf045c20495cc39ce45` (608) | n/a | n/a |
| `data\logs\heavy_workload_queue.jsonl` (created by the wrapper) | `a6b8c74399f6ef00ef75ca5fe4ff5a9d6d50581b87895639c0c53a30dd7b0893` (1,064) | n/a | n/a |

  - Nothing else is present. The directories are `config`, `data\logs` and `scripts\ops`.
  - **Discrepancy (raised to the coordinator, not resolved here).** 2 of the 4 copies are not equal to master
    99fff6c48. Master has commits on those two files that this branch does not have, so the copies match the branch
    tip blobs. The copies are byte copies of this worktree's checkout at its tip, and sentinel v10 ran with them.
    They are left unchanged pending a ruling.

## Appended 2026-11-03T08:59:15-05:00: integrity gate commit (append only)

- **Integrity gate commit:** `95762ae89da78b831ccf5b1a340aac124dcf8b6d`, on `origin/claude/row28-yearround-history-20261102`
  (plain push).
  - Its `run/integrity_report.json` blob sha256 is `d840406447dd9d70b8f2603e32363b06daa93d5532500e478fc84032acede71e`.
    This equals the run file `run\s3_integrity\walk.json` byte for byte.
  - It is the `integrity_commit` for the labels stage.
- **STOP.** Labels, the 390 look and the score each need master's go.

## Appended 2026-11-03T09:03:56-05:00: labels GO, step 1 (wrapper_root refreshed to master) and step 2 (admission probe); HOLD before labels (append only)

- **GO (relayed).** Master accepted integrity (report `d8404064…`, gate commit `95762ae89`). n = 657 and look n = 388
  are restated values within the §5.2 caps (C2 N2), not a deviation. The earlier wrapper copies are accepted as
  disclosed for a6, the rebuild and integrity.
- **Step 1.** Two files were refreshed to master `99fff6c480efc6131d00e887ca5e43ed1fff02c1`. Each was written with
  `git cat-file -p <full blob id>` (from `git rev-parse 99fff6c48:<path>`) as raw bytes, with no EOL conversion.
  The old copies were saved in the session scratchpad first.
  - `git hash-object --no-filters` of each written file equals its master blob id.
  - **Re-pinned manifest:** every file under `C:\t\L59\row28\wrapper_root`. All 4 copies equal master `99fff6c48`.

| File | sha256 (bytes) | git blob id | Source |
| --- | --- | --- | --- |
| `scripts\ops\workstation_heavy.ps1` | `acaf87e1880e7c7aacfac36cc73149286ecdb1f1ae3e8b0cdbc8e793769e037f` (11784) | `2393162d641254998ce22525902b688445a3d606` | master blob, refreshed |
| `scripts\ops\workload_admission.ps1` | `4f7940662726027ac4fcdd44e75b6ad5a666cb29d98972678573738ad370e636` (169982) | `2f8e5849fd8d178f7f3e1f31c3760ce8b9100beb` | master blob, refreshed |
| `scripts\ops\windows_kill_on_close_job.ps1` | `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669` (31571) | `a55997db12a362bc5b408ea3e13fc898f642fe0c` | equal to master blob, unchanged |
| `config\international_live_execution_host.json` | `111367a167628fcd78753f341beac119f81d9b87380989a9299d165daad80a5b` (491) | `133915f13ad2e4eb12e9eccca70a91283b92bcbd` | equal to master blob, unchanged |

  - The wrapper's own files, by name: `data\logs\heavy_workload.slot2.lock` and `data\logs\heavy_workload_queue.jsonl`.
    Nothing else is present.
- **Step 2, the admission probe.** `C:\t\L59\row28\wrapper_probe_v1.ps1` ran master's `workstation_heavy.ps1` from
  `wrapper_root`: `-Kind pytest -Queue`, arguments `-m pytest --version -p no:cacheprovider` (no collection),
  `PYTHONDONTWRITEBYTECODE=1`.
  - Result: queued, admitted to slot 2 of 3, thread cap 10, `pytest 9.0.3`, exit 0, stderr 0 bytes.
  - Master's wrapper admits the row-28 pytest route. Logs are in `wrapper_probe_logs`.
- **HOLD before labels, with the reason.** Launcher v6 does not use `wrapper_root`.
  - It dot-sources `windows_kill_on_close_job.ps1` and `workload_admission.ps1` from `C:\wt\L59row28\scripts\ops`,
    with a sha pin on each: `05f362cd…` and `48786bcb…`.
  - `48786bcb…` is the branch version of `workload_admission.ps1`. That is the pre-refresh copy, not master's
    `4f794066…`. a6, the rebuild and integrity all ran with it.
  - So a probe "through launcher v6 with the refreshed wrapper" cannot happen without a new launcher. Running labels
    on launcher v6 as it stands would use the old admission helper.
  - This is raised to the coordinator for a ruling. The labels stage has not been launched.

## Appended 2026-11-03T09:06:13-05:00: labels (stage 4) GO under ruling (A), the 48786bcb disclosure, config, pre-launch checks and exact command (append only)

- **Master ruling (A), relayed.** Run labels on launcher v6 unchanged: `8a2f8759…`, admission helper pinned to the
  branch's `48786bcb…`. That pin is disclosed in CLARIFICATION_3.md's twelfth addendum.
  - The master-wrapper probe of the 09:03:56 append passed: slot 2 of 3, exit 0.
  - Under C1 N7, consistency HALTs only. No score, no look.
- **Config.** `C:\t\L59\row28\run_config\stage4_labels_v1.json`, sha256
  `b038ed36375bd4235874fd2e9f7892292a6c668e6087959dde05bb96e5044044`. It is new. Compared with
  `stage3_integrity_v1.json`, it has `stage: labels`, `prev = {integrity: s3_integrity walk.json d8404064…, build:
  s2_build_a2 walk.json 80c70b2f…}` (`stage_labels` verifies both) and `integrity_commit`
  `95762ae89da78b831ccf5b1a340aac124dcf8b6d`.
- **Pre-launch checks** (read-only, `l59_prelaunch_s4_v1.py`):
  - **Dated scan.** 0 hits in the config path, the OutDir `s4_labels`, the stage, the log dir `ctl_s4_logs` and the
    launcher path. The walker path has 1, the masked doc dir name.
    - The config contents have 1 raw match, again inside the `prev.build` sha hex, and 0 valid calendar dates. The
      runner's `guard_text` and `guard_obj` on the config are clean.
    - The forbidden roots are referenced 0 times.
  - **The integrity binding.** The walk sha `d8404064…` equals the config's. The report is PASS, stage integrity.
    The receipt `fa5b5243…` is COMPLETE, with guard 0 and no FLAG; its stage and walker sha are bound.
  - **The gate commit.** `95762ae89` is on origin, and its `run/integrity_report.json` blob equals the run file.
  - **The build binding.** It is as before (receipt `eb60509b…`); the 4 build outputs are sha-equal, and all 264
    records equal the build's `records_sha256`.
  - **Junctions.** The manifest after integrity is `9dff281c…`.
  - Walker `9e97c892…`, launcher `8a2f8759…`. OutDir and log dir are absent.
- **Launch block** `C:\t\L59\row28\launch_s4_labels_v1.ps1`. The data\ check (exactly the 4 named junctions) and
  the 0-wrapper check run, then Start-Process immediately, with nothing in between. The 12.8 GB monitor runs.
- **Exact command:**

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s4_labels -Stage labels -TimeboxSeconds 7200 `
  -RootsPath C:\t\L59\row28\run_config\stage4_labels_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v12.py `
  -ExpectSha 9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b
```

## Appended 2026-11-03T09:20:47-05:00: labels (stage 4) PASS, consistency only (append only, counts only)

- **Run.** Launched at 09:06:23 with the exact form. Walker 09:06:24 → 09:20:01, about 13m37s.
  - Launcher: COMPLETE, exit 0, stderr 0 bytes. Walker exit 0, stderr 0 bytes.
  - Receipt `d38235a33a3efbc0b288129feda974ecf8011104daffc3fbb096dcc1d60b65cb`; walk.json
    `0f019343316f4e37a4acd543faf77b3cae54aca70d54ea96ab48615f91e73363`; walk.csv `68d3da1b028d1da18c5883b496c77eeebce9d9eff43300c7bd5c0399ae79a496`.
  - Peak job memory 4,034,621,440 bytes, under 12.8 GB.
  - **Guards:** output_guard CLEAN, hits 0, 4 files scanned, nothing withheld (`report_keys_withheld(_bytes)`
    absent), post_score false. Receipt guard 0, no FLAG.
- **The report.** Status PASS. No HALT; halted_arms none.
  - **integrity_gate:** commit `95762ae89…`, `run/integrity_report.json` sha `d8404064…`, verified.
  - **y_free_parity:** PASS. Rows 250,245 = 250,245, identical keys, no one-sided columns, max-abs-diff 0.0 in all
    16 compared columns.
  - **pool_label_counts:** label_complete 1,908,436; label_incomplete 31,660.
  - **Per fold and per arm.** The runner reports label_complete only as the pooled total above, not per fold or per
    arm. The per-arm × hour realised population and the per-fold kept dates are in the integrity report.
- **Junction manifest diff.** `9dff281c…` before = after, changed false, count 0, empty in all 4 subdirectories.
  83,937 files. Subdirectories read: declared all 4; observed `training`.
- Labels' outputs (`market_frame_y`, `pool_frame_y`) stay under the run root and were not opened. No score and no
  look were run.
- **The report file** is committed as `run/labels_report.json`, a byte copy of the stage-4 walk.json. It was
  screened: 0 control bytes, 0 `0x`+40-hex, 0 secret patterns.
- **Restated values, copied verbatim from the integrity report** (`d8404064…`, key `restated`): §6.3 MDE80, power
  and futility, and the §8.4 thresholds at n = 657 / look n = 388.

```json
{
 "formulas": "SE = 1.07*sigma/sqrt(n); MDE80 = 3.340*SE; power = Phi(0.0057/SE - 2.498); futility false-stop = 1 - Phi(0.00285/(sigma/sqrt(n_look))); sigma_hat thresholds = SE_thr*sqrt(n)/1.07",
 "frozen_n": 660,
 "frozen_n_look": 390,
 "n": 657,
 "n_look": 388,
 "table_6_3": {
  "2x_sigma_eff": {
   "futility_false_stop_look": 0.06685749184161882,
   "mde80_x1.07": 0.005219506312646536,
   "power_at_edge_x1.07": 0.8748191734615414,
   "sigma": 0.03743534737586924
  },
  "3x_sigma_eff": {
   "futility_false_stop_look": 0.158717880574344,
   "mde80_x1.07": 0.007829259468969806,
   "power_at_edge_x1.07": 0.4735486330957824,
   "sigma": 0.05615302106380386
  },
  "4x_sigma_eff": {
   "futility_false_stop_look": 0.22668580415529727,
   "mde80_x1.07": 0.010439012625293072,
   "power_at_edge_x1.07": 0.25007164831361484,
   "sigma": 0.07487069475173848
  },
  "sigma_dec": {
   "futility_false_stop_look": 0.009665032898956039,
   "mde80_x1.07": 0.003346253214796251,
   "power_at_edge_x1.07": 0.9992919477013618,
   "sigma": 0.024
  },
  "sigma_eff": {
   "futility_false_stop_look": 0.0013533427369343265,
   "mde80_x1.07": 0.002609753156323268,
   "power_at_edge_x1.07": 0.9999991944720932,
   "sigma": 0.01871767368793462
  }
 },
 "thresholds_8_4": {
  "se_wide_rule16": 0.0022818254603682946,
  "se_wide_xa_adequate": 0.0020342612419700216,
  "se_wide_xs_adequate": 0.0017065868263473052,
  "sigma_hat_rule16": {
   "sigma_hat": 0.054661472746395164,
   "x_sigma_eff": 2.9203133710803955
  },
  "sigma_hat_xa_adequate": {
   "sigma_hat": 0.04873103458975558,
   "x_sigma_eff": 2.6034770881366267
  },
  "sigma_hat_xs_adequate": {
   "sigma_hat": 0.040881544586974586,
   "x_sigma_eff": 2.184114611065517
  }
 }
}
```

- **STOP.** The look and the score each need master's go.

## Appended 2026-11-03T09:23:28-05:00: labels accepted; the post-push screen deviation; look (stage 5) GO, config, pre-launch checks and exact command (append only)

- **Labels accepted (relayed).** Receipt `d38235a3…`, report `0f019343…`, commit `b129f39ee`. No per-fold or
  per-arm label reader is built.
- **Deviation, accepted as disclosed.** At the labels commit, `run/labels_report.json` was screened just after the
  push, not before it. A shell quoting error had swallowed the pre-push screen line. The screen found 0 control bytes,
  0 `0x`+40-hex and 0 secret patterns. The RUN_LOG append text was screened before the push.
- **GO for the look on folds 2021–23, relayed.** Under C1 F1 and C2 N2 as frozen, at n_look 388.
  - No 2024–25 score. STOP either way: after a futility stop no score of any kind; after CONTINUE the score needs a
    separate go.
  - The look file is committed and pushed, screened BEFORE the push, before anything else is computed.
- **Config.** `C:\t\L59\row28\run_config\stage5_look_v1.json`, sha256
  `4940bb150bd754d85a1731b659d75a0e5d120770f2558f98f4747bfbee554335`. It is new. Compared with
  `stage4_labels_v1.json`, it has `stage: look` and
  `prev = {integrity d8404064…, labels 0f019343…, build 80c70b2f…}`; `load_scoring_inputs` verifies all three.
- **Pre-launch checks** (read-only, `l59_prelaunch_s5_v1.py`):
  - **Dated scan.** 0 hits in the config path, the OutDir `s5_look`, the stage, the log dir `ctl_s5_logs` and the
    launcher path. The walker path has 1, the masked doc dir name.
    - The config contents have 1 raw match, in a prev sha hex, with 0 valid calendar dates. The runner's guard on the
      config is clean.
    - The forbidden roots are referenced 0 times.
  - **The three prev bindings.** Each walk sha equals the config's, and each report is PASS. Each receipt is
    COMPLETE, with guard 0 and no FLAG, and its stage and walker sha are bound:
    - integrity `fa5b5243…`;
    - labels `d38235a3…`;
    - build `eb60509b…`.
    - Junction manifest after each: `9dff281c…`.
  - **Outputs unchanged.** The integrity outputs `kept_rows` and `s_dist`, and the labels outputs, equal their
    reported shas.
  - **No scored rows yet.** There are no `look_rows.jsonl` or `final_rows.jsonl` files under the run root.
  - **The look set.** The integrity-committed kept dates of folds 2021–23 are 388, equal to the restated n_look 388.
    halted_arms is empty in both integrity and labels.
  - The runner itself re-checks the look set and runs `precheck_folds` before any fit.
- **Launch block** `C:\t\L59\row28\launch_s5_look_v1.ps1`. The data\ check (exactly the 4 named junctions) and the
  0-wrapper check run, then Start-Process immediately. Launcher v6 is unchanged (`8a2f8759…`). Timebox 14,400 s, as
  in the stage plan. The 12.8 GB monitor runs.
- **Exact command:**

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s5_look -Stage look -TimeboxSeconds 14400 `
  -RootsPath C:\t\L59\row28\run_config\stage5_look_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v12.py `
  -ExpectSha 9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b
```

## Appended 2026-11-03T11:19:02-05:00: look (stage 5, folds 2021–23) PASS; look gate commit; decision CONTINUE (append only)

- **Launch.**
  - **First block refused.** `launch_s5_look_v1.ps1` ran at about 09:23. Its 0-wrapper check found 1 wrapper: another
    lane's `workstation_heavy.ps1 -Kind pytest` from `C:\wt\L56i343s`, started 09:23:07, not this lane's. The block
    threw before Start-Process. Nothing was launched, and that process was not touched.
    - The only trace is the empty log dir `ctl_s5_logs`, created before the check.
  - **Wait, then v2.** The lane waited until no wrapper was running (09:36:07). Then `launch_s5_look_v2.ps1` ran: the
    same block, with log dir `ctl_s5_logs2`. Checks: 4 junctions, 0 wrappers. Launched at 09:36:12.
- **Run.** Walker 09:36:13 → 11:17:35, about 1h41m22s.
  - Launcher: COMPLETE, exit 0, stderr 0 bytes. Walker exit 0, stderr 0 bytes.
  - Receipt `4ded26dcc6444d932f9d9f1ada92c0b9f2fadb3baa0ae7c5fe2dd4e6315955cc`; walk.csv
    `92eb1035152b29a2fdc96e8e49d110518581771543a79425994bcdb77db079f1`.
  - Peak job memory 6,778,474,496 bytes, under 12.8 GB.
  - **Guards:** output_guard CLEAN, hits 0, nothing withheld. Receipt guard 0, no FLAG. post_score_flags none; no
    INPUT-CHANGED.
- **Look gate commit.** `774abff81770dcf5601ac05b78b3d64b17b4b25d` holds `run/look_result.json`, a byte copy of the
  stage-5 walk.json, sha `9611df778250d2fa98001617c965eb9597014a02dd8122fd8b20dd450e677996`.
  - It was committed and pushed before anything else was computed. It was screened BEFORE the push: 0 control
    bytes, 0 `0x`+40-hex, 0 secret patterns.
  - `look_rows.jsonl` (`449d392a…`) stays under the run root and is not committed.
- **Pre-checks inside the runner.** The look set equals the integrity-committed 2021–23 kept dates, 388 = restated
  n_look 388. `precheck_folds` ran before any fit. Neither HALTed.
- **The frozen look statistic.** The X−S point per arm, the §8.1 rule's input:

| Arm | point | SE (wide) | ci95_wide | n | futile |
| --- | --- | --- | --- | --- | --- |
| A | -0.12424491518960121 | 0.004685544035247309 | [-0.13342858149868594, -0.11506124888051648] | 388 | false |
| B | -0.12410610367189523 | 0.004799869723069305 | [-0.13351384832911106, -0.1146983590146794] | 388 | false |
| C | -0.12882419382294194 | 0.004342112803524636 | [-0.13733473491785023, -0.12031365272803365] | 388 | false |
| D | -0.046682886068521355 | 0.01410210525250969 | [-0.07432301236344035, -0.019042759773602362] | 388 | false |

  - The other per-arm fields (κ, κ_block3, blocks 131, pairs 380, power information) are in the committed file.
- **Decision, as the frozen rule computes it.** Prereg §8.1 rule: "Each arm whose point is > **−0.00285** ... is
  stopped as FUTILE." No arm's point is > −0.00285, so no arm is stopped as FUTILE.
  - §8.1, "After the look": "There is no efficacy stopping, and survivors continue to all folds."
  - **Decision: CONTINUE** for arms A, B, C and D.
- **Realised n per arm.** 388 dates each (A, B, C, D). No arm HALTED or INCOMPLETE.
- **Descriptive fields.**
  - `first_390_equal_look_folds_descriptive` false: the restated look set is 388, not the frozen 390 (C2 N2).
  - The top-bucket counts are all 0.
- **Junction manifest.** At stage end, `9dff281c…` before = after, changed false, count 0, empty in all 4
  subdirectories, 83,937 files. Subdirectories read: declared `wunderground`, observed `training` and `wunderground`.
- **Archive.** The 5 receipts were COPIED, not moved, to `C:\archive\ruled-out\row28-yearround-history-2026-11-02`, each
  sha-equal to its source:
  - controls a6 `13f4d96a…`;
  - build a2 `eb60509b…`;
  - integrity `fa5b5243…`;
  - labels `d38235a3…`;
  - look `4ded26dc…`.
  - The result is not a stop, so no INDEX.md line was written.
- **STOP.** No 2024–25 score was computed. The score needs master's separate go.

## Appended 2026-11-03T11:21:15-05:00: look accepted; score (stage 6) GO, config, pre-launch checks and exact command (append only)

- **Look accepted (relayed).** Master accepted CONTINUE for all 4 arms. The refused first launch block is accepted as
  disclosed.
- **Score GO (relayed).** All folds, the deciding analysis, exactly as frozen with C1/C2/C3, on launcher v6
  unchanged.
  - **Manifest rule.** Master's stage-end manifest rule: an mtime-only change is noted and the result stands. A size
    change, or a file added or removed, in a subdirectory the stage read makes the arms INPUT-CHANGED, and the run
    STOPs to the coordinator before any verdict is recorded.
  - **Wrapper wait.** L56's chunked suite holds the wrapper. This lane re-runs its launch block as a new vN, no more
    often than every 2 minutes, once that suite has exited.
- **Config.** `C:\t\L59\row28\run_config\stage6_score_v1.json`, sha256
  `8285bd50db328641b6cd640fa2c8b24b1e73fa23c06edcf26d97e8c73a33a431`. It is new. Compared with
  `stage5_look_v1.json`, it has `stage: score`, adds `prev.look` = s5_look walk.json `9611df77…`, and adds
  `look_commit` `774abff81770dcf5601ac05b78b3d64b17b4b25d`.
- **Pre-launch checks** (read-only, `l59_prelaunch_s6_v1.py`):
  - **Dated scan.** Clean, as before: the config's single raw match is inside a sha hex (0 valid dates), and the
    runner's guard on the config is clean. The walker path's 1 hit is the masked doc dir name.
  - **The four prev bindings.** Each walk sha equals the config's, and each report is PASS. Each receipt is
    COMPLETE, with guard 0 and no FLAG, and its stage and walker sha are bound:
    - integrity `fa5b5243…`;
    - labels `d38235a3…`;
    - build `eb60509b…`;
    - look `4ded26dc…`.
    - Junction manifest after each: `9dff281c…`.
  - **The two gate commits.** `95762ae89` and `774abff81` are both on origin, and each blob equals its run file.
  - **Rows under the run root.** The look rows equal `look_rows_sha256`. They are the only `look_rows.jsonl`, and
    there are 0 `final_rows.jsonl`.
  - **Look result.** futile is false for A, B, C and D.
  - **The n inputs.** Restated n 657 = kept n_dates 657 = the kept list's 657. The runner re-checks n and runs
    `precheck_folds` before any fit.
- **Launch block** `C:\t\L59\row28\launch_s6_score_v1.ps1` (and any later vN). The data\ check (exactly the 4 named
  junctions) and the 0-wrapper check run, then Start-Process immediately. Timebox 21,600 s, as in the stage plan.
  The 12.8 GB monitor runs.
- **Exact command:**

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\t\L59\row28\run_row28_guarded_v6.ps1 `
  -OutDir C:\t\L59\row28\run\s6_score -Stage score -TimeboxSeconds 21600 `
  -RootsPath C:\t\L59\row28\run_config\stage6_score_v1.json `
  -WalkerPath C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v12.py `
  -ExpectSha 9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b
```

## Appended 2026-11-03T13:27:39-05:00: score (stage 6, all folds) PASS; outcomes per prereg §8.2 (append only)

- **Launch.**
  - **Hold.** The lane held while L56's suite held the wrapper (from 11:23), and then on the coordinator's hold.
  - **GO.** The coordinator relayed that L56's driver had ended (12:26:26; checked at 12:27:00). The lane's
    2-consecutive-clear-polls backup also passed at 12:29:51.
  - **Block.** `launch_s6_score_v1.ps1`, its first run: 4 junctions and 0 wrappers. Launched at 12:30:00.
- **Run.** Walker 12:30:01 → 13:25:36, about 55m35s.
  - Launcher: COMPLETE, exit 0, stderr 0 bytes. Walker exit 0, stderr 0 bytes.
  - Receipt `50cdadd1c028a55e04d307cf4c67298de889a912f180ded37af5c1edc1745430`.
  - Peak job memory 4,926,054,400 bytes, under 12.8 GB.
  - **Guards:** output_guard CLEAN, hits 0, nothing withheld. Receipt guard 0, no FLAG.
  - **Flags:** post_score_flags none, no ERROR.
- **Commit `741174e5f154e94ab4a9ed7b1d679cf8a952e7a4`** (screened BEFORE the push: 0 control bytes, 0 `0x`+40-hex, 0
  secret patterns):
  - `run/score_result.json`, a byte copy of the stage-6 walk.json:
    `32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b`.
  - `run/score_receipt.json`: the receipt. Git's `text=auto eol=lf` normalised its CRLF to LF, so the blob is
    `d376961378957e29…`, which equals the CRLF-stripped file. The run file sha is `50cdadd1…`.
  - `final_rows.jsonl` stays under the run root.
- **Start-of-stage checks.** C2 n: the kept rows equal the integrity-committed list, restated n 657. The look rows
  cover exactly the 2021–23 kept dates. `precheck_folds` ran before any fit. None HALTed.
- **Stage-end manifest.** `9dff281c…` before = after, changed false, count 0, empty in all 4 subdirectories, 83,937
  files. Nothing changed (mtime, size, add or remove), so no arm is INPUT-CHANGED.
- **The frozen deciding statistics** (X−S pooled, n = 657 dates per arm; decisions use ci95_wide):

| Arm | X−S point | ci95_wide | Holm p (threshold, rejected) | outcome (§8.2) |
| --- | --- | --- | --- | --- |
| A | -0.1361435077084128 | [-0.14375306511527866, -0.12853395030154693] | 0.0 (0.0125, yes) | SURVIVES-history |
| B | -0.1368376830046977 | [-0.1445342466657366, -0.1291411193436588] | 0.0 (0.016666666666666666, yes) | SURVIVES-history |
| C | -0.1412025733154026 | [-0.1484956683891957, -0.13390947824160948] | 0.0 (0.025, yes) | KILL |
| D | -0.07570473125571656 | [-0.09440552904878349, -0.05700393346264962] | 2.220446049250313e-15 (0.05, yes) | KILL |

  - **The X−A gate** (C and D):
    - C−A point -0.005059065606989814, ci95_wide [-0.0068501141023500686, -0.003268017111629559];
    - D−A point 0.060438776452696234, ci95_wide [0.04529227712823671, 0.07558527577715575].
  - **The conditions the runner recorded for each verdict:**
    - C, crossing: "a per-market X-A 95% lower bound (wide) > 0".
    - D, crossing: "a per-market X-S 95% CI (wide) lies above 0", "X-A point >= -0.0005" and "a per-market X-A 95%
      lower bound (wide) > 0". D, failure-to-show X−A: "X-A wide 95% upper bound >= 0" and "more than 1 of 5 folds
      have X-A d > 0".
    - A and B: no crossing and no failure-to-show conditions.
  - **§8.2 wording.** KILL is "(a true kill). Any one of the *crossing* conditions, at any power". SURVIVES-history
    is "Everything else. Survival is V4-scoped and is not an adoption."
  - **Realised power, §8.4** (the X−S rule-16 band is "< 0.50 (rule-16 failure flagged)" for every arm):
    - A: power_xs 0.13010525363167047;
    - B: power_xs 0.12685075883348407;
    - C: power_xs 0.14313154819437646, power_xa 0.999945496113139;
    - D: power_xs 0.026209595189528923, power_xa 0.10192521116294162.
  - **§8.3 selection** (the runner's output): survivors [A, B], passing G [A, B], candidate B. G: A -0.03027736205541938,
    B -0.0306235477424221.
  - **Pre-stated descriptive outputs:** top-bucket y > top: S 1; A, B and C 0. `not_implemented_descriptive`:
    S_bound, hours 07–12 vs the L6 stack, fold 2026 / V5.0.
- **Archive.** The score receipt was copied to `C:\archive\ruled-out\row28-yearround-history-2026-11-02\receipt_s6_score.json`
  (sha-equal, `50cdadd1…`).
  - **INDEX.md.** Two CRLF lines were appended to `C:\archive\ruled-out\INDEX.md`, one for KILL arm C and one for KILL
    arm D, each with the result sha. The prior bytes are unchanged.
  - **Correction.** My first append wrote a literal backslash-r instead of CR, and I replaced it at once. Only those
    2 just-written lines were rewritten, with exact CRLF bytes. The prefix was verified equal.
- **STOP.**

## Appended 2026-11-03T13:41:48-05:00: INDEX.md second correction accepted; root cause; standing rule (append only)

- **Second correction (accepted by master 2026-11-03).** After the first correction, the 2 row-28 KILL lines in
  `C:\archive\ruled-out\INDEX.md` still held control bytes in the receipts path: BEL (0x07) and CR (0x0D) where the
  backslashes before `archive`, `ruled-out` and `row28-yearround-history-2026-11-02` should be. At 13:33 EST only those
  2 path strings were replaced, by bytes, with the literal path. The prefix is byte-identical to the backup taken before
  row 28 (366,242 bytes); the tail is 2 CRLF lines with no control bytes; new file sha256
  `f5f49b3bb414292066c7745921086a6e96124f5b3f33ce75eab92626553b1780`.
- **Root cause.** Backslash paths passed through an escape-interpreting write: `\a` became BEL and `\r` became CR.
  The first correction fixed the line endings only and did not re-check the whole tail for control bytes.
- **Standing rule (master, 2026-11-03).** INDEX appends write bytes from a file, verify the tail bytes, and contain no
  control bytes.
