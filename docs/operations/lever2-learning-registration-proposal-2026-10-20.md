# Lever 2 learning-lane registration: proposal (2026-10-20)

Status: **dated proposal, not authority.** Nothing here is registered or approved. It was written on the
workstation from `origin/master` at `6aac6de81` as a read-only code and ops trace that read no outcome data.
It answers which tasks reach `daily_learning` and `market_beating_objective_scoreboard`, what Stage B does,
the narrowest blind registration, and the embargo surfaces.
**Read when** someone proposes enabling `WeatherEveningEvidenceRefresh` or registering any learning-lane
task, or plans the [exhaustion register](EXHAUSTION_REGISTER.md) order 1 or
[open question](OPEN_QUESTIONS.md) Q-11. The owner of the lane's current state is
[STATE_OF_PLAY](STATE_OF_PLAY.md).

All citations are `file:line` on `origin/master` `6aac6de81`. Abbreviations used throughout:
- `reg` = `src/weather/operations/daily_refresh_registry.py`
- `dr` = `src/weather/operations/daily_refresh.py`
- `cli` = `src/weather/operations/daily_refresh_cli.py`
- `rs` = `src/weather/operations/daily_refresh_reporting_steps.py`
- `gs` = `src/weather/operations/daily_refresh_gate_report_steps.py`
- `sm` = `src/weather/operations/daily_refresh_stage_manifests.py`
- `lanes` = `src/weather/operations/daily_refresh_lanes.py`

## Bottom line

1. **No Ready task reaches either step today** (§1). Only the disabled Stage B task runs both. The disabled
   training-window path runs `daily_learning` only. The nightly-retrain registrar cannot register at all.
2. **Do not enable Stage B for lever 2** (§2):
   - It holds the one non-blocking heavy-work lease from 00:35 for as long as it runs, up to 09:00. That
     makes every quiet-window merge, integration suite, C-night cutover, the U6 04:10 export, tiering and
     the 06:50 cold-snapshot nightly refuse.
   - On the capture host its two replay steps (`promotion_refresh` and `active_variant_shadow`) are
     DEFERRED every night by the live-capture admission gate.
   - So Stage B would buy hours of lease time without refreshing the replay inputs the scoreboard
     aggregates.
3. **The scoreboard cannot close exhaustion-register order 1 at all** (§3.1):
   - It aggregates six upstream JSON verdicts and checks only that they exist, never how old they are.
   - It has no per-hour-block, per-date or log-loss served/market ratio.
   - `daily_learning.json` and the scoreboard JSON are **overwritten** on every run, so nothing "accrues".
   - The order-1 measurement (per-block served/market ratio with the §3 positive control) is a workstation
     analysis. Its inputs already accrue on the capture host without any new task: `snapshots_long`
     carries the model probability and `market_yes`, Stage A writes the labels, and LB-5 backfills them.
   - It needs **no registration**. It needs SD-1 (countable dates), LB-5 coverage and a reviewed tracker
     that runs after 11-13.
4. **If the owner still wants the learning lane alive for Q-11**, the narrowest safe form is a **new bounded
   task, `WeatherLearningTailBlind`**, described in §3.2:
   - It runs `winner_rank_parity` through `market_beating_objective_scoreboard`, seeded from the Stage A
     status.
   - It runs at 00:35 with a 00:55 hard stop, so it is done before the 01:00 merge window.
   - It writes its outputs into a per-target-date embargo vault and restores the previous
     `data/backtest` copies, so no existing surface shows embargoed content (§4).
   - It needs about 200-300 lines of `.ps1` plus tests. That is more than the 30-line limit for this
     trace, so it is **described, not implemented**.
   - It is roll-free (`.ps1` and `config/` only) but is a new scheduled task, so it needs an owner yes.

## 1. Which registered tasks reach the two steps today

