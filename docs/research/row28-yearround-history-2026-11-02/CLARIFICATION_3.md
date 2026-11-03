# Row 28 — Clarification 3 (2026-11-03, before any control)

This clarification records master's rulings on the three v3 calls and on the v3 delta review (F1–F9), as relayed by
the coordinator on 2026-11-03. It is committed before the controls stage. It amends nothing in the prereg
(`cb6d4e8d…`), the freeze record, Clarification 1 or Clarification 2, except where it says it supersedes Clarification
2's global centre-label allowlist. Runner v4, launcher v4 and sentinel test v2 implement it; their sha256 values are
in `RUN_LOG.md`.

## 1. Launcher v4 deltas

Launcher v4 is launcher v3 (`fb039782…`) plus the following, and nothing else.

- **F3 (h), log token rule.** The log guard (G1) masks the prereg folder-name token. It also masks the exact token
  `centre=<label>` when the label is in the arm centre set. Nothing else is masked. The rule is identical to runner
  v4's `GuardedStream` (`LOG_CENTRE_TOKEN`). The launcher carries the 24 labels, and they must hash to
  `GUARD_CENTRE_SET_SHA256` (`38a17ec2…`, the sha256 of the ordinally sorted labels joined by LF). If they do not,
  the launcher refuses before any child starts. The receipt guard (G2) has no centre exception.
- **F4.** A receipt that G2 withholds is replaced by a minimal receipt that records `receipt_guard_hits`. Runner v4's
  `verify_prev` refuses a previous stage unless its receipt has status `COMPLETE`, `output_guard.hits_total == 0`,
  no `receipt_guard_hits` and no `output_guard_flag`.
- **F6.** In look and score, a withheld receipt keeps the stage status and adds `output_guard_flag`. It is a FLAG, not
  a HALT.
- **F7, reverted.** The receipt's `exception` string is back to the v2 text, as Clarification 2 §5 requires. That
  text contains a 2026 date, so G2 masks exactly that one string before it counts.

## 2. The F2 allowlisted path and its pins

Exactly one key path is allowlisted: `["calibrated_weights"]["metadata"]["generated_at"]`, in `records_*.pkl.gz`
files only.

- **Source of the value.** `pooled_residual_model.py` line 249 copies `model.calibrated_weights` into each payload.
  `src/weather/model/toronto_model.py` lines 145 and 227–238 load it from
  `artifacts/calibration/calibrated_weights{suffix}.json`, where it sits at line 1147 of each file.
- **Allowed values.** The value must be one of the 12 pinned values (`CALIBRATED_WEIGHTS_PINS` in runner v4). The 12
  values differ by file: each is a build time on 2026-06-07 between 22:05:46 and 22:15:56.
- **File check.** Every stage verifies the 12 files' sha256 values and their `generated_at` values before it starts.
  A mismatch HALTs.
- **Everything else stays strict.** Any other time string in a records file still HALTs before scoring, including
  the marine, reanalysis and forecast-profile spreads.

## 3. F9: HALTs inside `score_folds`

`post_score` stays where v3 sets it, after `score_folds` returns. Inside `score_folds` the following holds.

- **What may HALT.** Only the checks in `SCORE_FOLDS_HALT_CHECKS` may HALT:
  - SF1: k112_inputs finds a duplicate (market, 07Z) key in the D-arm input;
  - SF2: a fold/hour has a different number of built rows than kept rows. This cannot happen after precheck_folds.
- **What a HALT may carry.** Its message, log line and receipt carry only the code. No score, loss, Brier,
  probability or label value may appear.
- **Any other exception.** It becomes an ERROR that carries only the exception type name.
- **Partial results.** In-memory partial results are discarded. They are never written or logged.
- **Repair.** A repair after such a HALT must be a reviewed, committed amendment, made before any re-run and recorded
  in `RUN_LOG.md` with the HALT code.

## 4. F3 scoping rules

The output guard is a path-aware structural walk over the outputs: JSON, JSONL, CSV and pickle. Clarification 2's
global centre-label allowlist is withdrawn. A date on or after 2026-01-01 is a hit everywhere except in the
following cases.

- **Centre label as a value.** It passes as the whole value of a centre field and must be in the arm centre set.
  - The centre fields are `centre`, `payload_centre`, `rule_l_2024_02_29` and any field ending in `_centre`.
  - The same label in free text, in a non-centre field or as any other dict key is a hit.
- **Centre label as a key.** It passes as a whole dict key only directly under `by_centre`. Centre-keyed report dicts
  are now lists of `{"centre": …}`.
- **§7 constants.** A §7 constant passes as the whole value of `cap` inside the `v5_gate_section7` subtree.
- **The F2 path.** It passes as set out in §2.
- **Record names.** `records_<R0 market>_<arm centre>.pkl.gz` passes in three places:
  - under the configured `records_root`;
  - as the whole value of `file`;
  - as a key directly under `records_sha256`.
- **Logs.** Logs follow the token rule in §1.
- **HALT texts.** HALT messages use `centre#<index>` and `name#<hash>`, never a label or a record name.
- **Byte cross-check.** Each structured file's raw-byte date count may not exceed the count the walk accounted for.
  Any excess is a hit.
- **Walk references.** The walk keeps every object it visits alive, which fixes F1.
- **After a score exists.** A hit withholds the output, and the stage's arms become INCOMPLETE. No verdict and no
  futility decision is recorded until master rules (ruling 1, F5).
- **No unscopable output type.** Every output type could be scoped.
  - Outputs that are not structured (no JSON, JSONL, CSV or pickle) get only the masks.
  - The reviewer preferred hashing record paths. The exact record-name rule was used instead, because the
    `records_sha256` names are reused to open the files (runner v4 `stage_labels`) and the `outputs_sha256` keys are
    used for lookups.

