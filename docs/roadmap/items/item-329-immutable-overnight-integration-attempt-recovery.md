# 329. Immutable Overnight Integration Attempt Recovery [PARTIAL 2026-08-20 - WORKFLOW IMPLEMENTED; VERIFICATION AND HOST ADOPTION PENDING]

Goal: stop losing entire integration windows when one frozen cumulative tip
hits a deterministic ratchet, transient host failure, or wrapper defect.

Owner/package: `scripts/ops/`, with the canonical procedure under
`docs/operations/`.

Source: the 2026-08-20 production-host integration audit. The August 16-20
attempt history showed deterministic ownership/schema failures, a redirected
native-Git wrapper failure, a wrong-worktree import, and transient timeouts;
the recovery contracts preserved the failed tip but prohibited a corrected
successor attempt during the same night.

Why this matters: the former recovery handoff preserved evidence by forbidding
all source changes and tip rebinding for the rest of the mission. That made a
recovery agent an auditor even when the failure had a small, understood fix.
Several nights were then spent rediscovering or documenting blockers without a
safe way to create a corrected attempt.

## Scope

- [x] Freeze immutable per-attempt manifests, logs, task names, and receipts
  instead of freezing the whole night.
- [x] Run deterministic schema, ownership, import, wrapper, documentation, and
  roadmap ratchets before the full suite.
- [x] Preserve the exact-tip full-suite and guarded quiet-merge gates.
- [x] Permit a new attempt only from an immutable FAIL/closure receipt, with
  enforced mechanical repair scopes or explicit manual review.
- [x] Permit one reviewed unchanged-tip retry for a transient failure and
  refuse consecutive unchanged retries.
- [x] Add a crash/abandonment closer that verifies and disables only the exact
  non-running one-shot tasks before issuing a replacement-authorizing receipt.
- [x] Emit a per-attempt merge receipt binding the suite, quiet-merge report,
  documentation transaction, source ancestry, remote acknowledgement, and
  three-worker capture recovery.
- [x] Make the merge consumer wait for terminal suite evidence through the
  03:40 reserve instead of consuming a slow but valid attempt at a fixed offset.
- [x] Freeze the complete repository-owned PowerShell helper closure used by
  registration, containment, admission, roll verdict, merge, and recovery.
- [x] Require the candidate to contain the frozen production baseline and
  reject any baseline advance through registration, suite, wait, or merge.
- [x] Require every successor to descend from the failed tip, bind a reviewed
  recovery dispatch, and consume one atomic predecessor successor claim;
  unchanged retry means the exact same commit id.
- [x] Add executable wait-decision, recovery-dispatch, claim, and tamper tests,
  and require downstream adoption arguments to equal the attempt proof.
- [x] Surface failed, closed, recovery-ready, and successor-claimed attempt
  states through canonical host status for an active overnight recovery agent.
- [x] Correlate missed-trigger status with the exact suite task and preflight
  evidence, fail disabled never-run suites immediately, and give a completed
  PASS only a bounded Task Scheduler exit grace at the reserve.
- [x] Distinguish a running suite from a suite that terminated without a
  receipt, surface a spent merge trigger, tolerate null Scheduler run-time
  metadata, emit invariant log timestamps, and resolve stale terminal
  Scheduler results from immutable PASS evidence plus full validation.
- [x] Let transient non-terminal Scheduler states settle before the reserve,
  stop and prove them terminal at the reserve, and eliminate the status
  task/receipt sampling race without suppressing unreadable-evidence alerts.
- [x] Preserve `MERGED_UNVERIFIED` while providing a reviewed, immutable,
  explicitly non-authorizing reconciliation receipt and exact-task shutdown.
- [x] Add a read-only downstream gate and bind execution-tape adoption to the
  attempt hashes while retaining the historical suite-gated path.
- [ ] Pass focused operation tests, documentation audit, roadmap lint,
  compileall, and the exact full suite in an admitted host window.
- [ ] Merge the reviewed branch and explicitly adopt the registrar on the
  production scheduler; editing the scripts does not authorize registration.

