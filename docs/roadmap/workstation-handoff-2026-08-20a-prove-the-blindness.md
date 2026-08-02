# Workstation handoff 2026-08-20a — prove the blindness, and bound what it costs

Run this now. **No candidate, no artifact, no fit, no scoring, no fresh dates.** `-08-16a` remains
queued for 2026-08-05 04:30.

## Why

`-08-19a` found that nine of 19 base features are completely empty at 09:00–14:00 in the
floor-excluded lane, cloud state exists only for Toronto, and several of those empty fields are among
the most-used split fields in the trained trees — while METAR/ECCC capture is near-complete.

If that holds, it outranks every objective we have engineered this week. We would have been designing
new learning targets for a model that cannot see half its inputs in exactly the lane carrying 81% of
remaining positive excess and 84.58% of the primary objective.

Before anything is built on that premise, I want it nailed down. A wrong diagnosis here would be far
more expensive than the forecast-anchor dead end, because it would justify a serving change.

## 1. Skew or coverage gap? — the question that changes the fix

There is a logical tension in the finding that I want resolved explicitly.

If those fields were empty during **training** too, the trees could not have split on them heavily.
Since they *are* among the most-used splits, they must have carried values somewhere in the training
population. So which is true?

- **(a) Train/serve skew** — populated when the artifacts were fitted, empty at inference in this
  lane. The trees would then be routing these rows down missing-value branches that were fitted on a
  different population. Actively harmful, and the highest-value repair available.
- **(b) Lane-specific coverage gap** — populated at other hours, markets, or in the qualified lane,
  and legitimately absent at 09:00–14:00 in both training and inference. The trees learned real
  splits from rows that had them; these rows honestly lack the information. Still worth fixing, but
  it is an enrichment rather than a defect.

Answer with evidence: report per-feature population rates split by hour, by lane (qualified versus
excluded), and by training population versus captured-input inference rows. Name (a) or (b) per
feature — they may differ.

## 2. Is live serving affected, or only replay?

`-08-19a` reasoned from captured-input replay rows. Those *are* what serving consumed, so the
inference is strong — but "production is defective" deserves a direct check, not a deduction. Confirm
against the live serving path as directly as you can from the mirror, read-only, and state precisely
what you could and could not verify from there.

If you cannot establish it without production access, say so and name the exact check the production
host would have to run. I will run it here.

## 3. What does missingness actually do to the output?

For the affected features, determine which branch missing values take and whether that pushes the
predicted centre systematically in one direction. We already know this lane's failure is centre
displacement, so: **is the direction of the missing-value branch consistent with the observed
displacement?** If yes, that is a mechanism, not a correlation.

## 4. Bound the prize

Give an upper bound on what restoring the contract could buy, on the excluded lane only, using an
oracle-style construction rather than a fitted model — the same shape as the centre-versus-width
ceiling work. I need to know whether this is worth a serving change or is a 2% effect.

State the bound's assumptions plainly and do not present it as an expected gain.

## 5. Provenance — regression or never-implemented?

The extractor admits captured METAR/ECCC only to temperature and the hard floor. Was that always
true, or did it regress? If there is a commit or date where these fields stopped reaching the matrix,
find it. A regression and a never-implemented gap imply different risks and different fixes.

## Sequencing — do not fix this now

**Any repair is post-release-#1.** The feature extractor is roll-sensitive, and restoring the
information contract is a material serving change that must go through the full gate with its own
fresh evidence. Do not write a repair, a shim, a candidate, or a feature view in this mission.

This finding is in fact the strongest argument yet *for* release #1: a concrete, high-value model
change that we currently have no validated way to ship.

## Constraints — unchanged

- Base on `codex/workstation-1000-information-gap-audit-2026-08-19a` @ `f032bf4e`. Every branch in
  this chain is held and unmerged. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03** (reserved for `-08-16a`) or
  **2026-08-06 → 08-19** (final confirmation set).
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

Push the topic branch and report the branch and commit. The two answers I most need are **(a) versus
(b) per feature** and **the bound in section 4**. If the honest bound is small, say so — that would
retire this line and is worth knowing before it costs a serving change.
