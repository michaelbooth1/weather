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
| Verification | The latest Stage 0 reached an authenticated user-stream subscription and then failed in a pre-mutation account/market read check, but v0.2 receipts could not name that check and falsely inferred a mutation merely from context creation. Exact repair commit `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` (tree `8ffec7b716cd45be82d64e27266e3196d459a2bc`) now records allowlisted phases, separates stream subscription from REST writes, records each heartbeat/cancel boundary, preserves recovery lineage, requires exact two-heartbeat/one-cancel evidence for PASS, and validates the copies through Stage 1 lineage. Local verification passes 230 focused tests with 3 expected skips, compileall, docs audit, and diff checks; an independent pre-publication review found no remaining must-fix issue. The final state-only topic tip still requires exact-head CI/review and synchronized refs before attempt generation. |
| Second PC | The editable checkout contains the repair commit above; synchronizing the clean portable clone to the final published state-only tip is pending. Reprove local/cached/live topic equality, synchronized ancestral master, canonical origin, clean worktree, and exact-head CI/review after publication. Its CPython 3.11.9 x64 venv, all 26 HGB LFS objects, pinned dependencies, SDK 0.6.0 overlay, 34-wheel wheelhouse, installed audit, clock/proxy/reboot state, and tracked host/principal audit previously passed and must remain current. The development checkout's ambient SDK remains excluded from live use. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Prior compare-only receipts proved four exact matches, zero writes, zero mutation, and no retained values, but every spent-attempt receipt is historical only; create a fresh compare-only receipt for the new namespace. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. All substrates and candidates sealed into spent attempts are evidence only. The owner accepted economics snapshot `xecon-9f686625de725e6d` for August 31 and the latest exact NYC 78-79 scope, condition `0x576cca4ddd0ef5e55df4f79484ca88b6f4e1687288e7dabc0b145e7bbfe9e3c5`; use it only if the repository's freshness and exact-binding checks still pass after branch qualification, otherwise regenerate and obtain a new exact acceptance. |
| Live money | Attempts `pilot-20260831T134425424Z` and `pilot-20260831T145154800Z` are spent and must never be retried. The latter passed authenticated user-stream readiness, then failed before pre-mutation geography and before any heartbeat or cancel-all REST call; no order was submitted. Cleanup proved zero open orders and positions, stopped the stream, and closed the client. Its old receipt could retain only `RuntimeError`, so the precise read/check subgate is unrecoverable; the new phase repair will identify it in a wholly new attempt. Keep the exact 10 pUSD request / 100 pUSD wallet cap and every action-time gate. |

## Closed decisions -- do not relitigate without new evidence

- International Polymarket only; never use Polymarket US for a new probe,
  credential path, readiness decision, or mutation.
- The first live test is one bounded plumbing/evidence session: Stage 0
  heartbeat/cancel-all plus one smallest-valid post-only BUY for each Stage 1
  cancellation mode, at most 10 pUSD each and a non-raisable 100 pUSD wallet
  cap.
- Candidate selection is never authorization. A successful no-fill test does
  not prove edge, profitability, fill quality, rebates, or Stage 2 readiness.
- No alpha or paid weather provider. Baseline acceptance is informed operator
  action and is never scheduled automatically.
- No order from a blocked location and no circumvention. America/Toronto is
  scheduling/target-date configuration, never evidence of physical location.
  The live protocol asks for no city, state/province, or country; it uses the
  exact attended eligibility literal and Polymarket's credential-free geoblock.
- No unattended first live session.
- `capture_colocated_v1` retains local capture/tape/streak checks and
  `[00:30, 09:00) America/Toronto` containment.
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

1. Publish the repair plus this state update. Require exact local/cached/live
   equality, master ancestry, green exact-head CI, and independent review on
   the final topic tip, then fast-forward and re-inventory the portable clone.
2. Create a wholly new August 31 attempt. Revalidate the accepted NYC scope or
   select a fresh built-in market inside the unchanged midpoint/spread gates;
   refresh economics and exact acceptance if any bound input is stale. Run the
   600-second paper tick and no-network preflight. Never reuse either spent
   attempt or any launcher, manifest, or candidate sealed beneath one.
3. Build and review all three new immutable manifests and launchers, then
   refresh a constrained candidate immediately before each stage.
4. At action time, require eligible physical presence/no circumvention,
   official geoblock PASS, exact account topology, balance/allowance, zero
   unknown orders and positions, current market rules, clean synchronized Git,
   and every exact attended stage literal.
5. Stop on any ambiguity. PASS requires terminal receipts plus cancel-all and
   authenticated zero-open-order/zero-position reconciliation.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is
fail-closed identity and path binding, early deterministic checks, immutable
receipts, bounded execution, and truthful claims. The portable lane requires
the exact profile-authorized Git authority and every action-time gate; a green
branch alone is never a runnable live session.

## Update this file when

Rewrite after publication/CI, admitted qualification, production merge, second-PC provisioning, live-readiness, or any Stage 0/1 result.