## Addendum (2026-11-03, before any control): the v4 delta review

Master accepted the four v4 disclosures and required v5. Runner v5, launcher v5 and sentinel test v3 implement this
addendum; their sha256 values are in `RUN_LOG.md`.

- **§1 F7, the masked string, verbatim (G6).** Launcher v4 and v5 mask exactly this receipt `exception` string, and
  nothing else, before G2 counts:
  "one-off exception to workstation_heavy admission, master ruling 2026-11-02, read-only metadata walk".
- **G1, nothing withheld is ever written.** The Writer serialises each output first. Before anything is written it
  runs the structural walk and the byte cross-check on the serialised (uncompressed) bytes. A hit HALTs before a score
  exists, and after a score it withholds the output, which is never on disk. The walk also covers every categorical
  category, used or not (Series, Index, CategoricalIndex, DataFrame columns).
- **G2.** `verify_prev` also requires `receipt.stage` to equal the stage name and `receipt.walker_sha256` to equal the
  report's `runner_sha256`.
- **G3.** In a records file, `generated_at` passes only if it equals the pinned value of
  `calibrated_weights_<payload market>.json`. That is the file `toronto_model.load_calibrated_weights` opens, because
  `MarketSpec.artifact_suffix` is `_<id>` for every R0 market (`market_registry.py` 78-80). If no mapping exists, it is a hit.
- **G4.** Every stage's receipt records `job_memory.peak_job_memory_bytes`, on the success path and the timebox path.
  Launcher v5 also copies it, after guarding it, into the minimal receipt that replaces a guarded receipt.
- **G5, score_folds stays in-process.** The fits inside `score_folds` are `pooled_residual_model.fit_pooled`, which
  uses sklearn `HistGradientBoostingRegressor` with `MEAN_HGB_PARAMS` and `SCALE_HGB_PARAMS` and no `n_jobs`.
  - HGB parallelises with OpenMP threads inside the process. `pooled_residual_model.py` 48-50 caps
    `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` at 10 when it is imported.
  - None of `pooled_residual_model`, the R-P2 module copy, or the parts of `feature_model` that `score_folds` calls
    (`smoothed_dist`, `brier_score`, `log_loss`) uses joblib, multiprocessing, concurrent.futures or subprocess.
  - The runner's only subprocess is `git` in `verify_committed_gate`, which runs at stage start, outside `score_folds`.
  - No child process can be spawned inside `score_folds`, so no extra pin was needed.
- **Item 9, required.**
  - `set_guard_centres` asserts that B's centre set is non-empty and lies within A's, and that the arm union equals A.
  - A field whose name starts with `B_` and contains `centre` is checked against B's centre set.
  - No written output carries an arm-specific centre today. Every centre field holds a label of A's set, and B's
    labels are a subset of A's by code (`B = JAN_JUL[:10] + 2026-12-24`, `A = FORWARD + JAN_JUL + 2026-12-24`).

## Second addendum (2026-11-03, before any control): the v5 review

Runner v6 and sentinel test v4 implement this addendum. Launcher v5 is unchanged. Their sha256 values are in
`RUN_LOG.md`.

- **G5, corrected (H4).** The first addendum said the pools are "capped at 10" by `pooled_residual_model.py` 48-50.
  That was not assured. Those lines use `os.environ.setdefault`, so an inherited value wins, and `feature_model` and
  sklearn can be imported before `pooled_residual_model`.
  - Runner v6 therefore sets `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` to 10. It does so as the
    first statements after the module docstring, before numpy, sklearn or any bound module is imported, and it
    overrides any inherited value (`RULING_V6_THREADS = 10`).
  - The rest of G5 stands. The fits inside `score_folds` run in-process threads only. No child process is spawned
    there.
- **H2 (ruling 1).** The stage report (`walk.json`) is now checked the same way as every Writer output before it is
  written: the structural walk plus the byte cross-check of its exact serialisation (`guard_report`).
  - On a hit, the offending top-level keys are withheld.
  - Before a score exists, the stage HALTs.
  - After a score exists, the arms become INCOMPLETE.
  - If the report still hits (for example, a dated key), only a minimal report is written: the runner, its sha256,
    the stage, the status and counts.
  - The output-guard block records its start date in basic format (`20260101`), so the report carries no dated
    string of its own.
- **H1 (sentinel).** B's centre set holds one sealed label, `2026-12-24`. The other ten labels lie before 2026-05-27.
  Sentinel v4 tests both kinds of label.

## Third addendum (2026-11-03T04:50-05:00, before any control): controls attempt 1, launcher v6 and the smoke

Master accepted launcher v6 and the OutDir `run\s1_controls_a2`, as relayed by the coordinator. The relaunch counts
as the same attempt. The sha256 values are in `RUN_LOG.md`.

