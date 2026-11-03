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
