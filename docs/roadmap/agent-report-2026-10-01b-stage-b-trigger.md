# Agent report 2026-10-01b: Stage B trigger, review fix

**Verdict: REVISED, NOT REGISTERED. Stage B moves to 06:45. Lease holders are now derived from source, not
from a hand list.** This report answers the production review of PR #153. It supersedes the schedule and
guard sections of [agent-report-2026-10-01-stage-b-trigger.md](agent-report-2026-10-01-stage-b-trigger.md).
That report's GAPPED analysis and its "still blocking enablement" section stand. Nothing was registered,
enabled, merged or run on production, and no production data was read.

## The review finding was right

`WeatherClobTiering` (05:00, `PT31M`, 1800 s child bound) and `WeatherClobRawTapeTiering` (06:00, `PT41M`,
2400 s bound) both take the shared lease. On a busy lease they write `SKIPPED_WORKLOAD_LEASE_BUSY` and exit 0
(`clob_tiering_run.ps1` lines 105-109; `clob_raw_tape_tiering_run.ps1` around line 100). A 05:00 Stage B
would therefore have stopped both every day while their tasks reported success. The hand list missed them,
and it would have missed the storage-recovery night too, which launches the compression run from Python.

## Fix 1: holders derived from source

`Get-WeatherSharedLeaseEntryPoints` in `scripts/ops/daily_refresh_contract.ps1` derives the set:

- **Seed:** every `scripts/ops/*.ps1` with a non-comment call to `Enter-WeatherHeavyWorkloadLease`.
- **Closure:** anything that launches a holder, transitively. A launch is:
  - a quoted, whitespace-free `.ps1` path literal, such as `'-File', (Join-Path ... 'x.ps1')`;
  - a quoted `'weather.x.y'` module token in a script (`-m`);
  - a module import.

  Python modules count when they name a lease script (for example `storage_recovery_night_steps.py`).
- **Not counted:** comments and prose strings.
- **Reference-only files:** their quoted paths are data, not launches.
  - `status.ps1`
  - `integration_attempt_contract.ps1`
  - `weather.operations.operating_reference`
  - `weather.reporting.serving_gates.registration_parameters`
  - every `register_*.ps1`

The registrar passes **every** scheduled task on the host (`Get-ScheduledTask`, no name filter) to
`Get-DailyRefreshEvidenceLeaseHolders`. A task is a holder when any action names an entry point, either as a
path component or as a `-m` module token. This covers pinned deployment worktrees by file name, plus
host-local tasks that have no repository registrar.

The current derived set has 25 entry points, including both tiering runners, the cold-snapshot nightly,
the training window, the quiet merge, the integration suite and merge, the storage-recovery night (script
and module), chain recovery and the archive and compression runners. The health watchdog, `status.ps1`, the
memory guard and the registrars are excluded.

Tests in `tests/operations/test_daily_refresh_evidence_trigger.py`:

- **Independent re-derivation:** a Python implementation must equal the PowerShell set exactly.
- **Every daily lease-taking registrar:** parses each `-Daily` trigger time and the execution limit that
  follows it. It fails if any window overlaps Stage B, or if a daily trigger cannot be resolved. A new daily
  lease-taking task, or a moved one, fails here.
- **Canary repository:** a new lease script, a script launcher, a Python launcher and a prose-only mention.
  It proves detection needs no list edit and that prose is ignored.
- **Retired triggers:** asserts that the 00:35 and 05:00 triggers collide with the holders they starved.

## Fix 2: the slot

Lease-free windows between 00:30 and 09:00, using each holder's hard bound (Scheduler limit and child
bound):

| Window | Length | Bounded by |
| --- | --- | --- |
| 04:45-05:00 | 15 min | cold-snapshot nightly hard stop; projection tiering start |
| 05:31-06:00 | 29 min | projection tiering `PT31M`; raw-tape tiering start |
| **06:41-09:00** | 2h19m | raw-tape tiering `PT41M`; Stage B teardown |

**06:45** is the only usable slot. Composition: child SLA 6600 s (to 08:35) plus a 240 s lease wait is less
than the 8100 s wrapper span (to 09:00), which is less than the 9000 s `PT2H30M` Scheduler limit (to 09:15).
The 08:35 / 09:00 / 09:15 endpoints and the Stage-A gap are unchanged. Stage B's target date does not
change between 00:00 and 09:00.

## Durations: measured upper bounds, real values needed from production

