# State of play

**Last rewritten: 2026-09-02 America/Toronto.** Read this first; read `ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture/settlement; restore the exact production Git baseline through one reviewed reconciliation; complete one bounded International Stage 0/1 lifecycle test; then measure maker economics after costs. **No market edge is proved.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production | GitHub `master` remains published target `T=c932b54f8747df5cdefc4cc42f8454b6797f09ae`. The accepted production checkout remains local baseline `L=3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac`, with only the two expected generated location-config modifications. Production, its data, Scheduler, credentials, providers, exchanges, and push task were not contacted or mutated by this workstation mission. No reconciliation command has run. |
| Candidate | Exact reviewed parent `a24cf0f41bf0b321c5c813820594c56198a58d1a` is the base of branch `codex/workstation-production-baseline-self-adopting-reconcile-2026-09-85a`. The reviewed safety-patch implementation tree is complete and will be frozen by the implementation-only commit `S` named in the final handback. `S` must be a strict descendant of `T`. Runtime reconciliation creates config-only `C` with parent `L`, then merge `M` with ordered parents `[C,S]`; `M` must equal `S` plus only the two captured config contents and therefore remains a non-force descendant of `T`. `origin/master` stays exactly `T` until the one authorized publication. |
| Status/watchdog | The candidate's incident-bound status path is fail closed. A fully validated pre-dispatch marker says guarded reconciliation owns publication and manual `WeatherOneShotPush` is forbidden. A durably attempted marker says publication is pending/uncertain and retry is forbidden. Exact local/cached/live acknowledgement of `M` suppresses the warning. An absent incident marker leaves unrelated ordinary unpushed-state handling intact; malformed, unreadable/lookup-failed, stale, incomplete, or mismatched incident evidence is `incident_evidence_invalid`: preserve the marker and bound evidence, obtain reviewed recovery authority, and never invoke or retry. Invalid evidence uses cached `origin/master` for the unpushed count, and an unreadable comparison emits a neutral warning rather than false zero. The health watchdog preserves these meanings and never converts them into push/retry instructions. |
| Scheduler containment | Reconciliation uses no in-process ScheduledTasks call. Each read, Start, or Stop runs through the exact SHA-pinned safety-tip helper in a kill-on-close Job; the parent re-proves helper bytes per call, independently validates structured evidence, and the helper re-reads and fully attests the exact task immediately before mutation. The marker path is fixed to the canonical active marker. One fixed durable `CreateNew` claim spends Start authority; Stop has one fixed claim per ordinal 1/2. Creation/flush is followed by an immediate deadline recheck; if it consumes the budget, the claim is spent/unknown and Scheduler is not called. Any claimed throw, failed/lost response, timeout, or partial write means dispatch is unknown and authority is spent, never false or retryable; Start uncertainty cannot PASS even if publication later appears exact. |
| Absolute boundary | Every helper request has an immutable UTC deadline inside the earlier of the on-demand PT15M boundary and 04:00. The parent clamps the wait to leave five seconds for complete child-tree termination proof and a further three seconds for result parsing/validation. Normal helper exit also tears down surviving descendants. Start uncertainty is drained without retry; Stop uncertainty is terminal non-PASS and cannot consume another ordinal. |
| Verification | P0 passed on the assigned 32 GB non-capture workstation and attending principal: canonical hashed host/principal identities match `config/international_live_execution_host.json`, the host is not the dedicated capture host, and no raw MachineGuid or SID was exposed. Final executable gates are green: 70 reconciliation execution/adversarial tests; 74 complete status tests; 291 integrated affected tests; and the uninterrupted repository suite at 4,399 passed, 22 skipped, 13 warnings, plus 862 subtests in 45m50s. Final compileall passed through the workstation wrapper. PowerShell AST parsing, diff checks, the agent-doc audit (18 agent files/830 Markdown files), and roadmap lint/check also passed. Only exact `S`/tree/hash binding, canonical `L -> S` roll evidence, report-only `F`, branch push, and exact remote equality remain before `PASS_WITH_PRODUCTION_HANDOFF`. Production execution remains unauthorized. |
| Overnight bootstrap | The offline integration runner bootstrap remains production-adopted. Do not reuse or reconstruct the spent historical attempts that preceded it. |
| Portable executor | The owner-authorized exact remote branch `codex/portable-execution-host-clean-20260827` is now the sole pre-master live code authority for `portable_execution_v1`. It requires a clean exact local/cached/live topic tip, synchronized local/cached/live master, master ancestry, exact-head CI/review, and this tracked host/principal. `capture_colocated_v1` remains master-only; the exception is not production or capture adoption. |
| Portable verification | The latest Stage 0 reached an authenticated user-stream subscription and then failed in a pre-mutation account/market read check, but v0.2 receipts could not name that check and falsely inferred a mutation merely from context creation. Exact repair commit `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` (tree `8ffec7b716cd45be82d64e27266e3196d459a2bc`) now records allowlisted phases, separates stream subscription from REST writes, records each heartbeat/cancel boundary, preserves recovery lineage, requires exact two-heartbeat/one-cancel evidence for PASS, and validates the copies through Stage 1 lineage. Local verification passes 230 focused tests with 3 expected skips, compileall, docs audit, and diff checks; an independent pre-publication review found no remaining must-fix issue. The final state-only topic tip still requires exact-head CI/review and synchronized refs before attempt generation. |
| Second PC | The editable checkout contains the repair commit above; synchronizing the clean portable clone to the final published state-only tip is pending. Reprove local/cached/live topic equality, synchronized ancestral master, canonical origin, clean worktree, and exact-head CI/review after publication. Its CPython 3.11.9 x64 venv, all 26 HGB LFS objects, pinned dependencies, SDK 0.6.0 overlay, 34-wheel wheelhouse, installed audit, clock/proxy/reboot state, and tracked host/principal audit previously passed and must remain current. The development checkout's ambient SDK remains excluded from live use. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Prior compare-only receipts proved four exact matches, zero writes, zero mutation, and no retained values, but every spent-attempt receipt is historical only; create a fresh compare-only receipt for the new namespace. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. All substrates and candidates sealed into spent attempts are evidence only. The owner accepted economics snapshot `xecon-9f686625de725e6d` for August 31 and the latest exact NYC 78-79 scope, condition `0x576cca4ddd0ef5e55df4f79484ca88b6f4e1687288e7dabc0b145e7bbfe9e3c5`; use it only if the repository's freshness and exact-binding checks still pass after branch qualification, otherwise regenerate and obtain a new exact acceptance. |
| Live money | Attempts `pilot-20260831T134425424Z` and `pilot-20260831T145154800Z` are spent and must never be retried. The latter passed authenticated user-stream readiness, then failed before pre-mutation geography and before any heartbeat or cancel-all REST call; no order was submitted. Cleanup proved zero open orders and positions, stopped the stream, and closed the client. Its old receipt could retain only `RuntimeError`, so the precise read/check subgate is unrecoverable; the new phase repair will identify it in a wholly new attempt. Keep the exact 10 pUSD request / 100 pUSD wallet cap and every action-time gate. |

## Closed decisions -- do not relitigate without new evidence

- The owner authorizes one future 01:00-04:00 invocation of the existing exact `WeatherOneShotPush` definition for this reconciliation only. It grants no workstation execution, credential inspection, Scheduler modification, second Start, force push, or PR #9/#7 adoption.
- Reconciliation is fixed to exact `L`, `T`, strict `T < S`, config child `C`, and ordered merge `M=[C,S]`. The canonical roll command is `scripts/ops/roll_verdict.ps1 -Base L -Branch S`; no manual classification or substituted ref is valid.
- Precommit markers retain the rejected `T` boot sentinel. Only after exact `M` is committed may canonical fields expose real `C` and `M`. The adopted `L` boot bytes remain unchanged.
- Claimed Start or Stop authority is never recovered from a thrown helper, timeout, missing result, or uncertain Scheduler state. Status, watchdog, reports, and operators must preserve unknown/spent semantics.
- Ordinary synchronized quiet-merge behavior remains separate and unchanged. This one-time lane has no generic resume, hard-reset fallback, force, owner-exception, or integration-attempt routing.
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

1. Preserve the green P0, adversarial/affected, full-suite, compileall,
   PowerShell, documentation, roadmap, and diff evidence. Do not count the
   superseded path-length diagnostic runs as gates.
2. Commit the implementation-only safety tip `S`; prove its exact tip/tree,
   strict descent from `T` and reviewed parent, clean worktree,
   entry/dependency hashes, and unchanged PR #9/#7 separation.
3. Run the canonical final-branch roll verdict exactly from `L` to `S`, without
   a ref or manual substitution. A nonzero, missing, stale, unreadable,
   dormant-only, or incomplete classification remains roll-sensitive; it never
   relaxes the fixed 01:00-04:00 execution window or substitutes for review.
4. Write the required evidence report last and commit only that report as final
   tip `F`. Recheck `S`, `F`, their trees and changed files, then push the
   reviewed branch and verify exact local/cached/live branch equality. Do not
   create or execute a production mission here.
5. Only after exact-head CI/review and a complete PASS handoff may an attending
   operator consider the frozen future 01:00-04:00 production command bound to
   exact `S`, tree, entry/dependency hashes, `L`, `T`, canonical production
   root, and the unspent claim paths. Requalify production state at action time;
   a green branch alone is not authority.
6. After baseline equality is restored and independently proved, publish and qualify the portable repair with ancestral master, exact-head CI/review, and synchronized refs before re-inventorying the portable clone.
7. Create a wholly new live attempt. Revalidate or replace the accepted market/economics inputs, run the bounded paper/no-network gates, build new immutable manifests/launchers, and refresh a constrained candidate immediately before each attended stage.
8. At action time require eligible physical presence/no circumvention, official geoblock PASS, exact account topology, balance/allowance, zero unknown orders and positions, current rules, clean synchronized Git, and every exact attended literal. Stop on ambiguity; PASS requires terminal receipts plus authenticated cleanup reconciliation.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is fail-closed identity/path binding, immutable claims and evidence, exact topology, early deterministic checks, complete child-tree containment, bounded execution, and truthful uncertainty. Production remains untouched until a separately reviewed exact command passes every action-time gate. The portable lane likewise requires exact profile-authorized Git authority; no green branch is itself runnable.

## Update this file when

Rewrite after `S`/`F` publication or CI/review, any reconciliation gate or production result, baseline restoration, portable qualification, second-PC provisioning, live-readiness, or any Stage 0/1 result.
