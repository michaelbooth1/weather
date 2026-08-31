# State of play

**Last rewritten: 2026-08-31 America/Toronto.** Read this first; read `ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture/settlement; complete one bounded International Stage 0/1 lifecycle test; then measure maker economics after costs. **No market edge is proved.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production | GitHub merged portable base PR #3 into `master` as `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` on Aug 30, and exact-master CI passed. PR #4 was merged without being retargeted, so it landed on PR #3's old topic branch rather than `master`; its assignment and workstation-policy changes are therefore not production authority. Preserve the two expected fleet-generated location-config modifications on the production checkout. |
| Overnight bootstrap | The offline integration runner bootstrap remains production-adopted. Do not reuse or reconstruct the spent historical attempts that preceded it. |
| Portable executor | The owner-authorized exact remote branch `codex/portable-execution-host-clean-20260827` is now the sole pre-master live code authority for `portable_execution_v1`. It requires a clean exact local/cached/live topic tip, synchronized local/cached/live master, master ancestry, exact-head CI/review, and this tracked host/principal. `capture_colocated_v1` remains master-only; the exception is not production or capture adoption. |
| Verification | The latest Stage 0 reached an authenticated user-stream subscription and then failed in a pre-mutation account/market read check, but v0.2 receipts could not name that check and falsely inferred a mutation merely from context creation. Exact repair commit `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` records truthful phases and mutation boundaries; final state tip `1acf9ebbc4a9576810b99126ea5ab8764f35aa9b` passed exact-head CI, cumulative review, synchronized refs, and portable re-inventory. The stacked redesign now separates Stage 0 structural scope, Stage 1 lifecycle safety, and Stage 2 economics; the focused live-path suite is green. The branch remains unqualified and has no live authority. |
| Second PC | The clean portable clone, editable checkout, CPython 3.11.9 x64 venv, all 26 HGB LFS objects, pinned dependencies, SDK 0.6.0 overlay, 34-wheel wheelhouse, installed audit, clock/proxy/reboot state, and tracked host/principal audit all passed at the preserved exact tip. The development checkout's ambient SDK remains excluded from live use. Any redesign tip requires its own publication, exact-head CI/review, synchronized refs, portable update, and explicit authority before another attempt. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Prior compare-only receipts proved four exact matches, zero writes, zero mutation, and no retained values, but every spent-attempt receipt is historical only; create a fresh compare-only receipt for the new namespace. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. Fresh August 31 NYC economics `xecon-97f7e8de0d3e7cfb` was accepted with exact file/drift hashes. A fresh paper run and 13-artifact substrate audit passed, but the next selector found no candidate because central books were 0.19/0.25 wide and paper-permitted books lay outside the fixed midpoint interval. That trace exposed an unvalidated five-cent/midpoint heuristic coupled into Stage 0. It is evidence of the coupling, not evidence that wider quoting is safe. Every expiring artifact is historical now. |
| Live money | Attempts `pilot-20260831T134425424Z` and `pilot-20260831T145154800Z` are spent and must never be retried. The latter passed authenticated user-stream readiness, then failed before pre-mutation geography and before any heartbeat or cancel-all REST call; no order was submitted. Later public preparation accessed no credential and made no exchange mutation. New execution is paused for redesign qualification, not for paper/economics acceptance: Stage 0 uses generated event metadata, an exact current Gamma identity/status rebind, and structural scope; Stage 1 repeats that rebind and adds an exact lifecycle plan. Keep the 10 pUSD request / 100 pUSD wallet cap and every direct identity, geography, account, rule, mutation, cancellation, and cleanup gate. |

## Closed decisions -- do not relitigate without new evidence

- International Polymarket only; never use Polymarket US for a new probe, credential path, readiness decision, or mutation.
- The first live test is one bounded plumbing/evidence session: Stage 0
  heartbeat/cancel-all plus one smallest-valid post-only BUY for each Stage 1
  cancellation mode, at most 10 pUSD each and a non-raisable 100 pUSD wallet
  cap.
- Scope/lifecycle-plan selection is never authorization. A successful no-fill test does not prove edge, profitability, fill quality, rebates, or Stage 2 readiness.
- Numeric gates are stage-scoped. Protocol/safety invariants and current venue
  rules fail closed; an unmeasured heuristic may rank or warn but cannot be
  called optimal or block a stage it does not protect. Do not replace an
  arbitrary threshold with a different arbitrary threshold.
- No alpha or paid weather provider. Baseline acceptance is informed operator action and is never scheduled automatically.
- No order from a blocked location and no circumvention. America/Toronto is
  scheduling/target-date configuration, never evidence of physical location.
  The live protocol asks for no city, state/province, or country; it uses the
  exact attended eligibility literal and Polymarket's credential-free geoblock.
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
- `portable_execution_v1` retains every money, identity, geography, Git, SDK,
  credential, account, deadline, cancellation, and cleanup gate, but no local
  capture/tape/streak or capture timetable. It accepts one tracked non-capture
  host/principal and cannot authorize another workload; the hook is not role authority.
  Its target may be the selected-market-local execution date or the immediately
  following date; its bounded execution and cleanup stay within one local date.
- Its sole pre-master code exception is the literal remote topic branch named
  above. No arbitrary branch argument exists; changing that branch requires a
  new reviewed code and operator decision.
- Moving the executor again means a new production-tip assignment, clone/venv,
  uniquely named SDK transfer, WinCred setup, fresh compare receipt, host
  audit, event metadata, stage plans, and attempt manifests. Never edit an old
  host ID or absolute path into prior evidence.

## Ordered critical path

1. Finish qualification of the implemented split: Stage 0 owns structural scope,
   Stage 1 direct lifecycle safety, and Stage 2 quote economics. Stage
   0/1 import no paper/economics, spread/midpoint, reward/rebate, or positive-fee gate.
2. Complete broader verification, documentation/schema audit, and cumulative review. The focused live-path suite is green, not live authority.
3. Publish and qualify the exact tip with exact-head CI/review, synchronized refs, clean portable update, and explicit owner authority. Prior artifacts remain historical.
4. Only then create a new attempt, review all three immutable manifests and
   launchers, and create each 300-second plan against its bound event metadata
   plus exact current Gamma identity/status evidence whose normalized contract
   and hashes match the separately staged metadata; consume no more than the
   enforced 40-second preparation margin before composition.
5. At action time require geography, geoblock, account, balance/allowance,
   zero-state, current-rule, synchronized-Git, and attended-literal gates.
6. Stop on ambiguity. PASS requires terminal receipts, cancel-all, and
   authenticated zero-open-order/zero-position reconciliation.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is
fail-closed identity and path binding, early deterministic checks, immutable
receipts, bounded execution, and truthful claims. The portable lane requires
the exact profile-authorized Git authority and every action-time gate; a green
branch alone is never a runnable live session.

## Update this file when

Rewrite after publication/CI, admitted qualification, production merge, second-PC provisioning, live-readiness, or any Stage 0/1 result.
