# Workstation handoff — 2026-07-28: the observed maximum we never asked for (a standing queue)

The floor-authority queue is **accepted and closed**, and Mission 2 is the reason. You had a
preregistered hypothesis, you tested it, it failed — failed-WU covers all 38 misses but also
76 of 86 aligned cases, and authoritative timestamps exist in **0 of 124** — and you stopped
**before** modelling rather than reaching for a weaker discriminator that would have fit. That
is the single most valuable thing you have done for this program, because a tuned version of
that signal would have looked like progress for weeks.

Two other results land hard:

- **Mission 1**: the band-binary live capture path reproduces the invariant violation —
  269/535 partitions, and **206/206 evening F partitions** — while continuous-density does
  not. Your qualification that these rows are unbound/shadow, and therefore *not* active
  headline or trading bleed, is the difference between an emergency and a known pre-release
  defect. It is the latter. But it becomes real the moment anything binds to that path, so it
  is a fix-before-release item, not a someday item.
- **Mission 3**: in **38 of 38** cases the market had already selected the eventual winner,
  mean probability `0.994001`, while our captured authoritative higher-WU evidence is **0 of
  38**. The information existed and we did not have it. That is no longer a modelling problem.

**This handoff is a queue. Work in order, do not idle.**

## The lead: we already fetch the archive that carries the answer

Your Atlanta case was recoverable from a **pre-capture METAR six-hour maximum**. I checked
what we actually request. `src/weather/sources/metar_history.py` pulls the IEM ASOS archive
(`mesonet.agron.iastate.edu/cgi-bin/request/asos.py`) with exactly 14 `data` fields:

```
tmpc dwpc relh drct sknt gust alti mslp vsby skyc1 skyc2 skyc3 wxcodes
```

Temperature, dewpoint, humidity, wind, pressure, visibility, sky, weather. **No 6-hour
maximum group, and not the raw METAR text either.** That service also exposes the decoded
6-hour and 24-hour max/min groups and the raw report — confirm the exact field names against
the service rather than trusting my recollection of them.

So the most probable explanation for 0/38 authoritative evidence is not that the observation
was unavailable. It is that **we never asked for the column.** If that holds, this is the
cheapest information gain available to us, from a source already in the pipeline.

## Mission 1 (primary): prove or kill it on the 37

Fetch the 6-hour max/min groups and raw METAR text for the 37 unresolved cases from the same
IEM archive, into your declared output root. For each case answer:

1. Does an observed maximum consistent with the settlement exist in the archive?
2. **Was it time-valid at the hour-20 prediction cutoff** — published, not merely covering a
   period that had elapsed? This is the leakage trap and it is a sharp one: the 6-hour group
   is reported at synoptic hours and describes the *preceding* six hours, so a group that
   settles the question may not have been publishable at our cutoff. Report resolved counts
   **split by time-validity**, and treat any case you cannot timestamp as unresolved.
3. What is the latency between the true high occurring and it becoming readable?

Deliverable: of 37, how many were knowable at 20:00 from data we already pay to fetch. If the
answer is most of them, that is the finding. **If it is few, say so** — that bounds the
evening as largely unrecoverable and we stop spending on it, which is equally useful.

Read-only research. **Do not change the production collector**; adding fields to a live source
fetch is a collector change and needs separate authorization.

## Mission 2: where is this worth money, not just accuracy?

The evening is loss-avoidance — the market is at `0.994` and there is nothing to win there.
The interesting question is whether the same missing observation helps **earlier**, in the
09:00–14:00 primary window, where the market is genuinely uncertain and edge could exist.

Using the same time-validity discipline, measure: at 09:00–14:00 cutoffs, does an authoritative
observed-max-so-far exist that we do not currently consume, and does it separate outcomes the
market has not already priced? Report it against the market, not just against our own model —
being better than ourselves is not edge.

Note the coverage question honestly: the 6-hour convention is a US practice, so this may serve
the 11 F markets and not Toronto, which runs on ECCC/SWOB. Toronto is the streak and lock
market, so state the coverage split rather than reporting a pooled number.

## Mission 3: what a correct floor would require

Your freshness hypothesis failed because no authoritative timestamps exist. If Mission 1
succeeds, an authoritative observed max **is** the discriminator that was missing — a floor
you can trust because you know when it was published.

Specify, do not build: what would a correct floor look like given a timestamped authoritative
max, how would the blend have to change so the invariant holds where the floor is trustworthy,
and what would it have done on the 86 aligned and 38 above-floor populations. Design and
projected effect only. No model, no serving, no promotion.

## Guardrails

- `data/` strictly read-only, proven deny-write ACL, single declared output root.
- **No collector, model, serving, scheduler, promotion, release, pointer, sizing or trading
  change.** Missions 1 and 2 are measurement; Mission 3 is a written design.
- Topic branches only; push them without asking (standing authorization); never master, no
  PRs, no merges.
- Leakage first on any large improvement — and here the leakage risk is *specifically*
  time-validity of an observation that describes the past. Make the argument explicit.
- NOT-DONE / NOT-REHEARSED stay first-class; claim no enforcement you did not measure.

## Handback

`docs/roadmap/agent-report-<date>-workstation-observed-max.md`: the 37-case resolution table
split by time-validity, the 09:00–14:00 measurement against the market with the coverage
split, and the floor design. Push all topic branches.

Context: streak 5/14, earliest lock ~2026-08-03. Your profit-edge branch merges here tonight
in the quiet window; floor-authority is report-only and merges with it. The confirmation panel
you froze is 0/14 and starts accumulating today — leave it untouched.
