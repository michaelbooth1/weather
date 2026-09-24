# Host, model and operations audit — 2026-09-24

- **Owns:** the 2026-09-24 independent read-only review of the non-maker side (forecast model, logging, RAM/CPU, storage,
  scheduled fleet, settlement, repository health) and the production agent's dispositions.
- **Read when:** planning disk recovery, observability fixes, the learning lane, or the model's next step.
- **Do not use for:** current state (`docs/operations/STATE_OF_PLAY.md`).

**Verdict (auditor, verified by the production agent where marked):** capture is healthy (0.0 min max gap, all loops on
master, commit 41.7% of 32.5 GB, no leak), but the instruments mislead. Top risks: (1) **disk below the floor at its true
low** — 43.2 GiB at 21:50 09-23 (verified), 45.7 GiB at 12:35 09-24; System Restore shadow storage 15.4 of 18.6 GB with three
restore points (verified) drives 12-13 GiB purge steps; (2) **the Stage-A learning lane has not run since 2026-08-13** — the
settled-day barrier is blocked by maker gates (`exchange_economics_rule_drift`, `maker_paper_score`) (verified barrier state),
so `daily_learning`, the model-vs-market scoreboard and the retention inventory are stale; (3) signal buried — ~110 spent
one-shot tasks, sweep CRITICALs not in `status.ps1` flags, no reward-capture freshness check, a retired marker still flagged;
(4) Defender (no exclusions) and Windows Search indexing the repository tax the capture volume; (5) the signed band parser
(`016e1c92c`) is not on master and "item 335" does not exist.

| # | Sev | Finding | Disposition |
| --- | --- | --- | --- |
| 1 | Critical | True daily low 43.2 GiB; System Restore oscillation | Docs corrected (`6abbb3e5b`); **owner approved 09-24:** shadow storage capped at 2 GB (+10.7 GiB, one restore point kept) |
| 2 | High | Learning lane blocked by maker gates since 08-13 | Agent: reorder so learning/retention/scoreboard do not sit behind maker gates (roll verdict first); owner: paper-evidence rescore semantics |
| 3 | High | No reward-capture freshness; sweep CRITICALs not flags | Agent: roll-free `.ps1` changes to `staleness_sweep.ps1` and `status.ps1` |
| 4 | High | Defender no exclusions; Search indexes the repo (1.46 GB index) | **Owner approved 09-24:** Windows Search disabled and index removed (+1.7 GB); Defender excludes `data\` |
| 5 | Medium | ~110 spent one-shot tasks; noise | Agent: unregister with a receipt (role §4 task authority) |
| 6 | Medium | Boot recovery runs from a month-old worktree while the merge tool changed | Agent: choose the authoritative tip and re-register after a read-only check |
| 7 | Medium | Signed band parser not on master; bad item citation | Agent: rebase onto its own roll-verdicted branch; fix the citation |
| 8 | Medium | Paper maker roll writes ~0.8 GiB/day while BLOCKed daily; finalize re-revises all history daily | **Owner 09-24: paper roll paused** (retiring the old maker; tasks disabled, receipt in `data/alerts`); agent on the finalize fix |
| 9 | Medium | Console logs and watchdog log grow unrotated; 4.6 GB rotated archives | Agent: bounded rotation (roll-free where possible); archive the rotated files |
| 10 | Medium | status.ps1 ignores retirement receipts; EF §10b trough model stale; doc transaction overdue | Agent |
| 11 | Low (unverified) | Market-informed overlay variants flagged `active_for_headline` | Agent: trace one headline read before citing any headline figure |
| 12 | Low | 223 worktrees inside the indexed tree | Agent: prune clean merged candidates with receipts; new worktrees outside the indexed tree |

**Model:** the June HGB pickles are served (102 days old, out of season, cool-biased, no NBM column); parity and replay
contracts are intact. NBM layers 2-3 then the baseline board is the right forecast order, but the highest-value deliverable
for the owner's goal is the timing outputs (89b observation clock and band-decided estimator), which need no retrain or roll.

**Sound:** capture loops and supervisors, pagefile and commit guard, priority guard, WU restore and labels finalize for 09-23,
the roll-verdict/quiet-window/OneShotPush discipline, the hash-pinned watchdog, 06:00 raw-tape tiering, the serving floor, the
crossed-clustering and α rules, the no-second-disk decision with compress-and-retain.
