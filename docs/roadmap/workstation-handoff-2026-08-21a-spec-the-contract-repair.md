# Workstation handoff 2026-08-21a — specify the contract repair (no build)

Run this now. **Specification only: no repair, no candidate, no artifact, no fit, no scoring, no
fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Where this stands

`-08-20a` confirmed the defect on the direct serving path — 28,680 / 28,680 affected cells — and
established that **every** affected feature is train/serve **skew**, not a legitimate lane gap. The
strict oracle ceiling is **51.40%** of excluded-lane positive excess; since that lane holds 81.21% of
remaining excess, the ceiling is roughly **42% of total remaining loss**. It is a ceiling, not a
forecast.

This is now the largest identified lever in the project. It is also, unlike everything else this
week, a **defect** rather than a new idea — which changes how it should be handled.

Two corrections worth carrying forward:

- My missing-branch hypothesis was wrong. Nulls are **median-imputed** and categories become zero
  dummies, so they never reach HGB missing branches. The model cannot tell it is blind; it consumes a
  plausible median as though observed. And the imputation direction does **not** explain the cool
  displacement, so blindness and centre displacement are separate mechanisms.
- Provenance is mixed: WU availability **regressed at `5735b573`**, while full METAR/ECCC field
  parity was **never implemented**. Those are two different repairs and should be specified
  separately.

## The mission — write the specification

### 1. The regression half

Trace `5735b573` precisely: what changed, which fields stopped reaching the matrix, on what date, and
whether a clean restoration exists or the surrounding code has moved on. Say whether reverting the
behaviour is straightforward, awkward, or unsafe, and why.

### 2. The never-implemented half

Enumerate exactly which METAR/ECCC fields the **training contract expects** against what the
extractor currently produces. Field by field: source, unit, role, and what it would take to populate
it faithfully.

### 3. Point-in-time validity — the trap that killed `-08-18a`

Every restored field must be **cutoff-valid**. Restoring a value using any observation published
after the capture cutoff is leakage, and it would be undetectable in aggregate scores while
invalidating everything downstream. Specify the point-in-time semantics per field, and name the
fields where cutoff-valid restoration is *not* achievable — those must stay missing rather than be
approximated.

### 4. Does this need a retrain? — the question that sets the cost

Because this is skew rather than a coverage gap, restoring the fields makes **serving match
training**. If that is right, the repair may be serving-side plumbing with **no refit at all**, which
is dramatically cheaper and lower-risk than a model change and can be validated by replay parity
against the training contract.

Establish whether that holds. If any field's distribution at serve time would differ materially from
what the artifacts were fitted on, say so — that field needs a retrain and belongs in a separate
phase.

### 5. Should median imputation survive the repair?

HistGradientBoosting supports NaN natively. Median-imputing a genuinely absent observation destroys
the model's ability to represent its own ignorance, and it will still apply to fields that cannot be
restored cutoff-validly. Give a recommendation with reasoning. Treat it as a **separate** change from
the restoration, with its own evidence, not a free rider.

### 6. Would the release parity gate have caught this?

The release contract includes a **train/serve parity** check that has reported NOT_EVALUABLE in every
candidate scorecard we have produced. Would a real parity receipt have detected this skew? Will it
detect a recurrence once release #1 exists? If not, that is a gap in the gate itself and I want it
named.

## Sequencing — still no repair

The feature extractor is roll-sensitive and this is a material serving change. It goes through the
full gate after release #1, with its own fresh evidence. Do not write the repair, a shim, a feature
view, or a candidate.

Do not let this compete with the three held candidates for the August 4–5 dates. It should be
validated on post-August-19 evidence through the real gate.

## What I want back

A specification precise enough that the repair can be built without re-deriving any of it, plus:

1. Regression versus never-implemented, split cleanly, with per-field detail.
2. The cutoff-valid list and the cannot-be-restored list.
3. A clear yes or no on "serving-side only, no retrain", with the reasoning.
4. The parity-gate answer from section 6.
5. Anything that makes you doubt the 51.40% ceiling. A ceiling built on a wrong assumption would
   send us down an expensive path, and I would rather hear the doubt now.

## Constraints — unchanged

- Base on `codex/workstation-prove-1000-blindness-2026-08-20a` @ `6a068783`. Every branch in this
  chain is held and unmerged. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03** or **2026-08-06 → 08-19**.
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

Push the topic branch and report the branch and commit. Expect it to be held until release #1 exists.
