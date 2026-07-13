# Code-Health Cleanup Audit — 2026-07-12

Audit scope: `C:\Users\micha\Desktop\github\weather`

Audit started: `2026-07-12T19:22:41-04:00` (`America/Toronto`; Windows timezone `Eastern Standard Time`)

This was an audit-first, non-mutating pass. No source, configuration, release, model, test, data, or artifact cleanup was performed. The only intended tracked change is this report.

## Implementation follow-up — 2026-07-12

The subsequent cleanup pass implemented the behavior-preserving and bounded
items from this audit. The audit snapshot and line numbers below remain the
historical evidence baseline rather than being rewritten after the cleanup.

Completed in the follow-up:

- Removed the D1-D5 shadowed bodies and dead bindings while preserving the 44
  public calibration aliases as canonical runtime object re-exports.
- Removed the obsolete F811 runtime-audit allowances and added durable alias
  identity and direct module-CLI import-order coverage.
- Corrected structure root counts, compatibility-shim counts, module-size
  ownership/governance, ownership documentation, README commands, and a
  bidirectional documented-command existence ratchet.
- Removed the exact duplicate schema row; made the v0.2 composite schema name
  canonical and retained the old public name as an explicit deprecated alias.
- Split headline, live-capture, and promotion registry decisions into explicit
  typed booleans and audit both headline and live-capture contracts.
- Consolidated HTTP retryability, Retry-After parsing, backoff, and request
  execution in `weather.io`; preserved compatibility re-exports and removed the
  `market -> model` package edge.
- Consolidated exact writer-lock and file-hash copies in `weather.io` behind
  compatibility re-exports.

Deferred as non-obvious, behavior-sensitive, or lifecycle-gated: point-in-time
verifier consolidation, remaining train/serve transform consolidation,
maker/taker state-machine generalization, large-module decomposition, public
facade/shim removal, model-stage retirement, and generated data/artifact
cleanup. Those items retain the preconditions and rollback requirements below.

## 1. Executive verdict

There is a worthwhile behavior-preserving cleanup wave, but there is **no evidence-backed permission to delete an incumbent model stage or a whole model-lifecycle module**.

The safe-now set is narrow and concrete:

- Forty-four earlier calibration definitions/constants, totaling approximately 740 source lines, are overwritten unconditionally by canonical `weather.model.variant_prediction_runtime` imports. Their public names and re-exports are live; the earlier bodies are dead.
- `served_stage_ablation.execute_served_calibration_stage_ablation` contains one unused local assignment.
- `mm_paper.build_paper_payload` retains two discarded fill-size return bindings and an unnecessary fallback assignment.
- The schema registry contains one exact duplicate name/version row and one second-name alias for the same version; uniqueness is not currently enforced.
- The structure/module-size governance reports are stale or incomplete: structure counts omit package-root modules, seven current size warnings lack ownership metadata, four ownership records point to paths that no longer exist, and the ownership document reports five warnings while the tool reports eleven.
- Five README `python -m` commands point at modules that do not exist.

The highest-maintenance risks are not dead code. They are duplicated authorities and oversized mixed-responsibility modules:

- point-in-time verification has two implementations that have already diverged;
- training and serving transforms are copied across calibration and model packages;
- maker and taker daily-roll orchestration repeat the same state machine;
- live-settlement scoring and captured-input replay parity share one 3,191-line module;
- release-evidence validation, release binding, and parent readiness composition share one 2,779-line module.

Model-lifecycle deletion is blocked. The latest stage-retirement register is `BLOCK`: all 25 incumbent stages are `BLOCK`, zero are `RETIRE`, and the served-stage E3/E4 artifact has zero paired dates and no frozen full-stack identity. `ResidualDistributionV1` is implementation-complete but is currently an unqualified research/replay candidate: requalification is `BLOCK`, stress is `INCONCLUSIVE`, live capture is disabled, no immutable release is installed, and no forward attestation exists.

Local release state is `RESEARCH_UNBOUND`, not proof that no production deployment exists elsewhere. `artifacts/releases/current_release.json` and the releases directory are absent locally. Current local capture therefore cannot establish a production-serving identity.

### Classification summary

| Classification | Verdict |
| --- | --- |
| CONFIRMED DEAD | 44 overwritten local bodies/constants; one ablation local assignment; discarded `mm_paper` bindings/assignment. No whole source module is confirmed dead. |
| LIKELY DEAD | Undocumented `weather.operations.runtime_identity` compatibility facade, subject to an external-import check. |
| SUPERSEDED/DUPLICATED | Point-in-time verifiers, train/serve transforms, HTTP retry policy, daily-roll scaffolding, writer-lock/file-hash helpers, and schema rows. |
| COMPATIBILITY SURFACE | 103 dated flat/root/script shims; legacy schema names; old residual-release API name; empty `markets.json` override shell. |
| EVIDENCE/ROLLBACK DEPENDENCY | All 25 incumbent stages, archived variant IDs, historical schemas, calibration artifacts, replay comparators, release binding, and rollback machinery. |
| DECOMPOSITION CANDIDATE | Ten behavioral modules over 2,000 lines have coherent extraction seams; `schema_registry_data.py` is large static data and is KEEP/DEFER. |
| FALSE POSITIVE | Retired research sentinels; `pooled_candidate_replay.market_verdict` re-export; apparently inactive variants needed for live diagnostics, replay, or historical joins. |
| GENERATED/RUNTIME STATE | `data/`, runtime logs/statuses, ignored audit outputs, and artifacts remain under their existing retention, manifest, and rollback contracts. |

## 2. Current codebase structure and complexity snapshot

### Git and worktree starting state

| Field | Starting value |
| --- | --- |
| Commit | `e4685cec29980f4bdfaf532148f787df4704351e` |
| Branch | `master` |
| Dirty state | Clean |
| Existing untracked files | None |
| Tracked files | 1,349 |

Untracked operational scripts appeared and, in some cases, disappeared during the audit. They were concurrent workspace activity, were not created or modified by this audit, and were excluded from findings. The initial clean state above remains the cleanup baseline; any such paths present at handoff must be preserved as unrelated work.

### Corrected physical-line inventory

Counts below use tracked files and Python `splitlines()`, including blank physical lines.

