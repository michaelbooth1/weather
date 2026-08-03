# Workstation handoff 2026-08-24a — is the cool bias conditional or unconditional?

Run this now. **Diagnosis and sizing only: no repair, no retrain, no candidate, no artifact, no
scoring of held candidates, no fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Where we are

`-08-23a` confirmed the root cause with an interval that excludes zero: the raw HGB is
**−1.2131 °C-equivalent** at 09:00–14:00, `[−1.7928, −0.7035]`, measured before blend, prior,
calibration, floor and band conversion. The mechanism is a stale/cool training prior with
insufficient upper class support, and the evening uses the *same* cool base with stronger floor
binding masking it.

That unifies the old evening defect and the morning gap into one bias seen with and without a mask,
and it means the continuation objective, the gate, and the ordinal repair are all downstream patches
on a base model that is over a degree too cool.

## The tension that decides whether this is the main event

This project already measured its Brier decomposition as **98.88% resolution / 1.12% reliability**,
and concluded that recalibration cannot close the gap.

A **pure unconditional mean shift is a reliability fix.** If the −1.2131 bias is unconditional, then
correcting it can only reach on the order of 1% of loss, and this finding — however real — is a
curiosity rather than the main event.

But a bias **conditional** on hour, market, or regime does not appear as reliability in a pooled
decomposition. It appears as lost **resolution**, and correcting it could be worth a great deal more.

**Answering this is the mission.** Do not let it be assumed in either direction.

## What to do

1. **Decompose the bias.** How much of the −1.2131 is a constant offset across all rows, and how much
   varies with hour, market, forecast-relative position, and regime? Report the conditional structure
   explicitly, with intervals.
2. **Reconcile against the existing decomposition.** Recompute reliability and resolution on the
   development window and show where the measured bias lands within them. If the 98.88 / 1.12 split
   is stale, superseded by the floor repair, or was computed on a different population, say so — that
   would itself be an important correction.
3. **Size the correction causally, without circularity.** Estimate the shift on one fold and apply it
   to a held-out fold. Fitting and scoring the same correction on the same rows is exactly the
   circularity that inflated the earlier oracle number, and I would rather have a small honest figure
   than a large invalid one.
4. **Report pooled and severe-tail effects separately**, since the tail carries most of the loss.
5. **Development window only** — July 22–26. No July 27–31, no August 1–3, no August 6–19.

## The question behind the question

If the bias is conditional and correcting it is worth real loss, then the right fix is upstream —
training-data composition and upper class support — not another downstream corrector. In that case
tell me **what specifically is wrong with the training prior**: is it stale in time, under-weighted in
the warm classes, truncated at the top, or drawn from a different regime than we serve?

That determines whether the eventual repair is a reweighting, a prior refresh, a class-support
extension, or a full retrain — and those differ enormously in cost and risk.

## What I want back

1. Conditional versus unconditional, with the decomposition and intervals.
2. The reconciliation with resolution/reliability, including any correction to the 98.88 / 1.12
   figure.
3. The held-out causal size of the correction, pooled and severe-tail.
4. What specifically is wrong with the training prior, if the answer points upstream.
5. Your honest read on whether this is the main event or a ~1% curiosity. Say it plainly either way;
   a clear "curiosity" retires a large line of work cheaply.

## Sequencing

No repair and no candidate. Four candidates already contend for two remaining ordinary dates, which
is more than the evidence can referee. Any retrain-shaped fix requires release #1 and its own fresh
evidence on post-August-19 dates.

## Constraints — unchanged

- Base on `codex/workstation-why-is-the-morning-cool-2026-08-23a` @ `b893857e`. Every branch in this
  chain is held and unmerged. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.** The evening repair depends on it.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. The single answer I need most is whether this
bias is conditional. Everything else follows from it.
