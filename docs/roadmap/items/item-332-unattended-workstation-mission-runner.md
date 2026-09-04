# 332. Unattended Workstation Mission Runner [PARTIAL]

Goal: make an unattended Codex implementation mission on the assigned
non-capture workstation deadline-bound, observable, create-only, and capable
of accepting success only after an exact handback and complete bundle validate.

Owner/package: `scripts/ops/`, with synthetic contracts in
`tests/operations/` and the operator contract in `docs/operations/`.

Source: the sealed 2026-09-03 workstation mission. Faithful probes of the
external prototype reproduced missing heartbeat, deadline, descendant-tree
containment, atomic status, exact handback validation, and diagnostic terminal
state contracts. They also showed that the prototype already refused an
existing attempt directory and did not retry, so the repository implementation
preserves those properties.

The production controller's independent 99a review then supplied a second
falsifier: ordinary controller `worktree add` attempted to download the missing
LFS object for `artifacts/models/hgb/feature_model_hgb.pkl` and failed with
`Smudge error: batch request: missing protocol: ""`. The same review found that
the final identity boundary did not recheck the already-claimed Git and Windows
PowerShell path/digest pairs.

Why this matters: long implementation missions outlive interactive client
connections. Without a
fresh heartbeat, absolute deadline, whole-tree containment, immutable attempt
evidence, and exact success validation, an operator cannot distinguish useful
work from a stranded process or trust a zero exit as a reviewable handback.

## Scope

- [x] Bind the exact mission, Codex executable, source/base identities, result
  ref and worktree, required handback paths, bundle path, and UTC deadline in an
  immutable attempt claim.
- [x] Run the child in the repository's Windows kill-on-close Job and prove
  whole-tree teardown at deadline and interruption without PID-name matching.
- [x] Publish atomic, sequenced heartbeat/status evidence and a read-only status
  mode that distinguishes terminal, stale same-boot, and reboot-boundary cases.
- [x] Refuse attempt collisions, identity drift, invalid zero-exit handbacks,
  dirty result worktrees, undeclared changed paths, incomplete bundles, and
  failed strict object verification.
- [x] Add Windows PowerShell 5.1 synthetic tests for success and every required
  fail-closed state, plus the durable operator contract.
- [x] Suppress Git LFS smudging only while creating the controller worktree,
  restore the exact prior process environment value, retain pointer bytes, and
  leave Git configuration and non-LFS filter behavior unchanged.
- [x] Re-resolve and rehash Git and Windows PowerShell with every other claimed
  executable at the post-child identity boundary before handback validation.
- [ ] Obtain independent review and integrate the exact result tip through the
  repository Git workflow.
- [ ] Run one new non-production unattended mission with the adopted runner and
  retain its immutable attempt namespace, terminal receipt, and verified bundle.

Acceptance: an adopted runner attempt can report fresh progress, stop its full
child tree by an absolute deadline, survive client disconnection while the
wrapper remains alive, and declare `COMPLETE_VALIDATED` only when the exact
result ref, clean worktree, required receipt/report, declared tests and hashes,
complete bundle, and strict fsck all pass. A host reboot remains an explicit
boundary until a separately reviewed Scheduler or service supervisor exists.

## Evidence

- Implementation branch:
  `codex/workstation-unattended-mission-runner-hardening-2026-09-99a`.
- Implementation commit:
  `0a8108f9d24321aaac88762c28426f8ca68d2bf8`.
- Runner: `scripts/ops/invoke_workstation_codex_mission.ps1`.
- Contracts: `tests/operations/test_workstation_codex_mission_runner.py`.
- Operator contract: `docs/operations/WORKSTATION_CODEX_MISSION_RUNNER.md`.
- Mission handback:
  `docs/roadmap/agent-report-2026-09-03-workstation-unattended-mission-runner-hardening.md`
  and
  `docs/roadmap/workstation-handback-2026-09-03-unattended-mission-runner-hardening.json`.
- LFS/identity repair branch:
  `codex/workstation-unattended-mission-runner-lfs-repair-2026-09-99b`.
- Repair contracts: the local loopback LFS batch/download falsifier and copied
  Git/Windows PowerShell path/SHA drift cases in
  `tests/operations/test_workstation_codex_mission_runner.py`.

## Completion notes

This source branch grants no production, capture, Scheduler, credential,
network-provider, exchange, merge, publication, promotion, or live-trading
authority. The runner deliberately does not invent attempts or restart after a
reboot; each new attempt remains an explicit, separately bound operator action.
