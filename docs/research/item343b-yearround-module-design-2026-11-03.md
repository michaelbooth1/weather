# Item 343b: durable offline year-round refit module, design note (no code)

Status: **DESIGN ONLY, for master review before any code.** Lane L56, 2026-11-03, from origin/master
`621d67f0fdbd05556725239cd09f07468c132241`. Nothing here is built. No data values were read to write it: only code,
rule text, file shas and run-log timings and memory peaks. No row-28 label, score, outcome or price was opened.
No panel store was opened, and no B-bound file is edited.

Sources read:

- [Item 343](../roadmap/items/item-343-offline-year-round-refit-module-allowlist.md) at `97c2bb824`
  (`claude/item343-offline-refit-allowlist-20261103`). It sets the 343a/343b split, design (A), the reserved name
  `weather.calibration.yearround_refit`, and the trigger.
- Row 28's frozen runner `docs/research/row28-yearround-history-2026-11-02/scripts/row28_run_v12.py`, sha256
  `9e97c892936842e79b3d6279aa88979da8cf79fb09bd3b269b4726b2dfd1025b`, and its prereg `prereg_row28.md`, sha256
  `cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b`. Both are on
  `claude/row28-yearround-history-20261102` @ `946fe4fb7835ba60c2d4e5a4b01c79e5f34f9f81` and were verified by
  sha.
- The model contract in `AGENTS.md` (train/serve parity, the effective WU print cutoff, probability mass,
  captured-input replay, release binding), and `docs/operations/AGENT_CONTEXT.md`.
- Read-only, for the serve side: `weather.calibration.mg2_p3d_n` and `weather.model.mg_serve_core`.

## 0. Why now and what it is for

Row 28's candidate **B** is the season-matched P3d_N_fix refit. It trains on Dec 17 – May 31 rows only, with the
centre set `JAN_JUL_CENTRES[:10] + ("2026-12-24",)` (prereg §3.2, §4).

If B survives history and the owner OKs the forward embargo line (prereg §9.3), the separate forward test needs B
to emit **forward SHADOW forecasts** for 2026-12-17..2027-05-31. That is the trigger of item 343b: "the next
row-28 stage that needs the wrapper". This note designs the module that:

1. fits B's forward state from history rows;
2. emits B's shadow distributions on captured inputs;
3. proves itself equal to the frozen v12 run.

It serves nothing.

## 1. Interface

One module, `src/weather/calibration/yearround_refit.py` (the reserved name), with three CLI subcommands. Each is
offline, history- or replay-only, and admitted by `workstation_heavy.ps1 -Kind weather_heavy` once its allowlist
line lands (§9).

| Command | Inputs | Outputs |
| --- | --- | --- |
| `fit --arm B --config <cfg.json>` | A config naming every input root by path and sha256 (below). The arm. The training window, ending at or before `2025-12-16`. | The state `p3d_n_state.pkl` and its sidecar `p3d_n_state.json`, written by `mg2_p3d_n.write_state`, plus `fit_manifest.json` (schema `yearround_refit_fit_manifest/1`). |
| `emit --state <pkl> --state-sha <sha> --snapshots <parquet> --replay-root <dir> --first <d> --last <d> --inputs last_in_hour\|as_of_capture --forward-receipt <json> --out <dir>` | The frozen state, checked by sha before unpickling. The captured snapshot layout (label-free). The captured replay folders. The window. The forward-lane receipt. | `shadow_rows.jsonl` (rows written by `mg2_p3d_n.jsonl_line`) and `emit_receipt.json` (schema `yearround_refit_shadow_receipt/1`). |
| `equivalence --config <cfg.json> --frozen-runner <path> --frozen-runner-sha 9e97c892…` | The same config as `fit`. The frozen runner file, verified by sha. | `equivalence_report.json`: PASS or FAIL, counts and max abs differences only (§2.3). |

The config inputs mirror v12's `load_context` and are each verified by sha before use:

- the PIT-corpus root (`SEASON_CORPORA` shas);
- the fetch manifests (`FETCH_MANIFEST_SHA256`);
- the L9 NBM corpus `1ae4bf52…`;
- a new records root;
- the bound-module shas (`MODULE_SHA256`), checked against the importing checkout.

Repository paths come from `weather.paths`. No root is derived from the current working directory.

**Arms.** The module carries arms **A and B only**, because they differ only in training-row filter and centre
set. C (the R-P2 pool corpus) and D (K112) stay in the research runner. Adding either is a later 343b review.

