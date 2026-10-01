# Agent report 2026-10-01: Stage B non-colliding trigger

**Verdict: IMPLEMENTED, NOT REGISTERED.** `WeatherEveningEvidenceRefresh` (Stage B) now has one 05:00
trigger, after every recurring overnight lease holder's hard end. The registrar refuses before registering
anything while an enabled lease holder's scheduled window overlaps 05:00-09:15. The wrapper waits at most
240 s for the shared lease, then refuses with exit 76; it never preempts a holder. Nothing was registered,
enabled, merged or run on production. **Enabling Stage B is still blocked by more than the trigger** (see
"Still blocking enablement").

Branch `codex/stage-b-trigger-20261001`, workstation mission from the owner's prompt (no handoff file).

## Diagnosis confirmed

- The old trigger was a `ValidateSet("00:35")` literal. `WeatherColdSnapshotNightly` starts at 00:30 with
  `PT4H15M` and an absolute 04:45 teardown in `cold_snapshot_nightly_run.ps1`, and it holds the shared lease
  through its compression child. Stage B called the non-blocking `Enter-WeatherHeavyWorkloadLease`
  (`WaitOne(0)`) at 00:35, got `$null` and exited 76 every night it ran.
- Only waiting for the lease was not enough. Producer provenance rejects a delegated child that starts more
  than `--scheduler-correlation-seconds 300` after the task's `LastRunTime`
  (`scheduler_run_correlation_stale` / `scheduler_child_parent_start_correlation_stale` in
  `producer_provenance.py`). A 00:35 trigger that waited hours for the nightly would produce evidence that
  cannot be counted. Waiting from 00:35 would also take the lease the moment the nightly finished early,
  which starves the 01:00-04:00 quiet-window merges.

## Design

Every value lives in one place, `Get-DailyRefreshEvidenceSchedule` in `scripts/ops/daily_refresh_contract.ps1`.
The registrar, the wrapper and the child token builder all read it.

| Element | Old | New |
| --- | --- | --- |
| Trigger | 00:35 | **05:00** |
| Child SLA (`--producer-sla-seconds`) | 28800 (to 08:35) | 12900 (to 08:35) |
| Wrapper teardown | 09:00 | 09:00 (unchanged) |
| Scheduler limit | `PT8H40M` (to 09:15) | `PT4H15M` (to 09:15) |
| Lease acquisition | one immediate attempt | retry every 15 s for at most 240 s (inside the 300 s correlation) |
| Composition | 28800 < 30300 < 31200 | 12900 + 240 < 14400 < 15300, checked by the registrar |

Why 05:00 clears everything:

- Cold-snapshot nightly: 00:30 + `PT4H15M` = 04:45, the same as its in-script hard stop.
- Training window: a one-shot with `PT3H45M`; the default 01:00 start ends at 04:45. The restore runs at
  04:15 + `PT15M` = 04:30.
- Quiet-window merges end by 04:00.
- Stage B's target date does not move. `_expected_overnight_stage_a_target` = local today − 2 days, the
  same for any start from 00:00 to 09:00, so Stage B still binds the previous morning's Stage-A manifest.

The registration guard (`Get-DailyRefreshEvidenceTriggerCollisions`) collects every enabled trigger of
`WeatherColdSnapshotNightly`, `WeatherTrainingWindow`, `WeatherNightlyRetrainValidatePromote`,
`WeatherIntegrationSuite_*` and `WeatherIntegrationMerge_*`. It refuses on any clock overlap between
`[start, start + task limit)` and `[05:00, 09:15)`, including windows that wrap past midnight.

- One-shots whose start has already passed are ignored.
- A holder with no fixed clock window (a boot, logon or repeating trigger, or a zero or empty limit) counts
  as overlapping.
- Wall clocks are compared as registered, so a DST offset conversion cannot skew only one side.
- Practical effect: registration refuses on a night with a pending integration attempt, whose suite has
  `PT8H`. Register on a night without one.

## Why Stage A's in-chain learning steps report GAPPED

This is **correct fail-closed behavior, not a bug**. The chain is:

1. `settled_day_analysis_barrier` sets `learning_status` to `DIAGNOSTIC_ONLY` when its settlement-truth
   steps have no blocker but `_label_countability_from_freshness` finds that **at least one** settled label
   for the target date is not promotion-countable. That covers material-coverage-blocked labels and, without
   material grades, `quality_grade=partial` (`daily_refresh_settled_day.py`, around lines 237-340 and 457-462).
2. `settlement_barrier_blocker(..., learning_only=True)` accepts only `PASS`, so `DIAGNOSTIC_ONLY` is a
   blocker. `chain_target_settlement_coverage` then records `coverage_status=GAPPED`,
   `gap_reason=settlement_barrier_not_passing` (`daily_refresh_lanes.py`, around lines 320-368).
