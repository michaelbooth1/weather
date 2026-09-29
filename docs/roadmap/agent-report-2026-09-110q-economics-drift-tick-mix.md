# Agent report 2026-09-110q — economics drift tick mix

**PASS — fixture-proved repair: changing only the per-city mix of 0.01 and
0.001 ticks no longer requires a rescore. Real distinct fee-profile or tick-set
changes still BLOCK. Accepted snapshot hashes remain unchanged. Production
roll qualification and adoption remain with the production agent.**

## Provenance and scope

- Handoff: `docs/roadmap/workstation-handoff-2026-09-110q-economics-drift-tick-size-false-positive.md`
  on `origin/codex/handoff-110k-20260926`, fetched tip
  `c3916e6e90deb2d58ad8f461e98c505f7d873640`.
- Branch: `codex/economics-drift-tick-mix-20260927`.
- Fetched base: `origin/master` at `965374a0edc6fcb65d66e257be9e404cc9af8d60`.
- Implementation/test/runbook commit: `08dd1b61f3570948c2a51df49932225b5daebd2e`.
- Isolated worktree: `scratch/w/economics-tick-mix-110q` below the workstation
  checkout. The original checkout and all other worktrees were preserved.
- Open-question ids served: none. This is a deterministic gate repair, not an
  economics measurement; date clusters, market-day counts and intervals do not apply.
- The production incident and September 26 acceptance are supplied facts from
  the handoff, not independently read production evidence.

## Change and compatibility

The fetched base already separates `normalized_drift_payload` from
`normalized_economics_payload`. Only the drift projection changed:

1. `market_fee_rule_profiles` contains each city's distinct profiles of
   `fee_schedule`, `fees_enabled`, and `order_min_size`.
2. `market_tick_size_values` separately compares each city's distinct tick
   values. Adding or removing any distinct value is material, including an
   unfamiliar value. The implementation uses the handoff's conservative
   distinct-set-change rule, not an unconditional whitelist exemption.
3. `market_tick_size_mixes` in the drift report retains accepted/current
   per-city tick counts as a non-material diagnostic.

Both current and old accepted raw snapshots use the same new projection at
comparison time. Snapshot hashing, source hashing, identity, validation and
captured-run binding are unchanged; no schema-registry file or accepted
baseline is rewritten. A changed tick mix still changes the content hash.
Existing hashes need no migration or re-acceptance solely for this repair.
The owning [runbook](../operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md) documents the distinction.

## Fixture evidence and verification

The synthetic fixture has Atlanta 33 conditions and NYC 22, with distinct
fake condition/token identities. Atlanta's fine-tick count changes 12 to 15;
NYC's changes 15 to 12. Fee rate 0.05, exponent 1, taker-only, rebate 0.25 and
minimum size 5 remain constant. No venue data was fetched or copied.

- Before repair: the tick-only fixture had a PASS current-proof gate but a
  BLOCK drift report. The initial new-test run had 10 failures / 7 passes,
  including expected failures for the new separate tick-field diagnostics.
- After repair: tick-only drift is PASS with zero material changes; both
  cities' before/after counts remain visible. The prior-day baseline file is
  byte-identical after comparison.
- Rate, rebate, exponent, taker-only, fees-enabled and minimum-size mutations
  each BLOCK with material fee-profile drift. New ticks 0.005 / 0.0001,
  missing ticks, and either existing tick disappearing from either city BLOCK.
- Per-city profile isolation, profile removal, multiplicity/order invariance,
  stale proof and tampered-hash blocking are covered.
- The fixture hash captured on unmodified base code,
  `e06d9b8849f77e0eba10e6ca2889682d`, remains exact for identical inputs and JSON
  round trips. The changed mix has a different hash.
- Focused suite **310 passed, 17 subtests passed** (20.47 s), including existing
  economics/run-capture, daily-refresh and trading-evidence regressions plus
  the repo-wide audit files listed below. An earlier run passed 309 tests but
  correctly rejected the new untracked test; staging it resolved that audit.
