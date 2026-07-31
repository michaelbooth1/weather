# Workstation handoff — 2026-07-31f: the floor is fixed, so the frontier moved

The floor fix is **live in production**. Merged `42749c98` at 01:15, capture readopted cleanly, pushed
01:20. Streak is **10/14**, Jul 30 graded complete, lock still ~Aug 3. What we serve is now `1.498x`
market instead of `1.664x`, for real, not in a harness.

Your rejection of my redistribution hypothesis is accepted and it is the better answer. The equality
slice has a *lower* regression rate (26.68% vs 44.53%) but a ~41x larger mean loss when it does
regress — that is a **severity** mechanism, not a count mechanism, and my "renormalization pushes mass
away from the truth" story was wrong about the general case. You applied the stopping rule exactly as
written and stopped. That is three of my theories killed in four cycles, all with numbers. Keep doing
it.

Also accepted: the non-strict `rows[-1]` confirmation with the full caller list, and the warning that
candidate replay and corpus regeneration change on degraded rows so **both sides must be regenerated
rather than mixed across that boundary**. That note is going into the lock checklist.

## Mission 1: make the monitor loud, not fatal — until the lock

You built exactly what I specified, and my specification was wrong for the next four days.

`hard_stop_pipeline=true` as a critical non-skippable dependency of `settled_day_analysis_barrier`
means a `BLOCK` stops the daily chain. We have been bitten by precisely this: a single transient
failure on one non-streak market hard-stopped the chain at step 20/43 and silently killed a day's
learning and settlement. A missed chain day leaves a **permanent settlement hole** — each run settles
only yesterday — and that is exactly how a streak day gets lost.

Your `BLOCK` conditions are broad by design: evidence missing, malformed, duplicated, mismatched, or
lacking floor provenance. Those are the right conditions for a release gate and the wrong ones for a
system that is four days from a lock it has been chasing since June.

Weigh the two failure modes. A missed over-final floor costs us *analysis*, on a paper bot with **no
capital at risk**. A lost streak day costs the release timeline, which is the thing the operator
actually wants. So:

- default the monitor to **ALERT-only**: run every day, compute everything, report `ALERT`/`BLOCK`
  status, surface it in daily status and the rollup, but **do not** set `hard_stop_pipeline` and do
  not gate the barrier;
- put the fail-closed behaviour behind an explicit config flag, defaulting off;
- keep an `ALERT` maximally visible — it should be impossible to miss in the daily digest.

I will flip the flag on the day the lock is secured. Do not soften the detection logic, only its blast
radius. Note this in the docs as a deliberate, dated, temporary posture with the reason, so nobody
later reads it as the monitor being optional.

## Mission 2: re-decompose the gap — the old map is stale

Here is what your own hour table implies, and it is the most useful thing in the report.

The floor fix delivered almost all its gain late in the day: F `-0.01657` at 15-17 and `-0.01630` at
18-23, but only `-0.001538` at 09-14 — about **2.2% relative**. Toronto is worse: `-0.000776`, about
1.2%. And `floor == settlement` is 100% after 18:00, 81.5% at 15-17, but **12.4% at 09-14 and 0.00% at
03-08**.

So the floor mechanism is *exhausted* in the morning. There is nothing observed yet to floor.

That matters because our **adopted primary objective is the 09:00-14:00 slice** — chosen deliberately
over aggregate-Brier chasing. Measured against the objective we actually adopted, this fix bought
roughly 2%. Measured against an all-hours average it looks like a triumph. Both are true; only one is
the goal.

The standing decomposition said hour-20 evening lock-in was the widest gap. **We just fixed evening.**
That map no longer describes the territory.

So re-run the decomposition against current production behaviour and tell me where the excess loss
lives *now*:

1. candidate-versus-market excess loss by local-hour group, post-fix, for Toronto and the F family
   separately — where is the remaining gap concentrated?
2. within **09:00-14:00** specifically, decompose it: how much is resolution versus reliability, and
   what share is attributable to each named source or stage?
3. what is the largest single identifiable contributor in that window, with its magnitude?

No hypothesis from me this time. Three of mine are dead; the measurement should pick the next target,
not me. Report what the decomposition says even if it points somewhere inconvenient or boring.

## Mission 3: build the C admission patch now, inactive

Your scope is accepted, including the recommendation to run the C candidate only after the lock and
the finding that release #1 does **not** require it — the all-shadow bootstrap can bind Toronto's
incumbent with its seven existing components.

But prerequisite 1 — a reviewed `C` entry point in the pooled trainer, promotion-refresh CLI, and
family-secondary trainer — is control-plane only, candidate-only, inactive, and needs **no serving
change**. There is no reason for it to wait behind the lock and then add days to the critical path.

Build it now, on its own branch, with the proof you already named: that it does not alter the `F` lane.
Then it is ready the moment the lock lands.

Do not build the prelock, the candidate fit, or the locked replay — those consume lock-day evidence and
they wait.

## Priority

1 first and today — it changes risk on a system that is four days from a lock. 2 is the skill work and
is where I expect the next real gain. 3 is parallel and removes post-lock latency.

Still deferred: MM, cold tier and the 500 GB cap, pointer creation.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, no paid-provider change, never read or expose
the sync credential. POST-regime numbers only.

`schema_registry_recent_data.py` is roll-sensitive, so the monitor merge is mine to time and will go in
a quiet window.

## Handback

`docs/roadmap/agent-report-<date>-workstation-frontier.md`: the monitor posture change first, then the
post-fix decomposition with the 09:00-14:00 breakdown and the largest identified contributor, then the
C admission patch and its `F`-lane-unchanged proof. Push before you start and again at handback.
