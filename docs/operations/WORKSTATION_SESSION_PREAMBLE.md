# Workstation session preamble

**Read when:** a prompt tells you to read this file. It is the standing preamble for every Claude Code
session the owner starts on the workstation for a delegated mission. The mission itself follows in the
prompt, usually as "read handoff X and do it".

## Where you are

You are Claude Code on the owner's **32 GB workstation**, not the 16 GB production capture host. The
capture-host rules in `CLAUDE.md` and `AGENTS.md` (time windows, the bounded suite, the shared lease) do not
bind you. Focused pytest of at most 25 files with no `serial`-marked test (until that marker exists: no file
that starts PowerShell) runs directly, with an explicit `--basetemp` deleted afterwards. Full suites, larger
selections, xdist, compileall, training and replay go through `scripts\ops\workstation_heavy.ps1`, which is to
queue them in order (the queue is a follow-up; until then poll at most once a minute)
([host load policy](HOST_LOAD_POLICY.md), owner decision 2026-10-04). Other Claude sessions may be running
missions in parallel in this same clone.

## Before you start

1. `git fetch origin`.
2. Read `AGENTS.md`, [the state of play](STATE_OF_PLAY.md) and [the delegation contract](DELEGATION_CONTRACT.md);
   §2 of the contract binds every mission.
3. Read the handoff the prompt names, from the ref the prompt names (`git show <ref>:<path>` if it is not on
   `origin/master`).
4. Create your **own** worktree (set `GIT_LFS_SKIP_SMUDGE=1`) on the branch the handoff names. Never work in
   another session's worktree or push to another session's branch.

## Scratch space

- Put every worktree and temp directory of the session under `C:\wt\<session-name>\` (for example
  `C:\wt\<session-name>\wt` for the worktree and `C:\wt\<session-name>t` as pytest `--basetemp`). Never
  use `C:	mp`: the owner cleared it on 2026-10-04 without knowing it held other sessions' worktrees.
- Never delete, move or lock anything outside your own session folder. Space is freed from a list the owner
  approves: `scripts\ops\workstation_space_report.ps1 -JsonPath <json>` (read-only; a SAFE, IN USE or
  CHECK verdict per worktree and scratch folder) then `scripts\ops\workstation_space_clean.ps1 -FromReport
  <json>`, which lists by default and removes only still-SAFE items with `-Apply`. The scratch roots it
  reports are `C:\wt`, `C:\pt`, `C:\swarm`, `C:	mp`, `C:t` and the Claude Code scratchpad root
  `%TEMP%\claude`; older sessions used the others.

## Boundaries

- Fixtures only: no production data, credentials, `.env` files, Scheduler changes or venue calls. Nothing
  places, cancels or signs orders.
- Push and draft PRs are authorized. Never force-push, rebase a pushed branch or rewrite history; bring a
  branch up to date by merging `origin/master`.
- Run focused and affected tests plus the repo-wide audits (schema registry, imports, agent docs, path
  policy, module size). The PR's CI is the full-suite evidence, except that a change touching a
  Windows-executing script still needs a local full suite until CI has a Windows lane for those tests
  ([development.md](../development.md#verification-scope-and-assertion-strength-owner-decision-2026-10-04)). Wait for the PR's full GitHub CI to finish
  green. Fix the real cause of a failure, never by weakening a test.

## Finishing

At END SESSION remove your own worktree (`git worktree remove`, after the branch is pushed) and your temp
directories, then say in the handback which paths you removed and anything you deliberately left.

Write the report the handoff names (verdict first, per [delegation contract](DELEGATION_CONTRACT.md) §5),
push it with the branch, then reply with: the report path, the PR link(s), the head SHA(s) and the CI
conclusion. The owner pastes that reply to the production agent, which verifies before anything merges.

## Update this file when

The workstation's role, its heavy-command wrapper, or the standing session boundaries change. Mission
content belongs in handoffs, never here.
