# N7 heads, landing night 2026-10-11 -> 2026-10-12

N6 landed early on 10-11 at 05:27, so the 10-12 night carries N7.

- **Machine plan:** `night-plans/2026-10-12/landing-night-plan-2026-10-12-n7.json` (landing_night_plan_v0.1).
  - plan_sha256 fd9149704e580e20a8e175e3f6fbf813fab6b3dc0ad48763f8f80deb1a3457ef
  - file sha256 7c10eb3e91cef3447f909183c0f6d1ab23825419a13857c387338c66ed3926f8
- **Base:** origin/master 8ea5d089b. Zero drift at plan time.

| Exec | Head | Tip | Members (merge order) | Class (static) | journal_pinned_touch | qtest | Pre-gate (21 chunks) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | claude/integration-20261012-n7-rf | a367985748618ad16a3b5f40b4b019c677878fe1 | DST-M4 b27d9800b, defender-followups c7dc4638f, DST-M5/M6 1e4e743ec | RF | [] | 469 passed (16 files incl. reconciler) | PASS 519 files, 9611 passed, 63 skipped, 0 failed; receipt sha256 0a55d2d3631ef4c2a523b9f46a34440af71131f0c884b08ccec7883998ea2edd |

## Members
- **DST-M4.** The S4U memory guard compares process CreationDate as UTC instants, at 9 sites. Defender verdict: PASS-WITH-NOTES; its should-fix (PID-reuse ancestry cases) is applied.
  - No re-registration and no hash pin: the next one-minute guard run uses the merged file.
- **DST-M5/M6.** Push containment, rollback waits, the suite-gate wait and the adoption wait now hold their deadlines as instants. Defender verdict: PASS-WITH-NOTES; no behaviour change on ordinary nights.
- **Defender follow-ups:**
  - a status.ps1 DateTimeOffset coverage test;
  - one line in the #267 N4 runbook.
- **Integration commit (the M5/M6 merge):**
  - Additive conflicts in the DST test file and the audit doc are resolved by keeping both sides.
  - It adds DST-L15 (Scheduler `LastRunTime` ordering; fails closed; recorded, not fixed) and rewrites the section-5 row for M4/M6.

## Landing constraints
- **Land alone or as the last head of its night.** Integration-attempt manifests freeze the sha256 of `quiet_window_merge.ps1`.
- **Check the legacy bootstrap first (read-only).** Before landing, confirm no scheduled task still runs `suite_gated_quiet_merge.ps1` with `-ExpectedGateSha256`.
- **The bounded suite includes the reconciler file (~19 min).**
- **Deadline:** M4 and M5/M6 must land before 2026-11-01 01:00 EDT.

## Checks
- landing_preflight (`--tests none`): the only FAIL is `correspondence_index --check`, which is also rc 1 on master 8ea5d089b (by design).
  - `--check-structure`: OK.
  - agent_docs_audit: PASS.
- Merge-tree: each member merges clean alone on 8ea5d089b.
- STATE_OF_PLAY.md and cold-snapshot-compression.md are untouched.

## Not in plan
- LFC fe5f54cfa (held; journal_pinned_touch: wallet_reader_client.py).
- U6 D6 07dd78252 and inventory f22bea073 (build line).

## Owner
OD30 retirement is still the owner's decision.
