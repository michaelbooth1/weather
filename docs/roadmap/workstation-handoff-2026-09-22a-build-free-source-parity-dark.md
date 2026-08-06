# Workstation handoff 2026-09-22a — build the free-source feature parity, dark

**Goal: implement the free-source feature parity that was never built, measure it where the loss
actually is, and ship it switched off.** Eight numeric fields plus wind and cloud are 0% populated at
inference in the 09:00–14:00 lane while training reconstruction is 97–100% populated. The cause is
known, the effect is measured, and the repair has never been written.

Branch from refreshed `origin/master`. Branch name:
`codex/workstation-build-free-source-parity-dark-2026-09-22a`.

## Do not re-measure this — it is already measured, twice

`-08-20a` (prove the blindness) and `-08-22a` (measure it causally) both landed. Take their findings
as given and do not redo them. In particular, **do not build a case that this repair is worth a
fleet-wide retrain — the measurement says it is not**, and a mission that rediscovers the opposite is
a mission that has fooled itself.

What is established:

| Finding | Value |
| --- | --- |
| Training reconstruction populated | 97.04–100% by feature and hour |
| Captured inference populated | **0%** for 8 numeric fields + wind group, both lanes |
| Cloud | 99.96–100% training, 0% qualified lane, 11.16% excluded lane (all 254 rows Toronto) |
| Category | **(a) train/serve skew for every affected feature.** Category (b) rejected |
| Pooled daily-first Brier cost | `+0.009899`, cluster interval `[-0.022842, +0.041688]` — **crosses zero** |
| **Severe-tail squared error** | **737.065190 → 642.944476 = 12.77%**, interval **8.60–17.53%** |
| Severe tail, excluded lane | 434.348864 → 368.198847 = **15.23%**, interval **9.43–21.54%** |
| Centre mechanism | **Not blindness.** In the excluded lane blindness moves centre *warmer* `+0.005453` bands while served displacement is `-0.297504` cooler |

The nulls do **not** take HGB missing-value branches — the eight numeric fields get artifact
`SimpleImputer` medians and absent wind/cloud groups become all-zero dummy vectors. So this destroys
discriminating information; it is not a routing bug and not a demonstrated cause of the cool centre.

**The root cause, exactly:** commit `5735b573` disabled WU history/current on June 30, severing the
training-time surface contract. Commit `2a878d91` added a free METAR/ECCC station fallback on July 2,
but **only temperature and current max ever reached the feature extractor.** Full free-source parity
for trajectory, dew point, humidity, pressure, wind and cloud **was never implemented.** That missing
implementation is this mission.

## What justifies doing it now, and what does not

The pooled effect crosses zero. It does not justify a fleet-wide retrain and you should not argue
that it does.

The **severe tail** does justify building the input. 4.26% of rows carry 60.2% of total loss, the
market's mode wins roughly 98% of those rows against our roughly 24%, and restoring these fields is
the largest measured single reduction in severe-tail squared error we have — with an interval clear
of zero in both lanes. That is where this is worth building.

## P1 — implement the parity, from free sources only

Bring trajectory, dew point, humidity, pressure, wind and cloud through from the existing free
METAR/ECCC station path to the feature extractor, so the served feature row matches what the training
reconstruction contains.

- **Free sources only.** WU is disabled and stays disabled. No paid provider, no paid tier, no new
  credentialed endpoint. If a field genuinely cannot be sourced free, say which and stop on that
  field rather than substituting something that merely looks similar.
- **Match the training-time semantics, do not approximate them.** A field that arrives with different
  units, a different aggregation window, or a different station-selection rule is a *new* train/serve
  skew wearing the old one's name. State per field how you established semantic equivalence.
- Where a field cannot reach parity, leaving it absent is the correct outcome. **A wrong value is
  worse than a missing one here**, because missing routes to a median and wrong routes to a
  confident error.

## P2 — ship it dark, and mean it

**This must not change what we serve.** Release #1 freezes the June HGB artifacts, and those
artifacts' train/serve parity is a property we are about to lock. Changing the served feature row
before that lock invalidates the thing being locked.

- The new population path is behind a flag that **defaults off**.
- With the flag off, the served feature row must be **byte-identical** to what it is today. Prove
  that, do not assert it — a parity test against captured envelopes is the proof.
- `model_features.py` and `feature_store.py` are expected to be inside the snapshot capture import
  closure, so this branch is **roll-sensitive** and merges only in the 01:00–04:00 quiet window.
  That is acceptable *because* the roll is behaviourally inert with the flag off. Give a per-file
  roll verdict from the retained closures, not the `SOURCE_PATTERNS` glob.
- Do not fit anything, do not produce a candidate, do not touch an artifact, do not score a held
  candidate, do not write a feature or sidecar into production.

## P3 — measure it on the tail, with the predeclared rule

Evaluate the flag **on** in your own scratch, against the frozen development corpus.

- **Reuse `-08-22a`'s predeclared severe rule.** Do not invent a new severity threshold and do not
  tune one. Inventing the rule after seeing the data is how the retracted results in this project
  happened.
- Report severe-tail squared error with **crossed date x market clustering**, and report the effective
  date-cluster and market-cluster counts alongside every number.
- Report the pooled effect too, and if its interval crosses zero, **say so in those words** rather
  than presenting the point estimate as a movement.
- Report per-hour and per-market heterogeneity. `-08-22a` found the daily-first cost positive at
  09:00–11:00, negative at 12:00–13:00, near zero at 14:00, and negative in 5 of 12 markets including
  NYC and Toronto. If your repair inherits that heterogeneity, that is a finding about where it may
  be turned on later, not a defect to smooth away.

The deliverable sentence is: **on the severe tail, with the flag on, what is the squared-error
reduction and its crossed interval — and is it consistent with `-08-22a`'s 12.77% / 15.23%.**

## Boundaries

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled
  task, write nothing under `data/` on the production host, never write to the mirror or
  `D:\weather-mirror`.
- Never read or expose `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. Check the file when you run; do not read, enumerate,
  replay or score a reserved date. Use only the frozen development corpus.
- Do not weaken the trusted observed-high floor. Do not relax the promotion gate for `harvest_only`
  rows. Do not change providers or paid tiers. **Do not re-enable WU.**
- Concurrent missions own other files: `sources/forecast_history.py` and
  `collection/forecast_archive.py` (`-09-20a`); `live_variant_settlement_scorecard.py`,
  `nightly_retrain.py`, `daily_refresh.py` (`-09-21a`); `mm_*.py` and `schema_registry_data.py`
  (`-09-18a`); `operations/base_retrain.py` (`-09-23a`). **Stay out of all of them.** If you need
  `schema_registry_data.py`, report the requirement rather than taking the file.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-build-free-source-parity-dark.md`.

## What would falsify this mission

- Finding that one or more of the six fields cannot be sourced free at training-time semantics would
  narrow the repair. Report which fields survive; a partial parity is a real result.
- Finding that the flag-off path is not byte-identical means the change is not dark and must not
  merge. That is a hard stop.
- Finding that the severe-tail gain does not reproduce near `-08-22a`'s 12.77% / 15.23% would mean
  either the repair is not equivalent to the oracle restoration, or the original measurement was
  optimistic. **Report the discrepancy; do not tune the repair until it matches.**
- Finding that the repair also moves the excluded-lane centre would contradict `-08-22a`'s finding
  that blindness is not the centre mechanism. That would be a significant result and outranks the
  tail finding — say so loudly rather than burying it.
