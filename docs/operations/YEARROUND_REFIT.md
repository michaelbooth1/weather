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

`fit` and `equivalence` take a config JSON by path and sha256 (`--config`, `--config-sha`). Its keys are
`pit_corpora`, `l9_corpus`, `fetch_dir`, `bound_state`, `frozen_records_lists` (a list of `[path, sha256]`
pairs whose `records_*.pkl.gz` rows are unioned; an overlap, a duplicate or a union count other than every expected
record window refuses) and, for equivalence, `frozen_new_nbm_rows_sha256`. The records root is the REQUIRED
`--records-root` argument (master review 2026-11-03): it has no default, and a config holding `records_root` is
refused. No environment variable and no committed machine path names it. It must lie outside the repository,
because the bound `extract_market` refuses an in-repo output root.
The module reuses a records root only through its `records_manifest.json` when the manifest was written by the same
module source sha, lists no fail-closed or skipped centre, holds exactly the expected records with matching payload
shas, and equals the frozen lists; it refuses a partial root. A records root under any junction or symlink, or
inside any checkout (any ancestor holding `.git`, the checkout root included), is refused. `fit` requires
`frozen_records_lists`; the retired keys `frozen_records_list` and `frozen_records_list_sha256` refuse by name.

`fit` refuses by name, and never filters or alters the bound training set:
- a (market, date) on which any of F, x_high_so_far and x_current_temp has no finite value (WU hourly);
- a date with no NBM mean for any market (a per-market NBM gap stays the section 3.3b imputation; the pooled
  per-month cap refuses, and per-(market, month) counts are reported in the manifest only);
- a hole in the calendar grid: an expected (market, date) of the record windows with no scored-hour row.
If one trips on the bound inputs, stop and report the counts; master rules whether it is a disclosure or a defect.
The equivalence report carries the same checks as `training_source_checks` (reported, not a pass check).

`emit` refuses by name a batch (market, date) with no captured snapshot, no usable NBM or no METAR replay
observation. A batch (market, date) that still emits 0 rows is a named hole record in `holes.jsonl` with a reason
code (`no_snapshot_at_a_scored_cutoff` or `no_row_served`); the receipt carries the hole count and records; the
forward prereg's countability rules decide its effect.

Disclosure (inherited from bound MG-2, not changed here): training anchors NBM with `nbm_at_cutoff` at h:00, while
serving uses `usable_v2_mean` at capture time.

## 1. Fit (once, before `FROZEN_BEFORE_UTC`)

```powershell
-m weather.calibration.yearround_refit fit --arm B --config <cfg.json> --config-sha <sha256> --records-root <dir>
```

- Refuses at or after `FROZEN_BEFORE_UTC` (2026-12-17T00:00Z), any training row outside `TRAINING_WINDOW`, any
  missing training market, an upstream module whose sha differs from its pin, and a state whose sha is the bound
  P3d_N state or any release-binding sha.
- Writes once to `data/yearround_refit/row28_B/<fit_id>/`: the state, its sidecar and `fit_manifest.json`. An
  existing directory is refused.
- A refusal after the fit directory exists (the frozen-list compare, a source or calendar-grid check, the pooled
  imputation cap, a missing training market) writes a `REFUSED` marker there: the reason, the message and a UTC
  stamp. A directory with `REFUSED` (or without `fit_manifest.json`) is never a fit; leave it as evidence and fit
  again with a new fit id. The records root and the NBM work files it wrote stay as they are.
- An empty calendar grid (no covered year in the training window) refuses by name.
- Copies the three files to `C:\archive\row28b-forward-state\<fit_id>\` and verifies them sha-equal. Record that
  path and the state and fit-manifest shas in the forward prereg.
- Freeze the forward 13-16 state only at the FINAL module sha, after `--hours` lands: `emit` refuses when this
  module's sha, `mg2_p3d_n.py` or `r0_ols_floor_devfit.py` differs from the fit manifest, so any module change after
  the freeze refuses emission by design. K2 then proves the 13-16 state unchanged.

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
- Inputs are `as_of_capture` only. The snapshots parquet needs `target_date` row-group statistics; a row group
  outside the batch refuses before any read, then the read is filtered to the batch. It passes a schema screen
  that takes the snapshot columns only.
- `emit` refuses when any serve helper's source sha (`SERVE_HELPERS`) differs from the one recorded at fit, and
  when a whole-file pin (`EMIT_PINNED_MODULES` and this module) differs. A `target_date` that is not `date32` or a
  string refuses by name.
- Writes `shadow/<first>_<last>/shadow_rows.jsonl` and `emit_receipt.json` under the fit directory and prints
  `shadow_rows_sha256` and the emit receipt sha. Record both per batch.
- The scored window is 2026-12-17..2027-01-30 and is named separately from the emission window.

## 4. Equivalence (against the frozen v12 runner)

```powershell
-m weather.calibration.yearround_refit equivalence --config <cfg.json> --config-sha <sha> `
  --records-root <new dir> --frozen-runner <row28_run_v12.py> [--mode state_sha]
```

- The frozen runner must be `row28_run_v12.py` at its pinned sha. Use a new records root. A missing
  `frozen_records_lists`, a retired key or a non-empty records root refuses before any directory is written.
- Checks (a) the records against the `frozen_records_lists` union (column 3, the decompressed payload sha; a record
  built but not listed, or listed but not built, FAILS), the new NBM rows against `frozen_new_nbm_rows_sha256`
  (absent FAILS) and the frames,
  (b) the training row-key sets and bucket spaces, and (c) the fits: the trainer against the runner's to 1e-12 and
  serve through per-hour states. The report is PASS or FAIL with counts and max absolute differences, and holds no
  label, Brier or log loss.
- The report names its mode. `state_sha` passes a fit only when the trainer and serve compares cover every expected
  row (Feb 29 excluded from serve), and the forward check only when the state sha is equal and serve, round trip and
  trainer cover every row; the counts are in the report. `--mode per_row` additionally needs `per_row_compared`
  equal to the rows, needs `--frozen-rows` and its sha, and reads only label-free columns. v12's frozen rows keep only
  `A_yhat`, so `state_sha` is the mode in use. No mode passes with nothing compared.

## Update this file when

The CLI, the config keys, the windows, the archive root or the emission cadence change.
