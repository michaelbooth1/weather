# Workstation handoff `-09-13a` — why is the maker starved of fresh inputs?

Written 2026-08-05 by the operations master agent on the production host. Read this on
`origin/master` and execute it. **This is now the top MM-blocking item.**

## The gap this fills

`-09-11a` built the countability machinery and the execution-tape producer, and it was explicit that
it did **not** touch the starvation itself: *"This mission did not call providers or mutate those
workers."* So the thing actually standing between us and a first countable MM day is **unowned**.

From the `2026-08-04` active maker run:

```text
99 x NO_QUOTE_STALE_INPUT            <- infrastructure starvation
33 x NO_QUOTE_KNOWN_EDGE_PERMISSION  <- the promotion block

live_forward_gate = BLOCK   "nine markets had stale model/CLOB inputs, and the
                             observation-trigger runtime was stale for Los Angeles"
preflight         = WARN    same stale producer inputs
```

**Three-quarters of the no-quotes are an infrastructure problem that promotion PASS does not touch.**
Release #1 will not fix this. The operations agent previously told the operator that release #1 →
promotion PASS → quotes flow; that was wrong, and this mission exists because of it.

**Note the measurement trap.** `status.ps1` reports `ALLHEALTHY` and the capture loops genuinely are
alive and heartbeating. Loop liveness is **not** the same as *the maker seeing a fresh input for a
given market at a given decision time.* Only the second gates countability. Do not be reassured by
the first — it is what hid this.

## Host measurements taken 2026-08-05 ~11:00, as a starting point only

`python -m weather.market.market_microstructure audit` — fleet `ok:false`, threshold 140.1s:

| Market | Result |
| --- | --- |
| denver | 2 gaps over threshold, max **201.0s** |
| miami | 1 gap, max **207.5s** |
| los-angeles | 1 gap, max **151.8s** |
| the other 9 | clean |

All twelve were trailing-fresh at 32.6s at audit time, so nothing was down. **This is book-tape gap
analysis, which is a different measurement from what the maker checks.** Treat it as a hint, not an
answer, and say how the two relate.

## Questions

### Q1 — Characterise the staleness exactly

For the `2026-08-04` and `2026-08-05` active windows, per market and per decision: **which input was
stale, by how much, and against which threshold.** Name the exact artifact, the exact freshness rule,
and the code that enforces it.

"Nine markets were stale" is not actionable. `market X's model row was N seconds old against a limit
of M at decision time T` is.

Distinguish clearly between **model rows**, **CLOB books/features**, and **observation-trigger
runtime** — Los Angeles failed on the third, and that may be a different defect from the other two.

### Q2 — Root cause

Hypotheses worth testing explicitly, and **do not stop at the first one that fits**:

1. **Per-market sequential sampling.** If a producer walks 12 markets in sequence, the last market's
   snapshot is materially older than the first's when the maker reads them. That would neatly explain
   *nine of twelve* stale rather than all or none. `-09-11a` noted in passing that per-market
   sequential sampling "would also leave large blind intervals". **Test this first.**
2. **Cadence versus tolerance.** The maker preflight requires a model snapshot newer than
   `max_model_age_seconds = 900`. What is each producer's actual period, and what is the worst-case
   age it can deliver? A 10-minute nominal loop that occasionally takes 6 minutes will breach 900s.
3. **Priority contention.** Capture runs `AboveNormal`; the maker runs `BelowNormal` deliberately so
   the streak always wins. Does that starve the maker's own reads, or delay the producers it depends
   on?
4. **Memory pressure.** The historical signature of all-market gaps on this host is memory pressure
   rather than network. Rule it in or out with evidence.
5. **Los Angeles specifically.** It appears in both the observation-trigger staleness and the book
   audit. Is it one defect or two? Note LA is one of several markets whose local clock is far from the
   host's.

### Q3 — The fix

Specify it, and **implement it only if it is provably roll-safe and reversible.** State per file
whether it is roll-free or roll-sensitive, by import closure — not the `SOURCE_PATTERNS` glob.

If the fix is operational (cadence, scheduling, ordering, a task registration) rather than a code
change, **say so and do not write code.** An operational fix the operator can apply and revert in one
command is worth more than a merge here.

If the honest fix requires a new or reconfigured producer loop, cost it: **memory, CPU, disk per day,
and priority class.** This is a 16 GB host that has lost both capture loops to memory pressure before,
and any new loop competes with the streak, which outranks all MM work.

### Q4 — What must be true for a day to be un-starved

Give the mechanical check: for a maker day to be free of `NO_QUOTE_STALE_INPUT`, what must hold for
all 12 markets across the whole active window? Express it so it can be verified before the window, not
diagnosed after.

## Deliverable

1. Q1–Q4 answered, with per-market evidence.
2. A clear statement of **which no-quotes are infrastructure and which are legitimate abstention** —
   the 33 permission rows are a real, correct refusal and must not be "fixed".
3. Per-file roll-safety verdicts.
4. **What this means for the MM timeline**: is a countable day reachable the day after
   `WeatherMakerExecutionCapture` is registered, or does starvation push it out?
5. A `## What would falsify this` section.

## Constraints

**The Toronto capture streak outranks everything in this mission.** Do not change, restart, re-adopt,
or reconfigure a running capture loop. Diagnose from retained evidence. If a fix requires touching a
loop, **specify it for the operator to apply in a quiet window** rather than doing it.

**Do not touch the release or PIT path, and do not merge anything.** The release #1 build runs on the
production host tonight.

**Do not relax the promotion gate**, and do not attempt to convert the 33
`NO_QUOTE_KNOWN_EDGE_PERMISSION` rows into quotes. Those are the gate working.

**Do not weaken the trusted observed-high floor.**

**Reservation:** re-based 2026-08-04 — nothing is reserved today, window armed but undated.
`docs/operations/reserved-confirmation-window.md` is the single source of truth; re-read it and honour
its five binding rules.

**Network:** `git fetch` and `git push` only. **No provider calls** — everything needed is captured.

Push `codex/workstation-why-is-the-maker-starved-2026-09-13a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-05-workstation-why-is-the-maker-starved.md`.

## How to disagree

If the starvation turns out to be benign — a threshold set too tight rather than inputs genuinely
too old — **say so plainly**, because the fix is then the threshold and the whole MM timeline changes.
Equally, if it is worse than described and touches the capture path the streak depends on, say that
first and loudly. Do not soften either finding.
