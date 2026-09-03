# State of play

**Last rewritten: 2026-09-03 America/Toronto.** Read this first; read `ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture/settlement; restore the exact production Git baseline through one reviewed reconciliation; complete one bounded International Stage 0/1 lifecycle test; then measure maker economics after costs. **No market edge is proved.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production | GitHub `master` remains published target `T=c932b54f8747df5cdefc4cc42f8454b6797f09ae`. The accepted production checkout remains local baseline `L=3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac`, with only the two expected generated location-config modifications. Immutable evidence for spent attempt `WeatherProductionBaselineReconcile_20260903_a1` shows it failed closed at `2026-09-03T01:00:05.6156090-04:00` during pre-lease Scheduler snapshot attestation: no merge, push invocation, Stop, capture action, or lingering marker; all three supervisors remained `RUNNING`. This workstation repair did not contact production or Scheduler. |
| Candidate | PR #10 branch `codex/workstation-production-baseline-self-adopting-reconcile-2026-09-85a` began this repair at exact tip `1cd51d516875e279c674a76bf921e22ddaf30943` / tree `ba23363a956e66c4914ad7bdc4f3766d9e1678b8`. The minimal repair makes parent and child use one name/path `Export-ScheduledTask` plus UTF-8 hash path, brackets the structured object with identical exports, and counts only non-null triggers. Runtime reconciliation still creates config-only `C` with parent `L`, then merge `M` with ordered parents `[C,S]`; `M` must equal repaired safety tip `S` plus only the two captured config contents and remain a non-force descendant of `T`. |
| Status/watchdog | The candidate's incident-bound status path is fail closed. A fully validated pre-dispatch marker says guarded reconciliation owns publication and manual `WeatherOneShotPush` is forbidden. A durably attempted marker says publication is pending/uncertain and retry is forbidden. Exact local/cached/live acknowledgement of `M` suppresses the warning. An absent incident marker leaves unrelated ordinary unpushed-state handling intact; malformed, unreadable/lookup-failed, stale, incomplete, or mismatched incident evidence is `incident_evidence_invalid`: preserve the marker and bound evidence, obtain reviewed recovery authority, and never invoke or retry. Invalid evidence uses cached `origin/master` for the unpushed count, and an unreadable comparison emits a neutral warning rather than false zero. The health watchdog preserves these meanings and never converts them into push/retry instructions. |
| Scheduler containment | Reconciliation uses no in-process ScheduledTasks call. Each read, Start, or Stop runs through the exact SHA-pinned safety-tip helper in a kill-on-close Job; the parent re-proves helper bytes per call and independently validates structured evidence. The helper brackets its exact structured task read with the canonical frozen name/path XML serialization, requires byte/hash stability, treats null `Triggers` as zero, and still rejects every real trigger or identity mismatch. The fixed marker and durable `CreateNew` Start/Stop claims, immediate deadline recheck, unknown/spent semantics, and one-push budget remain unchanged. |
| Absolute boundary | Every helper request has an immutable UTC deadline inside the earlier of the on-demand PT15M boundary and 04:00. The parent clamps the wait to leave five seconds for complete child-tree termination proof and a further three seconds for result parsing/validation. Normal helper exit also tears down surviving descendants. Start uncertainty is drained without retry; Stop uncertainty is terminal non-PASS and cannot consume another ordinal. |
| Verification | P0 reproduced both defects before repair: the old child rejected the frozen name/path hash when `-InputObject` serialized the same task differently, and Windows PowerShell 5.1 reported old/new null-trigger counts `1|0`. Post-repair gates are green: 87 Scheduler/static tests, 70 complete execution/adversarial tests, and 93 complete reconciliation/status/watchdog tests. The workstation full-suite invocation completed with 4,405 passed, 18 expected skips, 862 passed subtests, and only the 12 documented legacy-MAX_PATH failures in `test_experiment_executor.py`; that complete file passed 24/24 under extended-prefix temp mode. Compileall, changed-script AST parsing, cumulative diff checks, the agent-doc audit (18 agent files/830 Markdown files), and roadmap lint/check pass. Commits, publication, and exact-head CI remain. |
| Overnight bootstrap | The offline integration runner bootstrap remains production-adopted. Do not reuse or reconstruct the spent historical attempts that preceded it. |
| Portable executor | The owner-authorized exact remote branch `codex/portable-execution-host-clean-20260827` is now the sole pre-master live code authority for `portable_execution_v1`. It requires a clean exact local/cached/live topic tip, synchronized local/cached/live master, master ancestry, exact-head CI/review, and this tracked host/principal. `capture_colocated_v1` remains master-only; the exception is not production or capture adoption. |
| Portable verification | The latest Stage 0 reached an authenticated user-stream subscription and then failed in a pre-mutation account/market read check, but v0.2 receipts could not name that check and falsely inferred a mutation merely from context creation. Exact repair commit `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` (tree `8ffec7b716cd45be82d64e27266e3196d459a2bc`) now records allowlisted phases, separates stream subscription from REST writes, records each heartbeat/cancel boundary, preserves recovery lineage, requires exact two-heartbeat/one-cancel evidence for PASS, and validates the copies through Stage 1 lineage. Local verification passes 230 focused tests with 3 expected skips, compileall, docs audit, and diff checks; an independent pre-publication review found no remaining must-fix issue. The final state-only topic tip still requires exact-head CI/review and synchronized refs before attempt generation. |
| Second PC | The editable checkout contains the repair commit above; synchronizing the clean portable clone to the final published state-only tip is pending. Reprove local/cached/live topic equality, synchronized ancestral master, canonical origin, clean worktree, and exact-head CI/review after publication. Its CPython 3.11.9 x64 venv, all 26 HGB LFS objects, pinned dependencies, SDK 0.6.0 overlay, 34-wheel wheelhouse, installed audit, clock/proxy/reboot state, and tracked host/principal audit previously passed and must remain current. The development checkout's ambient SDK remains excluded from live use. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Prior compare-only receipts proved four exact matches, zero writes, zero mutation, and no retained values, but every spent-attempt receipt is historical only; create a fresh compare-only receipt for the new namespace. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. All substrates and candidates sealed into spent attempts are evidence only. The owner accepted economics snapshot `xecon-9f686625de725e6d` for August 31 and the latest exact NYC 78-79 scope, condition `0x576cca4ddd0ef5e55df4f79484ca88b6f4e1687288e7dabc0b145e7bbfe9e3c5`; use it only if the repository's freshness and exact-binding checks still pass after branch qualification, otherwise regenerate and obtain a new exact acceptance. |
| Live money | Attempts `pilot-20260831T134425424Z` and `pilot-20260831T145154800Z` are spent and must never be retried. The latter passed authenticated user-stream readiness, then failed before pre-mutation geography and before any heartbeat or cancel-all REST call; no order was submitted. Cleanup proved zero open orders and positions, stopped the stream, and closed the client. Its old receipt could retain only `RuntimeError`, so the precise read/check subgate is unrecoverable; the new phase repair will identify it in a wholly new attempt. Keep the exact 10 pUSD request / 100 pUSD wallet cap and every action-time gate. |

## Closed decisions -- do not relitigate without new evidence

- Attempt `20260903_a1` is spent and frozen: never retry, rewrite, delete, or reconstruct it. Any later production action requires the production owner to independently fetch and review the final repair tip, run the canonical roll verdict, and create a wholly new immutable attempt; this workstation mission grants no retry or Scheduler authority.
- Reconciliation is fixed to exact `L`, `T`, strict `T < S`, config child `C`, and ordered merge `M=[C,S]`. The canonical roll command is `scripts/ops/roll_verdict.ps1 -Base L -Branch S`; no manual classification or substituted ref is valid.
- Precommit markers retain the rejected `T` boot sentinel. Only after exact `M` is committed may canonical fields expose real `C` and `M`. The adopted `L` boot bytes remain unchanged.
- Claimed Start or Stop authority is never recovered from a thrown helper, timeout, missing result, or uncertain Scheduler state. Status, watchdog, reports, and operators must preserve unknown/spent semantics.
- Ordinary synchronized quiet-merge behavior remains separate; its directly equivalent null-trigger count is repaired without changing its reviewed task contract. This one-time lane has no generic resume, hard-reset fallback, force, owner-exception, or integration-attempt routing.
- International Polymarket only; never use Polymarket US for a new probe, credential path, readiness decision, or mutation.
- The first live test is one bounded plumbing/evidence session: Stage 0 heartbeat/cancel-all plus one smallest-valid post-only BUY for each Stage 1 cancellation mode, at most 10 pUSD each and a non-raisable 100 pUSD wallet cap.
- Candidate selection is never authorization. A successful no-fill test does not prove edge, profitability, fill quality, rebates, or Stage 2 readiness.
- No alpha or paid weather provider. Baseline acceptance is informed operator action and is never scheduled automatically.
- No order from a blocked location and no circumvention. America/Toronto is scheduling/target-date configuration, never evidence of physical location. The live protocol asks for no city, state/province, or country; it uses the exact attended eligibility literal and Polymarket's credential-free geoblock.
- No unattended first live session.
- `capture_colocated_v1` retains local capture/tape/streak checks and `[00:30, 09:00) America/Toronto` containment.
- The separate 32 GB workstation may run implementation, tests, training,
  replay, and measurement outside the capture timetable/resource admission.
  Recognized heavy commands use its admission-only wrapper, which requires the
  assignment's exact host and attending principal. That wrapper and the
  portable launcher hold one host-global mutex and kill-on-close child-tree
  Jobs through cleanup. Finish heavy work before sealing to preserve the
  attempt; an inert seal is not live authority. This grants no production or
  live authority, and its PASS does not replace production-host qualification.
- `portable_execution_v1` retains every money, identity, geography, Git, SDK, credential, account, deadline, cancellation, and cleanup gate, but no local capture/tape/streak or capture timetable. It accepts one tracked non-capture
  host/principal and cannot authorize another workload; the hook is not role authority.
  Its target may be the candidate-market-local execution date or the immediately
  following date; its bounded execution and cleanup stay within one local date.
- Its sole pre-master code exception is the literal remote topic branch named
  above. No arbitrary branch argument exists; changing that branch requires a
  new reviewed code and operator decision.
- Moving the executor again means a new production-tip assignment, clone/venv,
  uniquely named SDK transfer, WinCred setup, fresh compare receipt, host
  audit, public substrate, candidates, and attempt manifests. Never edit an old
  host ID or absolute path into prior evidence.

## Ordered critical path

1. Finish documentation/roadmap audits and cumulative diff checks, then commit
   the implementation/tests/owning-documentation safety tip `S` separately.
2. Prove exact `S`, tree, entry/helper hashes, strict descent from `T` and the
   required starting tip, clean worktree, and unchanged PR #9/#7 separation.
3. Write and commit only the required report/handback receipt as final tip `F`,
   push the existing PR #10 branch without rewriting history, and prove exact
   local/cached/live equality plus exact-head Linux CI.
4. Do not run a workstation roll verdict as production evidence. The production
   owner must independently fetch/review exact `F` and `S`, run the canonical
   production-host roll verdict, and create a new immutable attempt. A green
   branch is not execution authority.
6. After baseline equality is restored and independently proved, publish and qualify the portable repair with ancestral master, exact-head CI/review, and synchronized refs before re-inventorying the portable clone.
7. Create a wholly new live attempt. Revalidate or replace the accepted market/economics inputs, run the bounded paper/no-network gates, build new immutable manifests/launchers, and refresh a constrained candidate immediately before each attended stage.
8. At action time require eligible physical presence/no circumvention, official geoblock PASS, exact account topology, balance/allowance, zero unknown orders and positions, current rules, clean synchronized Git, and every exact attended literal. Stop on ambiguity; PASS requires terminal receipts plus authenticated cleanup reconciliation.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is fail-closed identity/path binding, immutable claims and evidence, exact topology, early deterministic checks, complete child-tree containment, bounded execution, and truthful uncertainty. Production remains untouched until a separately reviewed exact command passes every action-time gate. The portable lane likewise requires exact profile-authorized Git authority; no green branch is itself runnable.

## Update this file when

Rewrite after `S`/`F` publication or CI/review, any reconciliation gate or production result, baseline restoration, portable qualification, second-PC provisioning, live-readiness, or any Stage 0/1 result.
