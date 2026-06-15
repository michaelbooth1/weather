# 37. MLOps And Always-On Production Hardening [PARTIAL 2026-06-15 - LIVE-FORWARD SLO GATE READY]

Goal: make the fleet reproducible, self-retraining, and observable.

- [x] Settlement-to-promotion refresh runner: `src.promotion_refresh` rebuilds
  the pinned corpus, refreshes trust, runs pooled replay, runs the current
  serving gauntlet, and emits per-market actions for automation.
- [x] Daily settlement-to-promotion automation: `src.daily_refresh run` executes
  `market_day_labels finalize`, `promotion_refresh`, `progress_audit`,
  `disagreement_casebook`, and `fleet_observability` in order; writes
  `data/backtest/daily_refresh_status.json` and
  `data/backtest/daily_refresh_report.md`; and
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
- [ ] Isolate or throttle long replay/refresh jobs so active-day CLOB book
  capture stays inside the generated strict cadence threshold while live-forward
  evidence is being collected.
- [ ] Model/artifact registry + versioning; scheduled nightly
  retrain -> validate -> promote.
- [ ] Shadow / A-B deployment; monitoring + alerting + drift detection per
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
managed or fresh. Item 37 remains open for the broader live-forward SLO gate,
gap-free active snapshot-tape requirement, model/artifact registry, and
shadow/A-B drift-monitoring work.

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
failure. Remaining item-37 work is the broader model/artifact registry,
scheduled retrain/validate/promote flow, and shadow/A-B drift monitoring.
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
