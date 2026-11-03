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
