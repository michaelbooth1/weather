# Maker fill model v3 replay read: registration DRAFT (2026-10-16)

**Status: DRAFT, UNSIGNED, NOT IN FORCE.** This text authorizes nothing. Until the owner signs it and a reviewed
code change sets `SIGNED_REGISTRATION_SHA256` in `src/maker_core/replay/fill_v3_embargo.py`, every *scored* read
through the fill model v3 is refused in code. Descriptive reads (for example the own-session reconciliation) do
not need this registration and are never scored evidence.

Owning plan: [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md), section "October 16
build 1". Related: the LFC pre-registration (`docs/research/live-fill-calibration-preregistration-2026-10-09.md`, on master) §1, §4 and §8;
[reserved confirmation window](../operations/reserved-confirmation-window.md).

## 1. Question

Would maker replay v2's economic result change if fills followed the queue-aware rule v3 instead of the 89a
price-path bounds? v3 is a third, narrower fill hypothesis. It does not replace either v2 bound.

## 2. Why a separate registration is needed

- LFC pre-registration §8: if `c_at` ≥ 0.7 with N_at ≥ 10, "a replay rerun needs its own registration". This is
  the draft for that rerun, or for any other scored v3 replay.
- LFC §1 and §8 forbid pooling LFC ratios with replay or shadow results. A scored v3 read uses LFC only to choose
  *which rule to run*. LFC ratios never enter the scored statistic, its interval or its decision rule.
- Replay v2's registration names only the two 89a bounds (`fill_model.BOUNDS`). v3 is not a bound in that
  registration and cannot be added to it.

## 3. The rule (frozen at `fill-v3.0`)

As implemented in `src/maker_core/replay/fill_v3.py`:

1. **Queue position.** A resting BUY leg at `p` joins the back of its own level. `q_ahead` is the displayed size
   at `p` on its own bid array (YES legs read `yes_bids`, NO legs read `no_bids`), taken from the last public 88a
   book the replay holds at placement.
2. **Eligible prints.** Prints are judged on the YES axis, exactly as in v2. A print is eligible if it is at price
   or strictly through.
3. **Fills.** Each eligible print first consumes the queue, then fills the leg. In the engine, prints are taken in
   capture order and the first fill ends the placement (v2 behaviour). A replacement re-enters at the back of the
   queue.

Any change to this rule is a new version, and a signed registration binds exactly one version.

## 4. Known limits (disclosed before any read)

- **Through prints do not sweep the level.** A strictly-through print depletes the queue like any other print.
  The alternative reading, where a through print clears the whole level including us, is not implemented. Under
  v3 that alternative would give more fills.
- **Within-minute order.** In the pure rule, the size of the first fill is invariant to print order within a
  minute. In the engine it can depend on that order. Whether a fill happens, and the minute it happens in, do not.
- **Hidden and cancelled depth.** `q_ahead` sees only displayed size. Cancellations ahead of us are not modelled,
  so v3 is conservative about them.
- **Uncovered prints.** Prints the v2 kernel does not evaluate (outside coverage, before placement or outside the
  active interval) do not deplete the queue. This is also conservative.

## 5. Data and embargo (enforced in code, `fill_v3_embargo`)

- **Reserved window** 2026-09-30..2026-10-15: refused for every purpose.
- **Shadow/panel embargo** through 2026-11-13: refused for scored reads.
- **Scored dates.** To be named at signing. Candidate: post-embargo capture days, with the LFC panel exclusions
  applied before any outcome read.

## 6. To be fixed at signing (open)

- The scored statistic, its decision rule, and whether v3 runs beside or instead of the v2 bounds.
- Which version is bound (default `fill-v3.0`).
- The day set, the policy set and the hurdle reuse, which follow replay v2's signed terms unless stated otherwise.

## 7. Signature

Unsigned. No owner decision has been recorded.
