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
