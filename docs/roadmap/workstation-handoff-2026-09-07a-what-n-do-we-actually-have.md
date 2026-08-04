# Workstation handoff 2026-09-07a — what N do we actually have?

Run this now. **Inventory, contamination audit and power arithmetic only: no fit, no retrain, no
candidate, no scoring of held candidates, no reserved dates.** `-08-16a` runs 2026-08-05 04:30 and
takes priority over this.

## The question nobody has asked

`-09-06a` told us what N we *need*. It did not ask what N we already *have*, and neither did I until
tonight. Measured on the production host just now, from `data/backtest/market_day_labels.csv`:

| | |
| --- | ---: |
| Label rows | **705** |
| Distinct target dates | **67** (`2026-05-27` → `2026-08-02`) |
| `quality_grade = complete` | 292 |
| `quality_grade = partial` | 413 |
| `promotion_countable = True` | 564 |
| Dates with **≥1** market complete | **31** |
| Dates with **all 12** markets complete | **21** |
| …of those, **before** `2026-07-22` | **9** (`2026-06-07` → `2026-07-18`) |

**Every power calculation this project has made was designed against five date clusters.** The
development window has been `2026-07-22 → 07-26` since `-08-24a`, and every mission since — mine
included — inherited it without asking whether it was a real constraint or a convention that stuck.

In the crossed date/market bootstrap, **the date dimension is the binding one.** Five date clusters
is why the intervals are wide enough to swallow every effect we have measured. If the admissible
date count is 14, or 20, or 31 rather than 5, the entire power picture changes **without touching
one reserved date.**

## The question I cannot answer

**How many independent, uncontaminated date clusters can we assemble right now, outside the reserved
window?**

`-09-06a` puts the 09:00–14:00 slice at **N=39** at the propagated point effect. We have 67 dates of
history. **If enough of them are admissible, the primary objective becomes measurable today** — and
the reserved window stops being the only path to a confirmation.

I do not know the answer and I am not going to guess it, because the answer turns entirely on
contamination, which I cannot audit from here.

## Contamination is the whole game — and this project has already been burned by it

The frozen per-market base HGB artifacts date from **2026-06-10 → 06-13** (Toronto's
`feature_model_hgb.pkl` is 06-13). Any date those artifacts saw in fitting **cannot** serve as
held-out evidence for a candidate derived from them. `item-224`'s apparent win was leakage; that is
exactly the error that must not recur.

So the real question is not "how many dates are labelled." It is: **which dates are (a) labelled,
(b) adequately covered, (c) not seen in fitting by the artifact under test, and (d) not reserved,
burned, or already declared?**

Relevant constraints you should not have to rediscover:

- **Reserved `2026-08-06 → 11-03`** — untouchable.
- **Burned `2026-07-27 → 07-31`.**
- **Declared to `-08-16a`: `2026-08-01 → 08-05`.**
- **`2026-07-31` is a `rows[-1]` regime boundary** — but it is about artifact *provenance*, not
  target dates. Replaying old dates through the current pipeline satisfies it, as `-09-05a` did.
  Do not exclude a date merely for being old.
- **Marine features go dark after `2026-06-13`** (unscheduled sidecar refresh). Dates on either side
  of that may not be feature-comparable. Say what it costs rather than silently dropping them.
- **`forecast_high` was not point-in-time in the trainer** — the *fit* was contaminated, the
  *evaluation* was not. That distinction may widen what is admissible for evaluation. Check it.

## Do not assume the admission bar

I used "all 12 markets complete" to get the 21 above. **That is my bar, not necessarily the right
one.** The crossed bootstrap resamples dates and markets *independently*, so a date with 8 complete
markets is still a full date cluster contributing 8 market cells. If partial-fleet dates are
admissible, the date-cluster count could be far closer to 31 than to 21.

Tell me what each endpoint actually requires, and what each admission bar costs in bias. **Do not
lower the bar just to make N look better** — that is the same instinct that produced every problem
we have fixed this week.

## Pre-empting the answers I do not want

**"Relax the clustering back to exchangeable market-days and everything is significant again."**
Absolutely not. That is the exact defect `-09-05a` and `-09-06a` just corrected. The crossed
bootstrap stays. If the honest answer is wide intervals, the answer is wide intervals.

**"Read some reserved dates to check."** No. Reserved is `2026-08-06 → 2026-11-03`;
`docs/operations/reserved-confirmation-window.md` is the single source of truth and wins over this
document. A read destroys the date permanently.

**"Count a date as held-out because it probably was not used."** No. If you cannot demonstrate a
date was outside the fit for the artifact in question, it is contaminated. Absence of evidence of
contamination is not evidence of absence, and this is precisely where `item-224` went wrong.

**Do not re-fit, re-train, or score either held `-08-16a` candidate.** This is an inventory and
audit mission. If answering properly requires scoring a held candidate, stop and say so — that is
itself the finding.

**Do not propose extending or shortening the reservation.** It is not the lever here, and it needs
an explicit dated operator decision regardless.

## What I want back

1. **The enumerated admissible held-out date set, per endpoint**, with an explicit exclusion reason
   for every one of the 67 dates that does not make the cut. I want the map, not just the count.
2. **The number I most want: how many independent date clusters can we assemble right now, outside
   the reserved window?** If it is ≥39, say so in the first line, because the 09:00–14:00 objective
   would then be measurable today.
3. **Was the five-date development window a real constraint or an inherited convention?** Trace it.
   If it was convention, say so plainly — that would mean we have been designing against an
   artificial N for weeks.
4. **Recomputed power for each endpoint at the true available N**, same crossed bootstrap, 2,000
   replicates, seed 90501, so it is directly comparable to `-09-06a`'s table.
5. **The contamination map**: which artifacts saw which dates, and what that leaves. If the frozen
   artifacts saw nearly everything, that is the answer and it is worth knowing precisely.

**The clean negative is genuinely valuable here.** If the honest finding is that the frozen artifacts
saw most of the history and the uncontaminated budget really is about five dates, then the reserved
window is the only path to any confirmation, the retrain cannot be sized before it, and I need to
know that before the build window is spent. Say it plainly if so.

## Sequencing

`-08-16a` at 2026-08-05 04:30 takes priority; do not let this delay it. This mission needs no
release pointer, no corpus rebuild, and no fresh capture.

## Constraints

- Base on `master` @ `a2ce353f`.
- **Reserved window is `2026-08-06 → 2026-11-03`** — see
  `docs/operations/reserved-confirmation-window.md`, the single source of truth, which wins over any
  handoff text. Not read, enumerated, evaluated, or substituted.
- Also excluded: **2026-07-27 → 07-31** (burned) and **2026-08-01 → 08-05** (`-08-16a`'s declared
  set). Enumerating a date as *excluded* is required here; that is not the same as reading it.
- **POST-regime artifacts only.** `2026-07-31` is a `rows[-1]` provenance boundary; never mix
  artifacts across it.
- **Never weaken the trusted observed-high floor.**
- **No network access, with one carve-out: the `git fetch`/clone needed to read this mission and push
  your topic branch is expected and permitted.** (My previous handoffs forbade all network access
  while requiring a fetch to read them — that was my error, disclosed by `-09-06a`.)
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. **Lead with item 2.** If the number is large,
say so first and let me reconsider the whole confirmation plan; if it is small, say that first and I
will stop pretending the reserved window is optional.
