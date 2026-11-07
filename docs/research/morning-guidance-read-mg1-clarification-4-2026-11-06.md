# MG-1 pre-registration — Clarification 4 (2026-11-06): outcome-blind countability

Status: **owner-approved amendment**, before the single look. This separate dated file amends
[the signed pre-registration](morning-guidance-read-mg1-preregistration-2026-10-04.md) and
[Clarifications 1](morning-guidance-read-mg1-clarification-1-2026-10-16.md),
[2](morning-guidance-read-mg1-clarification-2-2026-11-03.md) and
[3](morning-guidance-read-mg1-clarification-3-2026-11-04.md) only as specified below. Their bytes stay frozen.

## Source and blindness

Owner in the master chat, **2026-11-06 approximately 18:53 America/Toronto (EST)**, verbatim:
“yes approved no manual trade approve 2 and 3”. Item 3 was master's recommendation, verbatim:
“change MG-1 now — before anyone has looked at its results — so days are chosen without reference to the
outcome (the rule B already uses). The old rule would still be reported alongside, but it wouldn't decide anything.”
The source is the master's T020 dispatch of 2026-11-06 18:54, relaying that owner decision.

No MG-1 result has been looked at, as attested in that dispatch. **No protected flag, count or label was opened
to write this amendment** or implement it. No ledger row, countability list, label manifest, snapshot, outcome
or price for event dates on or after 2026-10-15 was read. The diagnosis and verification use code, documentation
and deterministic synthetic fixtures only; nothing under `data/` or the sealed panel store was opened.

## 1. Defect and new primary mask

T013 finding 5, confirmed by T016 section 5, traces `promotion_countable` through
`settlement_ledger.promotion_countability` and `reconcile_with_polymarket` to `mg1_countable.market_day_flags`
and `mg1_look.read_inputs`. The flag requires WU's bucket to fall in the venue winner's band. Changing only
that winning band can therefore remove an equally covered market-day before scoring, and can remove a date
when no other support market-day survives. Reading venue-rule labels later does not repair that selection.

**Primary rule:** a market-day is countable if and only if (1) its material coverage grade is in
`MATERIAL_COUNTABLE_COVERAGE_GRADES`, (2) its event is closed with exactly one venue winner, and (3) its
venue-label date key exists in the look-morning frozen manifest's `label_dates`. Winner existence and
cardinality are used, never the winning band or its agreement with WU. WU/venue reconciliation is not a condition.
A missing ledger row is pending; multiple event slugs for one market-day are non-countable. The latest revision for
the unique event supplies coverage and closed/winner metadata. Missing label keys make the market-day
non-countable; missing or inconsistent metadata refuses or holds before the look rather than guessing a mask.

These are exactly [B-1 Clarification 8 §1, lines 6–11](b1-clarification-8-countability-look-safety-2026-11-05.md)'s
three market-day conditions. The sole population difference is the existing date aggregation: **MG-1 needs at
least one qualifying support market-day; B needs all ten.** MG-1 keeps its previously ruled date aggregation
and Clarification 3's support (Denver out); there is no reason to import B's different estimand or stopping rule.

## 2. Dates, MG1_LAST and the single look

From fixed D0 = 2026-10-15, inspect calendar dates in order without discretionary skipping. A local date counts
iff at least one support market-day satisfies §1. Count the **first 45 such dates** and score only qualifying
market-days within those dates. Pending counts as non-countable in the final list. Do not substitute a date
because of reconciliation, an outcome, a price, a score or the sensitivity's coverage.

`MG1_LAST` remains **provisionally 2026-11-28**, the earliest possible 45th date. It may only move later,
never earlier. Each intervening non-countable or pending date pushes the earliest possible 45th date one day
later. Master records any necessary extension before a date beyond the recorded last is scored, enumerated
or joined. This amendment neither inspects dates nor claims that an extension is needed.