**The forward state's training set** is v12's fold-2026 training set for B: every B row (Dec 17 – May 31 by
`target_date`) dated at or before `LAST_TRAIN = 2025-12-16`, with no season-year held out. This is exactly
`arm_training(frame, "B", hour, 2026)`. The bucket space follows prereg §3.6 over those rows.

**Where B's fitted state lives: `data/`, not `artifacts/`.**

- Path: `weather.paths.data_path("yearround_refit", <candidate_id>, <fit_id>)`. `fit_id` is the ISO-basic UTC fit
  instant. The directory is write-once: `write_state` already refuses to overwrite.
- Reason 1: `artifacts/` holds durable model, calibration and release artifacts, and its tooling (registry,
  size-audit, `promotion-preflight`, `release_lifecycle`) scans it. A shadow candidate there sits one step from the
  release path. Keeping it outside `artifacts/` makes "serves nothing" structural, not a convention.
- Reason 2: the precedent. MG-2's bound P3d_N state `c6cc39f7…` is "local runtime evidence and not committed",
  re-verified from the file bytes (`rule.md` C3-binding). B's forward state is evidence of the same kind.
- Durable identity comes from the shas, not the location. The forward prereg freezes `state_sha256`, the sidecar
  sha and `fit_manifest_sha256` before 12-17. `fit_manifest.json` holds no values (shas, row counts, centres,
  windows, upstream shas, the sklearn version), so it may be committed beside the forward prereg. The pickle is
  not committed.
- Never `docs/research/mg2-composite-binding-2026-10-25/`, never `artifacts/releases/`, never
  `release-binding.json`.

**State schema.** The state is a `mg2_p3d_n_state/1` dict, built by `mg2_p3d_n.state_from_fits` (imported
read-only). The serve path can then be exactly MG-2's `serve_distribution` (§2.2).

- `provenance` carries `candidate: "row28_B"`, `shadow_only: true`, `module`, `module_source_sha256`,
  `fit_manifest_sha256` and the upstream shas.
- `conversion` and `late_report` are copied from the bound state `c6cc39f7…`. It is loaded through
  `mg2_p3d_n.load_state(..., forward=True)`, only those two dicts are read, and equality is asserted. B then
  differs from served P3d_N only in its fit.
- `season_of` maps months 01–05 to "jan_jul" and 12 to "oct_dec" (`pooled_residual_model.season_of` on B's
  centres).

**Open question Q-S for master.** `fit_kind` is `"forward"` here, so MG-2's `load_state(forward=True)` would accept
the state if anyone bound its sha. That would take an edit to the B-bound `release-binding.json`, which is
master-only. The design adds two guards:

- `emit` refuses a state whose sha equals any sha in `release-binding.json`;
- `fit` refuses to write a state whose sha equals the bound `c6cc39f7…`.

The alternative is `fit_kind "dev"`, so MG-2's forward loader would refuse it structurally. That misuses "dev",
which means the control-check fit, so it is not recommended. Master's choice.

## 2. Train/serve parity with the row-28 history build

### 2.1 What becomes library code (and what does not)

| v12 function | Becomes | Note |
| --- | --- | --- |
| `load_context`, the centre sets, the `MODULE_SHA256` check | `context(cfg)` | Sha checks unchanged. The run-root junction and `check_write_roots` logic is replaced by a write root under `data/yearround_refit/` |
| `centre_for` (Rule L), `circular_picks` | `centre_for`, `wrap_check` | Rule L unchanged. The wrap-free = wrap-aware assertion runs at fit time on every training date |
| `manifests_for`, `covered` | same | The "no covered year after 2025" HALT is kept |
| `market_frame`, `blank_labels`, `frame_diff` | `market_frame`, `frame_diff` | Bound `extract_market` → `pooled_frame` → `DEV_KEEP_X` reduction, imported read-only, not copied |
| `nbm_rows_index`, `merged_table`, `write_filtered_blocks`, `fetch_file`, `verify_fetch_manifest` | `nbm_tables` | The §3.3b one-table rule and the no-duplicate (market, date, cycle) HALT |
| `with_arm_centres`, `arm_training`, `arm_buckets` | `arm_rows`, `arm_buckets` | Filters act on `target_date` only |
| The fit half of `fit_and_score` | `fit_hour(train)` | Returns the `fit_pooled(..., market_id=False, doy=True, raw_columns=False, bias_by="season")` fit and `train_y` in the shape `state_from_fits` takes. The scoring half stays in the runner |
| `stage_build` (build only) | `build(cfg)` | Record windows through the bound `extract_market`, the y-free frame, the NBM tables. Pool rows (arm C) are not ported |

