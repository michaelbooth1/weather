# Audit dimension: what production actually serves

Key: `gap-what-production-serves`
Date: 2026-09-19 (audit window 2026-09-18). Auditor: one read-only subagent.
Scope: live input fetchers, the active post-processing stages in the served path, and silent input death.

Health grade for this dimension: **D** (the serving path is richly instrumented per snapshot, but the project cannot currently say what it serves without a research mission, and I found roughly half of the post-processing pipeline inert for eleven weeks with nothing reporting it).

---

## 1. Method and safety

- Tools used: Read, Grep, Glob, plus whitelisted `git log`, `git show --stat`, `git show <rev>:<path> | head`, and non-recursive `ls` of `artifacts/`, `artifacts/calibration`, `artifacts/misc`, `artifacts/manifests`, `artifacts/models/hgb`, `artifacts/models/coefs`, `config/`, `app/`, `app/views`. No python, no pytest, no scripts, no network, nothing under `data/`, `logs/`, `venv/`, `.git/`.
- Question (4) of the brief (read one small live status JSON) was **conditional on a grant from the lead that I did not receive, so I did not read any data file.** Everything below is from code and tracked text artifacts. Nothing here is confirmed from served output. That is stated again wherever it matters.
- Every structural claim below was traced through at least one full call path, not grepped. Line numbers are from the working tree at HEAD `3bdba3d15`.
- I never opened a `.pkl`. Statements about what the HGB bundles contain are inferred from the sibling LR JSON artifacts and from `ESTABLISHED_FINDINGS.md`, and are labelled as such.

Files read fully: `src/weather/model/model_sources.py` (all 2,425 lines, in six chunks), `source_adapters.py`, `toronto_model.py`, `calibration_runtime.py`, `app/streamlit_app.py`, `app/views/control_room.py`, `operations/operator_host_status.py`, `config/markets.json`.
Files read in the relevant parts: `model_distribution.py`, `model_distribution_signals.py`, `model_features.py`, `model_base.py`, `feature_store.py`, `model_constants.py`, `model_distribution_constants.py`, `artifacts.py`, `release_serving.py`, `io.py`, `collection/snapshot_tracker.py`, `collection/snapshot_store.py`, `collection/collection_health.py`, `collection/triggered_snapshot_queue.py`, `operations/observation_trigger.py`, `sources/mrms_precip.py`, `market/market_registry.py`, `calibration/probability_calibration.py`, `calibration/family_secondary_artifacts.py`, tracked artifacts under `artifacts/calibration`, `artifacts/misc`, `artifacts/manifests`, `artifacts/models/coefs`, and the relevant sections of `docs/operations/ESTABLISHED_FINDINGS.md`.

---

## 2. The one fact that organises everything else

`src/weather/model/model_constants.py:19` sets `PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False`. It is a module constant with no environment override. It was introduced by commit `5735b573a` on 2026-06-30 12:16 -0400 (the last commit to touch that file).

Consequence, traced:

1. `fetch_wu_history`, `fetch_wu_current` and `fetch_weather_com_forecast` call `paid_weather_provider_disabled(...)` first (`model_sources.py:1018`, `:1091`, `:1414`), which unconditionally raises `SourceExpectedUnavailable` (`:143-156`).
2. `source_adapters.fetch_source` converts that into `{"ok": False, "status": "paid_provider_disabled", ...}` (`source_adapters.py:168-179`).
3. `blend_with_last_good` emits `data: {}` for that status and never consults the cache (`model_sources.py:794-823`).
4. `ModelUtilsMixin.source_data` returns `{}` for any item that is not `ok` (`model_base.py:266-273`).

So in every live capture since 2026-06-30, `wu_history`, `wu_current` and `weather_forecast` are empty dicts. All three are still listed first in every market's `sources` tuple (`market_registry.py:111-113`, `:130-132`), so each capture spends a thread on each only to raise immediately.

The project knows the *feature* consequence of this (the "blind block", `ESTABLISHED_FINDINGS.md:1361-1364`, repaired 2026-08-08). It does **not** record the *post-processing* consequence. That is finding 1.

Production is release-unbound. `artifacts/releases/` does not exist in the working tree (`ls artifacts`), `release_serving.load_verified_active_serving_bundle` therefore returns `STATUS_RESEARCH_UNBOUND` (`release_serving.py:516-521`), and `TorontoHighTempModel._configure_base_model_components` takes the global-artifact branch (`toronto_model.py:140-150`). `ESTABLISHED_FINDINGS.md:1387` independently records the same absence. Every artifact named below is therefore loaded straight from `artifacts/` by filename.

---

## 3. Deliverable A: input failure-mode table

Common machinery (applies to every row unless noted):