| Area | Python files | Physical lines | Notes |
| --- | ---: | ---: | --- |
| Canonical package `src/weather` | 385 | 257,286 | Includes 19 package-root modules. |
| All `src` | 471 | 258,985 | Adds 86 flat files, including the `src` namespace file and compatibility wrappers. |
| Tests | 272 | 94,790 | Includes three root test files. |
| App | 10 | 1,814 | Streamlit app and views. |
| Tools | 30 | 2,850 | Includes supported, fixture-only, and retired research sentinels. |
| Scripts containing Python | 1 | 605 | PowerShell/CMD/VBS files are not included in this row. |
| All tracked Python | 789 | 359,146 | Repository-wide. |

`weather.operations.structure_inventory` reported `source_py=366`, `source_lines=246723`, `test_py=269`, and `test_lines=94096`. Those figures omit 19 `src/weather/*.py` files (10,563 lines) and three `tests/*.py` files (694 lines). This is an audit-tool defect, not a second valid counting convention: package-root code includes core release, schema, retirement, IO, time, and artifact modules.

### Module-size snapshot

`weather.operations.module_size_audit` found 385 modules and eleven warnings at the 2,000-line threshold:

| Module | Lines | Current ownership metadata |
| --- | ---: | --- |
| `reporting/scorecards/live_variant_settlement_scorecard.py` | 3,191 | Missing boundary and next split |
| `reporting/serving_gates/production_readiness_gate.py` | 2,779 | Missing boundary and next split |
| `reporting/validation/point_in_time_evaluation.py` | 2,726 | Missing boundary and next split |
| `collection/snapshot_store.py` | 2,630 | Present |
| `market/mm_paper.py` | 2,613 | Present |
| `calibration/residual_distribution_v1.py` | 2,421 | Missing boundary and next split |
| `calibration/pooled_candidate_replay.py` | 2,287 | Missing boundary and next split |
| `model/model_sources.py` | 2,196 | Present |
| `operations/event_day_manifest.py` | 2,162 | Missing boundary and next split |
| `market/market_microstructure.py` | 2,114 | Missing boundary and next split |
| `schema_registry_data.py` | 2,069 | Present; static data shard |

`docs/operations/module-ownership-map.md` still says there are five warnings and names `daily_learning.py`, which is now 1,983 lines. The audit implementation also has four ownership notes for nonexistent pre-migration paths. The current tests do not require every warning to have a boundary/next split and do not reject orphan notes.

## 3. Runtime and operational entrypoint inventory

### Entrypoint mechanisms

| Surface | Reachability finding |
| --- | --- |
| Package metadata | `pyproject.toml` defines no console scripts. The supported CLI mechanism is `python -m weather...`. |
| Canonical module CLIs | 196 modules under `src/weather` contain a `__main__` guard. This is a broad research/operations command surface, not evidence that every command is scheduled. |
| Web app | Canonical Streamlit target is `app/streamlit_app.py`; root `app.py` is a dated compatibility wrapper. |
| Human launchers | `scripts/launch/start_weather_dashboard.{cmd,ps1,vbs}`. |
| Scheduled-task setup | `scripts/ops/*.ps1`; root `scripts/*` wrappers are dated compatibility surfaces. |
| Reusable helpers | `tools/backfill_all.py`, `tools/generate_market_specs_from_locations.py`, `tools/train_all_markets.ps1`, and the classified research harness. |
| CI | `.github/workflows/ci.yml` runs compile and full tests; `retrain.yml` also invokes canonical backfill, calibration, and artifact commands. |

### Windows Task Scheduler inventory

The host inspection found the following repository-related tasks. This is stronger reachability evidence than source grep alone.

| Task | State at inspection | Canonical action |
| --- | --- | --- |
| `WeatherClobBookLoopSupervisor` | Running | `weather.market.market_microstructure ensure` |
| `WeatherDailySettlementPromotionRefresh` | Ready | `weather.operations.daily_refresh run --stage settlement` |
| `WeatherEveningEvidenceRefresh` | Disabled | `weather.operations.daily_refresh run --stage evidence` |
| `WeatherLocationConfigRefresh` | Ready | `scripts/ops/refresh_location_config.ps1` |
| `WeatherMarketMakingDailyRoll` | Ready | `weather.operations.market_making_daily_roll start` |
| `WeatherMarketMakingDailyRollSupervisor` | Ready | `weather.operations.market_making_daily_roll ensure` |
| `WeatherModelMarketDisagreementAnalysis` | Ready | `weather.reporting.candidate_lifecycle.model_market_disagreement_analysis` |
| `WeatherNightlyRetrainValidatePromote` | Disabled | `weather.operations.nightly_retrain run` |
| `WeatherObservationTriggerSupervisor` | Ready | `weather.operations.observation_trigger ensure` |
| `WeatherSnapshotLoopSupervisor` | Running | `weather.collection.snapshot_tracker --ensure` |
| `WeatherTakerBotDailyRoll` | Ready | `weather.operations.taker_bot_daily_roll start` |
| `WeatherTakerBotDailyRollSupervisor` | Ready | `weather.operations.taker_bot_daily_roll ensure` |
| `WeatherTapeBackupAndRestoreDrill` | Disabled | `weather.operations.tape_backup run` |

No inspected task used a dated flat/root compatibility shim.

### Current release and runtime identities

| Identity | Observed state |
| --- | --- |
| Active immutable release | Missing local pointer and releases directory; loader result `RESEARCH_UNBOUND`; blank release/manifest/pointer IDs; `base_model_bound=false`. |
| Snapshot loop | Runtime identity at `e4685cec2998`, branch `master`. |
| Observation trigger | Runtime identity at `e4685cec2998`, branch `master`. |
| Maker daily roll | Target `2026-07-12`, identity `e4685cec2998`; status observed as `idle_process`. |
| Taker daily roll | Target `2026-07-12`, identity `e4685cec2998`; status observed as `idle_process`. |
| CLOB status artifact | Still recorded `2282faa108e2` during inspection even though the supervisor was running/restarting; treat as volatile/stale until reconciled. |
| Latest persisted reconciliation | `BLOCK` for target `2026-07-11`: 11 runtime identities across 15,994 snapshot rows. It predates this commit and is not current-release proof. |

