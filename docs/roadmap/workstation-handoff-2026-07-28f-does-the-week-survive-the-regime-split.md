# Workstation handoff — 2026-07-28f: does this week's evidence survive the regime split?

This jumps ahead of `-27g` Missions 2 and 3 and ahead of further floor work. It is cheap, and
it decides whether a week of measurements means what we think it means.

## What I can add from the production host

I dated your runtime boundary:

| | |
| :--- | :--- |
| `4085a8fb6813` | 2026-07-01 19:03:56 -0400 |
| `89f3b908a245` | 2026-07-02 11:10:50 -0400 |

**That boundary sits inside the frozen corpus**, which spans 2026-06-28 to 2026-07-10. Days
06-28 through 07-01 are pre-boundary — 4 of 12 target dates, 33.3% — and the boundary falls
mid-morning on 07-02, which pushes the true pre-boundary share a little higher. You measured
**37.732%** stored-null. Those agree.

**The cause is not in that diff, so do not go looking there.** The only change to a feature file
is a removed *unused import* (`feature_names_need_dynamic_source_state`) in
`pooled_feature_assembly.py`, and the schema addition is `snapshot_cadence_attribution`, a
snapshot-loop diagnostics record. Neither touches `high_so_far`. The runtime identity marks
when the running process adopted new code, not necessarily what changed the behaviour.

## Why this outranks the floor

Your strongest result is the one that is easy to read past: **11,601 numeric pairs match
exactly, 101 are both null, and there are zero numeric disagreements.** Where the stored feature
exists it equals your reconstruction, always. So the computation never disagreed — only its
*availability* changed, sharply, one third of the way through the corpus.

Which means **every pooled number this week was averaged across two regimes**: preblend versus
replay-final versus recorded versus market, the 98.88/1.12 skill-gap decomposition, the hour-20
floor populations, the `NOT_ACCOUNTED_FOR` accounting. All of them pooled over a corpus in which
a model feature and its three derived band features are absent for the first third.

I am not claiming that invalidates any of it. I am saying we do not currently know, and it is
cheap to find out.

## Mission 1: re-run the headline comparisons on the post-boundary regime only

Restrict to captures at or after `89f3b908a245` — your 11,662 agreeing captures — and re-run:

1. **preblend vs replay-final vs incumbent vs recorded vs market**, pooled binary Brier with
   full Murphy decompositions.
2. The **named hour cuts**, predawn 03–05, primary 09–14, evening 20–23.
3. The **recorded-output agreement table** — row-exact and whole-partition against each lane.

Then answer plainly:

- Does **replay-final still beat preblend**? If that flips on the homogeneous subset, my blend
  refutation was an artifact of pooling and I need to know today.
- Does the **model-versus-market gap** keep its size and shape, or does it move materially?
- Does **recorded still match nothing**? If zero whole-partition matches persists post-boundary,
  `NOT_ACCOUNTED_FOR` is robust to the regime split and stands on firmer ground than before.

Report the pre-boundary subset too, so the two regimes can be compared directly rather than
inferred. State the reduced population sizes up front; a homogeneous 8-day panel with honest
counts is worth more than a 12-day panel that silently mixes regimes.

If the numbers are materially unchanged, say so and we treat the confound as immaterial and
stop discussing it. That is a perfectly good outcome and I would rather have it stated than
assumed.

## What stays open, deliberately

You were right that persisted feature evidence does not prove the predictor consumed those
values. I am not asking you to resolve that here — it needs serving-side evidence we do not
have, and it is the same wall as the release binding. Note it and move on.

The stored trajectory being non-clean in its own right — 286 decreases, 27 resurrections,
3,525 late nulls — is real and still unexplained. It is second in line behind the regime split,
because knowing whether the week's conclusions hold is worth more than knowing why a feature
was patchy in a window we may end up excluding anyway.

## Then the floor

`-27g` Missions 2 and 3 follow, restricted to the post-boundary regime if the split shows it
matters.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/serving/config/
release change, topic branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-regime-split.md`: the three re-run comparisons
with both regimes shown side by side, the population counts, and a direct verdict on whether
the blend refutation, the gap size, and `NOT_ACCOUNTED_FOR` survive.

Context: streak 7/14, lock ~2026-08-03. Storage merges here at 01:15 tonight.
