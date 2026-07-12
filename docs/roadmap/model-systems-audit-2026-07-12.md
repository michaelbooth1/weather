# Principal ML Systems Audit — 2026-07-12

## Scope, method, and evidence boundary

This is an audit-first, read-only assessment of the weather data, model, replay,
calibration, serving, and promotion system at
`C:\Users\micha\Desktop\github\weather`. No model behavior, release pointer,
worker, schedule, live configuration, or operational data was changed. No
release was promoted, no process was restarted, and no heavy training or
unbounded data scan was run. The two pre-existing worktree changes were
preserved.

The machine-readable evidence register is
[`model-systems-audit-2026-07-12-evidence.json`](model-systems-audit-2026-07-12-evidence.json).
All live-state counts in this report are bound either to an artifact generation
timestamp and SHA-256 or to a stated bounded-scan timestamp. A code path, schema,
test, or old PASS is treated only as mechanism evidence unless a current,
identity-bound artifact proves execution.

Conclusion labels have these meanings:

- **OBSERVED** — directly proven by inspected code, a current artifact, or a
  bounded command.
- **INFERRED** — the evidence strongly supports the conclusion, but its effect
  size was not directly measured.
- **HYPOTHESIS** — a predeclared experiment is required.
- **RECOMMENDATION** — proposed work, not evidence of current behavior.

### Audit identity

| Field | Value | Classification |
| --- | --- | --- |
| Audit start | `2026-07-12T13:01:25.7267419-04:00` / `2026-07-12T17:01:25.7287418Z` | **OBSERVED** |
| Timezone | Windows `Eastern Standard Time`; IANA `America/Toronto` | **OBSERVED** |
| Commit / branch | `aaec67fc70fab80a07c05b01608e3e8b9cd6bea1` / `master` | **OBSERVED** |
| Pre-existing dirty paths | `config/location_market_events.json`, `config/locations.json` | **OBSERVED** |
| Request SHA-256 | `52b1cc6312ee4c46a9f1445341b097115ff9885278b56d606102cd572707ed89` | **OBSERVED** |
| Active release pointer | `artifacts/releases/current_release.json` is absent | **OBSERVED** |
| Serving identity | `STATUS_RESEARCH_UNBOUND`; mutable global artifacts may load | **OBSERVED**, `src/weather/release_serving.py:394-402`, `src/weather/model/toronto_model.py:80-121` |

### Current evidence identity

| Artifact | Generated UTC | SHA-256 | Current result |
| --- | --- | --- | --- |
| `data/backtest/production_readiness_gate.json` | `2026-07-12T16:31:04.394724+00:00` | `33146a8e5194e67642682229897dd959cd44de549c769734757a259cd0c781d1` | **OBSERVED:** `BLOCK`, `NOT_READY`, 71 blockers (`:2`, `:673-674`, `:1774`) |
| `data/backtest/fleet_observability.json` | `2026-07-12T16:31:04.235710+00:00` | `6c2bdba2d9a377e45cb3a96bca2a925bb1a48a63a976647268e285b237201d75` | **OBSERVED:** `CRITICAL`; four current-date runtime identities |
| `data/backtest/live_variant_settlement_scorecard.json` | `2026-07-12T16:29:16.089744+00:00` | `161ab9c710887c12a931c298d6fbe3ce757e6e67fee5fc305f836b2b850cd875` | **OBSERVED:** `BLOCK`; zero valid eligible partitions |
| `data/backtest/runtime_identity_reconciliation.json` | `2026-07-12T16:29:15.929728+00:00` | `ca35b28946b2d7bb72281ed06d6096f916853641484e42331a373a8bbd3637b0` | **OBSERVED:** target `2026-07-11`, 11 identities over 15,994 rows (`:22`, `:35-39`) |
| `data/backtest/event_day_archive_coverage_audit.json` | `2026-07-12T03:48:33.659099+00:00` | `453f494cf571e2f5c11b0c0ba502f800b26d807183b3fb990b9fb61381e0e90c` | **OBSERVED:** `BLOCK`; no fully linked archive evidence |
| `data/backtest/item321_point_in_time_materialization_pilot.json` | `2026-07-12T02:14:47.497832+00:00` | `ac8be481e2e9861c973a3d1404a2dda306a24549b23b92e80dfd0e91186c2516` | **OBSERVED:** 1,496 input rows, zero accepted, all `missing_release_id` (`:9-16`, `:30`, `:56`) |
| `data/backtest/point_in_time_validation_plan.json` | `2026-07-12T02:13:58.095954+00:00` | `db6be0cdcd94015881c9857ecf2c30cb52426efca78eb0b1185535d0930c2b5d` | **OBSERVED:** mechanism PASS; 36 dates, 19 outer folds, three-day embargo; no candidate run |

## Executive verdict

**OBSERVED — release decision:** the system is not ready for a production
release, paper canary, or live capital. It is not even release-bound shadow
evidence yet. The fresh parent gate is correctly `BLOCK/NOT_READY`, the active
release pointer is absent, runtime identity is mixed, the live scorecard has
zero valid eligible partitions, the PIT pilot has zero accepted rows, and
parity/streaming artifacts are missing. This is consistent with the prior audit
decision at `docs/roadmap/production-readiness-audit-2026-07-11.md:3-15`.

**OBSERVED — strongest data-layer property:** the live snapshot, source-status,
replay-input, and variant writers contain unusually rich source health,
timestamp, runtime, artifact, and hash fields. Captured replay inputs use a
canonical SHA-256 and include release-lineage slots
(`src/weather/collection/snapshot_store.py:2077-2145`). The new production gate
and live scorer fail closed on missing identity, partition coverage, and child
evidence.

**OBSERVED — weakest data-layer property:** capture implementation is ahead of
retention and lineage contracts. Raw observation sidecars and the large CLOB
capture-status tape are actively produced but are absent from event-day,
storage-class, and closed-archive registries. Exact forecast raw payload
retention is off by default. Only 48/429 eligible closed folders had structurally
valid event manifests in the archive audit, zero were fully linked, and there
was no backup or restore proof.

**OBSERVED — strongest logic-layer property:** physical and operational stages
are explicit and inspectable, probability normalization is centralized in
several critical paths, and safety/promotion boundaries are generally
fail-closed. The system has enough tracing to diagnose candidate routes and
source degradation.

**OBSERVED — weakest logic-layer property:** model selection and serving do not
yet share one independently validated computational graph. Preprocessing leaks
holdout statistics; multiple calibrators/postprocessors are tuned and reported
on the same rows; the trained exact calibration objective differs from the
served transform; a selected binary calibrator is bypassed; and live band
blending omits freshness/context rules used by replay.

**INFERRED:** published historical gains from the affected paths are optimistic
or semantically unrelated to served behavior. Their magnitude is unknown
because this audit intentionally did not retrain.

**RECOMMENDATION — shortest responsible path:** stop feature expansion. First
make the existing tape immutable and complete, unify replay/serve routing, run
one leakage-safe nested comparison of a simple forecast-residual baseline
against the frozen incumbent and two legitimate challengers, retire stages that
do not survive removal, then collect one release-bound 14-day forward shadow.

**OBSERVED:** the prior two-week artifact reinforces the need for simplification: across 141
promotion-countable market-days on 12 independent dates, model Brier/log loss
were `0.07191/0.24078` versus market `0.03734/0.11823`; every recent date,
market, and hour trailed the market
(`docs/roadmap/production-readiness-audit-2026-07-11.md:24-54`). The best
legitimate weather challenger, dynamic source state, reached Brier `0.07635`
but remained `+0.01681` behind market (`:56-70`). Market performance is a
separate benchmark lane, not a legal weather-only feature.

## Verified end-to-end lineage map

| Data family | Producer → stored evidence → derived consumer → evaluation/gate | Times and identity | PIT / lane / recoverability | Classification |
| --- | --- | --- | --- | --- |
| Weather snapshots and probability bands | Model build → `SnapshotStore` → `snapshots.jsonl`, `snapshots_long.csv`, features/components/forecasts/source-status (`src/weather/collection/snapshot_store.py:383-408,475-497,618-742`) → base distribution and live variants → settlement scorecard → production gate | Captured/build/local/UTC timestamps and model/runtime fields are present; current release fields are blank | Weather-only when market fields are excluded; exact live tape exists, but current rows are not release-bound | **OBSERVED** |
| Forecast raw/revision evidence | Source adapter `raw_payload` → SHA-1 metadata in `forecast_payloads_long.csv/jsonl`; optional JSON blob (`src/weather/collection/snapshot_store.py:1034-1095`) → normalized forecast rows/features → model | Captured/fetched plus some run/issue/update fields; no uniform first-available/response-received/parser version | Exact provider bytes are unrecoverable when not retained; replay strips raw blobs (`:1331-1339,2099`) | **OBSERVED** |
| Observation raw evidence | WU/METAR/ECCC/NWS source → JSON blob plus `observation_payloads_long.csv/jsonl` (`src/weather/collection/snapshot_store.py:1097-1158`) → current/high/floor features → model/replay | Captured/fetched/update/optional observed time; no parser/release/runtime fields in sidecar row; recent `provider_observed_at` is blank | Weather-only, live-only exact timing; older missing bytes generally cannot be reconstructed | **OBSERVED** |
| Source status | Every fetched source → `source_status_long.csv` / `source_status.jsonl` (`src/weather/collection/snapshot_store.py:396-397,475-485`) → freshness/degradation features and gates | Status, stale, fetched, age, TTL, cache/fallback/degradation fields | PIT-compatible when captured with the prediction; stale rows remain consumable by base model | **OBSERVED** |
| Replay inputs and parity rows | Exact merged model `sources`, raw removed → `replay_inputs.jsonl`, `captured_input_hash=SHA-256` (`src/weather/collection/snapshot_store.py:2092-2145`) → captured-input replay / variant parity → scorecard | Build/capture, runtime guard, release slots, model identity | Strongest PIT contract, but zero pilot rows qualify without release ID; current parity artifacts missing | **OBSERVED** |
| Live variant predictions/explanations | Registry + artifact + replay hash → predicted or explicit skipped rows in `variant_predictions*.jsonl/csv` and explanation tapes (`src/weather/collection/live_variant_predictions.py:130-245,883-966`) → live settlement scorer → gate | Variant/artifact/postprocess/runtime/release fields supported | Weather-only and market-informed lanes are distinguished; current eligible partitions are all invalid | **OBSERVED** |
| CLOB tokens/books/status | Gamma/CLOB APIs → token map, raw books, long/summary tables, `clob_capture_status.jsonl`; content-addressed price-history blobs (`src/weather/market/market_microstructure_capture.py:566-610,745-857,860-926,1022-1065`) → CLOB features/benchmark/trading | Capture/provider timestamps and hashes; status tape lacks release/config binding | Market benchmark, market-informed, or trading only; book tape exists, status retention contract does not | **OBSERVED** |
| Market-making/taker | Model/CLOB/preflight → `data/mm_runs` / `data/taker_runs` intents, orders, risk, fills and summaries (`src/weather/market/market_making_run.py:1467-1517,1631-1762`; `src/weather/market/taker_bot_cli.py:189-205,632-680`) → paper/executable gates | Runtime/config are recorded; release ID/manifest/pointer not consistently present | Trading lane only; no capital authority from these artifacts | **OBSERVED** |
| Settlement labels | WU daily/snapshot evidence + optional override + market reconciliation → market ledger and folder `settlement.json` (`src/weather/backtesting/settlement_ledger.py:823-983`) → every proper-score path | Local day, station, unit, rounding, source, quality, countability, finalization time | Label is usable only with revision provenance; current ledger upsert is mutable | **OBSERVED** |
| Event/archive/backup | Folder scan → `event_day_manifest.json` → closed-day Parquet family partitions/manifests → archive coverage → PIT/release candidate | Event hash, archive/cursor/backup/restore links are designed | Current rollout has zero fully linked eligible folders and zero backup/restore PASS | **OBSERVED** |

### Producer-to-contract reconciliation

| Writer family | Event-day registration | Storage class | Closed archive / Parquet | PIT / release manifest | Finding |
| --- | --- | --- | --- | --- | --- |
| Core snapshots/features/components/forecasts/source status | Present | Present | Present | Replay/corpus fields exist | **OBSERVED:** registered, but event manifests are not broadly deployed |
| Forecast payload metadata/raw | Present (`src/weather/operations/event_day_manifest.py:50-53`) | Present (`src/weather/operations/storage_classes.py:85-86`) | Metadata family present (`src/weather/operations/closed_market_day_archive.py:127-133`) | Raw bytes not required | **OBSERVED:** contract exists; raw capture is disabled in practice |
| Observation payload metadata/raw | Absent (`src/weather/operations/event_day_manifest.py:45-83`) | JSONL/raw absent (`src/weather/operations/storage_classes.py:74-106`) | Absent (`src/weather/operations/closed_market_day_archive.py:98-213`) | No first-class corpus/release binding | **OBSERVED:** produced-but-unregistered orphan |
| `clob_capture_status.jsonl` | Absent | Absent | Absent | No release binding | **OBSERVED:** produced-but-unregistered orphan |
| Order books / price history / WS | Present | Present for principal tapes | Present | Lane-specific | **OBSERVED:** registered; current cadence and completeness still block |
| Variant predictions | Present | Present | Present | Required by live scoring | **OBSERVED:** mechanism present; current partitions invalid |
| Settlement | Present | Classified | Not a first-class immutable revision stream | Required by evaluation | **OBSERVED:** current-state label exists; revision chain is mutable |

