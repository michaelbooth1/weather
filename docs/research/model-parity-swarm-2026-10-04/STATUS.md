# Model-parity swarm v2 — STATUS

**Phase:** 0 (preflight) running — started 2026-10-04 00:20 local. All numbers here are development.

- Owner approval: confirmed in the workstation chat (Workstation Chat) at ~00:10 local.
- Worktree `C:\pt\swarm`, branch `codex/model-parity-swarm-20261004` = origin/master + merged
  `origin/codex/guidance-all-hours-analysis-20261003` (fast-forward to 0206f4d1).
- 111h extract found at `C:\Users\Michael\Documents\nbm-guidance-111h` (not `data\exports\...`);
  SHA256SUMS: all 3 match; manifest COMPLETE; parser head 2e17ce0eb; 110,807 rows / 626 market-days.
- Orchestration: one Workflow run (wf_247e1179-a53), dependency-driven: P0 -> F1/F2/F3 + 10 acquirers
  (IEM lane split into 4 sequential agents) -> hunters T1-T17 as their manifests land -> refuters per
  LEAD (max 6 families, first 6 refuters on Fable) -> T18/T19/T20 -> spares T21-T26 -> deep dives ->
  synthesis (critic on Fable). ~60 agents.
- Disk: C: 83 GB free at start; STOP if C:\swarm > 70 GB or C: free < 15 GB.
- Data lives in `C:\swarm` (never in the repo). Design copy: `C:\swarm\DESIGN.md`.
