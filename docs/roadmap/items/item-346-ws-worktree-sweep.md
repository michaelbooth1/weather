# 346. Scripted Daytime Sweep Of Old Workstation Worktrees [OPEN 2026-11-05 - WS BACKLOG; DRY-RUN LIST TO MASTER FIRST]

Goal: reclaim disk on the 32 GB workstation from old `C:\wt` worktrees (about 150 of them, about 60 GiB) with a
scripted, reviewable sweep that never loses unmerged work, ignored data or research output.

Owner/package: workstation tooling (a script under `tools/` or `scripts/ops/`), WS lane; master reviews the dry-run
list before anything is removed. Standing scratch-space rules:
[workstation session preamble](../../operations/WORKSTATION_SESSION_PREAMBLE.md#scratch-space).

Source: WS coordinator, 2026-11-05.

Why this matters: `git worktree remove` also deletes IGNORED files, so a worktree's `data\` directory is lost with it
(WS run lesson 2026-11-05). A hand sweep has no record and no safety check.

Checklist:

- [ ] Dry run first: list every candidate with its HEAD, ancestry result, `git status --porcelain --ignored` result
  and size; send the list to master for review. Nothing is removed in the dry run.
- [ ] Remove a worktree only if BOTH hold: its HEAD is an ancestor of `origin/master`, AND
  `git status --porcelain --ignored` is empty (known caches excepted, listed by name in the script).
- [ ] Research outputs go archive-first to `C:\archive\ruled-out\<id>` with an `INDEX.md` line (owner 10-30: keep
  everything ruled out); only then may the worktree go.
- [ ] Daytime only, light (no heavy lease needed), one worktree at a time, with a per-run receipt of what was removed.

Acceptance: master accepts the dry-run list; the applied run's receipt matches it; no worktree with unmerged commits
or non-cache ignored files is removed.