### Data-family detail register

| Family / rawness | Exact writer and files/schema | Event / issue / availability / ingestion / prediction times | Cadence and actual coverage | Identity, units, parser, hash, historical/live definition | Consumer, lane, PIT, retention | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| Snapshot bands — mixed raw build output and normalized projections | `SnapshotStore` paths at `src/weather/collection/snapshot_store.py:383-408`; `snapshots.jsonl`, `snapshots_long.csv`, `snapshots_wide.csv` | Captured UTC/local and model `built_at`; source-specific issue/availability remains inside source payload/status; prediction is build/capture time | Scheduled target is 10 minutes; bounded presence 453/453; current 12/12 liveness, but early-hour material coverage is 85/576 | Market/event/model/runtime fields; market-specific native units; canonical snapshot/replay hashes, but release blank. Parser versions are not uniformly row-bound | Base weather model, benchmark fields, replay, scorecards; weather-only only after lane filtering; canonical raw JSONL should be retained permanently | **OBSERVED** |
| Features/components/forecast projections — derived | Same writer; `features_long.csv/jsonl`, `components_long.csv/jsonl`, `forecasts_long.csv/jsonl` (`src/weather/collection/snapshot_store.py:390-395`) | Derived at prediction; provider issue/availability is not uniformly propagated to each feature row | Present through core snapshot rollout; folder-level feature presence is registered, value-level missingness varies materially | Feature schema/model version present; units depend on market; payload hashes in rows, not a universal parser/release binding | Model diagnostics/training/replay; weather-only unless market fields used; rebuildable only when raw inputs survive | **OBSERVED** |
| Forecast payloads — raw optional plus metadata | `write_forecast_payloads`, `forecast_payloads_long.csv/jsonl`, optional `forecast_payloads/<hash>.json`; `src/weather/collection/snapshot_store.py:1034-1095` | Captured/fetched, optional issue/update/valid; no uniform response-received/first-seen; prediction is snapshot time | Metadata 453/453 folders; July 11/12 zero raw links | Source and SHA-1; raw path; no hash-algorithm column/parser/release/config binding. Historical normalized forecast differs from live multi-source definition | Residual/features/PIT for normalized values; weather-only; exact parser replay unrecoverable when raw is absent | **OBSERVED** |
| Observation payloads — raw plus metadata | `write_observation_payloads`, raw JSON, `observation_payloads_long.csv/jsonl`; `src/weather/collection/snapshot_store.py:1097-1158` | Captured/fetched/update and optional provider observed; recent provider-observed field 0% populated; no explicit first-available | 231/453 all-history folders; 231/231 rollout-eligible folders across 12 markets, target dates `2026-06-23`–`2026-07-12`; 35,795 raw files at `13:43:42-04:00` | Source/station optional, native source units, SHA-1; no parser/runtime/release/config fields. Historical pre-rollout bytes unrecoverable | Current/high/floor features and forensic replay; weather-only; currently unregistered/unarchived | **OBSERVED** |
| Source-status — normalized provenance | `source_status_long.csv`, `source_status.jsonl`; writer call `src/weather/collection/snapshot_store.py:475-485` | Fetched/captured, cache age/TTL/status/fallback; provider issue time not universal | 453/453 folders; source-specific cadence follows snapshot loop; stale/failed historical rate 9.92% in July 10 audit | Source family, degradation/cache state and payload metadata; runtime release binding inherited imperfectly | Freshness features, outage diagnosis, gates; PIT-safe when captured contemporaneously; canonical evidence family registered | **OBSERVED** |
| Replay inputs — normalized exact model input | `replay_inputs.jsonl`; builder `src/weather/collection/snapshot_store.py:2092-2145` | Built/captured/prediction plus nested source times | 447/453 folders; current PIT accepted 0/1,496 | Model/runtime/release fields and canonical SHA-256; raw payload removed | Exact model replay, parity, variants; lane follows consumer; permanent canonical input, but current release-unbound | **OBSERVED** |
| Variant predictions/explanations — derived | `variant_predictions*.csv/jsonl`, `snapshot_explanations*.csv/jsonl`; `src/weather/collection/live_variant_predictions.py:130-245,883-966` | Prediction/capture time plus captured-input reference | 300/453 all-history and 300/300 rollout-eligible folders across 12 markets, target dates `2026-06-18`–`2026-07-12`; current scorecard zero valid eligible partitions | Variant, artifact, postprocess, runtime, release, skip reason, input hash; schema explicit | Weather-only/market-informed per registry; live scorecard and gate; registered/archive family | **OBSERVED** |
| CLOB token metadata — raw/normalized join keys | `clob_tokens.csv/jsonl`; store `src/weather/market/market_microstructure_capture.py:745-815` | Gamma fetch/capture; provider listing/update availability not uniformly first-seen | CLOB-enabled folders; exact fleet-wide token-row rate not recomputed in this audit | Condition/token/market IDs, prices, hashes where supplied; no release/config on ordinary rows | Books/history joins, benchmark/trading; market-only lane; registered and archived | **OBSERVED** |
| CLOB books — raw plus derived long/summary | `order_books.jsonl`, `order_books_long.csv[.gz]`, `order_books_summary.csv`; `src/weather/market/market_microstructure_capture.py:817-821` | Captured and provider book timestamp where present | 360/453 all-history and 360/372 rollout-eligible folders across 12 markets, target dates `2026-06-12`–`2026-07-12`; current fast path ~15s median, one ~160s fleet gap per market | Token/condition IDs, price/size, raw hashes/status; runtime/release/config not uniformly row-bound | CLOB features, market benchmark/informed/trading; registered, large retention target | **OBSERVED** |
| CLOB price history / public WS events — raw plus normalized | `price_history.csv/jsonl`, content-addressed `price_history_raw/<sha256>.json`, raw manifest; `market_ws.jsonl`, `market_ws_events.csv`; `src/weather/market/market_microstructure_capture.py:566-610,756-761,823-843` | Provider trade/point time plus capture for history/WS where supplied | Optional enrichment is currently disabled in the current loop; no current completeness claim | Token IDs, price/trade fields, SHA-256 raw blobs for history; runtime/release/config incomplete | Market benchmark/informed/trading only; archive contracts present | **OBSERVED** |
| CLOB capture status — raw provenance | `clob_capture_status.jsonl`; `src/weather/market/market_microstructure_capture.py:749,853-926` | Capture start/result plus raw/derived timestamp summaries | 288/453 all-history and 288/288 rollout-eligible folders across 12 markets, target dates `2026-06-19`–`2026-07-12`; 796,179,390 bytes at `13:43:42-04:00` | Counts, errors, raw hashes/paths; no first-class release/config storage contract | Collector health and completeness; market/trading evidence; currently unclassified and unarchived | **OBSERVED** |
| Settlement — derived truth plus source references | Market `ledger.jsonl`, folder `settlement.json`; `src/weather/backtesting/settlement_ledger.py:768-784,920-983` | Source observation/current file time, finalization; no immutable availability/supersession chain | 441 current labels in settlement audit; 324 proof-grade, 117 blocked, 7 revised | Market/station/timezone/unit/rounding/countability; hashes computed later; current-state rewrite | All evaluation lanes; PIT label use is after prediction but provenance must remain immutable | **OBSERVED** |
| Maker/taker intents, orders, fills — operational/trading | `data/mm_runs/**`, `data/taker_runs/**`; writers cited in lineage table | Decision/order/ack/fill/markout/run times by artifact | Current parent gate says trading evidence is not qualifying; this audit did not exhaustively enumerate runs | Runtime/config/risk IDs exist; immutable model release binding is incomplete | Trading lane only; paper/capital gates; no capital authority | **OBSERVED** |
| Runtime/config/artifact/release identity — provenance | Runtime identity in snapshot/variant/loop status; registry `config/model_variant_registry.json`; release loader `src/weather/release_serving.py` | Process start/load/build/capture; release activation time absent because pointer missing | Mixed current identities; 11 on July 11 reconciliation; four in current fleet artifact | Commit, source fingerprint, artifact hashes supported; no active immutable release | Every evidence lane and promotion gate; current state is research-unbound | **OBSERVED** |
| Event manifests / Parquet / backup / restore — retention metadata | `event_day_manifest.json`; family archive manifests/Parquet; audit code under `src/weather/operations/` | Manifest/archive/backup/restore generation times, not source event time | 48/429 structurally valid event manifests; 248/429 structurally valid archive manifests declaring PASS; zero full links/backups/restores | File SHA-256, family/schema/cursor links designed; core families optional and orphans omitted; Parquet/content not revalidated here | PIT corpus/release/promotion recoverability; current evidence not release-grade | **OBSERVED** |

## Current coverage and freshness

The folder-presence inventory below was a filename-only bounded scan at
`2026-07-12T13:21:12.0696776-04:00`. It did not parse the large tapes.

| Family/evidence | Expected scope | Actual current evidence | Freshness/quality | Classification |
| --- | --- | --- | --- | --- |
| Market-day folders | Repository snapshot root | 453 folders | Live July 12 folders were changing | **OBSERVED** |
| Snapshot JSONL | 453 folders | 453/453 | Current fleet liveness 12/12; current identity mixed | **OBSERVED** |
| Source-status JSONL | 453 folders | 453/453 | Current free sources were not fleet-blocking; historical audit measured 71,466/720,552 stale/failed rows (9.92%) | **OBSERVED**, `data/backtest/data_layer_audit.json`, generated `2026-07-10T03:08:08.972120Z`, SHA-256 `061f36b6207c31dd5db3e742ec3acb0c5df72f2088ec9973fa3b9f645bb3f54b` |
| Forecast-payload metadata | 453 folders | 453/453 | July 11: 12,952 rows, zero raw paths; July 12 at `13:21`: 3,402 rows, zero raw paths | **OBSERVED** |
| Observation payload sidecars | Per-market rollout begins `2026-06-23/24` | 231/453 all-history; 231/231 rollout-eligible across 12 markets | July 11: 1,586 metadata rows; July 12 at `13:21`: 426; `provider_observed_at` populated in 0 rows | **OBSERVED** |
| Replay inputs | Every suitable snapshot folder | 447/453 folders | PIT pilot accepts none because release ID is missing | **OBSERVED** |
| Variant tape | Per-market rollout begins `2026-06-18` | 300/453 all-history; 300/300 rollout-eligible across 12 markets | Scorecard: zero valid of 80,057 eligible partitions; 13,332 unsupported-runtime skipped bands | **OBSERVED**, `data/backtest/live_variant_settlement_scorecard.md:8-23,122-167` |
| Raw books | Per-market rollout begins `2026-06-12` | 360/453 all-history; 360/372 rollout-eligible (96.77%) across 12 markets | Current ~15-second median cadence, but each of 12 markets had one ~160.5–160.9 second gap | **OBSERVED**, `data/backtest/fleet_observability_report.md:110-140` |
| Event-day manifests | 429 eligible closed folders | 48/429 structurally valid (11.19%); 381 missing | Target dates June 6–9; manifests generated July 12 UTC; embedded validation is WARN because backup/restore are not configured | **OBSERVED**, `data/backtest/event_day_archive_coverage_audit.json:13218-13245` |
| Declared archive manifests | 429 eligible closed folders | 248/429 structurally valid manifests declaring `validation_status=PASS` (57.81%) | 0/429 fully linked; cursor invalid; Parquet/content hashes not independently revalidated here | **OBSERVED** |
| Backup / restore | 48-manifest protection denominator | 0/48 backup PASS; 0/48 restore PASS | No release-grade recoverability proof; 381/429 eligible folders have no event manifest | **OBSERVED** |
| Storage headroom | ≥30 days | 6.7578 days | `BLOCK` | **OBSERVED**, `data/backtest/data_retention_headroom_probe.json:7-8,18-22,33,61` |
| Settlement freshness | 12 markets for July 11 | 12 complete, 11 promotion-countable, one blocked | All label grades partial | **OBSERVED**, `data/backtest/settled_day_freshness.json`, generated `2026-07-12T16:29:07.093747Z` |
| Clean-day ledger | ≥3 clean release-bound days for early gate | zero entries | `BLOCK` | **OBSERVED**, SHA-256 `96df9652b7efd034819526b88bf6b252af6aa9c1a80612fd987a9f01d9b73c56` |
| Unattended-cycle ledger | seven complete cycles | zero entries | `BLOCK` | **OBSERVED**, SHA-256 `54628ee747f975ef3a7e7da8611e977ec4de85eb1e7df5f24d2c567bfa77b46a` |
| Early-hour snapshot evidence | 576 minimum in current fleet artifact | 85 present; 491 missing; max gap 301 minutes | All 12 markets blocked | **OBSERVED**, `data/backtest/fleet_observability_report.md:235-261` |

