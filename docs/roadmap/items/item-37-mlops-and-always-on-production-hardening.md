# 37. MLOps And Always-On Production Hardening [COMPLETE 2026-06-15 - NIGHTLY RETRAIN + SHADOW AB MONITORING LIVE]

Goal: make the fleet reproducible, self-retraining, and observable.

- [x] Settlement-to-promotion refresh runner: `src.promotion_refresh` rebuilds
  the pinned corpus, refreshes trust, runs pooled replay, runs the current
  serving gauntlet, and emits per-market actions for automation.
- [x] Daily settlement-to-promotion automation: `src.daily_refresh run` executes
  `market_day_labels finalize`, `promotion_refresh`, `progress_audit`,
  `disagreement_casebook`, `fleet_observability`, `data_layer_audit`, and
  `snapshot_evaluation` in order, then distills the day's logs into
  `daily_learning`; writes
  `data/backtest/daily_refresh_status.json`,
  `data/backtest/daily_refresh_report.md`, and the consolidated
  `data/backtest/snapshot_evaluation_report.md` plus
  `data/backtest/daily_learning_report.md`; and
  `scripts/register_daily_refresh.ps1` installs the Windows daily task.
- [x] Data-layer audit runner: `src.data_layer_audit` reports loop health,
  snapshot cadence/completeness, low-fill fields, historical source coverage,
  and prioritized data-retention recommendations.
- [x] Split capture cadences: keep full weather/model snapshots at 5-10 minutes,
  but capture market-book data every 30-60 seconds or via WebSocket without
  refetching every weather source.
- [x] Production-harden the CLOB book loop: heartbeat/status, diagnostics,
  detached start, stop, restart, ensure, and a Windows Task Scheduler
  registration script separate from the weather/model loop.
- [x] Define and enforce the market-making live-forward SLO gate for main
  snapshot collection, CLOB book capture, and the observation-trigger watcher:
  automatic recovery, critical alerting, strict freshness checks, and proof that
  all loops stay fresh before any live-forward paper day or live order can count
  toward an MM gate.
- [x] Require a gap-free active-day snapshot tape across all registered markets
  before fleet observability can clear strict mode; true same-day gaps remain
  immutable data-quality blockers and should not be backfilled synthetically.
- [x] Isolate or throttle long replay/refresh jobs so active-day CLOB book
  capture stays inside the generated strict cadence threshold while live-forward
  evidence is being collected.
- [x] Model/artifact registry + versioning.
- [x] Scheduled nightly retrain -> validate -> promote.
- [x] Shadow / A-B deployment; monitoring + alerting + drift detection per
  market.
- [x] Clean supervised always-on capture (closes item 16); one market's failure
  cannot stall the loop.

Acceptance: a new market or a model update flows through the pipeline with no
manual surgery, and any market-making live-forward or live-order gate fails
closed when CLOB capture or observation-trigger freshness violates its SLO.

CLOB hardening update (2026-06-12): `src.market_microstructure` now mirrors the
snapshot supervisor pattern for the irreplaceable fast book tape. The managed
loop writes `data/snapshots/clob_loop_status.json`, appends
`clob_diagnostics.jsonl`, keeps console output in `clob_loop_console.log`, and
exposes `status`, `start-detached`, `stop`, `restart`, and `ensure` commands.
`scripts/register_clob_supervisor.ps1` installs a separate Task Scheduler job
that runs `market_microstructure ensure` every minute and at logon. Health is
heartbeat-based with `RUNNING`, `DEGRADED`, `ERRORING`, `DEAD`, and `PAUSED`
states; per-market CLOB failures are isolated and surfaced without stopping the
rest of the fleet. A supervisor lock guards `ensure`, `start-detached`, and
`restart` against duplicate loop starts when a manual command lands on the same
minute as Task Scheduler. `src.data_layer_audit` schema `v0.2` now reports the
CLOB loop next to the weather/model loop and raises P0 when book capture is not
managed or fresh. At that point, item 37 still needed the broader live-forward
SLO gate, gap-free active snapshot-tape requirement, model/artifact registry,
and shadow/A-B drift-monitoring work.

Operational registration update (2026-06-14 UTC): the daily refresh and
observation-trigger supervisor tasks are now registered in Windows Task
Scheduler as `WeatherDailySettlementPromotionRefresh` and
`WeatherObservationTriggerSupervisor`, alongside the existing snapshot and CLOB
supervisors. The daily task runs `src.daily_refresh run --continue-on-error`;
the observation task runs `src.observation_trigger ensure`.

