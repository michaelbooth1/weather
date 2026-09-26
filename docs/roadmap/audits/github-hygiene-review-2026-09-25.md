# GitHub hygiene review — 2026-09-25

- **Owns:** the read-only review of open pull requests, branches, tags, worktrees and GitHub settings, and the owner-approved
  clean-up that followed.
- **Read when:** cleaning branches or PRs, before deleting any ref, or checking why a PR was closed.
- **Do not use for:** the git workflow itself ([git workflow SOP](../../git-workflow.md)).

Reviewer: Fable read-only subagent (unauthenticated REST reads; no `gh` on production). Owner approved the recommendations
2026-09-25 (DECISION_LOG).

## Starting state

63 open PRs (60 draft; master lands via the local quiet-window tool, so GitHub never auto-closes), 249 remote branches (110
fully merged into master), 270 local branches (32 unmerged ones existed only on the production disk), 208 worktrees
(100 on merged branches), 2 stashes (2026-08-30), no tags, master unprotected, `config/local/` ignored only locally.

## Done (receipts in `data/alerts/git-cleanup-20260925/` on production)

| Action | Result |
| --- | --- |
| Tag the only unreachable worktree commit | `archive/wt-stage2-build-20260921` |
| Delete merged local branches | 62 (`git branch -d`, 0 refused) |
| Push never-pushed local branches (secret-scanned first) | 32 |
| Archive-tag then delete stale unmerged branches (no PR, no canon mention, > 14 days) | 21 `archive/*` tags, branches deleted; `pit-v2-collector-handoff-20260831` kept (holds identity `42657a1f4`) |
| Preserve executed production sources | 6 `deployed/*` tags (`811efd4c2` cold-archive reclaim, four one-shot task sources, watchdog `aa99048ea`) |
| Close superseded / research-lineage / retired PRs (handoff 110d, workstation `gh`) | 39 closed, none skipped; #91 and #80 retargeted to master; 24 open |
| Delete fully merged remote branches (after PR closure) | 110 (each verified an ancestor of master) |
| Remove merged, clean, task-unreferenced worktrees | 90 removed (+5.88 GiB); 2 refused as dirty (`weather-capacity-recovery-20260908`, `weather-stage01-geo-probe-readiness-0823`) |
| Track `config/local/` and `.claude/settings.local.json` in `.gitignore` | landed 2026-09-26 |
| Retire storage-recovery stack (#45, #64, #66, #67, #71, #72) and qualification v2 (#69, #70) | PRs closed; branches kept |

## Still open

- RE-1 PR chain #78, #82-#85: close after RE-1 ends 2026-09-30 (owner).
- Small PRs #29, #30, #54, #55, #65, #68: production agent triage (land or close); #86, #90, #93 stay open.
- Master protection against force-push and deletion (owner, GitHub settings; merges still go through the tool).
- Two 2026-08-30 stashes: owner review before any drop.
- CI: `agent_docs_audit` fails intermittently on master after docs-only light-path merges; the light path now runs the audit.
