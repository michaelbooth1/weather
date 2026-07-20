# Daily Delegated-Child Attestation Agent Report — 2026-07-19b

## Handoff identity

- Branch: `daily-attestation-2026-07-19`
- Worktree:
  `C:\Users\micha\Desktop\github\weather-daily-attestation-2026-07-19`
- Base `master` commit: `c4e88aad07a991f8b79b603d4112e565028e91e6`
- Implementation commit: `1418c7d3a8a9c6481c8056562afa6f4c275164e6`
- Report commit: the follow-up commit containing this file; its final object ID
  is recorded in the operations handoff because a commit cannot contain its own
  final ID.

No merge, push, scheduled-task registration, scheduler query, task launch,
capture-loop action, release mutation, or runtime `data/` write was performed.
The main worktree's pre-existing changes to
`config/location_market_events.json` and `config/locations.json` were
preserved and excluded. No persistent main-worktree edit was left behind; the
only `data/` access was the required read of
`data/logs/memory_commit_guard_status.json` before verification batches.

## Outcome

Both daily tasks now use the same proven delegated-child shape as the training
window:

- `WeatherDailySettlementPromotionRefresh` registers a PowerShell wrapper for
  Stage A settlement at 09:30 local with its existing four-hour task limit.
- `WeatherEveningEvidenceRefresh` registers the same wrapper for Stage B
  evidence at 14:00 and 17:00 local with its existing eight-hour task limit.
- The wrapper starts the resolved repository `pythonw.exe`, waits for it, and
  returns the child's exit code.
- The child declares `scheduler-invocation-topology=delegated_child`, the exact
  base64 wrapper-action contract, its own executable and full argv, the
  repository working directory, a 300-second launch correlation bound, and the
  existing stage-specific SLA.

The shared verifier in
`src/weather/operations/producer_provenance.py` already supports this topology.
It was reused unchanged; no `src/` file was modified and no daily-only
verification fork was introduced.

## Exact argument contracts

`scripts/ops/daily_refresh_contract.ps1` dot-sources the established
`training_window_contract.ps1` converters and owns two pure builders used by
the live wrapper and the tests.

The registered PowerShell action token order is:

1. `-NoProfile -NonInteractive -ExecutionPolicy Bypass`
2. `-File <resolved daily_refresh.ps1>`
3. `-RepoRoot <resolved repo>`
4. `-Stage <settlement|evidence>`
5. `-SchedulerTaskName <stage task>`
6. `-EvidenceTaskName WeatherEveningEvidenceRefresh`
7. `-SchedulerTaskExecutable <resolved PowerShell executable>`
8. optional `-ContinueOnError`
9. exactly one mode token:
   `-ProvenanceOnly`, or
   `-ProductionEvidenceArgumentsB64 <opaque JSON-token-vector contract>`

Registration serializes that vector with
`ConvertTo-ScheduledTaskArgumentString`. The running wrapper independently
reconstructs the same vector and passes its
`ConvertTo-SchedulerArgumentContract` value to the child. Paths, token order,
task identity, executable, mode, or continue-on-error drift therefore changes
the attested contract and fails closed.

The Python child token order starts with:

`-m weather.operations.daily_refresh run --fail-on-variant-evidence-alert`

It then carries optional `--continue-on-error`, the stage, and:

- settlement: `--evidence-task-name WeatherEveningEvidenceRefresh` and
  `--producer-sla-seconds 14400`;
- evidence: the existing evidence status/report paths and
  `--producer-sla-seconds 28800`.

Both stages then carry the delegated task name/executable/working directory,
exact action B64, resolved `venv\Scripts\pythonw.exe` process executable,
`--scheduler-correlation-seconds 300`, and the active-release pointer,
releases root, and repository root. Full mode appends the decoded production
evidence vector; ProvenanceOnly appends none of it.

## Full versus ProvenanceOnly

The registration script's default `Full` parameter set still makes all four
production-evidence families mandatory:

- `CapturedInputParityServed`
- `CapturedInputParityReplay`
- `ProductionReadinessServedArtifact`
- `ProductionReadinessServedRoute`

Full registration resolves every file, requires the production-readiness fail
flag, and encodes the complete evidence token vector into one wrapper argument.
The wrapper decodes it through an allowlist, requires at least one served,
replay, and served-artifact binding, requires exactly one served route, and
rejects empty, malformed, unsupported, or incomplete contracts.

`-ProvenanceOnly` is a distinct, mutually exclusive parameter set. It retains
the wrapper, scheduler-provenance, release-pointer/root, task identity, stage,
and SLA contracts while omitting
`--fail-on-production-readiness-block` and every production-evidence binding.
It does not claim FULL evidence, parity admission, or production readiness.

## Adoption command

After merging during the operations quiet window, the master should run this
once from the repository root:

```powershell
& .\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly
```

One invocation replaces both named daily tasks. The delegate did not run it.

## Verification

The PowerShell-focused tests only parse scripts, dot-source pure contract
functions, inspect command parameter-set metadata, and serialize tokens. They
do not execute the registration script or wrapper. Producer-provenance tests
inject task/process queries and never inspect or mutate the live scheduler.

Evidence from the final branch state:

- Exact construction subset:
  `python -m pytest -q tests/operations/test_daily_refresh_script.py
  tests/operations/test_producer_provenance.py::test_build_invocation_proof_accepts_daily_delegated_child
  tests/operations/test_producer_provenance.py::test_build_invocation_proof_decodes_exact_delegated_action
  tests/operations/test_producer_provenance.py::test_delegated_scheduler_attestation_binds_wrapper_action_and_child
  tests/operations/test_producer_provenance.py::test_scheduler_registration_scripts_declare_producer_contracts`
  — **9 passed** in 2.83 seconds (`commit_percent=55.4`, 215.3 GiB free).
- Broader focused regression:
  `python -m pytest -q tests/operations/test_daily_refresh_script.py
  tests/operations/test_producer_provenance.py
  tests/operations/test_training_window_script.py
  tests/operations/test_agent_docs_audit.py`
  — **39 passed** in 5.10 seconds (`commit_percent=55.4`, 215.3 GiB free).
- Exact ordered parent-action and child vectors are checked for all four
  combinations: settlement/evidence × Full/ProvenanceOnly. The two daily
  provenance PASS cases consume tokens emitted by the production PowerShell
  builders and verify task lookup, running instance identity, engine PID, and
  child lineage through the shared verifier.
- `python -m compileall -q app src tests` — **PASS**
  (`commit_percent=59.7`, 215.2 GiB free).
- `python -m weather.operations.agent_docs_audit` — **PASS**
  (18 agent files and 450 Markdown files audited).
- `git diff --check` and the staged-diff check — **PASS**.
- Independent code and test rereviews — **no actionable findings**.

The operations master retains ownership of quiet-window merge, push,
registration, and live scheduled-fire verification.
