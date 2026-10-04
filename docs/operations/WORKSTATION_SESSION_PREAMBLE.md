# Workstation session preamble

**Read when:** a prompt tells you to read this file. It is the standing preamble for every Claude Code
session the owner starts on the workstation for a delegated mission. The mission itself follows in the
prompt, usually as "read handoff X and do it".

## Where you are

You are Claude Code on the owner's **32 GB workstation**, not the 16 GB production capture host. The
capture-host rules in `CLAUDE.md` and `AGENTS.md` (time windows, the bounded suite, the shared lease) do not
bind you. Instead, run heavy commands (pytest beyond a few files, compileall, training, replay) through
`scripts\ops\workstation_heavy.ps1` ([host load policy](HOST_LOAD_POLICY.md)). Other Claude sessions may be
running missions in parallel in this same clone.

## Before you start

1. `git fetch origin`.
2. Read `AGENTS.md`, [the state of play](STATE_OF_PLAY.md) and [the delegation contract](DELEGATION_CONTRACT.md);
   §2 of the contract binds every mission.
3. Read the handoff the prompt names, from the ref the prompt names (`git show <ref>:<path>` if it is not on
   `origin/master`).
4. Create your **own** worktree (set `GIT_LFS_SKIP_SMUDGE=1`) on the branch the handoff names. Never work in
   another session's worktree or push to another session's branch.

## Boundaries

- Fixtures only: no production data, credentials, `.env` files, Scheduler changes or venue calls. Nothing
  places, cancels or signs orders.
- Push and draft PRs are authorized. Never force-push, rebase a pushed branch or rewrite history; bring a
  branch up to date by merging `origin/master`.
- Include the repo-wide audits (schema registry, imports, agent docs, path policy, module size) in your
  test runs, and wait for the PR's full GitHub CI to finish green. Fix the real cause of a failure, never
  by weakening a test.

## Finishing

Write the report the handoff names (verdict first, per [delegation contract](DELEGATION_CONTRACT.md) §5),
push it with the branch, then reply with: the report path, the PR link(s), the head SHA(s) and the CI
conclusion. The owner pastes that reply to the production agent, which verifies before anything merges.

## PROPOSAL (not in force)

> **Owner decision pending (test-suite review K, 2026-10-04).** The text above governs until approved; see
> [test-policy-proposals.md](../research/test-suite-review-2026-10-04/test-policy-proposals.md) (P4).

- *Where you are* would read: focused pytest of at most 25 files with no `serial`-marked test runs directly
  (explicit `--basetemp`, deleted afterwards); full suites, larger selections, xdist, compileall, training and
  replay go through `scripts\ops\workstation_heavy.ps1`, which queues them in order.
- *Boundaries* would read: run focused and affected tests ([development.md](../development.md)); the PR's CI is
  the full-suite evidence; wait for it to finish green.

## Update this file when

The workstation's role, its heavy-command wrapper, or the standing session boundaries change. Mission
content belongs in handoffs, never here.