**Not ported:** statistics, Holm, the contrasts, the look and score stages, K112, the arm C pool, S (MG-1), the §7
gate, and the date-token output guard (`Writer`, `_walk`, `guard_file`, the gzip header scan).

The guard is about 1,000 lines. It protected sealed windows during a one-off, multi-stage history run with a
look. Its job is done in the module by **hard bounds in code**:

- `fit` refuses any row with `target_date > 2025-12-16`, and any 2026-dated input;
- `emit` refuses any target date outside `[first, last]`, and a window not named by the forward receipt;
- neither command writes outside its output directory under `data/yearround_refit/`;
- neither ever reads `C:\t\l2\p2` or a panel store.

That is a scope reduction. Master may instead want the guard ported as well; see Q-G in §8.

### 2.2 The serve side

Shadow emission uses MG-2's serve math unchanged: `mg2_p3d_n.serve_distribution(state, ...)`.

- That function is MG-2's copy of `pooled_residual_model`'s `MeanModel.features` / `predict`, the scale model and
  `predictive_distribution`. The bound control already pins it to the trainer (an exact reproduction of
  `dev_P3d_N.jsonl`).
- The module adds no serve math.
- The parity it adds is for B's new centre set and months. A test fits a small synthetic B state through
  `fit_hour` → `state_from_fits`. It then checks that `serve_distribution` on each training row equals the
  trainer-side `predictive_distribution` from the same fit, to 1e-12 per bucket. The rows cover Dec 17–31,
  Jan–May and both seasons.

**Gap found while designing:** `mg2_p3d_n.emit_rows` applies rule C5's training-coverage gate (`08-01..12-16`), so it
drops every Dec 17 – May 31 row and cannot emit B. The module therefore carries its own row loop.

- The loop has the same gate as `emit_rows` (cutoff hour in `INTRADAY_CUTOFF_HOURS`, `local_hour >= cutoff_hour`,
  `usable_v2_mean`, a replay observation with `high_so_far` and `current_temp`). Its coverage window is
  `12-17..05-31`, not C5's.
- It calls the public `scan_replay`, `scan_replay_as_of` and `as_of_capture` read-only. It does not call the
  private `_replay_index`, `_read_snapshot` or `_observations`.
- An equivalence test proves the copied loop. With a synthetic state and the coverage window set to C5's, the
  module's rows, statistics and distributions equal `emit_rows`'s byte for byte on a synthetic replay.

**Feb 29.** `mg2_p3d_n.nearest_centre` has no Rule L and raises on Feb 29. The forward window 2026-12-17..2027-05-31
has no Feb 29. `emit` refuses a Feb 29 target date with a named error rather than patching B-bound code, and any
later window with a leap day needs a ruling.

### 2.3 Real-data equivalence re-run (343b's original scope)

**Design.** One `equivalence` run on the WS through `workstation_heavy.ps1 -Queue`. It uses the frozen run's pinned
inputs (the same corpora, fetch manifests and L9 corpus, all by sha) and writes a **new** records root. It never
touches `C:\t\L59` or the frozen run's directories. It has three parts:

1. **Build stage.**
   - The module's `build` writes records.
   - Each records file's decompressed-payload sha256 (v8's identity rule, because the gzip MTIME varies) must
     equal the frozen run's `payload_sha256` for the same (market, centre).
   - The y-free row frame's key set and its non-label columns must equal those of v12's `market_frame` run
     in-process on the same records, to 1e-9.
   - The frozen side is a **path/sha list only**: the build stage's `walk.csv` payload shas. Master or L59
     supplies it; the comparator opens nothing else of that run.
