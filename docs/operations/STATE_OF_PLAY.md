# State of play

**Last rewritten: 2026-08-31 America/Toronto.** Read this first; read `ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture/settlement; complete one bounded International Stage 0/1 lifecycle test; then measure maker economics after costs. **No market edge is proved.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production | GitHub merged PR #5 into `master` on Aug 31, adopting the previous portable state and its exact-head repair. The redesigned Stage 0/1 split remains on a topic branch and is not production or capture adoption. Preserve the two expected fleet-generated location-config modifications on the production checkout. |
| Overnight bootstrap | The offline integration runner bootstrap remains production-adopted. Do not reuse or reconstruct the spent historical attempts that preceded it. |
| Portable executor | The operator-selected remote branch `codex/live-gate-provenance-20260831` is the sole pre-master candidate for `portable_execution_v1`, superseding the earlier branch exception. Only an exact tip that has a clean local/cached/live equality proof, synchronized ancestral master, exact-head CI/review, clean portable update, explicit owner authority, and the tracked host/principal may act as live code authority. `capture_colocated_v1` remains master-only; the exception is not production or capture adoption. |
| Verification | The latest Stage 0 reached an authenticated user-stream subscription and then failed in a pre-mutation account/market read check, but v0.2 receipts could not name that check and falsely inferred a mutation merely from context creation. Exact repair commit `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` records truthful phases and mutation boundaries. The Stage 0 structural / Stage 1 lifecycle-safety / Stage 2 economics redesign and portable-authority switch reached reviewed tip `c0820b94aec34791879fbf056f48c8f7f0cc5636`; exact-head CI run `33444860493` passed compile, docs, generated-roadmap, and full-suite checks, and two independent cumulative reviews found no must-fix issue. This state-only tip still requires its own exact-head CI/review and synchronized refs before attempt generation. |
| Second PC | At reviewed tip `c0820b94aec34791879fbf056f48c8f7f0cc5636`, the clean portable clone matched local/cached/live topic; local/cached/live master matched `c932b54f8747df5cdefc4cc42f8454b6797f09ae` and was ancestral; all 26 HGB LFS hashes passed; CPython 3.11.9 x64, the SDK 0.6.0 overlay, 34-wheel wheelhouse, fresh installed audit, clock, proxy, reboot, and tracked `Michael` host/principal audit passed with no credential or exchange contact. Reprove those dynamic facts after this state-only update. The development checkout's ambient SDK remains excluded from live use. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Prior compare-only receipts proved four exact matches, zero writes, zero mutation, and no retained values, but every spent-attempt receipt is historical only; create a fresh compare-only receipt for the new namespace. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. Fresh August 31 NYC economics `xecon-97f7e8de0d3e7cfb` was accepted with exact file/drift hashes. A fresh paper run and 13-artifact substrate audit passed, but the next selector found no candidate because central books were 0.19/0.25 wide and paper-permitted books lay outside the fixed midpoint interval. That trace exposed an unvalidated five-cent/midpoint heuristic coupled into Stage 0. It is evidence of the coupling, not evidence that wider quoting is safe. Every expiring artifact is historical now. |
| Live money | Attempts `pilot-20260831T134425424Z` and `pilot-20260831T145154800Z` are spent and must never be retried. The latter passed authenticated user-stream readiness, then failed before pre-mutation geography and before any heartbeat or cancel-all REST call; no order was submitted. Later public preparation accessed no credential and made no exchange mutation. New execution is paused only until exact-tip and host qualification pass, not for paper/economics acceptance: Stage 0 uses generated event metadata, an exact current Gamma identity/status rebind, and structural scope; Stage 1 repeats that rebind and adds an exact lifecycle plan. Keep the 10 pUSD request / 100 pUSD wallet cap and every direct identity, geography, account, rule, mutation, cancellation, and cleanup gate. |

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

1. Publish this state update, then require exact-head CI/review, synchronized
   local/cached/live refs, clean portable update, and explicit exact-tip owner
   authority. The verified Stage 0 structural, Stage 1 lifecycle-safety, and
   Stage 2 economics split is not live authority by itself.
2. Only then create a new attempt, review all three immutable manifests and
   launchers, and create each 300-second plan against its bound event metadata
   plus exact current Gamma identity/status evidence whose normalized contract
   and hashes match the separately staged metadata; consume no more than the
   enforced 40-second preparation margin before composition.
3. At action time require geography, geoblock, account, balance/allowance,
   zero-state, current-rule, synchronized-Git, and attended-literal gates.
4. Stop on ambiguity. PASS requires terminal receipts, cancel-all, and
   authenticated zero-open-order/zero-position reconciliation.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is
fail-closed identity and path binding, early deterministic checks, immutable
receipts, bounded execution, and truthful claims. The portable lane requires
the exact profile-authorized Git authority and every action-time gate; a green
branch alone is never a runnable live session.

## Update this file when

Rewrite after publication/CI, admitted qualification, production merge, second-PC provisioning, live-readiness, or any Stage 0/1 result.
