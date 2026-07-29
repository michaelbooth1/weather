# Workstation handoff — 2026-07-28i: characterise the concentrated deficit

Missions 3+ of `-28c` remain queued and should take the next 01:00–08:30 window; they are the
commercially important item. This is the fill-in before it.

## No mechanism from me this time

Eight mechanisms this week, six dead. The one that keeps working is not my hypotheses — it is
your characterisations, and the confounds you find while testing mine. Sharpening died cleanly
and usefully: the fit chose **β = 0.65, smoothing rather than sharpening**, and still worsened
held-out Brier on both bases. So we are neither too diffuse nor too sharp globally, and the
resolution deficit is not a confidence-calibration artifact. It is information.

**So this mission asks what is true, not whether something I guessed is true.** Describe the
concentration; do not test a story of mine. If a mechanism suggests itself from the data, say
so and I will treat it as yours, which historically has been the better bet.

## The lead

You found the deficit concentrated in **Denver, Dallas and Austin at local hours 09–15** — that
is continental markets during the heating window, which is exactly when a daily maximum is
hardest to pin down.

## Mission 1: is the market actually sharp there, or is everyone diffuse?

This is the discriminator that decides whether there is anything to chase.

For the concentrated cells (Denver/Dallas/Austin, hours 09–15) and for a matched set of
well-performing cells, report **absolute** resolution for us and for the market, not just the
deficit:

- If the market achieves high resolution where we do not, they hold specific information we
  lack, and it is worth identifying.
- If both of us are diffuse there and they are merely slightly less so, the cells are
  intrinsically uncertain and the deficit is close to irreducible — which is equally valuable to
  know, because it caps what any modelling effort can win.

Give the uncertainty term per cell too, so intrinsic difficulty is separated from skill.

## Mission 2: what distinguishes the bad cells?

Descriptive, using data already in the corpus or cheaply derivable from retained inputs:

- Do the worst partitions cluster on particular **days** rather than being spread across all
  days in those markets? A few pathological days behave very differently from a persistent
  market-level weakness.
- On those days, what do the retained observations and forecasts look like — large intraday
  range, rapid mid-day movement, disagreement between forecast sources, unusual cloud or wind
  signatures in what we captured?
- Does our error there look like **bias** (centred wrong) or **spread** (centred right, too
  flat)? Those need different remedies and the decomposition already distinguishes them.
- Is the deficit worse on days where the outcome landed near a band edge?

## Mission 3: connect to the known data gaps, or rule them out

`docs/roadmap/` carries a 2026-06-20 predictor audit naming 850 hPa temperature and mixing
depth, soil moisture, forecast shortwave, and smoke/AOD as absent predictors. Continental
daytime heating is exactly what those govern.

Without adding any predictor or retraining, can you say whether the bad cells are consistent
with those absences — for example, do they coincide with conditions those variables would
describe? A defensible "consistent with" or "not explained by" is enough. **Do not manufacture
a link**; "the corpus cannot distinguish these" is a fine answer and more useful than a
plausible story.

If the answer is that a specific absent predictor would plausibly address a concentrated,
sizeable deficit, that becomes the first genuinely fundable modelling change we have identified
all week.

## Carry forward

`POOLED_WIN_UNSAFE_PER_CASE` on the floor projection is accepted as the verdict. Blanket and
targeted both worsen individual cases with no principled separator, so it is not deployable and
I am not asking again. It stays quantified for the day we have release binding and can weigh a
pooled gain against per-case risk deliberately.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/alpha/predictor/
config/serving/release change and no retraining. Topic branches only, no PR/merge/master push,
NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-deficit-anatomy.md`: absolute resolution and
uncertainty by cell first, then the descriptive contrast between bad and good cells, then the
data-gap consistency assessment.

Context: streak 7/14, lock ~2026-08-03. Storage merges here at 01:15 tonight.
