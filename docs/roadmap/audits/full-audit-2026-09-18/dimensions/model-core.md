# Audit dimension: Forecast model core and release/serving binding (`model-core`)

Auditor: subagent, 2026-09-18. Read-only. Host: live 16 GB production capture host, protected window.
Tools used: Read, Grep, Glob (scoped to `src/`, `tests/`, `docs/`, `artifacts/` text manifests), and
whitelisted `git log` / `git show --stat` / `git show <rev>:<path>` / `git branch` / non-recursive `ls`.
No Python, no tests, no data/ access, no network, no project writes other than this file.

Health grade for this dimension: **C**.

---

## 1. Scope and method

In scope: `src/weather/model/` (22 files) plus top-level `release_serving.py`,
`residual_distribution_release.py`, `release_artifacts.py`, `artifacts.py`, `runtime_identity.py`,
`captured_input_hash.py`, `point_in_time_contract.py`, `model_stage_retirement.py`,
`experiment_contract.py`, `variant_registry.py`, `units.py`.

Method: read the serving entry point (`toronto_model.py`) and traced one full distribution build
end to end: artifact loading -> feature extraction (`model_features.extract_live_features`) ->
HGB/LR/empirical evaluation -> the stage pipeline in `model_distribution._estimate_distribution_result`
-> calibration (`calibration_runtime.apply_exact_distribution_calibration`) -> identity capture
(`model_identity.model_replay_identity`, called from `collection/snapshot_store.py:2891`).
Each structural claim below was traced through at least one concrete call path; line numbers are
from the working tree on `master` at `3bdba3d15`.

Read in full: `toronto_model.py`, `model_base.py`, `model_identity.py`, `model_constants.py`,
`model_distribution_constants.py`, `calibration_runtime.py`, `current_blend.py`, `artifacts.py`,
`runtime_identity.py`, `units.py`, `captured_input_hash.py`, `variant_registry.py`.
Read in substantial part: `model_distribution.py` (lines 1-1240, 1300-1630), `model_features.py`
(1-330, 783-1082, 1140-1400), `feature_store.py` (1-730, 1188-1377), `release_serving.py` (1-850),
`model_distribution_signals.py` (221-370), `model_climatology.py` (186-290),
`model_sources.py` (276-300, 1080-1128, 1290-1411, 2389-2410).
Grep-only: `release_artifacts.py`, `model_stage_retirement.py`, `calibration/feature_model.py`
(read 820-910, 1340-1420), `variant_prediction_runtime.py`.

Cross-checked against `docs/operations/ESTABLISHED_FINDINGS.md` (sections 2, 3, 4b, 4c),
`docs/operations/OPERATIONS_AGENT_ROLE.md`, `docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md`,
`docs/roadmap/items/item-268-*.md`, `docs/roadmap/model-systems-audit-2026-07-12.md`.

---

## 2. What is actually serving today (context, verified)

- There is **no `artifacts/releases/` directory** (`ls artifacts` shows only `calibration`,
  `candidates`, `manifests`, `misc`, `models`). `release_serving.load_verified_active_serving_bundle`
  therefore returns `STATUS_RESEARCH_UNBOUND` (`release_serving.py:516-521`), and
  `TorontoHighTempModel._configure_base_model_components` takes the legacy branch that loads every
  component from global artifact paths (`toronto_model.py:133-150`).
- The base HGB pickles were last committed **2026-06-13 / 2026-06-20** (`git log -- artifacts/models/hgb/feature_model_hgb.pkl ..._nyc.pkl ..._chicago.pkl` -> `5b6f5af2d 2026-06-20`, `fd728d4a4 2026-06-13`).
  Later commits under `artifacts/models/hgb` (through 07-11) touch only overlay artifacts
  (e.g. `feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl`).
- All 11 F markets are gated `"mode": "ml"` in `artifacts/manifests/f_family_secondary_artifacts.json`
  (lines 120-760), so the HGB path is the live path whenever the pickle loads.
