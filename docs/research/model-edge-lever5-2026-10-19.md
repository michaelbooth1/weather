# Model-edge week 1: NBM code check (task 4) and lever 5 serving-stage re-trace, 2026-10-19

Status: development, **outcome-blind**. No labels, settlement rows or market prices were read for this
document. Code base: `origin/master` `6aac6de81a25bd939b954c5e7f29db02b2fd2fee` (`ML_MODEL_VERSION`
v0.5.12). Branch `claude/model-edge-codecheck-20261019`. Owner of the open item: EXHAUSTION_REGISTER
order 16 (L17, L19).

## 1. Task 4: does the served forecast read NBM station guidance into the band probabilities?

**Verdict: confirmed, with one correction to the wording.** No NBM-derived value reaches the served
band probabilities, neither as a model feature nor through any post-processing floor, clip or lock-in.
FINDINGS_DIGEST line 54 ("the active artifact selects no NBM, NWS-grid or HRRR column") holds for
the HGB feature model. The NWS **hourly** forecast (`nws_hourly`, the `forecastHourly` point product,
not the `nws_grid` column) is one vote in the `forecast_high` median, so an NWS product does reach the
bands, but no NBM, NWS-grid or HRRR column does. `guidance_physical_floor` is misnamed: it is an
observation floor and consumes no guidance.

### 1.1 Active artifact

- Binding: `artifacts/releases/` is absent on `origin/master`, so `release_serving` returns
  RESEARCH_UNBOUND and `toronto_model.py:133-150` takes the global-artifact branch (production state as
  recorded in the 2026-09-18 audit; not re-read on the host here).
- Gate: `artifacts/manifests/f_family_secondary_artifacts.json` (sha256 `78a11bd2…`, generated
  2026-07-07) sets `serving_gate.mode = ml` for all 11 F markets, so every market takes the feature path
  (`model_features.py:1349-1371`).
- Atlanta instance artifact: `artifacts/models/hgb/feature_model_hgb_atlanta.pkl`, LFS oid / sha256
  `9f045926126ab37bbc71b2c7db97b79cda8061c36c0fae93f2e12495493c9b9f`, 14 cutoff bundles (7..20), every
  `probability_temperature` 1.0, no `ordinal_smoothing`, `blend_weight` 0.85 at hour 15. Its 27 selected
  columns: `current_temp, dewpoint_c, forecast_gap, forecast_high, high_so_far, hours_at_peak, humidity,
  live_reading_minus_high, live_reading_temp, minutes_since_cutoff, pressure, pressure_trend_3h,
  rise_from_7am, warming_rate_2h, wind_speed_kmh`, six `cloud_*` and six `wind_*` one-hots.
- Fleet: the union of `feature_names` over all 12 HGB pickles (24-29 columns each) and all 12 LR
  fallbacks (`feature_model_coefs*.json`) and late-day LR files contains **no** column matching
  `nbm|nws|hrrr|grid|guidance|multimodel`.

### 1.2 One served instance end to end (Atlanta, US morning, captured feature vector)

The concrete instance is an Atlanta snapshot from the 111h extract (identifiers and captured feature
values only; see section 3.2 for the row). Its captured `feature_vector` carries NBM v1 values
(`nbm_prob_tmax_p10/p50/p90/mean`), because the live feature builder writes them. Path through the code:

1. Sources: `model_sources.py:208,226-228` adds `nbm_probabilistic_tmax` to every US market's sources;
   its parser on master is still `nbm-probabilistic-tmax-parser-v1` (`model_sources.py:129-131`; #190 v2
   is not landed).
2. Features: `extract_live_features` reads it (`model_features.py:1039`) and `us_guidance_features`
   writes `nbm_prob_tmax_*` (`model_features.py:542-613`); these are in `FEATURE_COLUMNS`
   (`feature_store.py:221`) and so in the persisted feature vector.
3. **Model input: dropped.** `_evaluate_feature_model_for_cutoff` builds `feat_dict` over
   `FEATURE_COLUMNS` and then `pd.DataFrame([feat_dict], columns=bundle["feature_names"])`
   (`model_features.py:1257-1269`): only the 27 artifact columns survive. The LR fallback likewise reads
   only its `feature_names` (`:1299-1311`).
