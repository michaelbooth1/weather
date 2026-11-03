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
