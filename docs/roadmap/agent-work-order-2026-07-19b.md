# Agent Work Order — 2026-07-19b (daily-chain delegated_child attestation)

Composed by the operations master agent. Scheduled daily-refresh runs still
report `scheduler_attested: false` (mode `manual_or_unverified`) even after
the task actions gained the `--scheduler-*` contract arguments on
2026-07-17. The surviving blockers on a genuine 13:30 UTC scheduled fire
(2026-07-19) are running-instance correlation checks:

- `scheduler_process_command_unparseable` (ancestor depth 2:
  "Windows command line is required")
- `scheduler_running_instance_count_mismatch` (expected 1, actual 0)
- `scheduler_parent_engine_pid_mismatch` (expected -1 — the verifier could
  not query the task instance at all)
- `scheduler_running_instance_identity_missing` / state mismatch

The nightly retrain solved this exact problem with the `delegated_child`
topology: a PowerShell wrapper action whose exact action tokens are
attested via `scripts/ops/training_window_contract.ps1`
(Get-TrainingWindowTaskActionTokens, ConvertTo-ScheduledTaskArgumentString,
ConvertTo-SchedulerArgumentContract b64), and the child process attests the
wrapper lineage. Its window runs verify end-to-end (2026-07-19 01:00:
inactive-confirm → retrain → restore in 24 s).

## Task — port the delegated_child contract to both daily tasks

1. A wrapper script (pattern: `training_window.ps1`'s scheduler-provenance
   block) for `WeatherDailySettlementPromotionRefresh` (Stage A settlement)
   and `WeatherEveningEvidenceRefresh` (Stage B evidence), passing
   `--scheduler-invocation-topology delegated_child` plus the b64 action
   contract to `weather.operations.daily_refresh`.
2. Update `scripts/ops/register_daily_refresh.ps1` to register the wrapper
   actions. Keep its production-evidence parameters mandatory (they gate
   the FULL contract at release #1); add a documented
   `-ProvenanceOnly` registration mode that registers the wrapper +
   provenance/release arguments without the production-evidence contract,
   matching what is live today, so the tasks can be re-registered NOW
   without inventing parity inputs.
3. Verify `producer_provenance` accepts the topology for these tasks (the
   nightly path already does; reuse, do not fork, its verification).
4. Tests for the argument-contract construction (mirror the existing
   training-window contract tests if present; else add focused ones).

## Rules

Same repository, isolation, and rules as
`docs/roadmap/agent-work-order-2026-07-16.md`: NEW worktree on branch
`daily-attestation-2026-07-19`, based on current `master`, focused tests
under commit_percent < 70, no scheduler changes (master registers at
adoption), no merge/push. ps1/docs changes are roll-free; any src change to
`producer_provenance.py` is chain-side (not loop-loaded) but master still
merges in the quiet window.

### Reporting

`docs/roadmap/agent-report-2026-07-19b.md`: what changed, the exact
registration command master should run, test counts, branch/commit ids.

---

*Context: attestation feeds the item-321 gate chain
(attestation → release → admission → parity) for release #1. Streak clock:
day 1 = 2026-07-18, lockable ~Aug 1.*