4. Post-processing in `_estimate_distribution_result` (`model_distribution.py:144-614`):
   - `guidance_floor = guidance_physical_floor(...)` (`:222-228`) is the max of `high_so_far`,
     `current_temp`, `trusted_current_max` and the rows of `wu_history`, `wu_current`, `metar`,
     `eccc_swob` only (`model_features.py:222-252`). **No guidance source.**
   - `forecast_ensemble_metrics` (`:229-236`) pools `open_meteo`, `weather_forecast`, `eccc_citypage`,
     `nws_hourly`, `global_ensemble` (`model_features.py:365-414`). No NBM, no `nws_grid`, no HRRR.
   - `guidance_physical_states` (`:237-240`) does compute an NBM validity state
     (`model_features.py:339-362`), but the only reader, `forecast_signal` (`:242-252`), looks up the five
     forecast sources above; the NBM state is never read.
   - Hard floor (`:298-308`, `:447`), observed floors (`:502-511`), the lock-in anchor (`:515-522`,
     which stores `guidance_floor` as a diagnostic field only, `:1233`), lock-in stages and the v4
     pre-lock-in floor (`:1525-1541`), the calibration (`:557-566`) and the overlock guard (`:568-572`)
     read observations, forecasts in the pool above, or artifacts. None reads NBM.
5. Bands: `model_presentation.py:697-741` sums the final distribution per band and calls
   `calibrate_market_probability`, which returns the raw probability after the hard 0/1 floor because
   every `probability_calibration*.json` sets `preserve_distribution_coherence: true`
   (`calibration_runtime.py:504-526`).

Dynamic check (synthetic record, real Atlanta HGB, current code): removing the NBM source, or adding
+10 °F to every NBM value, changes the final vector by exactly 0 at every hour while
`extract_live_features` shows `nbm_prob_tmax_p50 = 89.0` in the feature dict. The same two variants
(`nbm_removed`, `nbm_perturbed`) are in the lever-5 replay so the host run proves it on every captured
dev snapshot.

Side note (not NBM): the HGB `forecast_high` feature includes `open_meteo_global_models` (four global
models, `model_features.py:1053-1061`), while the distribution's own `forecast_ensemble` omits it
(`model_distribution.py:229-236`), so the two `forecast_high` values can differ in one snapshot.

## 2. Lever 5: the 13 stages re-traced on `origin/master`

"No-op" means the stage cannot change the served vector in the current fleet configuration (all 12
markets on the HGB feature path, WU inputs empty). Line numbers are `model_distribution.py` unless noted.

| # | Stage (2026-09-18 audit list) | 06-30..10-05 | Now | Why |
| --- | --- | --- | --- | --- |
| 1 | Heuristic late-day lock-in (S1) | no-op | **live** | reads the lock-in anchor (`:515-522`, `:1407-1415`); anchor = observed same-day station high since v3 (10-06) |
| 2 | Learned lock-in (S2) | no-op | **live** | anchor view supplies `max_native` and `max_times` (`:1257-1260`); `signals.py:408-428` |
| 3 | High-has-stood (S3) | no-op | **live** (13-15 h, conditional) | same anchor view; `signals.py:506-579` |
| 4 | Expanded late-day lock-in (S4) | no-op | **live** (conditional) | `signals.py:617-707` |
| 5 | Standing-high partial (S5) | no-op | **live** (conditional) | `signals.py:755-878` |
| 6 | `apply_late_day_lockin` | no-op | **live** | `:1467-1473` with anchor high |
| 7 | Calibration taper (S7) | no-op | **live** | `resolution_weight` = effective lock-in strength (`:557-566`) |
| 8 | Late-day continuation blend (S6) | no-op | **live at cutoff 15-17 only** | `observed_bucket` = anchor bucket (`:523-532`); `late_day_model_coefs*` have keys 15/16/17 only |
| 9 | Bucket-transition blend | no-op | **no-op (input)** | reads the WU cutoff-aligned high only (`model_features.py:1402-1422`) |
| 10 | Intraday tail target | no-op | **no-op (structural)** | `intraday` is `None` on the feature path (`:788`, `:838`); stage needs it (`:993`) |
| 11 | Learned METAR live signal | no-op | **no-op (structural)** | needs a WU high (`signals.py:316-319`) **and** the feature-path signal list never includes it (`:1580-1611`) |
| 12 | WU-floor residual | no-op | **no-op (input)** | needs a WU high (`signals.py:344-354`) |
| 13 | Validated current-max floor (Miami) and the current-max live-signal member | no-op | **no-op (input)** | `trusted_current_max` is `None` without a WU high (`feature_store.py:394-398`) |

