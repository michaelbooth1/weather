# Rule B-1 clarification: SPECI-inclusive floor vs SPECI-free labels, a disclosure reported at the look, 2026-11-01

- **Status:** a non-deciding disclosure filed after the B-1 binding (2026-10-28). Accepted by master 2026-11-0X
  (date filled at landing). It binds nothing in B-1.
- **Authority:** master's scope ruling of 2026-11-01, relayed by the coordinator: the disclosure is a procedure
  run at B's look, not a number computed before it.
- **History only:** no B forward cell and no outcome, label, price or market row dated after 2026-09-29 was
  read to write this. The only number in this file is dev context from canon (§4).
- **What changes:** nothing in B-1. This file changes no bound file, rule, hash, threshold, date, market,
  interval, estimand, embargo, void condition or keep/kill rule of B-1 or of MG-2. It adds two descriptive
  numbers to what the look reports beside the verdict. It is filed outside
  `docs/research/mg2-composite-binding-2026-10-25/` and does not edit `B_FORWARD_TEST_DESIGN.md`.

## 1. Why

- **Labels are SPECI-free.** B scores against venue-rule labels from 2026-10-23: the highest routine METAR,
  SPECI excluded, tenths °C half-up to °F
  ([B-1 §5](../../operations/B_FORWARD_TEST_DESIGN.md); [AGENT_CONTEXT](../../operations/AGENT_CONTEXT.md)).
- **The floor is SPECI-inclusive.** MG-2's rule-4 hard floor is B = floor(F + 0.5), with F the max of
  `guidance_physical_floor`, `high_so_far` and `trusted_current_max` (`mg_serve_core.floor_B`). Those served
  fields are built from observation rows that keep SPECI and COR reports (AGENT_CONTEXT, `metar-parser-v4`);
  `weather.model.observed_running_max` has no SPECI filter. B's scorer applies the same mask to MG-2's
  vector: a non-`gte` band whose `high` is below floor(F + 0.5) gets probability 0 (`dev_scorecard.Table.impossible`,
  used by `b_scorer.arm`). The market arm is scored unmasked (`b_scorer.excess_rows`).
- **The consequence.** When the floor rises above the routine-only daily max, for example after a SPECI that
  routine reports never reach, MG-2 puts exactly 0 on the band that pays. That cell's loss is certain and
  does not depend on forecast skill. Removing SPECI from the floor (fix 11) is on the after-B list and is not
  applied to MG-2 as bound ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)).
- **Purpose.** If B ends PASS, FAIL or INCONCLUSIVE, the reader can see how much of Δ(07-16) came from cells
  where the floor zeroed the paying band. The disclosure explains the result. It never decides it.

## 2. What the look reports beside the verdict

Both numbers are labelled **descriptive, non-deciding** wherever they are printed.

**Population.** B's own scored table: `b_scorer.build_table` on the surviving dates, `b_scorer.arm` on the bound
gate vectors, and B's `covered` mask, restricted to local hours 07-16. This is exactly the primary population of
B-1 §5, at the look, from the same sha-pinned transfer bytes the scorer consumed.

**Paying band.** In each snapshot, the band with label y = 1 from the transfer's venue-rule `labels.parquet`.

**Zeroed snapshot.** A covered 07-16 snapshot whose paying band has `Table.impossible` true. On such a snapshot
MG-2's scored probability for the paying band is exactly 0.

**(1) Affected-cell count.** The number of B (date, market) cells with at least one zeroed snapshot, out of the
scored cell count. Beside it, one row per affected cell: date, market, covered 07-16 snapshots, zeroed
snapshots, the first zeroed local hour, and the cell's arm-minus-market Brier difference.

**(2) Δ(07-16) without those cells.** B's primary estimand recomputed by `b_scorer.excess_rows` logic with every
snapshot of every affected cell removed from both arms: equal snapshots within a cell, then equal cells, and
the same date-clustered percentile interval (`Table.w_date`, 2,000 draws, seed 20260921) restricted to the
remaining cells. Reported: Δ, [L, U], the cell count and the date count, next to B's own Δ(07-16) and [L, U].
If no cell is affected, (2) equals B's primary row and is printed as such.

## 3. How it runs and what it cannot do

- **When.** In the look session, after `b_scorer look` has written its receipt with a scored verdict (PASS,
  FAIL or INCONCLUSIVE). It is not run after a VOID or an ABORTED look.
- **Inputs.** It reads no byte B did not: the transfer files verified against B's recorded manifest hash, the
  bound vectors and B's recorded look dates and drop list. It imports B's modules read-only and edits no
  B-bound file. Its output is written once, with mode "x", beside B's look output with its own receipt.
- **Code.** The implementing module is pinned by sha in a master-reviewed record before the look. If no pinned
  implementation exists at the look, the disclosure is reported as NOT COMPUTED, and nothing about B changes.
- **No effect on B.** Neither number changes, rescues, re-labels or qualifies B's verdict, its NOT-WORSE label
  or any VOID. (2) is a re-cut of cells, which B-1 §6 forbids as a basis for the verdict. It is never pooled
  with MG-2's gate, the paper test, PT-1 or any later look. No successor may be selected on it.
- **Not reported.** No per-cell attribution of a zeroed snapshot to a SPECI rather than another floor cause
  (for example a `trusted_current_max` or `guidance_physical_floor` value above the routine max). The count is
  every case where the SPECI-inclusive floor, as bound, zeroed the paying band.

## 4. Expected frequency (dev context only)

- **Measured on dev.** Dropping SPECIs changes the 2 °F label band on 9 of 671 US station-days (1.3%; IEM METAR,
  2026-07-31..09-29, all 11 US markets including Denver)
  ([ESTABLISHED_FINDINGS §10x](../../operations/ESTABLISHED_FINDINGS.md); digest line under settlement).
- **What it implies, as arithmetic only.** On about 450 B cells, 1.3% is about 6 cells. A SPECI-driven zeroed
  cell also needs the SPECI to reach the floor at or before a 07-16 snapshot, which lowers that figure. Other
  floor causes can raise the count in §2. This is context, not a prediction or a threshold. No count, Δ or
  interval in §2 is tested against it.
- **Not used.** No B forward cell, no label after 2026-10-15 and no captured input dated after 2026-09-29 was
  read for this section.
