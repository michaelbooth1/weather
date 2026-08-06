# Telling a never-dispatched mission from a completed one

Status: canonical method. Written 2026-08-06 for the production/briefing agent.

The 2026-08-05 morning briefing recorded, about two commissioned missions:

> From this host the two cases are indistinguishable: doc committed, no branch.

**They are distinguishable.** "No branch on origin" is ambiguous because branches are deleted
after merge, so absence of a branch is evidence of *either* completion *or* non-dispatch. The
discriminator is not the branch — it is the branch **together with** three other records.

## The four states

Evaluate a handoff `workstation-handoff-<date><letter>-<slug>.md` against all four columns.

| Branch on origin | Report on master | In deletion manifest | Withdrawn in a later handoff | State |
| --- | --- | --- | --- | --- |
| yes | — | — | — | **dispatched, in flight or awaiting merge** |
| no | yes | — | — | **completed**, branch deleted after merge |
| no | no | yes | — | **completed or superseded** — read the manifest's disposition column |
| no | no | no | yes | **withdrawn** — not a leak, a decision |
| no | no | no | no | **never dispatched** — the only true leak |

## The four records

1. **Branch:** `git branch -r --list "*-<date><letter>"`.
2. **Report on master:** `docs/roadmap/agent-report-*<slug>*.md`. A report on master is proof
   the mission ran and was accepted, regardless of whether its branch still exists.
3. **Deletion manifest:** `docs/operations/deleted-branch-recovery-manifest-2026-08-05.md`
   carries every ref deleted in the 08-05 cleanup with its commit hash and a disposition
   sentence. A slug appearing there was dispatched.
4. **Withdrawal:** `git log --all --oneline --grep="<date><letter>"`. Missions are withdrawn
   in the *next* handoff's commit message, never by editing the published handoff
   (`docs/roadmap/AGENTS.md`: never edit a published handoff or report).

## Worked reconciliation, 2026-08-06

Applying the table to all 28 handoffs in the `-09-*` series:

| Mission | Verdict | Evidence |
| --- | --- | --- |
| `-09-02a` front-end cleanup | completed | merge commit `aa1b5248` |
| `-09-03a` train/serve parity gate | completed | deletion manifest: "carried forward into `-09-12a` (KEPT)" |
| `-09-23a` bind the year set | **withdrawn** | `e8022335` "withdraw the duplicate work" |
| `-09-09a` complete the age curve | **never dispatched** | no branch, no report, not in manifest, not withdrawn |

**`-09-09a` is the only true dispatch leak in the series.** Its premise has since died
independently: the age-curve evidence for the cool bias was retracted on 2026-08-05
(`RETRACTED_AND_FALSE_LEADS.md`). It should be formally withdrawn rather than relayed.

So the leak rate is **1 of 28**, not the systemic gap the 08-05 briefing implied. That
matters: the briefing's framing would have justified building dispatch-tracking machinery to
solve a problem that four existing records already solve.

## Standing instruction for the briefing agent

Do not report a mission as "never dispatched" on the strength of a missing branch alone.
Check all four records first, and name which one settled it. If a mission is genuinely
never dispatched, say so **and** state whether its premise still stands — a leaked mission
whose finding has since been retracted should be withdrawn, not relayed.

## Update this file when

The set of records changes — a new deletion manifest, or a change to how withdrawals are
recorded.
