# Workstation handoff — 2026-08-03a: both lanes retired, and the queue that produced them is stale

## Decision: RETIRE both lanes — accepted

`audit-review-seattle-92631cf037` (exact-band / winner-centering) and
`audit-review-seattle-ad4416de86` (warm-tail dampening) are **retired**, on your evidence, as
operator decision. Merged at `fe98ed4f`.

I verified your scoping before accepting: audit keys `mma_c239fa0a60a08b61` and
`mma_7729758981275fdc` both resolve to `seattle` / `target_date=2026-06-07`. You replayed exactly the
right day.

This is the null result I asked for and it is worth more than a tuned win. Three things you did that
made it usable: you froze both variants before the run and never reran after seeing a score; you
regenerated candidate *and* incumbent together after the `rows[-1]` boundary from the same code; and
you **downgraded your own result** by noting that Items 147/232 already had 2026-06-07 in their
development corpus, so this is replay-only development evidence and not an unseen-day claim. Grading
your own evidence down is the habit that makes the rest of your reporting trustworthy.

Lane 2 also produced a finding worth keeping: the "dampener" allocates **more** to the losing warm
band, not less — mean 0.066961 candidate versus 0.043444 incumbent. The policy does the opposite of
its name. That is a mis-specification, not a tuning shortfall.

## The bigger finding — which is in your numbers, not your conclusions

You reported the historical recorded model probabilities as context. They are more than context.

| Lane | Model vs market **when audited** (2026-06-23) | Model vs market **under today's incumbent** |
| :--- | :--- | :--- |
| seattle 64-65 F | 0.999500 − 0.274247 = **72.53 pts** | 0.999500 − 0.997139 = **0.24 pts** |
| seattle 66-67 F | 0.724665 − 0.000500 = **72.42 pts** | 0.002860 − 0.000500 = **0.24 pts** |

Those reconstruct the audit's recorded 72.53 and 72.42 point gaps **exactly**, so this is arithmetic,
not inference.

**Both disagreements have collapsed by ~99.7%. The defect these lanes were built to repair no longer
exists.** The current model already agrees with the market on both audited snapshots, almost
certainly via the serving-floor fix and what followed. So these lanes did not merely fail to help —
they were repairs aimed at a ghost, and any tuning would have been fitting to a model that has not
served in months.

That generalises, and it is the reason for your next mission: **every remaining row in the review
queue was audited on 2026-06-23 against that same retired model.** The queue is regenerated daily, but
from an append-only audit *log* whose entries are never re-evaluated, so stale disagreements persist
as live-looking work items indefinitely. We came close to spending the run-up to a release chasing
another one.

## Mission: re-derive the disagreement map against the model we actually serve

Answer one question: **where does the model we serve today actually disagree with the market, and on
which of those is the market right?**

1. Re-derive disagreements over a recent, settled window using the **current** serving path — not the
   2026-06-23 log. Choose the window yourself and declare it; it must sit **entirely after the
   `2026-07-31` `rows[-1]` boundary** so nothing needs splicing.
2. For each of the nine existing queue rows, state whether its disagreement **still exists** under the
   current model, with the same before/after arithmetic you produced for these two. Expect most to be
   dead; say so if they are.
3. Rank the *live* disagreements by contribution to the resolution gap, not by raw point gap. A large
   gap on a rare band matters less than a modest one that recurs.
4. Recommend which, if any, justify a repair lane — and explicitly recommend retiring the rest.

What I do **not** want is another repair candidate built and scored. Build the map first. We have just
learned what it costs to work from a stale one.

If the honest answer is "the current model has no material live disagreements in this window," that is
an excellent result and I want it stated plainly — it would mean the remaining gap is diffuse rather
than concentrated, which changes where feature work should point.

## Constraints

- **Read-only.** No repair candidate, no tuning, no production artifact, no `data/` write. Produce the
  map in your run root.
- Scope your freshness gate to the dates you actually read, as you did this time — that worked.
- Declare the leakage posture as carefully as you just did, including whether your chosen window
  appears in any prior development corpus.
- Do not cross the `rows[-1]` boundary.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR,
no merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read
or expose the sync credential.

**Timing note:** the Toronto lock lands ~2026-08-03 and the release build starts no earlier than
08-04. This mission is deliberately independent of both — it touches nothing on the release path, so
it will not collide with the build.

## Handback

`docs/roadmap/agent-report-<date>-workstation-disagreement-map.md`: the declared window and freshness
assertion, the live/dead verdict for all nine existing queue rows with before/after arithmetic, the
ranked live disagreements by resolution-gap contribution, and your keep/retire recommendation per
lane.
