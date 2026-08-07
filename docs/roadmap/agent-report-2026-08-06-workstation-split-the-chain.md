# Workstation report 2026-08-06 — split the chain into promotion and learning lanes

**GO — the chain now fails promotion closed while continuing independent learning with explicit target-day coverage and staleness. P0 found that only two of the 23 post-barrier steps consume target-day truth as a correctness requirement; the other 21 can operate on the last-settled corpus. P1 was an unreached step, not a silent writer or an alternate path. One bounded NO-GO remains: do not claim that the prior-run `daily_learning.json` and `data_layer_audit.json` inputs already consumed by promotion are current-run, target-bound receipts. That pre-existing dependency lag is documented, not weakened or disguised.**

## Scope and guardrails

This report answers `workstation-handoff-2026-09-29a-split-the-chain-into-promotion-and-learning.md`. The reserved-confirmation-window source was checked at execution time: no dates are currently reserved; the reservation is armed but undated. No candidate was fitted, frozen, scored, or promoted.

The production incident facts below come from the handoff and are not re-measured from the lagging workstation mirror. Code-structure findings, local retained-state diagnostics, and test results were measured on this branch.

## P0 — consumer trace and cheapest falsifier

The canonical registry contains 44 steps. `settled_day_analysis_barrier` is step 21 (one-indexed), leaving 23 steps after it. A source-and-consumer trace found:

| Post-barrier class | Steps | Target-day settlement requirement | Disposition |
| --- | ---: | --- | --- |
| Promotion consumers | 2 | `live_variant_settlement_scorecard` needs target-day settlement; `promotion_refresh` consumes its current-run receipt and the other declared promotion receipts | Promotion lane; fail closed |
| Evidence and learning | 21 | Can use the last-settled corpus, or are operational/not settlement-applicable | Learning lane; continue and emit coverage/gap metadata |

The mission premise therefore survived its falsifier. Most post-barrier work does not require the target day to be settled for correctness. The lane split is preferable to globally stopping all 23 steps.

Execution lane and promotion-receipt gating are deliberately separate axes beside the registry. Eight current-run receipts gate promotion: `ingest_quality_gate`, `hourly_model_performance`, `ten_minute_model_performance`, `settled_day_analysis_barrier`, `runtime_identity_reconciliation`, `live_variant_settlement_scorecard`, `fleet_observability`, and `promotion_refresh`. Missing, malformed, skipped, errored, target-mismatched, or vacuous positive-count receipts fail closed. A current-model `BLOCK` from hourly or ten-minute scoring may reach only the existing canonical candidate-mitigation path; it is not converted to a pass.

## Incident support and interval treatment

The descriptive crossed date × market unit is the market-day. The handoff supplies two production incidents:

| Incident / affected target date | Date clusters | Market clusters in that date | Market-days | Observed chain effect |
| --- | ---: | ---: | ---: | --- |
| 2026-07-27 | 1 | 1 | 1 | One transient WU timeout stopped at step 20 of 43; 23 downstream steps were lost |
| 2026-08-06 / target 2026-08-05 | 1 | 12 | 12 | Twelve WU 404s inside eight minutes blocked the barrier and left the fleet target unsettled |

Across the supplied incidents there are 2 date clusters and 13 observed market-days. The number of distinct market clusters across both dates is not asserted because the handoff does not enumerate the 12-market fleet. These are deterministic incident counts and control-flow observations, not a sampled effect estimate, so no confidence interval, bootstrap, or inferential interval is applicable. The required crossed date × market treatment is the explicit reporting unit; no rows or stations are treated as independent replicates.

## P1 — why `daily_learning` stopped rolling up

Verdict: **NOT RUNNING / UNREACHED**.

- The local retained artifact `data/backtest/daily_learning.json` and its rendered report both last wrote at `2026-07-10T04:01:48Z`; no alternate copy exists below local `data/`.
- The only writer is the registered `run_daily_learning_step` route to `backtest_path(args, "daily_learning.json")`, and it writes unconditionally once reached. This rejects the wrong-path and silent-writer hypotheses.
- Commit `28c40a7e5241426e49c3e403c236c1815609ed6a` made `promotion_refresh` and `active_variant_shadow` heavy steps. `promotion_refresh` was the first evidence-stage step, and a heavy preflight deferral broke the stage before `daily_learning`. Barrier and earlier-stage exits had the same reachability effect.
- The local progress ledger has 28 rows from `2026-07-07T05:41:58Z` through `2026-08-05T13:49:03Z`; its repeated `daily_learning_status=BLOCKED` values are reads of the stale artifact, not receipts proving that the step ran.
- The retained settlement manifest stops after seven steps at deferred `taker_finalization_watchdog`. The retained evidence manifest stops after 25 steps at deferred `capture_resource_admission`, before both `promotion_refresh` and `daily_learning`.

The P1 finding was established before the repair. The split addresses the daily-refresh reachability failure: a promotion blocker or heavy-step deferral no longer suppresses lightweight learning. Global physical-resource admission and isolated-orchestration failures still stop execution because continuing would be unsafe or invalid.

## Implemented behavior

