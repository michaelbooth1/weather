# 95c — settlement-valid learning independently of maker readiness

**IMPLEMENTED AND WORKSTATION-VERIFIED: maker/economics blocks no longer prevent
the three learning producers from running on valid settlement inputs. Real
settlement faults still deny them.** Serves Q-11. Production adoption and a
current production run remain separate.

Branch `codex/learning-lane-unblock-20260924`, from the user-requested fetched
handoff tip `69c5a325342b99fa03655883436e169159b7756d`. This overrides the handoff's
default master base; review the mission diff against that exact parent. The
branch does not depend on 95b.

## Dependency change

The retained aggregate barrier and all its readiness dependencies remain.
A second `learning_status` is derived from the settlement subset. Consumers
require that verdict for their exact target date; their own input-quality
checks still apply after admission.

| Consumer | Before | After |
| --- | --- | --- |
| Retention inventory, daily learning, objective scoreboard | Aggregate barrier couples maker/economics readiness into target settlement coverage | Current target-bound settlement verdict only |
| Promotion and live-variant settlement scoring | Aggregate barrier | Same aggregate barrier, including maker/economics gates |
| Learning settlement verdict | No separate value | WU restoration → label finalization; settlement-source audit; observed-floor monitor under its existing policy; replay-status repair; freshness and material countability |
| Scoreboard learning coverage | Proper scoring, winner parity and trading evidence | Proper scoring and winner parity; the scoreboard still reports trading readiness independently |
| Explicit owner-paused maker | Scoring attempts or generic skip | `NOT_APPLICABLE`, `paper_maker_paused`, `counts_toward_maker_readiness=false` |

The pause is explicit via `--paper-maker-paused`, preserved by the barrier's
resume command. It avoids both reading old maker runs and launching a scoring
child. Missing files never imply a pause. No Scheduler state is queried or
changed to infer it. A production adopter must supply the flag for an explicitly
paused maker; without it, the active-maker behavior remains.

A typed aggregate-barrier exception can carry `learning_status=PASS` while
remaining BLOCK for promotion. Generic errors cannot do so. Missing receipts,
wrong dates and old blocked receipts without the new field fail closed until
the barrier reruns. Existing passing legacy receipts remain compatible. The
orchestrator supplies the current carried-forward receipt list to all three
adapters, including resumed Stage B. Failed settlement admission returns a
current BLOCK result without rebuilding the learning artifact; retained older
artifacts are not rewritten or certified as current.

No settlement threshold, trusted floor, harvest-only promotion rule, maker
countability or exchange-readiness gate is relaxed. The existing observed-floor
alert-only default remains; explicit hard-stop floor alerts still deny learning.
Malformed freshness and deferred/stale settlement receipts also remain blocked.

## Verification

Final focused suite: **217 passed and 17 subtests passed in 28.01 seconds**.
Covers real-chain maker BLOCK → three written learning artifacts while promotion
is suppressed; finalize/source-audit/WU/replay failures → no producer artifact;
missing/stale/generic-error receipts; unknown freshness; wrong dates; enforced
floor alerts; explicit paused-maker no-read/no-child; existing resource,
stage/resume, script and architecture checks. These are deterministic fixtures,
not measured production dates or a statistical sample; no intervals claimed.

The first run had 156 passes and three fixture failures: the pause test patched
the wrong imported module, and two direct adapter tests lacked the newly
required settlement receipt. Those fixtures were corrected before the final run.

`compileall -q src/weather tests`, `git diff --check`, the canonical
`agent_docs_audit` and backlog `--fail-on-lint --check` passed. The two canonical
doc entrypoints were invoked from a temporary pytest adapter under the same
workstation wrapper (one passing check); no production command was run.

## Roll and host boundary

`roll_verdict.ps1 -Branch codex/learning-lane-unblock-20260924` returned
**UNDECIDABLE** (exit 1): all four live closure files are absent from this
isolated worktree. The handoff says the registry was in no live capture closure;
that is a handed host-audit fact, not fresh workstation proof. No assertion is
made that its consumers share that finding.

| Changed file | Per-file roll finding |
| --- | --- |
| `src/weather/operations/daily_refresh_registry.py` | Handoff audit: not in live closure; current host verdict still required |
| `src/weather/operations/daily_refresh.py` | Unknown without host closures |
| `src/weather/operations/daily_refresh_cli.py` | Unknown without host closures |
| `src/weather/operations/daily_refresh_lanes.py` | Unknown without host closures |
| `src/weather/operations/daily_refresh_reporting_steps.py` | Unknown without host closures |
| `src/weather/operations/daily_refresh_settled_day.py` | Unknown without host closures |
| `src/weather/operations/daily_refresh_trading_steps.py` | Unknown without host closures |
| All changed tests and docs | Roll-free by contract |

Production must derive the current per-closure verdict before guarded adoption.
No registration, production write, restart, master merge, training, promotion,
credential access or live order was performed. The frozen mirror was not read.

## Reproduction

From this branch's repository root on the workstation:

```powershell
$missionRoot = (Resolve-Path .).Path
$missionGit = (& git rev-parse --path-format=absolute --git-common-dir).Trim()
$missionPython = Join-Path (Split-Path $missionGit -Parent) 'venv/Scripts/python.exe'
$missionArgs = @('-m','pytest','tests/operations/test_learning_lane_unblock.py',
 'tests/operations/test_daily_refresh.py','tests/operations/test_daily_refresh_resources.py',
 'tests/operations/test_daily_refresh_step_child.py','tests/operations/test_daily_refresh_script.py',
 'tests/operations/test_settled_day_freshness.py','tests/operations/test_import_architecture.py',
 '-q',('--basetemp=' + (Join-Path $env:TEMP 'weather-95c-tests')))
$missionEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -Compress -InputObject $missionArgs)))
& ./scripts/ops/workstation_heavy.ps1 -Kind pytest -PythonPath $missionPython -ArgumentsBase64 $missionEncoded -RepoRoot $missionRoot
& ./scripts/ops/roll_verdict.ps1 -Branch origin/codex/learning-lane-unblock-20260924
```

The capture host uses its admitted bounded verification path. Resume from
`settled_day_analysis_barrier` after adoption to produce both verdicts; preserve
the original exact target/root arguments and pass `--paper-maker-paused` when
the owner-paused state applies. No such production run was performed here.