**OBSERVED:** the current Parquet incremental batch reports a local PASS (25
scanned, 15 converted, five blocked, backlog 253), but that does not prove full
archive coverage or linkage (`data/backtest/fleet_observability_report.md:354-368`).

**OBSERVED:** no single current, release-bound artifact reports missing, stale,
failed, duplicate, and impossible-value rates for every family over the same
market/date window. The July 10 data-layer audit supplies broad historical
checks, and CLOB status rows carry duplicate/correction counts, but combining
them with July 12 live counts would mix identities and generation times.
Accordingly, this report gives exact rates only where the bound evidence permits
them: forecast raw-link missingness `100%` on July 11/12, observation
`provider_observed_at` missingness `100%` on those rows, historical source
stale/failed `9.92%`, current valid live-partition coverage `0%`, event-manifest
coverage `11.19%`, archive-manifest coverage `57.81%`, and full archive/
backup/restore coverage `0%`. A singular-release data-quality cube remains a
required output of the DO NOW work.

**OBSERVED:** the retention inventory can say PASS based on free space even when
classification integrity is poor: its `2026-07-10` artifact reported
58,998,421,150 unclassified bytes, 37,372 unclassified files, and zero event
manifests; status logic uses disk/headroom at
`src/weather/reporting/data_quality/data_retention_inventory.py:859-881`.

## High-impact findings

### F01 — Two active capture families are outside all retention contracts

**OBSERVED:** observation sidecars are created and written as raw JSON,
CSV, and JSONL at
`src/weather/collection/snapshot_store.py:401-403,492-497,1097-1158`. The event
family tuple (`src/weather/operations/event_day_manifest.py:45-83`),
canonical-evidence patterns (`src/weather/operations/storage_classes.py:74-106`),
and closed archive families
(`src/weather/operations/closed_market_day_archive.py:98-213`) contain no
observation-payload family.
Direct classification leaves the JSONL/raw files unclassified; the long CSV is
only caught by a generic projection class.

**OBSERVED:** `clob_capture_status.jsonl` is created at
`src/weather/market/market_microstructure_capture.py:745-755`, appended at
`:853-854`, and contains
capture success/failure, raw/derived timestamps, counts, duplicate/correction
counts, hashes, and paths at `:860-926`; it is absent from the same three
registries. A bounded scan at `2026-07-12T13:43:42.5113491-04:00` found 288
folders and 796,179,390 bytes of this tape. The observation raw tree contained
35,795 JSON files / 392,770,145 bytes at that same scan time.

**INFERRED:** ordinary archive and retention operations can omit evidence that
is necessary to prove what the model or CLOB collector saw, despite the writer
succeeding.

**RECOMMENDATION:** register both as canonical families before any new source
work. Raw JSON/JSONL should be permanent source evidence; CSV/Parquet should be
rebuildable projections. Require event-manifest hash, storage class, archive
partition, backup coverage, restore proof, runtime/release/config identity, and
zero unclassified bytes for both families.

### F02 — Exact forecast provider evidence is not retained

**OBSERVED:** for source items exposing a non-null `raw_payload`,
`write_forecast_payloads` emits metadata and SHA-1 but writes raw JSON only when
`retain_raw_forecast_payloads` is true
(`src/weather/collection/snapshot_store.py:1034-1062`). Environment default is
false (`:1326-1329`).
All 12 July 11 and July 12 folders had blank `raw_payload_path`; no recent row
linked to provider bytes. Replay removes `raw_payload` (`:1331-1339,2099`).

**INFERRED:** the normalized captured input is sufficient to rerun current
model logic, but it cannot reproduce parser behavior, provider member/run
contents, first-seen revisions, or a future parser correction. A stored hash of
discarded bytes is not recoverability.

**RECOMMENDATION:** use content-addressed, change-only SHA-256 raw retention,
analogous to price-history blobs at
`src/weather/market/market_microstructure_capture.py:566-610`. Store request
start, response
received, first seen, provider issue/run/update/valid time, source/model/member,
URL sans secrets, bytes, parser/schema version, runtime/release/config hashes,
and payload hash. Acceptance: ≥99% of healthy manifest rows link to a verified
blob and the daily deduplicated storage budget is below a predeclared cap.

### F03 — Event/archive manifests can pass without core evidence

**OBSERVED:** `EventDayArtifactFamily.required` defaults false and no family in
the declared tuple overrides it
(`src/weather/operations/event_day_manifest.py:37-83`). Required-family
checks therefore pass if all core tapes are absent (`:843-845,1075-1089`).
Runtime checks block only mixed identity; missing identity passes
(`:837-840,1084-1089`). Closed archive planning blocks a present non-PASS
manifest but does not block an absent manifest
(`src/weather/operations/closed_market_day_archive.py:934-936`).

**INFERRED:** current rollout has an inversion: adding a truthful WARN manifest
can block conversion, while leaving the manifest absent permits it.

**RECOMMENDATION:** for closed promotion-countable days, require snapshot,
source-status, replay-input, settlement, observation/CLOB status where enabled,
and singular runtime/release identity. Missing event manifest must block archive
conversion. Rebuild and link archive manifests only after the event manifest is
valid.

### F04 — Labels are current-state records, not immutable truth histories

**OBSERVED:** settlement `upsert_ledger_record` removes the existing event row
and rewrites the JSONL (`src/weather/backtesting/settlement_ledger.py:768-784`).
The label records station/timezone/unit/rounding/countability and finalization
(`:920-983`) but not an append-only old/new revision chain. The settlement audit
hashes current files (`src/weather/reporting/source_gates/settlement_source_audit.py:125-188`)
and treats a missing raw weather/market payload as lineage PASS when a missing
reason string exists (`:189-197`).

**OBSERVED:** the bound settlement audit is `BLOCK`: 441 labels, 324 proof-grade,
117 promotion-blocked, seven revised, and 882 missing-with-reason lineage
entries; SHA-256
`cde13ecea3997c72333a5b4869168cd3da28df147a79039ad07cf7fc5047ca58`.

**RECOMMENDATION:** append immutable settlement revision events with observed,
available, ingested, finalized, and superseded times; old/new value; raw
resolution/source hashes; and operator/reason/approval for overrides. A missing
raw resolution payload may be explicitly tolerated for research but must not be
called proof-grade lineage.

### F05 — Feature-model preprocessing leaks validation statistics

**OBSERVED:** the primary feature trainer fits `SimpleImputer` and
`StandardScaler` on all hour rows at
`src/weather/calibration/feature_model.py:1056-1068`, constructs the blocked
plan afterward at `:1088-1093`, then slices the globally transformed matrices
for train/validation at `:1183-1188`. HGB receives the globally imputed matrix
with only selected native-NaN columns restored (`:1070-1083`). A fold-local
helper exists at `:485-499` but this path does not call it.

**INFERRED:** the direction and size of metric inflation are unknown, but the
reported validation is not strictly out of sample and is not promotion-grade.

**RECOMMENDATION:** revoke the affected feature-model report as promotion
evidence. Refit every transform inside each inner/outer training fold and emit
stage receipts binding transform fit dates, row hashes, and output hashes.

### F06 — Selection and evaluation reuse the same rows at several layers

**OBSERVED:** feature-model HGB temperature and climatology blend weight are
selected on `hgb_fold_data` and immediately scored on the same predictions
(`src/weather/calibration/feature_model.py:1285-1311`).

**OBSERVED:** pooled band training tunes temperature on evaluation rows
(`src/weather/calibration/pooled_training.py:536-565`), then fits adjacent,
exact-winner, and market-bias postprocessors on those same rows and overwrites
the evaluation score (`:612-703`). It refits the final model on all rows,
including that holdout, while retaining the selected temperature/postprocessing
(`:579-596`). Density sigma/shape and density
postprocessing similarly reuse the single holdout (`:215-253,322-326`). The CLI
default is one `--holdout-year 2025`, not nested rolling origin
(`src/weather/calibration/pooled_feature_cli.py:122`).

**OBSERVED:** `blocked_validation_audit` summarizes partitions and always
returns `ok=True`, `leak_count=0`, `leaks=[]`
(`src/weather/calibration/blocked_validation.py:226-368`); it does not attest to
which rows the model, transform, or calibrator actually used.

**RECOMMENDATION:** rename that artifact “partition feasibility audit” unless
execution receipts are verified. All model, feature, weight, calibrator,
postprocessor, and router selection must occur on inner folds; outer folds are
estimation only.

### F07 — Calibration training, reporting, and serving have incompatible semantics

**OBSERVED:** exact temperature training treats each band independently as
`sigmoid(logit(p)/T)` (`src/weather/calibration/probability_calibration.py:656-713`).
Serving applies joint multiclass power scaling `p^(1/T)` and renormalizes the
simplex (`src/weather/model/calibration_runtime.py:351-412`), called at
`src/weather/model/model_distribution.py:508-520`. The artifact replay scorer
calls only the binary market calibrator and never scores the served exact
transform (`src/weather/calibration/probability_calibration.py:716-730`).

**OBSERVED:** all 13 inspected mutable probability-calibration JSON artifacts
set `market_bin.preserve_distribution_coherence=true`; runtime returns the raw
probability before the selected prior/Platt/isotonic branch
(`src/weather/model/calibration_runtime.py:504-526`). Thus the reported selected binary arm is
dead for ordinary served probabilities, while hard-bin overrides remain
reachable.

**OBSERVED:** the inspected pooled-F artifact advertises 96,041 rows but only
six target dates and carries the coherence flag
(`artifacts/calibration/probability_calibration_f_family.json:1994-2008,2036,2102-2109`).
Its SHA-256 is
`3045d99aca7b953441123dc34de7e894db1590ecec3e504137f769a0ac99c718`.
Artifact reporting calls the binary replay scorer and omits the served exact
transform (`src/weather/calibration/probability_calibration.py:733-774`).
Correlated snapshot/band rows are not independent evidence.

**RECOMMENDATION:** retire the bypassed selector or mark it diagnostic-only.
Refit the literal served simplex transform on inner-fold OOF distributions and
score the literal post-stage served vector on untouched fleet dates.

### F08 — Registry-active/reachable pooled variants differ between replay and live scoring

**OBSERVED:** replay resolves current blend as market/default alpha, then a
source-freshness minimum cap, then every matching context rule with last-match
overwrite (`src/weather/calibration/pooled_candidate_replay.py:1051-1073`), and
applies it at `:1115-1128`. Live scoring uses only market/default alpha
(`src/weather/collection/live_variant_predictions.py:586-608,678-683`).

**OBSERVED:** base artifact configuration has default alpha `1`, market
overrides Dallas/Miami/San Francisco `0`, Denver/Houston/Los Angeles/NYC/Seattle
`.2`, and warm-pressure/two-degrees-above-floor/weak-current-max context rules
`.35/.35/.50` (`src/weather/calibration/pooled_training.py:95-126`). The optional
source-freshness guardrail separately adds default `0` and `all_fresh=1` at
`:141-153` and is applied only when requested at `:505-506`. For artifacts that
carry it, last-match context overwrite can raise a fail-closed `0` to `.35` or
`.50` in replay; live ignores the optional freshness cap and every context
rule. The dynamic-source and Miami fallback artifacts are registry-reachable
(`config/model_variant_registry.json:51-65,84-98`), but no active release
pointer proves execution. Their inspected SHA-256 values are respectively
`ee7b65d078961bf21c3f89ff6e359d0acca5f3fedc90e456bf0192e4656867e9`
and `3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c`.

**OBSERVED:** the current blend validator matches context keys by string
equality and does not implement replay's `_min/_max` semantics
(`src/weather/reporting/validation/current_blend_validation.py:114-122`); its
input context omits `forecast_bucket_pressure`,
`band_mid_minus_high_so_far`, and `current_max_disposition`, making all three
base context rules unavailable (`:171-179`; rules at
`src/weather/calibration/pooled_training.py:107-126`).
`data/backtest/live_variant_replay_parity.json` is missing.

**RECOMMENDATION:** classify all affected variant evidence as non-countable.
Use one shared pure blend resolver in training/replay/live; safety constraints
must be monotonic minima or have explicit priority. Require exhaustive branch
truth-table and captured-input end-to-end parity before shadow countability.

### F09 — Historical and live forecast feature definitions differ

**OBSERVED:** historical records receive one forecast index at
`src/weather/calibration/feature_model.py:635-668`. Historical feature assembly defaults
`forecast_source_count=1`, disagreement `0`, robust/trimmed high to the same
single forecast (`src/weather/model/feature_store.py:1384-1400`). Live serving
uses a median/trimmed ensemble of up to six providers and computes real
source-count/disagreement/outlier fields
(`src/weather/model/model_features.py:322-425`).

**INFERRED:** the live model receives covariates and a forecast definition that
the historical estimator did not learn under the same distribution. Comments
and small replay comparisons are not a canonical train/serve parity proof.

**RECOMMENDATION:** either reconstruct point-in-time multi-source historical
features with first-available times or serve the exact single-source definition
used in training until a new artifact qualifies.

### F10 — Missingness is silently converted into neutral meteorology

