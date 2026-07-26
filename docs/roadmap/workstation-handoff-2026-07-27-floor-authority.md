# Workstation handoff — 2026-07-27: make the floor trustworthy (a standing queue)

The profit-edge queue is **accepted and closed**, and it is the most useful thing this
program has produced in weeks. Three things earned that:

- **"No slice is historically exploitable"** is the finding I wanted, delivered without
  hedging. The all-hours point estimate being positive while both lower bounds are negative
  and only 49.61% of market-days are positive is exactly the kind of result that gets
  rationalised into a green light elsewhere. You called it NO.
- You found a **real invariant violation** and then immediately undercut your own headline:
  impossible bands are only 2.9512% of hour-20 squared loss, and the blend *improves*
  aggregate hour-20 Brier by partly rescuing the 38 above-floor cases. A less careful report
  would have sold the bug as the answer.
- You separated the bug from the hypothesis rather than merging them into one story, and
  declined to claim resource enforcement you had not measured this queue.

**This handoff is a queue. Work in order, do not idle.**

## What the evidence actually says

The executable order is: floor applied → preblend captured → incumbent blended at
context-specific alpha (α<1 on 97.29% of rows, median 0.50) → simplex cleanup → **floor never
reapplied**. Preblend has zero partitions with impossible mass; the final output has 108 of
124, averaging 10.08% and reaching 49.59%. Dallas 2026-07-07 is the clean illustration: floor
and winner both 100–101 °F, preblend winner probability `0.999999927`, final `0.501756776`.
We took a near-certainty and halved it.

But the two populations behind that are opposites, and this is the crux:

| Population | n | Preblend Brier | What the blend does |
| :--- | ---: | ---: | :--- |
| Floor identifies winner | 86 | `0.000499` | **damages** a near-perfect prediction |
| Settlement 1–11 °F above floor | 38 | `1.999905` | **rescues** a catastrophic one |

So the blend is an indiscriminate hedge against the floor sometimes being wrong, and the
impossible mass is the symptom. **Do not "just reapply the floor after blending."** That
restores the invariant and destroys the hedge on the 38, and aggregate Brier probably gets
worse. The real defect is that we do not know *when the floor is trustworthy* — and every one
of the 38 reports failed `weather_forecast`, `wu_current` and `wu_history`, which is why you
preregistered `authoritative_wu_print_freshness_v0.1`.

## Mission 1 (urgent, before anything else): is the live serving path affected?

The diagnosis ran on the repaired candidate replay. `current_blend.py` is loaded by the live
capture loop on the production host, so the same ordering plausibly runs in live serving —
which would mean our published evening distributions assert probability on bands the day has
already excluded, and any price-taker acting on them is structurally wrong at exactly the
hour the market is most certain. You already sized that liability at `0.468218` over 735
opportunities.

Answer narrowly and with evidence: **does live serving reproduce the same post-blend floor
violation, or does the live path differ?** Read-only. If it does, quantify recent live
occurrence. Do not change serving. This is the one question I want answered before any
modelling work, because it decides whether this is a research artifact or an active bleed.

## Mission 2: implement the freshness-conditional floor — candidate only

Implement `authoritative_wu_print_freshness_v0.1` as the discriminator you preregistered, and
make the floor conditional on it:

- floor **fresh and authoritative** → it is a physical fact; the blend must not move mass
  below it, and the invariant must hold in the final output;
- floor **stale or unauthenticated** → it is not a floor at all; do not treat it as a hard
  constraint, and let the incumbent hedge as it does today.

Constraints:

1. **Candidate only.** No promotion, release, pointer, activation, or serving change. Build
   it, evaluate it, stop. Deployment is a separate operator decision.
2. Evaluate on the **untouched preregistered window** you froze. Report the aligned-86 and
   above-floor-38 populations **separately as well as pooled** — a change that improves the
   pool while damaging the 86 is the same mistake the current blend makes, just in reverse.
3. Report the **physical invariant** as a first-class metric: partitions with impossible mass
   must go to zero on the fresh-floor population. That is a correctness claim, not a score.
4. If freshness turns out **not** to separate the 86 from the 38, say so and stop. You already
   noted many aligned partitions carry the same failed-source label, so the discriminator may
   not hold. A negative result here is worth more than a tuned one.

## Mission 3: what is the other 97%?

Impossible mass is 2.95% of hour-20 loss. Near-resolved rows explain 99.96% of signed evening
excess. So the bulk of the evening gap is elsewhere — most likely the 38 above-floor cases,
whose preblend Brier is near-maximal at `1.999905`.

Characterise it: when the day exceeds the printed high by a median 5 °F, what did the market
know that we did not? Was the true high already printed somewhere we do not read, was it
knowable from trajectory, or was it genuinely unknowable at 20:00? **If it was unknowable, say
so** — that bounds how much of the evening gap is recoverable at all, which is worth knowing
before anyone spends more on it.

## Guardrails

- `data/` strictly read-only, proven deny-write ACL, single declared output root.
- **No promotion, release, pointer, activation, serving, scheduler, collector, sizing, or
  trading-surface change.** Mission 2 is a candidate build, nothing more.
- Topic branches only; never push master; no PRs, no merges. Merge timing stays with me.
  You may push topic branches without asking — that is standing authorization.
- Any large improvement is a leakage suspect first, and this mission is unusually exposed:
  a freshness signal derived from the same prints we are predicting is a leakage trap. State
  the time-validity argument explicitly.
- NOT-DONE and NOT-REHEARSED lists stay first-class. Do not claim resource enforcement you
  did not measure.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-authority.md`: the live-path answer with
evidence, the candidate results split by population with the invariant metric, and your
Mission 3 characterisation. Push all topic branches.

Context: streak 5/14, earliest lock ~2026-08-03, advancing on its own. Your profit-edge branch
merges here tonight in the quiet window — it supersedes the skill-gap branch, which I will not
merge separately. Rebase on master before any merge-readiness claim.
