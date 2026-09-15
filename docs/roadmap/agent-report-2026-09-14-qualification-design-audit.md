# Qualification design: fresh end-to-end audit

Date: September 14, 2026. Scope: audit of the completed
[qualification design](agent-report-2026-09-14-qualification-design.md).
Verdict: design review complete after corrections. The replacement is not
implemented, qualified on production, or authorized for first landing.

## Review identity and method

The first design was committed before this review at
`f1bc4fdf824d6496e995d34d351fabe336f69e56`, based on fetched master
`3bdba3d15470d831710eeeb8c5885d1c9d4ae12a`. Its original file SHA256 is
`da637045838d2d91c6ab60841f9bc5c7a3b321f55cce3ed49b92551f8512f245`.
The corrected design reviewed here has SHA256
`aa85c8cbfe7f1eae4943037fe9153cb380d23093055b2568ea1173a4eef7eac6`.
These are hashes of file bytes, not a reserialized document or a runtime PASS.

This was a separate pass by the same agent, after freezing the first design.
It was not an independent human or second-agent review. The pass traced every
authority transition, compared claims with the actual owning code, constructed
failure cases, corrected the design, and retraced the corrected boundaries.
No candidate code, full test suite, current-data audit, merge, task registration
or live operation was run for this design audit.

The production contract reference is the baseline above. Audit implementation
and CI references are the unadopted reliability source
`aaa7f2de19542f2ddc0c2953e0301433dcd69a93`; they are not silently treated as
installed code. Principal sources:

- [Integration-attempt runbook](../operations/INTEGRATION_ATTEMPT_RUNBOOK.md),
  including bootstrap, immutable retry, terminal grace and reconciliation.
- [Host-load policy](../operations/HOST_LOAD_POLICY.md),
  [delegation contract](../operations/DELEGATION_CONTRACT.md),
  [development matrix](../development.md), and
  [reserved-window contract](../operations/reserved-confirmation-window.md).
- [Adopted bounded suite](../../scripts/ops/bounded_worktree_test_suite.ps1):
  inline environment/marker setup, native containment, exact source/inventory,
  64% start / 66% abort, and full-suite-only authorization.
- [Ordinary guarded merge](../../scripts/ops/quiet_window_merge.ps1):
  generated-config preparation, no-commit staging, MERGE_HEAD recovery,
  parent validation, documentation and publication boundaries. Its separate
  incident-bound reconciliation path grants no generic bootstrap authority.
