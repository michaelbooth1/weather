# Deep audit 2026-09-29 — exam executability, disk, security, docs, merge queue

**Verdict: the signed replay exam cannot execute as frozen (structural, fixable); disk runs out before the panel ends;
security is clean in tracked content with one host-side token risk.** Seven read-only auditors (exam integrity,
integration code review, production operations, documentation truth, merge queue, strategy and evidence, security) ran
2026-09-29 17:10-18:00 on the production host. Claims marked (V) were re-verified by the production agent in code or
data. Owner decisions the same evening: approve Clarification 2 drafting
([draft](../../research/maker-replay-clarification-2-2026-09-29.md)), the competitor-reaction diagnostic (111f),
GitHub protections (owner action), and disk relief (111g, 91a registration). Handoffs 111e, 111f, 111g.

Correction recorded here: an earlier same-day claim of a two-week "exam source freeze" was wrong (finding 3).

Seven Fable auditors (exam integrity, integration code review, production ops, docs truth, merge queue, strategy/evidence,
security), read-only, 17:10-18:00. Key claims re-verified by the production agent in code/data where marked (V).

## Exam (maker-replay-2026-10-15-v1)
1. (V) Nightly bundles unreadable: maker_replay_night.py:159 writes active_intervals; bundle.py:249 exact key set -> unexpected_fields.
2. (V) Manifest build needs 14 panel days + 10-14 (execution_manifest.py:114): enrolment ~10-15, not 09-30.
3. (V) source_hashes recorded at build, checked at run (__main__.py:110-112): no two-week freeze; code may change until build.
4. (V) reserve_attempt precedes comparison_report (__main__.py:113-114): any refusal inside scoring spends the only look.
5. No calibration-bundle producer (calibrate() refuses other kinds; bundle doc says production evidence owner prepares them).
6. Frozen ceilings (64 MiB / 100k records / max_events 500k) likely 50-100x below real 88a volume; unmeasured.
7. Nightly export refuses after any master commit (ExpectedSourceTip == HEAD) and on live-file growth; provider rebuild per minute.
8. Replay reward accrual cannot see competitor reaction (RE-1: share collapse in 2-4 min, ~10x); k=0.5 sensitivity. PASS optimistic, FAIL credible.
9. No minimum effect of interest; 12 market clusters cap power; a low-power null prints HURDLE_NOT_MET, not UNDERPOWERED.
10. One-sided candidate's directional signal is a latency race 60 s books cannot adjudicate; fill endpoint likely underpowered.

## Operations
11. (V) Disk ~11 GB/day net on a clean day (09-26->27 80.8->70.0 GiB); watchdog 7.1 includes one-offs. 50 GiB ~10-03.
12. Journal task runs unmerged code, undocumented in inventory/docs (deployed by owner instruction 17:06).
13. 26 spent disabled tasks registered; WeatherColdSnapshotNightly in inventory but not registered; stale worktrees.
14. Nightly 05:00/06:00 tiering skipped if the lease runs past 04:55.

## Security
15. Plaintext repo-scoped gh token (insecure storage) + master unprotected + secret scanning/push protection off on a public repo.
16. S4U deployed-worktree pins are self-attesting in user-writable folders (detect drift, not a same-user writer).
17. .gitignore lacks *.cred, *.key, *.pem, *.pfx. No secrets found in tracked content on master or 44 PR branches.
18. Order mutation unreachable by any task/agent; no CLOB credentials stored on this host; US adapter refusal (#139) pending.

## Docs
19. STATE_OF_PLAY stale on watchdog, Stage-A, 110x, 5f/5g, freeze/exam timing, master tip.
20. Codex-hook enforcement described in AGENTS.md/HOST_LOAD_POLICY does not exist for Claude Code sessions (no hooks configured).
21. Handoff/report pairing gaps (110e, 110p, 111d without handoffs; 110f without report).

## Merge queue
22. #132 carries #110 (close #110 after). Stacked exam PRs will not auto-close. #129 has a real schema-row conflict with #134.
23. #140 (110o part 10) CI red: real regression (item 160 expected active). #141 changes the index generator: land last.
