# State of play

**Last rewritten: 2026-08-30 America/Toronto.** Read this first; read `ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture/settlement; complete one bounded International Stage 0/1 lifecycle test; then measure maker economics after costs. **No market edge is proved.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production | GitHub merged portable base PR #3 into `master` as `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` on Aug 30, and exact-master CI passed. PR #4 was merged without being retargeted, so it landed on PR #3's old topic branch rather than `master`; its assignment and workstation-policy changes are therefore not production authority. Preserve the two expected fleet-generated location-config modifications on the production checkout. |
| Overnight bootstrap | The offline integration runner bootstrap remains production-adopted. Do not reuse or reconstruct the spent historical attempts that preceded it. |
| Portable executor | The owner-authorized exact remote branch `codex/portable-execution-host-clean-20260827` is now the sole pre-master live code authority for `portable_execution_v1`. It requires a clean exact local/cached/live topic tip, synchronized local/cached/live master, master ancestry, exact-head CI/review, and this tracked host/principal. `capture_colocated_v1` remains master-only; the exception is not production or capture adoption. |
| Verification | August 30 preparation repairs for the 600-second proof TTL and multi-condition economics rows are already in the authorized topic branch. The first August 31 Stage 0 launch then exposed a third deterministic defect before any prompt: Windows ran the sealed wrapper as `PowerShell lease owner -> venv python.exe redirector -> base python.exe`, while the wrapper required the lease owner to be the base process's direct parent. The bounded repair accepts only a direct owner or exactly one sealed redirector, proves an actively deny-write-held v3 lease and owner creation token, locks and hashes the redirector, `pyvenv.cfg`, and base process image, requires strict process-creation order, and carries one consistent lineage proof through every downstream receipt. It is published in exact code commit `1e60b6b0c184fc88bd5c52913cdf949961d475db` (tree `cdae3c2510a695edf9e0812c647305265f51a5e2`); exact-code-head CI run `33350227270` passed and an independent exact-commit review reported no findings. Local verification passes 256 focused tests with 14 expected skips plus the real v3 portable-lease functional test. Any later state-only tip still needs its own exact-head CI/review and synchronized refs before attempt generation. |
| Second PC | At the published repair code tip, local/cached/live topic agreed at `1e60b6b0c184fc88bd5c52913cdf949961d475db`; local/cached/live master agreed at `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac`, master was an ancestor, origin was canonical, and the worktree was clean. Reprove those dynamic conditions after this state update. Its CPython 3.11.9 x64 venv, all 26 HGB LFS objects, pinned dependencies, SDK 0.6.0 overlay, 34-wheel wheelhouse, installed audit, clock/proxy/reboot state, and exact assigned host/principal audit pass. The development checkout's ambient SDK remains excluded from live use. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Spent attempt `pilot-20260830T233709864Z` produced a v0.4 compare-only PASS for this exact host/principal: four exact matches, zero writes, zero mutation, no retained values. That receipt is historical only; create a fresh compare-only receipt for the new attempt. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. August 30 Toronto evidence remains a valid failed selection with no safe candidate. A fresh August 31 San Francisco 64-65 F substrate at `C:\w31\pilot-20260831T002111189Z-stage0-s6` passed its 600-second paper tick and no-network preflight. Its exact candidate selected the accepted `xecon-aa45dfe56150f577` economics scope and had SHA-256 `f67b7cea285f32b6b62f6d4b4c43cd1a5af5134679405fa07d549ed0dfb08a2e`; it is now expired and bound to a spent attempt, so it is evidence only and must never be reused. |
| Live money | Attempt `pilot-20260831T002111189Z` was invoked exactly once and terminally failed during fixed-launcher preflight on the parent-process assertion. It produced no doctor, geography, credential-resolution, bootstrap, command, or user-stream artifact. Therefore no credential value was read, no authenticated exchange contact or write occurred, and no heartbeat, cancellation, order, position, or balance mutation occurred. The attempt and all three launchers are spent. A new attended International-only attempt must retain the exact 10 pUSD request / 100 pUSD wallet cap and every action-time gate. |

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

1. Preserve the exact implementation evidence at `1e60b6b0c184fc88bd5c52913cdf949961d475db`.
   Require exact local/cached/live equality, green CI, and independent review on
   the current topic tip, then synchronize and re-inventory the clean portable
   clone. Do not reuse any artifact sealed from the predecessor tip.
2. Create a wholly new August 31 attempt and fresh public substrate. Select
   only a built-in market inside the unchanged midpoint/spread gates, refresh
   date-bound economics if required, run the 600-second paper tick and
   no-network preflight, and obtain the exact new candidate/date/hash-bound
   acknowledgment. The expired `s6` candidate and spent
   `pilot-20260831T002111189Z` namespace are never retry inputs.
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
