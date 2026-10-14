# Maker replay v2: C15/A8 option M text edits (UNSIGNED DRAFT, pending owner M/X; do not land)

**Status: UNSIGNED DRAFT. Pending the owner's M/X ruling. Do not land.** This file proposes three text edits, and
records one consequence edit, to the [v2 registration draft](maker-replay-v2-registration-DRAFT.md) for **option M**:
the C15 manifest builder and the A8 re-run move to the §4 whole-minute rule. It edits nothing in place, and it is not
signed or registered text. If the owner rules option X instead, this file and its branch are dropped, and the option X
disclosure (T1 report 6) applies.

**Read when:** the owner rules on C15/A8 M vs X, or someone reviews the speculative branch
`claude/mrv2-c15a8-minute-SPECULATIVE-20261014`. **Do not use for:** current state or decisions in force
([STATE_OF_PLAY](../operations/STATE_OF_PLAY.md), [DECISION_LOG](../operations/DECISION_LOG.md)).

## Code on the speculative branch (off r3 5dedc198a)

- `horizon.minute_lines`: a descriptor read at instant s counts from the first UTC minute start at or after s.
  Derived local midnights already fall on a minute and are unchanged.
- `execution_manifest.active_intervals` cuts runs over `minute_lines`. On every eligible (date, condition) of the
  registered fixture panel, its construction gives exactly the `intervals.evaluate` windows.
- `attribution.horizon_sources` cuts the A8 clause windows over `minute_lines`.
- A8 reads `clause_horizon`, the engine's own descriptor reads under the minute rule, in all four of its tests:
  - the direct A8 condition;
  - the cut rule;
  - completeness (i), where the exempt cancel is the one at the minute start at which the clause horizon leaves 1..2;
  - completeness (ii).

  The blind gate still reads the engine's horizon at the instant, as the engine does.

## A8 re-run on minute windows (4 registered fictional fixtures, 32 cells)

All 32 cells PASS, with only the class A8, zero clause violations and zero unexplained cuts. The minute windows
differ from the exact ones on dense-09-27, dense-11-01-dst and w0-09-27-roll, but not on w2-on-level.

| Fixture | Verdicts | Changed decisions (sum over 8 passes) | Quote delta | Fill delta | Cash delta |
| --- | --- | --- | --- | --- | --- |
| dense-09-27 | 8 PASS | 372 | 0 | 0 | 0 |
| dense-11-01-dst | 8 PASS | 1710 | 0 | 0 | 0 |
| w0-09-27-roll | 8 PASS | 2612 | 0, except `clock_only` −1 (both bounds) | 0 | 0 |
| w2-on-level | 8 PASS | 8 | 0 | 0 | 0 |

Two mutants FAIL the re-run, as they must:
- the registered exact-instant A8 rules on minute windows (the Defender's 10-13 probe);
- exact windows under the minute A8 rules.

The negative control (a cut where the engine reads lead 1) still FAILs.

## Edit 1: §4, after "The manifest builder computes intervals mechanically ..."

Add:

> Intervals are on whole UTC minutes. A descriptor change at instant s takes effect from the first minute start at or
> after s. A band first discovered at 00:03:20 is active from 00:04. A captured descriptor moving a lead out of 1..2
> at 00:03:20 ends the interval at 00:04. Derived local-midnight changes fall on a minute and are unaffected.

## Edit 2: §4 gate-ordering disclosure

Replace "(every active minute has a lead in 1..2, and the interval end withdraws the legs), so it changes no scored
decision" with:

> (at every minute start of an active interval the lead is in 1..2, and the interval end withdraws the legs). The
> exception is at most 59 s after a captured descriptor moves a lead out of 1..2 mid-minute, where informed-v0's
> resting legs are held until the interval end at the next minute start.

## Edit 3: C15 row, the A8 sentence

Report 6 proposed changing only the "other than ..." clause. The implemented rules also read the horizon at the
minute start in the direct condition and in completeness (i). Without that, the HOLD decisions in the end-side gap
(edit 2's exception) are "a decision taken at such a horizon" and fail the re-run. So the edit covers the whole
sentence. Replace:

> A8 is not self-labelling: a difference is A8 only where the engine's own horizon read is missing or outside 1..2,
> and the re-run fails on any decision taken at such a horizon other than the `OUTSIDE_ACTIVE_INTERVAL` cancel at the
> instant the horizon leaves 1..2, on legs still resting after that instant, or on any window cut where the engine
> reads 1..2.

with:

> A8 is not self-labelling: a difference is A8 only where the engine's own horizon read, taken as it stood at the
> latest minute start (§4 whole minutes), is missing or outside 1..2, and the re-run fails on any decision taken at
> such a horizon other than the `OUTSIDE_ACTIVE_INTERVAL` cancel at the first minute start at or after the instant the
> horizon leaves 1..2, on legs still resting after that minute start, or on any window cut where the engine reads
> 1..2, except the part of a minute before the first minute start after the descriptor change.

## Consequence edit 4: C15 row, the fixture-delta sentence (required by the re-run)

Under the minute windows, "The A8 fixtures show zero quote, fill and cash deltas" no longer holds. On w0-09-27-roll,
`clock_only` places one quote fewer (two legs) in the start-side gap, with zero fill and cash change. Replace it with:

> The A8 fixtures show zero fill and cash deltas, and zero quote deltas except one fewer `clock_only` quote on
> w0-09-27-roll inside a start-side minute gap.