- Timeout: `self.timeout = 8` seconds per socket operation (`toronto_model.py:84,92`). It is a `requests` timeout, so it bounds each read, not the whole call.
- Retry: `weather.io.request_with_retries`, 3 attempts, 0.5 s then 1.0 s backoff, `Retry-After` honoured but capped at 10 s, retries on connection error, timeout, HTTP 429 and HTTP 5xx (`io.py:46-55`, `:87-124`). Only calls made through `get_json` / `get_text` get this. The SWOB directory index, the marine `get_text`, and the MRMS `get_text` closures do not (`model_sources.py:1186`, `:2222-2225`, `:2238-2241`).
- Isolation: each fetcher runs in its own thread; any exception becomes a data record, never a crash (`source_adapters.py:137-197`).
- Stale fallback: on failure, the last good payload is used only if it is for the same target date and its age is within that source's TTL (`model_sources.py:787-846`). It is flagged `stale: True`, `status: stale_cache` or `rate_limited_cache`. **There is no unbounded-age fallback and no yesterday's-value fallback anywhere in this path.** That is a genuine strength.
- Beyond TTL: `data: {}`, which becomes `None` features. For the HGB, `forecast_high`, `forecast_gap`, `live_reading_temp`, `live_reading_minus_high` and the live-only families stay native NaN (`feature_store.py:235-251`, `model_features.py:1278-1280`). **Every other trained input, including `high_so_far` and `current_temp`, is replaced by the training median by the bundle's imputer (`model_features.py:1272`).** The LR fallback imputes medians for everything (`:1313-1315`).
- Recording: every snapshot persists a full per-source status row (`snapshot_store.py:1162-1215`, written at `:991-994`), the whole feature vector (`:917`, `:923-936`), every stage snapshot (`:909`, `:938-949`) and the model-version label. So failure **is** recorded per snapshot.
- Aggregation: see finding 2. In short, a latest-row source summary exists in `collection_health.py` and feeds reporting, but nothing in the alert path reads it, and nothing anywhere aggregates NaN features or model kind.

