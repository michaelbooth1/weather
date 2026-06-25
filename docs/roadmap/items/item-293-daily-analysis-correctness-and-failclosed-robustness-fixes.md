# 293. Daily-Analysis Correctness And Fail-Closed Robustness Fixes [COMPLETE 2026-06-24 - FAIL-CLOSED PROMOTION AND STABLE DAILY LEDGERS]

Goal: fix the discrete correctness and fail-open defects in the daily analysis
pipeline (`daily_learning`, `daily_progress_ledger`, `daily_flow_analysis`) so a
single missing field or schema change cannot silently corrupt a promotion
decision or drop the highest-priority learning.

Source: 2026-06-24 audit of the daily analysis script. Concrete defects found in
the code:

1. `daily_learning._retrain_plan` marks `promotion_ready=True` when
   `candidate.delta_vs_current is None` (improvement unmeasured) as long as rows
   exist (`src/weather/reporting/daily/daily_learning.py:1289`), and it gates only
   on beating the current model, never on `delta_vs_market`.
2. `daily_progress_ledger.append_csv` writes with
   `fieldnames=ledger_columns(row)` and `extrasaction="ignore"`
   (`src/weather/reporting/daily/daily_progress_ledger.py:518`), so any schema
   change rewrites the entire CSV to the newest row's columns, silently dropping
   removed columns from all history and blank-filling older rows.
3. `daily_learning` truncates several upstream lists before sorting by
   importance: `recommendations[:8]`, `gap_owner_table[:8]`,
   `remediation_manifest[:8]`, `registry.rows[:12]`
   (`daily_learning.py:444,424,466,879`), so an unsorted source can drop a real
   P0 while keeping a P2, with no dropped-count signal.
4. Numeric `x or y` fallbacks treat a legitimate `0` as missing, for example
   `safe_int(aggregate.get("rows") or aggregate.get("n"))`
   (`daily_learning.py:273`).
5. `_add_gate_learnings` (`daily_learning.py:385`) only treats
   `status=="FAIL" and severity=="fail"` as P0/blocker, relying on an unenforced
   upstream invariant; a future `FAIL` with a non-`fail` severity would be
   silently demoted to a P2 non-blocker. `maybe_int` also truncates in the ledger
   but rounds in flow analysis.

Why this matters: these modules drive retrain/promotion readiness and the
operator action queue. A fail-open promotion flag, a silently mutated history
file, or a dropped P0 learning all directly degrade the trustworthiness of the
daily decision without any visible error.

Why it is not already covered: items 199 and 205 hardened daily-refresh rollup
locks and the orchestration facade, and item 163 owns the broad-claim ledger
fields, but none address these specific aggregation/fail-open defects inside the
daily analysis modules. The ledger dead-load and missing trend analysis are
owned separately by item 295; this item is scoped to the discrete correctness
fixes.

## Design

1. Require a measured, non-`None` `delta_vs_current <= 0` for `promotion_ready`,
   and add an explicit `beats_market` field (from `delta_vs_market`) so the
   distinction between "beats current model" and "beats market" is visible in
   the retrain plan.
2. Make the CSV ledger schema-stable: write the union of historical and current
   columns (or treat JSONL as canonical and regenerate the CSV from the full
   JSONL each run) so no historical column is silently dropped.
3. Sort `recommendations`, `gap_owner_table`, `remediation_manifest`, and the
   remediation registry by `(priority, impact)` before truncating, and emit a
   `dropped_count` per source when the cap is hit.
4. Replace numeric `x or y` fallbacks with explicit `None` checks so a real `0`
   is preserved.
5. Treat any gate `status=="FAIL"` as at least P1/blocker regardless of
   severity, and unify integer coercion (`round` vs truncate) across the daily
   modules.

- [x] Make `promotion_ready` require a measured improvement and expose a
  `beats_market` field.
- [x] Make the CSV ledger schema-stable with no silent column loss across schema
  changes.
- [x] Sort-before-truncate with a `dropped_count` for each capped source list.
- [x] Remove numeric `x or y` zero-as-missing fallbacks in the daily modules.
- [x] Treat any `FAIL` gate as a blocker and unify int coercion; add regression
  tests for each fixed defect.

Acceptance: `promotion_ready` cannot be true without a measured non-positive
`delta_vs_current`; the CSV ledger never loses a historical column across a
schema change; capped source lists are sorted by priority/impact before
truncation and report a dropped count; legitimate `0` values are preserved; any
`FAIL` gate is a blocker; and tests cover each defect with the shapes that
triggered them.

Related: items 36, 37, 163, 199, 205, 295.

## Completion Note - 2026-06-24

Implemented the scoped correctness fixes in `weather.reporting.daily`:
`promotion_ready` now requires measured `delta_vs_current <= 0` and exposes
`beats_current_model`, `beats_market`, measured-delta flags, and failed readiness
checks; the candidate row count preserves legitimate `0` values; snapshot
evaluation `FAIL` gates are P0 blockers regardless of severity; capped learning
sources are sorted before truncation and report `dropped_count`; daily progress
CSV writes preserve the union of historical and current columns; and ledger
integer coercion now matches flow-analysis rounding.

Verification: `python -m pytest tests/reporting/test_daily_learning.py
tests/reporting/test_daily_progress_ledger.py
tests/reporting/test_daily_flow_analysis.py -q` covers the missing-improvement
fail-closed path, zero-preserving row counts, FAIL gate handling, sort before
truncate, schema-stable CSV append, and integer rounding consistency.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - FAIL-CLOSED PROMOTION AND STABLE DAILY LEDGERS`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

