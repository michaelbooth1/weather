# Workstation handoff `-09-08a` — is the cool bias a correctable offset, or does it need the retrain?

Written 2026-08-04 by the operations master agent on the production host. Read this on
`origin/master` and execute it.

## Why this mission, and why now

Release #1 locked today. It **freezes the June per-market HGBs** — it does not refresh them. We are
about to commit, for the life of release #1, to base models we have concluded are **systematically
too cool**. The first retrain is the only event that can change that, and it has not been scheduled.

Two prior results make this the highest-value open question:

- **Centre, not width, is the lever.** Oracle ceilings: centre **74.97%**, width **10.94%**.
- **The cool bias is the centre defect.** `centre-displacement-mechanism-found`: a too-cool HGB puts
  probability mass below the trusted observed-high floor; truncation then yanks the centre warm. The
  evening defect and the morning defect are believed to be the *same* bias, with the floor masking it
  in the evening and nothing masking it in the morning.

**But we have never measured the bias directly.** We inferred it from a truncation mechanism. This
mission measures it.

### The power argument — read this before proposing anything else

Every recent mission has died against the 09:00–14:00 endpoint's ~75.76% power (`-09-07a`). **This
mission deliberately does not use that endpoint.** A systematic signed centre error, pooled across 34
date clusters × 12 markets × all hours, is a completely different measurement with vastly more
support. We are not trying to detect a candidate win. We are characterising a defect in the frozen
incumbent.

If your design finds itself needing the 09:00–14:00 slice endpoint to answer Q1–Q4, you have drifted
off-mission. Say so and stop.

## The inventory you must use

Use the **34-date clean set** from `-09-07a` (`≥8 markets promotion_countable` + replayable). Do not
re-derive it; do not fall back to the five-date window; do not use `quality_grade=complete`, which
yields only 9 fleet dates. `promotion_countable` is the canonical admission bar.

Report `N` and its basis for **every** interval you produce.

## Questions, in priority order

### Q1 — What is the signed centre error of the frozen base HGBs?

Predicted centre minus realized high, on the frozen per-market artifacts, over the 34-date set.
Report the pooled estimate **and** the decomposition by:

- **market** (all 12; note the 1 C / 11 F native-unit split — do not pool raw °C with °F),
- **hour-of-day bucket**, including but not limited to 09:00–14:00,
- **lead time**,
- **calendar month**.

Sign convention stated explicitly, once, at the top. "Cool" must mean one thing in the whole report.

### Q2 — Is it a constant, or is it structured? (the decisive question)

Distinguish, with evidence:

- **(a) a single global offset** — correctable serving-side, cheaply, without a retrain;
- **(b) per-market constants** — correctable serving-side, 12 numbers;
- **(c) hour- or lead-dependent** — a shape, not an offset; harder, probably needs the retrain;
- **(d) drift** — see Q3.

This is the question that decides whether the fix is cheap or expensive. Do not skip to a
recommendation without separating these.

### Q3 — Test the "stale June prior" hypothesis, which is falsifiable

The stated root cause is a **stale, cool June prior**. That predicts the bias **grows with distance
from the training distribution** — smallest in June, largest in August.

Test it. Report the trend with a crossed interval.

**This is the highest-information question in the mission**, because the two outcomes point opposite
ways:

- **Bias grows with distance** → a retrain genuinely fixes it, and its value decays after, which
  makes *retrain cadence* a first-class operational parameter we have never set.
- **Bias is flat across months** → it is *not* staleness. It is a structural property of the fitting
  procedure, and **a retrain would reproduce it.** That would be a major finding and would redirect
  the entire first-retrain plan.

Do not assume the first outcome because it is the received story. It is currently a hypothesis with
no direct test behind it.

### Q4 — What does correcting centre do to the floor interaction?

The mechanism says the cool bias puts mass below the floor, and truncation yanks the centre warm.
So a centre correction **reduces the mass the floor truncates**, and the two effects are coupled.
The naive expectation — that they simply add — is probably wrong.

**Trace this, do not infer it.** That instruction is written because inferring this exact interaction
is how the last mechanism claim went wrong.

**The trusted observed-high floor is not in scope and must not be weakened, softened, re-tuned, or
"improved" in any variant you construct.** It is load-bearing and it is the one absorber whose
benefit survives correct clustering. A proposal that weakens it will be rejected without review.

## Deliverable

1. A written answer to Q1–Q4, with N and clustered intervals throughout.
2. **A recommendation on whether a serving-side centre correction is admissible pre-retrain** — and
   if you judge it is, the exact form, plus what evidence would be required to ship it. If you judge
   it is not, say so plainly; that is an equally useful answer.
3. **What this implies the first retrain must fix**, distinguishing what a retrain repairs from what
   it would reproduce.
4. A `## What would falsify this` section. Every claim you make, state what result would have
   overturned it.

## Constraints

**Reserved dates `2026-08-06` → `2026-11-03` must not be read, replayed, scored, or inspected.**
`docs/operations/reserved-confirmation-window.md` is the single source of truth and outranks this
document. Reading a reserved date destroys it permanently. All 34 dates are on or before
`2026-08-03`, so this should never bind — if you find yourself near it, stop and report.

**`2026-07-31` is a `rows[-1]` regime boundary.** It concerns **artifact provenance, not target-date
age**. Never mix artifacts across it. This mission spans June through August, so this *will* come up —
handle it explicitly and say how.

**Clustering.** Every interval uses **crossed date × market** clustering. Exchangeable market-day
resampling produces intervals that are too narrow and has already retracted one headline result. If
an interval crosses zero, say so in the same sentence as the point estimate.

**Do not quote proxy sensitivity as candidate power.** That error has now been made twice.

**No fitting, no retraining, no candidate scoring, no promotion, no pointer or release-path change.**
This mission measures the frozen incumbent. The two held continuation candidates are out of scope.

**Do not touch the release or PIT path.** The release #1 build runs imminently on the production host;
a change there would collide with it.

**Network:** you may `git fetch` and `git push` — that is required to read this mission and return
your work. **No provider calls, no paid-source access, no new data collection.** Everything needed is
already captured.

Push a branch named `codex/workstation-is-the-cool-bias-correctable-2026-09-08a`. **Do not open a PR
and do not merge.** Write your report to
`docs/roadmap/agent-report-2026-08-04-workstation-is-the-cool-bias-correctable.md`.

## How to disagree with this mission

If the measurement turns out to be unsound, or the decomposition is not identifiable from what is
captured, **say so and stop** rather than producing a number that cannot bear weight. Three of the
last four missions improved materially by contradicting the handoff that launched them, including
correcting my own errors. That is the expected behaviour, not a failure mode.
