# T008r1: B007 intake dispositions and NBM-FRESH registration

Dated research handback, 2026-11-06. This is the response to master ruling B007 at 14:27
America/Toronto, and supersedes the unresolved proposals in the earlier intake note without
rewriting that historical record. No data was read and no S1, replay, training or heavy job ran.

## Ruling recorded

- X109 H2 market arm: CLOSED-BY-RULE (reopenable), not a measured KILL. The v4 increment is the
  floor-only control; whole-model v0.5.12 is X21's family. Reopen at R within about 0.05 of 1 in
  a block or receipt latency below book repricing. Signed H2 remains a model-versus-model
  secondary; October replay remains prohibited.
- X110 unconditional NBM tilt: CLOSED-BY-RULE (reopenable). B007 extends X21/X22 plus sibling
  X58/X96 measurements under method rules 14/15. No new statistical result on this member.
- X111 R-P2 versus market: UNTESTABLE as a T4 because the existing corpus covers only Aug-Sep;
  building more is on the approved stop-list. X95 stays PARKED.

The register contains the three rows, all with `not computed; no data read` and the archive
`C:\archive\ruled-out\t4-screens-intake-20261106\`. The old proposed three K rows never opened.

## NBM-FRESH

[rule_nbm_fresh.md](rule_nbm_fresh.md) defines the only admitted mechanism: a market centre
that responds to a new NBM cycle after our actual response receipt, rather than before.
US11 07-12, receipt age <=15 min, abs(cycle revision)>=1 F, parser v2 only, dev through September 29.
Stage order: timing/source feasibility, label-free S1 lag, full-donor-population synthetic
power projection, one market-residual P0 (20 seeds, BH K=1), then w only for a survivor.
Coarse unresolved timing is UNTESTABLE; lack of the predeclared S1 lag is KILL for the screen.
No executable-price, profit or T4 claim follows from display-price lag or a dev statistical win.

Ledger row 121 pins the rule SHA256. Count 213->214 explicitly depends on C14's unlanded
row 120 (`1a7edb0a5242be7f0643bf17f17642d76c70419f`, ledger blob
`734d1c540dde8e37f0b1aea9259c38106bb7f0bc`); C14 lands first. Its row is not silently copied.
No S1 until master confirms row 121 has landed. The runner remains unimplemented/unadmitted.
S1 expires if not completed by November 10 at 18:00 America/Toronto. Existing resource holds,
the live-session freeze and the research-script review/allowlist protocol remain binding.

## Archive and publication

Copy the original `C:\t\codex\T008\out\intake-v1\` byte-for-byte into the named permanent
archive, preserving source files and historical HOLD receipts. Add this ruling handback as a
separate dated record. Preserve original indexes before regenerating per-file indexes; the
task receipt verifies every copied file's hash. B007 explicitly authorises this archive write
outside COMMON's usual task/worktree write roots. Nothing is moved or deleted.

Publish the docs branch using the connected GitHub API. If API-created commits receive different
SHAs from local commits, preserve local history and verify equal Git tree IDs. Report both tips;
no force update, credential changes or CLI push retry. A verified local bundle is also retained.

## Proposed DECISION_LOG row text (master-owned file, not edited)

| 2026-11-06 | **MASTER RULING B007 (14:27 America/Toronto; not an owner decision): T008 intake closes X109 H2 and X110 unconditional NBM tilt CLOSED-BY-RULE (reopenable); X111 R-P2 is UNTESTABLE as a T4, X95 stays PARKED. No data read. Admit only low-priority NBM-FRESH under ledger row 121 and its pinned rule: US11 07-12, receipt age <=15 min, abs(v2_mean revision)>=1 F, parser v2; timing/S1 then full-donor power >=0.5 then P0 (20 seeds, BH K=1) then w. S1 waits for master confirmation that row 121 landed after C14; stop if S1 incomplete by 11-10.** | T008r1; model-screen intake | master B007, 2026-11-06 14:27; docs/research/t4-screens-2026-11-06/handback-B007.md; ledger row 121 pins rule SHA256 | earlier unresolved T008 intake proposals only; no frozen trial or embargo changed |

## Proposed STATE_OF_PLAY bullet text (master-owned file, not edited)

- **T008 intake (master B007, 11-06):** H2 and unconditional NBM tilt CLOSED-BY-RULE (X109/X110); R-P2 UNTESTABLE as T4 (X111), X95 PARKED; no data read. Only NBM-FRESH admitted, low priority (ledger 121; rule in `docs/research/t4-screens-2026-11-06/`); S1 waits for master's row-121 landing confirmation after C14, expires 11-10; no October replay or corpus work.
