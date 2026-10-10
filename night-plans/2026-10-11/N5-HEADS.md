# N5 heads, landing night 2026-10-10 -> 2026-10-11

- Machine plan: branch `claude/night-plans`, `night-plans/2026-10-11/landing-night-plan-2026-10-11.json` (landing_night_plan_v0.1, plan_sha256 2f5c1310bd34a12839bd57467d4e13dbc198f57f10dcfb304960b6f4cf2fb041).
- Base: origin/master 32aa8c7c5 (= dc7cb6dd3 + CI ratchet fix 94d860d87, which every head contains). Pre-gates ran with -Base dc7cb6dd3 (same tree plus the fix inside each head).

| Exec | Head (v2) | Tip | PRs | Class (static) | qtest | Pre-gate (21 chunks) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | claude/integration-20261011-rs-v2 | f8499d0bd55f9591d35fec8adf00023ba82c5db1 | #259 9d409b21c, #210, #270 | RS | 854 passed, 2 skipped | PASS 514 files, 9346 passed, 66 skipped, 0 failed |
| 2 | claude/integration-20261011-rsb-v2 | ee41a90e828c215f57e57511910cc547117c59fa | snap-hb 0766101ee, D5N7 a4727d6d6, #265, #267 | RS | 1282 passed, 12 skipped | PASS 519 files, 9552 passed, 66 skipped, 0 failed |
| 3 | claude/integration-20261011-rf-v2 | c9029029a61e1a5f8cc23832f0b1245dbb0ca3dd | #272, #273 | RF | 386 passed, 1 xfailed | PASS 519 files, 9590 passed, 64 skipped, 0 failed |

Fallbacks (on the fix): rsb-nors-v2 7e377cc08113cca55b638f625e40148c81fe8d07 (snap-hb + D5N7; qtest 433 passed; pre-gate PASS 515 files, 9183 passed) and rf-nors-v2 36456a4bfb8a8efc946de6a205b217636c75d75a (#272 + #273; qtest 386 passed; pre-gate PASS 514 files, 9177 passed).

- If RS-A fails: land rsb-nors-v2 (RS) then rf-nors-v2 (RF); #265/#267 slip. If RS-B fails: land rf-nors-v2 on RS-A.
- Drop order on overflow: rf first, then rsb.
- **Post-merge for RS-B:** the shadow runner (activated 04:16 on 1e0e84793) must take the Restart step in docs/operations/maker-shadow-runner.md to pick up D5N7/#265/#267; verify with maker_shadow_readout.ps1.
- #265/#267 conflicted with #268 (master). Union resolution on the integration branch only (readout.ps1 format string carries record-stream MB {12} and $embargo {13}; tests keep both asserts; runner doc `minute` row from #267, `terminal` row from #268).
- landing_preflight (--tests none) on each slot: only FAIL is correspondence_index --check, which is stale on master 32aa8c7c5 itself (closeout regenerates it); --check-structure PASS on all heads. Static roll classes RS/RS/RF as declared.
- Not in plan: #266, #269 (build line). Superseded v1 branches claude/integration-20261011-{rs,rsb,rf,rf-nors,rsb-nors}: delete after N5.