Weather snapshot-loop update (2026-06-15 UTC): `src.snapshot_tracker` now
heartbeats/status-writes before and after each market capture in the serial
all-market loop, records `last_iteration_elapsed_minutes`,
`max_recent_iteration_elapsed_minutes`, and `last_sleep_seconds`, and sleeps
from the iteration start instead of adding a full interval after the capture
cycle. This prevents future 12-market weather/model captures from mechanically
creating cadence gaps. The June 14 active-day snapshot holes are still real
immutable tape gaps, so `src.fleet_observability report --strict` remains
collection-critical until a clean active day clears the snapshot tape gate; the
current refreshed strict report also blocks on CLOB book-capture tape gaps.

Live-forward SLO gate update (2026-06-15 UTC): `src.fleet_observability` now
adds observation-trigger watcher health and a generated `live_forward_slo`
verdict to the fleet payload/report. The gate combines three fail-closed inputs:
fleet snapshot collection health, CLOB book-loop/book-tape health, and
observation-trigger watcher health. It emits
`counts_toward_live_forward_gate=false` whenever any of those inputs has a
warning or critical alert, so live-forward paper or live-order evidence cannot
be counted while weather snapshots, CLOB books, or trigger freshness are stale,
gappy, paused, dead, or erroring. Focused coverage in
`tests/reporting/test_fleet_observability.py` proves the gate passes only when
all capture loops are clean and blocks on snapshot gaps, CLOB gaps, or watcher
failure. At that point, the remaining item-37 work was the broader
model/artifact registry, scheduled retrain/validate/promote flow, and
shadow/A-B drift monitoring.
Validation: `pytest tests\collection\test_collection_robustness.py -q`
passes.

CLOB tape-audit update (2026-06-15 UTC): the fleet CLOB audit now uses the
measured serial 12-market loop cadence with a wider jitter buffer and persists
`max_iteration_elapsed_seconds` in loop status so successful slow cycles do not
turn into retroactive false CLOB tape gaps after the recent window rolls forward.
The current `data/backtest/fleet_observability_report.md`, regenerated at
`2026-06-15T04:08:04Z`, is still `CRITICAL`: snapshot collection has immutable
active-day gaps, and the CLOB book tape also has post-startup gaps on eight
markets (`max_counted_gap_seconds` roughly 229-236s versus the generated
204.7s threshold). The live-forward SLO gate correctly blocks credit until a
future active day is clean for both snapshot collection and CLOB book capture.
The CLOB loop itself is running and heartbeating, so this is now a tape-quality
gate, not a dead-loop diagnosis.

Continuous snapshot evaluation update (2026-06-15 UTC):
`src.snapshot_evaluation` now consolidates the latest snapshot inventory,
replay-input coverage, promotion corpus, candidate replay, serving gauntlet,
data-layer audit, fleet SLO, and generated improvement slices into
`data/backtest/snapshot_evaluation.json` and
`data/backtest/snapshot_evaluation_report.md`. `src.daily_refresh` runs it last,
after all source artifacts have been regenerated, and
`--fail-on-snapshot-evaluation` can mark the refresh critical when the
evaluation status is `FAIL`. Focused coverage lives in
`tests/reporting/test_snapshot_evaluation.py` and
`tests/operations/test_daily_refresh.py`.

Artifact-registry update (2026-06-15 UTC): `weather.artifacts` now writes a
versioned model/calibration artifact registry (`model_artifact_registry_v0.1`)
with artifact ids, paths, kind, bytes, SHA-256 fingerprint, modified time, and
JSON-extracted schema/feature/model schema versions. The compatibility command
`python -m src.artifacts registry` writes
`artifacts/manifests/model_artifact_registry.json`; the current run fingerprinted
93 artifacts (`calibration=51`, `coefs_model=24`, `hgb_model=17`,
`manifest=1`). This completes the artifact registry/versioning part of the
roadmap bullet, but the scheduled retrain -> validate -> promote loop remains
open. Focused tests: `tests\test_artifacts.py` and
`tests\operations\test_schema_registry.py` pass; strict schema audit reports
`66` registered schemas, `125` discovered literals, and `0` unregistered.

