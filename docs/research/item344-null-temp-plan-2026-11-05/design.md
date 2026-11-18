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

## 1a. Field-by-field proof: what each serve/replay helper does with a null last row (master Q1, 2026-11-05)

- **`mg_serve_core.observations_at_cutoff`** (`src/weather/model/mg_serve_core.py:108-129`):
  - `:119-121`: `temp = row.get("temp_native")`, then `if temp is None: continue`. The row is dropped **before** its
    instant is parsed (`:122`). It never enters `kept`, the instant-keyed dict of `float(temp)` at `:125`.
  - `:128-129`: `latest = max(kept)` is the latest NON-null instant. It returns `kept[latest]`, `max(kept.values())`
    and `len(kept)`.
  - So the null row is skipped as a **whole row**. It is excluded from `current_temp`, from `high_so_far` and from
    the count `n`. The helper returns no dewpoint, pressure, wind, cloud or humidity at all. Its only consumer,
    `state_features` (`:531-552`), builds the serve vector from `high_so_far` and `current_temp` only (`:548`).
- **`r0_ols_floor_challenger.observations_at_cutoff`** (`src/weather/calibration/r0_ols_floor_challenger.py:572-593`):
  - It has the same body, line for line: skip at `:583-585`, `kept` at `:589`, latest at `:592-593`.
  - It too returns only `(current_temp, high_so_far, n)`. So it is also a whole-row skip with no non-temperature
    field. Its callers keep those three values only: `scan_replay_observations` `:628-632`, and `mg2_p3d_n.py:361`
    (cite only), which keeps `current` and `n`.
- **`pooled_residual_model.scan_replay_n`** (`src/weather/calibration/pooled_residual_model.py:1101-1133`):
  - It has no row logic of its own. It calls the injected helper (L3's, `:1190`) at `:1128`.
  - It emits `current_temp`, `main_high_so_far` and `n_rows` from that helper. Its `high_so_far` comes instead from
    `observed_running_max.running_max_since_midnight(..., metar_only=True)` (`:1129-1130`).
  - It emits no non-temperature field (`:1131-1132`).
- **Do the helpers differ? No.** The two `observations_at_cutoff` bodies are identical (mg_serve_core's copy is pinned
  equal to its source, `mg_serve_core.py:13`), and `scan_replay_n` adds no null handling of its own. The one
  difference is the source of `scan_replay_n`'s own `high_so_far` (`running_max`, not the helper). That is outside
  item 344, because the trainer's `high_so_far` already skips nulls (`feature_store.py:1234`).
- **Consequence for scope.** Master's condition for temperature-only was that serve keeps the other fields from the
  null-temperature row. It is NOT met. No helper keeps anything from that row; each drops it whole.
  - The field-by-field match is therefore a **whole-row** skip. `current_obs` becomes the latest row at or before
    the cutoff whose temperature is non-null, and every field read from `current_obs` follows it.
  - The helpers expose no non-temperature fields. So whole-row is the only reading consistent with them, not a
    measured parity for those fields.
  - Side note, no change asked: the parity scorecard's own WU serving surface takes `latest = rows[-1]`
    (`train_serve_feature_parity.py:546`). That surface is not one of the three helpers.

## 2. The change, at the next retrain (not before)

- **Semantics.** In `build_historical_feature_record`, `current_temp` becomes the temperature of the latest row at or
  before the cutoff whose temperature is non-null. This is what all three serve/replay helpers already do.
- **Scope: whole row (master Q1, 2026-11-05, decided by the §1a proof).** `current_obs` becomes the latest row in
  `obs_before` whose temperature is non-null. This matches the helpers' `continue` before parsing, which drops the
  null row whole. Every field read from `current_obs` follows it:
  - `current_temp` (`:1258`) and the at-print `live_reading` (`:1243`), and so `rise_from_7am` and `warming_rate_2h`
    (`:1263-1275`);
  - dewpoint `:1290`, pressure `:1293`, the wind and cloud groups `:1314-1337`, and humidity and wind `:1388-1392`.

  `temps_before` (`:1234`) is non-empty exactly when such a row exists, so the existing `return None` at
  `:1235-1236` covers the empty case. The earlier temperature-only proposal is withdrawn: the proof shows serve keeps
  nothing from the null-temperature row.
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
- **Not done now (master Q2, 2026-11-05: no source edit now; it is a retrain-time step in item 344).** A
  null-temperature case kind inside the gate's manifest runner. The runner builds its serving surface with `float(row["temp_native"])` over every row
  (`train_serve_feature_parity.py`, `_wu_sources` `:539`, the `float` at `:547`), so a null row cannot be expressed in a manifest
  fixture without changing the scorecard.
- **At the fix,** the trainer pin flips to assert `current_temp == LAST_NON_NULL`, and the gate fixture to assert no
  finding.