- **Attempt 1.** Controls attempt 1 (launcher v5, runner v6) HALTed with exit 6. No control was computed. Two
  causes:
  - **R4.** The runner refused in run scope because `C:\wt\L59row28\data` held `logs`. The stage-0 wrapper had
    created it.
  - **G2 self-hit.** Launcher v5's receipt carried `output_guard.from = "2026-01-01"`, which matches the guard
    pattern. Every v5 receipt therefore counted at least 1 hit and was replaced by the minimal HALT receipt.

  The folder `run\s1_controls` stays in place, untouched, as evidence. `data\logs` was moved (not deleted) to
  `C:\t\L59\row28\sentinel_wrapper_logs\` under master's pre-approval.
- **Launcher v6 delta (K1).** v6 is v5 plus one change, and nothing else. The receipt writes `output_guard.from` as
  `$GuardFrom.Replace("-", "")`, which is `20260101`, the same basic format runner v6 writes in walk.json. There is
  no field mask.
  - `$GuardFrom` itself stays `2026-01-01`. It is the bound of the guard's ordinal comparison (`CompareOrdinal(match,
    $GuardFrom) -ge 0`).
  - Setting `$GuardFrom = "20260101"` would have disabled the guard for every 2026 date: `-` sorts before `0`, so
    `"2026-01-08" < "20260101"`.
  - The other v6 changes are header comment lines only.
- **Sweep: guard-matching constants that land in a receipt, report or log.** v6 line numbers below.
  - **Hits on a clean path: none.** The only one was launcher v5 L96/L179 (`$GuardFrom` into `output_guard.from`);
    v6 L185 fixes it.
  - **Present but masked, or never emitted:**
    - launcher L103 `$GuardMaskToken`: the folder token, in `walker` and in log paths; masked at L139 and L156.
    - launcher L134 `$ReceiptExceptionText`: `receipt.exception`; masked exactly at L475.
    - launcher L106-130 centre labels: used only for the set sha and the log `centre=` token; never written.
    - runner L240 `GUARD_FROM`: written only in basic format, at L2882.
    - runner L241 `GUARD_SEALED_FROM`: compared only; the counter keys use underscores, L463.
    - runner L86/L403 the folder token in `DOC_DIR` paths: masked at L472 and L497.
    - runner L193-216 F2 pins: emitted only as `pins_sha256` and a count, L818-819; the L817 Halt names the file
      only.
    - runner L265/L266/L269 via L404 `S7_CONSTANTS`: written only at `v5_gate_section7.cap`, L2032 (context-allowed).
    - runner L1016-1017 and L1634/L1639 centre labels: written only in centre fields and `centre=` log tokens
      (context-allowed).
  - **Fail-closed halt paths only.** The Halt texts at runner L1889 and L1908 interpolate a 2026 date. They can only
    occur on a path that already HALTs, so the guard withholds that reason text and counts it.
  - **Below 2026, not hits:** runner L143, L1384, L2128-2129 and L2314-2315.
- **Smoke (stage 0b, required by master).** Launcher v6 ran the no-op child `scripts/row28_smoke_noop_v1.py` into
  `run\s0_smoke`, in the RUN_LOG form, with `-Stage controls`. The child reads nothing. It writes only the two files
  the launcher names: walk.json `{runner_sha256: <its --expect-sha>, stage, status: PASS}` and a header-only
  walk.csv.

  `scripts/row28_smoke_verify_v1.py` does not import the runner. It checks runner v6's sha256, extracts by ast the
  exact source of `verify_prev` and its dependencies (`Halt`, `sha256_file`, `FORBIDDEN_ROOTS`, `MAIN_DATA_PIN`,
  `_OBSERVED_READS`, `guard_read`), executes only that code and calls `verify_prev` on the smoke folder. Every check
  in `verify_prev` was exercised:
  - the report sha;
  - report status PASS;
  - the receipt exists and is COMPLETE;
  - `output_guard.hits_total == 0`, `receipt_guard_hits` (absent, so 0) and no `output_guard_flag`;
  - receipt stage equals the stage name;
  - receipt `walker_sha256` equals report `runner_sha256`.

  As a negative control, the same call refuses attempt 1's folder (at its first check: report status HALT).

## Fourth addendum (2026-11-03T05:08-05:00): controls a2 ERROR, the local LFS checkout, a3

The coordinator's go covered the repair and the a3 relaunch, as the same attempt. The sha256 values are in
`RUN_LOG.md`.

- **a2 ERROR.** Controls a2 (launcher v6, runner v6) ended PARTIAL: launcher exit 5, walker exit 11. It failed at
  the first `extract`, with `ColumnAllowlistError`: the served artifact
  `artifacts/models/hgb/feature_model_hgb_atlanta.pkl` was a Git LFS pointer. In the worktree, all 26 LFS-tracked
  files had never been checked out. No control ran.
- **Local checkout.** `git -C C:\wt\L59row28 lfs checkout artifacts/models/hgb` was run with `lfs.url` and
  `remote.origin.lfsurl` set to an unroutable address, so it could make no network access. All 26 objects came from
  the shared local LFS store (0 B/s, 380 MB). The main checkout was not touched. `git status` stayed clean.
- **oid verification.** For each of the 26 files, the sha256 and the size equal the oid and size in the pointer
  committed at HEAD (`git show HEAD:<path>`). The oid is the pin. The path, oid and size table is in `RUN_LOG.md`;
  sha256 of the table text: `f39da351331bbec8c8e9051ef937fa7fcdb6153f7405abda28a02dcf29abd1cf`.
- **Other LFS paths.** `.gitattributes` has two LFS patterns: `artifacts/models/hgb/*.pkl` (the 26 files) and
  `docs/roadmap/repair-ceiling-single-environment-runtime-bundle-*.zip`. No file in this tree matches the second
  pattern, and the runner does not read any such path. No pointer file remains under `artifacts/`, `src/` or
  `config/`.
- **a3.** Controls a3 went into `run\s1_controls_a3`, with the same launcher, runner and config. Its result is in
  `RUN_LOG.md`. The a2 folder stays in place as evidence.

## Fifth addendum (2026-11-03T05:25-05:00): the a3 guard HALT, its root cause, runner v7

The coordinator called this "C3 addendum 4"; the fourth addendum (LFS repair, a3) already exists, so this one is the
fifth. Master accepted the BENIGN verdict and gave runner v7 a go. The sha256 values are in `RUN_LOG.md`.

- **The a3 diagnostic (d1).** `scripts/row28_guard_diag_v1.py` (`adad5ce6…`) ran under launcher v6 into
  `run\d1_guard_diag`. Receipt `3bc30bd0…`, COMPLETE.
  - It reconciled exactly: the runner's own stage-end scan gave 276, the traced rows gave 276, walk.json 158 of 158
    and walk.csv 66 of 66.
  - All 276 hits had the class EMBARGO, so I stopped under pre-ruling (c). The coordinator then read the table
    under master's ruling: all 276 hits sit at records, `plan/column_differences_from_served/decision`.
- **Root cause.** The hits are code constants, not data:
  - `r0_scope.py:51` `DECISION_PRESSURE` and `:52` `DECISION_CONSENSUS`, owner-decision strings that contain the
    dates of those owner decisions;
  - written by `column_differences` (`r0_scope.py:117`, `:119`) into the plan key `column_differences_from_served`
    (`feature_column_allowlist.py:288`; the coordinator cited 287/288);
  - which every records payload carries as `plan` (`pooled_residual_model.py:247`).
- **Review error, v3 F2.** The v3 review's F2 residual treated the dated text in `feature_column_allowlist` and
  `r0_scope` as "docstrings only". `r0_scope.py:51-54` are string constants, and two of them reach every records
  file. That reading was wrong.
- **d2 not run.** Master's d2 brief had no category for a code constant (`DECISION_CONST` was missing). After the
  BENIGN verdict, master decided d2 is not needed, and it was not run.
- **v7 allowance (K1).** In a records file, at exactly `plan/column_differences_from_served/[i]/decision`, a value
  is allowed only if the WHOLE string equals `DECISION_PRESSURE` or `DECISION_CONSENSUS`.
  - The two strings are pinned verbatim in the runner, and `r0_scope.py` by sha256
    `E8BB0683ED7C252B4F07E18F83709C9E0A5FCFD4C835D803B80C5C531F18607B`. `check_decision_pins` HALTs if the sha or
    either string differs, and the allowance is off until it passes.
  - Every firing is counted. walk.json `output_guard.decision_allowance` reports `values` and `dated_tokens`, and
    a4 must show `dated_tokens` = 276.
  - The same strings anywhere else, or any other value at that path, are still hits.
  - `DECISION_BASE_ONLY` and `DECISION_LEAF_SWEEP` are not allowed.
- **v7 K2 and K3** (see the temporal-type note below).
- **Non-string temporal values in v6's walk (code reading of `_walk`, runner v6 L532-614).**
  - **Classed in v6:**
    - `datetime`, `date` and `pd.Timestamp` (a `datetime` subclass) go through `isoformat`.
    - numpy `datetime64` scalars and arrays, `DatetimeIndex` and datetime Series (dtype kind `M`) are cast to
      `datetime64[D]` strings.
    - categorical values, and every category (G1).
  - **Not dates, so no hit:** `timedelta`, `timedelta64`, `TimedeltaIndex` and `time`.
  - **Two gaps, fixed in v7:**
    - **K2: tz-aware datetime arrays.** v6 cast them through `np.asarray(...).astype("datetime64[D]")`, which is
      not assured for tz-aware values. Any exception there fails closed (unscannable or ERROR), but the class is
      the UTC date at best. v7 walks them as `isoformat` strings, keeping the wall-clock date and offset.
    - **K3: pandas `Period`.** A `Period` is not a `date`, has no `dtype`, and has a `__dict__`, so v6 walked its
      empty `vars()` and saw nothing. A pickled `Period` holds no date text, so the byte cross-check cannot catch
      it either. This was a silent coverage hole. v7 walks a `Period` (and so a `PeriodIndex` or a Period Series,
      whose values are `Period` objects) as `str(o)`.
  - Sentinel v5 has a case for every type above.
- **Code sweep (static: an AST pass over the weather.* import closure of the runner's bound modules, 168
  modules, plus the R-P2 copy).** It lists every 2026 ISO date inside a string constant (docstrings and comments
  excluded) and whether that constant can reach a pickled or written output.
  - **Reaches records: `r0_scope.py:51` `DECISION_PRESSURE` and `:52` `DECISION_CONSENSUS`.** Path:
    `column_differences` (`:117`, `:119`), then the plan key `column_differences_from_served`
    (`feature_column_allowlist.py:288`), then the records payload `plan` (`pooled_residual_model.py:247`). These
    are the 276. v7 K1 allows them only there.
  - **Not reached by the runner: `r0_scope.py:53` `DECISION_BASE_ONLY` and `:54` `DECISION_LEAF_SWEEP`.** Both
    occur only in `served_model_differences` (`r0_scope.py:145`, `:164`). That function is called only from
    `feature_model._train_main` (`feature_model.py:1619`) and `r0_candidate_manifest.py:319`. The runner calls
    neither: its `fm.*` calls are `brier_score`, `log_loss` and `smoothed_dist`; its `prm.*` calls are
    `extract_market`, `covered_years`, `load_records`, `pooled_frame`, `fit_pooled`, `predictive_distribution`,
    `attach_training_nbm`, `nearest_centre`, `season_of`, `station_coordinates`, `records_path` and `R0_MARKETS`.
    Neither constant is pre-allowed; if either ever reaches an output, it is a hit.
  - **Error text only (it reaches a report only as a HALT or ERROR reason, which the guard counts):**
    `r0_scope.py:48` `R0_OUT_OF_SCOPE_MARKETS` (toronto, in `require_r0_market`'s error at `:85`; toronto is not
    in R0).
  - **Centre labels, written only in centre fields (context-allowed):** `pooled_residual_model.py:90`
    `VALIDATION_CENTRE`, `:91` `OCT_DEC_CENTRES`, `:93-94` `JAN_JUL_CENTRES`, `:96` `AUG_SEP_CENTRES` and `:1258`
    `FORWARD_CENTRES`.
  - **In functions the runner never calls:**
    - `pooled_residual_model.py:874` (`headline_markdown`), `:949` (`dev_training_frame`), `:993`
      (`dev_emit_distributions`) and `:1170` (`dev_emit_n_distributions`);
    - `r0_ols_floor_challenger.py:680`, `:907`, `:1019` and `:1310` (the dev functions; `prm` reaches them only
      via `score_l3_comparators`, `dev_emit_*` and `receipt_grace_check`, none of which the runner calls).
  - **In the closure but off the runner's call path (no payload use):**
    - `upstream_obs_screen.py:58` `DEV_LAST` and `:335`;
    - `operations/storage_classes.py:83`, `:138`, `:350` and `:681` `ARTIFACT_FAMILIES`;
    - `reporting/scorecards/dev_scorecard.py` (`:319`, `:406`, `:433`, `:476`, `:489`, `:503`);
    - `dev_scorecard_data.py:89` and `:190`;
    - `free_source_candidates/remaining_rise.py:30` `HIST_END` and `:31` `OBS_LAST`;
    - `loss_atlas.py` (`:89` `RANGE`, `:695`, `:732`, `:967`, `:979`, `:1009`, `:1026`, `:1053`);
    - `schema_registry_data.py:708` `REGISTERED_SCHEMAS` and `schema_registry_recent_data.py:272`
      `RECENT_REGISTERED_SCHEMAS`;
    - `sources/free_screens/captured_openmeteo.py:102`.
  - **No dated string constant at all** in `feature_column_allowlist.py`, `feature_model.py`,
    `feature_model_training_inputs.py`, `model/feature_store.py`, `model/toronto_model.py` or
    `market/market_registry.py` (their dates are in docstrings or comments only).

## Sixth addendum (2026-11-03T05:59-05:00): controls a4, the records identity rule, runner v8 (M1, M2)

- **a4 result** (RUN_LOG "Appended 2026-11-03T05:46:52"). Runner v7, launcher v6 and the config `66e4b46e…` were
  unchanged, and the run went into `run\s1_controls_a4`.
  - Receipt COMPLETE (`9c288c9f…`), runner PASS, output guard 0 over 68 files.
  - `decision_allowance` `dated_tokens` 276, the target exactly (`values` 144).
  - The controls equal a3: C-0 19,657 / 0.0, C-0b 2 of 2, C-0c 4,125 / 0, C-b 660 / 0.0.
  - The raw records sha256 differed from a3 on 66 of 66 files, and the lane STOPPED.
  - **Master: BENIGN.** The cause is the gzip header MTIME: `pooled_residual_model.py:256` writes with
    `gzip.open(tmp, "wb")`. That module is B-bound and stays as it is.
  - **Established:** a4 = a3 on the decompressed payload, 66 of 66. The lane's decompress-and-hash of the a3
    evidence is accepted as disclosed.
- **Records identity (v8).** A records file is identified by the sha256 of its decompressed payload.
  - The raw sha256 is kept, and `records_sha256` still chains build and labels.
  - The raw sha256 is cross-checked with the MTIME bytes 4-8 zeroed (`gz_raw_sha256_mtime_masked`).
  - The controls and build reports add `records_payload_sha256` (`row28_run_v8.py:1954`, `:1998`).
  - walk.json adds `outputs_payload_sha256` (`:3177`), and walk.csv gains a third column, `payload_sha256`, for
    every `.gz` output.
  - Helpers:
    - `records_identity` (`:790`) and `compare_records_identity` (`:800`): equal iff the payload sha256 and the
      masked raw sha256 are equal for every file;
    - `compare_walk_csv` (`:825`): rows keyed by basename. A records row is compared on `payload_sha256`; a records
      row without one (a v7 walk.csv) counts as unverified, never as equal. Any other row is compared on `sha256`.
  - Differing names are reported only as templates, with each date replaced.
- **The stage-end guard already decompresses (v7, by line).** `guard_file` decompresses every `.gz` before any scan:
  `row28_run_v7.py:666` checks `if name.endswith(".gz"):` and `:669` does `data = gzip.decompress(data)`.
  - The structured walks, the text fallback (`:688`) and the byte cross-check (`:690`) all run on the decompressed
    bytes.
  - `output_guard_scan` calls `guard_file` for every new or changed file (`:813`).
  - No fix was needed. Sentinel v6 adds the case anyway: a dated token inside a `.txt.gz`, `.json.gz`,
    `.csv.gz`, `.pkl.gz` or `.jsonl.gz` payload is a HIT.
- **M1 (`m1_cut_set` `:718`, `m1_records_bytes` `:737`, applied at `:884`).** This applies only to a records file
  (`records_*.pkl.gz`) and replaces the per-object byte count there. Other files keep the v7 cross-check.
  1. The DECOMPRESSED pickle is read with `pickletools.genops`.
  2. Every str opcode (`SHORT_BINUNICODE`, `BINUNICODE`, `BINUNICODE8`) is verified to hold its value as a raw
     UTF-8 span at its own offset, with its length field. A mismatch is a hit (`m1_span_mismatch`).
  3. A span is cut only if its WHOLE value is one of:
     - (a) the file's own centre label from the file name, which must be in the pinned arm union. For a GAP file
       this is the 4 GAP labels instead: `pooled_residual_model.AUG_SEP_CENTRES`, a sha256-pinned module, checked
       by `set_m1_pins` (`:1067`) to be 4 labels inside the union;
     - (b) the market's pinned generated_at;
     - (c) a pinned decision constant, only while the K1 pins hold.
  4. The remaining bytes must hold ZERO dated tokens. Each one remaining is a hit (`m1_remaining`).
  - A pinned value inside a longer string is not a whole span, so it stays and is a hit.
  - Memoised strings occupy one span, which is why per-object counting was replaced (review minor 2).
  - walk.json reports `output_guard.m1_records`, keyed by the records basename (an allowed key parent) and holding
    the cut counts per kind plus `remaining`, `str_ops`, `span_mismatch` and `protocol`. `m1_summary` holds the
    totals.
- **M2 (`FrameColumn` `:559`, `_push_index_surfaces`, `_push_pandas_surfaces` `:578`).** The walk now visits every
  pandas surface, standalone or nested:
  - a Series' `.index` (in its name's context), `.name` and `.attrs`;
  - every Index's `.names`;
  - every MultiIndex level, used or not;
  - a DataFrame's column-axis names and levels;
  - every category (G1, kept).
  A DataFrame column is walked through `FrameColumn`, so the frame's index, labels and attrs are walked once and
  not once per column (review minor 5).
- **Disclosures.**
  - **Raw gzip header not scanned.** The raw header of every records file carries FNAME =
    `records_<market>_<centre>.pkl.tmp`, the file's own label: `gzip.open` on the `.tmp` path at
    `pooled_residual_model.py:256` writes the basename. The guard scans payloads, not raw gzip headers, so this
    was never scanned in v4-v8. It is the record's own name, but it is disclosed for a ruling.
  - **M1 is not yet tested on real records.** "Remaining 0 on 66" is the target, but it has not been checked on
    the a4 records: the lane ran nothing. If the real payloads hold any other dated string, for example inside a
    longer string or under the folder-name mask that the walk allows, a5 will HIT and STOP.
- **The v8 delta from v7** is 21 counted exact replacements (scratchpad `make_v8.py`). The runner name is
  `row28_run_v8`. Nothing else changes: the stages, gates, pins and K1-K3 are the same.
- **Sentinel v6** pins v8 (`7bb10f05…`). It changes v5 in one place, and only as M2 requires: a Series' dated
  `.name` is now a walk HIT, not byte-only. It adds one case per M2 surface, including a plain non-tz datetime64
  Series. It also adds:
  - the M1 cases: the pinned spans alone leave 0, under protocols 4 and 5 and for a GAP file; each kind of
    dated token outside them is a HIT;
  - the stage-end M1 report;
  - the gzip-payload case and the identity and comparison helpers;
  - an autouse check that no test's `tmp_path`, and so no basetemp, holds a date.

## Seventh addendum (2026-11-03T06:07-05:00): the M1 pre-check of a4, runner v9 (raw gzip headers), v8 review minors

- **The M1 pre-check of a4** (master GO; count only; RUN_LOG "Appended 2026-11-03T06:07"). Runner v8's
  `m1_records_bytes`, imported unchanged from `row28_run_v8.py` (`7bb10f05…`, as committed at `f074ba7ab`), was
  run over the 66 a4 records in `run\records`.
  - **Result:** remaining 0 on 66 of 66, span_mismatch 0, protocol 5 throughout, 28,716 str opcodes.
  - **Cuts:** centre 66 (1 per file; the GAP files hold only their own label), generated_at 66, decision 72
    (60 files × 1, 6 files × 2).
  - **Cost:** peak working set 32,468,992 bytes, 6.88 s wall in all (import, decompress and genops over 66 files).
- **The headers before v9.** Runners v4-v8 never scanned raw gzip headers: the guard scanned decompressed payloads
  only. The headers were by construction only prm:256's own tmp name, so there is no retroactive concern.
- **Runner v9** (`row28_run_v9.py`) is v8 plus the raw-header scan and nothing else (10 counted exact
  replacements; scratchpad `make_v9.py`).
  - `gz_header_members` (`:869`) parses the header of EVERY member, because `gzip.decompress` accepts
    multi-member streams. Each member's end is found by inflating it, and its 8-byte trailer is skipped. Trailing
    zero padding ends the file. Bad magic, reserved flag bits or truncation make the file unscannable.
  - `gz_header_scan` (`:911`, applied in `guard_file` at `:959`) decodes FNAME and FCOMMENT as latin-1 (RFC 1952)
    and reads FEXTRA bytes as latin-1 text for the count. MTIME is a binary int: it is reported per member as a
    value and never counted as a date.
  - **The one allowance:** a records file's FNAME equal to the exact string derived from its own final name,
    `records_<market>_<centre>.pkl.gz` → `records_<market>_<centre>.pkl.tmp`. The final name must pass the
    record-name rule (market in R0, centre in the arm union). Each firing is counted in walk.json
    (`gz_header_allowance` `fname_own_tmp` and `dated_tokens`).
  - **Hits:**
    - any other FNAME on any `.gz` (`gz_fname`);
    - any FCOMMENT on a non-records `.gz`, Writer outputs included, since `gzip.compress` writes neither field
      (`gz_fcomment`);
    - every dated token in any other header text, by category.
  - walk.json adds `output_guard.gz_headers` (per `.gz` basename: members, MTIME values, field counts, hits),
    `gz_header_allowance` and `gz_header_summary`.
- **Sentinel v7** pins v9 and adds the header cases:
  - FNAMEs that pass: the own tmp name written exactly as prm:256 writes it (0 hits, counted, MTIME a value), and
    the own name in a hand-built header;
  - FNAME hits: a wrong-centre FNAME, a wrong-market FNAME, a non-tmp FNAME, an undated foreign FNAME, an FNAME on
    a records file whose own name fails the rule, and any FNAME on a non-records `.gz`;
  - FCOMMENT hits: a dated FCOMMENT, the own name as FCOMMENT, and any FCOMMENT on a non-records `.gz`;
  - a dated FEXTRA, a dated header in a second member, and a reserved flag bit (unscannable);
  - the stage-end report.
- **The v8 review minors.** Disclosed here; the walk counting is NOT changed, so a5 = a4 compares cleanly.
  - **m-a.** `compare_walk_csv` compares records rows on the payload sha256 only; the MTIME-masked raw check lives
    only in `records_identity` and `compare_records_identity`. `records_identity` and `read_walk_csv` return
    dated basenames, so only the `compare_*` results (templates and counts) may be printed or logged.
  - **m-b.** The walk counts some names twice. A frame's `columns.name` is pushed at `:662` and again inside
    `names` at `:663` (v8 lines; v9 `:673`/`:674`). A MultiIndex's used labels are counted in its tuples and
    again in its levels. This only inflates counts and is fail-closed. It is not fixed before a5; the fix is
    backlog.
  - **m-c.** M1 counts the remainder (`m1_records_bytes`, v8 `:767`) with NO folder-name mask and NO records-root
    mask, while the walk applies both. This is intended: M1 is stricter, and fail-closed.
  - **m-d.** genops runs over every records file at stage end, which adds time: the pre-check measured 6.88 s for
    all 66 files, import included.

## Eighth addendum (2026-11-03T06:12-05:00): the v9 review minors m-1 to m-3, runner v10

- **The v9 review is CLEAN** (no B or M findings). The coordinator adopted m-1 to m-3.
- **m-1, runner v10** (`row28_run_v10.py`): v9 plus m-1 and nothing else (6 counted exact replacements; scratchpad
  `make_v10.py`). In `gz_header_scan`:
  - ANY FCOMMENT on ANY `.gz` is a hit (`gz_fcomment`);
  - ANY FEXTRA present on any `.gz` is a hit (`gz_fextra`);
  - the dated-token count is kept on top.
  Neither `gzip.compress` (the Writer) nor prm:256's `gzip.open` writes either field. The hits are therefore any
  other FNAME on any `.gz`, any FCOMMENT or FEXTRA on any `.gz`, and every dated token in any header text other
  than the one allowed own tmp FNAME. The seventh addendum's hit list now carries this wording too, marked v10.
  - **Sentinel v8** pins v10 and updates the header expectations:
    - comment and comment_own → `gz_fcomment` 1 plus 1 dated;
    - extra → `gz_fextra` 1 plus 1 dated;
    - undated_comment → `gz_fcomment` 1;
    - second_member → `gz_fcomment` 1 plus 1 dated;
    - new: an undated FEXTRA → `gz_fextra` 1.
- **m-2.** The seventh addendum's no-retroactive-concern sentence now ends with the qualifier "(code reading; not
  measured on the a3/a4 evidence, which stays unopened; a5 measures it prospectively)".
- **m-3.** The a5 header targets and the `compare_walk_csv` expectation are in RUN_LOG ("Appended
  2026-11-03T06:12").
- **Correction (2026-11-03T06:15-05:00, m-A of the v10 review; append-only).**
  - **The revert.** The two in-place edits to the seventh addendum were reverted. The seventh addendum is now
    byte-identical to its text at `149393482` (CLARIFICATION_3.md `aa3844d7…`), proven by a diff of that section.
    Its sha256, from its heading through its last line, is `68c393f3211bc825…` both now and at `149393482`. The
    whole file up to the eighth addendum's heading equals the `149393482` file byte for byte.
  - **Superseded.** This addendum's two statements above, that the seventh addendum "now carries" the v10 wording
    and "now ends with" the qualifier, are superseded by this note. Both corrections are carried here instead.
  - **(1) m-1 wording.** Where the seventh addendum says "any FCOMMENT on a non-records `.gz`", read for v10:
    "any FCOMMENT or FEXTRA on any `.gz`" (`gz_fcomment`, `gz_fextra`; the dated-token count on top). That text
    remains true of v9 itself.
  - **(2) m-2 qualifier.** The seventh addendum's sentence "The headers were by construction only prm:256's own
    tmp name, so there is no retroactive concern" is qualified: (code reading; not measured on the a3/a4
    evidence, which stays unopened; a5 measures it prospectively).

## Ninth addendum (2026-11-03T07:27:29-05:00): the build-1 HALT, the NBM rollover allowance, runner v11

- **The HALT.** Build 1 HALTed on the runner's output guard. Every hit is class Y26_PRE0527:
  - 11 hits at stage end in `nbm_market_new/nbm_pit_corpus_rows.jsonl`;
  - 300 tokens in the refused `pool_nbm_rows.jsonl` write, which was never written.
- **d3 finding** (`row28_guard_diag_v3.py`, `5606a287…`; RUN_LOG 07:19:11 append). All 11 are `valid_time_utc`, a
  row-date field, ISO with an offset, literal Y26-M01 and market-local PRE2026. The count at or after 2026-05-27 is
  0, literal and market-local.
- **The pool tokens.** The 300 are attributed by code to the same schema and field. They are not measured; the
  rebuild measures them prospectively.
- **Master's ruling.** These are UTC rollovers of the local 2025-12-31 corpus year end. 2026-01-01..05-26 rows are
  descriptive for all arms; deciding stays 2021-25; sealed starts at 05-27. The build config is unchanged.
- **Runner v11** (`row28_run_v11.py`, built from v10 by `make_v11.py`, 15 exact replacements; v10 is not edited)
  adds one allowance, armed only by the build stage (`set_v11_allowance`). It applies to:
  - **paths:** exactly `nbm_market_new/nbm_pit_corpus_rows.jsonl` and `pool_nbm_rows.jsonl`, relative to the build
    stage directory;
  - **key:** `valid_time_utc` at a row's top level only.
- **Value rule.** The value must be one full ISO instant holding one dated token, and all three conditions must hold:
  1. the literal class is Y26_PRE0527;
  2. the local date is ≤ 2025-12-31 in the row's tz;
  3. the instant is ≤ 2026-01-01T12:00Z.
- **The row's tz.**
  - **Market rows:** `market_id` is the market id, and the tz comes from the pinned market registry.
  - **Pool rows:** `market_id` is the station ICAO (`station_pool_corpus.nbm_pool_rows` sets
    `market_id = station_id = icao`). The tz comes from the pinned pool station list:
    `s0_candidate_stations.json` `tz` for each `station_set.json` survivor, the same `tz_pool` the producer uses.
  - An unknown market id, a missing `market_id`, an unresolvable tz or a naive instant is a HIT.
- **Pins** (`set_v11_allowance` HALTs on any difference):
  - `WEATHER_MARKET_REGISTRY` must be unset.
  - `src/weather/market/market_registry.py` `b738b28616ee3a69b9f8c8e46e976345caebc39524be290bd18fe74e576050a0`.
  - `config/markets.json` `25a3db6dd2e4f90d0b67eca4c92a033204aa6289ef75cb195d6a214bcda4852d`.
  - Market tz map, 11 NBM markets (canonical JSON):
    `5ea728abebfec7150535c8b247b7da16364fb61e767b041ac200407266548341`.
  - `station_set.json` `f757acb7…` (`STATION_SET_SHA256`) and `s0_candidate_stations.json` `60351c58…`
    (`STATIONS_META_SHA256`).
  - Pool tz map, 300 survivors: `4bf76e7a6363af8eeb55ba92c3ea2c56957ceee5d20a168b8a2ee5f441edcd32`.
- **Byte side.**
  - The exact spans `"valid_time_utc": <json value>`, one per passed row, are cut from the raw text, and each must
    occur exactly as often as it passed (otherwise `v11_span_mismatch`).
  - The remainder may hold no more dated tokens than the walk's hits plus other allowances; it must be 0 when the
    file is clean (otherwise `byte_crosscheck`).
  - The same holds in the Writer (`pool_nbm_rows.jsonl`, phase `writer`) and at stage end (both files, phase
    `stage_end`).
- **Counting.** walk.json `output_guard.v11_nbm_allowance` holds `phase|file|class|month` → count, and
  `v11_nbm_bytes` holds `phase|file` → {spans_cut, remaining, span_mismatch}. walk.json `v11_pins` holds the pins.
- **Still a HIT:** a local 2026 date, a value after 12:00Z, another key or depth, another file (including the right
  name in another directory), another class, and any value when the stage is not build.
- **Sentinel v9** (`test_row28_s7_sentinel_v9.py`, built from v8 by `make_test_v9.py`; v8 is not edited) has 44
  tests: v8's 34 plus 10 for v11.
  - **The 0 case:** the rollover case passes at 0 and is counted, in both files and both phases.
  - **HITs:**
    - a local-2026 value, and a 05-27 value;
    - a 13:00Z value (the instant rule binds on its own);
    - unknown and unresolvable pool tz, a missing `market_id`, and a market id in the pool file;
    - the allowed value at `target_date`, at `issued_at` and nested;
    - a third file, the right names in the wrong directories, and outside the stage dir;
    - a non-exact span;
    - an unarmed stage.
  - **Other tests:** the counts are reported by the stage-end scan, and unpinned sources are refused.

## Tenth addendum (2026-11-03T07:37:21-05:00): the v11 review (B-1, m-1 to m-4), runner v12

- **B-1 (blocker), fixed.** v11's `RULING_V11_NBM_ROLLOVER` held a literal ISO instant in the guard's range.
  - main reports every `RULING_*` in `report["rulings"]`, and the report guard has no allowance there. The rebuild
    would therefore have withheld `rulings` and HALTed (code 10).
  - v12 rewords it as "instant <= V11_INSTANT_LAST (noon UTC of the first day of that year)". The rule itself is
    unchanged.
  - An AST pass over every module-level constant of v12 (`l59_static_dates_v1.py`) finds 0 of 33 `RULING_*` with a
    2026+ date. The other constants holding one are not reported as values:
    - `DOC_DIR`: masked by `GUARD_MASK_TOKEN` in the gate paths;
    - `CALIBRATED_WEIGHTS_PINS`: reported as a count and a sha;
    - `DECISION_ALLOWED_VALUES`: reported as a count;
    - `GUARD_FROM`: reported in compact form;
    - `S7_*`: only the section 7 `cap` field, its declared constant field;
    - `V11_*`: never reported.
  - Sentinel v10 guards the real `RULING_*` dict.
- **m-1, adopted.** `spc.nbm_pool_rows` setdefaults its `tz_pool` into
  `nbm_probabilistic_tmax.NBM_NBP_STATION_TIMEZONES`, and the bound parser uses that table for market stations. So
  the pool rows' local dates follow the parser's table wherever it has an entry, not `tz_pool`.
  - **Qualifier on the ninth addendum's "the same `tz_pool` the producer uses":** true for stations without a
    parser entry. For stations with one, the parser's entry governs.
  - v12 therefore HALTs at stage start if any v11 market tz or pool tz differs from the parser's entry for the
    same station (market: via `NBM_STATIONS[market]`; pool: the ICAO itself).
  - The parser module is pinned: `src/weather/sources/nbm_probabilistic_tmax.py`
    `c469229b979c9a29fe96ec15db64d80e30038045fbc000a7a128e1ffca84f70b`.
  - The agreement counts are pinned and reported in `v11_pins.parser_tz_agreements`: market 11 (all 11 have an
    entry, all agree) and pool 0 (no survivor has an entry).
- **m-3, adopted.** The allowance fires only for a dict row at the JSONL line root (`o is obj`).
  - The Writer walks each row separately, as the stage-end scan walks each written line.
  - A non-dict line in an allowed file is a HIT (`v11_non_row_line`), and so is a list-wrapped row.
- **m-2, adopted.** Sentinel v10 (`test_row28_s7_sentinel_v10.py`, from v9; 48 tests) adds:
  - the real rulings-dict guard;
  - a naive instant is a HIT, and a `Z` instant passes;
  - every `set_v11_allowance` pin HALT branch: market tz map, station list, pool tz map, parser disagreement (pool
    station and market), and the agreement-count pin; the pinned case arms the allowance;
  - a list-wrapped line and a non-dict line are HITs, in the Writer and at stage end.
- **m-4.** This addendum records the above. The ninth addendum's statement that a naive instant is a HIT is now
  tested.
