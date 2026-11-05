# Item 344: trainer adopts the serve/replay null-temperature semantics (DESIGN NOTE, plan only)

Status: **PLAN ONLY.** Lane L59, WS, 2026-11-05, from `origin/master` `94d59df3e`. Nothing here changes code. The fix
lands only at the next retrain or model change, through the parity, retrain and edge gates, with its release
binding ([item 344](../../roadmap/items/item-344-trainer-null-last-pre-cutoff-temperature.md); master ruling
2026-11-05; [EF §10ay](../../operations/ESTABLISHED_FINDINGS.md)). No data file was read for it.

## 1. The mismatch (line numbers verified at `94d59df3e`)

- **Trainer.** `weather.model.feature_store.build_historical_feature_record` (`src/weather/model/feature_store.py:1194`,
  `strict=False` default at `:1215`):
  - `obs_before` = every row with `minute_of_day` at or before the cutoff (`:1226-1230`);
  - `current_obs = obs_before[-1]` (`:1233`), whatever its temperature;
  - `high_so_far` already skips nulls (`temps_before`, `:1234`);
  - `current_temp = row_temp_native(current_obs)` (`:1258`). With `strict=False` (`:1259`), a null is carried on as a
    null `current_temp`. The at-print `live_reading` takes the same row (`:1243`), and so do the derived
    `rise_from_7am` and `warming_rate_2h` (`:1263-1275`).
- **Serve and replay** take the latest row with a NON-null temperature:
  - `weather.model.mg_serve_core.observations_at_cutoff` (`src/weather/model/mg_serve_core.py:108`; null skip
    `:120-121`, latest `:128-129`);
  - `weather.calibration.r0_ols_floor_challenger.observations_at_cutoff`
    (`src/weather/calibration/r0_ols_floor_challenger.py:572`; skip `:584-585`, latest `:592-593`). The B-bound
    `mg2_p3d_n._observations` reaches it at `src/weather/calibration/mg2_p3d_n.py:361`; that file is cited only, never
    edited;
  - `weather.calibration.pooled_residual_model.scan_replay_n`
    (`src/weather/calibration/pooled_residual_model.py:1101`), which calls the injected helper at `:1128` (L3's helper
    at `:1190`; the history cache at `:1402`).

  All three docstrings say "same semantics as the trainer". The null last row is where that claim fails.
- **Trainer-side callers of the builder:**
  - `model_features.find_analog_days` (`src/weather/model/model_features.py:1777`, call `:1807`);
  - `pooled_feature_assembly.build_market_records` (`src/weather/calibration/pooled_feature_assembly.py:774`, call
    `:906`);
  - the parity scorecard's `train_serve_feature_parity._base_training_record`
    (`src/weather/reporting/scorecards/train_serve_feature_parity.py:512`, call `:521`);
  - `feature_model.build_feature_records_for_model` (`src/weather/calibration/feature_model.py:952`, call `:987`).
- **History rate.** 2 of 28,936 (market, date, hour) keys: nyc 2024-03-13 h13 and san-francisco 2022-03-17 h13
  (EF §10ay). The reference fit carried the NaN into the HGB through sklearn's native missing-value handling.

## 2. The change, at the next retrain (not before)

- **Semantics.** In `build_historical_feature_record`, `current_temp` becomes the temperature of the latest row at or
  before the cutoff whose temperature is non-null. This is what all three serve/replay helpers already do.
  - Concretely, `current_temp = temps_before[-1]` in row order. `temps_before` is already computed at `:1234`, and
    the function already returns `None` when it is empty (`:1235-1236`).
- **Scope: temperature only (recommended).** The at-print `live_reading` (`:1243`) and the derived `rise_from_7am` /
  `warming_rate_2h` follow `current_temp`.
  - The other row fields read from `current_obs` (dewpoint `:1290`, pressure `:1293`, wind and cloud groups
    `:1314-1337`, humidity and wind speed `:1388-1392`) stay on `current_obs`.
  - The serve helpers carry only temperature, so moving the other fields would be a separate parity question.
  - **Open for master:** temperature only, or move `current_obs` to the latest non-null-temperature row as a whole.
- **Gate.** The change lands only with a retrain or model change:
  - the parity gate first (the null-last-row fixture below must then show agreement);
  - then the retrain and edge gates and the release binding.
  - There is no serve-side change.
- **Frozen or pinned states this must not touch before then:**
  - the row-28b forward state (`d9badf41…`) and candidate B;
  - MG-1 and MG-2.

  Each reads this builder through `pooled_feature_assembly` or `feature_model`. A trainer edit now would move their
  state shas. This plan edits no trainer code path.
- **Expected effect.** About 2 keys in 28,936 change from NaN to the previous reading. This is not a lever and is too
  rare to power (EF §10ay). It is a correctness fix, judged by the parity gate, not by a score.

## 3. Tests on this branch (tests only; no source edit)

`tests/model/test_item344_null_last_pre_cutoff_temp_pin.py`, in both °F and °C. Every case uses the same rows, where
the last row at or before 13:00 has a null temperature.

- **Pin of today's divergence:**
  - the trainer's `current_temp` is None, while its `high_so_far` already skips the null;
  - `mg_serve_core.observations_at_cutoff` returns the latest non-null reading;
  - `r0_ols_floor_challenger.observations_at_cutoff` returns the latest non-null reading;
  - `pooled_residual_model.scan_replay_n` returns the latest non-null reading, on a one-snapshot `replay_inputs.jsonl`
    under `tmp_path`.
- **Parity-gate null-last-row fixture.** The gate's own comparator, `compare_feature_records`, is fed the trainer
  record and the serve helper's value on the same case, and reports the `current_temp` missingness finding. It
  compares the serve helper with the trainer instead of the trainer with itself.
- **Not done (needs a source edit, so it goes to master first).** A null-temperature case kind inside the gate's
  manifest runner. The runner builds its serving surface with `float(row["temp_native"])` over every row
  (`train_serve_feature_parity.py`, `_wu_sources` `:539`, the `float` at `:547`), so a null row cannot be expressed in a manifest
  fixture without changing the scorecard.
- **At the fix,** the trainer pin flips to assert `current_temp == LAST_NON_NULL`, and the gate fixture to assert no
  finding.
