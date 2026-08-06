# Workstation handoff 2026-09-04a — can we even detect the win?

Run this now. **Power analysis and design only: no fit, no retrain, no candidate, no scoring, no
network, and above all no reading of the reserved window.** `-08-16a` remains queued for
2026-08-05 04:30 and takes priority.

## Why this is urgent rather than academic

The reserved confirmation window **2026-08-06 → 08-19** was set aside when the first retrain looked
imminent. It is not imminent any more. Realistically: lock 08-04, a 7-day release build window to
~08-11, then the PIT corpus at 1–2 weeks, then the retrain. The retrain will land well after 08-19.

The reservation still works — those days stay valid held-out evidence as long as nobody looks at
them. But **14 days was chosen by calendar convenience, not by power.** And every day I delay this
question is a day I cannot retroactively reserve, because unreserved days get read by other work.

So: **if 14 days is not enough to detect the effect we expect, I need to know today**, while
extending the reservation is still free.

This project has already been burned by an underpowered evaluation. Toronto parity was called a win
and was not one; item-224's apparent win was leakage. I would rather discover the test is too weak
before spending the only clean window we have than after.

## 1. What effect size are we actually testing for?

Do not assume one — derive it from what has been measured:

- Conditional correction of the cool bias closed **24.69% of the raw HGB–market Brier gap**, interval
  excluding zero.
- At the **served** level the same correction was **5.39%, interval crossing zero** — downstream
  stages absorb most of it.
- Severe tail: SSE −25.53%, positive excess −30.06%, improving all five held-out dates.
- The forecast lookahead contributes ~0.070 C-equivalent of centre displacement, ~6% of the −1.2131
  raw bias.

The retrain targets the prior and class support. **What served-level effect should we expect, with an
honest range?** If the honest answer is "somewhere between nothing and 5%", say that — it changes the
design completely.

## 2. Is 14 days enough?

For each candidate test, compute the detectable effect at 80% power and the N required for the
expected effect:

- pooled Brier;
- the **09:00–14:00 primary objective slice**;
- the severe tail (4.26% of rows carrying 60.2% of loss).

Use the correct unit of clustering. Market-days are correlated within a day and within a market;
treating snapshot rows as independent is exactly the error that manufactures false wins. Prior
sessions used year- or day-clustered intervals — keep that discipline.

Toronto-only versus 12-market changes the answer enormously. Report both, and say which one the
retrain's evidence will actually be.

## 3. The multiple-comparison problem nobody has priced

The catastrophic-slice gate requires **no protected slice to regress by more than the pooled
improvement**, across **53–54 slices**. The first candidate breached it on 19 of 54; the repaired one
on 3 of 53.

With that many slices and a per-slice bar, what is the probability a **genuinely good** retrain fails
the gate by chance alone? If that probability is high, the gate is not protecting us — it is a
lottery that will reject good work and eventually get overridden, which is worse than no gate.

Report the false-rejection rate under a null of "uniformly better", and if it is unacceptable,
propose a correction that preserves the gate's actual purpose: catching a candidate that wins on
average by breaking a specific regime.

## 4. Then tell me what to reserve

Given 1–3: **is 2026-08-06 → 08-19 sufficient?** If not, exactly how many additional days, and
starting when?

I will act on this immediately — extending the reservation is cheap now and impossible later. If the
answer is that no realistic number of days can detect the expected effect, that is the most important
finding available and I want it stated plainly rather than softened.

## Hard constraint on method

**You cannot read the reserved window to answer this.** Derive power from the development window,
prior-year data, and the already-published measurements. If a quantity genuinely requires the reserved
data, that quantity is not available — say so and work around it.

Reading 08-06 → 08-19 to size a test on 08-06 → 08-19 destroys the thing being sized.

## What I want back

1. Expected served-level effect size, with an honest range and its derivation.
2. Detectable effect and required N for each candidate test, correctly clustered, Toronto and fleet.
3. The slice-gate false-rejection rate, and a correction if it is unacceptable.
4. A concrete reservation recommendation: how many days, from when.
5. Your recommended primary endpoint — one pre-registered test, not a menu. If we get to choose after
   seeing results, we will fool ourselves.

## Sequencing

Nothing downstream depends on this being fast, but the reservation decision is time-sensitive and
mine to act on. Independent of every held branch.

## Constraints — unchanged

- Base on `master` @ `9d65a21a`.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.** The last one is the entire point of this mission.
- **No network access.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Lead with item 4 — the reservation
recommendation — because that is the only part I have to act on before the window opens.