The incumbent graph is operationally reachable through `snapshot_tracker`, which constructs the current model. Missing release binding makes current local capture non-countable; it does not make the incumbent code dead.

## 4. Model lifecycle and reachability map

### Variant registry snapshot

| Lifecycle | Count | Role summary |
| --- | ---: | --- |
| `control` | 1 | Shared pooled control. |
| `active` | 7 | Five no-market live diagnostic/quarantined rows plus two CLOB diagnostic headline rows. |
| `shadow` | 5 | Quarantined density, label-leak probe, two extra-location research controls, and disabled `ResidualDistributionV1`. |
| `archived` | 5 | Exact-winner alpha/smoke and dynamic-source smoke historical IDs. |

`active_registry_variants()` returns only the two headline CLOB rows, whereas the live-capture adapter can execute eight rows. Six executable live-capture contracts are omitted from the registry audit: Item50, exact-winner, dynamic-source, conservative bridge, Miami fallback, and quarantined continuous density. This is a registry-audit blind spot, not a reason to delete those variants.

### Incumbent stage reachability

Latest decision for every row below is `BLOCK`; none is `RETIRE`. “Serving” means the incumbent operational path, not verified production binding.

| Stage | Serving/shadow/replay/artifact reachability | Classification |
| --- | --- | --- |
| `binary_market_calibration_selector` | Live `ModelPresentationMixin.bin_probability`; incumbent/control replay; probability-calibration JSON. | EVIDENCE/ROLLBACK DEPENDENCY |
| `legacy_exact_distribution_calibration` | Final exact-distribution calibration; incumbent tape base; frozen/current comparator; calibration JSON. | EVIDENCE/ROLLBACK DEPENDENCY |
| `legacy_continuous_density_calibration` | Quarantined density shadow, density replay/parity, legacy density/calibration artifacts. | EVIDENCE/ROLLBACK DEPENDENCY |
| `legacy_served_power_normalization` | Exact served transform plus legacy density/band paths and serialized postprocess configuration. | EVIDENCE/ROLLBACK DEPENDENCY |
| `forecast_floor` | Incumbent distribution path, captured base, comparator/attribution evidence. | EVIDENCE/ROLLBACK DEPENDENCY |
| `forecast_pull` | Incumbent distribution path, captured base, comparator/attribution evidence. | EVIDENCE/ROLLBACK DEPENDENCY |
| `warm_tail_falsification` | Incumbent path, replay, hardening/attribution controls. | EVIDENCE/ROLLBACK DEPENDENCY |
| `bucket_transition` | Incumbent path, replay, historical behavior controls. | EVIDENCE/ROLLBACK DEPENDENCY |
| `afternoon_residual_centering` | Incumbent path, replay, bound/shared release JSON and evidence. | EVIDENCE/ROLLBACK DEPENDENCY |
| `observation_support_floor` | Incumbent distribution support, replay, tape fields. | EVIDENCE/ROLLBACK DEPENDENCY |
| `upper_tail_cap` | Incumbent distribution path and behavior snapshots. | EVIDENCE/ROLLBACK DEPENDENCY |
| `continuation_adjustment` | Incumbent late-day path and coefficients. | EVIDENCE/ROLLBACK DEPENDENCY |
| `late_day_lockin` | Incumbent and pooled band postprocess, replay, tape/config fields. | EVIDENCE/ROLLBACK DEPENDENCY |
| `hard_floor_postprocess` | Live-captured pooled candidates and candidate replay; pooled artifact fields. | EVIDENCE/ROLLBACK DEPENDENCY |
| `support_floor_postprocess` | Live-captured pooled candidates and candidate replay; pooled artifact fields. | EVIDENCE/ROLLBACK DEPENDENCY |
| `adjacent_band_calibration` | Diagnostic shadow/replay and exact/density artifact configuration. | EVIDENCE/ROLLBACK DEPENDENCY |
| `exact_winner_catchup` | Active diagnostic variant, candidate replay, archived alpha/smoke IDs, v0.4 artifacts. | EVIDENCE/ROLLBACK DEPENDENCY |
| `forecast_centering` | Diagnostic pooled variants, replay, serialized postprocess config. | EVIDENCE/ROLLBACK DEPENDENCY |
| `market_bias_calibration` | Diagnostic pooled variants, replay, serialized postprocess config. | EVIDENCE/ROLLBACK DEPENDENCY |
| `partition_normalization` | Enabled in band live adapter, replay equivalent, serialized gamma/config evidence. | EVIDENCE/ROLLBACK DEPENDENCY |
| `current_incumbent_blend` | Live diagnostic variants, replay, validation evidence. | EVIDENCE/ROLLBACK DEPENDENCY |
| `cutoff_hour_model_router` | Live HGB/LR per-hour selection, captured base, replay, per-hour model dictionaries. | EVIDENCE/ROLLBACK DEPENDENCY |
| `dynamic_source_state_router` | Dynamic-source variant/current-blend state, replay, v0.5 source-state artifact columns. | EVIDENCE/ROLLBACK DEPENDENCY |
| `silent_model_family_fallback_router` | Live HGB → LR → empirical fallback on broad exceptions; inherited by shadow/replay. | KEEP pending explicit-route migration |
| `unknown_market_toronto_fallback_router` | Reachable through market registry/config default semantics; event gates may block later. | KEEP pending explicit abstention migration |

The release verifier forbids release-manifest fallback flags, but that does not disable the in-process HGB → LR → empirical exception fallback. The two semantics must not be conflated in retirement evidence.

### `ResidualDistributionV1`

| Surface | Status |
| --- | --- |
| Serving | No active serving and no local active release. |
| Shadow | Registry lifecycle `shadow`, but `live_capture_enabled=false`; requires exact immutable `SHADOW_BOUND` opt-in after offline qualification. |
| Replay/comparator | Explicit replay adapter and prediction mode are live. |
| Research | Training, locked-window evaluation, stress, ablation, release construction, and graph audit are live. |
| Artifact compatibility | Current v0.2 candidate plus archived schema metadata; historical schemas remain registered. |
| Current evidence | Requalification `BLOCK`; stress `INCONCLUSIVE`; E3/E4 `BLOCK`; zero `RETIRE`; no immutable release or attestation. |

The verified V1 graph audit finding that V1 calls none of the legacy stage categories proves isolation. It does **not** satisfy the incumbent retirement contract.