Also inert, not input-dead: forecast floor/pull (skipped on the feature path, `:1073-1076`), the
dormant `calibrated_weights`/`forecast_error_model` (empirical branch only), the market-bin calibration
(dead under `preserve_distribution_coherence`). The **110g afternoon residual centering** is off by owner
decision (`afternoon_residual_centering.json` `component.enabled: false`, sha256 `1cbe4cc8…`,
`calibration_runtime.py:228-231`).

So of the 13, eight are live again (v3/v4 lock-in work) and five are still no-ops: two structural
(10, 11) and three because their only input is WU history (9, 12, 13).

**Zero-variant audit (2026-10-21, Toronto host run on `bd75f710a`).** `wu_residual_repointed`,
`metar_live_signal_repointed` and `intraday_tail_repointed` read exactly 0.000 in every hour band. All
three shims patch instance methods called as `self.<name>` (no import-by-value), and
`test_metar_signal_and_intraday_tail_shims_reach_the_call_site` proves the repointed value reaches the
call. Verdicts: intraday tail and METAR live signal are **structurally inert on any HGB market**, so their
variants cannot move the vector by construction (tail needs `intraday`, which the feature path leaves
`None`, `model_distribution.py:788`/`:838`, gate `:993`; the METAR vote is computed at `:423` but the
feature-path live-signal list at `:1580-1611` never includes it; also the repointed station high includes
the METAR rows, so `metar_bucket <= history_bucket` returns `None` at `signals.py:318`). The WU residual is
**data-conditional, not dead**: it fires only when the observed-support bucket (max of current temp, SWOB
same-day max, METAR temp) rounds above the repointed station high and that bucket's mass is below 0.001
(`signals.py:344-352`); `test_wu_residual_variant_can_change_the_served_vector` shows a synthetic case
moving the vector. For Toronto the station order is SWOB-first (`model_sources.py:279-283`), so SWOB rows
are already inside the repointed high and the gate can open only if the SWOB same-day-max field exceeds its
own rows; a single-snapshot trace confirms which gate condition closed.

## 3. Outcome-blind restoration check

### 3.1 What could be run on the workstation

Captured `replay_inputs.jsonl` for dev dates exist only on the capture host (the workstation holds one
June pilot folder). A full served-vector recompute on 07-31..09-29 therefore **cannot run here**. Built
instead:

- `tools/research/model_edge_lever5/stage_replay.py` (`python -m tools.research.model_edge_lever5.run
  replay`): re-runs the current pipeline on each captured snapshot unmodified (the base: current code
  on captured inputs, **not** the served vector of record; section 3.6) and once per variant,
  reports total-variation distance (an exact upper bound on any band's absolute change, for any banding;
  0 if and only if no band changes) and max bucket change, per hour block. Read-only, refuses targets
  outside 07-31..09-29, reads only `replay_inputs.jsonl`.
- `tools/research/model_edge_lever5/census.py` (`... run census`): the outcome-blind part that the 111h
  swarm cache allows (explicit column list; no `winner`, `settlement_*`, `floor*`, `bands.parquet` or
  price column is decoded).

### 3.2 Census results (111h swarm cache, 110,807 snapshots, 626 market-days, 11 US markets, targets 08-01..09-29)