| Task (registrar) | Expected state | Reaches `daily_learning`? | Reaches the scoreboard? | Conditions |
| --- | --- | --- | --- | --- |
| `WeatherDailySettlementPromotionRefresh` (`scripts/ops/register_daily_refresh.ps1:132-172`) | active, Ready (`config/scheduled_tasks.json:88-98`) | **No** | **No** | Runs `--stage settlement` (`scripts/ops/daily_refresh_contract.ps1:94-117`). That stage is `STEP_ORDER` up to `physical_feature_family_ratchet` (`reg:250,258-260`); both steps sit after it (`reg:69,72`). It does **read** both files after its loop: the daily progress ledger takes `daily_learning.json`, the scoreboard JSON and `proper_scoring_reliability_scorecard.json` (`src/weather/reporting/daily/daily_progress_ledger.py:283-298,420-434`; `dr:1686`). |
| `WeatherEveningEvidenceRefresh` (same registrar, `:138-142,174-203`) | active, `expected_disabled: true` (`config/scheduled_tasks.json:108-117`); disabled unless `-EnableEvidenceTask` (`:198-203,225-230`) | Yes | Yes | All must hold: (a) enabled; (b) 00:30-09:00 (`scripts/ops/daily_refresh.ps1:103-109`); (c) lease free (`:110-116`, exit 76 otherwise); (d) Stage-A manifest present, valid, for target = Toronto yesterday minus 1 (`sm:82-85`, `dr:1129-1140`), `COMPLETED` and not trigger-pending (`sm:207-262`), and Stage B not already `COMPLETED` for that binding (`sm:280-298`); (e) the learning gate (`rs:1795-1804`) finds the carried Stage-A barrier with `learning_status` exactly `PASS` for the target (`lanes:271-314`; `src/weather/operations/daily_refresh_settled_day.py:427-437`). `DIAGNOSTIC_ONLY` also blocks. (f) No `--skip-daily-learning` / `--skip-market-beating-objective-scoreboard` (`cli:729-730`). |
| `WeatherTrainingWindow` (`scripts/ops/register_training_window.ps1`) | `expected_disabled: true` (`config/scheduled_tasks.json:389-399`); registers Disabled without `-EnableWindow` (`:128-133`) | Yes, as `nightly_retrain`'s own step (`src/weather/operations/nightly_retrain.py:1379-1380,529-541`; `scripts/ops/training_window.ps1:431-432`) | **No** (not a `nightly_retrain` step, `nightly_retrain.py:1376-1409`) | Stops all capture for the window (HOST_LOAD_POLICY, training window). Not usable for a daily blind lane. |
| `WeatherNightlyRetrainValidatePromote` (`scripts/ops/register_nightly_retrain.ps1`) | `expected_disabled: true` (`config/scheduled_tasks.json:283-291`) | Would, via `nightly_retrain` | No | The registrar **throws before registering** (`register_nightly_retrain.ps1:173-182`): no lease-owning wrapper exists. |
| Manual tools: `scripts/ops/chain_recovery_run.ps1`, `scripts/ops/settlement_backfill_one.ps1` | no registrar, no task row | Only if an operator resumes at or before `daily_learning` | Same | 00:30-09:00 only, with the lease (`chain_recovery_run.ps1:135-142,218-248`). |

Not runners:
- `scripts/ops/health_watchdog.ps1:272-275` only **demotes** two staleness-sweep findings to MEDIUM.
- `scripts/ops/staleness_sweep.ps1:237-240` checks only file age.

**Confirmed: none of the Ready tasks runs either step.** This holds for the repository's intended state. The
live Scheduler state is host-only; verify it there with `Get-ScheduledTask`.

Correction to the brief: the settlement stage ends at `physical_feature_family_ratchet` (`reg:250`), not
`fleet_observability`. The stale-lock repair's resume fallback in `cli:1007-1011,1037-1040` still treats
`fleet_observability` as the settlement terminal. That latent inconsistency is noted, not fixed here.

## 2. What enabling Stage B would do each night

**Envelope.**
- **Trigger and teardown:** one 00:35 trigger (`register_daily_refresh.ps1:22-23,179`). The wrapper refuses
  outside 00:30-09:00 and tears the child tree down at 09:00 (`daily_refresh.ps1:103-109,127-145`).
- **Time limits:**
  - child SLA: 28,800 s, ending 08:35 (`daily_refresh_contract.ps1:124-126`)
  - Scheduler limit: `PT8H40M`, ending 09:15 (`register_daily_refresh.ps1:184,213`)
  - no `StartWhenAvailable` (`:181-187`)
  - this leaves 15 minutes before the 09:30 Stage-A exception
    ([HOST_LOAD_POLICY](HOST_LOAD_POLICY.md), Stage B paragraph)