- [Candidate audit store](https://github.com/michaelbooth1/weather/blob/aaa7f2de19542f2ddc0c2953e0301433dcd69a93/src/weather/reporting/source_gates/settlement_audit_store.py),
  [audit lineage reader](https://github.com/michaelbooth1/weather/blob/aaa7f2de19542f2ddc0c2953e0301433dcd69a93/src/weather/reporting/source_gates/settlement_source_audit.py),
  and [sealed hashes](https://github.com/michaelbooth1/weather/blob/aaa7f2de19542f2ddc0c2953e0301433dcd69a93/src/weather/reporting/source_gates/settlement_audit_hashes.py).

## Findings and corrections

Severity describes the consequence if the original design were implemented
literally. Closed below means corrected in the specification, not proved by
an implementation test.

| ID | Severity | Finding in first design | Correction and required implementation proof |
| --- | --- | --- | --- |
| Q1 | High | The new gate's bootstrap still depended on facilities that were not yet adopted. Offline-marker installation is inline code, and the new publisher cannot be its own initial authority. | Section 10 binds directly reviewed off-host evidence and a separate exact owner-approved adapter/installer closure. It names the actual inline logic and requires an independently reviewed temporary guarded primitive with the missing checks. No fabricated v1 PASS, candidate-selected installer or generic exception switch. Test first landing without an installed v2 publisher/verifier. |
| Q2 | High | Requiring a final S-plus-Q tree while invoking an unchanged ordinary merge wrapper leaves enforcement until after publication. Parent identity alone is insufficient. | Section 8 adds typed verification inside the guarded primitive before staging, commit and push, with preview in an isolated index and explicit Git configuration. Negative tests change Q, merge attributes, an external driver, index contents and working bytes at each boundary; none may publish an unqualified tree. |
| Q3 | High | Freezing dependency hashes does not prevent later verifier imports from loading S after production files are replaced. | Section 8 executes authority from an immutable attempt-local copy of the approved B closure, including deferred imports. Recovery may inspect S; S cannot become its own acceptance authority mid-attempt. Inject replacement immediately before each deferred child/import. |
| Q4 | High | D covered labels and ledgers but omitted files read through row lineage paths, including potentially large or active snapshot tapes. Copies would still contain original absolute paths. | Section 7 covers the full dependency closure, approved roots, optional missing-payload states, and a read-only identity resolver. Include every byte read in resource estimates. Test out-of-root paths, reparse escapes, same file under repeated aliases, missing payload appearance and mutable original paths behind a staged ledger. |
| Q5 | Medium | The promise to reject malformed input disagreed with the candidate reader, which skips malformed JSONL records. Mandatory missing inputs and optional missing lineage also had different semantics. | Section 7 adds a strict streaming qualification precheck without changing the existing algorithm's row semantics. It distinguishes mandatory ledger coverage from explicitly reported optional absence. Test malformed middle records, truncated tails, invalid JSON types, duplicate CSV headers and missing/extra market ledgers. |
| Q6 | High | Full rereads could exceed the two-minute pre-merge allowance, and unchanged live input was assumed without a feasibility or atomicity definition. | Sections 6-7 charge discovery, staging, all hashes, indexing and output to the measured audit envelope. Acceptance states its final observation time and bounds delay to mutation. It does not claim an atomic multi-file producer generation. Stability/throughput are release gates; persistent drift requires a reviewed generation/append-aware design, not repeated nightly retries. |
| Q7 | Medium | Remote-state freshness was bounded only when arming; a task armed far in advance could consume stale provenance. Conversely, requiring a live query under S4U would create an unavailable capability. | Section 5 bounds import freshness at launch and merge, with a declared maximum 24-hour remote-information lag, immutable arming and local revocations. This is a proposed policy choice for cutover review. Test old, future-dated, replayed and locally revoked receipts without requiring S4U network authentication. |
| Q8 | Medium | Process caps did not specify aggregate enforcement and could omit parent/monitor overhead or descendants. | Section 6 budgets the full tree and monitor, combines native Job commit limits with bounded external monitoring, and distinguishes sampled working-set abort from a hard allocation guarantee. Test child fan-out, monitor loss, failed Job assignment and parent death. |

All eight findings were incorporated into the corrected design and retraced.
No critical/high design finding remains open in this review. Runtime behavior,
performance and first-landing acceptance remain explicit release gates.

## End-to-end trace after correction

| Step | Positive path | Adversarial case and required refusal |
| --- | --- | --- |
| 1. Authority and scope | Existing contracts stay active until an accepted version transition. | A design document or draft PR is presented as permission to bypass v1: reject. |
| 2. Candidate identity | Reviewed clean S contains synchronized B; source, imports, environment and test inventory are frozen. | B advances, dependency bytes differ, a test disappears or the PR merge SHA is mistaken for its head: new qualification required. |
| 3. Off-host execution | Full Windows and Linux plans finish at exactly S with explicit native coverage. | Only affected Windows tests pass, a required capability is skipped, collection is empty, or successful shards come from different attempts: no certificate. |
| 4. Evidence publication | Pinned trusted publisher validates exact run IDs, results and artifact digests without executing candidate artifacts. | Forged JUnit, altered ZIP, wrong workflow revision, traversal, duplicate JSON keys or candidate-controlled signing logic: reject. |
| 5. Import and arming | Authenticated exact bundle and remote snapshot are retained locally with policy and expiry. | An old run is renamed latest, a timestamp is edited, registration occurs without a sealed arming receipt, or known revocation exists: no launch. |
| 6. Host admission | Real S4U task, shared lease, healthy capture, disk and measured full-tree envelope fit the window. | Resources are unknown, start commit exceeds 64%, projected peak violates 66%, disk reserve is insufficient, or the deadline cannot include cleanup: non-authorizing refusal. |
| 7. Native probes | Adopted authority sets offline controls and contains fixtures in disposable roots. | Wrong installation/principal, inherited secret control, import escape, failed assignment or descendant leak: fail and prove cleanup; poison unresolved ownership. |
| 8. Current audit | Fresh complete inputs and lineage are staged, resolved read-only, checked strictly and processed with established semantics. | Missing required ledger, malformed record, changed tail, replaced source, unsealed payload reference, incomplete output or exhausted budget: no host PASS. |
| 9. Semantic judgment | Computation, coverage and consumer parity pass while existing truth-label BLOCKs remain visible. | An agent changes expected answers after inspecting current data or equates algorithm acceptance with economic readiness: reject. |
| 10. Handoff to merge | Receipt, environment, Q/D, source and capture are revalidated under the merge lease within expiry. | A lease wait occurs after the final data check, the permitted delay expires, or new drift is observed: restart validation within budget or close the attempt. |
| 11. Source mutation | Trusted B authority previews S-plus-Q, retains no-commit recovery markers, checks actual bytes and proves affected-worker recovery. | Config/driver/tree changes, capture fails, or recovery observes different bytes from those being committed: rollback/recovery before publication. |
| 12. Publication | Exact two-parent commit, documentation transaction and guarded push receive remote acknowledgment. | Crash after commit, lost push response or disagreement between receipt and remote: reconciliation/resume only; never an ordinary retry. |
| 13. Downstream and history | Only a v2-aware validator accepts the complete graph; all v1 evidence remains readable under v1. | An old consumer treats a v2 smoke receipt as a full suite, a reconciled failure gains authority, or a failed attempt is overwritten: reject. |
| 14. Rollback and next attempt | Source rollback uses the existing recovery contract; successor claims are immutable and single-use. | Possible publication is treated as absence, tasks remain unclosed, two successors race or source moves: stop, preserve evidence and reconcile. |

The bootstrap trace is separate: reviewed K and off-host evidence -> exact
owner envelope -> independently reviewed single-use adapter and guarded copy
-> contained real-S4U probes -> guarded K adoption and acknowledged publication
-> installed v2 authority -> newly reconciled and qualified reliability source.
There is no edge from K's own test result directly to authority to install K.

## Finite implementation gates

The design is ready to guide implementation. These are required proofs before
calling the bottleneck fixed in operation:

1. Complete exact-source Windows/Linux coverage and authenticated evidence
   work with the repository's actual service permissions and reproducible
   production environment. No assumed hosted capability or unsigned fallback.
2. The full current-input dependency closure, repeated validation and native
   probes finish inside measured host budgets without disrupting capture. A
   safe refusal is useful evidence but does not satisfy this performance gate.
3. Actual authority/consumer functions pass the negative cases above on native
   Windows, including complete child teardown and crashes around commit/push.
4. The concrete first-landing envelope has explicit acceptance of its one-time
   v1 prerequisite substitution and temporary reviewed installer. That decision
   occurs after the implementation and evidence are reviewable.
5. One reconciled reliability candidate completes the v2 chain, including its
   current-data audit, guarded recovery and acknowledged publication. Observe
   subsequent adoption opportunities without claiming long-term reliability
   from that first success.

The release plan deliberately starts with qualification and its trust
transition. Unattended workstation deployment, broad scheduling redesign,
immutable live capture deployment and maker/model work are not prerequisites.
If the current-input feasibility gate fails, the next implementation increment
must address that measured cause before claiming reliable adoption capacity.

## Document verification

The audit records a source/design review, not executable fault-test results.
Whitespace checks and the canonical documentation/link audit are recorded in
the accompanying PR after the final files are staged. No full-suite or native
host qualification result is inferred from those documentation checks.
