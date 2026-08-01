# Workstation handoff — 2026-08-03b: is it one mechanism or five? (and a lead I found here)

The map is exactly what I asked for and it is merged (`24372873`). You built it before any candidate,
you declared the queue-bounding cut as a queue-bounding cut rather than dressing it as a statistical
gate, and you stated plainly that July 22–30 is **not** operationally untouched so this is a
retrospective map and not a forward holdout. That last point is what makes the rest usable.

Two results I want carried forward as framing, because they are more important than the band list:

**1. We are closer more often and lose anyway.** Model closer on 128,954 rows, market closer on
82,961 — we win 61% of rows and still carry a `+0.0157` Brier gap. Only 9,032 rows (4.3%) are
market-right by ≥30 points. **This is a severity problem, not a frequency problem.** Our losses are
concentrated in a small minority of rows where we are badly wrong. Anything that improves the median
row is close to worthless; only the tail matters.

**2. All five retained bands appear as "market higher than model."** Every one is a case where we
**under-allocate to the band the market favours**. Five independent bands failing in the same
direction is either one mechanism or a coincidence, and it is worth knowing which.

## The lead: three of your five bands have marine features that went dark six weeks before your window

Found on the production host while reviewing your map:

| Band | Contribution | Marine station | Marine feature coverage |
| :--- | ---: | :--- | :--- |
| Los Angeles 78–79°F | 5.59% | `klax` | 2022-06-17 → **2026-06-13** |
| Houston 94–95°F | 3.36% | `khou` | → **2026-06-13** |
| San Francisco 68–69°F | 3.08% | `ksfo` | → **2026-06-13** |

`data/marine_water_contrast/<station>/manifest.json` shows a one-shot backfill generated
`2026-06-25`, `schema_version: marine_water_contrast_backfill_v0.1`, 938 feature rows, **last_date
2026-06-13**. It exposes 17 features including `marine_layer_suppression`,
`marine_onshore_cooling_potential`, `marine_breeze_risk`, and `marine_water_minus_forecast_high`.

**Nothing refreshes it.** No scheduled task on this host mentions it (I checked all 28), and nothing
under `src/weather/operations` references it — so the daily refresh does not touch it. It is wired
into the feature path (`model_features.py`, `feature_store.py`, `pooled_feature_assembly.py`), but its
data stops **39 days before your window opens**.

So for July 22–30, in exactly the markets where a marine layer decides the daily high, the model may
be flying blind while the market is not. **12.03% of your 18.64% sits in these three bands.**

The remaining two — Dallas 98–99°F and Austin 98–99°F, 6.61% combined — are inland Texas with no
marine station and a near-100°F band. That looks like a different mechanism: upper-tail behaviour in
extreme heat.

**This is a hypothesis, not a conclusion.** The features may degrade gracefully; the model may barely
weight them. Test it, do not assume it.

## Mission: diagnose, do not repair

1. **Establish what the model actually sees.** For the three marine bands across July 22–30, determine
   whether the marine features are absent, defaulted, stale-but-present, or silently zero-filled — and
   what the model does differently as a result. Quantify it.
2. **Test the two-cluster hypothesis.** Do the marine three and the inland-Texas two fail the same way
   or differently? Compare the shape of the failure — is the distribution mis-centred, too wide, or
   too thin in the tail?
3. **Answer "one mechanism or five?"** All five under-allocate to the market-favoured band. Is there a
   shared condition, or five unrelated causes that happen to share a direction?
4. **Connect it to severity.** Given finding 1 above, characterise the ≥30-point market-right rows
   specifically. Are they concentrated in these bands, at particular hours, or under particular source
   states?

## Hard constraints

- **Do not extend, regenerate, or backfill the marine feature CSVs.** Serving reads that feature path.
  Extending it would change model behaviour mid-streak — a serving change, two days from the lock, and
  categorically out of bounds. If your conclusion is "backfill it", say so and I will schedule it as a
  measured change after release #1.
- No candidate, no tuning, no fitting, no production artifact, no `data/` write.
- Same window or a declared superset, wholly after the `2026-07-31` `rows[-1]` boundary.
- Declare leakage posture as carefully as you just did.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

**Timing:** the Toronto lock lands ~2026-08-03 and the release build starts no earlier than 08-04, run
from the production host. This mission touches nothing on the release path and will not collide.

## Handback

`docs/roadmap/agent-report-<date>-workstation-band-mechanisms.md`: what the model sees for the marine
bands, the two-cluster verdict, your answer to "one mechanism or five", the severity-row
characterisation, and a ranked list of what to change — each item marked as needing a measured
candidate, a data fix, or nothing.
