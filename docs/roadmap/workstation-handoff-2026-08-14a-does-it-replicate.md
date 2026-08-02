# Workstation handoff 2026-08-14a — does it replicate?

`-08-13a` did what it was built to do. The gate tightened the bootstrap by `0.005223` and flipped its
sign, cut newly-severe from 2.669% to 0.590%, took protected-slice failures from 19/54 to 3/53, and
leaked nothing — all 15,675 excluded band rows copied the incumbent exactly.

**But the fresh evidence was one calendar day, and it was a favourable one.** The incumbent scored
`0.056481` on July 31 against `0.052530` on July 27–30, and the candidate's improvement was
`-0.006860` against `-0.002370`, roughly 2.9x larger. A paired market-day bootstrap over 12 units
that all share one calendar day — one synoptic regime, one model state, one forecast vintage —
overstates the effective sample. The interval genuinely tightened; that part is structural. Whether
non-regression actually holds is not yet established.

There is no modelling work in this mission. **Nothing is fitted, selected, tuned, or changed.**

## The mission

Rescore the **already-frozen** candidate artifact and the **already-frozen** 20% threshold on every
additional clean date now available, and report whether the July 31 result replicates.

The frozen inputs, which must not change:

- research candidate artifact `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85`
- gate `floor_available and floor_removed_mass > 0.20`
- the `-08-09a` harness and all three primary gates as applied in `-08-13a`

If anything about the candidate or threshold changes, this stops being a replication test and the
new dates are burned. Do not refit, do not reselect, do not adjust the cut.

## Pre-commit the score set before you look at any of it

This is the discipline that makes the result mean anything. Rescoring until it passes and stopping
there is the same multiple-testing error we avoided in `-08-13a`, run in the opposite direction.

1. At declaration time, enumerate every complete, coverage-clean, promotion-countable POST-regime
   date outside July 22–30 that the mirror actually holds. August 1's labels should arrive with the
   04:30 mirror run on August 3; August 2's on August 4.
2. **Declare that exact list, in the report, before scoring any of it.** The list is fixed once
   declared. Do not extend it after seeing a result, and do not drop a date that scores badly.
3. Score every date on the list. Report every date, including any that fail.

If fewer than three dates are available, say so and label the outcome **provisional** rather than a
verdict. Thin is fine as long as it is named.

## What I want back

1. **Per-date deltas**, one row per calendar day, including July 31 restated. This is the replication
   question: does the improvement recur, or was July 31 a good day?
2. **The pooled multi-day estimate**, with the bootstrap recomputed over the full market-day set
   across all days — more independent units is the entire point.
3. **The new dates alone**, separately from the pooled figure, since July 31 is no longer fresh for
   this artifact.
4. All three primary gates on the pooled estimate.
5. Whether `capture_hour=14` and `capture_hour=17` recur. Hour 17 *passed* at `-0.005742` in the
   ungated run and failed at `+0.008626` here with severe rows barely moving (42 → 43); hour 14
   missed by `0.000205` against a bar of `0.006860`. I expect at least one of them not to replicate.
6. Whether `D_class=D1` recurs. It failed in **both** runs (`+0.002559` then `+0.032302`), so I
   expect it to, and that would confirm it as structural rather than noise.

## Secondary, strictly diagnostic

`D1` is the only failure present in both runs, and it is the case the continuation objective should
have been *best* at — the day settled exactly one band above the floor.

Diagnose why, and **do not fix it**. No refit, no threshold change, no candidate variant. Any repair
is a future mission with its own fresh evidence; attempting one here would burn the dates this
mission exists to spend properly. If you find the mechanism, describe it and stop.

## What would make this worth confirming

Stated in advance so it is not decided after the fact: this candidate becomes worth taking to the
reserved confirmation window only if **all three primary gates pass on the pooled multi-day
estimate** *and* the per-date deltas are consistently negative rather than carried by one day.

Anything less and it stays held and keeps iterating on ordinary evidence.

**The reserved 2026-08-06 → 08-19 window remains untouched** — not read, enumerated, evaluated, or
substituted. It is the final confirmation set and nothing has earned it yet.

## Constraints — unchanged

- Base on `codex/workstation-floor-informativeness-gate-2026-08-13a` @ `55f5f5dd`. Held and unmerged
  on purpose, as are its two parents. Do not merge any of them.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **July 22–30 stays burned.** Development and the previous score window may not enter this
  evaluation at all, except that July 31 is restated as already-scored, clearly labelled as such.
- **Never weaken the trusted observed-high floor.** Control, not a tunable.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- **Scope the freshness gate to the exact dates you declared.** Do not gate on the mirror being
  current to today — it cannot be. If a declared date turns out to lack labels, report it missing;
  do not wait on it and do not substitute.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Expect it to be held. The production host is
at or near its release-#1 lock and nothing here touches that path.