2. **Row sets.** For arms A and B, every hour 13–16 and every fold 2021–2025, plus the forward set (fold 2026 for
   B): the training row-key set's sha from `arm_rows` must equal that from v12's `arm_training`. The scored
   row-key set's sha must equal v12's for each fold (the prereg's 660 dates × US10 × 13–16 for the history folds).
3. **Fits and predictions.**
   - For each (arm, hour, fold), the module's `fit_hour` and v12's `fit_and_score` fit (v12 is loaded by
     `importlib` from the pinned runner file after its sha check, as v12 itself loads R-P2's `station_pool_corpus`)
     run on identical training frames with `OMP/MKL/OPENBLAS_NUM_THREADS = 10`.
   - On the fold's held-out rows, the comparison is `yhat`, `s` and the full predictive distribution, to 1e-12 per
     bucket.
   - **No Brier, log loss or label is compared or printed.** The report holds counts and max |Δ| only.
   - The forward B fit is compared the same way on the fold-2026 set, on a fixed set of synthetic serve rows.
   - Finally, the forward state round-trips through `write_state` / `load_state`. `serve_distribution` on those
     rows must equal the in-process fit to 1e-12.

If the frozen run persisted per-row `yhat`/`s`, a direct comparison against them could be added. Which outputs the
score stage kept is for master or L59 to say (Q-E, §8); the design does not depend on it.

**Cost.** Estimated from row 28's run log (operational timings and memory peaks only):

- the rebuild stage took about 1 h, with a peak job memory of about 5 GB;
- the look stage (4 arms, 3 folds) and the score stage (4 arms, 5 folds) took about 2 h each, with peaks under
  7 GB.

The equivalence run needs:

- one build, about 1 h;
- for A and B, 5 folds × 4 hours = 40 fits, doubled for v12 = 80 fits, plus 2 forward B fits. That is roughly
  2.5–3 h, at the score stage's rate of roughly 2 min per fit.

**Total: about 4 h wall in one WS slot (thread cap 10), with a peak under about 7 GB**, below the 12.8 GB 40% line
the row-28 run used. Before launch, disk is measured from the frozen records manifest (sizes only), with the same
45 GiB free-space floor as row 28.

It runs after master's code review of 343b and before 343b lands. It holds no capture-host time and needs no
admission window: it is a WS run.

## 3. Effective WU print-cutoff semantics

The module introduces **no cutoff logic of its own**. Both sides inherit the bound semantics, imported read-only.

- **Training:**
  - Rows come from the bound `extract_market`. `high_so_far` is the max over WU hourly rows with
    `minute_of_day <= H*60`, and `current_temp` is the last such row (`feature_model` 1111–1117, as the bound
    trainer).
  - Scored rows need the 07Z NBM posted at or before their own cutoff instant. Training rows use `nbm_at_cutoff`
    (07Z → 01Z → 00Z by LastModified ≤ cutoff), with prereg §3.3b's fill-from-forecast and its 5% per-month cap.
    The cap is enforced at fit time.
- **Serving (emit):**
  - The cutoff hour is the snapshot's captured `cutoff_hour`, the effective WU printed cutoff the capture path
    recorded. It is never recomputed from wall-clock time.
  - `high_so_far` and `current_temp` come from captured METAR rows observed at or before h:00, keyed on the
    observation instant (`metar_observation_instant`, the raw DDHHMMZ group). The state's `late_report` rule
    applies (`last_in_hour` or `receipt_by`), as do its `conversion` hook and the `usable_v2_mean` anchor
    (finite, available at or before capture).
- **Disclosed asymmetry** (prereg §3.3; MG-2 rule C1): history F is WU-hourly, while serve F is captured METAR.
  The module does not hide it. `fit_manifest.json` records `train_F_source: "wu_hourly"`, and the emit receipt
  records `serve_F_source: "captured_metar"`. The forward test is where METAR-F parity is confirmed.

## 4. Captured-input replay

- `emit` reads only:
  - the captured snapshot layout (`row_key, snapshot_id, market, target_date, local_hour, cutoff_hour, v2_mean,
    v2_stddev, v2_available_at, captured_at_utc`, the `mg2_p3d_n.SNAPSHOT_COLUMNS`);
  - the captured replay folders.
- An input screen refuses any label, settlement or price column.
- Both input modes of MG-2 rule C4:
  - `last_in_hour` (PRIMARY against MG-1);
  - `as_of_capture` (PRIMARY against the market). Each row reads only the latest replay snapshot captured at or
    before its own capture time.
- **Replay determinism.** The output is a pure function of (state sha, snapshot file sha, replay folder shas, window,
  input mode, module sha). Re-running `emit` on the same inputs must reproduce `shadow_rows.jsonl` byte for byte,
  and the receipt records every one of those shas.
- **When it runs.** Because emission is deterministic on captured inputs, B's shadow forecasts do not need a daily
  job. `emit` runs on the WS when the forward lane allows forward dates to be read, on a transferred copy of the
  captured inputs. The state sha is frozen before 12-17, and the as-of-capture rows prove that no later
  information entered. This is proposed because it keeps the module:
  - off the capture host (`mg2_p3d_n` already refuses it through `r0_ols_floor_challenger`);
  - out of every scheduler change;
  - inside the embargo (prereg §9.3: no forward date before the PT-1 and F8-MH looks).
  A daily on-host emitter is rejected for the same three reasons.
- `emit` requires `--forward-receipt`: the owner-approved forward embargo line and the forward prereg's frozen sha.
  It refuses without it, and refuses any target date outside the receipt's window.

## 5. Shadow-only: what the module never does

- It never serves:
  - it is not imported by any capture loop, serving, release or trading module (§7);
  - it writes no `release-binding.json` and no release manifest;
  - it does not call `release_lifecycle`.
- It touches no MG-2 file, no B-bound file and no PT-1 file. It imports these read-only, each sha-pinned and
  recorded in `fit_manifest.json`:
  - `pooled_residual_model`;
  - `mg2_p3d_n`;
  - `mg_serve_core`;
  - `feature_model`;
  - `ols_floor_ladder`;
  - `r0_ols_floor_devfit` (`usable_v2_mean`).
- It makes no scheduler change, no `config/` change and no new required environment variable.
- It has no live, order, promote, execute, place or cancel path. The wrapper refuses those arguments (§9), and the
  module has none.
- Its outputs hold distributions and shas only. They never hold a label, settlement, Brier, log loss or price.

## 6. Plug-in to the forward prereg (L59's lane)

L59 is drafting `claude/row28b-forward-prereg-draft-20261103`, which is not yet pushed. The fields below are
**proposed**. The coordinator reconciles them with L59.

| Field (proposed) | Meaning |
| --- | --- |
| `candidate_id` | `row28_B` |
| `module`, `module_source_sha256` | `weather.calibration.yearround_refit` and its file sha at the frozen tip |
| `fit_manifest_sha256` | `fit_manifest.json` bytes |
| `state_sha256`, `state_sidecar_sha256` | The `p3d_n_state.pkl` and `p3d_n_state.json` bytes |
| `state_schema` | `mg2_p3d_n_state/1` |
| `arm`, `centres`, `season_of`, `hours` | `B`, B's 11 centres, the month → season map, 13–16 |
| `training_window`, `training_rows_sha256`, `bucket_space_sha256` | The fold-2026 B set (target dates at or before 2025-12-16) and its key-set sha |
| `upstream_sha256` | `{pooled_residual_model, mg2_p3d_n, mg_serve_core, feature_model, ols_floor_ladder, r0_ols_floor_devfit}` |
| `sklearn_version` | The HGB pickle pin; `emit` refuses a mismatch |
| `conversion`, `late_report` | Copied from the bound state `c6cc39f7…` |
| `train_F_source`, `serve_F_source` | `wu_hourly`, `captured_metar` |
| `shadow_first`, `shadow_last`, `coverage_window` | `2026-12-17`, `2027-05-31`, `12-17..05-31` |
| `input_modes` | `last_in_hour` (vs MG-1), `as_of_capture` (vs market) |
| `forward_receipt_sha256` | The owner's embargo-line record that `emit` requires |
| `shadow_rows_sha256`, `emit_receipt_sha256` | Per emission run |
| `equivalence_report_sha256` | The §2.3 PASS report at the module's landing tip |
| `frozen_before_utc` | The fit instant. It must be before the forward window opens |

## 7. Roll class and loop isolation

If any capture loop imports the module, it is roll-sensitive: supervisors fingerprint imported sources. The design
keeps it out of every loop import closure:

1. **Runtime refusal.** At import, the module refuses a production importer with the same frame walk and prefixes
   as `mg2_p3d_n._refuse_production_import`:
   - the prefixes are `weather.operations`, `.market`, `.model`, `.serving`, `.trading`, `.capture`, `.sources`,
     `.execution`, `maker_core` and `app`;
   - it inherits the capture-host refusal through its `mg2_p3d_n` import.
2. **Lazy heavy imports.** numpy, pandas, sklearn and the bound modules are imported inside functions. Importing the
   module does no I/O.
3. **Static ratchet.** A test walks every `src/` module's AST and asserts that only `tests/` and the module itself
   import `weather.calibration.yearround_refit`. It also asserts that the module imports nothing under the
   production prefixes, apart from `weather.market.market_registry` and `weather.model.mg_serve_core`, which are
   read-only data and math. That matches `mg2_p3d_n`'s own allowed imports.
4. **The verdict comes from `scripts\ops\roll_verdict.ps1 -Branch <b>`, never by hand.** The expectation is
   roll-free for the module file, because no supervisor imports it. The allowlist line in
   `workload_admission.ps1` is `.ps1` and so roll-free, but the S4U guard parses that file every tick. Its landing
   needs guard-parse evidence at the combo tip, as 343a's did.

## 8. Test plan

All tests are synthetic, focused, and run through `workstation_heavy.ps1 -Queue` with a flat `--basetemp` that is
deleted afterwards.

- **Rows and centres:**
  - Rule L (2024-02-29 → 02-22);
  - both centre sets;
  - the wrap-free = wrap-aware assertion;
  - B's filter on `target_date` (May 31 rows in the 06-07 window map to 05-23; Dec rows in the 01-08 window
    map to 12-24);
  - the fold hold-out by season-year;
  - the forward set = `arm_training(..., 2026)`;
  - §3.6 buckets.
- **Hard bounds:** the run refuses on:
  - a row dated after 2025-12-16, or any 2026 input;
  - a sha mismatch on any input or bound module;
  - a write outside `data/yearround_refit/`;
  - a state sha equal to the bound `c6cc39f7…`, or listed in `release-binding.json` (`emit`);
  - an `emit` target outside the receipt window;
  - a Feb 29 `emit` target;
  - a missing `--forward-receipt`;
  - a label, settlement or price column in the emit inputs.
- **State:** `state_from_fits` → `state_problems` is empty, `write_state` is write-once, `load_state` checks the
  sha, `provenance.shadow_only` is set, and `conversion`/`late_report` equal the bound state's.
- **Train/serve parity (§2.2):** on Dec 17–31 and Jan–May rows, `serve_distribution` equals the trainer
  `predictive_distribution` to 1e-12. Probability mass sums to 1 within 1e-12, with no negative bucket.
- **Emitter:** the module's loop equals `emit_rows`'s on the C5 window (rows, statistics and bytes). `as_of_capture`
  never admits a METAR row received after the row's capture. Re-emission is byte-identical. The receipt's shas
  match.
- **Equivalence harness:** on a small synthetic records set, `equivalence` passes, and it fails when one record
  byte, one row key or one fit seed is changed. The report holds no label, score or price (walked as in R24's
  no-value test).
- **Loop isolation (§7):** the runtime refusal from a `weather.operations.*` importer, the static AST ratchet, and
  `test_import_architecture` unchanged and passing.
- **Admission (lands with the module):** `test_yearround_refit_admission.py` beside
  `test_r0_full_year_admission.py` covers:
  - exact-name admission in both mirrors;
  - refusal of the `_x` sibling;
  - live/execute/place/cancel/promote refusals before any lease;
  - the B-look argument refusal kept;
  - the full-list pin gaining the entry.
- **Schemas:** a new family `schema_families/yearround_refit.py` registers `yearround_refit_fit_manifest/1`,
  `yearround_refit_shadow_receipt/1` and `yearround_refit_equivalence/1`, and the strict schema audit is green.
  A pin test asserts that the state schema equals `mg2_p3d_n.STATE_SCHEMA`.
- **Real data:** the §2.3 equivalence re-run, once, on the WS, before landing.

Open questions for master:

- **Q-S:** `fit_kind` (§1).
- **Q-G:** a scope reduction of v12's date-token output guard versus porting it (§2.1).
- **Q-E:** whether the frozen score stage kept per-row `yhat`/`s` for a direct comparison (§2.3).
- **Q-W:** the WS-side, after-the-fact emission model (§4), versus any daily cadence.

## 9. Allowlist line: with the module, not before

Per master's 343 ruling, the allowlist line for `weather.calibration.yearround_refit` lands in the same change as
the module, and not before. That change contains:

- `Get-WeatherWorkstationOfflineModule` in `scripts/ops/workload_admission.ps1`;
- the Codex hook mirror `.codex/hooks/pre_tool_use_host_load.py`;
- its own admission test;
- `README.md` (the operator command catalog) and the owning runbook for the three commands.

Until then, nothing names the module in any allowlist, hook mirror or test, and row 28's remaining stages stay on
launcher v6 under the one-off exception. This note adds no allowlist line.
