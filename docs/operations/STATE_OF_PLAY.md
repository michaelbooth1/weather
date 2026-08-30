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
| Verification | Paper and no-network preparation exposed two deterministic defects: the run orchestrator rejected its documented 600-second proof TTL, then candidate preflight assumed one economics row per event although temperature events have one row per binary condition. Set-based repair `4e87112a9d0cd528fafcbc108346b29f4356e3d9` plus independently re-reviewed fail-closed row-shape/cardinality hardening `045a9e6d991db487f9feb9302e3450a864095aa9` are included in topic tip `65926ba1d97265ffba9638a405924c2b634bf832`; exact-head [CI](https://github.com/michaelbooth1/weather/actions/runs/33341934428) is green. Local verification passed 73 focused tests plus compile, and the real 11-condition/22-token evidence conforms exactly. |
| Second PC | The clean portable clone is synchronized to authorized topic tip `65926ba1d97265ffba9638a405924c2b634bf832`; local/cached/live topic agree, local/cached/live master agree at `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac`, master is an ancestor, origin is canonical, and the worktree is clean. Its CPython 3.11.9 x64 venv, all 26 HGB LFS objects, pinned dependencies, SDK 0.6.0 overlay, 34-wheel wheelhouse, fresh installed audit, clock/proxy/reboot state, and exact assigned host/principal audit all pass. The development checkout's ambient SDK remains excluded from live use. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets. Current attempt `pilot-20260830T233709864Z` produced a fresh v0.4 compare-only PASS for this exact host/principal: four exact matches, zero writes, zero mutation, no retained values. Keep the private transfer source locked down until a final comparison is consumed, then use the approved deletion procedure. |
| Public substrate | Preserve every partial namespace. Current attempt `pilot-20260830T233709864Z` passed initialization, public identity, credential comparison, metadata, observation dry-run, weather/source capture, CLOB capture, and exact economics acceptance for snapshot `xecon-9b1b7201e5871a5b` / SHA-256 `e52fb0fbeed3e8d658e51fa9eae763dc2e287340aa00f3f46f7998710e965aa6`, including the acknowledged pUSD/USDC documentation conflict. Toronto then produced zero paper quote-permission rows because every YES book was one-sided. A 23:40Z public scan of all 12 built-in markets found 132 latest YES rows: 119 one-sided and 13 two-sided, with none of the latter inside the required `[0.20, 0.80]` midpoint interval; therefore no eligible candidate existed at that capture. Do not weaken selection gates or reuse the failed Toronto substrate. Later Stage refreshes use compact attempt-bound sibling roots below the legacy path budget. |
| Live money | Public unauthenticated metadata/weather endpoints were contacted; no credentialed exchange call, authenticated write, order, cancellation, or Stage 0/1 session occurred. The first session remains attended, International-only, exact 10 pUSD request / 100 pUSD wallet cap, and separately gated at every mutation boundary. |

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
- Its sole pre-master code exception is the literal remote topic branch named
  above. No arbitrary branch argument exists; changing that branch requires a
  new reviewed code and operator decision.
- Moving the executor again means a new production-tip assignment, clone/venv,
  uniquely named SDK transfer, WinCred setup, fresh compare receipt, host
  audit, public substrate, candidates, and attempt manifests. Never edit an old
  host ID or absolute path into prior evidence.

## Ordered critical path

1. Before the target date ends, repeat fresh public book discovery only if a
   built-in market develops a two-sided candidate inside the fixed midpoint and
   spread gates. Current market state is the blocker; do not relax the gates.
2. For an eligible market, build a new one-market public substrate. Reuse the
   exact accepted economics snapshot only while its two-hour gate and hashes
   remain current; otherwise collect it again and stop for acceptance. Run the
   600-second paper tick and no-network preflight, then stop for the exact
   candidate/date/hash-bound acknowledgment emitted by the review-only selector.
3. Build and review all three immutable manifests and launchers, then refresh a
   constrained candidate immediately before each stage. Never reuse the failed
   long-path namespace or an expired artifact.
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
