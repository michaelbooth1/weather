# 305. Settled-Day Finalization Order, Partial-Label, And Nightly Run-Date Gate [COMPLETE 2026-06-24 - NIGHTLY ANALYSIS CAN RUN BEFORE FINAL ARTIFACTS AND MIX TARGET DATES]

Goal: enforce a strict settled-day analysis order so nightly and daily reports
cannot mix pre-finalization artifacts, stale target dates, or partial-label
evidence into promotion and trading conclusions.

Source: settled 2026-06-23 log audit. Settled-day freshness eventually passed
after all 12 labels existed, but earlier nightly reports saw source-lag warnings
and blocked before finalization fully settled. Daily learning had a run-date
mismatch relative to the audited day, trading evidence selected stale maker
runs, taker bakeoffs were generated before labels finalized, and all June 23
labels were partial because snapshot gaps remained.

Why this matters: the individual gates can be correct and still produce a
confusing daily packet if they run in the wrong order. Promotion, trading, and
operator reviews need a single target date, a finalization barrier, and explicit
partial-label propagation before any report claims market skill or bot evidence.

Why it is not already covered: item 120 checks settled-day finalization
freshness, item 293 fixed daily-analysis fail-closed behavior, and item 294
checks broad input freshness/consistency. June 23 shows the orchestration gap:
post-label taker/maker/audit refreshes must run between finalization and daily
learning, and the final reports must reject mixed target dates and partial-label
overclaims.

## Design

1. Define the settled-day analysis dependency graph: label finalization,
   settled-day freshness, disagreement rehydration, taker finalization,
   maker paper/trading evidence, snapshot evaluation, daily learning, daily
   flow, and nightly promotion checks.
2. Add a finalization barrier that prevents daily learning/nightly promotion
   from running until required target-date artifacts are fresh or explicitly
   marked non-critical.
3. Add target-date invariants across daily learning, daily flow, trading
   evidence, taker bakeoffs, maker reports, and snapshot evaluation.
4. Propagate partial-label status into promotion claims, model scoreboards, and
   trading evidence, with clear `diagnostic_only` or `promotion_countable`
   status.
5. Add rerun/resume behavior so an early blocked nightly can refresh after
   finalization completes instead of leaving stale blocker conclusions as the
   latest packet.

- [x] Encode the settled-day analysis dependency graph and finalization barrier.
- [x] Add target-date invariant checks across daily/nightly artifacts.
- [x] Propagate partial-label status into promotion and evidence countability.
- [x] Add rerun/resume behavior after finalization completes.
- [x] Add tests for pre-finalization nightly runs, mixed target dates, and
  partial-label diagnostic-only days.

Closed notes: daily refresh now inserts a `settled_day_analysis_barrier` step
after post-label scoring and before promotion refresh. The barrier writes
`settled_day_freshness.json` and `settled_day_analysis_barrier.json`, hard-stops
downstream promotion/daily steps on incomplete finalization even under
`--continue-on-error`, and emits a `--resume-from-step
settled_day_analysis_barrier` command. Daily learning now checks declared target
dates across settled freshness, barrier, trading evidence, root cause, and
corpus-backed scoring artifacts, and partial-label days are carried as
`diagnostic_only` with `labels_not_promotion_countable` broad-claim failures.

Acceptance: daily learning and nightly promotion cannot publish final
target-date conclusions until required post-settlement artifacts are current,
all consumed artifacts agree on target date, partial labels downgrade broad
promotion claims to diagnostic-only, and an early run is automatically refreshed
or clearly superseded after finalization completes.

Related: items 37, 120, 157, 199, 205, 229, 293, 294, 295, 298, 302, 303, 304.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - NIGHTLY ANALYSIS CAN RUN BEFORE FINAL ARTIFACTS AND MIX TARGET DATES`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