Run: `workstation_heavy.ps1 -Kind weather_heavy -Queue` (lease ticket 1), code at `1a711fa12`, climatology
read from the workstation's prior-year `data/wunderground/<icao>/daily` copy (the serving cache drops every
row of the target year, so nothing dated 2026 enters). Output JSON sha256
`261a4ff17ace53e060231538af603317dee55a9361a8c8f2e94684fb5f4deabe` (workstation scratch, not committed).
Columns decoded: identifiers, local/cutoff hour, `model_version`, `high_so_far`,
`guidance_physical_floor`, `forecast_high`, `nbm_prob_tmax_{p10,p50,p90,mean,physical_valid_flag}`.

- **Task 4 coverage:** 36,498 of 110,807 served snapshots (32.9%) carried NBM v1 values in the captured
  feature vector (per market 26.9-39.2%); every row was served as `v0.5.10 HGBC`. Concrete instance:
  `atlanta|20260903T080212918889-0400` (target 2026-09-03, 08:02 local, cutoff 8):
  `nbm_prob_tmax_p10/p50/p90 = 93/95/97 °F`, `mean 95`, valid flag 1, `high_so_far 78.08`,
  `guidance_physical_floor 82.94`, `forecast_high 96.425`. By section 1.2 step 3 the HGB saw none of the
  NBM values; the band vector is a function of the 27 columns plus observation/forecast post-processing.