## 5. Confirmed and likely dead-code table

### Deletion candidates

| ID | File and symbol | Purpose/callers | Evidence and classification | Action and preconditions | Tests/docs/rollback | Payoff / implementation risk |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | `calibration/pooled_band_training.py`: `predict_band_probabilities`, `apply_band_postprocessing`, `normal_cdf`, `forecast_anchor_probability`, `forecast_centering_alpha`, `apply_forecast_centering`, `calibration_hour_bucket`, `calibration_gap_bucket`, `adjacent_calibration_contexts`, `adjacent_calibration_factor`, `apply_adjacent_calibration`, `market_bias_calibration_contexts`, `market_bias_calibration_factor`, `apply_market_bias_calibration`, `source_trust_bucket`, `exact_winner_catchup_contexts`, `exact_winner_catchup_factor`, `apply_exact_winner_catchup`, `predict_band_rows_for_bundle` | Historical training-slice bodies; external callers use the public names. | **CONFIRMED DEAD BODIES / SUPERSEDED**. All 19 are overwritten at lines 995–1015 by canonical runtime objects; no module-scope load occurs first; normalized bodies match the canonical implementations. | Delete only earlier bodies, retain explicit imports/re-exports and stable symbol names. First snapshot `__all__`, prove no import cycle, and add object-identity/golden-vector tests. | Pooled feature/replay/live prediction/current blend/density tests; update runtime-audit baseline. Rollback: restore bodies without moving imports. | High: ~295 misleading lines and less F811 noise / Low behavior, medium import-order risk. |
| D2 | `calibration/pooled_feature_assembly.py`: `finite_float`, `temperature_scale_probability`, `late_lockin_strength_from_features`, `band_outcome`, `hard_floor_probability`, `support_floor_cap`, `late_lockin_target`, `native_value_to_f`, `native_delta_to_f`, `record_unit`, `canonical_density_record(s)`, `feature_frame`, `band_prediction_record`, `band_feature_frame` | Historical feature-assembly bodies; live callers resolve aliases. | **CONFIRMED DEAD BODIES / SUPERSEDED**. Overwritten at lines 1218–1234; no import-time consumer; canonical objects own runtime and pickle identity. | Same constrained deletion as D1; retain facade names. | Feature-store, pooled-feature, residual replay, release and live parity tests. Rollback: restore bodies. | High: ~303 lines / Low behavior, medium slice-order risk. |
| D3 | `calibration/pooled_candidate_replay.py`: `density_projection_index`, `density_projection_probability`; `calibration/pooled_candidate_replay_diagnostics.py`: microstructure constants plus `probability_logit`, `cutoff_hour_bucket`, `_micro_float`, `microstructure_feature_record`, `microstructure_feature_frame`; `calibration/pooled_training.py`: `predict_density_rows_for_bundle` | Compatibility-slice copies; names are live through later imports. | **CONFIRMED DEAD BODIES / SUPERSEDED**. Later imports overwrite them; runtime identities are canonical; no module-scope pre-overwrite loads. | Delete earlier copies only, preserve re-exports. Add alias identity and exact parity tests. | `test_pooled_candidate_replay`, microstructure, pooled training, residual release. Rollback: restore copies. | High: ~142 lines / Low behavior, medium import-order risk. |
| D4 | `calibration/served_stage_ablation.py:1194`, local `primary` | Was presumably a convenience alias for the remove-one arm. No caller can observe it. | **CONFIRMED DEAD**. Assigned once, never loaded; subsequent code indexes the summary maps directly. Strict runtime audit reports unowned F841. | Delete the assignment. No migration precondition. | `tests/calibration/test_served_stage_ablation.py`; remove the unowned runtime-audit finding. Rollback: restore one line. | Tiny / Negligible. |
| D5 | `market/mm_paper.py:2203,2214,2220`, `_leg_fill_sizes` and `_model_variant_leg_fill_sizes` bindings | Fill simulation’s fourth return is discarded; simulation calls and first three outputs are live. | **CONFIRMED DEAD BINDINGS**. Neither variable is read. The else-only `Counter()` assignment is wholly dead. | Bind the fourth tuple position to `_`; delete line 2214. Do not remove either simulator call. | `tests/market/test_mm_paper.py`, covering both fill-simulation branches. Rollback: restore local bindings. | Low / Negligible. |
| L1 | Entire `operations/runtime_identity.py` facade | Five-line star re-export of `weather.runtime_identity`; known first-party callers: none. | **LIKELY DEAD**. No tracked imports, path/full-name references, CLI, package re-export, scheduled action, documentation, config, test, or tracked artifact string. Callable `__module__` remains canonical. An external import remains unverified. | Add it to a dated compatibility inventory or deprecate/remove only after an external/local import check. | Runtime identity, import architecture, compile. Rollback: restore five-line facade. | Low / Low-medium external API risk. |

### Negative-evidence checklists for proposed deletions

| Candidate | Static imports/calls | Re-exports/dynamic dispatch | CLI/app/scripts/workflows/tasks | Tests/config/registries/schemas/docs | Serialization/artifacts/replay | External uncertainty |
| --- | --- | --- | --- | --- | --- | --- |
| D1–D3 earlier bodies | All live loads resolve after overwrite; no module-scope pre-overwrite load. | Public names retained as canonical re-exports; registries refer to names/modes, not earlier function objects. | No entrypoint executes a body before overwrite. | Tests call aliases; no configuration or schema selects the earlier objects. | Runtime objects report canonical model module; tracked artifact strings do not bind dead calibration bodies. | None material if symbol names/import positions remain stable. |
| D4 local `primary` | No load in function AST or source search. | Local variable cannot be dynamically imported or serialized. | Not applicable. | Focused ablation tests cover surrounding behavior. | No artifact field derives from the variable. | None. |
| D5 tuple bindings | No load after assignment; simulator calls remain. | Locals are not exported. | No CLI/config selects the discarded return binding. | `mm_paper` tests cover branch behavior. | Fill rows/queues/diagnostics remain unchanged. | None. |
| L1 facade | No tracked inbound import/call. | Not re-exported by `operations.__init__`; callable identities are canonical. | No `__main__`, app, workflow, script, README command, or inspected scheduled task. | No tracked test/config/schema/doc full-name occurrence. | No tracked artifact byte string; function pickle identities are canonical. | External Python imports and non-Task-Scheduler automation were not verifiable; therefore LIKELY, not CONFIRMED. |
| Exact duplicate schema row | One identical name/version exists in both static shards. | Dictionary lookup already selects the later row; registry payload currently exposes both. | No CLI selects the earlier record. | Tests lack uniqueness assertions; docs describe only one logical schema. | Historical artifacts store version, not which duplicate row supplied it. | External consumers may have tolerated the duplicate registry payload; change with a schema-registry test/release note. |

