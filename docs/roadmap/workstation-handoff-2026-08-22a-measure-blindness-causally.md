# Workstation handoff 2026-08-22a — measure the cost of blindness causally

Run this now. **No repair, no candidate, no artifact, no fit, no scoring of held candidates, no fresh
dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Why

Your section 7 was right and I was wrong to repeat 51.40% as a repair ceiling. It is an oracle for a
correction *class* that supplies the contemporaneous market centre — information METAR/ECCC does not
contain — applied with hindsight only where it helps. I also compounded the error by multiplying it
against the 81.21% post-gate share to claim "~42% of total remaining loss", combining denominators
your report explicitly flags as inconsistent with `-08-20a`'s 69.42%. Both statements are withdrawn.

So the defect is confirmed and its value is unknown. Before anyone commits to a retrain-required
Phase F, size it **causally** rather than by oracle.

## The experiment

The ten fields are populated somewhere — that is why the trained trees split on them heavily. That
gives us both states of the same variable, which is what an oracle bound never had.

**Take rows where the affected fields are populated, blind them exactly as serving does, and measure
the degradation.** Blinding must reproduce the real mechanism precisely: median-impute the numerics
through the fitted preprocessing, and turn the categoricals into the all-zero one-hot vector — not
NaN, not a `Missing` category. Anything else measures a different defect.

This yields a direct estimate of what blindness costs, in the model we actually serve, with no
retrain and no new artifact.

## Design requirements

1. **Report per field and jointly.** Blinding all ten at once gives the headline; per-field tells us
   which are worth the engineering. Phase R and Phase F cover different fields, so split the estimate
   along that line too — the cheap conditional no-refit path should be priced separately from the
   retrain-required one.
2. **State the transfer assumption plainly.** Populated rows sit at different hours, markets, and
   lanes than the blind ones. This measures the cost of blindness *on the population where we can
   observe it*, and transfers to 09:00–14:00 only under an assumption you should name and, if
   possible, test — for example whether the per-field effect is stable across hours where both states
   occur.
3. **Report the effect on the severe tail**, not only pooled Brier. The excluded lane's problem is
   concentrated loss, so a pooled-only answer will mislead.
4. **Check direction.** `-08-20a` found the imputation direction does not explain the observed cool
   displacement. Does blinding reproduce a displacement at all, and in which direction? If blinding
   moves the centre the *opposite* way from the observed defect, then blindness is not the centre
   mechanism and that materially changes what Phase F is worth.
5. **Development window only.** July 22–26. No July 27–31, no August 1–3, no August 6–19.

## What I want back

1. The joint estimate, per-field estimates, and the Phase R versus Phase F split.
2. The severe-tail effect alongside the pooled one.
3. The direction finding from requirement 4, stated even if it undermines the repair's rationale.
4. The transfer assumption, named, with whatever evidence bounds it.
5. **Your own view of whether Phase F is worth a retrain**, given the number you get. If the causal
   estimate is small, say so — retiring this line cheaply is a good outcome, and far better than
   discovering it after a retrain.

## Sequencing unchanged

No repair before release #1. This measurement does not authorize one, and a favourable number does
not either — Phase F needs the full gate and its own fresh evidence, on post-August-19 dates rather
than competing for August 4–5 with the three held candidates.

## Constraints — unchanged

- Base on `codex/workstation-spec-contract-repair-2026-08-21a` @ `37183243`. Every branch in this
  chain is held and unmerged. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **Do not backfill, repair, or write any feature, sidecar, or marine path.** Read-only.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. The number I most need is the honest causal
cost of blindness, per field, with its transfer assumption stated — including if that number is
disappointing.