3. Each learning step inherits the chain gap (`basis=chain_gap`). The steps still run and produce
   diagnostics, but the target day is recorded as a gap, not as learning coverage.

This matches the standing rules. Partial or non-countable settlement days are coverage exclusions, not
zeros, and a gate that refuses is usually right. It is also consistent with the two power-loss days
(09-29, 09-30), whose capture gaps make material-coverage-blocked labels likely. The barrier JSON
(`json_out`, `material_coverage_blocked_sample`) on production names the exact labels; I did not read
production data.

Two consequences for the owner:

- **Re-enabling Stage B does not make learning countable on those days.** `_stage_b_start_gate` copies Stage
  A's `target_settlement_coverage` into Stage B as `learning_mode`, so Stage B's `daily_learning` and
  scoreboard gap the same way.
- The rule is all-or-nothing per day: one non-countable label gaps that day's learning for every market.
  Changing that to per-market exclusion would relax a learning gate. That is an owner design decision, and I
  did not change it.

## Still blocking enablement (not changed here)

- **Monolithic-memory hold.** OPERATIONS_DESIGN keeps Stage B disabled until the evidence workload is chunked
  and representative resource receipts pass the host-load contract. This is the 2026-08-13 incident: an
  orphaned evidence child exhausted commit in the graded window, and `memory_commit_guard.ps1` still carries
  its kill rule. A collision-free trigger does not lift that hold.
- **Runtime budget is unmeasured.** The child now has 3h35m instead of 8h. No Stage B duration receipt
  exists since it has not run since 08-13. The first enabled run should be read for its SLA field. The
  09:00 teardown is unchanged, so an overrun is stopped, not carried into Stage A.

## Per-file roll verdict

All changed files are `.ps1`, Markdown under `docs/`, or tests. Expected **roll-free**; production must
confirm with `scripts\ops\roll_verdict.ps1 -Branch codex/stage-b-trigger-20261001`.

- `scripts/ops/daily_refresh_contract.ps1`: schedule contract, collision check, bounded lease wait, SLA
  token.
- `scripts/ops/daily_refresh.ps1`: evidence-stage bounded lease wait.
- `scripts/ops/register_daily_refresh.ps1`: 05:00 / `PT4H15M`, composition check, pre-registration overlap
  refusal.
- `docs/operations/OPERATIONS_DESIGN.md` and `docs/operations/HOST_LOAD_POLICY.md`: owning text updated.
- `tests/operations/test_daily_refresh_script.py` (updated) and
  `tests/operations/test_daily_refresh_evidence_trigger.py` (new).

## What was NOT done

No scheduled task was registered, changed, enabled or disabled. Nothing was written to production `data/`,
no loop was restarted, nothing was merged to `master`, and no production data was read. Local Task
Scheduler was only read to smoke-test trigger parsing. `STATE_OF_PLAY.md` is left for the production agent.

## Production registration (after merge; run from the production repo root)

The registrar re-registers **both** tasks, so it must re-pass the parameter set Stage A carries today. Run it
outside 09:30-11:55 (Stage A's run) and on a night with no pending integration attempt. First, read-only:

```powershell
(Get-ScheduledTask -TaskName WeatherDailySettlementPromotionRefresh).Actions[0].Arguments -match '-ProvenanceOnly'
```

If that prints `True`, run this. It leaves Stage B **disabled**:

```powershell
.\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly
```

If it prints `False`, Stage A carries the Full contract. Re-pass the same `-CapturedInputParityServed`,
`-CapturedInputParityReplay`, `-ProductionReadinessServedArtifact` and `-ProductionReadinessServedRoute`
values. They are base64 JSON inside `-ProductionEvidenceArgumentsB64` in the same Arguments string.

Verify afterwards: `Get-ScheduledTask WeatherEveningEvidenceRefresh` shows `Disabled`, trigger 05:00 and
`PT4H15M`. The registrar already reads all three back and throws on drift.

Enabling is a separate owner decision after the memory hold is lifted. The command is the same one plus
`-EnableEvidenceTask`.

## Reproduction (workstation)

```powershell
.\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath <abs venv python> -RepoRoot <abs repo> `
  -ArgumentsBase64 <base64 of ["-m","pytest","-q","--basetemp",<tmp>,
    "tests/operations/test_daily_refresh_evidence_trigger.py","tests/operations/test_daily_refresh_script.py",
    "tests/operations/test_agent_docs_audit.py","tests/operations/test_import_architecture.py",
    "tests/operations/test_module_size_audit.py","tests/operations/test_path_policy.py",
    "tests/operations/test_schema_registry.py","tests/operations/test_operating_reference.py",
    "tests/operations/test_producer_provenance.py","tests/operations/test_memory_commit_guard_script.py"]>
```

Workstation result: 125 passed (the list above plus `tests/reporting/test_roadmap_backlog.py`).
`agent_docs_audit` PASS. On the capture host, run only through the bounded suite in its window.