### Apparent dead code that must stay

| Surface | Why it is not dead |
| --- | --- |
| Nineteen retired `tools/research` scripts | `research_harness.SCRIPT_INVENTORY` inventories them, `test_research_harness` invokes every retired script with `--help`, and generated-state cleanup explicitly preserves documented retired sentinels. They are **FALSE POSITIVE / KEEP** unless the sentinel policy is retired deliberately. |
| `pooled_candidate_replay.market_verdict` import | Public compatibility re-export consumed by tests and callers. A same-named local result causes the F811 signal. Rename the local to `candidate_market_verdict`; keep the import. |
| Archived alpha/smoke variants | Historical replay/report IDs and evidence joins depend on stable names. |
| Legacy schemas | Supersedes chains, historical artifact audit, and external artifacts may depend on them even when the current runtime rejects old model payloads. |
| Missing active release paths | Loader fallback is an explicit `RESEARCH_UNBOUND` non-countable state, not a signal to delete release binding or incumbent code. |

## 6. Duplication and consolidation opportunities

| Finding | Exact evidence and callers | Recommended consolidation | Preconditions / affected tests and docs / rollback | Payoff / risk |
| --- | --- | --- | --- | --- |
| Point-in-time verification has two authorities | `weather.point_in_time_contract` defines `verify_validation_plan_payload`, `verify_streaming_evaluation_payload`, and `verify_production_point_in_time_artifacts`; `reporting/validation/point_in_time_evaluation.py` redefines all three. `release_artifacts.py` uses the root version; `residual_distribution_release.py` uses the reporting version. The reporting version has stricter manifest/artifact/date checks. | Port the strict superset into dependency-safe `weather.point_in_time_contract`; make reporting delegate/re-export. | Add conformance tests for tampered manifest/artifact identities, target dates, lanes, locks and intervals. Update point-in-time docs. Keep wrapper for rollback. | Very high / Medium-high evidence risk. |
| Live training/serving transforms are copied | Exact duplicates span `pooled_feature_assembly`, `pooled_band_training`, `pooled_density_training`, `pooled_candidate_replay_diagnostics`, `probability_calibration`, `variant_prediction_runtime`, and `calibration_runtime`. | Make serving-safe pure transforms under `weather.model` canonical; calibration imports/re-exports them. Do not introduce model → calibration. | Golden vectors across F/C units, tails/ranges, NaN/missing features, source state, legacy artifacts; exact replay/live parity. | Very high / Medium. |
| HTTP retry policy duplicates and creates an entire package edge | `model_sources.py:146–193` duplicates `sources/forecast_history.py:228–279`. The only `market -> model` imports are three market modules importing this helper. | Move retryability, Retry-After, backoff and request helper to `weather.sources.http`; leave old re-exports; repoint market modules; remove the transitional edge. | Collection robustness, source-cache TTL, market-microstructure, import architecture. Update package-boundary docs and ratchet. | High / Low-medium. |
| Maker/taker daily-roll scaffolding | Exact time/date/JSON/process/path-stat helpers and near-identical start/status/disk/quarantine/launch state machines in `market_making_daily_roll.py` and `taker_bot_daily_roll.py`. | First extract exact helpers to a small common operations owner. Generalize the state machine only after golden payload characterization; keep maker/taker liveness policy in adapters. | Both daily-roll suites and supervisor tests; preserve public imports and task commands. Roll back via wrapper delegation. | High / Medium, then medium-high. |
| Writer-lock primitives appear twice | `weather.io` and `operations.supervisor` both define writer-lock path, owner payload, stale check, acquire and release functions; consumers split between the two. | Canonicalize in `weather.io`; supervisor re-exports during migration. | Lock contention/stale-lock/PermissionError tests and existing supervisor/collection/market tests. | Medium / Low-medium. |
| File hashing is cloned | Eleven definitions in five shapes; six exact copies in point-in-time contract, release artifacts, residual corpus, cleanup preflight, closed-day archive and event-day manifest. | Add one dependency-free canonical file hash helper under shared IO/artifacts; preserve old aliases. | Golden hashes and manifest/cleanup/release tests. | Medium / Low. |
| Time/report writers are copied broadly | 72 `utc_iso` definitions, 60 `write_json` definitions, 26 `read_json` definitions, and many identical `write_outputs` functions. | Migrate only semantically identical forms; forbid new clones. Define named durability tiers before consolidating atomic writers. | Explicit tests for timezone/naive inputs, defaults, newline, retry, file fsync and directory fsync. | Medium / Medium if done mechanically; high risk if blanket-replaced. |
| Schema rows are duplicated | `taker_current_replay_profitability_verification_v0.1` is registered twice under the same name/version. Version `taker_profitability_artifact_verification_v0.2` is registered under both `..._composite` and `..._v0_2`. | Remove the exact duplicate row. Choose one canonical v0.2 name, retain the other as an explicit deprecated alias only if callers require it. Enforce unique name and deliberate version aliases. | Schema payload/lookup tests, strict audit, external consumer check, schema docs. Restore rows to roll back. | Medium audit clarity / Low for exact duplicate, medium for alias migration. |

## 7. Oversized-module decomposition plan

A split is proposed only where there is a coherent responsibility boundary and testable dependency direction.

