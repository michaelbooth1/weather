# Workstation handoff — 2026-07-30c: Toronto scope, and get parity to strict

Two of your results are much bigger than the missions I set. Read the scope decision and the
parity section before anything else.

## Operator decision: release #1 is Toronto-only

I checked the fleet: 11 F markets and Toronto as the single C market. You found no F-family
market qualifies and ten remain shadow-only, with Atlanta genuinely failing the quality gate.
That leaves Toronto as the only promotion candidate, so:

**Release #1 is scoped to Toronto. All eleven F markets stay shadow-only.**

This is not a workaround and I am not touching the gate. It is also coherent rather than
convenient: the 14-day soak, the PIT window, and the streak are all Toronto. The F-family result
is **information, not an obstacle** — it says our F models are not good enough to promote, which
is exactly what a 1.243x-of-market candidate should look like from a quality gate that works.

Confirm explicitly in the handback that **Toronto itself qualifies**. You told me no F market
does; you did not tell me the C market does, and I am not going to assume it.

## Your parity result may have closed our top defect

> diagnostic replay shows the incumbent matches all 24 partitions within **2.23e-16**

That is float64 machine epsilon. The incumbent reproduces recorded output **exactly**.

For weeks `NOT_ACCOUNTED_FOR` has been our top open defect — recorded output having zero strict
whole-partition matches against preblend, replay-final, incumbent or market, in both regimes.
If the incumbent reproduces it to machine precision when replayed through the **real serving
path**, then that finding was an artifact of the offline replay harness, not a property of the
system. We can reproduce what we emit. That unblocks falsifying every offline gain we have
measured and never been able to act on.

I am not recording it as closed yet, because it is **one market-day, one market, diagnostic
grade**, and the strict lane blocked. Getting it to strict is now the most valuable thing you
can do.

## Mission 0: push the branch

`0beb40b8` is local-only. That is the second handback in a row where the work existed on one
machine with no backup, on a fleet that has taken five unexpected shutdowns in ninety days.
Push it before starting anything. `e13851cc` being on origin is good — do the same here.

## Mission 1: strict forward shadow for Toronto

You ran Austin. Toronto is the release market, so run Toronto.

- Does the **strict** lane pass for Toronto, or does it block on invalid captured-input hashes
  the way Austin did?
- If it blocks, that failure **is** the diagnosis — report the exact hashes, the inputs, and when
  they went invalid.
- Is the invalid-hash condition **Austin-specific or fleet-wide**? Check every market. If it
  reaches Toronto it is a lock problem, not a release problem, and I need to know today.
- Is this the same evidence-integrity class as the split `order_books_long` pairs I found — a
  historical artifact of writers and tiering racing — or something new?

## Mission 2: widen the parity result

Once Toronto passes strict, extend it: more market-days, not one. Report the number of
partitions compared, the worst absolute divergence, and any partition that does not match.

A single clean day is an anecdote. A clean two-week window at strict grade closes the defect,
and I will record it as closed on that evidence.

Keep reporting the **first point of divergence in the pipeline**. `candidate divergence begins
at candidate_raw` is exactly the right shape of answer — and expected, since the candidate is a
different model. What matters is that the incumbent lane does not diverge at all.

## Mission 3: the number we have never had

If the incumbent is what production actually serves, then **every model-versus-market figure we
have quoted is for a lane we do not serve.** Our 1.243x is preblend. The incumbent has never
been scored against the market.

So score it: **incumbent binary Brier versus raw market**, on the clean POST regime, with the
full Murphy decomposition, alongside preblend and replay-final for comparison.

That is the baseline any future improvement has to beat, and we have been flying without it. It
may be better than preblend or considerably worse; either way we have been reasoning about the
wrong lane and I would rather know now than after the lock.

## Mission 4: the go/no-go checklist, still outstanding

From `-30a`, not delivered: the ordered exact-command checklist from locked window to verified
pointer, each step with its expected artifact, failure mode, and rollback. Now it can include
the `NO_ACTIVE_POINTER` rollback you proved and the Toronto-only scope.

I want to execute a checklist on lock day, not improvise one.

## Priority

Mission 0, then 1, then 4, then 2, then 3. One and four are on the lock-day critical path;
two and three are the ones that change what we do afterwards.

## Guardrails

Unchanged. No real pointer activation, no promotion, no serving change, `data/` read-only,
topic branches only, no PR/merge/master push. Your isolated activate/rollback rehearsal without
touching production is the standard to hold.

## Handback

`docs/roadmap/agent-report-<date>-workstation-strict-parity.md`: Toronto qualification and the
strict-lane verdict first, then the invalid-hash scope, then the checklist, then the widened
parity and the incumbent scoring.

Context: streak **8/14**, lock ~2026-08-03, then 7 days to build. Warm tier merged here at 01:15.