**OBSERVED:** missing two-hour temperature becomes current temperature,
producing warming `0` (`src/weather/model/model_features.py:831-844`); missing peak time becomes
hours-at-peak `0` (`:846-855`); missing wind shift becomes `0` (`:1069`); a
missing late-day first-high time is fabricated as now minus 30 minutes
(`:1474-1490`). Historical feature assembly also maps missing rise, warming,
peak duration, pressure trend, wind shift, and disagreement to zero
(`src/weather/model/feature_store.py:1253-1300,1382-1400`).

**INFERRED:** outages and sparse capture can be interpreted as stable physical
conditions, causing confident predictions exactly when uncertainty should
increase.

**RECOMMENDATION:** preserve missingness, add availability indicators, use
fold-local imputation, and require explicit uncertainty widening or abstention
for critical missing context.

### F11 — Model/artifact failures silently switch model family

**OBSERVED:** feature evaluation falls HGB → LR → empirical on missing artifact
or exceptions (`src/weather/model/model_features.py:1110-1225`) and the distribution continues to
emit a prediction. Unknown market IDs silently resolve to Toronto
(`src/weather/market/market_registry.py:396-397`); replay also defaults unknown
slugs to the default market. A missing/invalid cutoff first uses the parsed
captured local hour and becomes hour `12` only if captured time also cannot be
parsed (`src/weather/backtesting/replay.py:341-362`).

**INFERRED:** artifact corruption, identity mistakes, or schema mismatches can
yield plausible but differently defined probabilities without a distinct
release/route identity.

**RECOMMENDATION:** permit these fallbacks only as separately named research
variants. Release-bound serving should fail closed or explicitly abstain on an
unregistered market/unit/event/date/cutoff or an unexpected model-family switch.

### F12 — Stale data remains model-valid and live routing ignores its guardrail

**OBSERVED:** cache TTLs are 20 minutes for MRMS, 30 for WU/SWOB, 75 for
METAR/marine, and 90–120 for forecast families
(`src/weather/model/model_constants.py:27-55`). On fetch failure a recent cache
returns `ok=True, stale=True` (`src/weather/model/model_sources.py:606-725`).
The base consumer accepts `ok` data with a target-date match without checking
`stale` (`src/weather/model/model_base.py:170-177`). For registry variants whose
artifacts carry the optional source-freshness guardrail, the live pooled blend
omits the replay freshness cap.

**RECOMMENDATION:** retain source-specific TTLs as operational hypotheses, not
truth. Exercise exact boundary, correlated outage, and age-jitter simulations;
make model permission/uncertainty depend on the captured freshness state.

### F13 — Several reachable corrections have tautological or pseudoreplicated evidence

**OBSERVED:** afternoon contexts are fitted and validated on the identical rows
(`src/weather/calibration/afternoon_residual_centering.py:197-286`). The current
inspected mutable artifact uses 5,747 rows / 213 folders, hours 15–18, minimum
context `4`, maximum shift `2`, and reports near-zero after-bias
(`artifacts/misc/afternoon_residual_centering.json:745,748,764,983-1044`).
**INFERRED:** the near-zero after-bias is tautological because fit and validation
reuse the same rows.

**OBSERVED:** settlement-lag summaries count snapshot rows and use minimum
`n=20`, although one market-day can contribute many correlated snapshots
(`src/weather/calibration/settlement_lag_model.py:190-355`). Pooled training
expands one source row into many synthetic bands and applies winner/distance/late
weights (`src/weather/calibration/pooled_feature_assembly.py:1145-1208`).

**INFERRED:** raw row counts materially overstate independent sample size and
can make context-specific corrections look mature.

**RECOMMENDATION:** re-estimate by fleet date/market-day/cutoff, cluster
uncertainty by fleet date, publish effective sample size, and require a minimum
number of independent dates rather than snapshots.

### F14 — Serving is a long noncommutative hand-tuned stack

**OBSERVED:** `src/weather/model/model_distribution.py:253-530` applies prior/support, feature or
empirical model, transition prior, live signals, hard floor, intraday tail,
plausibility cap, forecast shape, ramp damping, afternoon centering, current and
observed floors, continuation, multiple lock-ins, normalization, exact
calibration, then an overlock guard. The final guard can change probabilities
after the fitted calibration.

**OBSERVED:** the central constants file contains dozens of forecast floors,
pulls, caps, damping, hedge, sigma, timing, lock-in, and market allowlist values
(`src/weather/model/model_distribution_constants.py:9-172`; SHA-256
`546a6524…9e8`). Comments cite isolated June replays and a Toronto A/B, not
nested fleet-wide independent evidence for most interactions.

**INFERRED:** stage ordering and parameter interactions are large enough that
one-at-a-time local rationales do not establish global out-of-time value.

**RECOMMENDATION:** freeze physical/settlement invariants, then run remove-one,
cumulative-removal, and selected order tests inside the nested protocol. Fit one
final coherent calibrator after all retained deterministic stages.

### F15 — PIT and release contracts exist but are mechanism-only

**OBSERVED:** the documented canonical key, evidence lanes, materializer, folds,
and locked evaluation are specified in
`docs/operations/POINT_IN_TIME_EVALUATION.md:7-102`. The diagnostic plan has 36
dates, 19 outer folds, and a three-day embargo, but no candidate/release/corpus
binding or fit receipts. `run_training_only_pipeline` has no production caller
outside tests. The PIT pilot accepts zero rows. The streaming evaluation and
live replay-parity artifacts are missing.

**OBSERVED:** fit-receipt verification validates declared dates/counts/hash
syntax but does not recompute receipt inputs from the corpus or bind every
receipt to its fitted stage output (`src/weather/point_in_time_contract.py:299-337`).
Window-lock code proves creation before scoring, not before human candidate
selection (`src/weather/reporting/validation/point_in_time_evaluation.py:1938-2020,2098-2143`).

**RECOMMENDATION:** add append-only pre-selection lock registration and
corpus-recomputed, stage-output-bound receipts. A plan PASS must never be
presented as model-performance evidence.

### F16 — Production gates are strong but do not rescue invalid upstream estimates

**OBSERVED:** the parent gate validates freshness, hashes, identity, and child
status and fails closed
(`src/weather/reporting/serving_gates/production_readiness_gate.py:1283-1432,1465-1658,2233-2317`).
The live scorer checks explicit release ID, complete simplex partitions,
coverage, equal market-day weighting, and date-clustered intervals
(`src/weather/reporting/scorecards/live_variant_settlement_scorecard.py:586-719,1237-1414`).

**OBSERVED:** 178 focused tests plus 26 subtests passed during this audit, yet F01,
F05, F07, and F08 remain because no current cross-contract or literal
serve-transform evidence exists.

**RECOMMENDATION:** preserve the gate architecture. Add computational-graph
receipts, writer-registry reconciliation, and end-to-end branch parity rather
than weakening current blockers.

### F17 — Current evidence proves no edge and no capital authority

**OBSERVED:** the fresh gate is `NOT_READY`; `capital_authority=false`
(`data/backtest/production_readiness_gate.md:125-130`). Clean/unattended ledgers
have zero entries, forward challenger/paper/capital evidence is absent or
blocked, and current live partitions are non-countable. Historical recent
weather variants still trail the market benchmark in their separate lane.

**RECOMMENDATION:** keep collection and bounded diagnostics running, but do not
promote, paper-canary, or authorize capital from this audit. The first decision
to unlock is countable shadow evidence for one immutable release—not an order
adapter.

## Ranked missing-capture and repair opportunity matrix

The ranking uses the requested principle:

`expected uncertainty reduction × disagreement × regime novelty × economic exposure ÷ acquisition/operational cost`.

Scores are ordinal audit priorities, not measured information values.

| Rank | Opportunity and precise hypothesis | Required fields / PIT availability | Backfill and incremental information | Failure/leakage/cost | Ablation and decision rule | Classification |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | **Register/archive observation sidecars and CLOB capture status.** Hypothesis: preserving evidence already written closes replay, outage, and archive-integrity uncertainty without acquiring a new correlated signal. Consumers: lineage, PIT, parity, CLOB health. | Existing payload/status plus `captured_at`, provider observed/book time, fetched/request/response time, first seen, station/token, source, parser/schema, units, SHA-256, runtime/release/config. Availability is live first-seen. | No reliable backfill for missing raw observation timing; existing files can be classified/manifests rebuilt. Information is provenance, not predictive lift. | Low API cost; moderate manifest/archive I/O. Risk is accidental classification as a feature lane. | Acceptance is operational: zero unclassified bytes for these families, 100% post-enable folder registration, verified hash links, backup coverage, and a successful restore/replay. | **RECOMMENDATION — DO NOW** |
| 2 | **Content-addressed forecast run/member/revision payloads.** Hypothesis: first-seen revision trajectories explain forecast disagreement and improve residual uncertainty/outage handling beyond a median high. Consumer: weather-only residual/density model and leakage audit. | Request start, response received, first seen, provider issue/run/update/valid time, model/member/grid/station, availability, parser, units, source URL, SHA-256, bytes, runtime/release/config. Enforce `first_available_at <= prediction_made_at`. | Exact historical first-seen availability is mostly live-only; provider archives may backfill values but not local availability. Incremental content is revisions/member shape, not another correlated point high. | Potentially high storage/API; use hash dedup and save-on-change. Leakage if issue/availability is reconstructed from future metadata. | Nested leave-family-out/add-family test on whole dates. Promote only if outer Brier and log loss both improve or outage robustness improves materially with no protected-metric regression. | **HYPOTHESIS / RECOMMENDATION — DO NOW capture, later model use** |
| 3 | **Append-only settlement and market-resolution revisions.** Hypothesis: immutable revision history prevents retrospective target drift and quantifies boundary/rounding sensitivity. Consumer: every evaluation lane. | Source observed/available/ingested/finalized/superseded times; old/new high/bucket; station/timezone/unit/rounding; raw WU/Gamma hash; override operator/reason/approval. | Current final values can be retained; historical revision timing is generally unrecoverable. Incremental information is label uncertainty/provenance. | Low volume and cost; severe leakage risk if revised final values enter feature tapes. | Acceptance: every countable label resolves to one append-only chain and raw hashes; Monte Carlo decision stability ≥95% under valid revisions/rounding. | **RECOMMENDATION — DO NOW** |
| 4 | **Make existing NBM probabilistic Tmax fields reliable.** Hypothesis: NBM quantile/threshold shape adds calibrated US-market uncertainty beyond the multi-source median. | Run/issue/valid/first-seen, grid/station, p10/p50/p90 and thresholds, units, raw hash, parser version, missing reason. | Archive backfill may recover runs but not local first-seen time; live proof required. Existing `item190` artifact covered only three dates/33 folders (generated `2026-06-25`, SHA `cd790252…b35af`). | Existing API/source path; moderate storage. Correlation with NWS/global guidance; missing-feature defaults risk. | Whole-date nested add-one/leave-one family ablation on US markets; require both primary metrics better and no market Brier regression >0.01. | **HYPOTHESIS — COLLECT FORWARD EVIDENCE** |
| 5 | **Complete existing marine/MRMS/forecast-profile availability before adding new feeds.** Hypothesis: these sources help only in coastal, convective, or ramp regimes, not globally. | Source-specific observation/valid/first-seen times, station/grid, measured value, QC, units, raw hash, missing reason, regime label fixed before outcome. | Partial archives exist; exact live missingness needs forward collection. Incremental value is conditional regime context. | Moderate operational complexity; high multiple-testing risk in tiny slices. | Predeclare regime episodes; require ≥7 independent dates per reported slice and nested interaction gain. Existing small-date ablations with zero/neutral deltas are not promotion evidence. | **HYPOTHESIS — DEFER model use; repair capture after ranks 1–4** |
| 6 | **Nearby-station spatial gradients and station-health change events.** Hypothesis: spatial gradients improve resilience and microclimate timing when the settlement station is delayed/degraded. | Station ID/lat/lon/elevation, observed/available/ingested time, QC/correction flag, station-health state, temperature/dew/wind, distance/bearing, units, raw hash. | Historical observations may backfill values; first-seen health state is live-only. Adds spatial structure beyond same-station and NWP. | Moderate API/storage; leakage if end-of-day QC/correction is treated as contemporaneous. | Leave-station-family-out and correlated primary/nearby outage simulation; promote only on degraded-source slices plus aggregate noninferiority. | **HYPOTHESIS — DEFER** |
| 7 | **Pressure-level/boundary-layer, solar/cloud, smoke/AQ regime state.** Hypothesis: these improve rare heat/ramp regimes after point-in-time manifests exist. | Provider run/issue/valid/available times, level/variable/grid, ensemble/member where relevant, units/QC, raw hash, parser. | Reanalysis is backfillable but not automatically PIT-safe; operational forecasts require first-seen archive. Incremental novelty must be shown versus existing NWP/profile/AQ fields. | High dimensionality and correlated-source risk; moderate/high I/O and training cost. | Grouped add-one-family tests with random-noise control and rare-regime pre-registration. No promotion from row-level permutation importance. | **HYPOTHESIS — DEFER** |
| 8 | **Additional exotic providers or broader ensembles.** Hypothesis unspecified until ranks 1–7 leave a measured uncertainty gap. | Must meet the same five-time provenance and raw-hash contract. | Unknown. | Highest cost and operational surface. | Do not acquire until a decision analysis identifies the exact unresolved error slice and a predeclared promotion threshold. | **RECOMMENDATION — DEFER** |