| Module | Coherent extraction | Dependency direction and public surface | Acceptance / rollback | Payoff / risk |
| --- | --- | --- | --- | --- |
| `live_variant_settlement_scorecard.py` | Move parity normalization, comparison, persistence and parity rendering (roughly lines 1974–3020) to `reporting.validation.captured_input_replay_parity`. | Settlement scorecard facade/CLI imports parity owner; parity owner must not import the facade. Preserve existing exports. | Byte-identical scorecard/parity payloads; daily refresh, nightly retrain, residual release and scorecard tests. Revert delegation for rollback. | High / Medium. |
| `production_readiness_gate.py` | Extract child evidence validators/spec registry; separately extract active-release verification and pointer attestation. Leave parent gate composition. | Parent composer depends on evidence contract and release binding; extracted modules never import parent facade. | Byte-identical PASS/BLOCK payloads, unchanged first-blocker ordering, pointer-change safety, release tests. | High / Medium-high. |
| `point_in_time_evaluation.py` | Separate canonical materialization, fold/fit receipts, streaming evaluator and CLI after consolidating verifier authority. | Shared frozen contracts remain dependency-safe; calibration owns training receipts; backtesting/reporting consumers use stable contracts without new cross-owner cycles. | Exact materialization hashes, receipt binding, bounded-read failures and release conformance. | Very high / Medium-high. |
| `snapshot_store.py` | Extract content-addressed payload persistence; explanation/reconstruction/backfill; replay-input collaborator. Existing backfill module currently only calls methods still on `SnapshotStore`. | `SnapshotStore.write` orchestrates collaborators; public methods delegate. Collaborators do not import the facade. | Byte-identical sidecars/replay rows and hashes; idempotent backfill; forecast-persistence and feature-store tests. | High / Medium. |
| `mm_paper.py` | Move reward diagnostics, model-variant promotion gates or fill-evidence completeness helpers; tape/fill/P&L scoring is already extracted. | Orchestration facade depends on scoring/evidence owners; extracted owners do not import facade. | Exact paper payload/report and promotion decisions across fill/no-fill branches. | High / Medium. |
| `residual_distribution_v1.py` | Extract receipt construction/verification and nested/locked evaluation; leave qualification/orchestration and CLI. | Facade/orchestrator → evaluation → fit/receipts; never extracted module → facade. | Candidate artifact/hash, OOF/final receipts, locked-window decisions and release tests unchanged. | High / Medium. |
| `pooled_candidate_replay.py` | Extract cache/sentinel/result-aggregation subsystem (roughly lines 1307–1757). | Replay orchestrator calls cache owner; cache owner does not import replay facade. | Same cache keys, sentinel decisions, forensics and replay payloads. | High / Medium. |
| `model_sources.py` | After shared retry extraction, split provider adapters from source assembly/health/cache. | Provider implementations move toward `weather.sources`; `SourceFetchMixin` delegates/re-exports. Pass explicit session/spec/time/cache dependencies. | Source cache TTL, degradation, provider parsing, fallback and model-source tests. | High / Medium. |
| `event_day_manifest.py` | Extract folder discovery, existing-state/storage-gate summary, backfill report and CLI; keep family inventory/build/validate core. | Backfill owner imports core; core must not import backfill facade. Move pure formatting/hash helpers to shared owners. | Identical manifest hashes, validation and deletion-candidate decisions. | Medium-high / Medium evidence risk. |
| `market_microstructure.py` | Extract tape audit; extract supervisor/process/start/ensure; leave loop implementations and a stable CLI facade. | Market-making callers use audit owner; fleet/ops callers use supervisor owner; facade delegates. | Existing task commands, lock/process/status behavior and tape audit results unchanged. | High / High operational risk. |
| `schema_registry_data.py` | No behavioral split required now. Future growth can shard by producer family while preserving concatenation order and lookup equality. | Static shards import only registry types. | Registry payload and lookup equality. | Low / Low. Classification: KEEP/DEFER. |

## 8. Package-boundary debt and proposed burn-down

The architecture ratchet passes and found no stale transitional edge. Current debt is still substantial:

| Transitional edge | Files |
| --- | ---: |
| `backtesting -> collection` | 1 |
| `backtesting -> operations` | 1 |
| `backtesting -> reporting` | 2 |
| `calibration -> operations` | 2 |
| `calibration -> reporting` | 8 |
| `collection -> backtesting` | 1 |
| `market -> backtesting` | 3 |
| `market -> collection` | 3 |
| `market -> model` | 3 |
| `operations -> reporting` | 17 |
| `reporting -> calibration` | 11 |
| `reporting -> operations` | 10 |

Recommended burn-down order:

1. Remove `market -> model` completely by moving the shared HTTP policy to a source/shared owner.
2. Remove `backtesting -> collection` by moving `coverage_summary`, `local_window`, and `parse_times` to a read-only shared coverage/time contract; collection can keep re-exports.
3. Move pure `reporting.formatting` implementation to `weather.formatting`, retaining a reporting facade. This reduces backtesting/calibration/operations pressure without inventing a new owner edge.
4. Move the pure artifact disk-budget preflight out of reporting data-quality and into shared artifact/IO ownership.
5. Use the point-in-time consolidation to remove calibration/release dependence on reporting-owned verification.

Every edge removal must update `TRANSITIONAL_PACKAGE_EDGES`, `docs/operations/package-boundaries.md`, structure inventory evidence and architecture tests in the same change. Do not replace an edge with a new undocumented cross-owner dependency.

## 9. Compatibility-shim retirement status

The dated policy begins `2026-06-18` and expires `2026-07-18`. Today is six days early.

| Shim class | Actual count | Documented count | Status |
| --- | ---: | ---: | --- |
| Flat `src/*.py` wrappers | 85 plus `src/__init__.py` | 86 wrappers | Retain until policy date; clarify namespace vs wrapper count. |
| Root app/helper shims | 4 | 1 app + 3 helpers | Retain until policy date. |
| Root `scripts/*` wrappers | 14 | 9 | Retain until policy date; correct inventory now. |
| Total compatibility shims | 103 | 99 implied | Retain until policy date. |

The first-party caller ratchet passes, and inspected tasks use canonical commands. External shortcuts, desktop launch paths and automation outside Task Scheduler remain unverified. Therefore no shim batch is safe to delete before the checklist date.

After `2026-07-18`, remove only batches whose first-party scan remains clean and whose external check is negative. Update the architecture ratchet, docs and launch smoke tests with each batch. Do not rename `scratch.py`; delete the misleading wrapper when eligible rather than creating a second compatibility name.

The internal `weather.operations.runtime_identity` facade is not in this policy. Either inventory it with an expiry or remove it after its own external-import window.

