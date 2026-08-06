# Workstation handoff 2026-09-05a — where does the improvement go?

Run this now. **Measurement and attribution only: no fit, no retrain, no candidate, no scoring of
held candidates, no network, no reserved dates.** `-08-16a` runs 2026-08-05 04:30 and takes priority.

## The number that should be bothering us

`-08-24a` measured the conditional cool-bias correction two ways:

- **raw HGB: 24.69% of the raw-versus-market Brier gap closed**, interval excluding zero;
- **served output: 5.39%**, interval `[-0.007011, +0.004711]` crossing zero, 3 of 5 dates better.

**Roughly 78% of a real upstream improvement disappears between the model and what we serve.**

We are about to spend a month on release #1, the PIT corpus, the observation contract and the first
retrain — all to improve the upstream model. `-08-04a` then priced the honest served payoff at
**0 to 5.39%**, an interval containing zero.

If the leak is real and fixable, the same retrain is worth up to 24.69% instead of 5.39%. **That is a
~4.5x multiplier on the entire plan**, and unlike everything else on the roadmap it needs no release
pointer, no corpus, and no fresh dates.

If the leak is *not* fixable — if every stage is absorbing improvement for a good reason — then the
retrain's honest ceiling really is ~5%, and I want to know that before spending the month, not
after.

## Measure it stage by stage

`DistributionPipelineState` (`model_distribution.py:92`) already records named snapshots through
smoothing, blend, prior, calibration, floor and band conversion. `app/views/model_pipeline.py`
already renders them. **The instrumentation exists; nobody has ever measured through it.**

Take the frozen `-08-24a` conditional correction — do not refit it, do not reselect it — and push
both the corrected and uncorrected distributions through the real serving pipeline. At **every
stage**, measure how much of the raw improvement survives.

I want a waterfall: 24.69% at the raw HGB, then the remaining fraction after each stage, ending at
5.39%. **Name the stage or stages where it goes.**

Use the same no-fit substitution discipline as `-08-29a`: change one input, hold everything else
exactly, and report intervals with proper clustering by date and market.

## Then say whether each absorption is legitimate

This is the part that matters, and it needs judgement rather than arithmetic. For each stage that
absorbs improvement, classify it:

- **By design and correct** — the stage is supposed to damp this, and damping it is right. Say why.
- **By design but now wrong** — e.g. a probability calibrator fitted to the *old* distribution
  shape will distort a corrected one. That is a known suspect: the release contract copies
  calibration from the parent rather than refitting it.
- **A defect** — the stage discards improvement for no defensible reason.

The blend is a second suspect: `why-we-lose-to-the-market` recorded that blending **hurts** on the
clean regime. If the blend is averaging a corrected model back toward an uncorrected component, that
is a large and cheap finding.

## The constraint that is not negotiable

**If the floor turns out to be a major absorber, the answer is NOT to weaken it.**

`centre-displacement-mechanism-found` established that the base model puts mass below the physical
floor and truncation then yanks the centre warm. If a corrected model still needs the floor to
truncate it, the finding is that **the raw model must stop putting mass down there** — not that the
floor should let it through. The floor is a physical constraint and it stays.

Any recommendation that reduces to "relax the floor" is wrong and I will reject it. Say the upstream
version instead.

## What I want back

1. The stage-by-stage waterfall from 24.69% to 5.39%, with intervals.
2. Which stage or stages absorb the improvement, and how much each.
3. The legitimacy classification for each absorbing stage, with reasoning.
4. **The number I most want:** if the top absorbing stage were corrected — most likely a
   candidate-specific calibration refit rather than a copied parent calibrator — what would the
   served effect be? An honest range, and say plainly if it is still small.
5. Whether this changes the first-retrain contract. If the retrain must refit calibration jointly
   rather than inherit it, that is a change to a contract we just built and I want it flagged now.

## Sequencing

Development window **2026-07-22 → 07-26** only. No 07-27 → 07-31, no 08-01 → 08-05, and nothing in
the reserved window. This needs no release pointer, no corpus, and no held branch.

## Constraints

- Base on `master` @ `9a9376ef`.
- **Reserved window is now `2026-08-06 → 2026-11-03`** — see
  `docs/operations/reserved-confirmation-window.md`, which is the single source of truth and wins
  over any handoff text. Not read, enumerated, evaluated, or substituted.
- Also excluded: **2026-07-27 → 07-31** (burned) and **2026-08-01 → 08-05** (`-08-16a`'s declared
  set).
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor**, per the section above.
- **No network access.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Lead with item 4. If the answer is that the
leak is structural and the served ceiling really is ~5%, say so plainly — that would reshape the
roadmap, and I would rather hear it now than after the retrain.