- **Lease:**
  - Taken once, non-blocking (`WaitOne(0)`, `scripts/ops/workload_admission.ps1:1808`), and held until the
    child ends.
  - `quiet_window_merge.ps1:3281-3285` fails when the lease is busy, and so do integration suites, the C
    cutover (G5 in [the host Python runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md) requires Stage B disabled),
    U6 at 04:10, tiering at 05:00/06:00 and the cold-snapshot nightly at 06:50
    ([cold snapshot compression](cold-snapshot-compression.md), "Morning lease contention").
- **Conflict:** an enabled Stage B is therefore **incompatible with every merge night and every C night**
  unless it is disabled for that night.

**Admission on the capture host.**
- `DAILY_HEAVY_STEPS = {promotion_refresh, active_variant_shadow}` (`dr:123`) must pass the
  capture-resource gate (`dr:1290-1345`).
- The default mode is `live` (`cli:177-184`). In `live` mode an active capture loop is a blocker
  (`src/weather/operations/capture_resource_gate.py:394-403`), and capture runs 24/7. So both steps are
  **DEFERRED** every night, and the evidence manifest is `INCOMPLETE` (`sm:126-138`).
- `promotion_refresh` is also skipped as BLOCKED whenever Stage A's promotion lane or barrier blocked
  (`sm:264-283`, `dr:1254-1278`).

**Steps** (`reg:49-73`; runners in `src/weather/operations/daily_refresh_steps.py:128-152`):

| Step | Writes / mutates | Heavy on the host? |
| --- | --- | --- |
| promotion_refresh (`rs:290`) | `data/backtest` promotion artifacts, including `f_family_promotion_refresh.json` and its allowlist. **No** release-pointer, `artifacts/`, `config/` or registry write (outputs are forced under the backtest root, `src/weather/reporting/promotion/orchestration.py:72-141`). The allowlist **is** read by the legacy market-making runtime (`src/weather/market/mm_policy.py:66,818-858`; `market_making_run.py:1276,1387`). No active task runs that runtime; the maker shadow (`src/weather/market/maker_shadow.py:28-41`) does not import it. | Full corpus replay plus gauntlet (about 3.5 h); 8 h child. DEFERRED on the host. |
| pooled_f_retrain_location_gate, served_distribution_calibration_contract (`gs:62,81`) | Their JSON/MD in backtest | Light (isolated child) |
| shadow_ab_monitor (`rs:609`) | JSON/MD | Light |
| active_variant_shadow (`rs:748`) | Backtest outputs **plus each registry variant's `default_export_path` outside backtest** (`src/weather/reporting/candidate_lifecycle/active_variant_shadow_refresh.py:352,376,424,464`). Reads `config/model_variant_registry.json` but never rewrites it. | Largest heap in the chain. DEFERRED on the host. |
| proper_scoring_reliability_scorecard, frozen_baseline_replay_trend, model_variant_evidence_growth (`rs:826,1179,1288`) | JSON/MD; `frozen_baseline_replay_trend.jsonl` is upserted | Medium. They recompute on a **stale** `active_variant_shadow_long.csv` because of the deferral above. |
| progress_audit, early_hour_positive_daily_first_gate (`rs:1355`, `gs:102`) | JSON/MD | Light-medium |
| disagreement_casebook (`rs:1412`) | JSON/MD | **Full snapshot-tape scan, in-process, no timeout** |
| daily_roll_log_hygiene (`rs:1503`) | Extracts only; no delete or rotate | Light |
| nightly_health_checks (`rs:1552`) | **`data/alerts/<date>/nightly_health*` and `data/alerts/nightly_health_latest.*`** (`src/weather/operations/nightly_health_checks.py:18,322-336`); files only, no notification | Light |
| data_layer_audit, snapshot_evaluation, distribution_stage_attribution (`rs:1589,1617,1644`) | JSON/MD | **Full-corpus scans** |
| settled_day_root_cause, winner_rank_parity, june23_location_bias_repair (`rs:1676,1713,1759`) | JSON/MD | Medium |
| data_retention_inventory (`rs:1807`) | JSON/MD (read-only `os.walk` of `data/`) | Heavy I/O |
| daily_learning, weather_only_model_proof_packet, market_benchmark_residual_edge, market_beating_objective_scoreboard, daily_flow_analysis (`rs:1849`, `gs:119,144`, `rs:1905,1938`) | JSON/MD; `daily_flow_analysis_decision_history.jsonl` is appended | Light |

