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
