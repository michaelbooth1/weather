# Workstation handoff — 2026-08-10a: stand down until release #1

Accepted. The harness is exactly right, and **it is deliberately not merged** — see below.

Building the judge first paid for itself immediately: you found **six specification defects** that
would otherwise have surfaced mid-confirmation, when the cost of discovering them is a burned
confirmation window rather than an afternoon.

The two I value most are the ones where you refused to paper over a gap:

- **The accepted replay cannot implement the native continuation gate.** It exports final 11-band
  probabilities, not native `P(D=0)`, `P(D=1)`, `P(D>=2)`. You implemented the real gate, made it
  `NOT_EVALUABLE` without a hash-bound native export, and labelled the July run's band-relative proxy
  as a proxy. The easy move was to let the proxy quietly stand in for the real thing.
- **You declined to invent a catastrophe threshold.** That hole is real, and leaving it visible is
  better than filling it with a number nobody can defend.

`TIE_SELF_CHECK` that "can never qualify a real candidate" is the right way to admit a degenerate case
without weakening a real gate. And the exact reproductions — daily-first Brier `0.05255831235690557`,
9,032 severe rows, positive excess `1.718715410383236` — match the accepted baselines to the digit,
which is what makes the harness trustworthy as an instrument.

## The branch is held, not rejected

`codex/workstation-gate-harness-2026-08-09a` touches `src/weather/schema_registry_recent_data.py`,
which is roll-sensitive. Merging it costs a fleet roll and restart budget, and buys nothing: the
harness cannot judge anything until a candidate exists, and no candidate can exist until release #1.
It merges after the lock, in a quiet window. Nothing for you to change.

## Open decision I am taking, not delegating

The catastrophic-slice threshold is mine to set, and it must be set **before** a candidate exists so it
cannot be shaped by one. My working proposal, to be finalised before the retrain is built: *no
protected slice may regress by more than the pooled improvement* — a pooled win must not be a net
transfer from one market or hour into the others. That is a relationship rather than a magic constant,
and it is defensible without knowing anything about the candidate. I am recording it as open rather
than freezing it tonight, because it is a promotion-contract decision and there is at least a week
before it binds.

## Stand down

There is no high-value work left on this thread that is independent of release #1, and I would rather
say that than invent a mission:

- the retrain is blocked — nightly retrain has no release identity to bind parity against;
- the harness is `NOT_READY` pending parity, replay, and release receipts that only exist after a
  release;
- the native continuation gate is `NOT_EVALUABLE` pending a candidate-native export;
- the release build itself runs on the production host, not here.

So: **stand by.** Do not start new research on the model thread, do not refine the harness
speculatively, and do not touch the reserved 2026-08-06 → 08-19 window.

**Resume trigger:** I will send a new handoff once release #1 exists and is verified. At that point the
first task is implementing the continuation-objective candidate against the frozen spec and the harness
you just built — in that order, with the harness unchanged from what it is today except for defects
found by running it.

You have produced eight consecutive reports that changed what we believe, including three that killed
directions I was pushing. That is the whole value of the arrangement. Thank you — genuinely.

## Guardrails

Unchanged while standing by. `data/` read-only, topic branches only, no PR, no merge, no master push,
no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or expose the sync
credential, and the reserved window stays untouched and unswapped.
