# Year-Round Refit (Row 28 Candidate B) Runbook

Owner: `weather.calibration.yearround_refit` (item 343b,
[item 343](../roadmap/items/item-343-offline-year-round-refit-module-allowlist.md)). This runbook owns the
operator steps for the module's three commands. The rulings, the frozen field list and the Feb 29 statement are
in the module docstring; the forward test itself is owned by its prereg.

Scope: offline research on the workstation only. The module serves nothing, has no live, execute, place, cancel or
promote path, is never imported by a capture loop (an AST ratchet in
`tests/calibration/test_yearround_refit.py` proves it), and imports no label or price reader. Every command runs
through `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy`; the module is on the workstation offline allowlist
and the B-look argument refusal stays in force for it.

## Inputs

All three commands take a config JSON by path and sha256 (`--config`, `--config-sha`). Its keys are
`records_root`, `pit_corpora`, `fetch_dir`, `bound_state` and, for equivalence only, `frozen_records_list`.
`records_root` must lie outside the repository, because the bound `extract_market` refuses an in-repo output root.
The module reuses a records root only through its `records_manifest.json` payload shas and refuses a partial one.

## 1. Fit (once, before `FROZEN_BEFORE_UTC`)

```powershell
-m weather.calibration.yearround_refit fit --arm B --config <cfg.json> --config-sha <sha256>
```

- Refuses at or after `FROZEN_BEFORE_UTC` (2026-12-17T00:00Z), any training row outside `TRAINING_WINDOW`, any
  missing training market, an upstream module whose sha differs from its pin, and a state whose sha is the bound
  P3d_N state or any release-binding sha.
- Writes once to `data/yearround_refit/row28_B/<fit_id>/`: the state, its sidecar and `fit_manifest.json`. An
  existing directory is refused.
- Copies the three files to `C:\archive\row28b-forward-state\<fit_id>\` and verifies them sha-equal. Record that
  path and the state and fit-manifest shas in the forward prereg.

## 2. Forward receipt

Emission needs an owner-approved forward receipt (`yearround_refit_forward_receipt/1`). It names the state sha,
the fit-manifest sha, the forward prereg sha, the window (inside `EMISSION_WINDOW`) and the owner approval record.
The module does not write it.

## 3. Emit (weekly, after the fact)

```powershell
-m weather.calibration.yearround_refit emit --state <state> --state-sha <sha> --fit-manifest <m> `
  --fit-manifest-sha <sha> --forward-receipt <r> --forward-receipt-sha <sha> --snapshots <parquet> `
  --replay-root <dir> --first <date> --last <date> [--inputs as_of_capture]
```

- Weekly batches from 2026-12-21: at most `BATCH_MAX_DAYS` (7) days, `--last` before today, inside both the
  emission window (2026-12-17..2027-05-31) and the receipt window. There is no daily task and no Scheduler change.
- Inputs are `as_of_capture` only. The snapshots file must hold only rows inside the batch, and is read through a
  schema screen that takes the snapshot columns only.
- Writes `shadow/<first>_<last>/shadow_rows.jsonl` and `emit_receipt.json` under the fit directory and prints
  `shadow_rows_sha256` and the emit receipt sha. Record both per batch.
- The scored window is 2026-12-17..2027-01-30 and is named separately from the emission window.

## 4. Equivalence (against the frozen v12 runner)

```powershell
-m weather.calibration.yearround_refit equivalence --config <cfg.json> --config-sha <sha> `
  --frozen-runner <row28_run_v12.py> [--mode state_sha]
```

- The frozen runner must be `row28_run_v12.py` at its pinned sha. Use a new records root.
- Checks (a) the records against `frozen_records_list` (column 3, the decompressed payload sha) and the frames,
  (b) the training row-key sets and bucket spaces, and (c) the fits: the trainer against the runner's to 1e-12 and
  serve through per-hour states. The report is PASS or FAIL with counts and max absolute differences, and holds no
  label, Brier or log loss.
- `--mode per_row` needs `--frozen-rows` and its sha and reads only label-free columns. v12's frozen rows keep only
  `A_yhat`, so `state_sha` is the mode in use.

## Update this file when

The CLI, the config keys, the windows, the archive root or the emission cadence change.
