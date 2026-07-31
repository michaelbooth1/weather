# Workstation handoff — 2026-08-01a: is Toronto's parity real?

Both branches are queued to merge in tonight's quiet window — monitor at 01:15, frontier at 01:50.
Both are roll-sensitive (`schema_registry_recent_data.py`; and `family_secondary_artifacts.py`, which
`toronto_model.py` and `calibration_runtime.py` import), so they are staggered with separate readoption
checks.

The monitor posture is exactly right, the decomposition is clean, and the C admission proof — pooled
band without `--family-unit` still dispatching `unit=F`, both other parsers still defaulting to `F`,
and C selection choosing only Toronto — is the shape of evidence I want for an inactive lane.

Two pieces of discipline worth naming, because both prevented a wasted cycle: reporting the
`current_or_station_max_since_7am` split as **exposure, not causation** (99.49% of snapshots, so its
99.23% gap share means nothing), and reconciling my "~2.2%" against your `8.37%` as a different
denominator rather than letting two numbers sit in the record contradicting each other.

## First: cool the Toronto headline

You wrote "Toronto now slightly beats market," and your own conclusion — "Toronto does not currently
own the primary-window deficit" — is the correct one. But the number will get over-read, so let me put
the caveat in the record before it travels.

`−0.000157` against a Brier of `0.066322` is **0.24% relative**. It comes from **294 snapshots drawn
from 9 settled days**, and snapshots inside one day share a target date and a weather regime, so they
are nowhere near independent. The effective sample is closer to **9** than to 294.

That is a **tie**, not a win, and it is a tie measured in **replay** — the population was re-scored
through the new code, so it is a counterfactual, not observed live performance.

I applied our standing rule that any claimed market-beat is a leakage suspect before it is a result. I
checked the mechanism rather than the number: 0/1,213 over-final floors, settlement labels resolving
from `wunderground_history` independent of the rescue source, and a point-in-time attestation with
every observation time at or before build. It is sound. So this is not leakage — it is simply
underpowered, which is a different problem with a different fix.

## Mission 1: how uncertain is that tie?

Cheap and it decides where the next month goes.

1. Break Toronto's 09:00–14:00 result down **per settled day**: model Brier, market Brier, and the
   signed gap for each of the 9 days. How many days does Toronto win, and by how much?
2. Give me the dispersion across days and an honest uncertainty statement on the day-first mean. If
   it is 5 days up and 4 days down with the mean riding on one outlier, say that plainly.
3. Do the same for the 15:00–17:00 window, where you also report Toronto ahead (`−0.001381`).

I am not asking for a significance ritual. I am asking whether this result would survive another nine
days, and you are better placed than a p-value to answer that.

## Mission 2: make every future day count — the live Toronto scoreboard

This is the build I most want, and today is the right day to start it.

The floor fix went live at 01:15 this morning, so **production behaviour changed** and every settled
day from here is evidence under the current code rather than a replay of old days through new code.
That is a third regime boundary, and it is the first one that generates the evidence we actually care
about.

Build a daily Toronto 09:00–14:00 model-versus-market scoreboard:

- runs off settled-day evidence in the daily chain, no replay;
- records per-day model Brier, market Brier, signed gap, and snapshot count;
- appends to a durable series so the record accumulates rather than being recomputed;
- surfaces the running day-first mean and the win/loss day count in daily status;
- **advisory only** — it must never gate or stop the chain. Same posture as the floor monitor, and for
  the same reason: we are days from a lock.

Then the parity claim stops being a 9-day replay assertion and starts being an accumulating live
record. If Toronto is genuinely at parity in the objective window, that is the first credible
profitability signal this project has produced, and it deserves to be measured every single day rather
than re-litigated in replay.

## Mission 3: Dallas, but only as a transferable mechanism

The measurement picked F-family morning resolution, with Dallas at `+0.037111` within-market — about
**2.2x the F average** — and 20.35% of the F gap on only 255 snapshots. That is a real, specific
signal and it is the right next target by the numbers.

But hold the strategic fact alongside it: **release #1 is Toronto-only, and all 11 F markets are
shadow.** So the largest measurable gap sits in markets we cannot trade, while the one market we can
trade is at parity. Dallas is therefore worth understanding for **what its mechanism tells us about
Toronto**, not for Dallas's own score.

So: what is different about Dallas mornings? Diagnose the mechanism — sources, forecast disagreement,
diurnal shape, anything that separates it from the F markets nearer the average — and then say
explicitly whether that mechanism is present in Toronto. If it is Dallas-specific, it is interesting
and low priority. If it also fires in Toronto, it is the next real target and it goes to the front of
the queue.

## Priority

1 is cheap and reframes everything. 2 is the build that compounds — every day it exists is a day of
evidence we would otherwise not have. 3 only matters through the Toronto transfer question.

Still deferred: MM, cold tier and the 500 GB cap, pointer creation, and any C prelock, fit, or replay —
those wait for the lock.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, no paid-provider change, never read or expose
the sync credential. POST-regime numbers only, and treat 2026-07-31 as a **new regime boundary** — do
not pool pre-floor-fix live days with post-fix live days without saying so.

Start from `origin/master` after tonight's two merges land.

## Handback

`docs/roadmap/agent-report-<date>-workstation-toronto-parity.md`: the per-day Toronto breakdown and
your uncertainty judgement first, then the live scoreboard, then Dallas and the explicit
does-it-transfer-to-Toronto verdict. Push before you start and again at handback.
