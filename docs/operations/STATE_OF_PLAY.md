# State of play

**Last rewritten: 2026-08-30 America/Toronto.** Read this first; read `ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before research.

> **REWRITTEN, never appended. Capped at about 90 lines.** Put quantitative evidence, false claims, and durable mechanics in their owning canonical file.

**Objectives:** protect capture/settlement; complete one bounded International Stage 0/1 lifecycle test; then measure maker economics after costs. **No market edge is proved.**

## Current truth

| Area | State / next action |
| --- | --- |
| Production | GitHub merged portable base PR #3 into `master` as `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` on Aug 30, and exact-master CI passed. PR #4 was merged without being retargeted, so it landed on PR #3's old topic branch rather than `master`; its assignment and workstation-policy changes are therefore not production authority. Preserve the two expected fleet-generated location-config modifications on the production checkout. |
| Overnight bootstrap | The offline integration runner bootstrap remains production-adopted. Do not reuse or reconstruct the spent historical attempts that preceded it. |
| Portable executor | Corrective [draft PR #5](https://github.com/michaelbooth1/weather/pull/5) targets `master` and contains exact reviewed head `e1f7985ed9057019ccbfa1034fbdeadd8fd52a4a` plus this state rewrite. It names this selected 32 GB host and attending principal and keeps workstation-heavy work outside the capture timetable, but remains non-authoritative until the production host supplies the canonical roll verdict and guarded adoption. |
| Verification | Corrective PR #5 exact-head [CI](https://github.com/michaelbooth1/weather/actions/runs/33326607314) passed compilation, knowledge contracts, roadmap validation, 4,073 tests, 92 skips, and 860 subtests. The portable clone's new environment passed import and package-integrity smoke plus 35 focused portable-host/SDK tests. Its clean venv activates only the sealed SDK overlay; the older development-checkout venv has an ambient `polymarket` install and is deliberately not an execution-lane interpreter. Production-host qualification and adoption remain separate and pending. |
| Second PC | The clean portable clone still matches production `origin/master` at `3361520f...`; all 26 HGB LFS objects hash exactly, and its CPython 3.11.9 x64 venv has pinned runtime/test dependencies with `pip check` clean. Source transfer `20260830T184120257Z` supplied the canonical SDK 0.6.0 overlay and 34-wheel wheelhouse; destination bundle audit, create-only import, and installed audit all passed exact hashes. Windows Time is running and synchronized, proxy/reboot checks are clear, and the offline host audit passes on the corrective policy branch for this exact host/principal. The production clone remains unassigned until PR #5 lands, so no attempt has started and no exchange endpoint was contacted. |
| Capture | The portable lane does not run capture and does not consume remote capture-host status as live authority. Capture continues as a separate production-host objective; a portable lifecycle receipt is not capture-health or streak evidence. |
| Credentials | The root plaintext `.env` was moved intact outside Git into a non-reparse directory whose allow ACL is limited to the attending user, SYSTEM, and Administrators. The canonical create-only importer provisioned all four fixed WinCred targets, then a distinct v0.4 compare-only run verified all four exactly with zero mutation; public outputs retain no secret values. That receipt is intentionally short-lived, so a new compare-only receipt is required after production enrollment. Keep the private transfer source locked down until that final comparison is consumed, then use the approved deletion procedure. |
| Live money | No exchange endpoint was contacted and no Stage 0/1 session has run. The first session remains attended, International-only, exact 10 pUSD request / 100 pUSD wallet cap, and separately gated at every mutation boundary. |

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
- Moving the executor again means a new production-tip assignment, clone/venv,
  uniquely named SDK transfer, WinCred setup, fresh compare receipt, host
  audit, public substrate, candidates, and attempt manifests. Never edit an old
  host ID or absolute path into prior evidence.

## Ordered critical path

1. On the production host, fetch and independently review PR #5's current exact tip,
   obtain the canonical roll verdict, run the required serial qualification, and use the guarded integration path. Green CI and a remote mergeable state
   are not production adoption; never rewrite the published history.
2. After PR #5 is adopted, update the clean portable clone to that exact
   `master` tip and require local `HEAD`, tree, cached `origin/master`, and a
   fresh canonical remote query to agree. Rerun the installed SDK and offline
   host audits; do not use the ambient-SDK development venv.
3. Generate a fresh host/principal-bound compare-only credential receipt into
   new paths, consume it within two hours, and then dispose of the temporary
   private source through the approved deletion procedure.
4. Build a new attempt-local public substrate from metadata, observation,
   weather/source, CLOB, economics and a strictly passing paper tick; run its
   no-network local preflight. Regenerate identity, candidate, and all three
   immutable attempts. Never reuse another host's or an expired attempt's
   artifacts.
5. At action time, require eligible physical presence/no circumvention,
   official geoblock PASS, exact account topology, balance/allowance, zero
   unknown orders and positions, current market rules, clean synchronized Git,
   and every exact attended stage literal.
6. Stop on any ambiguity. PASS requires terminal receipts plus cancel-all and
   authenticated zero-open-order/zero-position reconciliation.

## Verification boundary

A finite audit cannot predict every unknown defect. The durable standard is
fail-closed identity and path binding, early deterministic checks, immutable
receipts, bounded execution, and truthful claims. Until focused/bounded tests
pass and the exact code is production-adopted, the portable executor is a
reviewed candidate, not a runnable live lane.

## Update this file when

Rewrite after publication/CI, admitted qualification, production merge, second-PC provisioning, live-readiness, or any Stage 0/1 result.