**OBSERVED:** source support already exists for NBM, MRMS, marine, AQ/smoke,
global ensembles, and expanded Open-Meteo families. The first data problem is
therefore reliable population and immutable retention, not a lack of adapters.

## Assumption and parameter register

The register covers consequential serving, training, calibration, routing,
identity, missingness, freshness, and readiness values encountered in the
active/reachable model graph. It groups related constants where they form one
policy. “Independent N” is the evidence encoded or identifiable in the
repository; `not encoded` means comments may cite an anecdote or report but the
artifact does not bind a fleet-date sample.

| ID | Current value and exact implementation | Type / scope | Justification and independent evidence | Selection reuse / consistency / interaction | Disposition | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| A01 | Forecast floor: margin `2°C`, agreement `5°C`, minimum sources `2`, base `.5`; `src/weather/model/model_distribution_constants.py:9-16`; conversion at `src/weather/model/model_distribution_signals.py:999-1009` | Heuristic; uncalibrated-empirical route for `{houston, los-angeles, miami, nyc, seattle, toronto}` | Comments cite same-day miss intuition and a `2026-06-09` replay; independent N not encoded. The inline HGB rationale conflicts with runtime, which skips this stage for HGB (`src/weather/model/model_distribution.py:79-88,1007-1048`) | Serving-only route subset; interacts with falsification, pull, floors, cap | Re-estimate inside nested stage ablation; retain only if removal fails noninferiority | **OBSERVED / RECOMMENDATION** |
| A02 | Falsification: earliest hour `13`, high stood `90m`, margin `1°C`; `src/weather/model/model_distribution_constants.py:29-31`; conversion/use at `src/weather/model/model_distribution_signals.py:1041-1075` | Heuristic; same uncalibrated-empirical market allowlist | One June bust-day narrative; N not encoded | Serving-only; does not alter trained forecast feature; interacts with floor/pull | Learn/shrink or simplify with monotonic rule; stress clock/cadence | **OBSERVED / RECOMMENDATION** |
| A03 | Forecast pull: sigma `1.5°C`, blend max `.75`, hours `12–16`; `src/weather/model/model_distribution_constants.py:48-60`; conversion/use at `src/weather/model/model_distribution_signals.py:999-1009,1041-1075` | Empirical heuristic; same uncalibrated-empirical market allowlist/time | Comment cites Open-Meteo RMSE `1.68` and a frozen 15-day Toronto A/B; the HGB rationale conflicts with runtime skip | Serving-only route subset; noncommutative with cap, ramp, centering, calibration | Re-estimate on allowed markets and outer dates; no transfer without evidence | **OBSERVED / RECOMMENDATION** |
| A04 | Forecast cluster weight step/cap `1.4/2.4`; `src/weather/model/model_distribution_constants.py:62-70` | Correlation-control heuristic | Conceptual correlated-family rationale; N not encoded; fallback-only comment conflicts with runtime | Used on feature path (`src/weather/model/model_distribution.py:1297-1328`) and uncalibrated empirical fallback (`:1339-1360`), omitted by calibrated empirical route (`:1329-1338`) | Replace with one explicit family aggregate or learned shrinkage; first reconcile route semantics | **OBSERVED / RECOMMENDATION** |
| A05 | Ramp warm-tail hours `8–14`, disagreement `4`, margins `1`, decay `.45`; `src/weather/model/model_distribution_constants.py:72-84` | Market/regime heuristic | One `2026-06-20` settled audit; N not encoded | Serving after forecast shape; interacts with centering and lock-in | Disable unless nested removal shows repeatable protected-slice value | **OBSERVED / RECOMMENDATION** |
| A06 | Bucket transition minimum `n=20`, blend max `.12`; `src/weather/model/model_distribution_constants.py:86-93` | Empirical prior | Richer model overlap acknowledged; N counts may be correlated | Serving correction before later floors/calibration | Recompute by independent market-day; learn shrinkage or retire | **OBSERVED / RECOMMENDATION** |
| A07 | Live floor hedge `.4`, base `.12`, clamp `.3–.8`; METAR baseline `.5`, max weight `.6`, sigma `.9`; WU residual `.001`; `src/weather/model/model_distribution_constants.py:95-112` | Safety/settlement heuristic | Comments cite Toronto ablations and lag artifact; independent cross-market N not bound | Interacts with current max, continuation, lock-in, final calibration | Keep hard settlement invariant only where source is legally authoritative; re-estimate soft floors | **OBSERVED / RECOMMENDATION** |
| A08 | Current-max conflict exact cap `.55`; `src/weather/model/model_distribution_constants.py:114-119`; activation requires Toronto at `src/weather/model/model_distribution_signals.py:131-137` | Safety policy; Toronto WU current-max | Qualitative conflict guard | Applied near end and can change calibration result | Retain as temporary Toronto-only conservative cap; require boundary Monte Carlo | **OBSERVED / RECOMMENDATION** |
| A09 | Late lock-in: start `15`, full `17`, drop `2`, hedge `.05`, base `.15`, continuation `.35/.45`; `src/weather/model/model_distribution_constants.py:121-135` | Time/regime heuristics | Market-gap narrative; no bound outer sample | Multiple overlapping late stages; noncommutative | Collapse to one learned/monotonic late-day state model or retire redundant stages | **OBSERVED / RECOMMENDATION** |
| A10 | Learned lock-in start `17`, stood `90m`; `src/weather/model/model_distribution_constants.py:136-145` | Empirical estimate + heuristic gate | Comment lists unconditional revision rates; settlement-lag rows are snapshot-weighted | Runtime confidence uses correlated counts; overlaps heuristic lock-in | Deduplicate by market-day/cutoff and shrink; otherwise abstain | **OBSERVED / RECOMMENDATION** |
| A11 | High-stood: hours `13–15`, `60m`, ≥2 sources, margins `.25`; expanded: `15–19`, `60m`, margins `.5/.25`, max `.85`; `src/weather/model/model_distribution_constants.py:146-157` | Heuristic router | Item-specific rationale; independent N not encoded | Overlaps partial and learned lock-ins | Combine into one predeclared state machine; run branch ablation | **OBSERVED / RECOMMENDATION** |
| A12 | Partial lock-in: `13–19`, `60m`, rollover `.25`, upside `1.25`, agreement `3`, max `.55`, retained `.55/.30`, base `.18`; `src/weather/model/model_distribution_constants.py:158-170` | Market-transfer heuristic | Austin-style narrative; N not encoded | Overlaps A09–A11 | Quarantine unless outer slice improvement repeats | **OBSERVED / RECOMMENDATION** |
| A13 | WU hard current-max floor allowlist `{miami}`; `src/weather/model/model_distribution_constants.py:172` | Market exception / safety policy | Location-specific replay history, not encoded in constant artifact | Exact Miami identity is required; unknown IDs route to Toronto and create the separate A18 risk | Require release-manifest route and per-market outer/forward evidence | **OBSERVED / RECOMMENDATION** |
| A14 | Source TTLs: MRMS `20m`; WU/SWOB `30m`; METAR/marine `75m`; forecasts `90–120m`; `src/weather/model/model_constants.py:27-55` | Operational SLA / freshness heuristic | Expected update cadence comments; no boundary sensitivity artifact | Cache can return `ok=True, stale=True`; live pooled freshness is ignored only for artifacts carrying the optional guardrail | Retain provisionally, simulate boundaries; make state explicit in model permission | **OBSERVED / RECOMMENDATION** |
| A15 | Multi-source median; warm outlier gaps `3` and isolated `1.5`; `src/weather/model/model_features.py:390-425` | Feature/routing heuristic | Robustness rationale; historical training has one source | Direct train/serve mismatch; correlated provider count | Reconstruct historical multi-source PIT or serve training-matched definition | **OBSERVED / RECOMMENDATION** |
| A16 | Missing warming/peak/pressure/wind/disagreement → `0`; late first-high → now−30m; `src/weather/model/model_features.py:831-855,1069,1474-1490`; `src/weather/model/feature_store.py:1253-1300,1382-1400` | Missing-data substitutions | Convenience fallbacks; no missingness ablation | Converts outage to neutral physical state; differs across paths | Disable neutral fabrication; add missing flags/imputation/abstention | **OBSERVED / RECOMMENDATION** |
| A17 | HGB → LR → empirical on exceptions; `src/weather/model/model_features.py:1110-1225` | Model fallback | Resilience rationale; fallback not separately qualified | Changes model family without release change | Named shadow routes only; fail closed for release-bound unexpected switch | **OBSERVED / RECOMMENDATION** |
| A18 | Unknown market → Toronto default; invalid/missing replay cutoff → captured local hour, then `12` only if capture time is unparseable; `src/weather/market/market_registry.py:396-397`, `src/weather/backtesting/replay.py:341-362` | Identity/default policy | Legacy compatibility | Can mix market/unit/timezone; plausible silent output | Strict validation; allow default only for explicitly absent legacy research input | **OBSERVED / RECOMMENDATION** |
| A19 | HGB temperature grid `{.70,.85,1,1.2,1.5,2}` and blend weights `{.50,.60,.70,.75,.80,.85,.90,.95,.97}`; `src/weather/calibration/feature_probability_calibration.py:8-9`, selected/reported on same OOF rows at `src/weather/calibration/feature_model.py:1285-1311` | Learned selection | Minimizes same-row log loss | Selector and reporter share rows | Nested selection only | **OBSERVED / RECOMMENDATION** |
| A20 | Base current blend: default `1`, market overrides `0/.2`, context `.35/.35/.50`; optional freshness default `0`, `all_fresh=1`; `src/weather/calibration/pooled_training.py:95-153,505-506` | Manual routing/safety | Item-specific replay rationale | Replay/live mismatch; for guarded artifacts, last match can override safety cap | One shared monotonic resolver; re-estimate or simplify | **OBSERVED / RECOMMENDATION** |
| A21 | Probability calibration min context `40`, shrink K `50`; exact temperatures `{1,1.2,1.5,2,3,4}`, deployment cap `1.5`, hour shrink `4` dates; `src/weather/calibration/probability_calibration.py:58,599-610,649-713` | Calibration heuristics | Small-date artifacts; selector/report reuse | Binary arm bypassed; exact fit differs from serve transform | Retire dead arm; coherent OOF simplex calibration | **OBSERVED / RECOMMENDATION** |
| A22 | Afternoon hours `15–18`, min context `4`, max shift `2`, disagreement ref `3`, spread sigma `.75 + .05`, max blend `.35`; `artifacts/misc/afternoon_residual_centering.json:2-21`; trainer `src/weather/calibration/afternoon_residual_centering.py:197-286` | Active correction heuristic | 5,747 correlated rows / 213 folders; validation in-sample | Runs before later floors/lock-ins; after-bias tautological | Disable for promotion or validate leave-fleet-date-out with minimum independent dates | **OBSERVED / RECOMMENDATION** |
| A23 | Family `F`, trust ≥`25`, settled days ≥`2`; trust maturity K `8`, ECE `.04/.16`, prior `.15`; `src/weather/calibration/family_secondary_artifacts.py:26-34,371-399`, `src/weather/reporting/location_analysis/location_trust.py:51-88` | Operational safety policy | Two days can meet low trust; no required lift | Can authorize ML without locked improvement | Gate on outer/forward skill and clustered uncertainty, not low trust alone | **OBSERVED / RECOMMENDATION** |
| A24 | Readiness: three clean active days; challenger minimum seven forward days / 84 market-days; `src/weather/reporting/serving_gates/production_readiness_gate.py:546-570,1031-1090` | Operational SLA | Parent program; shorter than canonical 14-day confirmation | Gate stages interact with missing release identity | Preserve seven-day minimum but require contiguous predeclared 14-day confirmation before paper/capital | **OBSERVED / RECOMMENDATION** |
| A25 | Synthetic band weights: positive exact ×`4`, other positive ×`2`, settlement distance zero ×`1.5`, late hour ×`2`; `src/weather/calibration/pooled_feature_assembly.py:1191-1198`, with many generated band rows at `:1145-1208` | Training sample/weight heuristic | Encodes desired winner/tail emphasis; no bound nested sensitivity report | One market-day yields many pseudoreplicated rows; evaluation can inherit synthetic weighting | Score real partitions by market-day/date; publish 0/0.5/1/2/4 weight sensitivity and use regularization | **OBSERVED / RECOMMENDATION** |
| A26 | Settlement window `00:00:00–23:59:59 local`, market display unit, configured station/timezone, `round_half_up` whole degree, material coverage and reconciliation countability; `src/weather/backtesting/settlement_ledger.py:915-983` | Settlement/market contract | Market resolution specification and source policy; one of the few rule-like invariants | Mutable label upsert and missing raw resolution weaken provenance; unit/boundary sensitivity unmeasured | Retain explicit contract, make revisions immutable, and test unit/timezone/boundary/rounding metamorphics | **OBSERVED / RECOMMENDATION** |
| A27 | Forecast-error scaling: sigma `.75–3`, weight shrink `20`, source-prior shrink `60`, maximum shrink factor `6`, disagreement widening `.20/°C`; `src/weather/calibration/forecast_error_model.py:54-55,564-573`; runtime `src/weather/model/calibration_runtime.py:622-673` | Learned uncertainty correction plus clamps | Toronto honest daily-archive LOO learned Brier `.823009` versus cap `.715999`; `artifacts/calibration/forecast_error_model.json:22-25` | Reachable even where honest Toronto result is adverse; per-market transfer not established | Require positive outer lift per market or disable; sweep clamps/shrink | **OBSERVED / RECOMMENDATION** |
| A28 | Settlement lag: hours `8–20`, smoothing alpha `2`, catch-up prior `.70`, revision prior `.50`, minimum context `20`, default source `eccc_swob`; `src/weather/calibration/settlement_lag_model.py:38,255-258,274-310,320-381` | Learned lag estimate plus priors | Snapshot rows, not independent market-days, establish context N | Cadence inflates confidence; multiple lock-in stages consume result | Deduplicate by market-day/cutoff, cluster CIs, shrink or abstain | **OBSERVED / RECOMMENDATION** |
| A29 | Hand-set empirical/live weights: intraday bases `.36/.48/.58/.70/.82` with `n/(n+25)`, tail `.15/.35/.55/.75/.90`, history `1/1.6/2.2/2.7/3.5`, forecast `1.8/1.4/1`; route-specific weights at `src/weather/model/model_distribution.py:1296-1360,1519-1559` | Empirical blend heuristics by hour/route | Original independent selection sample not bound | Interacts with route choice, forecast cluster, floors, and calibration | Include in E4; learn with shrinkage or collapse to simpler residual model | **OBSERVED / RECOMMENDATION** |