- `compileall -q app src tests`: PASS.
- CLI audits: agent docs PASS, roadmap backlog parity PASS, correspondence
  index parity PASS (three CLI checks run under the workstation wrapper).
- `git diff --check`: PASS. Full-suite execution is left to draft-PR CI;
  this report makes no production-host qualification or CI-pass claim.

## Reproduction

From this branch's checkout, use its existing project interpreter and the
workstation wrapper described in [development](../development.md). The
following attended PowerShell form resolves the interpreter from the common
checkout for both a linked worktree and a normal checkout; Codex tool calls
must expand the wrapper invocation to the documented literal form.

```powershell
$repoRoot = (Get-Location).Path
$commonGit = git rev-parse --path-format=absolute --git-common-dir
$pythonPath = Join-Path (Split-Path $commonGit -Parent) 'venv\Scripts\python.exe'
$testRoot = Join-Path $env:TEMP 'weather-110q-repro'
$testArguments = @(
  '-m', 'pytest', '-q', "--basetemp=$testRoot",
  'tests/market/test_exchange_economics.py',
  'tests/market/test_exchange_economics_drift.py',
  'tests/operations/test_daily_refresh.py',
  'tests/operations/test_learning_lane_unblock.py',
  'tests/reporting/test_trading_evidence.py',
  'tests/operations/test_agent_docs_audit.py',
  'tests/operations/test_knowledge_structure_audit.py',
  'tests/operations/test_schema_registry.py',
  'tests/operations/test_import_architecture.py',
  'tests/operations/test_path_policy.py',
  'tests/operations/test_module_size_audit.py',
  'tests/reporting/test_roadmap_backlog.py',
  'tests/reporting/test_correspondence_index.py'
)
$argumentBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
  (ConvertTo-Json -InputObject $testArguments -Compress)))
& .\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath $pythonPath -ArgumentsBase64 $argumentBase64 -RepoRoot $repoRoot
& .\scripts\ops\workstation_heavy.ps1 -Kind compileall -PythonPath $pythonPath -ArgumentsBase64 'WyItbSIsImNvbXBpbGVhbGwiLCItcSIsImFwcCIsInNyYyIsInRlc3RzIl0=' -RepoRoot $repoRoot
```

The additional CLI checks use `python -m weather.operations.agent_docs_audit`,
`python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check`,
and `python -m weather.reporting.roadmap.correspondence_index --check`.
They were invoked as subprocesses from a temporary pytest harness under the
same wrapper. Remove only the resolved task-specific pytest temporary trees
after verification. Capture-host reproduction must instead follow its admitted
bounded-suite policy; the workstation result grants no capture-host exemption.

## Per-file roll classification and handback

| Changed file | Classification / closure evidence |
| --- | --- |
| `src/weather/market/exchange_economics.py` | UNDECIDABLE on this fixtures-only workstation: live closure membership was not read. Treat as potentially roll-sensitive pending production's mechanical verdict. |
| `tests/market/test_exchange_economics_drift.py` | Test-only source; no runtime import change. Production confirms exclusion from retained closures. |
| `docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md` | ROLL-FREE documentation by contract; no Python closure. |
| `docs/roadmap/agent-report-2026-09-110q-economics-drift-tick-mix.md` | ROLL-FREE documentation by contract; no Python closure. |
| `docs/roadmap/correspondence-index.md` | ROLL-FREE generated documentation by contract; no Python closure. Regenerated after committing this report so its Git-added date exists. |

Production must run `scripts\ops\roll_verdict.ps1 -Branch origin/codex/economics-drift-tick-mix-20260927`
against current retained closures before selecting an integration window.
No hand-derived closure claim substitutes for that result.

No venue calls, production data access, mirror access, production writes,
registration, scheduled-task mutation, worker restart, baseline acceptance,
promotion, live trading or merge was performed. Network use was limited to
authorized Git/GitHub source-control actions. The topic branch and draft PR
are the delivery surface; production acceptance remains separate.
