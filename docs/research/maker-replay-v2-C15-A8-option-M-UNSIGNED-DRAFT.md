# Maker replay v2: C15/A8 option M text edits (owner-ruled M; text not yet signed)

**Status: the owner ruled C15/A8 = option M** ([DECISION_LOG](../operations/DECISION_LOG.md) 2026-10-15, "C15/A8 =
option M"); option X is not taken. This file holds the three text edits, and one consequence edit, to the
[v2 registration draft](maker-replay-v2-registration-DRAFT.md) for option M: the C15 manifest builder and the A8
re-run move to the §4 whole-minute rule. It edits nothing in place. The edits become signed text only when the
registration that carries them is signed; until then they are draft wording. The code lands only after master-agent's
review (same DECISION_LOG row).

**Read when:** folding the option M edits into the registration draft, or reviewing the option M code (built on
`claude/mrv2-c15a8-minute-SPECULATIVE-20261014`, carried by `claude/mrv2-owner-rulings-20261015`). **Do not use
for:** current state or decisions in force ([STATE_OF_PLAY](../operations/STATE_OF_PLAY.md),
[DECISION_LOG](../operations/DECISION_LOG.md)).

## Code for option M (built off r3 5dedc198a)

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

  The blind gate still reads the engine's horizon at the instant, as the engine does. So `attribution.pull()` still
  labels a `blind_re1` `HORIZON_NOT_ELIGIBLE` pull A8 on that instant read. In the end-side gap this can come up to
  59 s before the clause horizon leaves 1..2. The Defender found 2 such labels on dense-11-01-dst (A-1, 2026-10-14);
  edit 3 carries the carve-out.

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

Replace the whole sentence "The asymmetry cannot be reached inside the clause windows (every active minute has a lead
in 1..2, and the interval end withdraws the legs), so it changes no scored decision." with:

> The asymmetry is reachable only in the part of a minute after a captured descriptor moves a lead out of 1..2
> mid-minute, for at most 59 s until the interval end at the next minute start. There `blind_re1`'s gate pulls at
> the instant of the descriptor, while `informed-v0`'s HOLD path still holds its existing legs until the interval end
> withdraws them. So in that gap the arms can differ, and it can change a scored decision. At every minute start of an
> active interval the lead is in 1..2, so the asymmetry is not reachable elsewhere.

On the four registered fixtures, every decision in that end-side gap, on every arm, is `NO_QUOTE` with no legs
resting (Defender probe P3, 2026-10-14). So the fixtures do not exercise the held-legs case; it follows from the
rule, not from an observed fixture difference.

## Edit 3: C15 row, the A8 sentence

Report 6 proposed changing only the "other than ..." clause. The implemented rules also read the horizon at the
minute start in the direct condition and in completeness (i). Without that, any decision in the end-side gap (edit
2's exception) would be "a decision taken at such a horizon" and fail the re-run. In the fixtures every such decision
is `NO_QUOTE`; a held-legs HOLD there is the rule's case, not an observed one. So the edit covers the whole sentence.
It also carries a carve-out for the blind gate, which still labels A8 on the read at the instant (Defender A-1).
Replace:

> A8 is not self-labelling: a difference is A8 only where the engine's own horizon read is missing or outside 1..2,
> and the re-run fails on any decision taken at such a horizon other than the `OUTSIDE_ACTIVE_INTERVAL` cancel at the
> instant the horizon leaves 1..2, on legs still resting after that instant, or on any window cut where the engine
> reads 1..2.

with:

> A8 is not self-labelling: a difference is A8 only where the engine's own horizon read, taken as it stood at the
> latest minute start (§4 whole minutes), is missing or outside 1..2, or, for `blind_re1`'s horizon gate
> (`HORIZON_NOT_ELIGIBLE`), where the engine's read at the instant of the pull is missing or outside 1..2, which can
> precede that minute start by up to 59 s. The re-run fails on any decision taken at such a minute-start horizon
> other than the `OUTSIDE_ACTIVE_INTERVAL` cancel at the first minute start at or after the instant the horizon leaves
> 1..2, on legs still resting after that minute start, or on any window cut where the engine reads 1..2, except the
> part of a minute before the first minute start after the descriptor change.

## Consequence edit 4: C15 row, the fixture-delta sentence (required by the re-run)

Under the minute windows, "The A8 fixtures show zero quote, fill and cash deltas" no longer holds. On w0-09-27-roll,
`clock_only` places one quote fewer (two legs) at each bound (`at_price` and `strictly_through`), with zero fill and
cash change. The difference comes only from the minute rule, so it lies in a minute gap; which side of the window
that gap is on has not been independently confirmed. Replace it with:

> The A8 fixtures show zero fill and cash deltas, and zero quote deltas except one fewer `clock_only` quote (two
> legs) at each bound (`at_price` and `strictly_through`) on w0-09-27-roll, inside a minute gap.