Acceptance: after any failed attempt, the evidence stays immutable and the
operator or active recovery agent can either close it, emit one reviewed
machine-readable dispatch, and create exactly one reviewed successor, or stop
with one specific blocker. A still-running suite cannot be mistaken for a
failure before the quiet-window reserve. No successor can inherit a PASS from
the failed attempt, no deterministic failure can trigger sibling or chained
unchanged reruns, and no merge or downstream task can proceed without complete
exact hash-bound evidence.

## Evidence

- Canonical procedure: `docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md`.
- Repository entry points: `scripts/ops/integration_attempt_*.ps1`,
  `new_integration_attempt.ps1`, `register_integration_attempt.ps1`,
  `close_integration_attempt.ps1`, and
  `assert_integration_attempt_success.ps1`.
- Deterministic and executable behavioral contract tests:
  `tests/operations/test_integration_attempt_scripts.py`.
- The first follow-up verification at tip `2f911f6f` passed 60 focused
  contracts, but an independent read-only audit then falsified the PASS path:
  `-split` was parsed as a nonexistent advanced-function parameter, so the
  full suite could never start. That audit correctly returned
  `APPROVE_AFTER_FIXES`; parser-only and source-substring tests had missed the
  executable binding defect.
- Post-audit repair verification on 2026-08-20: 65 focused operation contracts
  pass, including executable log-verdict/binding, wait/stop, baseline,
  dispatch, repair-scope, partial-registration closure, atomic-claim,
  exact-retry, DST, alert-lifecycle, and tamper cases. All 12 PowerShell files
  in the reviewed range parse, and the semantic AST ratchet finds no operator
  token misparsed as a command parameter. Fourteen roadmap/UI contracts,
  compileall, roadmap lint/check, the agent-document audit, and diff check also
  pass on the repaired tree. The exact full suite remains time-gated.
- A second adversarial review of tip `af5e8f9bd` confirmed the original repair
  set but found a deterministic false missed-trigger alert, a disabled-task
  wait that could consume the recovery window, no terminal reconciliation for
  `MERGED_UNVERIFIED`, and a narrow PASS/deadline race. It also found four
  low-cost parser/scope/regex/timestamp hardening gaps. The branch now carries
  all eight corrections plus caller-level status, wait-decision, exact-verdict,
  reconciliation, repair-scope, timestamp, and positive-control AST coverage.
  The 13-file parser/expanded semantic sweep, changed-test `py_compile`, and
  direct wait/verdict/timestamp/status probes pass. The 67 focused pytest
  contracts remain unexecuted because the changes were written inside the
  protected 18:00-00:30 host window.
- Production-host `roll_verdict.ps1` reported `ROLL-FREE` for the prior 28-file
  exact tip. The current follow-up adds one PowerShell file and otherwise changes
  only PowerShell, tests, and documentation, so it is structurally roll-free;
  re-run the canonical verdict on the committed exact tip before landing.
- A final adversarial validation of `e41d30232` found no authority or evidence-
  binding bypass, but found that a power-loss-interrupted suite and the later
  missed merge trigger could remain silent. It also found null Scheduler
  metadata misclassification, culture-sensitive evidence timestamps, and a
  one-second stale-result race that could discard PASS. The branch now carries
  all four repairs. All 13 PowerShell files parse and pass the 63-spelling
  semantic sweep, the three changed Python tests compile, diff check passes,
  and pure status/wait/task-validation/culture probes exercise the repaired
  boundaries. Exact-tip focused and full-suite execution remains part of the
  pending admitted-window verification gate.
- The release-gate audit of `7bfdb6fd4` returned
  `APPROVE_FOR_REMAINING_GATES` and re-executed all F1-F16, N1-N8, and R1-R4
  boundaries. Its blind pass found no blocking defect, but identified two LOW
  pre-adoption gaps: a transient non-terminal task state spent the attempt
  immediately, and status could sample an absent receipt before sampling the
  now-terminal task. The branch now waits safely for the former, stops it at
  the reserve unless it proves `Ready` or `Disabled`, and rechecks receipt
  existence after the latter task-state sample. The 67 focused tests and exact
  full suite remain pending in an admitted window.

The implementation is intentionally not registered or run from this topic
worktree. Verification and scheduler adoption remain open until their owning
time windows and explicit authority are available.
