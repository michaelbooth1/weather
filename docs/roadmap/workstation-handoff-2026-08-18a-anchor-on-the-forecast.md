# Workstation handoff 2026-08-18a — anchor on the forecast, not the floor (build only)

Run this now. It consumes **no** fresh scoring dates. `-08-16a` remains queued for 2026-08-05 04:30.

## Why

`-08-17a` settled where the loss actually is. After gating, the excluded rows carry **81.21% of
remaining positive excess** and **80.10% of remaining severe rows**, and **84.58%** of the
09:00–14:00 primary-objective window sits outside the gate. The floor-anchored line has been
improving the third of the data that was already best served.

Your own recommendation is the right one and this mission takes it: a **cutoff-valid
forecast-residual distribution for early and mid-day rows**. The continuation objective was correct
in *form* — learn a displacement from a known anchor — and wrong in *anchor* for rows where the
observed high is not yet informative. Where the floor is uninformative, the forecast is the anchor
that is.

## The mission — build only

Fit and freeze a residual-distribution candidate for the **excluded** population: rows where
`floor_available` is false or `floor_removed_mass <= 0.20`.

- Learn the distribution of the residual between the settled bucket and the **cutoff-valid** forecast
  anchor, then decode back to absolute buckets, mirroring the structure that worked for the
  continuation lane.
- **Cutoff-valid is the whole game.** Use only the forecast vintage actually available at the capture
  cutoff. A later revision, a settled-day reconstruction, or any post-cutoff source state is
  leakage, and this is the most likely way this mission fails silently. State explicitly how you
  established vintage validity.
- Apply the ordinal-monotonicity lesson from `-08-15a` to the residual support from the start rather
  than as a later repair — but keep the parameterization coarse and pre-declared.
- The qualified population keeps whatever `-08-16a` selects. This lane is **additive and disjoint**;
  it must not alter a single qualified row.
- All hard-floor stages stay frozen. The floor remains a control, never a tunable.

**Do not score it on any fresh date.** Development and selection stay entirely inside July 22–26.

## The methodological problem I want you to respect

We now have three candidates competing for a shrinking pool of fresh evidence. Every additional
candidate fitted on July 22–26 and tested against the same dates inflates the family-wise error rate,
and that is precisely how this project produced the item-224 "win" that turned out to be leakage.

So: **this artifact is built to wait.** Ordinary dates after August 3 are only August 4 and 5, and
August 6–19 is the reserved confirmation window for whichever candidate we ultimately commit to. Do
not assume this one gets scored soon, and do not design it around a quick read.

Build it well rather than fast.

## What I want back

1. The frozen artifact SHA-256 and the frozen parameterization.
2. **How you established cutoff-validity of the forecast anchor**, in enough detail that I can
   attack it. This is the claim I will be most sceptical of.
3. Development-fold evidence on the excluded population only: does residual anchoring beat the
   incumbent there, and by how much on positive excess and severe rows?
4. The monotonicity check on the residual support, before and after, as `-08-15a` reported it.
5. Proof that zero qualified rows changed.
6. Honest self-assessment of whether the development gain could be an artifact of selecting on those
   folds. You caught this risk yourself last time; do it again.

## Constraints — unchanged

- Base on `codex/workstation-gate-cost-diagnosis-2026-08-17a` @ `b5be028a`. Every branch in this
  chain is held and unmerged on purpose. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31** (burned and reserved),
  **2026-08-01 → 08-03** (reserved for `-08-16a`), or **2026-08-06 → 08-19** (final confirmation).
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch, commit, and frozen artifact SHA-256. Expect it to be
held and to wait for evidence.
