# Workstation handoff — 2026-07-28b: floor gate respecified, then resume `-27g`

Missions 2 and 3 of `workstation-handoff-2026-07-27g-who-breaks-the-floor.md` are unchanged.
Only the Mission 1 gate is respecified, because **the gate was wrong, not the data**.

## The gate bug was mine

I wrote a gate requiring a finite `high_so_far` for every admitted snapshot. That conflates
*undefined* with *invalid*, and it is wrong on its face:

`feature_model.py:966-972` computes `high_so_far = max(temps_before)` over observations at or
before the cutoff. Before the market-day's first observation there is nothing to take a
maximum of, so the quantity is legitimately undefined — not missing, not contaminated.

Your failing snapshot is `20260628T030303-0400`. That timestamp is **capture-host Eastern
time**. The six markets you completed were Atlanta, Austin, Chicago, Dallas, Denver and
Houston, so the failure is on the next market alphabetically — and if that is Los Angeles,
03:03 EDT is **00:03 market-local**, three minutes into its day. A market three minutes old
has no high so far. **Confirm that reading before proceeding**; if the failing market is
*not* a western one, or the market-local hour is not early, then this explanation is wrong
and the null is a real defect that should stop the mission again.

You were right to stop, and right to refuse to narrow the population after seeing the failure.
Do not treat this respecification as permission to drop instants — it defines the undefined
case and *adds* invariants rather than relaxing one.

## The respecified gate

Treat a null `high_so_far` as **"no floor constraint at this instant"** (equivalently, floor at
negative infinity, no band excluded). Then verify all of the following over the complete
admitted population:

1. **Monotone non-decreasing** across non-null values within each market-day, ordered by
   snapshot instant.
2. **Never above settlement** — neither raw `high_so_far` nor `ROUND_HALF_UP(high_so_far)`
   exceeds the frozen settled maximum.
3. **No resurrection of the null** — once a market-day has a non-null `high_so_far`, no later
   snapshot in that market-day may be null again. A value-then-null transition means observed
   information was lost and is a **hard failure**, not a warning.
4. **Nulls confined to the early market-local day** — report the distribution of nulls by
   market-local hour. Nulls before the first observation are expected. A null at a late
   market-local hour (say 12 or beyond) cannot be "no observations yet" and is a **hard
   failure**.
5. Report the null count and share, per market and pooled, so the size of the
   no-constraint population is visible before any projection is scored.

Checks 3 and 4 did not exist in the original gate. They are the checks that would actually
catch forward-looking contamination or observation loss, which is what the gate was for.

If any of 1–4 fails, stop again and report. That is a good outcome, not a failed mission.

## Then resume

With the gate passed, Missions 2 and 3 of `-27g` proceed unchanged: localize where below-floor
mass is introduced given a clean preblend (`0 / 124`) and a violating incumbent (`118 / 124`),
and price the counterfactual floor projection with full decompositions.

One addition, following from the null semantics: when scoring the projection counterfactual,
**exclude no-constraint instants from the projected lane rather than projecting them onto an
imaginary floor**, and report how much of any measured gain comes from constrained instants
only. A gain that survives only because nulls were treated as constraints would be an artifact
of my specification, not a finding.

## Currency answer received, and what it changes here

Confirmed and useful: `-28c` reads `order_books_summary.csv` via `mm_paper_scoring.load_book_rows()`
and has no caller of `iter_full_book_rows`, so tonight's `order_books_long.csv` compression
cannot strand the current scorer. I am proceeding with the apply.

I have noted that the JSONL → `.csv.gz` → CSV boundary exists in the storage rework but is not
wired into `-28c`, so a genuine post-cleanup full-depth run remains **NOT REHEARSED**. I am not
treating it as working. Canonical `order_books.jsonl` is untouched by tonight's apply, so full
depth remains available whenever that path is wired.

## Guardrails

Unchanged from `-27g`. `data/` read-only, single declared output root, no model/blend/serving/
config/release change, topic branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-gate-and-attribution.md`: the failing
market's identity and market-local hour, the five gate results with null distribution, and — if
the gate passes — the Mission 2 attribution and Mission 3 priced counterfactual.

Context: master carries both your reports. Streak 7/14, lock ~2026-08-03. The storage branch
merges here at 01:15 tonight and I apply the cleanup in the same window.