**OBSERVED:** genuine physical/contract invariants are narrower than this stack:
probabilities must form a simplex; bands must match market resolution and
rounding; timestamps must precede prediction; market/station/unit/timezone must
be explicit; and a printed settlement-authoritative high can rule out lower
outcomes under the market's legal rule. Most other values above are heuristics,
empirical estimates, safety policies, or operational SLAs and must not be
presented as physical facts.

**OBSERVED — relevant git history:** bounded `git blame` on the 174-line
`model_distribution_constants.py` attributes 123 lines to
`f7265bd3764bbc7ee3d601e71a73b9f1a7ae3bfa` (`2026-06-15`), 20 to
`1e175b4428b7193f2efe010b86333b24c349b941` (`2026-06-21`), 13 to
`847d71d461f24b0c4f711694b66120e917567c40` (`2026-06-22`), ten to
`2e3672d99680ac7d28886d81856e8f4d76f65bdf` (`2026-06-21`), six to
`3242e26399be1dedfed627c6d8c95e2c6835915b` (`2026-06-24`), and two to
`5735b573aa284da070fba9b751d3a48f5819aca4` (`2026-06-30`). Every subject is
the generic `add`; history adds no independent sample or transfer rationale
beyond the inline comments. This strengthens the need for the disposition
tests above; it is not evidence that the constants are wrong.

## Validation-gap matrix

| Path / claim | Implemented and release-gating | Implemented but diagnostic, stale, or noncanonical | Missing / invalid | Required disposition | Classification |
| --- | --- | --- | --- | --- | --- |
| Legacy feature HGB/LR | Feature safety, blocked-date plan, artifact exports, unit tests | Year/date exclusion and feature-family ablations | Global preprocessing leaks; temperature/blend selection lacks outer layer; train/live forecast definition differs | Fold-local nested rerun; old report diagnostic only | **OBSERVED / RECOMMENDATION** |
| Pooled band candidate / Item 50 | Artifact schema, replay, live runtime, score reports | Single holdout-year report; synthetic band expansion; “blocked validation” partition summary | Same-holdout temperature/adjacent/exact/bias tuning; replay/live blend mismatch; no current parity artifact | P0 parity fix, then nested OOF postprocessing | **OBSERVED / RECOMMENDATION** |
| Continuous density candidate | Density artifact/replay mechanisms, forensic parity diagnostic | Two-sample parity diagnostic is correctly `BLOCK`; candidate quarantined | Same-holdout sigma/shape/postprocess tuning; no promotion-grade live parity | Keep quarantined; include as a control only | **OBSERVED / RECOMMENDATION** |
| Probability calibration | Candidate LOO code, hard-bin rules, runtime simplex transform | Proper-score artifact says PASS while served parity/CRPS skip; thresholds diagnostic-only | Exact fitted objective differs from served transform; same rows tune/report; selected binary arm bypassed | Refit literal served transform from inner OOF; retire dead arm | **OBSERVED / RECOMMENDATION** |
| Afternoon residual centering | Artifact, runtime stage, unit tests | In-sample summary | No independent validation, tiny minimum context, stage interactions unmeasured | Disable or nested leave-date-out qualification | **OBSERVED / RECOMMENDATION** |
| Settlement-lag / forecast-error corrections | Artifacts and runtime consumers | Snapshot-weighted and in-sample summaries; Toronto forecast-error honest result can be adverse | Effective independent N, outer lift, and per-market fail-closed permission absent | Re-estimate by market-day/date with shrinkage or disable | **OBSERVED / RECOMMENDATION** |
| Point-in-time materializer/folds | Canonical key/lanes, materializer checks, 3-day embargo plan, release candidate contract | Plan PASS only | Zero accepted corpus rows; no production training caller, fit receipts, candidate run, streaming evaluation, or pre-selection lock proof | Operationalize one hash-bound candidate execution | **OBSERVED / RECOMMENDATION** |
| Base distribution stages | Component trace and stage attribution diagnostic | `distribution_stage_attribution.json` is actionable but not nested promotion evidence; four stages net-negative in that diagnostic | No complete remove-one/cumulative/order matrix on untouched dates | Run E4; retire noninferior removals | **OBSERVED / RECOMMENDATION** |
| Live variant captured-input parity | Generic comparator checks identity, coverage, skip decisions, hashes, probabilities | Density-only forensic diagnostic | `live_variant_replay_parity.json` and all-branch active-variant proof absent | E1 must PASS before countability | **OBSERVED / RECOMMENDATION** |
| Live settlement scorecard | Explicit release ID, simplex, coverage, equal market-day weighting, fleet-date clustered intervals | Fresh current scorecard | Zero valid eligible partitions; unsupported runtimes; no release ID | Keep blocker; regenerate only from one immutable release | **OBSERVED / RECOMMENDATION** |
| Archive/recoverability | Event/archive schemas, bounded coverage audit | Incremental Parquet batch can locally PASS | Core families optional; orphan writers; zero full links/backups/restores | Repair contracts and prove restore before PIT corpus use | **OBSERVED / RECOMMENDATION** |
| Settlement truth | Quality/countability rules, settlement source audit | Current-state hashes and missing-reason lineage | Mutable upsert, no revision chain, no raw market-resolution proof for many rows | Append-only truth ledger and perturbation analysis | **OBSERVED / RECOMMENDATION** |
| Maker/taker evidence | Risk/preflight/run artifacts and staged gates | Paper/trading scorecards exist but blocked/stale | Release binding, countable settled fill evidence, executable after-cost proof | Defer until shadow model qualifies | **OBSERVED / RECOMMENDATION** |
| Parent production gate | Freshness/hash/release/child fail-closed checks | None relevant; current BLOCK is truthful | Upstream evidence is absent/invalid, not a gate bug | Preserve blocker semantics | **OBSERVED / RECOMMENDATION** |

### Existing test/analysis inventory by status

**OBSERVED — implemented and genuinely gating:** release-candidate schema and
hash checks; active release identity; live partition completeness; exact
captured-input replay parity contract; freshness; PIT role/date rules; static
label-field audit; staged shadow/paper/capital inputs; settlement countability;
archive coverage; and the parent production gate.

**OBSERVED — implemented but diagnostic/currently non-promotion-grade:** proper
scoring/reliability scorecard (served parity and density CRPS skipped), density
forensic parity (two samples, BLOCK), source-family ablation (five market-days
despite 265,034 rows), distribution-stage attribution, winner-rank parity
(BLOCK), active-variant shadow (BLOCK), and stale served-calibration/ordinal
artifacts. Their hashes are in the evidence manifest.

**OBSERVED — not found in bounded `src/`/`tests/` search:** grouped whole-date
target permutation, random-noise feature control, market-copy placebo,
future-availability sentinel, label-derived proxy/hash sentinel, comprehensive
metamorphic suite, clock-skew/late-arrival leakage probe, model-performance
cadence downsampling, settlement revision/rounding Monte Carlo, forecast
revision change-point detector, seed/fold/embargo stability report, and an
effective independent sample estimator. Some operational cadence, malformed
log, source gate, and feature-importance permutation tests exist, but they do
not implement these model-evidence controls.

## Ranked experiment and simulation plan

Every experiment below uses immutable inputs and emits terminal status from
`resolved`, `rejected`, `regressed`, `inconclusive`, or `superseded`. No result
may be promoted from snapshot/band row counts alone.

### E1 — Active replay/serve parity matrix

- **HYPOTHESIS:** active band variants diverge whenever source/context alpha
  differs from market/default alpha, and multi-match ordering can defeat a
  source safety cap.
- **RECOMMENDATION — immutable inputs:** hash the registry
  (`062d7b…18ef`), active artifacts, source fixtures, and one captured input per
  market. Include every market, active variant, source freshness state, context
  rule, multi-match order, missing field, unsupported runtime, and fallback.
- **RECOMMENDATION — independent unit/minimum:** 12 markets × all active
  variants × every reachable branch; at least one real partition per market.
- **RECOMMENDATION — comparator/control:** literal live runtime versus canonical
  replay; identity/no-current-blend control.
- **RECOMMENDATION — metrics/threshold:** exact identity and skip decision;
  identical bands; simplex error ≤`1e-12`; probability absolute tolerance
  `1e-12`, relative `1e-9`; zero missing/extra rows.
- **RECOMMENDATION — budget/output:** two CPU, 4 GB RAM, ≤2 GB I/O, 15 minutes;
  emit `live_variant_replay_parity.json/.md`, branch trace, input manifest.
- **RECOMMENDATION — decision:** only full PASS is `resolved`; any mismatch is
  `regressed`. This removes the replay/serve-parity blocker; countability still
  requires release identity, complete coverage, valid partitions, and every
  remaining scorer gate.

### E2 — Leakage-correct nested baseline requalification

- **HYPOTHESIS:** fold-local preprocessing and nested calibration reduce
  apparent legacy skill; a regularized forecast-residual model is competitive
  with the large serving stack.
- **RECOMMENDATION — immutable inputs:** one release-bound PIT corpus and
  materialization manifest, whole fleet dates, three-day embargo, predeclared
  feature set. Hash all input partitions and code/artifacts.
- **RECOMMENDATION — models:** frozen current release, climatology, simple
  regularized NWP-residual ordinal/density baseline, Item 50, dynamic-source,
  and no-change/component-removal controls. Market is reported only in its
  benchmark lane.
- **RECOMMENDATION — independent unit/minimum:** fleet date; current plan has 36
  dates/19 possible outer folds. Mark model selection inconclusive with fewer
  than 14 usable outer dates.
- **RECOMMENDATION — selection/evaluation:** inner rolling folds fit transforms,
  features, hyperparameters, weights, calibration, postprocessing, and router;
  untouched outer dates estimate. Calibrators consume inner-OOF predictions.
- **RECOMMENDATION — negative controls:** whole-date target permutation and
  random-noise features. The recent inspected window is consumed; register a
  new locked contiguous 14-day window before selection.
- **RECOMMENDATION — metrics:** equal-market-day and equal-fleet-date Brier/log
  loss; protected RPS/CRPS where supported, ECE/reliability, sharpness, top-band
  hit/rank, market/cutoff/regime/source-health slices, fleet-date-clustered CIs.
- **RECOMMENDATION — threshold:** both aggregate deltas <0; material target
  `ΔBrier ≤ -0.002`, `Δlogloss ≤ -0.005`; no market `ΔBrier > +0.01`; negative
  controls show no positive skill.
- **RECOMMENDATION — budget/output:** eight CPU, 16 GB, ≤10 GB I/O, four hours;
  emit hash-linked fold predictions, stage receipts, outer scorecard, controls.
  Unlocks freezing one challenger, never immediate promotion.

### E3 — Served calibration semantics and dead-arm ablation

- **HYPOTHESIS:** identity or correctly fitted simplex-preserving temperature
  beats the current mismatched/bypassed calibration stack.
- **RECOMMENDATION — inputs/unit:** reuse E2 inner-OOF full distributions;
  independent unit fleet date.
- **RECOMMENDATION — arms:** identity; literal served power-normalization
  temperature; coherent ordinal/simplex shrinkage; current taper-to-identity;
  Platt/isotonic only if mapped jointly to a valid partition. Include the literal
  current served transform as comparator.
