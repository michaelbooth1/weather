# Workstation handoff — 2026-08-01b: consolidate the release path, then rehearse it

Plan of record: `docs/roadmap/lock-readiness-plan-2026-08-03.md`. Read it first; this handoff is
workstreams 1 and 3 of it.

**The lock is real and close.** I ran your release-admissibility clock from a worktree against live
production evidence today:

```text
contiguous_pass_days : 10
streak_start_date    : 2026-07-21
latest_status        : PASS (release_admissible)
```

Every day 07-21 → 07-30 grades `release_admissible`, **including 07-24**. Both clocks agree at 10 from
the same start date. So the lock lands **2026-08-03** if the next three days stay clean, and the 7-day
build window runs to about **08-10**.

(Root paths, since they cost me a cycle: `--snapshots-root data/snapshots` and **`--ledger-root
data/settlements`** — not `data/backtest`, which fails every day with `settlement_ledger_missing`.)

## Mission 1: one branch, not three

Three unmerged branches are release-critical, and **all three touch the same roll-sensitive files**
(`snapshot_store.py`, `schema_registry_recent_data.py`):

- `codex/workstation-second-clock-bootstrap-2026-07-30f-keystone` — `release_admissibility_clock.py`
  and `all_shadow_release_bootstrap.py`, i.e. the release builder itself;
- `codex/workstation-release-one-blockers-2026-07-29`;
- `codex/workstation-strict-parity-2026-07-29`.

Roll-sensitive merges only happen 01:00-04:00, about two a night. Tonight's slots are taken by the
monitor and frontier branches. That leaves four slots on 08-01 and 08-02 for three branches that will
conflict with each other — three fleet rolls in the 48 hours before the lock, each able to cost a
streak day. That is the wrong shape of risk this close in.

So: **rebase all three onto current `origin/master` as a single stack and hand back one mergeable
branch.** Resolve the conflicts on your side where nothing is at stake. Requirements:

- full suite green on the **combined** tree, not on each branch separately;
- an explicit list of every conflict you resolved and what you chose — I am merging this blind into a
  system three days from a lock, so I need to know where you exercised judgement;
- confirm the roll-sensitive file set of the combined branch so I can time it;
- do **not** fold in warm-tier, skill-gap or hardening. They are not lock-critical and they only add
  conflict surface.

If any of the three turns out to be already-absorbed or dead, say so and drop it — five of the fifteen
unmerged branches are just handback reports whose code already landed, and I would rather retire them
than carry them.

## Mission 2: rehearse the build before the lock spends the window

Nothing past preselection has ever run on real evidence, and the lock opens only a **7-day** window.
Any failure we discover on 08-04 is paid for out of that window; any failure we discover this week is
free.

Build a **throwaway prelock from current evidence** and run the entire path end to end to a
research-only, all-shadow release: preselection → lock → candidate fit → locked replay → PIT →
promotion qualification → immutable training-graph verification.

Report the **first thing that breaks**, honestly, rather than a green summary. A rehearsal that finds
three real failures is worth far more to me than one that reports success. If it runs clean the whole
way, say that too and tell me what the rehearsal could *not* cover.

Constraints: throwaway artifacts under your declared run root, nothing that could be mistaken for a
real prelock, and no pointer, promotion or serving change.

## What I am doing on my side

Wiring the clock into daily ops once Mission 1 lands, pre-staging the lock-day checklist, and deciding
the disk question — free space runs out around 08-08/08-09 while the build window runs to 08-10, so
the window currently gets truncated by about two days.

## Priority

1 first — it is on the critical path and it gates my merge scheduling. 2 is the highest-value thing
you can do with the remaining time before the lock.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, no paid-provider change, never read or expose
the sync credential.

Note `2026-07-31` is a regime boundary (the floor fix went live at 01:15), and the non-strict
`rows[-1]` removal changes candidate replay and corpus regeneration on degraded rows — **regenerate
both sides, never mix artifacts across that boundary.** That applies to the rehearsal too.

## Handback

`docs/roadmap/agent-report-<date>-workstation-release-consolidation.md`: the consolidated branch with
its conflict log and roll-sensitive file set first, then the rehearsal's first failure (or its clean
run plus what it could not cover). Push before you start and again at handback.