The look timing stays **on or after 2026-11-30**, in the first admitted morning at least two local calendar
days after the actual 45th countable date, with the recorded window closed, all scored markets final and the
R24 freeze present. The final mask is made from that freeze's keys and the frozen latest ledger revisions;
the list binds the freeze receipt SHA-256 and includes separate old-mask flags from those same ledger bytes.
P1/P2 reports require frozen key metadata too. They may use separately named, immutable R24 preview freezes
(`mg1-countability-*` look IDs), never the old mask as a proxy. Reports stop at the preview's `through` and
read no label values or old flags. Create fresh preview IDs as needed until readiness; only then create the
single `mg1` look freeze, so an insufficient preview cannot strand the final freeze. Absent metadata, refuse.
P3 requires that exact `mg1` freeze and fixes the final list before any label value is read. A true primary flag
without a matching frozen key or layout row still holds the look, unconsumed (stale/inconsistent inputs).

## 3. Frozen NONDECIDING sensitivity

Keep the former ledger `promotion_countable` mask **only** for a sensitivity at the same single look, on the
same frozen inputs, intersected with the primary's qualifying market-days and first 45 dates. It selects no
replacement dates, never extends `MG1_LAST`, and opens no additional label or price. Recompute the 00–16
MG-1-minus-served contrast with the existing equal-cell weighting and fixed-date/crossed bootstrap seeds;
report included and excluded market-days, dates represented, point estimate and intervals. There is no
sensitivity PASS/FAIL, materiality test or alternate verdict. An empty subset is reported as unavailable;
a sensitivity exception is reported as an error after the primary has been computed and cannot lose its receipt.

**Fixed reporting wording (literal):**

> NONDECIDING sensitivity: old promotion_countable mask within the primary's first 45 countable dates, on the same frozen inputs at the same single look. Outcome-selected subset; cannot change the primary verdict, dates, MG1_LAST, pass rule, falsifiers or VOID conditions.

Every sensitivity report carries that wording, including unavailable/error reports. Only the primary mask's
result enters the verdict, pass rule, falsifiers and VOID conditions. No combination of sensitivity estimates,
signs, intervals, coverage or errors can change them.

## 4. Supersession and binding

Line numbers below refer to the unchanged earlier files at task base `22b3dd835`:

- Clarification 1 **line 21**: “From D0 the evaluation counts each promotion-countable date” — replace only the
  mask meaning with §1. **Line 25**: “window proves not promotion-countable” — apply the new mask;
  **lines 23–26** retain provisional LAST and extension mechanics.
- Clarification 2 **line 36**, R11 (1): “has the ledger's promotion_countable true; §4 scores only countable
  market-days.” Superseded by §1, retaining the at-least-one date rule and primary-only pre-join mask.
- Clarification 2 **line 74**, A3: “D counts iff at least one support market-day is promotion_countable.”
  Superseded by §1. Its **line 86** schema reference and **lines 104–105** scored-population reference now mean
  `mg1_countable/2`, with `countable` and primary `markets` flags plus separate `sensitivity_markets` flags.
- Clarification 2 **lines 52–57**'s P0/P1/P2 promotion-based counts and extension schedule are superseded only
  insofar as §2 now requires the new mask and frozen key metadata. P3's single-look timing is unchanged.
- Clarification 3 **line 31**: “every A, T and R11 ruling in Clarification 2” remains in force except for the
  countability rulings explicitly replaced here. Its A1, A5 and A12 answers are unchanged.

The signed pre-registration's promotion-mask population language (§3(e), §4) is amended to §1, not rewritten.
Every other estimand, threshold, falsifier, VOID condition, reporting caveat, label source, owner answer,
reservation scope and one-look constraint stands. B's code path and frozen bindings are unchanged.

The look pins the raw SHA-256 of this document and Clarifications 1–3 before stamping; its receipt records
`clarifications_sha256`, covered by `body_sha256`, and its result binds the countability list and freeze.
The reviewed `mg1_look.py` SHA must be re-registered in `MG1_CONFIRMATION_ENTRY_POINTS` with this implementation.
Master retains ownership of STATE_OF_PLAY, DECISION_LOG, B's later S1 pin and production landing.
