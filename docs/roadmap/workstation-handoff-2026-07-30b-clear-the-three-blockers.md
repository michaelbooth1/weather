# Workstation handoff — 2026-07-30b: clear the three blockers

The rehearsal paid for itself. Three real gates that would otherwise have surfaced inside the
7-day build window are now named, five days early. That is exactly what I wanted from it, and
a NO-GO with an enumerated failure list is the good outcome, not the bad one.

## Mission 0, before anything else: push the branch

`e13851cc` is committed **locally only**. The report exists on exactly one machine, and that
machine is the one without a backup — this host has had 5 unexpected shutdowns in 90 days.
Push the topic branch now.

If the push fails, tell me the exact error. Our Git LFS bandwidth is exhausted; uploads should
not be metered, but if GitHub is refusing LFS operations wholesale that would explain it, and
your branch almost certainly touches no `.pkl` so a plain push should go through.

## What you proved

Two results materially de-risk tonight, and I am proceeding on them:

- **149 simplex failures gone, 2,000-iteration PIT qualification passed.** That was the last
  measured BLOCK and it is now clean end to end.
- **The gzip-only probe passed the technical release path** — 36 raw tapes, a verified 220-file
  inactive release, strict pointer resolution, 128 serving roles bound. That answers Mission 2:
  the release build survives compressed evidence, so I am applying the warm-tier pilot tonight
  after the 01:15 merge and the full 192 folders tomorrow.

Note the warm tier is not in `origin/master` as you tested — it merges at **01:15 tonight**.
Pull before you re-verify anything that depends on it.

## Mission 1: why does Atlanta block, and is it required?

Report the **exact gate and reason**, not the summary. Then answer the question that decides
what we do:

- Is Atlanta blocked by a **genuine quality bar** — meaning serving it would be wrong — or by an
  **evidence gap** we can close?
- What is the smallest honest fix for the evidence case?

**Do not fix this by weakening the gate.** If Atlanta genuinely fails, the legitimate move is to
**scope release #1 to the markets that pass** — a narrower first release is safer, not weaker,
and we are not trading Atlanta today. Tell me which markets pass and what a scoped release would
contain. I will make the scope call; I need the reason first.

## Mission 2: rollback for a release with no predecessor

`active release pointer has no verified rollback target` is a first-release chicken-and-egg, and
the semantics are not ambiguous: **rollback from release #1 means returning to the no-active-
pointer state.** That state is not hypothetical — it is exactly what production runs right now,
and has run for months, so it is the best-evidenced rollback target we will ever have.

Make that explicit and verified rather than implicit:

- a first activation may declare the null/no-pointer state as its rollback target;
- rollback must **prove** the serving path works after deactivation, not merely unset a file;
- and it must be exercised in the rehearsal — activate the inactive release, roll back, confirm
  serving resolves as it does today.

An activation we cannot reverse is one I will not authorize, so treat this as the hard gate.

## Mission 3: forward-shadow parity — this is bigger than procedure

You reported no canonical procedure collects parity/forward-shadow evidence against the inactive
first release. That gap matters far more than it sounds.

**It is the mechanism that would finally tell us what production serves.** Our top open defect
is `NOT_ACCOUNTED_FOR`: recorded output has zero strict whole-partition matches against preblend,
replay-final, incumbent or market, in both regimes, and we cannot reproduce our own emissions.
A forward shadow that runs the inactive release alongside live serving and compares outputs
instant by instant is exactly the instrument that answers it.

So build the procedure to serve both purposes:

- run the inactive release in shadow against live serving over a declared window;
- record, per instant, the release output and the recorded production output with enough
  identity to compare them exactly;
- report agreement, and where they diverge, **the first point of divergence in the pipeline**
  rather than only the terminal mismatch.

If that shows the release reproduces recorded output, we have closed the defect and release #1
becomes the answer to it. If it shows divergence, we finally have a localised place to look
instead of a whole-pipeline mystery.

## Priority

Mission 0 now. Then 2, then 1, then 3 — rollback is the hard gate, Atlanta decides scope, and
the shadow procedure is the one that can slip past the lock if it must, because it can run
against an inactive release at any time.

## Guardrails

Unchanged. No real pointer activation on production, no promotion, no serving change, `data/`
read-only, single declared output root, topic branches only, no PR/merge/master push.

## Handback

`docs/roadmap/agent-report-<date>-workstation-release-one-blockers.md`: the Atlanta gate and
reason first, then the rollback implementation with its exercised proof, then the shadow
procedure.

Context: streak **8/14**, lock ~2026-08-03, then 7 days to build. Production host 155.6 GB free;
warm tier merges 01:15 and the pilot applies tonight.
