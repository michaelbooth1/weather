# Workstation handoff — 2026-08-02a: check the real lock window for your own findings

The synthetic rehearsal is exactly what I asked for, and it is merged (`5d095187`). You got the
expensive middle of the path to run on real-shaped data, you found a real defect, and — most
importantly — **the safety properties held**: `qualify-production` refused the marked synthetic lock
before replay and created no PIT artifacts, and the production verifier independently refused the
same file the lightweight reader accepted. A rehearsal whose synthetic input *cannot* masquerade as
evidence is the only kind worth having.

I verified your one real defect myself rather than taking it on trust.
`point_in_time_evaluation.py:1111` folds two unrelated conditions into one message, so an empty
manifest raises `market-day bound exceeded: 0 > 60`. Confirmed, and your classification is right.

## The mission: your June findings, re-run against the dates that actually matter

This is the highest-value pre-lock work left, and it comes straight out of your own report.

You found three defect classes — but every instance was in **June**, and the lock window is
**`2026-07-21` through `2026-08-03`**. Your synthetic universe never covered those dates, so we do not
know whether the lock window is clean. Each of these **fails the build** if present:

1. **Duplicate pinned replay identities** — you hit these in seven folders (`06-17`, `06-18`, `06-19`,
   `06-20`, `06-22`, `06-25`, `06-28`). The bounded reader refuses on the first duplicate. One
   duplicate anywhere in the lock window stops the real build.
2. **`too_few_replay_inputs`** — `06-01`, `06-02`.
3. **F-family training-corpus coverage gaps** — `06-15`, `06-16`, `06-18`, `06-24`, `06-25`, `06-26`,
   which pooled fitting refused.

**Sweep `2026-07-14` → `2026-08-03` for all three, read-only, and give me a per-date table.** Include
07-14 onward rather than just the window so I can see whether the problem is aging out or spreading.
If the window is clean, say so plainly — that is a genuinely valuable result and it is what I expect.
If it is not, that is a lock-day blocker found for free, and I want it in my hands on 08-02, not
discovered mid-build.

Then, if and only if the sweep is done: fix the `0 > 60` diagnostic on the same branch. Split the
condition so an empty manifest says it is empty. **Declare the roll footprint** —
`calibration/residual_distribution_v1.py` imports that module, which puts it on the calibration path,
so I must treat the merge as roll-sensitive and time it. Keep it to the message; do not restructure
the bounds logic before a lock.

## What I took from your report and acted on

Your timing numbers went straight into `docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md` as a new
budget section, because "tens of minutes, not seconds" is the single most useful operational fact in
the handback. Recorded: pooled fit 1,499 s, family graph 1,853 s, frozen replay 915 s — a ~71-minute
no-retry floor, and you burned two extra family fits (1,769 s and 1,578 s) before a pass. The runbook
now says to budget hours and expect a retry cycle.

## One correction

You reported that "main's existing `config/storage_pressure.json` modification remains untouched."
On the production host that file is **clean** and was last committed in `6312e88d`; the only modified
tracked files are the two auto-refreshed location configs. So that modification is local to your
clone, not main's. Worth resolving on your side, because it is not a state master is in.

That matters more than it sounds: any dirty file under `config/` fails the release build's
clean-source-tree gate. See `RELEASE_ONE_BUILD_RUNBOOK.md` §1 and handoff `-08-01d`.

## Not now

The five items you listed as unexercised are all genuinely gated on the real lock — I am not asking
you to simulate them further. Also still deferred: MM promotion-gate relaxation, C prelock/fit/replay,
cold tier, pointer creation, warm tier, hardening branch. Disk stays parked by operator decision.

## Guardrails

Unchanged. `data/` read-only, outputs under one declared run root outside the mirror, topic branches
only, no PR, no merge, no master push, no promotion, no pointer change, no serving change, no
scheduler/capture/mirror/ACL change, never read or expose the sync credential. Start from
`origin/master` at `5d095187` or later.

## Handback

`docs/roadmap/agent-report-<date>-workstation-lock-window-sweep.md`: the per-date table for all three
defect classes across `2026-07-14` → `2026-08-03`, a plain clean/not-clean verdict for the lock
window, then the diagnostic fix with its declared roll footprint. Push before you start and again at
handback.
