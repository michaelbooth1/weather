# Workstation handoff 2026-09-110d — close superseded pull requests (owner-approved clean-up)

Written 2026-09-25 by the production agent. The owner approved the GitHub hygiene review's recommendations
(`docs/roadmap/audits/github-hygiene-review-2026-09-25.md`, landing tonight). The production host has no `gh` and no API
token; use `gh` on the workstation. **Close PRs only; never merge, never delete branches, never force-push.** Branch
deletions are done afterwards by the production agent.

Already done on production (2026-09-25 ~23:15): 32 never-pushed local branches pushed; 21 stale unmerged branches tagged
`archive/<name>` (verified on origin) and deleted; tag `archive/wt-stage2-build-20260921`; 62 merged local branches deleted.
Receipts in `data\alerts\git-cleanup-20260925\` on production.

## 1. Close these PRs with `gh pr close <n> --comment "<text>"` (do not pass `--delete-branch`)

**A. Already on master** (#92, #89, #88, #75, #73, #23, #22, #18). Before closing each, confirm
`git merge-base --is-ancestor <head> origin/master`; skip any that is not. Comment: "Closing: this branch was merged into
master locally through the quiet-window/light-path tool (the head is an ancestor of origin/master), so GitHub never
registered the merge. No content is lost."

**B. Contained in a newer tracked branch** (#6, #13, #21, #24, #25, #26, #27, #28, #40, #41, #42, #49, #50, #51, #53).
Confirm each head is an ancestor of `origin/codex/stage2-hold-build-20260921` or `origin/codex/re1-wallet-200-20260923`
(#13: tree identical to the archived 98a branch); skip any that is not. Comment: "Closing as superseded: every commit here is
contained in a newer tracked branch (codex/stage2-hold-build-20260921 or codex/re1-wallet-200-20260923). The branch is
retained; nothing is dropped." For #6 add: "origin/codex/live-gate-provenance-20260831 remains the execution PC's recorded
lineage and must not be deleted."

**C. September research lineage** (#7, #8, #9, #10, #12, #14, #15, #52). Comment: "Closing without merge: September
workstation research lineage, recorded in ESTABLISHED_FINDINGS §1m as evidence that by design never lands on master. The
branch stays."

## 2. Retarget

`gh pr edit 91 --base master` and `gh pr edit 80 --base master` (their base branches are already merged).

## 3. Do not touch

#95, #96, #94, #91, #80, #81, #74, #38 (live), and the owner-decision group (#78, #82-#85 RE-1 chain; #45, #64, #66, #67,
#69-#72 storage/qualification stacks; #54, #55; #29, #30; #65, #68; #86, #90, #93).

## 4. Report

`docs/roadmap/agent-report-2026-09-110d-github-pr-cleanup.md`: each PR number with CLOSED / SKIPPED (reason), the retargets,
and `gh pr list --state open` count after. Push the report on a docs branch. Push is authorized.