- Stage order in `_estimate_distribution_result` (`model_distribution.py:139-594`):
  climatology prior -> feature-model blend (or empirical components) -> bucket-transition blend ->
  live-signal kernels -> hard floor (x1e-6) -> intraday tail -> plausible cap -> forecast shape
  (empirical only) -> ramp warm-tail dampening -> **afternoon residual centering** -> validated
  current-max floor -> hedged observed floors -> late-day continuation -> late-day lock-in ->
  normalize -> exact-distribution calibration (temperature, then **hard zero below floor**) ->
  current-max boundary guard -> final.

---

## 3. Findings (most severe first)

### model-core-1 (HIGH, known_open) - Replay identity on master describes the disk, not the process; and the human version label has not moved across four behaviour-changing commits

Verified in code:
- `model_identity.py:100-104` fingerprints code files by reading `SRC_ROOT / name` from disk **at
  every capture**, and `model_identity.py:101-104` hashes artifact files from disk at capture.
  It is called per snapshot from `collection/snapshot_store.py:2891-2895` (exceptions swallowed,
  identity silently becomes `None`).
- `IDENTITY_SCHEMA_VERSION = "weather_model_replay_identity_v0.1"` (`model_identity.py:18`);
  `git log master -- src/weather/model/model_identity.py` shows the last change was **2026-06-13**.