I did not read production data. Each tiering task's hard bound is in code: projection tiering ends by 05:31
and raw-tape tiering by 06:41. Those bounds are what the slot is built on, so 06:45 is safe whatever the
real durations are. Real durations only show slack, for example whether raw tape could move earlier.

Stage B's own runtime is the open question, because its budget drops from 8 h to 1h50m. The production agent
should run these read-only commands from the production repo root:

```powershell
foreach ($f in 'data\logs\clob_tiering_task_history.jsonl', 'data\logs\clob_raw_tape_tiering_task_history.jsonl') {
    $f; Get-Content -LiteralPath $f -Tail 120 | ForEach-Object { $_ | ConvertFrom-Json } |
        Select-Object local_time, status, duration_seconds, hard_stop_reached, max_runtime_seconds | Format-Table
}
$b = Get-Content -LiteralPath data\backtest\daily_refresh_evidence_status.json -Raw | ConvertFrom-Json
$b.started_at_utc; $b.finished_at_utc; $b.status
$b.steps | Select-Object name, status, duration_seconds | Format-Table
```

Paths needed:

- `data/logs/clob_tiering_task_history.jsonl` and `data/logs/clob_raw_tape_tiering_task_history.jsonl`, for
  the `duration_seconds`, `status`, `hard_stop_reached` and `SKIPPED_WORKLOAD_LEASE_BUSY` rows.
- `data/backtest/daily_refresh_evidence_status.json` and
  `data/backtest/daily_refresh_evidence_learning_manifest.json`, for Stage B's last run (2026-08-13 or
  earlier), steps and durations.
- If Stage B has no retained run: `data/backtest/daily_refresh_status.json` from the last pre-split `all`
  run, for the same 20 step names.

**Decision rule for that measurement:**

- **It fits** if the 20 evidence steps' summed `duration_seconds` from the last representative run is at
  most about 5,900 s, which is 6,600 s with 10% headroom. Enable later as planned.
- **It does not fit** if the sum is larger. Then no single overnight slot can hold it while the nightly and
  tiering keep their times. Stage B would need chunking at step boundaries into two tasks, both inside
  06:45-09:00 or split across nights:
  - **B1, learning lane first:** `promotion_refresh`, `shadow_ab_monitor`, `active_variant_shadow`,
    `proper_scoring_reliability_scorecard`, `data_retention_inventory`, `daily_learning`,
    `market_beating_objective_scoreboard`.
  - **B2, diagnostics:** the audits, attribution and casebook steps, run on alternate nights or after the
    cold-snapshot policy ends (valid to 10-30), which frees 00:30-04:45.

  The memory hold already requires chunking before enablement. This rule sizes the chunks. A timed-out run
  is stopped at 09:00, so an overrun never reaches Stage A.

## Per-file roll verdict

Changed files: `scripts/ops/daily_refresh_contract.ps1` and `scripts/ops/register_daily_refresh.ps1`
(`.ps1`), `docs/operations/OPERATIONS_DESIGN.md` and `docs/operations/HOST_LOAD_POLICY.md`, this report, the
correspondence index, and the two test files. All expected **roll-free**; confirm with
`scripts\ops\roll_verdict.ps1 -Branch codex/stage-b-trigger-20261001`.

## What was NOT done

No registration, enable or disable, and no Scheduler mutation. No production `data/` read or write, no
restart, no merge. The local Task Scheduler was only enumerated read-only to smoke-test the holder
classifier.

## Production registration (after merge)

The commands are unchanged from the first report. The trigger is now 06:45 and the readback checks
`PT2H30M`. Check Stage A's parameter set first:

```powershell
(Get-ScheduledTask -TaskName WeatherDailySettlementPromotionRefresh).Actions[0].Arguments -match '-ProvenanceOnly'
```

If that prints `True`, register with Stage B **disabled**:

```powershell
.\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly
```

If it prints `False`, re-pass Stage A's existing Full evidence parameters. Run it outside 09:30-11:55, on a
night with no pending integration attempt. The registrar refuses on any overlap and names the task.

## Reproduction (workstation)

Run `scripts\ops\workstation_heavy.ps1 -Kind pytest` over these files:

- `tests/operations/test_daily_refresh_evidence_trigger.py`
- `tests/operations/test_daily_refresh_script.py`
- the agent-docs, import-architecture, module-size, path-policy, schema-registry, operating-reference,
  producer-provenance and memory-commit-guard tests
- `tests/reporting/test_roadmap_backlog.py`
