# Workstation handoff 2026-08-23a — why is the morning centre cool?

Run this now. **Diagnosis only: no repair, no candidate, no artifact, no fit, no scoring, no fresh
dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Where the eliminations leave us

`-08-22a` killed blindness as the mechanism, correctly and on the evidence I asked for: both
intervals cross zero, and the direction is *wrong* — blinding moves the excluded-lane centre warmer
while the observed defect is cooler. Your recommendation against a fleet-wide Phase F retrain is
accepted.

Taking stock of what this week has eliminated for the 09:00–14:00 lane:

- **The floor** — fixed and shipped; the evening is solved and that gain did not reach this window.
- **Objective reparameterization** — only pays when the anchor is a *constraint*; the forecast
  isn't, and it failed on its own folds.
- **Blindness / missing features** — real defect, but small, insignificant, and directionally wrong.

The centre displacement in this window is still unexplained, and it remains the largest thing we
understand least. Centre is worth 74.97% of the severe tail against width's 10.94%, so this is the
question.

## The hypothesis to test

`centre-displacement-mechanism-found` established that the base HGB puts mass **below the physical
floor** and that truncation then yanked the centre warm — the evening mechanism, now repaired. That
finding also said the real fix was upstream.

So: **is the base HGB systematically too cool, with the floor having merely masked it in the
evening?** In the morning there is no binding floor to truncate, so a raw cool bias would show
through directly. That would make the morning gap and the old evening defect the *same* underlying
bias, seen with and without a mask.

Test it. If it holds, the next question is which of these produces it:

1. **Target/label** — is the training target itself biased cool relative to settlement? Check the
   label construction and any rounding, source-precision, or admission asymmetry.
2. **Training distribution** — are training rows drawn disproportionately from cooler regimes,
   hours, or seasons relative to what we serve at 09:00–14:00?
3. **Loss/objective** — does the fitted loss penalise warm errors more than cool ones, or does the
   band discretization round systematically downward?
4. **Feature-driven** — is the cool centre traceable to a specific feature's response rather than a
   global bias? Partial-dependence over the fitted trees would show it.

Name which, with evidence. If the bias is not present in the base HGB at all, say so — that would
mean the displacement is introduced downstream, in blend, prior, calibration, or band conversion, and
that is equally valuable to know.

## Design requirements

1. **Measure the bias on the base HGB directly**, before blend, prior, calibration, floor, and band
   conversion, so the stages are separable. We have been burned twice by attributing to the wrong
   stage.
2. **Report by hour**, so the evening-versus-morning contrast is visible rather than assumed. If the
   base bias is uniform across hours, the mask explanation holds. If it is hour-dependent, it does
   not, and that is a different finding.
3. **Development window only** — July 22–26. No July 27–31, no August 1–3, no August 6–19.
4. **Distinguish bias from noise.** Give an interval. `-08-22a` was valuable precisely because it
   reported that its intervals crossed zero.

## What I want back

1. Is the base HGB systematically cool at 09:00–14:00? With an interval, by hour.
2. Does the mask explanation hold — same bias evening and morning, differing only in whether the
   floor truncates it?
3. Which of the four causes, with evidence, or a clear statement that it enters downstream instead.
4. Your honest read on whether this is tractable. We have eliminated three hypotheses this week; if
   the fourth looks like irreducible forecast uncertainty at that lead time, say so.

## Sequencing

No repair, and no candidate. We already hold three awaiting scarce dates, and I am not adding a
fourth before `-08-16a` reports. This mission is to understand, not to build.

## Constraints — unchanged

- Base on `codex/workstation-measure-blindness-causally-2026-08-22a` @ `ababbfd1`. Every branch in
  this chain is held and unmerged. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.** It is a control here, and the evening repair
  depends on it.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. A precise negative — that the base HGB is not
cool and the displacement enters downstream — is as useful as a positive, and should be reported as
prominently.