- **RECOMMENDATION — threshold:** outer Brier and log loss both improve; ECE
  worsens by no more than `.01`; simplex always valid; no market Brier regression
  >`.01`. Check hours, seeds, and 3/5/7-day embargo.
- **RECOMMENDATION — budget/output:** four CPU, 8 GB, one hour with cached OOF;
  emit calibration map, reliability/sharpness, parity vectors, retirement
  decision. Terminal `resolved`, `rejected`, or `superseded`.

### E4 — Distribution-stage and router simplification

- **HYPOTHESIS:** one or more forecast floor/pull, warm-tail, transition,
  centering, observation-floor, cap, continuation, lock-in, calibration, or
  router stages adds no out-of-time value.
- **RECOMMENDATION — protocol:** inside E2, run remove-one, cumulative removal,
  and a small predeclared interaction/order matrix. Freeze deterministic stages
  before fitting final calibration. Use paired fleet-date deltas.
- **RECOMMENDATION — comparator/control:** frozen full stack, no-change, and
  simple baseline.
- **RECOMMENDATION — threshold:** retire a stage if removal is noninferior within
  `+0.001` Brier and `+0.005` log loss and violates no physical/settlement
  invariant; retain only on repeatable improvement in both primaries.
- **RECOMMENDATION — budget/output:** eight CPU, 16 GB, four hours using cached
  base predictions; emit stage DAG, paired deltas, interaction matrix, and
  retain/retire register.

### E5 — Leakage and placebo negative-control battery

- **HYPOTHESIS:** static feature-name checks catch explicit labels but not
  statistical, temporal, or lane leakage.
- **RECOMMENDATION — controls:** whole-date target permutation; random-noise
  features; future-availability timestamp; hashed label proxy; settlement-
  distance alias; and market-copy placebo restricted to market-informed lane.
- **RECOMMENDATION — unit/threshold:** fleet date; explicit sentinels must hard
  block; permutation/noise must not beat climatology with clustered CI;
  selection frequency ≤5% across five seeds.
- **RECOMMENDATION — budget/output:** four CPU, 8 GB, one hour; emit
  `candidate_negative_controls.json`, rejected-field manifest, seed table.
  Any sentinel survival is `regressed`.

### E6 — Provider fault, cadence, timing, and metamorphic simulation

- **HYPOTHESIS:** stale/missing/correlated providers, timing shifts, and unit or
  timezone transforms expose untested fallback/parity branches and fabricated
  neutral features.
- **RECOMMENDATION — immutable inputs:** frozen real captured inputs plus
  deterministic mutations: single/correlated outage, stale, delayed, malformed,
  partial, provider time shift, ±clock skew, late arrival, and 1/5/10/20/30-minute
  downsampling.
- **RECOMMENDATION — metamorphic controls:** C↔F round trips, timezone-preserving
  local-day transformation, market-context identity, band-boundary perturbation,
  reordered equivalent source payload.
- **RECOMMENDATION — threshold:** no exception or impossible fabricated value;
  probability invariants and replay/serve parity always pass; critical missing
  context causes explicit abstention; equivalent unit/timezone inputs are
  invariant.
- **RECOMMENDATION — budget/output:** four CPU, 8 GB, ≤5 GB I/O, 45 minutes;
  emit fault matrix, fallback trace, cadence curve, metamorphic failures.

### E7 — Settlement uncertainty and rare-regime robustness

- **HYPOTHESIS:** valid station precision, rounding, correction, and revision
  uncertainty changes winning-band decisions; rare heat/convection/smoke/marine
  regimes expose brittle stages.
- **RECOMMENDATION — protocol:** seeded Monte Carlo over documented settlement
  rules and revision chains; heatwave, convection, smoke, marine, station/source
  degradation, and near-boundary slices; forecast-revision change-point scan.
- **RECOMMENDATION — unit/minimum:** fleet date clustered by physical episode;
  report but do not tune any slice with fewer than seven dates.
- **RECOMMENDATION — threshold:** ≥95% decision stability under valid label
  perturbations; no protected-slice catastrophic regression.
- **RECOMMENDATION — budget/output:** four CPU, 8 GB, one hour; emit sensitivity
  cube, regime coverage, and change-point report. Thin slices are `inconclusive`.

### E8 — Immutable forward shadow

- **HYPOTHESIS:** the frozen challenger improves over the pinned incumbent under
  exact live production capture.
- **RECOMMENDATION — protocol:** freeze release/routes before day one; one
  identity; no retuning. First meet the parent minimum of seven complete
  days/84 market-days, then continue to a contiguous predeclared 14-day/168
  market-day confirmation.
- **RECOMMENDATION — threshold:** 100% eligible partition coverage; zero
  unsupported-runtime skips; full parity; Brier and log loss both better; no
  material location regression; fleet-date clustered uncertainty reported.
- **RECOMMENDATION — output/decision:** clean-day ledger, live scorecard, parity,
  challenger-forward artifact. PASS unlocks paper canary only; failure is
  `rejected` or `regressed`.

## Canonical tuning and “fine-tuning” protocol

The repository should have one canonical model-selection protocol and make all
other reports explicitly diagnostic.

1. **RECOMMENDATION — freeze identity first.** Bind code commit, source
   fingerprint, dependency versions, feature schema, model/calibration/
   postprocess hashes, registry/routes, market/station/unit/timezone registry,
   corpus partitions, and rollback target into an immutable candidate release.

2. **RECOMMENDATION — materialize point-in-time inputs.** Require event, issue,
   provider availability, local ingestion, and prediction times. Reject any
   feature whose first availability is after prediction. Hash source payloads,
   normalized rows, derived features, labels, and each partition.

3. **RECOMMENDATION — keep fleet dates indivisible.** A fleet date is the outer
   independent unit; market-day is a secondary reporting unit. Never split
   snapshots/bands from one date across train and validation.

4. **RECOMMENDATION — use nested rolling origin.** Predeclare a 3–7 day embargo.
   Inner rolling folds select feature/source families, preprocessing, model
   hyperparameters, class/sample weights, calibration, smoothing,
   postprocessing, thresholds, and router. Outer folds estimate the already
   selected stack only.

5. **RECOMMENDATION — fit transforms locally.** Imputers, scalers, encoders,
   feature selectors, source-bias models, lag/error models, and every learned
   correction fit only on the relevant training fold. Missing indicators and
   availability states are features; zero is used only when it is a physical
   zero.

6. **RECOMMENDATION — calibrate OOF predictions.** Generate model predictions
   for the inner training set out of fold, then fit one coherent final
   calibrator on those predictions. Apply the literal served transform during
   validation. No correction may be fitted on an outer date.

7. **RECOMMENDATION — control weighting.** Optimize equal market-day weights
   and report equal-fleet-date results. Synthetic bands can be training
   augmentation but never independent evaluation rows. Publish sensitivity to
   winner/distance/late weights and an effective independent sample count.

8. **RECOMMENDATION — compare simple baselines.** Always include frozen current
   release, climatology, strong regularized NWP-residual baseline, dynamic-source
   and Item 50 challengers, no-change, and component removals. Keep market
   benchmark and market-informed models in separate legal/evidence lanes.

9. **RECOMMENDATION — report complete metrics.** Brier, log loss, RPS/CRPS where
   supported, ECE/reliability, sharpness, top-band hit/rank, per-market/cutoff/
   regime/source-health slices, and fleet-date-clustered confidence intervals.
   Report exclusions, date coverage, identities, and missing partitions.

10. **RECOMMENDATION — lock before selection.** Register an append-only,
    contiguous latest 14-day window before any candidate inspection. The recent
    June 28–July 11 window has influenced choices and is consumed. A declaration
    created immediately before scoring is insufficient proof of pre-selection
    lock.

11. **RECOMMENDATION — freeze once.** After outer selection, fit the candidate
    once on allowed pre-lock data, create stage-output-bound receipts, and do not
    tune against the locked window. One evaluation produces a terminal result.

12. **RECOMMENDATION — require forward evidence.** A successful locked result
    permits immutable shadow only. Require exact captured-input parity, at least
    seven complete forward days/84 market-days, then a 14-day confirmation,
    before paper. Paper after-cost/executable gates must pass before any capital
    canary.

### Current compliance with the canonical protocol

| Requirement | Current state | Classification |
| --- | --- | --- |
| Whole fleet dates | Plan mechanism exists; legacy paths are noncanonical | **OBSERVED** |
| Nested rolling origin | Plan builder exists; no candidate execution/receipts | **OBSERVED** |
| 3–7 day embargo | Diagnostic plan uses three; feature/pooled trainers do not | **OBSERVED** |
| Fold-local all stages | Interface intent exists; preprocessing/postprocessing violate it | **OBSERVED** |
| Calibrator on training OOF | Not enforced; active paths violate or mismatch serving | **OBSERVED** |
| Inner selection / outer estimation | No production candidate run | **OBSERVED** |
| Equal market-day/date reporting | PIT/live scorer support it; old calibration reports row-weight | **OBSERVED** |
| Fleet-date clustered intervals | Live/PIT scoring supports; old artifacts are incomplete | **OBSERVED** |
| Locked 14-day window before selection | Not proven; recent window consumed | **OBSERVED / INFERRED** |
| Forward shadow after freeze | Parent gate requires it; current evidence absent | **OBSERVED** |

## Simplification and retirement list

| Component/claim | Current status | Proposed disposition and acceptance rule | Classification |
| --- | --- | --- | --- |
| Selected binary prior/Platt/isotonic calibrator | Serialized but bypassed by coherence flag | Retire or label diagnostic; retain only if a coherent served consumer passes E3 | **OBSERVED / RECOMMENDATION** |
| Exact binary-fitted temperature report | Active serving transform is different | Supersede with literal simplex calibration fitted on OOF distributions | **OBSERVED / RECOMMENDATION** |
| “Blocked validation PASS” performance claim | Partition feasibility only | Rename; never use as skill/leakage evidence without execution receipts | **OBSERVED / RECOMMENDATION** |
| Same-holdout pooled temperature/adjacent/exact/bias gains | Reported on rows used for fitting | Mark diagnostic-only and regenerate under E2 | **OBSERVED / RECOMMENDATION** |
| Afternoon residual centering | Reachable; validation in-sample | Disable for promotion until independent dates pass; retire if E4 removal is noninferior | **OBSERVED / RECOMMENDATION** |
| Forecast-error scaling | Reachable; adverse honest Toronto result can coexist with enablement | Require positive outer lift per market or disable | **OBSERVED / RECOMMENDATION** |
| Multiple overlapping late lock-ins | Reachable, many thresholds | Collapse to one explicit state model; retire redundant stages by E4 | **OBSERVED / RECOMMENDATION** |
| LR exception fallback | Different model family, not a named qualified release | Make a named shadow variant or fail closed; do not silently substitute | **OBSERVED / RECOMMENDATION** |
| Empirical exception fallback | Final plausible output despite artifact failure | Shadow/diagnostic only; production abstains on unexpected route | **OBSERVED / RECOMMENDATION** |
| Ordinal smoothing exports | Implemented but current exports disabled | Remove dead export/runtime branches after compatibility audit | **OBSERVED / RECOMMENDATION** |
| F-family aggregate probability artifact | Generated; no static serving reference found | Confirm release-manifest consumer or retire artifact production | **OBSERVED / RECOMMENDATION** |
| Density HGB | Current forensic parity BLOCK, poor recent score | Keep quarantined; use only as a negative/control arm until full requalification | **OBSERVED / RECOMMENDATION** |
| Unknown-market Toronto default | Reachable compatibility behavior | Retire for all nonempty unknown IDs; explicit legacy absence only | **OBSERVED / RECOMMENDATION** |
| Neutral fabricated missing values | Reachable | Replace with missingness/uncertainty/abstention; remove after artifact migration | **OBSERVED / RECOMMENDATION** |
| New exotic feature families | No evidence-integrity foundation yet | Defer until E1/E2 and capture ranks 1–4 are complete | **RECOMMENDATION** |

The target simpler model is:

> **RECOMMENDATION:** a market-specific climatology/prior plus one regularized,
> point-in-time NWP-residual ordinal or density model, explicit missing/source
> health, only settlement-valid hard constraints, and one final
> simplex-preserving calibrator. Add a router only if nested outer folds and
> immutable forward evidence prove it.

## Prioritized work order

### DO NOW

1. **RECOMMENDATION:** fix F08 with one shared blend resolver and exhaustive
   branch parity. Do not count affected variant evidence until E1 passes.
2. **RECOMMENDATION:** register observation payload and CLOB capture-status
   writers in event/storage/archive/PIT/backup contracts; require core event
   families and singular identity.
3. **RECOMMENDATION:** enable deduplicated raw forecast payload retention and an
   append-only settlement revision stream with five-time provenance.
4. **RECOMMENDATION:** remove global preprocessing from feature validation and
   same-holdout postprocess tuning; correct calibration/serve semantics.
5. **RECOMMENDATION:** create one immutable research release and materialize a
   nonempty hash-bound PIT corpus with recomputable stage receipts.
6. **RECOMMENDATION:** run E1, then E2/E3/E4; choose one simpler candidate only
   from untouched outer dates.