## 10. Registry, schema, configuration, and CLI cleanup findings

| Surface | Finding | Classification and action |
| --- | --- | --- |
| Model variant registry | `active_registry_variants` means headline-active, not all executable live variants; audit covers 2 while capture can run 8. | **STALE ABSTRACTION / P1**. Introduce explicit `headline_registry_variants` and `live_capture_registry_variants`; audit both with lane-specific requirements; keep old name as temporary alias. |
| Registry semantics | Five lifecycle-`active` no-market rows are blocked, non-headline, legacy-validation-quarantined but intentionally live-captured. CLOB diagnostic rows omit an explicit weather-promotion boolean. | **NAMING/CONFIG DRIFT / P0 docs and explicit fields**. Document active collection vs headline/promotion; make decision booleans explicit. Defer lifecycle value changes until report parity is proven. |
| Schemas | Strict audit: 460 registered, 757 discovered literals, zero unregistered, seven explicit exclusions. | **KEEP** overall. Lack of an unregistered literal does not prove producer/consumer reachability. |
| Schema uniqueness | Exact duplicate current-replay verification row; two names share v0.2 profitability version. | **SUPERSEDED/DUPLICATED**. Add unique-name and intentional-version-alias assertions, remove exact duplicate, migrate/deprecate alias deliberately. |
| Historical schemas | Residual v0.1/v1 and pooled density v0.1–v0.6 are superseded or rejected by current runtime. | **COMPATIBILITY/EVIDENCE**. Retain for external artifacts, supersedes chains and replay audit until a historical inventory proves removal safe. |
| Configuration | Config inventory passes: six configs, zero warnings. | **KEEP**. No field is proven written-never-consumed in this pass. |
| `config/markets.json` | Empty deprecated override shell, but market registry and release candidate contract still load/copy it. | **COMPATIBILITY SURFACE**. Keep until that contract is migrated. |
| CLI arguments | No argument was proven behaviorless. Several facade CLIs inject/delegate the `args` namespace, making same-file attribute scans unreliable. | **KEEP / no finding**. Add command-level behavior tests before removing an option. |
| Residual release API | Documented `build_residual_distribution_v1_offline_release` is a thin alias of older `build_*_candidate_release`; tests still use the old name. | **COMPATIBILITY/NAMING**. Make offline name canonical and deprecate old alias after external import scan. |
| Artifact receipt wording | `release_eligible=true` can mean candidate namespace/path policy passes while `candidate_release_eligible=false` means qualification is blocked. | **MISLEADING NAME**. Migrate to an explicit namespace/path-policy field with a compatibility alias. |

## 11. Test and fixture cleanup opportunities

| Finding | Action | Payoff / risk |
| --- | --- | --- |
| Module-size governance tests fail open | Require every WARN row to have owner/boundary/next split; require every ownership-note path to exist; validate or generate the ownership document bidirectionally. | High audit reliability / Low. |
| Structure inventory fixture misses root modules | Add root `src/weather/*.py` and root `tests/*.py` cases and assert corrected totals. | High audit reliability / Low. |
| Documentation command existence is not tested | Parse active README/operations `python -m weather...` commands and assert module targets exist, with an explicit allowlist for placeholders. | Medium / Low. |
| Maker/taker daily-roll suites repeat scenarios | After common helper extraction, parameterize common date, disk, stale PID, quarantine and launch-state cases; retain bot-specific liveness tests. | Medium / Medium if done before production extraction; low after. |
| Exact duplicate test helpers | `_write_json`, `_write_jsonl`, `_write_csv`, timestamp and HGB fixture helpers repeat in a few files. Keep local helpers unless a production extraction creates a stable shared fixture contract; a global helper layer would add coupling for little benefit. | Low / Low. |
| Unused test-only bindings | `tests/operations/test_daily_refresh.py` local `_run` and `tests/reporting/test_trading_evidence.py` local `_new_run` retain only side-effect results. Delete bindings but keep calls. | Tiny / Negligible. |
| Research sentinels | Harness validation and smoke make them intentional controls. | KEEP / FALSE POSITIVE. |
| Registry/schema tests | Add registry lane coverage and schema unique-name/version-alias invariants. | High / Low-medium. |

## 12. Documentation and naming drift

### Broken README commands

The following documented canonical commands point to modules that do not exist:

- `README.md:198` — `weather.reporting.daily_learning`
- `README.md:233` — `weather.reporting.fleet_observability`
- `README.md:234` — `weather.reporting.data_layer_audit`
- `README.md:236` and `:237` — `weather.reporting.data_auditor`

They should point to current nested owners (`reporting.daily`, `reporting.fleet`, and `reporting.data_quality`) or to intentionally retained facades that actually exist.

Additional drift:

- `module-ownership-map.md` reports five warnings instead of eleven and includes one module now below threshold.
- Four `module_size_audit.OWNERSHIP_NOTES` paths predate package moves.
- The compatibility inventory undercounts root scripts and conflates `src/__init__.py` with wrappers.
- `pooled_candidate_replay.py` is described as a compatibility facade but remains a 2,287-line live orchestrator.
- `snapshot_store_backfill.py` is described as owning backfill implementation, but it delegates back to 236 lines of `SnapshotStore` methods.
- Registry lifecycle `active` currently mixes “actively collected” with headline/promotion semantics.
- `scratch.py` is actually a market-spec generator compatibility wrapper.
- The residual release API and artifact “release eligible” receipt field use names broader than their current semantics.

## 13. Cleanup work order

### P0 — high-confidence, behavior-preserving

1. Fix audit governance first: structure root counts, module ownership metadata/path validation, ownership documentation, compatibility counts and README command targets.
2. Remove D4 and D5 dead locals/bindings.
3. Remove D1–D3 overwritten bodies while retaining canonical imports/re-exports; reduce the runtime-audit F811 baseline only after identity/parity tests pass.
4. Remove the exact duplicate schema row and add uniqueness/alias tests; do not yet remove a public schema alias.
5. Add explicit registry decision booleans and clarify active-collection vs headline/promotion semantics without changing lifecycle behavior.

### P1 — consolidation and bounded extraction