- **110g centering, re-enabled as fitted:** every one of the 18,548 snapshots at local hour 15-18
  (16.7% of all snapshots) selects a `market=<m>|hour=<h>` context with a non-zero shift, so 100% of
  in-window vectors change (lower bound; the disagreement smoothing term is extra). Stage-level |shift|
  (an upper bound on the stage's TV on integer buckets): mean 0.49, median 0.39, p90 1.00, max 1.31 °F.
- **Bucket transition, re-pointed on the station high at the cutoff:** the serving code's own sample
  reaches the 20-day minimum on 14,660 of 110,077 snapshots (13.3%), blend weight 0.012-0.0588 (mean
  0.031 when active), so stage-level TV <= 0.0588. Changed share by market: Miami 57%, Houston 35%,
  San Francisco 15%, Austin 13%, Los Angeles 11%, Atlanta 7%, others 1-3%. Sample size median 10, max 49.

### 3.3 Per-stage result

Final-vector numbers (max/mean band change, fraction of snapshots changed) come from the 12-market
replay of section 3.5 and are measured against the current-code base, not the served vector (3.6);
the stage-level numbers above bound one stage, not the vector after the later floors, lock-ins and
calibration temperature.

| Stage | Change tested | Result | Status |
| --- | --- | --- | --- |
| 10 Intraday tail | give it the station bucket | cannot act: `intraday` is `None` on the feature path for all 12 markets (ml gate); replay changed fraction 0 in all 12 markets (3.5) | **CLOSED** (code + 12-market replay) |
| 11 Learned METAR live signal | give it the station high | the feature-path signal list never carries it; replay changed fraction 0 in all 12 markets | **CLOSED** (code + 12-market replay) |
| 12 WU-floor residual | read the station high | acts only when live support exceeds the anchor, which is the max of the same rows; replay changed fraction 0 in all 12 markets | **CLOSED for the dev window** (data-inert on every captured snapshot; the gate can still open in principle) |
| 13 Trusted current max (Miami floor + live-signal member) | validate METAR max-since-07:00 against the station high | final vector changes on 1-11% of snapshots outside Miami; Miami 62% (3.5) | **changes the vector; open** for a scored look |
| 9 Bucket transition | re-point on the station high at the cutoff | final vector: Toronto 99%, Miami 56%, Houston 36%, others 1-16% (3.5) | **changes the vector; open** |
| 110g centering | re-enable as fitted | final vector changes on 16-17% of all snapshots in every market, none before 13 h; largest mover (3.5) | **changes the vector; open**; a re-fit is label-defined (section 4) |
| Task 4 (NBM) | remove / +10 °F | replay changed fraction 0 in all 12 markets, while NBM values are present in nearly every US snapshot | **confirmed: NBM does not reach the bands** |

Nothing here is evidence of benefit or harm: no outcome was read. "Changes the vector" only means the
stage is not closed by the outcome-blind test; scoring it needs a registered look on permitted dates.

### 3.4 Host command (for the production agent; read-only, closed dates)

Master-agent review 2026-10-19: SAFE-WITH-CHANGES; the changes are in `stage_replay.py` (required
`--data-root`, fail-closed `folder_error` rows when the climatology / bucket-transition prior is empty or
the served HGB pickle does not load, base-run errors as rows, both outputs refused inside `data/`,
`--market`, `--max-folders`, `--budget-minutes`, resumable append-only `--out` with a header check,
one `TIMING` line per folder, incremental `--summary-out`, `--config-root` with the effective registry
path and the sha256 of `markets.json` and `locations.json` recorded in the summary).

Throughput on the workstation (synthetic Atlanta folder, real HGB, 9 runs per snapshot): 7 snapshots in
8.4 s, about 1.2 s per snapshot. At ~11k snapshots per market that is roughly 3.5-4 h per market, so run
one market per admitted window and resume.

```powershell
# capture host, 00:30-09:00, under the workload lease; serial; from a worktree of this branch with
# `git lfs checkout artifacts/models/hgb` done (artifacts resolve from the code checkout)
$env:PYTHONPATH = '<worktree>\src;<worktree>'
<venv>\Scripts\python.exe -m tools.research.model_edge_lever5.run replay `
  --market toronto --data-root <host repo>\data --config-root <host repo>\config `
  --budget-minutes 230 --out C:\tmp\lever5\replay-toronto.jsonl `
  --summary-out C:\tmp\lever5\summary-toronto.json
```

Re-running the same command resumes (folders with a `folder_done` row are skipped; a folder that
ended in a `folder_error` has no `folder_done` and is re-attempted, e.g. after `git lfs checkout`). Expected:
`nbm_removed`, `nbm_perturbed`, `intraday_tail_repointed`, `metar_live_signal_repointed` exactly 0
everywhere; any `folder_error` means no current-code base could be computed for that folder (the base is
never the served vector of record; section 3.6).

### 3.5 Final-vector replay, 12 markets (2026-10-21)

Toronto ran on the capture host (`bd75f710a`, 00:32-00:53 under the workload lease); all 12 markets then
ran on the workstation (code `a653a7c14`, tool `6a4c92d7b`, finished 08:06) from a checksum-verified copy of
the captured `replay_inputs.jsonl` files dated 07-31..09-29. Every market: 61 folders, 0 folder errors,
0 base errors, model kind `hgb` only. The workstation's Toronto file reproduces the host file row for row
(11,360 rows; identical `tv` and `max_bucket`; only the `attempt` and `seconds` run fields differ).
Outputs stay in the two hosts' scratch directories, not committed.

All-hours changed fraction / mean TV / max TV:

- **110g centering re-enabled:** 0.160-0.173 in every market, exactly 0 before 13 h (13-16 h about 0.50,
  17-23 h about 0.29). The largest mover: mean TV 0.0014 (Miami) to 0.0313 (Austin); max TV up to 0.871
  (Los Angeles), 0.763 (San Francisco), 0.749 (Chicago), 0.705 (Austin).
- **Bucket transition re-pointed:** Toronto 0.989 / 0.0178 / 0.295, Miami 0.557 / 0.0035 / 0.045,
  Houston 0.355 / 0.0043 / 0.049, Austin 0.158 / 0.0021 / 0.123, San Francisco 0.157 / 0.0014 / 0.034,
  Los Angeles 0.088 / 0.0026 / 0.119; the other six 0.012-0.047 with max TV <= 0.024.
- **Trusted current max re-pointed:** Miami 0.619 / 0.0022 / 0.146 (06-09 h 0.79, 10-12 h 0.99);
  elsewhere 0.010-0.105 (Denver 0.105 / 0.0020 / 0.181, Chicago 0.064 / 0.0011 / 0.176, Toronto
  0.042 / 0.0002 / 0.078).
- **Exactly 0 in every market and band:** intraday tail, METAR live signal, WU-floor residual,
  `nbm_perturbed`, `nbm_removed`. NBM values are present in nearly every US snapshot (for example
  Atlanta 10,796 of 10,805, Denver 10,769 of 10,769), so the two NBM zeros are measured on real NBM
  input, as section 1 predicts.

**NBM zeros are real, not a wiring no-op** (workstation check, 2026-10-21). The `nbm_removed` shim
(`stage_replay.py:220-222`) drops `nbm_probabilistic_tmax`; `nbm_perturbed` (`:223-225`, `_perturb_nbm`
`:182-196`) adds +10 native degrees to a deep copy that the pipeline reads. Served columns: none of the 12
markets' HGB bundles (14 cutoffs each), no feature or late-day coefs manifest and the `f_family_secondary`
manifest selects an NBM-derived column (`open_meteo_nbm_*` included); per-market name counts are 24, 27 or 29.
Real trace, Atlanta 2026-08-10 snapshot `20260810T150843696523-0400`, 15 h, `hgb`: removing NBM nulls
`nbm_prob_tmax_*` and the NBM guidance state; perturbing moves the reader's p10..p90 from 73..77 to 83..87 and
the state's representative 77 → 87; in both the served HGB row is identical (`model_features.py:1269`) and
final TV is 0. So the served HGB fleet does not consume NBM; NBM's only route to value is a new model.

### 3.6 Base = current code, not the served vector of record (M8 check, 2026-10-21)

Every delta in sections 3.3-3.5 is "current code ± variant on captured inputs". It is **not** a delta
from what was served: the unmodified replay does not reproduce the served vector on dev dates.

Check (outcome-blind): `python -m tools.research.model_edge_lever5.run served`
(`tools/research/model_edge_lever5/served_repro.py`, added in `64cbecca4`; branch
`claude/model-edge-codecheck-20261019` at `0941dc432afe8ff47291938479d17c2931ef3a6b`) compares the
unmodified replay of each snapshot with the record's `recorded_distribution`, which
`snapshot_store.py` writes as `model.get("distribution")` next to the sources it consumed (the replay
fidelity canary). It is a model output, not an outcome. Run: 732 folders, 128,594 snapshots, 0 folder
errors, 0 base errors. `max_abs` = max absolute per-bucket difference.

| market | n | share within 1e-9 | p99 max_abs | max max_abs |
| --- | --- | --- | --- | --- |
| atlanta | 10805 | 0.056 | 0.784 | 0.872 |
| austin | 10875 | 0.100 | 0.725 | 0.956 |
| chicago | 10819 | 0.062 | 0.883 | 0.952 |
| dallas | 10662 | 0.040 | 0.769 | 0.830 |
| denver | 10769 | 0.116 | 0.844 | 0.917 |
| houston | 10584 | 0.079 | 0.758 | 0.799 |
| los-angeles | 10432 | 0.043 | 0.869 | 0.968 |
| miami | 10561 | 0.171 | 0.754 | 0.976 |
| nyc | 10551 | 0.059 | 0.814 | 0.982 |
| san-francisco | 10512 | 0.224 | 0.859 | 0.971 |
| seattle | 10726 | 0.115 | 0.709 | 0.941 |
| toronto | 11298 | 0.143 | 0.662 | 0.891 |

By local hour band, all markets (share within 1e-9 / median `max_abs`): 00-05 0.247 / 0.0017; 06-09
0.112 / 0.0063; 10-12 0.098 / ~0; 13-16 0.042 / 0.060; 17-23 0.004 / 0.275. The late hours dominate,
matching the lock-in serving changes made after capture (section 2, stages 1-8).

Cause, code drift since capture (capture `model_identity` against the replay identity):
`model_version` differs on 100% of rows; `code_changed` includes `src/weather/model/model_constants.py`
and `model_distribution.py` on 100%, `market_registry.py` on 75,116 rows, `feature_store.py` and
`model_features.py` on 19,230 rows each. Not the artifacts: `artifact_hash` changed on 0 rows,
`active_model_kind` (`hgb`) differs on 0 rows, and 0 mismatched rows have an identical identity. Dev
captures span 490 distinct capture commits.

Consequences: the base of every lever-5 delta is current code. The EDGE-1 twin (T1/T0) dev deltas are
likewise "current code ± twin", not "served ± twin". Reproducing the served vector to 1e-9 on dev dates
would need a per-row replay at each row's capture commit, which no tool does (and EF §1k found the
June-July served bytes often never committed); forward reproduction (M8) is checkable only at a frozen
hash on forward rows. The A0 power figure used the served vector of record, so it is unaffected. Nothing
here says which code is better: no outcome was read. EF §10v.

### 3.7 EDGE-1 twin variants on dev inputs (3b, 2026-10-21; codecheck level)

Vector deltas against the current-code base (section 3.6), outcome-blind. No score was read and nothing
here is an edge claim: a dev delta is "current code ± twin", and the binding T1/T0 comparison is forward,
at the frozen hash. Tool: `claude/model-edge-codecheck-20261019` at
`0941dc432afe8ff47291938479d17c2931ef3a6b`; the twins run only when named in `--variants`. Run: 732
folders, 128,594 snapshots, 0 errors, `hgb` only, dev targets 07-31..09-29.

- **`t1_nws_hourly_only`** (EDGE-1 annex §1.1, the binding twin) empties the `open_meteo`,
  `weather_forecast`, `eccc_citypage`, `global_ensemble` and `open_meteo_global_models` payloads. Serving's
  own code then sets `forecast_high` to the NWS hourly day max and recomputes `forecast_gap`; with no NWS
  day max the variant equals the base. By construction T1 also removes those sources from the
  post-processing forecast votes. Miami: source count 1, disagreement `None`. Toronto has no
  `nws_hourly`, so T1 = base on all 11,298 rows. NWS fill is 1.000 elsewhere, except Los Angeles 0.997,
  Miami 0.998, Seattle 0.999.
- **`t0_climatology_prior`** (non-binding) empties every forecast payload; `forecast_high` becomes the
  target month's mean daily high from prior years only, and `forecast_gap` is recomputed.
- Served columns: no bundle selects a per-source forecast column. The forecast columns are
  `forecast_high` and `forecast_gap`, plus `forecast_source_count` and `forecast_disagreement` in Miami and
  Toronto.

T1 against the current-code base, per market and local hour band; each cell is changed fraction / mean
TV / max TV (changed = TV > 1e-12). Source: `l5_twin_tables.py` (scratch) over the run's `twin.jsonl`,
0 base errors and 0 variant errors in every market; the output stays uncommitted.

| market | 00-05 | 06-09 | 10-12 | 13-16 | 17-23 | all hours |
| --- | --- | --- | --- | --- | --- | --- |
| atlanta | 0.912 / 0.156 / 0.706 | 0.906 / 0.149 / 0.741 | 0.916 / 0.145 / 0.736 | 0.996 / 0.157 / 0.707 | 0.949 / 0.029 / 0.839 | 0.936 / 0.117 / 0.839 |
| austin | 0.968 / 0.120 / 0.726 | 0.972 / 0.094 / 0.667 | 0.986 / 0.096 / 0.627 | 0.999 / 0.139 / 0.783 | 0.943 / 0.037 / 0.840 | 0.969 / 0.092 / 0.840 |
| chicago | 0.968 / 0.279 / 0.945 | 0.966 / 0.273 / 0.911 | 0.966 / 0.303 / 0.889 | 0.995 / 0.313 / 0.917 | 0.936 / 0.045 / 0.836 | 0.962 / 0.219 / 0.945 |
| dallas | 0.965 / 0.064 / 0.582 | 0.943 / 0.061 / 0.695 | 0.981 / 0.068 / 0.749 | 0.999 / 0.164 / 0.787 | 0.974 / 0.081 / 0.700 | 0.972 / 0.085 / 0.787 |
| denver | 0.984 / 0.213 / 0.811 | 0.978 / 0.191 / 0.763 | 0.992 / 0.221 / 0.904 | 0.992 / 0.196 / 0.858 | 0.609 / 0.043 / 0.864 | 0.873 / 0.157 / 0.904 |
| houston | 0.975 / 0.205 / 0.833 | 0.952 / 0.192 / 0.854 | 0.983 / 0.199 / 0.911 | 0.999 / 0.164 / 0.806 | 0.995 / 0.028 / 0.750 | 0.982 / 0.143 / 0.911 |
| los-angeles | 0.950 / 0.092 / 0.732 | 0.922 / 0.099 / 0.706 | 0.933 / 0.187 / 0.675 | 0.998 / 0.228 / 0.797 | 0.988 / 0.046 / 0.486 | 0.962 / 0.114 / 0.797 |
| miami | 0.945 / 0.203 / 0.884 | 0.954 / 0.194 / 0.871 | 0.886 / 0.125 / 0.665 | 0.934 / 0.099 / 0.575 | 0.734 / 0.010 / 0.916 | 0.876 / 0.118 / 0.916 |
| nyc | 0.984 / 0.245 / 0.872 | 0.977 / 0.224 / 0.893 | 0.979 / 0.216 / 0.763 | 0.999 / 0.241 / 0.855 | 0.965 / 0.044 / 0.910 | 0.979 / 0.179 / 0.910 |
| san-francisco | 0.997 / 0.306 / 0.758 | 1.000 / 0.284 / 0.764 | 1.000 / 0.254 / 0.768 | 0.997 / 0.201 / 0.820 | 1.000 / 0.017 / 0.519 | 0.999 / 0.193 / 0.820 |
| seattle | 0.999 / 0.209 / 0.923 | 0.991 / 0.208 / 0.960 | 0.972 / 0.196 / 0.837 | 0.991 / 0.229 / 0.874 | 0.951 / 0.043 / 0.547 | 0.979 / 0.162 / 0.960 |
| toronto | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 (T1 = base) |

T1 fallback rows (no NWS day max, variant = base): Los Angeles 34, Miami 19, Seattle 7, Toronto 11,298;
every other market 0. The 17-23 band changes least in mean TV everywhere, and its changed fraction drops
to 0.609 in Denver and 0.734 in Miami.

T0 against the same base, all hours (changed fraction / mean TV / max TV); 17-23 is again the smallest
band in mean TV (0.009-0.069) and 00-12 the largest (0.16-0.65):

| market | all hours | market | all hours |
| --- | --- | --- | --- |
| atlanta | 0.985 / 0.155 / 0.905 | miami | 0.991 / 0.207 / 0.899 |
| austin | 1.000 / 0.270 / 0.788 | nyc | 1.000 / 0.328 / 0.978 |
| chicago | 1.000 / 0.429 / 0.968 | san-francisco | 1.000 / 0.222 / 0.758 |
| dallas | 1.000 / 0.150 / 0.748 | seattle | 1.000 / 0.319 / 0.941 |
| denver | 0.994 / 0.302 / 0.926 | toronto | 1.000 / 0.224 / 0.882 |
| houston | 1.000 / 0.299 / 0.772 | los-angeles | 1.000 / 0.190 / 0.863 |

Both tables are vector deltas only: no score was read, nothing here is evidence of edge, and the binding
T1/T0 comparison is forward at the frozen hash.

Throughput: uncapped HGB predicts used ~17 cores at ~27 s/folder; with `OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` = 1 the run took ~3 s/folder (fix on its own branch;
[host load policy](../operations/HOST_LOAD_POLICY.md) rule 11).

## 4. What "110g re-fit" is

Handoff `docs/roadmap/workstation-handoff-2026-09-110g-disable-afternoon-centering.md` and report
`docs/roadmap/agent-report-2026-09-110g-disable-afternoon-centering.md`: the owner switched the June
in-sample afternoon (15-18 h) residual-centering artifact off on 2026-09-25 (disabled in serving since 09-28), "pending a separate
measurement" (EF §2); EXHAUSTION_REGISTER L19 / order 16 asks for a re-fitted centering. A re-fit is a
fit of per-context mean residuals against settlement, so it cannot be specified, let alone closed,
outcome-blind: any non-zero fitted shift changes every 15-18 h vector in its context. Section 3 measures
only the artifact as fitted.