Long-job guard update (2026-06-15 UTC): `weather.operations.long_job_guard`
adds a shared lock, durable `long_job_guard_v0.1` status file, nested-process
detection, and best-effort process priority throttling for expensive local
jobs. `src.daily_refresh run`, `src.promotion_refresh`, `src.replay_backtest`,
and `src.pooled_candidate_replay` now serialize long replay/refresh work via
the guard by default, with `--disable-long-job-guard`, `--force-long-job-lock`,
and `--long-job-priority` operator overrides. The daily refresh status,
promotion refresh JSON, pooled candidate JSON, and replay result payloads carry
guard metadata so live-forward evidence can distinguish guarded from unguarded
maintenance work. This left shadow/A-B drift monitoring as the final item-37
slice. Focused
validation: `pytest tests/operations/test_long_job_guard.py
tests/operations/test_daily_refresh.py tests/backtesting/test_replay.py
tests/reporting/test_promotion_corpus.py
tests/calibration/test_pooled_candidate_replay.py -q` passes.

Nightly retrain update (2026-06-15 UTC): `weather.operations.nightly_retrain`
adds a scheduled retrain/validation/promotion-decision runner with schema
`nightly_retrain_v0.1`. The default run trains family secondary artifacts,
trains the F-family pooled band candidate, refreshes the model artifact
registry, runs `promotion_refresh`, and writes
`data/backtest/nightly_retrain_status.json` plus
`data/backtest/nightly_retrain_report.md`. It is fail-closed: subprocess
errors mark the run `error`, while promotion decisions classify the result as
`promote_ready`, `shadow`, or `blocked` without mutating serving code paths.
`scripts/register_nightly_retrain.ps1` installs the Windows Task Scheduler job
`WeatherNightlyRetrainValidatePromote` for the nightly run. This left
shadow/A-B deployment plus drift monitoring and alerting as the final item-37
slice. Focused validation: `pytest tests/operations/test_nightly_retrain.py -q`
passes; CLI dry-run and strict schema audit pass.

Shadow/A-B monitoring update (2026-06-15 UTC):
`weather.reporting.shadow_ab_monitor` adds schema `shadow_ab_monitor_v0.1` and
builds an alertable per-market monitor from `f_family_promotion_refresh.json`
and `pooled_candidate_replay_latest.json`. It classifies markets as
`PROMOTE_READY`, `SHADOW`, or `ALERT`, flags candidate regression versus the
current serving replay, candidate gaps versus market prices, blocked promotion
actions, serving-gauntlet blockers, missing artifacts, and failed replay gates,
and writes `data/backtest/shadow_ab_monitor.json` plus
`data/backtest/shadow_ab_monitor_report.md`. `src.daily_refresh run` now runs
the monitor after promotion refresh and can mark the refresh critical with
`--fail-on-shadow-ab-alert`; `src.nightly_retrain run` also runs it after the
post-retrain promotion refresh and can fail with `--fail-on-shadow-ab-alert`.
This completes item 37. Focused validation:
`pytest tests/reporting/test_shadow_ab_monitor.py
tests/operations/test_daily_refresh.py tests/operations/test_nightly_retrain.py
-q` passes; CLI help and strict schema audit pass.

Daily log-learning update (2026-06-16 UTC):
`weather.reporting.daily_learning` adds schema `daily_learning_v0.1` and
builds a daily self-improvement pack from the refreshed settlement labels,
promotion corpus, candidate replay, shadow A/B monitor, variant evidence
growth, disagreement casebook, fleet/data-layer audits, and continuous
snapshot evaluation. The artifact writes `data/backtest/daily_learning.json`
and `data/backtest/daily_learning_report.md`, classifies learnings by priority,
marks data-quality and collection blockers, identifies replay/casebook slices
that should feed retraining, and emits `training_ready` / `promotion_ready`
signals. `weather.operations.daily_refresh` runs it last and can fail critical
with `--fail-on-daily-learning-blocker`; `weather.operations.nightly_retrain`
runs it first so retrain status records what the prior day's logs taught before
building model artifacts. Focused validation:
`pytest tests/reporting/test_daily_learning.py
tests/operations/test_daily_refresh.py tests/operations/test_nightly_retrain.py
-q`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - NIGHTLY RETRAIN + SHADOW AB MONITORING LIVE`.
- The file contains 12 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