- Every step declares an execution lane adjacent to the canonical registry; tests fail if a step lacks a lane or learning coverage mode.
- Barrier failures and promotion-lane errors become explicit promotion blockers. Independent evidence and learning continue on the last-settled corpus.
- Learning steps emit `coverage_mode`, target date, covered date bounds, corpus maximum date, included-market/date counts where available, staleness in days, and gap reason. Dependency-derived coverage propagates the weakest named input. Operational steps declare coverage not applicable rather than inventing completeness.
- `daily_learning.json` receives its coverage envelope before the report is written. The lane rollup exposes the weakest coverage date and maximum staleness.
- Heavy promotion/shadow deferral produces explicit deferred rows but permits lightweight learning to continue. An explicitly skipped active shadow bypasses heavy preflight.
- The evidence-stage manifest is bound to the exact settlement-stage run ID and target. A repaired settlement stage reruns evidence for that target. A target or Stage-A binding mismatch rejects stale tail-only resume; incomplete evidence remains retryable. A completed evidence-stage fallback preserves the prior successful canonical result.
- Production readiness does not run when the promotion lane is blocked, and the final report names the exact upstream blocker.
- The operations design, SOP, and module-ownership map describe the lane contract and the extracted `daily_refresh_lanes.py` owner.

### Bounded residual limitation

The existing promotion adapter also reads prior `data_layer_audit.json` and `daily_learning.json` artifacts. Their producers run after promotion, and `daily_learning` itself consumes promotion output, so making them same-run prerequisites would create the existing dependency cycle. This branch does not pretend those artifacts are current-run receipts and does not relax their gate semantics. A later design may version and bind prior-run inputs explicitly, but that is outside this mission.

## Verification

| Check | Result |
| --- | --- |
| Daily-refresh plus module-size focused tests | 143 passed, 13 subtests passed |
| Daily-learning tests | 55 passed |
| Import/path/module/release/app architecture tests | 31 passed |
| Compile check | Passed for `app`, `src`, and `tests` |
| Full repository suite | 3,309 passed, 4 skipped, 18 failed, 829 subtests passed |

The full-suite failures match pre-existing environment/baseline classes: one unrelated broken documentation link, four Windows PowerShell execution-policy tests, and 13 Windows temporary-path/path-length experiment-executor tests. No new failure class appeared. Post-rebase focused architecture and daily-learning checks remained green.

`weather.operations.agent_docs_audit` continues to report the pre-existing unrelated missing target `../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079` from `docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md`.

## Per-file roll verdict

The retained `runtime_identity.source_scope_files` closures were read directly; `SOURCE_PATTERNS` was not used. Closure captures were:

- snapshot: `2026-08-06T05:00:19.307557Z`, 77 files
- CLOB: `2026-08-06T05:00:12.462452Z`, 23 files
- observation trigger: `2026-08-06T08:29:44.575019Z`, 85 files
- CLOB enrichment: `2026-07-27T13:51:33.280915Z`, 21 files

| Changed file | Snapshot | CLOB | Observation | CLOB enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/operations/OPERATIONS_DESIGN.md` | No | No | No | No | Roll-free |
| `docs/operations/PROJECT_OPERATING_SOP.md` | No | No | No | No | Roll-free |
| `docs/operations/module-ownership-map.md` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh.py` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh_lanes.py` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh_registry.py` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh_report.py` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh_reporting_steps.py` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh_source_steps.py` | No | No | No | No | Roll-free |
| `src/weather/operations/daily_refresh_steps.py` | No | No | No | No | Roll-free |
| `tests/operations/test_daily_refresh.py` | No | No | No | No | Roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-split-the-chain.md` | No | No | No | No | Roll-free |

No changed file enters any retained capture closure. This verdict governs a later production merge; it does not claim that the workstation commit or push can restart capture.

## What was not done

- No chain step was registered; the existing 44 steps were classified and a seam remains for the separately owned feature-coverage gate.
- No registration or scheduled-task mutation was performed.
- No production state or workstation-mirror `data/` state was written.
- No loop was started, stopped, or restarted.
- Nothing was merged and no pull request was opened.
- No promotion gate was relaxed; no candidate was produced or promoted.
- The concurrently owned model-feature, free-source-parity, retrain, source-gate, and recovery-script files were not changed.

## Exact reproduction commands

Run from the repository root on the production host with its canonical interpreter:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_daily_refresh.py
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_module_size_audit.py tests\reporting\test_daily_learning.py
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_import_architecture.py tests\operations\test_path_policy.py tests\operations\test_module_size_audit.py tests\operations\test_release_import_boundary.py tests\app\test_app_architecture.py
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m pytest -q
```

Read-only roll recheck, using the host's retained status files rather than a source glob:

```powershell
$changed = git diff --name-only origin/master...origin/codex/workstation-split-the-chain-2026-09-29a
$statusFiles = @(
  'data/snapshots/loop_status.json',
  'data/snapshots/clob_loop_status.json',
  'data/snapshots/observation_trigger_status.json',
  'data/snapshots/clob_enrichment_status.json'
)
foreach ($statusFile in $statusFiles) {
  $closure = @((Get-Content -Raw $statusFile | ConvertFrom-Json).runtime_identity.source_scope_files)
  [pscustomobject]@{
    status_file = $statusFile
    changed_files_in_closure = @($changed | Where-Object { $closure -contains $_ })
  }
}
```

## Commit and branch

- Implementation commit: `8ae1f427e86efa503beea143341431ab9d43f7c5`
- Branch: `codex/workstation-split-the-chain-2026-09-29a`
