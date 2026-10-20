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

## 3. Outcome-blind restoration check

### 3.1 What could be run on the workstation

Captured `replay_inputs.jsonl` for dev dates exist only on the capture host (the workstation holds one
June pilot folder). A full served-vector recompute on 07-31..09-29 therefore **cannot run here**. Built
instead:

- `tools/research/model_edge_lever5/stage_replay.py` (`python -m tools.research.model_edge_lever5.run
  replay`): re-runs the current pipeline on each captured snapshot as served and once per variant,
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

Final-vector numbers (max/mean band change, fraction of snapshots changed) need the host replay of
section 3.4; the stage-level numbers above bound one stage, not the vector after the later floors,
lock-ins and calibration temperature.

| Stage | Change tested | Result | Status |
| --- | --- | --- | --- |
| 10 Intraday tail | give it the station bucket | cannot act: `intraday` is `None` on the feature path for all 12 markets (ml gate); synthetic replay TV 0 | **CLOSED** (code; host replay re-confirms) |
| 11 Learned METAR live signal | give it the station high | the feature-path signal list never carries it; synthetic TV 0 | **CLOSED** (code; host replay re-confirms) |
| 12 WU-floor residual | read the station high | acts only when live support exceeds the anchor, which is the max of the same rows; synthetic TV 0 | expected inert; **open until the host replay** |
| 13 Trusted current max (Miami floor + live-signal member) | validate METAR max-since-07:00 against the station high | changes vectors: synthetic Atlanta TV up to 0.10 (08-18 h) | **changes the vector; open**, magnitude by host replay, then a scored look |
| 9 Bucket transition | re-point on the station high at the cutoff | changes 13.3% of dev snapshots, stage TV <= 0.0588 | **changes the vector; open** |
| 110g centering | re-enable as fitted | changes 100% of 15-18 h snapshots, stage |shift| mean 0.49, max 1.31 °F | **changes the vector; open**; a re-fit is label-defined (section 4) |
| Task 4 (NBM) | remove / +10 °F | synthetic TV 0 at every hour; host replay variants `nbm_removed`, `nbm_perturbed` | **confirmed: NBM does not reach the bands** |

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
everywhere; any `folder_error` means the base would not have been the served vector for that folder.

## 4. What "110g re-fit" is

Handoff `docs/roadmap/workstation-handoff-2026-09-110g-disable-afternoon-centering.md` and report
`docs/roadmap/agent-report-2026-09-110g-disable-afternoon-centering.md`: the owner switched the June
in-sample afternoon (15-18 h) residual-centering artifact off on 2026-09-25 (disabled in serving since 09-28), "pending a separate
measurement" (EF §2); EXHAUSTION_REGISTER L19 / order 16 asks for a re-fitted centering. A re-fit is a
fit of per-context mean residuals against settlement, so it cannot be specified, let alone closed,
outcome-blind: any non-zero fitted shift changes every 15-18 h vector in its context. Section 3 measures
only the artifact as fitted.