- The fix exists only on unmerged branches: `codex/model-loaded-identity-v03-20260815`
  (`9f81b3fe5 2026-08-15`, `7cf605a4f 2026-08-11`) and
  `codex/production-bind-model-identity-to-the-process-2026-08-11`. `git branch --merged master
  --list "*identity*"` lists neither. The branch's own docstring states the v0.1 defect
  ("only 114 of 358 decision snapshots reproduced their own recorded output, and 0 of 63 captured
  identities could be rebuilt from Git").
- Coverage gap on master: `DISTRIBUTION_CODE_FILES` (`model_identity.py:24-36`) has 11 files and
  omits modules that demonstrably change the served distribution:
  `model_distribution_constants.py` (imported at `model_distribution.py:29-76`),
  `model_distribution_signals.py` (`model_distribution.py:118`), `calibration_runtime.py`
  (`model_distribution.py:22-25`), `model_sources.py`, `toronto_model.py`, `units.py`. The fix
  branch lists 24 files. `DISTRIBUTION_ARTIFACT_TEMPLATES` (`model_identity.py:38-46`) omits
  `afternoon_residual_centering.json`, which is loaded (`toronto_model.py:147, 254-259`) and applied
  to every build (`model_distribution.py:484-490`).
- `ML_MODEL_VERSION = "v0.5.10"` (`model_constants.py:122`), file last changed 2026-06-30, while
  serving behaviour changed in `e8fdce38c` and `b77cfbed4` (2026-07-30, the floor change that is the
  project's one shipped win), `87ca37cf8` (08-07) and `b17f29b0f` (08-08, feature routing repair).
  `runtime_identity.get_runtime_identity` hard-codes `git_dirty: None` (`runtime_identity.py:217-218`).

Impact: no tape row can be attributed with confidence to the code and artifacts that produced it, by
hash or by label. Every before/after measurement of a serving change, and any future promotion
evidence, inherits this. The project already records this (`OPERATIONS_AGENT_ROLE.md:266`,
`REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md:40`); what this audit adds is that, five
weeks after the fix was built, master is unchanged and the master file list is also incomplete.

Recommendation: decide the fix branch explicitly (merge in a quiet window, or close it with a
written reason). Independently of the merge, bump `ML_MODEL_VERSION` on every commit that touches a
file in the (v0.3) distribution file list, and add `afternoon_residual_centering.json` to the artifact
templates.

### model-core-2 (HIGH, new as stated; the tautological fit was flagged 2026-07-12) - A stale, in-sample-fitted per-market COOL shift is live in serving from 15:00 to 18:00, pointing the same way as the established cool bias

Verified in code and artifact:
- `distribution_afternoon_residual_centering_stage` runs unconditionally in every build
  (`model_distribution.py:484-490, 721-743`). The artifact resolves to
  `artifacts/misc/afternoon_residual_centering.json` (`artifacts.py:356-374` falls through to
  `misc`; file present per `ls artifacts/misc`).
- Artifact config: `"enabled": true`, `"start_hour": 15`, `"end_hour": 18`, `"max_abs_shift": 2.0`,
  `"min_context_n": 4`, `"allow_global_fallback": false` (lines 3-21); `generated_at_utc`
  **2026-06-23** (line 745).
- `apply_afternoon_residual_centering` sets `shift = clamp(mean_residual)` and calls
  `shift_bucket_distribution` with `target = bucket + shift` (`calibration_runtime.py:129-145,
  248-250`). Negative residual = mass moved to **cooler** buckets.
- Market contexts are negative for most F markets: austin -0.79..-1.16, chicago -0.74..-0.92,
  dallas -0.55..-1.00, houston -0.75..-1.10, los-angeles -0.48..-0.90, san-francisco -0.75..-1.31
  (artifact lines 119-515). Only denver is positive.
- Provenance (`docs/roadmap/items/item-268-*.md:88-94`): trained on 5,747 rows "through 2026-06-22"
  (one served-tape week, Jun 16-22), validated **in-sample** ("moved mean bias +0.3948 -> 0.0000").
  `model-systems-audit-2026-07-12.md` F13 already records that fit and validation reuse the same
  rows. `model_stage_retirement.py:126-129` lists the stage for retirement. Its test is on the
  accepted known-failing list (`OPERATIONS_AGENT_ROLE.md:269`).
- `ESTABLISHED_FINDINGS.md:1075-1092` later established that the model is **cool** (-0.64387 C-eq)
  and states "**Do not implement a serving-side offset.**" No document under `docs/operations/`
  mentions that one is already live (grep for `afternoon.residual.centering` returns only the
  known-failing-test row).

What is NOT established: the effect on Brier/log-loss. The cool-bias measurement in section 2 is of
the *base HGB centre* via replay, so it is not itself contaminated by this stage. Mechanically,
because exact calibration zeroes everything below the floor afterwards
(`calibration_runtime.py:365-373`), a cool shift late in the day mostly removes upside mass and
concentrates the distribution on the floor bucket - the same shape as the documented
"centre overconfidence" tail. That link is inference, not measurement.

Recommendation: measure the stage in isolation on the existing stage-attribution harness
(`pipeline.snapshot("afternoon_residual_centering")` vs the preceding snapshot) on out-of-sample
dates, with crossed clustering. If it does not earn its place, disable it via the artifact's
`enabled` flag (a data change, roll-free) rather than new code. Record the outcome in
ESTABLISHED_FINDINGS either way; right now the canon and the serving path disagree.

### model-core-3 (HIGH, known_open) - The served base model is an absolute-bucket classifier fitted to prior-year days within +/-7 days of mid-June, now three months out of season with the retrain blocked

Verified in code:
- Target is the absolute integer settlement bucket: `final_bucket` (`calibration/feature_model.py:1341, 1409`),
  `HistGradientBoostingClassifier(... random_state=42)` (`:1432, :1630`). Serving maps
  `model_obj.classes_` to probabilities (`model_features.py:1283-1286`); a multiclass classifier cannot
  place mass on a bucket absent from `classes_`.
- Training rows come from `historical_target_cache()`, which skips the target year and keeps only
  days within `HISTORY_WINDOW_DAYS = 7` of the target day-of-year (`model_climatology.py:121-124`,
  `model_constants.py:25`).
- Artifacts last committed 06-13/06-20 (section 2). `ESTABLISHED_FINDINGS.md:1509`: "Every served HGB
  was fitted 2026-06-10 to 06-13". Section 2 of that doc measures in-season centre error -0.18 vs
  out-of-season **-1.02** C-eq. `OPERATIONS_AGENT_ROLE.md:264`: season-window re-fetch "Permitted and
  **still un-run**. Flagged CRITICAL". Lead context: training window disabled.
- Other warm-season hard-codes on the serving path: Toronto's thin-history prior is always uniform
  8..32 C (`model_climatology.py:198-209`); `bucket_space or list(range(8, 35))`
  (`model_climatology.py:193`) is Celsius-only.

Inferred: through September most markets' highs still sit inside early-June class ranges, which is
why the symptom so far is a centre bias. As highs fall below the lowest trained class (late
October onward for Toronto, Chicago, Denver, NYC), the HGB component becomes structurally unable to
cover the outcome; after the plausible-cap stage (`model_distribution.py:1022-1025`) the distribution
collapses onto the 0.0005-padded prior between floor and forecast cap. I could not inspect `classes_`
(binary pickles are off limits), so the date this starts is not verified.

Recommendation: this is the known retrain critical path; the audit's addition is a deadline. Run the
permitted season-window re-fetch now, and before the retrain lands add a monitor for "realized bucket
outside `classes_`" and "observed floor outside `classes_`" per market so the transition is seen
rather than discovered.

### model-core-4 (MEDIUM, new) - A 30 F "plausibility" bound will treat legitimate winter observations in F markets as unit errors, and training never applies the same gate

Verified in code:
- `plausible_native_temperature`: F range is `30.0 <= number <= 125.0` (`feature_store.py:337-344`).
- `current_max_trust_features` quarantines any `current_max` outside it as
  `implausible_current_max_unit` (`feature_store.py:370-374`).
- `startup_observation_guard_features` flags `high_so_far` / `current_temp` / `live_reading_temp`
  outside it, and quarantines when the live reading is missing (`feature_store.py:424-438`).
  On quarantine `effective_observed_high_context` nulls `effective_high` and `current_temp`
  (`model_base.py:88-100`), so the HGB sees imputer medians for its two most important inputs. The
  hard floor survives only when WU history is present (`model_base.py:102-106`); with WU empty the
  floor is also lost.
- The behaviour is pinned by a test that quarantines `17.0` in NYC in June
  (`tests/model/test_feature_store.py:151-168`) - correct as a C-vs-F sentinel in June, identical to a
  real 17 F reading in January. F markets include chicago, denver, nyc
  (`market/market_registry.py:118-220`).
- Train/serve skew: training calls `build_historical_feature_record` **without `unit=`**
  (`calibration/feature_model.py:866-879`), so the gate is inert in training
  (`feature_store.py:370` requires `unit`), while serving always passes `unit=self.spec.display_unit`
  (`model_features.py:1086-1092`, `model_distribution.py:188-194`). Also `gap_threshold=10.0`
  (`feature_store.py:354`) is in native degrees: 10 C for Toronto, 10 F (5.6 C) elsewhere.

Not recorded in `docs/operations/` or `docs/roadmap` (grep for `plausible_native_temperature`,
"below 30", "winter" found nothing relevant). Bites from roughly November (morning temperatures at
early cutoffs first, daily highs later).

Recommendation: replace the absolute bound with a unit-consistency test relative to other evidence
(forecast high, climatology, the other unit's conversion), or widen F to a physically real range
(about -40..130 F) and keep the sentinel logic for the specific startup case. Pass `unit` in training.

### model-core-5 (MEDIUM, new) - Constants tuned in Celsius are applied per-bucket in Fahrenheit markets without scaling, while neighbouring thresholds are scaled

Verified in code. `MarketSpec.scale_delta` exists for exactly this purpose
(`market/market_registry.py:94-98`) and is used for thresholds
(`model_distribution_signals.py:392, 532, 567, 978, 999, 1007, 1072`). It is **not** used for:
- live-signal kernel sigmas 0.65 / 0.75 / 0.8 / 0.9 / 1.0 / 1.2 buckets
  (`model_distribution.py:1359-1361, 1365-1371, 1383-1394`; kernel at `:1447-1455`;
  `METAR_LIVE_SIGNAL_SIGMA = 0.90`);
- per-bucket decay rates: plausible cap `0.28 ** (temp - cap - 1)` with a fixed `+1` bucket
  allowance (`model_distribution.py:1022-1025`), `LIVE_FLOOR_BASE` (`signals.py:238, 305`),
  `LATE_LOCKIN_BASE` (`signals.py:899`), `FORECAST_FLOOR_BASE` (`signals.py:1023`),
  `RAMP_WARM_TAIL_DECAY` (`model_distribution.py:680`), `cap_prior_distribution`
  (`model_distribution.py:1437-1444`);
- `max_abs_shift: 2.0`, `disagreement_reference: 3.0` in the afternoon centering artifact;
  `current_blend.py:117-138` thresholds 1.0 / 2.5 on native-unit disagreement.
- Artifact evidence: `artifacts/calibration/forecast_error_model_chicago.json` carries
  `"max_sigma": 3.0, "min_sigma": 0.75` (lines 5-6), identical to Toronto's Celsius file, while its
  own measured RMSE is **4.45 F** globally and 3.2-4.3 F in most hour contexts (lines 40-233).
  `calibration_runtime.py:672-673` clips sigma to `max_sigma`, so that component is structurally
  over-sharp for Chicago. (This component is on the empirical path only; with all F markets gated
  `ml` it matters when the HGB silently falls back - see model-core-6.)

Net: in 11 of 12 markets the kernels and tail decays are about 1.8x tighter in physical terms than
the Toronto-tuned design. This is consistent with the project's own diagnosis (loss is sharpness /
centre overconfidence) but I have **not** shown it causes it. Treat as a units defect, not as alpha.

Recommendation: inventory every bucket-unit constant, decide per constant whether it is "per bucket"
or "per degree C", and express the latter through `scale_delta`. Any change must go through the
leakage-free evaluation; do not tune.

### model-core-6 (MEDIUM, new) - HGB -> LR -> empirical fallback is silent, the live pickle load is unverified, and nothing in ops watches the model kind

Verified in code:
- `_read_feature_model_hgb` on the live (unbound) path: bare `pickle.load`, any exception ->
  `logger.warning` and `None` (`model_features.py:59-71`). No hash check against
  `artifacts/manifests/model_artifact_registry.json`; no sklearn/numpy version check (that exists
  only on the release path, `release_artifacts.py:204-221, 964-970`). `test_tracked_artifact_manifests`
  is on the accepted known-failing list (`OPERATIONS_AGENT_ROLE.md:269`), so the one hash inventory
  for this path is not enforced.
- `_evaluate_feature_model_for_cutoff` wraps the whole HGB predict in `except Exception` -> warning
  -> LR; the LR block is wrapped the same way -> `(None, "empirical")` (`model_features.py:1238-1347`).
  A pandas import error, a renamed bundle key or a changed feature name therefore changes which
  model is served without any error.
- The LR path imputes only `None` (`model_features.py:1313-1316`); a NaN feature propagates to NaN
  logits. `normalize_scores` then maps NaN to 0.0 via `max(0.0, nan)` (`model_distribution.py:1513-1525`),
  which can yield an empty distribution.
- `active_model_kind` is recorded in the tape, but grep finds **no** reference to it under
  `src/weather/operations/` or `scripts/`. No alarm exists for a fleet-wide downgrade.

This is the project's own "a default that looks like data" shape (the all-day feature-blind defect
ran for weeks unseen).

Recommendation: add a status-monitor check on the share of snapshots per market with
`active_model_kind != "hgb"` over the last N hours; log the fallback at ERROR with the exception
type; verify the pickle sha256 against the tracked registry at load.

### model-core-7 (MEDIUM, known_open) - Train and serve build features through two separate implementations guarded by a single happy-path parity case

Verified: training uses `feature_store.build_historical_feature_record` (`feature_store.py:1188-1377`),
serving uses `model_features.extract_live_features` (`model_features.py:783-1221`). The parity test
(`tests/model/test_feature_skew.py:72-93`) compares all `FEATURE_COLUMNS`, which is good, but for one
synthetic Toronto day with complete data and no `unit`. Serving-only branches it cannot see:
station-surface fallbacks for 7am temp, 2h warming, dewpoint, humidity, wind (`model_features.py:880-1015`);
pressure back-fill from earlier rows (`:951-961`) vs training's latest-row-only (`feature_store.py:1287`);
`current_max` from live `max_since_7am` vs training's reconstruction from WU rows
(`feature_store.py:1241-1251`), which makes `current_max_*` states near-constant in training;
the `unit` gate (model-core-4). `AGENTS.md` for the package names this risk and the project keeps a
standing parity gate, hence known_open.

Recommendation: extend the parity test to a small matrix (F market, WU-empty with station rescue,
missing pressure, pre-07:00 cutoff, sub-30 F values) rather than adding a third implementation.

### model-core-8 (MEDIUM, known_accepted) - About 300 KB of release/verification code has never bound a live process

`release_serving.py`, `release_artifacts.py`, `residual_distribution_release.py`,
`point_in_time_contract.py`, `experiment_contract.py`, `model_stage_retirement.py` total roughly
300 KB. With no active pointer the live process gets none of their guarantees (hash-before-load,
runtime version binding, no-global-fallback). `point_in_time_contract` is imported only by release and
candidate tooling (grep: 3 importers, none in `model/` or `collection/`). The owner took release
machinery off the critical path on 2026-08-09 (ESTABLISHED_FINDINGS 0b), so this is reported once as
accepted. The residual risk is rot: unexercised code against a moving serving path.

### model-core-9 (LOW, known_open) - Exact zero below the floor, and the WU-empty floor is sourced from non-resolution observations

`apply_exact_distribution_calibration` sets every bucket below `floor_bucket` to exactly 0.0
(`calibration_runtime.py:365-373, 408-412`), overriding the 1e-6 residual left by `apply_floor`
(`model_distribution.py:952-957`). When WU history is empty, the floor comes from station/current
temperature and `max_since_7am` (`model_base.py:78-80, 102-114`), although
`apply_current_observed_floor`'s docstring says such readings "must never act as a hard floor"
(`model_distribution_signals.py:274-282`). The contract is deliberate and documented
(`model_distribution_constants.py:96-102`, package `AGENTS.md`), the 07:00 guard exists
(`model_base.py:79`), and the project measures served zero-on-realized at 0.000% after `28d1c146`.
Keep the floor (ESTABLISHED_FINDINGS section 2 is explicit); the ask is only a standing monitor of
zero-on-realized split by `effective_observed_high_source`.

### model-core-10 (LOW, new) - Small latent defects, mostly cold-weather

- Falsy-zero: `(hard_floor_bucket or observed_bucket or max_signal or ...)` and
  `(max_signal or observed_bucket or ...)` (`model_distribution.py:329, 331`) treat a 0 degree bucket
  as missing when sizing support. Only an exact 0 bucket is affected.
- `row_wind_direction` uses an `or` chain (`feature_store.py:670-676`); a numeric 0 (north) falls
  through to the next key.
- `TARGET_DATE` is evaluated at import (`model_constants.py:12-15`) and is the constructor default
  (`toronto_model.py:125`); safe only while callers always pass an event/date.
- `resolve_current_blend_alpha` returns **1.0** (full candidate weight) on a non-numeric or
  non-finite alpha (`current_blend.py:247-253`), and later context rules override the source-health
  cap (`:242-246`; already noted as A20 in the 07-12 audit). Shadow path only.
- `variant_registry.py` is described as keeping callers off the reporting package but itself imports
  `weather.reporting.candidate_lifecycle.variant_registry`.

---

## 4. Brief items checked and found sound or already owned

- **Pickle safety / sklearn binding:** `scikit-learn==1.8.0`, `numpy==2.4.6`, `pandas==3.0.3`,
  `scipy==1.17.1` pinned exactly with a stated reason (`requirements.txt:2-10`). Release path
  verifies versions and hashes before deserialising (`release_serving.py:175-217`). Live path gap is
  model-core-6. Threat model is a single-user host; the practical risk is silent incompatibility, not
  code execution.
- **Order of floor / blend / cap / calibration:** coherent. Hard floor before shaping, floors
  re-applied after centering, calibration last with the floor re-enforced. Temperature tapering to
  identity under lock-in is implemented as documented (`calibration_runtime.py:377-392`).
- **`max_since_7am` carrying yesterday:** guarded at `cutoff_hour >= 7` (`model_base.py:79`) and
  `hour < 7` (`model_distribution.py:1330`); METAR rows are filtered to the local target date
  (`model_sources.py:1317-1318`, `parse_utc_time` converts to market tz at `:2403-2410`);
  `wu_current` requires `validTimeLocal` on the target date (`:1102-1106`). The replay-side version of
  this defect is recorded by the project and not re-derived here.
- **C vs F naming:** `*_c` keys carry native units by documented convention; accessors prefer
  `*_native` (`feature_store.py:574-622`). Consistent within a market. The real unit problem is
  model-core-5.
- **`forecast_high` not point-in-time; `high_so_far` from a non-append-only WU series:** both recorded
  by the project (`ESTABLISHED_FINDINGS` 4f; memory `-09-71a`). Not re-measured.
- **Determinism:** `random_state=42` throughout the trainers; sorted-key canonical hashing; no
  randomness on the serving path that I could find.
- **NaN / empty distribution:** `to_float` rejects NaN and sentinel strings (`units.py:8-20`);
  `normalize_*` clamp negatives and return `{}` on zero mass; the empty case is returned explicitly
  (`model_distribution.py:317-326`). The LR NaN path is the exception (model-core-6).

---

## 5. Strengths

1. Exact dependency pinning with rationale, and runtime-version verification on the release path
   (`requirements.txt:2-10`, `release_artifacts.py:204-221`).
2. `release_serving.py` is genuinely fail-closed: hash before deserialise, stability re-check after,
   refusal of any graph that permits fallback (`:175-217, 263-269, 340-346`), undeclared-pickle check
   (`:307-316`).
3. The floor design distinguishes the settlement source from supporting sources and sizes hedges
   from a learned catch-up rate clamped to [0.30, 0.80], preserving a residual on the printed WU
   bucket (`model_distribution_signals.py:221-369`). Constants carry their measured justification
   inline (`model_distribution_constants.py`).
4. Every stage writes a named snapshot into `DistributionPipelineState`
   (`model_distribution.py:91-114`), which is what makes stage attribution (and the check asked for in
   model-core-2) cheap.
5. An all-column train/serve parity test exists and native-NaN handling at serve mirrors training
   (`tests/model/test_feature_skew.py:72-137`, `model_features.py:1274-1280`).

---

## 6. Not covered

- `residual_distribution_release.py`, `release_artifacts.py`, `point_in_time_contract.py`,
  `experiment_contract.py`, `model_stage_retirement.py`: grep only, not read.
- `model_presentation.py`, `source_adapters.py`, `feature_safety.py`, `corpus_lineage.py`,
  `continuous_density.py`, `model_contracts.py`, `variant_prediction_runtime.py`,
  `model/residual_distribution_v1.py`: not read.
- `model_sources.py` (105 KB) and `model_distribution_signals.py` lock-in logic (370-960): sampled.
- Nothing was executed. No pickle was opened, so `classes_` ranges, trained `feature_names`, and
  per-hour blend weights are unverified. No `data/` file was read, so no live rate (fallback share,
  quarantine share, zero-on-realized) is measured here.

## 7. Open questions for the owner

1. Is the afternoon residual centering meant to be live? If yes, where is its out-of-sample evidence;
   if no, flipping `enabled` is a roll-free data change.
2. What blocks merging `codex/model-loaded-identity-v03-20260815` beyond roll sensitivity? Each week
   on v0.1 adds tape that cannot be attributed.
3. Does AviationWeather ever return a `reportTime` without an offset? `parse_utc_time`
   (`model_sources.py:2403-2410`) would then interpret it in the **host's** timezone. Tests use the `Z`
   form only (`tests/model/test_source_cache_ttl.py:661`). Unverified; no network used.
4. What is the lowest class in each market's HGB `classes_`? That number sets the date model-core-3
   changes from a bias into a coverage failure.