### COLLECT FORWARD EVIDENCE

- **RECOMMENDATION:** populate NBM probabilistic Tmax and existing supported
  sources under explicit first-available/raw-hash contracts.
- **RECOMMENDATION:** complete event/archive links for retained closed days,
  then prove off-machine backup and restore of one release input and score.
- **RECOMMENDATION:** freeze one candidate and collect seven complete days, then
  a 14-day confirmation with 100% parity/coverage and one runtime identity.
- **RECOMMENDATION:** only after shadow qualification, collect paper executable
  fill, slippage, fee, adverse-selection, and after-cost evidence.

### DEFER

- **RECOMMENDATION:** new exotic providers, higher-capacity model families,
  broad hyperparameter searches, complex regime routers, market-informed model
  promotion, authenticated order adapter, and capital work.
- **RECOMMENDATION:** pressure-level, smoke/AQ, marine, MRMS, and nearby-station
  model use until their exact consumer, PIT availability, independent regime
  sample, and add-one decision threshold are predeclared.

### RETIRE OR QUARANTINE

- **RECOMMENDATION:** retire the dead binary calibration selector and
  non-executed “blocked validation PASS” claim unless their semantics change.
- **RECOMMENDATION:** quarantine density HGB, same-holdout gains, and all
  current-blend-affected live variant evidence.
- **RECOMMENDATION:** retire any distribution stage whose removal satisfies
  E4's noninferiority and safety rule.
- **RECOMMENDATION:** retire silent Toronto identity fallback and unexpected
  model-family fallbacks from release-bound serving.

## Proposed roadmap changes

No new roadmap item is necessary. The repository already has owners for every
material finding; creating another umbrella item would fragment execution.

| Existing item | Proposed amendment / acceptance criterion | Classification |
| --- | --- | --- |
| Item 321 — production readiness/evidence integrity | Make F01–F08 explicit Stage 0 blockers; require hash-bound PIT execution, pre-selection lock ledger, computational receipts, 100% active-branch parity, and restored archive sample | **RECOMMENDATION** |
| Item 201 — raw observation payload sidecars | Expand closure from “writer exists” to event-family, storage class, archive/Parquet, backup/restore, parser/release identity, and zero-unclassified-byte proof | **RECOMMENDATION** |
| Items 243, 287, 290, 291 — archive/event manifest/schema | Require core families and singular identity; block missing manifest; register observation/CLOB status; relink all retained closed-day archives | **RECOMMENDATION** |
| Item 265 — settlement revision/truth audit | Replace destructive upsert with append-only revision ledger and raw Gamma/WU resolution hashes; distinguish tolerated missingness from proof-grade lineage | **RECOMMENDATION** |
| Items 106, 179 — leakage/honest blocked validation | Add fold-local preprocessing and executed-stage receipts; forbid same-row calibrator/postprocessor selection claims | **RECOMMENDATION** |
| Items 21, 96, 233 — calibration/serve boundary | Fit the literal served simplex transform on inner OOF; disposition dead binary arm; score all post-calibration stages | **RECOMMENDATION** |
| Items 177, 233, 254 — validation/serve skew/runtime | Own the shared blend resolver and all-market/all-branch captured-input parity matrix | **RECOMMENDATION** |
| Item 182 — distribution-stage attribution | Upgrade from diagnostic remove-one report to nested paired date/order interaction matrix and retirement register | **RECOMMENDATION** |
| Items 190, 263, 317 — NBM/physical family/marine | Require raw first-seen provenance and whole-date add-one/leave-one evidence before promotion | **RECOMMENDATION** |
| Items 141, 217, 262, 266 — live variant/frozen baseline/scoring/rank | Require one immutable release, equal-date reporting, 100% partition coverage, exact parity, seven-day minimum and 14-day confirmation | **RECOMMENDATION** |
| Items 112, 124, 154, 159, 171 — writer/storage/headroom | Separate disk-headroom PASS from classification-integrity PASS; add orphan-byte and backup/restore gates | **RECOMMENDATION** |

## Five highest-value next actions

| Priority | Action | Acceptance criteria | Production decision unlocked | Classification |
| ---: | --- | --- | --- | --- |
| 1 | Unify current-blend replay/live resolution and run E1 | One shared function; exhaustive market/source/context/multi-match tests; real captured partitions; zero identity/skip/band/probability mismatch; `live_variant_replay_parity.json` PASS | Removes the parity blocker; identity, complete coverage, valid partitions, and remaining scorer gates still control countability | **RECOMMENDATION** |
| 2 | Close writer-to-retention lineage | Observation and CLOB-status families registered everywhere; required core manifest; missing manifest blocks; zero unclassified bytes for those families; linked archive plus successful restore | Closes retention/recoverability prerequisites; PIT/release eligibility still requires row timing, identity, and release binding | **RECOMMENDATION** |
| 3 | Rebuild one honest nested baseline/challenger comparison | Nonempty release-bound PIT corpus; fold-local all stages; inner OOF calibration; 3-day embargo; ≥14 usable outer dates; negative controls fail; complete equal-date metrics and CIs | Selects one defensible frozen challenger or rejects model complexity | **RECOMMENDATION** |
| 4 | Correct calibration semantics and simplify the stack | Literal serve-transform parity; dead arm retired; E3/E4 paired results; every retained stage improves both primary metrics or enforces a documented invariant | Produces a smaller, auditable candidate graph | **RECOMMENDATION** |
| 5 | Freeze identity and collect immutable forward shadow | Active release pointer to immutable manifest; singular runtime; 100% eligible coverage; zero unsupported skips; seven complete days then 14-day/168-market-day confirmation; Brier/log loss better with no material market regression | Unlocks paper canary only; capital remains separately gated | **RECOMMENDATION** |

## Reproducibility and verification

### Bounded tests run

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/calibration/test_blocked_validation.py tests/reporting/test_point_in_time_evaluation.py tests/reporting/test_live_variant_settlement_scorecard.py tests/reporting/test_production_readiness_gate.py -q -p no:cacheprovider
```

**OBSERVED result:** `58 passed in 2.59s`.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/operations/test_event_day_manifest.py tests/operations/test_closed_market_day_archive.py tests/operations/test_storage_classes.py tests/collection/test_live_variant_predictions.py tests/calibration/test_probability_calibration.py tests/calibration/test_pooled_candidate_replay.py -q -p no:cacheprovider
```

**OBSERVED result:** `120 passed, 26 subtests passed in 4.26s`.

These results prove the inspected unit contracts pass at commit `aaec67f`; they
do not negate missing cross-contract, nested-validation, or literal-serve-path
evidence.

### Reproduce key findings

```powershell
git rev-parse HEAD
git status --short --branch
Get-Date -Format o

# Writer/registry omissions.
rg -n "observation_payload|clob_capture_status" src/weather/operations/event_day_manifest.py src/weather/operations/storage_classes.py src/weather/operations/closed_market_day_archive.py

# Forecast raw retention and replay stripping.
rg -n "retain_raw_forecast_payloads|raw_forecast_payload_retention_enabled|strip_raw_payloads" src/weather/collection/snapshot_store.py

# Feature preprocessing and meta-selection.
rg -n "fit_transform|blocked_plan|hgb_fold_data|fit_temperature_blend_grid" src/weather/calibration/feature_model.py

# Pooled same-holdout postprocessing.
rg -n "holdout_year|tune_temperature|fit_adjacent_calibration|fit_exact_winner_catchup|fit_market_bias_calibration" src/weather/calibration/pooled_training.py

# Replay/live blend implementations.
rg -n "current_blend_alpha|_apply_current_blend|current_blend_context_rule_matches" src/weather tests

# Release/PIT evidence presence.
Test-Path artifacts/releases/current_release.json
Test-Path data/backtest/live_variant_replay_parity.json
Test-Path data/backtest/point_in_time_streaming_evaluation.json

# Hash current bound artifacts.
Get-FileHash data/backtest/production_readiness_gate.json -Algorithm SHA256
Get-FileHash data/backtest/fleet_observability.json -Algorithm SHA256
Get-FileHash data/backtest/live_variant_settlement_scorecard.json -Algorithm SHA256
Get-FileHash data/backtest/event_day_archive_coverage_audit.json -Algorithm SHA256
```

### Reproduce bounded live inventories

```powershell
# Filename-only presence across the 453 event folders.
$folders = @(Get-ChildItem -LiteralPath data\snapshots -Directory |
  Where-Object { $_.Name -like 'highest-temperature-in-*' })
$names = @(
  'snapshots.jsonl', 'source_status.jsonl', 'forecast_payloads.jsonl',
  'replay_inputs.jsonl', 'variant_predictions.jsonl',
  'observation_payloads.jsonl', 'order_books.jsonl',
  'event_day_manifest.json'
)
$names | ForEach-Object {
  $name = $_
  [pscustomobject]@{
    file = $name
    folders_with_file = @($folders | Where-Object {
      Test-Path -LiteralPath (Join-Path $_.FullName $name)
    }).Count
  }
}

# Exact orphan file counts/bytes without opening tape contents.
$clob = @(foreach ($folder in $folders) {
  $path = Join-Path $folder.FullName 'clob_capture_status.jsonl'
  if (Test-Path -LiteralPath $path) { Get-Item -LiteralPath $path }
})
$obs = @(foreach ($folder in $folders) {
  $path = Join-Path $folder.FullName 'observation_payloads'
  if (Test-Path -LiteralPath $path) {
    Get-ChildItem -LiteralPath $path -File -Filter '*.json'
  }
})
[pscustomobject]@{
  captured_at_local = (Get-Date).ToString('o')
  clob_folders = $clob.Count
  clob_bytes = ($clob | Measure-Object Length -Sum).Sum
  observation_raw_files = $obs.Count
  observation_raw_bytes = ($obs | Measure-Object Length -Sum).Sum
}

# Recent payload metadata only.
$dates = @('july-11-2026', 'july-12-2026')
foreach ($date in $dates) {
  $dayFolders = @($folders | Where-Object {
    $_.Name -like "highest-temperature-in-*-on-$date"
  })
  $forecast = @(foreach ($folder in $dayFolders) {
    Import-Csv -LiteralPath (Join-Path $folder.FullName 'forecast_payloads_long.csv')
  })
  $observations = @(foreach ($folder in $dayFolders) {
    Import-Csv -LiteralPath (Join-Path $folder.FullName 'observation_payloads_long.csv')
  })
  [pscustomobject]@{
    date = $date
    forecast_rows = $forecast.Count
    forecast_raw_paths = @($forecast | Where-Object raw_payload_path).Count
    observation_rows = $observations.Count
    provider_observed_times = @($observations | Where-Object provider_observed_at).Count
  }
}
```

Rollout coverage uses this declared denominator: for each market and family,
the first target date containing that file begins that market's eligible
rollout; all earlier market folders are excluded. The evidence JSON records the
result and target-date bounds. This definition measures file continuity after
first observed deployment; it does not prove the first observed date was the
intended rollout date.

## Explicit uncertainties and unverified facts

- **OBSERVED:** no heavy retraining, corpus-wide simulation, provider API call,
  worker restart, schedule change, archive operation, or release mutation was
  performed. Therefore the effect sizes of preprocessing leakage, same-row
  tuning, stage removal, and replay/live skew were not measured here.
- **OBSERVED:** July 12 live counts changed during the audit. Folder presence is
  bound to `13:21:12-04:00`; recent metadata row counts are bound to
  `13:21:35-04:00`; current operational claims use artifact generation times.
- **OBSERVED:** raw provider historical backfill availability, pricing, and rate
  limits were not independently verified. Exact local first-availability times
  generally cannot be reconstructed from provider archives.
- **OBSERVED:** archive coverage findings are manifest/index claims; this audit
  did not open and revalidate every Parquet partition or perform a restore.
- **OBSERVED:** raw maker/taker folders were not exhaustively parsed. Code proves
  their ordinary summaries lack the same immutable release fields, but an
  external operator-side manifest cannot be ruled out.
- **OBSERVED:** pickle artifacts were not deserialized for audit. Relevant
  policy-key presence was established from code, registry entries, safe artifact
  inspection, and hashes.
- **INFERRED:** bounded terminology searches can miss an experiment implemented
  under an unrelated name. No evidence artifact satisfying the specified
  negative-control/metamorphic protocols was found.
- **OBSERVED:** repository evidence cannot prove a human never inspected a date
  window before calling it locked. Only an independently timestamped append-only
  pre-registration record can establish that boundary.
- **OBSERVED:** no immutable active release exists, so “current model” means the
  reachable mutable checkout/artifact graph, not a verified production release.
- **INFERRED:** historical metrics from invalid paths may move materially after
  correction, but direction and magnitude must be measured by E2/E3 rather than
  assumed.

## Final decision

**OBSERVED:** current production disposition remains `NOT_READY`. The correct
near-term operating mode is bounded collection, audit repair, and research
shadow only.

**RECOMMENDATION:** do not capture broadly or tune harder. Make the existing
evidence trustworthy, prove one shared serve/replay graph, select the simplest
candidate under nested whole-date validation, and demand immutable forward
evidence before paper or capital.