**After the loop** (not in a bounded run):
- the read-only production readiness gate (it BLOCKs if the release pointer changed during the run)
- the daily progress ledger append (`dr:1680-1693`)
- the Stage-B manifest (`dr:1704`)

**Served-state verdict:** Stage B promotes nothing and activates no release.
- It changes only `data/backtest` and `data/alerts`, plus registry export paths if `active_variant_shadow`
  ever runs.
- Its one serving-adjacent output is the dormant market-making allowlist.
- Its cost is lease time, not served state.

## 3. The narrowest safe registration

### 3.1 What the scoreboard is

`market_beating_objective_scoreboard` (`src/weather/reporting/market/market_beating_objective_scoreboard.py`):
- **Inputs:** reads six JSONs (`:659-666`): the proof packet, proper scoring, residual edge, winner-rank
  parity, `daily_progress_latest` and trading evidence.
- **Freshness:** checks existence and `schema_version` only (`:96-121`).
- **The one number it uses:** the weather-only minus market-only **Brier** from proper scoring, falling
  back to residual edge (`:205-210`).
- **Writes:** overwrites its JSON/MD (`:846-853`). `daily_learning.write_outputs` also overwrites
  (`src/weather/reporting/daily/daily_learning.py:1946-1951`).

Of its upstreams, only `winner_rank_parity` measures the served model against the market on recent settled
dates: the last 7 days from `snapshots_long` and labels, with hit rate, winner gap and Brier/log-loss
contributions sliced by local hour (`src/weather/reporting/scorecards/winner_rank_parity.py`, step `rs:1713`).
The Brier pair comes from `active_variant_shadow_long.csv`, which the host cannot refresh (§2).

`daily_learning`:
- treats `f_family_promotion_refresh.json` as a critical input with an 18-hour freshness test
  (`src/weather/reporting/daily/daily_learning_scorecard.py:41,128-138,877-964`)
- so on the host it will report that input STALE
- it still writes its file

### 3.2 `WeatherLearningTailBlind` (if the owner wants it for Q-11)

**Mechanism.** Existing CLI flags, no Python change:

```
python -m weather.operations.daily_refresh run
  --resume-from-step winner_rank_parity
  --stop-after-step market_beating_objective_scoreboard
  --skip-june23-location-bias-repair --skip-data-retention-inventory
  --settled-analysis-target-date <Stage-A target>
  --status-out <seeded copy> --report-out <vault report>
```

- `--stop-after-step` makes this a bounded run: no ledger, manifest, readiness gate or trigger
  (`cli:266-274`, `src/weather/operations/daily_refresh_bounded.py:46-108`).
- `--stage` stays `all`.
- With stage `all`, `--resume-from-step` carries every prior step before the resume point **from the file at
  `--status-out`** (`dr:1153-1198`, `lanes:69-125`). That is how the learning gate sees the Stage-A barrier.

**Why the existing wrapper is not enough.**
- `chain_recovery_run.ps1 -StopAfter` writes to a **fresh** status file (`:75-84`), so nothing is carried and
  every learning step returns `BLOCK settlement_truth_not_ready`.
- The run step still records `ok` (`src/weather/operations/daily_refresh_status.py:36-37`), so the bounded
  receipt says PASS while nothing was written.
- A bounded `--stage evidence` run raises instead (`daily_refresh_bounded.py:36-43`), because a fresh status
  can never match the Stage-A binding.
- The fix is to seed the status file from Stage A's `data/backtest/daily_refresh_status.json`. Stage A
  writes it with the default `--status-out` (`dr:119`, `daily_refresh_contract.ps1:94-117`). The seed is a
  copy, never the original.

**Code to add** (describe only):

1. `scripts/ops/chain_recovery_run.ps1`:
   - add `-SeedStatusPath`: copy the file to `$refreshStatus` before the run, refusing unless `terminal`,
     `config.stage == settlement`, `config.settled_analysis_target_date == -TargetDate`, and a
     `settled_day_analysis_barrier` step is present
   - add `-HardStopLocal` (default 09:00; it may only be earlier) in place of the fixed 09:00 (`:142`)
   - add `-SkipStep <name[]>`, mapped to the existing `--skip-*` flags