1. Consolidate point-in-time verification into the dependency-safe contract.
2. Move HTTP retry policy to source/shared ownership and retire the complete `market -> model` edge.
3. Canonicalize train/serve pure transforms with golden live/replay equivalence.
4. Extract captured-input replay parity from the live settlement scorecard.
5. Add registry audit coverage for all live-capture variants.
6. Extract exact maker/taker daily-roll helpers; defer common state-machine generalization until payload characterization is complete.
7. Canonicalize writer locks and exact file hashing behind compatibility re-exports.

### P2 — migration or external verification required

1. Deprecate/remove `weather.operations.runtime_identity` after an external import window.
2. Generalize the maker/taker daily-roll state machine.
3. Split production readiness, point-in-time ownership, SnapshotStore, Residual V1, pooled replay cache, model providers, event manifest and market microstructure in the bounded order above.
4. Migrate schema v0.2 alias names, residual release API names and artifact receipt field names.
5. Remove low-pressure package edges only with matching architecture ratchets and docs.

### DEFER

- Every incumbent stage deletion: blocked until the exact row has a verified `RETIRE` decision.
- Any Residual V1 promotion or incumbent replacement: blocked by offline qualification, immutable release, shadow binding, exact parity and forward attestation.
- Compatibility shim deletion before `2026-07-18` and before external checks.
- Historical schema/variant/artifact cleanup without a bounded historical-consumer and rollback inventory.
- `data/` or `artifacts/` cleanup outside storage-class, event-day manifest, archive/restore, release and cleanup-manifest contracts.
- Static schema registry sharding solely for line count.

## 14. Five highest-value next actions

### 1. Make the audit ratchets truthful

Acceptance criteria:

- Structure inventory reports 385 canonical modules and 257,286 lines for this commit, including package-root code.
- Test counts include root tests.
- Every size WARN has owner, boundary and next split.
- Every ownership note path exists.
- Ownership documentation and compatibility counts match generated evidence.
- All active documented `python -m weather...` targets exist.

### 2. Remove the 740 lines of shadowed implementations safely

Acceptance criteria:

- All 44 public aliases remain importable from existing calibration facades.
- Representative and then complete alias identity tests prove they resolve to canonical runtime functions.
- Golden train/replay/live vectors are unchanged byte-for-byte or within the already-declared exact tolerance.
- Legacy artifact loading and pickle import paths remain valid.
- F811 baseline entries are reduced only for removed copies; no new import cycle appears.

### 3. Establish one point-in-time verification authority

Acceptance criteria:

- Both release paths call the same dependency-safe verifier.
- Both reject identical tampering of manifest identity, candidate artifact identity, target dates, lanes, window locks, receipts and clustered intervals.
- Existing valid point-in-time fixtures remain accepted.
- No new package-boundary exception is introduced.

### 4. Audit the actual live variant set

Acceptance criteria:

- Registry API names distinguish headline, live-capture, report-only and archived selections.
- Audit covers all eight currently executable live rows, not only two headline rows.
- Each live row has explicit artifact/export/capture/promotion requirements and a named severity for intentionally unbound diagnostics.
- Existing live tape and scorecard membership is unchanged.

### 5. Retire the `market -> model` transitional edge

Acceptance criteria:

- One canonical source/shared HTTP retry policy owns retryable status, Retry-After parsing, backoff and request execution.
- Model/source legacy imports remain available through temporary re-exports.
- All three market callers import the neutral owner.
- Source-cache, collection robustness and market-microstructure tests pass.
- Architecture test and package-boundary documentation remove `market -> model` in the same change.

## 15. Explicit uncertainties and external dependencies

- External production deployment state, remote release stores and off-host active pointers were not available. Local `RESEARCH_UNBOUND` must not be generalized to “no production serving anywhere.”
- External Python callers, desktop shortcuts and automation outside inspected Windows Task Scheduler could not be proven absent. This blocks early shim and internal-facade deletion.
- Ignored/local historical artifacts were not subjected to an unbounded pickle/string scan. Tracked artifacts and runtime object identities were checked. Historical schema and import compatibility therefore remain conservative.
- Runtime status is moving while scheduled workers run. Snapshot/observation/maker/taker identities were current at inspection, while CLOB status and persisted reconciliation lagged. Concurrent untracked operations scripts also appeared during the pass and were left untouched.
- The full pytest suite did not finish within a roughly ten-minute bounded audit window and was stopped without a result. Focused suites and static/runtime gates are recorded below.
- Data/artifact size and age were intentionally not used as deletion evidence. No full retention scan or cleanup preflight was requested or run.
- The severity policy for a live diagnostic variant with an intentionally absent artifact needs an owner decision before expanding registry audit from headline rows to all live rows.
- Schema aliases may be consumed externally through registry-name lookup even when stored artifacts contain only version strings.

## Validation record

| Command/check | Result |
| --- | --- |
| `git status --short` at start | Clean; no untracked files. |
| `python -m weather.operations.structure_inventory` | Completed: 1,349 tracked, reported 366 source modules, 82 modules over its 1,000-line inventory threshold, 103 shims. Root-count defect documented above. |
| Structure inventory with architecture ratchet | Architecture subtest `20 passed`; status PASS. |
| `python -m weather.operations.module_size_audit` | Completed: 385 modules, 11 warnings at 2,000 lines. |
| Strict Python runtime/static audit | `BLOCK`: log-signature ownership plus one new unowned F841 at `served_stage_ablation.py:1194`; Streamlit route and daily-refresh smoke PASS. |
| Strict schema registry audit | PASS: 460 registered, 757 discovered literals, 0 unregistered, 7 exclusions. |
| Config inventory | PASS: 6 configs, 0 warnings. |
| `python -m compileall -q app src tests tools weather` | PASS after retrying outside concurrent bytecode readers. |
| Architecture/path/structure/module-size tests | 28 passed. |
| Schema and variant registry tests | 13 passed. |
| Release lifecycle/import/residual release/serving/retirement/ablation tests | 67 passed. |
| Independent focused reachability suite | 153 passed and 2 subtests passed; overlaps the suites above. |
| Independent focused lifecycle suite | 66 passed; overlaps the suites above. |
| Research harness validation/smoke | PASS. |
| Full pytest | Attempted, did not complete within the bounded window, stopped without a result. |

The final handoff must also pass `git diff --check`. This audit's only source-controlled deliverable is this report; unrelated concurrent untracked files must remain untouched.
