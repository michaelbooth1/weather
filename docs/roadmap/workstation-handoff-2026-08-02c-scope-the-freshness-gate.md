# Workstation handoff — 2026-08-02c: your gate was right, my instruction was too broad — start now

**You did the right thing.** Refusing to run on evidence you could not vouch for, and refusing to
reach for the production host or the sync credential to fix it yourself, is exactly the behaviour I
want. Nothing about this handoff is a correction of your judgement.

## The mirror gap is structural, not a fault — and not yours

I checked the production host:

| Event | Time (2026-08-01) |
| :--- | :--- |
| `WeatherDataMirror` ran (success) | **04:30** |
| `2026-07-31` settlement labels written by the daily refresh | **09:49** |

The mirror runs about five hours *before* the previous day settles. **So the mirror can never contain
the immediately-preceding day's labels** — it is permanently ~19 hours behind on settlement, by
schedule design, not by failure. Your observation that it holds zero July 31 labels and that F-market
WU summaries stop at July 30 is exactly correct and exactly expected.

This means a freshness gate phrased as *"is the mirror current to today?"* will **fail forever**, on
every mission, no matter how healthy everything is. That is my fault for writing "refresh your mirror
before you start" as an unqualified instruction after the last sweep. I over-corrected.

Fixing the mirror schedule is a scheduler change I am not making two days before the lock. It is
recorded for afterwards.

## Re-scope the gate, then start

**Gate on the dates your experiment actually reads, not on the mirror's global horizon.**

Both repair lanes target Seattle disagreement cases audited **2026-06-23**. Their replay evidence is
historical June snapshots and settlements, which your mirror has held completely for weeks. Nothing in
either lane needs July 31, August 1, or any date near the horizon.

So: **you are clear to start now.** Concretely —

1. Declare the exact date range each replay reads.
2. Assert every date in that range is present and settled in the mirror, and **fail if any is not**.
3. Ignore the mirror's distance from "today" — it is not evidence of anything about June.

If a lane genuinely needs a date inside the last ~48 hours, stop and tell me, and I will get you that
date specifically. I do not expect that to happen.

## Separately, the mirror is being refreshed anyway

I have scheduled a one-shot `WeatherDataMirror` run for **18:15 today**, after the 12:00–18:00 graded
capture window closes — I would not run a full mirror sync during it, because the I/O contention is a
real risk to the streak day, and the streak outranks your unblocking. After it completes, your mirror
will hold `2026-07-31`, including its F-market labels. Tomorrow's ordinary 04:30 run will then carry
`2026-08-01` as usual.

You do **not** need to wait for it. Start on the June evidence now.

## Everything else in `-08-02b` stands

Unchanged: replay-only, `auto_change_allowed` is false on both lanes, explicit leakage audit before
any number is reported, do not mix artifacts across the `2026-07-31` `rows[-1]` boundary, and **a null
result is a real result** — if a lane does not help, say so and I will retire it.

## Guardrails

Unchanged. `data/` read-only, outputs under one declared run root outside the mirror, topic branches
only, no PR, no merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL
change, never read or expose the sync credential. Do not attempt to refresh the mirror yourself — that
is mine, and you were right to say so.

## Handback

As in `-08-02b`: `docs/roadmap/agent-report-<date>-workstation-repair-replays.md` — per lane, the
exact variant, the declared date range and its freshness assertion, the leakage audit, the measured
effect against both the incumbent and the market, and a plain keep / retire recommendation.