2. New `scripts/ops/learning_tail_blind.ps1`:
   - **Target:** Toronto today minus 2 days. That is Stage A's target from the previous morning, the same
     rule Stage B uses (`sm:82-85`). Refuse unless Stage A's status matches it.
   - **Stage B overlap:** refuse when the Stage-B manifest is already `COMPLETED` for the target.
   - **Pre-run snapshot:** copy the 12 output files (§4) into `data/backtest/embargo_vault/_prerun/<stamp>/`.
   - **Run:** call `chain_recovery_run.ps1` with `-ResumeFrom winner_rank_parity`,
     `-StopAfter market_beating_objective_scoreboard`, the seed, `-HardStopLocal 00:55` and the two skips.
   - **Verify:** check from the bounded status, outcome-free, that `daily_learning` and the scoreboard
     results do not have `reason == settlement_truth_not_ready` and that their files' mtime is newer than
     the start.
   - **Vault:** copy the new outputs and the bounded status/report into
     `data/backtest/embargo_vault/learning_tail/<target>/`, with a SHA-256 manifest.
   - **Restore:** in `finally`, put the pre-run copies back.
   - **Recovery:** a leftover `_prerun` directory, for example after a Scheduler kill, makes the next run
     restore first and refuse.
3. New `scripts/ops/register_learning_tail_blind.ps1`:
   - S4U/Limited
   - `ValidateSet("00:35")`
   - `ExecutionTimeLimit PT25M` (kill by 01:00)
   - `MultipleInstances IgnoreNew`
   - no `StartWhenAvailable`
   - `-Enable` switch; registered Disabled by default
4. Repository bookkeeping:
   - a `config/scheduled_tasks.json` row
   - `status.ps1`: expected non-zero codes and a vault-age check that reads mtime only
   - an [OPERATIONS_DESIGN](OPERATIONS_DESIGN.md) row
   - a C2 aux-list entry in the [host Python runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md)
   - wrapper tests: seed refusal, restore after kill, vault manifest, deadline

**Schedule: 00:35, hard stop 00:55, Scheduler limit PT25M (01:00).**
- The night has no other free lease slot:
  - 01:00-04:00 is merges
  - 04:10 is U6
  - 04:45-06:45 is tiering
  - about 06:50-08:50 is the cold-snapshot nightly
  - 09:30-11:55 is Stage A only
- 00:35 is Stage B's own unused slot. If Stage B is ever enabled, this task refuses on the busy lease
  (exit 3). Never enable both.
- The 00:55 stop keeps it out of the 01:00 merge window and ahead of the C cutover's 01:15 latest lease.
- It must still be **disabled on C nights** (G5: no other lease user) and on any night whose integration
  suite trigger is before 01:00. The night plan either puts the suite at 01:00 or later, or disables this
  task. A suite due at 00:40 would otherwise find the lease busy.
- The runtime of the seven-step tail is **unknown**: no outcome data was read and no timing exists since
  07-10. The first night is the measurement. An overrun is torn down at 00:55, the files are restored and
  the night is lost.

**Lease.**
- `chain_recovery_run.ps1` acquires the shared lease itself, or inherits it only from a proven ancestor
  (`:218-248`).
- It is non-blocking: if busy, exit 3 and no retry that night.
- It also requires the canonical stale-lock repair to find no live `daily_refresh.lock` or long-job owner
  (`:255-309`).

**Fails closed.** In every case below, nothing new stays in `data/backtest`:

| Condition | Exit |
| --- | --- |
| Outside 00:30-00:55 | 2 |
| Lease busy or live lock found | 3 |
| Stage-A status missing, not terminal, not settlement, wrong target or no barrier step | refuse before Python |
| Stage-B already completed for the target | skip, 0 |
| Barrier not `PASS` | outputs not written; receipt `BARRIER_BLOCK`; exit 2, declared expected in `status.ps1` |
| 00:55 deadline | 75, restore |
| Vault write failure | 1, restore |
| Leftover `_prerun` | restore, then refuse |

The task promotes nothing: none of the seven steps writes outside `data/backtest` (§2 table).

### 3.3 Rejected alternatives

| Alternative | Why rejected |
| --- | --- |
| Enable Stage B | §2 |
| Training window | Stops capture; runs no scoreboard |
| Append the tail inside Stage A's 09:30-11:55 exception | Needs the Stage-A contract to change. Stage A already reaches the 11:55 teardown (`0x4B` is an expected result, `config/scheduled_tasks.json:93-96`). It would also push heavy work closer to the graded window. That is an owner decision, not a narrow registration. |

