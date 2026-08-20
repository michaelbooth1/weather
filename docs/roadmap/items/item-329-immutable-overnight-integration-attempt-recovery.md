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
- [x] Add a read-only downstream gate and bind execution-tape adoption to the
  attempt hashes while retaining the historical suite-gated path.
- [ ] Pass focused operation tests, documentation audit, roadmap lint,
  compileall, and the exact full suite in an admitted host window.
- [ ] Merge the reviewed branch and explicitly adopt the registrar on the
  production scheduler; editing the scripts does not authorize registration.

Acceptance: after any failed attempt, the evidence stays immutable and the
operator can either close it and create a reviewed successor or stop with one
specific blocker. No successor can inherit a PASS from the failed attempt, no
deterministic failure can trigger an unbounded rerun loop, and no merge or
downstream task can proceed without exact hash-bound evidence.

## Evidence

- Canonical procedure: `docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md`.
- Repository entry points: `scripts/ops/integration_attempt_*.ps1`,
  `new_integration_attempt.ps1`, `register_integration_attempt.ps1`,
  `close_integration_attempt.ps1`, and
  `assert_integration_attempt_success.ps1`.
- Deterministic contract tests:
  `tests/operations/test_integration_attempt_scripts.py`.
- Lightweight verification on 2026-08-20: 53 focused operation contracts
  passed; all 11 affected PowerShell sources parsed; compileall, roadmap lint,
  and the agent-document audit passed. The full suite remains time-gated.
- `roll_verdict.ps1` reports `ROLL-FREE`: 27 changed files and zero importable
  capture files. Landing this branch does not require a capture readoption roll.

The implementation is intentionally not registered or run from this topic
worktree. Verification and scheduler adoption remain open until their owning
time windows and explicit authority are available.
