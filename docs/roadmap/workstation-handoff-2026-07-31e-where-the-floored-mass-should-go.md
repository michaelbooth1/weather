# Workstation handoff — 2026-07-31e: the floor is right, now fix where the mass goes

The audit answered the blocking question properly, so **the hard variant is merging** into master in
tonight's 01:15 quiet window. Zero over-final floors in 12,813 enforced floors across both unit
families, every market, every hour group — that retires a standing prohibition that had stood since
v0.4.8, on evidence rather than on argument.

I verified the join independently before accepting it, because a settlement label derived from the
same station stream that produced the floor would have made `0` vacuous. It isn't: every label in the
audited window has `resolution_source_type = wunderground_history` (KDAL, CYYZ, `daily_summary`,
round-half-up whole degree). The floor comes from station/current observations; the label comes from
the WU settlement print. Genuinely independent, so the zero means what you said it means.

Also accepted, and both are the reason I trust the rest: you reported **4,385 / 4,046 / 407 worsened
snapshots** without being asked twice, and you reported Toronto's 00-02 slice as a small regression
instead of rounding it into an across-the-clock win.

Headline, recorded: served/market **`1.663916x → 1.497960x`** snapshot-weighted, **`1.794457x →
1.521139x`** day-first, Toronto **`1.242351x → 1.175213x`**. Best single improvement to the lane we
actually publish that this project has measured.

## Mission 1: the compensating control, before anything else

Your own caveat is the right one: the frozen sample shows the floor did not exceed settlement *there*,
not that every future station observation is infallible. I am merging a hard floor on a sample, so the
monitor you proposed is now the thing that makes that safe.

Build it: join every captured enforced floor to its eventual settlement, and **fail closed** on any
over-final observation — market, date, snapshot id, floor, settlement, rescue source, overshoot in
buckets. It should run off settled-day evidence in the daily chain, need no replay, and alert rather
than silently record. Design it so a single over-final floor is loud, because the whole safety
argument for hard-rather-than-hedged rests on that count staying at zero.

Ship this as its own commit, first, so it can merge ahead of anything else.

## Mission 2: the regressions all point at one mechanism

Look at what your three worst cases have in common:

```text
dallas        hour 23   floor 97 F   settlement 97 F   +0.074697
san-francisco hour 15   floor 67 F   settlement 67 F   +0.019513
toronto       hour 17   floor 27 C   settlement 27 C   +0.040335
```

**In every one, the floor equals settlement.** The day's high was already in, already observed, and
sitting exactly on the floor bucket. Enforcing the floor correctly deletes the impossible mass below
it — and then renormalization spreads that mass *proportionally upward*, onto bands strictly above the
truth. So the more confident the floor is, the more mass gets pushed away from the right answer.

That is not a floor bug. It is the redistribution rule being wrong in exactly the situation the floor
identifies. Proportional renormalization encodes "the high will keep climbing", which is a reasonable
prior at 10:00 and a bad one at 20:00.

So, measurement first, and no code change until it says so:

1. On the frozen population, among snapshots with an enforced floor, what fraction have
   **`floor == settlement`**, by local-hour group? My expectation is that it rises steeply through the
   afternoon and is very high after 18:00 — Toronto's 18-23 Brier after the fix is `0.000322990`,
   which is nearly a solved problem, and that number smells like "the high is in and the floor knows
   it."
2. Split the 4,385 / 407 regressions by whether `floor == settlement`. If they concentrate there, this
   hypothesis is confirmed and it is the next skill lever.
3. Then, and only then, counterfactual it: redistribute the removed below-floor mass **weighted toward
   the floor bucket** rather than proportionally across all surviving bands, and report the same
   before/after tables. One variant is enough — I am not asking for a tuned family.

If the fraction is low or the regressions are spread evenly, say so and stop; I would rather kill this
in one cycle than tune a redistribution curve into a corpus.

## Mission 3: does this change what release #1 can contain?

Toronto at `1.175213x` market is a materially different market than the one I scoped release #1
around. The Toronto C-family candidate run has been deferred every cycle on the grounds that the model
was too far behind to be worth the work.

Do not run it. **Scope it**: what a C-family candidate run needs that does not exist today, what it
would cost, and what it could and could not conclude given that Toronto has no authorized frozen
postblend artifact. I want a decision-ready recommendation, not a result.

Note the constraint that shapes the answer: the Toronto lock is ~2026-08-03 and the streak is at
**9/14**, so anything requiring a code change to the serving path competes directly with that clock.

## One review note from the merge read

In `model_features.py`, the non-strict path no longer falls back to `row_temp_native(rows[-1])` for
`current_temp`; that value now feeds only the startup-guard diagnostic. I read this as deliberate and
as a *tightening* — `rows[-1]` is unfiltered by cutoff, so admitting it could inflate `high_so_far`
with a post-cutoff reading — and it is why I am comfortable merging. Confirm it was intentional, and
say which callers use the non-strict path and whether any of them change behaviour. If a training or
backfill path consumes it, I want that named before the next artifact regeneration, not after.

## Recorded

- Hard retained, hedged fallback correctly not run, implementation unchanged from the audited
  `b77cfbed`.
- The `0.001357125` remains untouched and correctly so.
- Paid provider: not re-enabled, not purchased. The bounded research-only overlap from the existing
  free page-backed collector stays proposed-not-run.

## Priority

1 first and alone if time is short — it is the control for a change that is landing tonight. 2 is the
skill lever. 3 is planning only.

Still deferred: MM, cold tier and the 500 GB cap, pointer creation.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, no paid-provider change, never read or expose
the sync credential. POST-regime numbers only.

Start a fresh branch from `origin/master` once tonight's merge lands — do not keep building on
`codex/workstation-fix-floor-toronto-2026-07-31b`.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-monitor.md`: the monitor and its fail-closed
behaviour first, then the `floor == settlement` fractions and the regression split, then the
redistribution counterfactual only if the split justified it, then the C-family scoping. Push before
you start and again at handback.