## 4. Embargo: outputs written for 10-16..11-13, read nothing until 11-13

Automatic surfaces that would expose new learning-lane content (owner 10-17: descriptive reads refused):
- **Stage A's ledger row and report:**
  - the row copies `daily_learning_status` and the scoreboard's status, first blocker and lane statuses
    (`daily_progress_ledger.py:420-434,556,671-673`)
  - Stage A writes the row daily, as do `daily_progress_latest.json` and `daily_refresh_report.md`
    (`src/weather/operations/daily_refresh_report.py:654-667`)
- **Rollup freshness:** it copies `daily_learning.json`'s top-level status word into Stage A's status
  (`src/weather/reporting/daily/daily_rollup_freshness.py:24-25,103-118`). `status.ps1` and the
  15-minute watchdog read that status file and `MORNING_BRIEFING.md`.
- **Stage B's own surfaces:**
  - `status.ps1` reads only Stage A's status file
  - but Stage B writes `data/alerts/nightly_health_latest.*` and the ledger
- **Nightly retrain** reads `daily_learning.json` (`nightly_retrain.py:1550,2523`). It is disabled.

**Mtime-only surfaces** (not a read): `staleness_sweep.ps1:237-240` and its relays.
**Human-only surfaces:** `ops_monitor.py`, `runtime_monitor.py` and `production_evidence_ledgers.py`.
No Streamlit view, notification or network surface reads these files.

**Suppression** is the vault-and-restore in §3.2:
- `data/backtest` keeps its pre-run copies, so every automatic surface stays byte-identical to today.
- That includes the standing 07-10 staleness finding, which the watchdog demotes.
- The per-date vault is the only place the content exists, and it **accrues** one copy per target date.

**Files covered by vault-and-restore:**
- `winner_rank_parity.json/.md`
- `daily_learning.json`, `daily_learning_report.md`
- `weather_only_model_proof_packet.json/_report.md`
- `market_benchmark_residual_edge.json/.md`
- `market_beating_objective_scoreboard.json/.md`

**Agent rules:**
- No agent opens `data/backtest/embargo_vault/` before 11-13.
- `status.ps1` may report only the vault's file count and mtime.
- On or after 11-13, re-register without the vault, or read the vault under the panel's normal close
  process.

## 5. Registration notes for the SD-1 head (ready to paste)

```text
Registration notes — lever 2 / Q-11 (from docs/operations/lever2-learning-registration-proposal-2026-10-20.md)
- SD-1 registers NO task and changes NO task. WeatherDailySettlementPromotionRefresh (Stage A) keeps its
  action; WeatherEveningEvidenceRefresh (Stage B) STAYS DISABLED (do not pass -EnableEvidenceTask).
- Effect after landing: an undecided SOURCE_DISAGREEMENT on the Stage-A target defers (non-countable)
  instead of blocking settlement_source_audit, so the settled-day barrier's learning_status can be PASS
  (still BLOCK on a confirmed mismatch or other settlement-truth blocker; DIAGNOSTIC_ONLY still blocks
  learning). The ledger row gains the blocker class.
- SD-1 alone does NOT make daily_learning or the scoreboard run: no Ready task reaches them (proposal §1).
- The only proposed runner is WeatherLearningTailBlind (proposal §3.2): a separate head, .ps1/config only,
  owner yes required, 00:35 with a 00:55 hard stop, shared lease non-blocking, disabled on C nights and on
  nights with an integration suite before 01:00; outputs go to data/backtest/embargo_vault/learning_tail/<target>/
  with data/backtest restored, so no automatic surface shows 10-16..11-13 content.
- Exhaustion-register order 1 does not depend on this task: its per-block served/market tracker is a
  workstation analysis over captured snapshots and labels after 11-13; it needs SD-1 countability and LB-5.
- Verify after landing (outcome-free): Stage-A ledger row for the next target carries the blocker class
  field; do not count PASS/BLOCK days for 10-16..11-13 until the owner confirms that count is allowed.
```

## Open boundary question

Is the barrier PASS/BLOCK count for 10-16..11-13 an allowed "outcome-free coverage count"? It describes
settlement-source agreement, not forecasts or prices, but it is a descriptive count over embargoed dates.
This proposal assumes **no** until the owner says yes.
