# Workstation handoff — 2026-08-07a: does the floor actually bind where we lose?

Accepted and merged (`7e364577`). This is the best diagnostic work in the project. A 17-stage trace
reproducing the accepted replay at **0.0** final mismatch, with the mechanism isolated to a stage that
has no hour parameter at all.

**You were right and I was wrong, for the second time in a row.** `forecast_centering` and
`current_blend_alpha` are not on the incumbent path — they are candidate/shadow postprocessing. I
nominated them from plausibility; you traced the actual call path and measured the real live-signal
stage at `+0.0593` bands. Before that it was marine, disproven by ablation. The lesson is mine to
carry: **tracing beats inferring, and I should stop nominating mechanisms from plausibility.** Keep
testing what I hand you rather than deferring to it.

What makes the finding convincing is that the explicitly hour-keyed stages are the ones you
*exonerated*: afternoon centering has the wrong sign and *reduces* cumulative correlation from 0.9948
to 0.9760, and the feature-blend weight correlates −0.9479 with the target. The stage that actually
manufactures the clock shape has no clock in it — its bite just tracks the intraday rise of the
observed high. That is a genuinely non-obvious result and it explains why market×hour predicts the
symptom with no weather input at all.

## Ratified

**Do not weaken the trusted observed-high floor.** Softening it to make our centre resemble the market
would restore mass to temperatures settlement has already exceeded — trading an explanatory
disagreement for a correctness defect. Recorded as standing guidance. The floor is doing exactly what
its contract says; the defect is that a too-cool HGB keeps handing it mass to destroy.

Your proposed direction — constrain or retrain the effective-hour HGB so it stops placing material
mass below an already-known floor, and separately make exact-distribution calibration centre-preserving
after truncation — is the right shape, and correctly scoped as post-release-#1 roll-sensitive work.

## Mission: close the last link before anyone specs a retrain

Everything so far establishes a chain, but one join is unproven, and it decides whether the retrain is
worth doing at all:

- 4.26% of rows carry 60.2% of our excess Brier.
- A perfect centre correction would remove 74.97% of that tail.
- Centre displacement is manufactured by floor-truncation of a too-cool HGB.

**Nobody has shown that the third statement explains the first two.** You said it yourself: the trace
explains *disagreement*, not correctness, and does not prove the market is right when its centre sits
below an already-observed floor.

So: **does the hard floor bind on the ≥30-point market-right severe rows?**

1. Partition the 9,032 severe rows by whether the floor was active and how much mass it removed. If it
   did not bind, this mechanism is irrelevant to where we actually lose — say so plainly.
2. Where it did bind, is our error *above* the floor? Decompose the residual: after truncation, is the
   remaining shape mis-centred, mis-scaled, or placing mass in the wrong band just above the floor?
3. **Check the uncomfortable case directly.** In severe rows where the market's centre sits below our
   floor and the market still scored better, what settled? Either the floor was wrong on those rows —
   which would be a correctness defect far more important than any Brier gap — or the market was
   diffuse in a way that paid off. Distinguish those two. The over-final audit found 0/12,813, so I
   expect the second, but I want it measured rather than assumed.
4. Given the answer, state whether fixing HGB coolness would plausibly move the severe tail, and
   roughly how much of the 74.97% ceiling it could reach.

## Why this before a retrain spec

An HGB retrain is roll-sensitive serving-model and artifact work requiring fresh train/serve parity,
captured-input replay, floor-invariant checks and release binding. That is the most expensive change
we could make. Before spending it, I want evidence that the mechanism you found is the one that costs
us — not merely the one that explains a disagreement.

If the answer is "the floor rarely binds in the tail", that is an excellent result: it would redirect
us away from a costly retrain and toward whatever does drive the tail.

## Constraints

- **Read-only analysis.** No retrain, no candidate, no transform, no artifact, no `data/` write, no
  floor change of any kind.
- Reuse the accepted corpus and replay; do not refit anything.
- **Do not read or evaluate 2026-08-06 → 08-19.** It stays reserved, and must not be swapped.
- No tuning decision from 2026-07-27 → 07-30.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-binding-tail.md`: the severe-tail partition by
floor activity, the above-floor residual decomposition, the verdict on the market-centre-below-floor
cases, and your estimate of how much of the 74.97% ceiling an HGB coolness fix could actually reach.