| Source | Endpoint | Fresh-cache reuse | Stale TTL (min) | Feeds the served model? | On failure within TTL | On failure beyond TTL | Downstream effect |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wu_history` | disabled since 2026-06-30 | n/a | 30 | No. Always `{}` | n/a | n/a | `history_max` is always `None`. See finding 1 |
| `wu_current` | disabled | n/a | 30 | No. Always `{}` | n/a | n/a | `wind_group` and (F markets) `cloud_group` permanently `None` |
| `weather_forecast` | disabled | n/a | 90 | No. Always `{}` | n/a | n/a | one forecast vote permanently absent |
| `metar` | `aviationweather.gov/api/data/metar` | none, fetched every snapshot and every 60 s by the trigger | 75 | **Yes, critical.** Sole observation for the 11 F markets: `high_so_far`, `current_temp`, `live_reading_temp`, hard floor, local-met block | stale rows, `stale: True` | `station = {}` | `high_so_far` and `current_temp` become **training medians** (not NaN); hard floor disappears; forecast still served and looks plausible |
| `metar`, empty list returned | same | | | | **`ok: True`, status `fresh`, `target_date_match: False`** (`model_sources.py:1377`), `source_data` then returns `{}` (`model_base.py:271-272`) | same as above | **identical blindness, but reported as healthy** |
| `eccc_swob` (Toronto) | `dd.weather.gc.ca/today/observations/swob-ml/<date>/CYYZ/` index plus every `*CYYZ-MAN-swob.xml` | none. Re-downloads every file each call (`:1197-1230`) | 30 | Yes, Toronto leading observation | stale | falls back to METAR (`station_observation_source_order`, `:276-280`) | Toronto degrades to METAR resolution |
| `eccc_citypage` (Toronto) | `api.weather.gc.ca/collections/citypageweather-realtime/items/on-143` | none | 120 | Yes: forecast vote, Toronto `cloud_group` text | stale | `{}` | regex `High\s+(-?\d+)` on English text (`:1273`); any wording change yields `None` silently while status stays `fresh` |
| `open_meteo` | `api.open-meteo.com/v1/forecast`, 21 hourly vars | **reused while age <= 90** | 90 | **Yes, critical**: `forecast_high` vote, forecast profile | **unreachable, see finding 4** | `{}` | `forecast_high` falls to the remaining sources; if none, native NaN and the HGB is forecast-blind |
| `open_meteo_global_models` | same host, 4 models | reused <= 120 | 120 | Yes: one `forecast_high` vote (median of 4 model highs) | unreachable | `{}` | vote lost |
| `global_ensemble` | `ensemble-api.open-meteo.com/v1/ensemble`, gfs_seamless | reused <= 120 | 120 | Yes: one `forecast_high` vote (daily max of the ensemble **mean**) and spread features | unreachable | `{}` | vote lost |
| `open_meteo_multimodel` (US) | `api.open-meteo.com/v1/gfs`, 18 vars x 4 models | reused <= 120 | 120 | Live-only features. Not in the v0.3 served feature list | unreachable | `{}` | none on the served forecast |
| `open_meteo_air_quality` | `air-quality-api.open-meteo.com` | reused <= 120 | 120 | Live-only | unreachable | `{}` | none |
| `eccc_gem` (Toronto) | `api.open-meteo.com/v1/gem` | reused <= 120 | 120 | Live-only | unreachable | `{}` | none |
| `nws_hourly` (US) | `api.weather.gov/points/...` then `forecastHourly` | none | 90 | Yes: one `forecast_high` vote | stale | `{}` | vote lost |
| `nws_grid` (US) | `forecastGridData` | none | 90 | Live-only | stale | `{}` | none |
| NWS `/points` lookup | cached to `data/<market>/nws_points.json` **forever**, no TTL, no invalidation on a downstream 404 (`:1979-1997`) | | | | | | if NWS re-grids an office, both NWS sources fail permanently until a human deletes the cache file |
| `nbm_probabilistic_tmax` (US) | NOMADS national NBP text, last 24 h of cycles | per-cycle fan-out shared across market children | 120 | Live-only | stale | `available: False` | none on the served forecast |
| `marine_context` | CO-OPS and NDBC | none | 75 | Live-only | errors swallowed per station inside the fetcher, source still `fresh` | | none on the served forecast (known: "marine features went dark") |
| `mrms_precip` (11 US markets) | `noaa-mrms-pds.s3.amazonaws.com` listing | none | 20 | **Never.** All three return paths set `available: False`, `rows: []` (`mrms_precip.py:283-329`) | | | a network call every snapshot for a source that cannot produce a feature; reported `fresh`. See finding 9 |
| `local_history` | `data/<market>/daily/daily_summary.csv` | n/a | n/a | Yes: climatology prior | | missing file or under 30 window days falls open to `climatology_fallback_prior` (`model_distribution.py:263-271`) | prior silently changes family |

Features that can go silently NaN, median-imputed, or stale, and what happens:

- `high_so_far`, `current_temp` (METAR or SWOB dead beyond TTL, or an empty-but-OK METAR reply): **training median**, e.g. 71 F for NYC (`feature_model_coefs_nyc.json:1029-1030`). The hard floor vanishes with them. Highest-consequence silent path in the system.
- `live_reading_temp`, `live_reading_minus_high`: native NaN.
- `forecast_high`, `forecast_gap`: native NaN only if every forecast vote is gone; more commonly the *definition* of the median shifts as votes drop in and out (finding 6).
- `rise_from_7am`, `warming_rate_2h`, `hours_at_peak`, `dewpoint_c`, `humidity`, `wind_speed_kmh`: median when station rows are missing for the needed window.
- `pressure`, `pressure_trend_3h`: permanently median in the 11 F markets. Known and accepted (`ESTABLISHED_FINDINGS.md:1217-1222`).
- `wind_group`: permanently `None` in all 12, so every wind one-hot is 0. Known open (`ESTABLISHED_FINDINGS.md:1215`).
- `cloud_group`: permanently `None` in the 11 F markets. **Not recorded.** Finding 7.

---

## 4. Deliverable B: active-stage census

Evidence grades: **A** = code path traced and the tracked artifact read; **B** = code path traced, artifact not inspectable (pickle) or not applicable; **C** = inferred. None of this is confirmed from served output.

Stage order is `model_distribution.py:139-594`.

| # | Stage | Live today? | Artifact or flag | Missing or corrupt artifact | Grade |
| --- | --- | --- | --- | --- | --- |
| 1 | Climatology prior | yes | `daily_summary.csv`, needs >= 30 window days | fail-open to fallback prior | B |
| 2 | Family-secondary gate (F markets) | yes, all 11 are `mode: ml` | `artifacts/manifests/f_family_secondary_artifacts.json` (2026-07-07) | no manifest means `ml`; market absent means `empirical` (`model_features.py:1373-1394`) | A |
| 3 | HGB feature model | yes if the pickle loads | `artifacts/models/hgb/feature_model_hgb{suffix}.pkl`, dated 2026-06-10 to 06-13, materialised (15-29 MB, not LFS pointers) | **fail-open, silently**: load error or predict error logs a warning and falls to LR, then to empirical (`:69-71`, `:1292-1293`, `:1344-1347`) | B |
| 4 | HGB `probability_temperature` | yes | inside the pickle, default 1.0 (`:1287-1290`) | default | B |
| 5 | Feature ordinal smoothing | only if the bundle declares it; absence means disabled (`:152-182`) | pickle | disabled | B |
| 6 | Feature blend, 0.8 model / 0.2 climatology | yes | per-hour `blend_weight`, default 0.80 (`:91-106`); NYC LR JSON shows 0.8 | default | A for LR, B for HGB |
| 7 | Per-market blend weights `calibrated_weights*.json` | **dormant.** Read only inside the empirical branch (`model_distribution.py:372-373`, `:876-890`) | | `None` | A |
| 8 | `forecast_error_model*.json` | **dormant.** Empirical branch only (`:841-850`) | | `None` | A |
| 9 | Bucket-transition blend | **inert.** Needs a WU observed bucket (`model_features.py:1403-1422`) | | | A |
| 10 | Live signals | yes, but reduced to the forecast-cluster kernel (plus two ECCC kernels in Toronto); `trusted_current_max` is always `None` without WU (`feature_store.py:394-398`) | constants | n/a | A |
| 11 | Hard floor | yes, driven by METAR/SWOB because `history_high` is `None` (`model_base.py:102-106`) | code | n/a | A, known and accepted |
| 12 | Intraday tail target | inert in the feature path and needs a WU bucket (`model_distribution.py:973`) | | | A |
| 13 | Plausible cap | yes | constants | n/a | A |
| 14 | Forecast floor / forecast pull | skipped whenever the feature model is active (`:1053-1056`) | | | A |
| 15 | Ramp warm-tail dampening | yes, 08:00-14:00 local, conditional | constants | n/a | A |
| 16 | **Afternoon residual centering** | **YES, 15:00-18:00 local** | `artifacts/misc/afternoon_residual_centering.json`, `enabled: true` | fail-open, reason `missing_artifact` (`calibration_runtime.py:223-226`) | **A** |
| 17 | Validated current-max floor (Miami) | **inert**, needs a trusted current max | | | A |
| 18 | Observed-floor stage (hedged SWOB/METAR) | yes | `settlement_lag_model{suffix}.json` | fail-open to the constant hedge (`signals.py:252-253`) | A |
| 19 | WU-floor residual | **inert** (`signals.py:344-354`) | | | A |
| 20 | Late-day continuation blend | **inert**, needs a WU observed bucket (`model_distribution.py:1147-1151`). `late_day_model_coefs*.json` are loaded and never applied to the distribution | | | A |
| 21 | Late-day lock-in, five variants | **inert**, all need WU history | | | **A** |
| 22 | Exact-distribution temperature by hour | **YES** | `probability_calibration{suffix}.json` | fail-open to identity; below-floor zeroing still applied (`calibration_runtime.py:351-412`) | **A** |
| 23 | Calibration taper toward identity as the day locks in | **inert**: `resolution_weight = lockin_strength = 0` always | | | A |
| 24 | Market-bin calibration (`prior_shrink`, `platt`, ...) | **dead code at serve**: `preserve_distribution_coherence: true` in all 13 artifacts returns the raw probability first (`calibration_runtime.py:525-526`). Only the hard 0/1 floor override above it is live | | | A |
| 25 | Simplex coherence | yes, by item 24 | | | A |
| 26 | Gamma sharpening | **does not exist** in `src/weather/model` or `config/model_variant_registry.json` | | | A (grep plus stage trace) |

All `load_*` helpers share `_load_json_artifact` (`calibration_runtime.py:42-50`): absent file returns `None` silently; corrupt file logs one warning and returns `None`. Every `apply_*` treats `None` as identity. **The whole calibration layer is fail-open, and nothing downstream reports that an artifact failed to load** other than the per-snapshot `reason` string inside the stage context.

### The two claims I was asked to confirm or refute

**model-core: "a June-fitted 15:00-18:00 cool shift is live." CONFIRMED from code and artifact (grade A), not from served output.**

- Loaded at `toronto_model.py:147` via `:254-259`, resolving to `artifacts/misc/afternoon_residual_centering.json` (57,700 bytes, present).
- Invoked unconditionally at `model_distribution.py:484-490`, with `hour=now.hour` in market-local time.
- `component.enabled: true`, `start_hour: 15`, `end_hour: 18`, `max_abs_shift: 2.0`, `min_context_n: 4`, `allow_global_fallback: false` (artifact lines 3-21).
- `generated_at_utc: 2026-06-23T15:28:26Z`, `folder_count: 213`, 12 markets, 5,747 rows (artifact lines 745-764). The F markets began capturing on 2026-06-06 (first non-Toronto folders, artifact lines 775+), so each F-market context rests on at most about 18 dates.
- Direction: 80 contexts; the global mean residual is -0.395 native units (line 29); `regime=marine|hour=15` is -0.609 (line 713); `market=atlanta|hour=15` is -0.427 (line 83). Eleven contexts are warm (Denver afternoon, 17h and 18h; NYC 17h and 18h; Seattle 16h; Toronto and the Canadian regime at 17h and 18h). So it is "mostly cool", not uniformly cool.
- Context `n` counts snapshot rows, not dates (`market=atlanta|hour=15` has n=121). `min_context_n: 4` can therefore be satisfied by a single afternoon.
- The same stage also blends in an ordinal smoother whenever forecast disagreement exceeds `disagreement_reference: 3.0`. That 3.0 is not unit-scaled (`calibration_runtime.py:251-262`, no `scale_delta`), and the artifact's own mean disagreement is 4.4, so in F markets this widening is on more often than not.

**calibration: "a worse-than-identity calibration artifact is served." CONFIRMED by the artifacts' own self-report, but the mechanism is not the one the metric's name implies.**

- Ten of the eleven F-market artifacts record `artifact_replay_brier` above `baseline_brier` (NYC 0.06645 vs 0.06242; Los Angeles 0.05000 vs 0.04230; Seattle 0.07382 vs 0.06660; Chicago 0.06884 vs 0.06179; Houston 0.06937 vs 0.06353; San Francisco 0.07057 vs 0.06426; Atlanta 0.06771 vs 0.06188; Denver 0.06782 vs 0.06340; Austin 0.05857 vs 0.05753; Dallas 0.07465 vs 0.07367). Miami is marginally better. Toronto is identical because its selected method is `identity`.
- `artifact_replay_brier` scores `calibrate_market_probability` (`calibration/probability_calibration.py:716-730`, `:767-768`). With `preserve_distribution_coherence: true` that function is the raw probability plus the hard floor 0/1 override. NYC's log loss goes from 0.200 to 0.362 (artifact lines 1693, 1696), which is the signature of hard zeros placed on winners. That points at the floor recorded in the training rows, a known defect class, not at the shrink.
- **What actually reshapes the served distribution, `exact_distribution.temperature_by_hour`, is not scored by that metric at all.** NYC serves T = 1.12 to 1.30 at most hours, fitted on 5-6 days per hour (artifact lines 243-381, 391-416). Toronto serves T up to 1.25 fitted on **2 to 4 days per hour** (lines 242-295), while its own pooled table says T = 1.0 scores best (Brier 0.06516 vs 0.06549 at T = 1.2, lines 202-213).
- **Nothing gates serving on these numbers.** `gate_for_market` checks trust score, settled-day count and that each artifact's build status is `ok` (`family_secondary_artifacts.py:1259-1287`). It never compares replay to baseline. All 11 markets carry "trust and artifacts clear".

---

## 5. Findings

### Finding 1 (high, new): every post-processing stage keyed on WU history has been inert in production since 2026-06-30, and nothing records it

With `history = {}` and `history_max = None` (`model_distribution.py:147`, `:183`) and therefore `observed_bucket = None` (`:285`):

| Stage | Guard that makes it a no-op |
| --- | --- |
| Heuristic late-day lock-in | `signals.py:381`, returns 0.0 when `history_max is None` |
| Learned lock-in (revision-up curve) | `signals.py:415-418`, needs `history.max_times` |
| High-has-stood lock-in | `signals.py:509-513`, reason `missing_history_high` |
| Expanded late-day lock-in | `signals.py:620-623`, same |
| Standing-high partial lock-in | `signals.py:758-761`, same |
| `apply_late_day_lockin` | `signals.py:888-892`, strength 0 or bucket `None` |
| Calibration taper | `model_distribution.py:540-546`, `resolution_weight=lockin_strength`, which is always 0 |
| Late-day continuation blend | `model_distribution.py:1147-1151`, needs `observed_bucket` |
| Bucket-transition blend | `model_features.py:1408-1422`, empty probabilities |
| Intraday tail target | `model_distribution.py:973` |
| Learned METAR live signal | `signals.py:316-319`, needs `history_bucket` |
| WU-floor residual | `signals.py:344-354` |
| Validated current-max floor (Miami) | `feature_store.py:394-398` leaves `trusted_current_max` as `None` |

That is 13 of the roughly 26 stages in section 4.

What remains above the observed high late in the day is: 0.8 HGB plus 0.2 climatology, multiplied by a Gaussian kernel centred on the *forecast* high that never switches off (`forecast_source_cluster_signal`, `model_distribution.py:1595-1641`; `forecast_signal_weight` bottoms out at 1.0, `:1588-1593`), a plausible cap referenced to the forecast, and then a temperature softening of T > 1 that was designed to taper to identity as the day locks in and now never does. The version notes in `model_constants.py:60-64` and `:82-87` describe that taper and the learned lock-in as the serving behaviour. They are not.

Why it matters to the project's own conclusions. The established finding is that the gap to the market is sharpness. This is a set of sharpening stages silently off and a softening stage silently un-tapered, for eleven weeks. I am **not** claiming this explains the gap. The lock-in window starts at 15:00 and the primary objective is 09:00-14:00, and I measured nothing. I am claiming that nobody knows, that `missing_history_high` appears in no doc and no test (Grep over `docs/` and `tests/` returns nothing), and that any replay of pre-06-30 dates exercises a pipeline production no longer runs.

The evidence to see it is already captured: the stage snapshots simply do not contain `late_day_lockin`-family movement, and `high_has_stood_lockin.reason` is persisted per snapshot. Nothing counts it.

### Finding 2 (high, new): there is no served-input liveness alarm, and the one source summary that exists calls empty payloads healthy

- The snapshot loop's status has no source, feature or model-kind fields (`snapshot_tracker.py:1496-1532`; a Grep of the file for `source_`, `model_kind`, `model_version` finds only backfill helpers and the cooldown path).
- `scripts/ops/health_watchdog.ps1` classifies flags by text and has no source or feature check (its only "observability" rule is `streak checker failed|BLIND`, line 71). No script under `scripts/ops` reads `source_status`, `degradation_state` or a model-kind field.
- `src/weather/operations` checks only that `source_status_long.csv` *exists* (`settled_day_freshness.py:245-316`).
- A real source summary does exist, which corrects the critic's blanket claim: `collection_health.source_family_degradation` (`collection_health.py:842-1034`). It feeds `reporting/fleet/fleet_observability_*`, `market_making_run_support.py` and `cross_hub_readiness.py`. Its limits: it reads only the latest snapshot's rows; `source_degradation_bucket` (`:664-697`) decides on `status` and `ok` alone, and `row_count` is passed through for display only (`:717`); and it is not in the watchdog or briefing path.
- Therefore: an empty METAR reply (`ok: True`, `target_date_match: False`), a city-page wording change, MRMS (always `available: False`), and marine (errors swallowed per station) are all `fresh`.
- The observation trigger has the same blind spot: `errors` is populated only by exceptions (`observation_trigger.py:826-835`), and source failures are data, not exceptions, so a total METAR outage leaves `consecutive_errors = 0` and a healthy heartbeat.
- HGB to LR to empirical fallback is a `logger.warning` in a short-lived child process plus a changed `model_version` string in the tapes. No consumer of `MODEL_VERSION_LR`, `MODEL_VERSION_EMPIRICAL` or `active_model_kind` exists in `operations/` or `collection_health.py`.
- The train/serve parity scorecard is a manual heavy workload (`scripts/ops/workload_admission.ps1:631`), not scheduled, and `ESTABLISHED_FINDINGS.md:1273-1275` records it as permanently BLOCK until its fixture is narrowed. A permanently red gate cannot signal a new failure.

This is how the blind block, the marine outage, the non-point-in-time `forecast_high`, and now finding 1 were each found by research rather than by monitoring.

### Finding 3 (high, new as a policy contradiction): a June-fitted serving-side temperature offset is live, against the project's own rule, with a known-failing test

Mechanics are in section 4. The additional points:

- `ESTABLISHED_FINDINGS.md:1091-1092`: "**Do not implement a serving-side offset.** Market heterogeneity forbids it." This stage is a serving-side offset. It is per market and hour, which answers the heterogeneity objection only in-sample on at most about 18 dates.
- It is fitted entirely inside the window the project calls in-season (through 2026-06-23) and is being applied in September, the stratum the project measures as a full degree cool (`ESTABLISHED_FINDINGS.md:1099-1107`). Most contexts push cooler.
- `docs/operations/OPERATIONS_AGENT_ROLE.md:269` lists `test_afternoon_residual_centering` among known-failing tests, "pre-existing, out of scope". So the one live stage that moves the served centre has no passing test.
- The stage is mentioned nowhere else under `docs/operations` (Grep for `afternoon.residual|residual.centering`). The cool-bias section does not know it exists.
- Bounded magnitude: typical |shift| 0.1 to 0.6 native units, hard cap 2.0. Later floors truncate part of it.

### Finding 4 (medium, new): for the Open-Meteo family the stale-cache fallback is unreachable, so any failed refresh blanks the source at once

`source_fetcher_with_budget` reuses the cached payload while `age <= TTL` (`model_sources.py:435-453`, `:509-524`), and the reuse window *is* the TTL (`:509-511`). A real fetch is attempted only when `age > TTL`. If it fails, `blend_with_last_good` requires `age <= TTL` to fall back (`:787-793`, `:824-828`). Reuse does not refresh the stored `fetched_at` (the fetcher's metadata overrides the wrapper timestamp, `source_adapters.py:150-156`, and `:765-769` stores it back), and time only moves forward, so that condition is false by construction. The branch that would yield `rate_limited_cache` cannot be reached for these six sources in steady state.

Effect: a 429, timeout or 5xx at the moment of refresh takes `open_meteo`, `global_ensemble` or `open_meteo_global_models` straight to `{}` for at least one snapshot, and under a family cooldown every member that expires during it. In an F market that can leave `nws_hourly` as the only forecast vote. The intent, "avoid re-querying while TTL-valid", is sound; the zero grace is almost certainly unintended.

On 429 generally: three attempts inside `get_json` (the retry helper treats 429 as retryable, `io.py:54`), then the 429 is recorded as a family cooldown of `max(Retry-After, 60 s)` in memory and in `data/ops/live_source_family_cooldown.json`, shared with the other capture children through an environment variable (`model_sources.py:92`, `:639-700`; `snapshot_tracker.py:238`, `:1698`). During cooldown all Open-Meteo fetches raise `SourceProviderRateLimited` without touching the network. That part is well built.

Request budget (inferred, not measured): with reuse, about 16 + 4 x 12 = 64 Open-Meteo HTTP calls per market per day, about 770 per day fleet-wide, at most two in flight (`DEFAULT_CAPTURE_WORKERS = 2`, and the family is serialised within a market, `model_sources.py:267-268`). Open-Meteo weights calls by variable and model count, so the weighted figure is several times higher. **The project records no free-tier limit** (Grep of `docs/operations` for daily, hourly or per-minute limits returns nothing) **and the code keeps no request counter.** The only budget signal is a 429 after the fact. Counting `rate_limited` and `rate_limited_cache` statuses per day would cost nothing.

### Finding 5 (medium, partly known): calibration artifacts are served fail-open, fitted on 2-6 days per hour, self-report worse than baseline in 10 of 11 F markets, and no gate reads those numbers

See section 4. The precise statement: the gate (`family_secondary_artifacts.py:1259-1287`) cannot fail an artifact for being worse than identity; the recorded "selected" `prior_shrink` method is dead code at serve; the live transform is an unscored per-hour temperature. The project's own bound says recalibration cannot close the gap, so this is about not making things worse, not about a lost win.

### Finding 6 (medium, new): `forecast_high` is a different quantity at serve than at training, and the parity gate does not look

Training: one source, the Open-Meteo archive (`feature_store.py:1389-1398`; stated in `model_constants.py:70-75`). Serve: the median of whichever of `open_meteo`, `eccc_citypage`, `nws_hourly`, `global_ensemble` (daily max of the ensemble **mean**) and `open_meteo_global_models` (median of four model highs) are alive (`model_features.py:397-414`, `:435`, `:454`, consumed at `:1063`). The v0.5.3 note defends the median as "unchanged by definition" because the median of one value is itself. That holds for the training side only; the served statistic is a different estimator, its membership changes snapshot to snapshot as sources drop (finding 4), and an ensemble mean's daily max is structurally lower than a deterministic model's. `train_serve_feature_parity.py` contains no reference to `median`, `forecast_ensemble` or `source_count`. Direction and size are unmeasured; this is a mechanism, not a measured bias.

### Finding 7 (low-medium, partly known): `cloud_group` is dead at serve in the 11 F markets, alongside the known-dead `wind_group`

`model_features.py:1018-1024` resolves both groups from `feature_latest` (WU rows, always `None`) or from `live_wind_group` / `live_cloud_group`, which read only `wu_current`, `weather_forecast` and, for cloud, the ECCC city page (`model_base.py:181-196`). In an F market all three are `{}`, so `cloud_group("", "")` returns `None` (`:212-224`) and every `cloud_*` one-hot is 0. The 2026-08-08 repair routed station rows into eight numeric features but not into either group. The METAR `cover` code is captured and carried in station rows (`model_sources.py:1347`), and the `cloud_group` keyword list already contains `clr`, `few`, `sct`, `bkn`, `ovc`, so the intent is visible; the routing is missing. `ESTABLISHED_FINDINGS.md:1215` records `wind_group` only. Toronto's `cloud_group` comes from forecast prose, and words such as "sunny" match no keyword, so it lands in `Other`. Per the project's own precise null, expect a correctness gain, not a skill gain.

### Finding 8 (medium, inferred): the in-season versus out-of-season contrast is confounded with the WU cutoff

`ESTABLISHED_FINDINGS.md:1094-1111` attributes the B versus C difference in base-HGB centre error (-0.18 vs -1.02 C-eq) to the archive's May 10 - Jun 30 seasonal coverage. Captures exist only from late May 2026, so B is "2026 dates up to Jun 30" and C is "dates from Jul 1". The WU live inputs were disabled on 2026-06-30 (`ESTABLISHED_FINDINGS.md:1361`). Every C date therefore has METAR-derived `high_so_far` and `current_temp`, a dead `pressure` pair and dead group one-hots, feeding a model trained on the WU surface; every B date has the WU surface. Season and input provenance change on the same day, and the market comparator, which the text uses to rule out weather, is not subject to our input change. I did not find this confound discussed in `ESTABLISHED_FINDINGS.md` or `RETRACTED_AND_FALSE_LEADS.md`. It does not overturn the finding. It means "seasonal coverage, not staleness" is one of two explanations the design cannot separate, and the retrain rationale leans on it.

### Finding 9 (low-medium, inferred volume): avoidable polling and dead payload

- The observation trigger runs `--market all --interval-seconds 60` (`register_observation_trigger_supervisor.ps1:17-19,27`) and calls the raw fetchers with no reuse (`observation_trigger.py:235-253`, `:730-739`). For Toronto that is the SWOB directory plus **every** per-observation XML for the day, every minute (`model_sources.py:1197-1230`), growing through the day. It also calls the two disabled WU fetchers every minute for all 12 markets.
- MRMS is fetched for 11 markets at every snapshot, can never set `available: True`, and its full S3 listing (`objects`, up to about 720 entries of roughly 350 bytes) sits outside `raw_payload`, so `strip_raw_payloads` keeps it (`snapshot_store.py:2190-2199`) and it is appended to `replay_inputs.jsonl` with every snapshot (`:2975`, `:3018`). My bound is on the order of 100-200 MB per day uncompressed. Not measured; I could not open the tapes. Small against 5.9 GB per day, but it is pure waste on a host with about four days of disk.
- `last_good_sources.json` holds raw payloads and is fully parsed at least seven times per capture (five reuse checks, one blend, one merge-on-save).

### Finding 10 (low): smaller items

- `cached_nws_points` never expires or self-heals (table above). The NWS User-Agent has no contact string (`model_sources.py:1662`), which NWS asks for.
- `variant_prediction_error` is written to `snapshots.jsonl` and the capture result (`snapshot_store.py:919`, `:1038`) and read by nothing, so the variant tape can fail silently for weeks.
- `check_snapshot_probabilities` recomputes the same deterministic function on the same inputs (`:2260-2299`); it can only catch nondeterminism. An empty distribution is "skipped" and still written as all-zero bands.
- Git history holds a hard-coded default weather.com web API key at `src/weather/model/model_constants.py` in commit `fd728d4a4` (2026-06-13); the adjacent comment describes it as the widely published public browser key. Location and type only. Low sensitivity, no longer in the tree.

---

## 6. Deliverable C: the concrete silent-degradation paths

1. METAR returns `[]` for a station: `ok: True`, `fresh`; `high_so_far` and `current_temp` become training medians; the hard floor vanishes; a plausible forecast is served; the observation trigger reports zero errors.
2. METAR down longer than 75 minutes: same effect, but at least reported as `failed` in the per-snapshot rows that nothing alerts on.
3. Open-Meteo refresh fails once: instant `{}` for that source (finding 4); `forecast_high` silently becomes a median over different members.
4. The HGB pickle fails to load or predict (a scikit-learn upgrade, a non-materialised LFS pointer, a memory error in the child): LR serves, then empirical; one warning line in a child log.
5. Any calibration JSON is absent or corrupt: identity, silently.
6. The ECCC city-page English wording changes: Toronto loses a forecast vote and its cloud text while the source stays `fresh`.
7. NWS re-grids an office: both NWS sources fail until someone deletes `nws_points.json`.
8. Everything in finding 1: already happened, eleven weeks ago.

---

## 7. Answers to the numbered questions

1. Section 3.
2. Finding 4.
3. Section 4.
4. **Not performed; no grant.** From code, there is no small per-market latest-prediction JSON: `SnapshotStore` writes only append-only per-event tapes (`snapshot_store.py:620-642`). The only small status file is `data/snapshots/loop_status.json`, and by construction it carries no model kind, stage reasons or NaN count. The absence of a cheap "what did we just serve" artifact is part of finding 2.
5. **Twelve.** `run_loop` iterates `all_specs()` (`snapshot_tracker.py:1595`), which is the 12 `BUILTIN_SPECS` plus `config/markets.json` (`market_registry.py:388-394`), and that file is a deprecated shell with `"markets": []`. The observation trigger uses the same registry (`observation_trigger.py:223-226`). The 51 locations and 119 events in `config/location_market_events.json` are not iterated by either served-forecast loop.
6. Section 8.

Dashboard: `app/streamlit_app.py` is a two-page router. The Control Room reads a handful of small JSONs (`mm_runs/*/*/run_summary.json`, `backtest/mm_live_readiness*.json`) and, every 300 s per open session, spawns `powershell -File scripts/ops/status.ps1 -Json` with a 20 s timeout (`operator_host_status.py:22-40`). No tape and no large frame is loaded; the heavy pages were retired (`app/AGENTS.md`). Opening it on the production host is low risk. The residual cost is one PowerShell process per five minutes per open tab, and the ordinary Streamlit and pandas import footprint.

---

## 8. Minimal served-input liveness check (specification only)

Where: compute inside the capture child from objects already in memory at `SnapshotStore.write` (the feature vector, the source-status rows, the stage contexts), return it in the capture result dict, and have `run_loop` fold it into `loop_status.json`, which the watchdog already reads. No tape reads, no new process, no new file walk.

Count, per market per snapshot:

1. `model_kind`, and alarm on anything other than `hgb`.
2. `unexpected_missing`: the number of `None` values among **that artifact's own trained numeric feature names**, not the 100+ schema columns, minus an explicit allowlist. Today's allowlist is `pressure` and `pressure_trend_3h` in F markets. `wind_group` and F-market `cloud_group` should be listed as known-dead, with a date, so that they stay visible.
3. Core five present: `high_so_far`, `current_temp`, `live_reading_temp`, `forecast_high`, `dewpoint_c`.
4. `forecast_source_count` and the member list.
5. Per source: the existing bucket plus a new `empty_ok` bucket for `ok` with `row_count == 0` or `available is False`.
6. Observation age: minutes since the newest station row.
7. Stage reasons: the `reason` string of afternoon centering and of each lock-in context, the applied calibration temperature, and a list of stages that were no-ops.

Thresholds:

- Flag (class `observability`, severity HIGH) when, for any market between 07:00 and 20:00 local, three consecutive scheduled snapshots (30 minutes) show a missing core-five value, a non-HGB model kind, or `unexpected_missing > 0`.
- Flag when three or more markets share a `failed`, `rate_limited` or `empty_ok` bucket for the same source for two consecutive cycles.
- Morning briefing line when any trained feature's populated rate for a market falls below 95% for the day, and whenever any stage has been a no-op in 100% of the day's snapshots. **That last rule alone would have reported finding 1 on 2026-07-01.**

---

## 9. Strengths

- **Honest, bounded caching.** Stale fallback is limited by a per-source TTL and by target date; observations expire fast and forecasts slowly (`model_constants.py:35-55`, `model_sources.py:783-846`). No unbounded or previous-day value can reach a feature through this path.
- **Per-snapshot evidence is excellent.** Source status, feature vector, every stage snapshot, stage reasons, runtime identity and a captured-input hash are persisted with every snapshot (`snapshot_store.py:892-1011`). Every finding here is cheap to confirm from data the project already holds. The gap is aggregation, not capture.
- **Refusing a false alias.** `parse_metar_payload` keeps altimeter and sea-level pressure out of the trained station-`pressure` field, with the reasoning written down (`model_sources.py:1335-1341`). A presence check would have passed; the team chose correctness.
- **Release binding fails closed.** A present release pointer forbids any global-artifact fallback (`toronto_model.py:207-211`, `model_features.py:43-52`), and snapshot persistence asserts that model and store share one bundle (`snapshot_store.py:244-262`).
- **Fault isolation and provider manners.** One thread per source with exceptions turned into data, one subprocess per market, a cross-process 429 cooldown with a short-stale lock, single-worker Open-Meteo access, and a once-per-cycle shared fetch of the national NBM bulletin.
- **The dashboard was cut down to something safe for the production host.**

---

## 10. Not covered, and open questions

- Nothing under `data/` was read. I cannot report the live model kind, stage reasons, NaN counts or 429 frequency. The owner can settle findings 1 and 3 by reading one recent afternoon row of any market's `components_long.csv` and the `high_has_stood_lockin.reason` field in a late-day snapshot record.
- HGB pickle contents (trained feature names, `probability_temperature`, `ordinal_smoothing`, `blend_weight`) were not inspected. The v0.3 feature list is taken from the NYC LR JSON; `ESTABLISHED_FINDINGS.md:1174` says the Toronto HGB has 29 features.
- `forecast_tracker.py` turned out to be an offline report tool, not a fetcher, and was only skimmed. `variant_prediction_runtime.py` was surveyed by symbol only; it serves the shadow variant tape, not the forecast.
- `sources/marine_context.py` and `sources/eccc_gridded.py` were skimmed for endpoints and error handling only.
- `scripts/ops/status.ps1` was not read, so the cost of the dashboard's five-minute subprocess is unassessed.
- The `current_max_boundary` overlock guard and the ramp warm-tail stage were read but not traced against live inputs.
- Open question for the owner: is the afternoon centering stage meant to be live? If yes it needs a passing test and an entry in the canonical findings. If no, the artifact's own `enabled` flag is the switch, which respects the rule about suppressing via the switch itself.
- Open question: should the inert WU-keyed stages be re-pointed at the station surface, or deleted? Either is defensible. Leaving them in place, described as live in the version notes, is not.
