# Atlas readiness: the served-vs-market per-block re-base on the 09-30..10-14 release (draft)

Status: DRAFT, lane L8, 2026-10-31. This is research evidence, not a canonical document. It was written from code
and docs only; no data was read.

- **Scope.** EXHAUSTION_REGISTER §5 orders 1, 2 and 6 (`docs/operations/EXHAUSTION_REGISTER.md:316-345`).
- **Exclusions.** MG-2 is excluded throughout.
- **Sequencing.** Nothing here runs before the row 80 look
  ([row80-look-runbook.md](row80-look-runbook.md)) has written its receipt.

## 1. What the release can and cannot give

- **Post-fix dates.** The release covers local targets up to 10-14, so the post-10-09 dates are **10-10..10-14 only
  (5 dates)**. Target 10-14 may also lose US labels to the tape-sha binding (runbook §1).
- **Markets.** The extract is US °F only, so the layout path covers **US11, not 12 markets**. Toronto needs a
  separate °C extract path, which does not exist on master.
- **Pre-fix dates.** 10-01..10-09 are pre-fix served output. They are useful as a contrast stratum, not as order 1
  evidence.
- **Later dates.** 10-15 and later stay embargoed: MG-1 reserved through 11-28, and in the OUTCOME window.

| Order | Readiness on this release | Why |
| --- | --- | --- |
| 1: served-vs-market per block, post-10-09, crossed and fixed-market intervals | **Descriptive first slice only; cannot close** | It closes at 45 countable dates, and this release gives 5. Under `CLUSTER_FLOOR` 12 every block is `powered: false`. |
| 2: §1f position split under a rank-based disagreement gate (B and C separate), then the tail recomputed on post-10-09 served output | **Not ready** | The §1f split code was not located on master or the harness branch. The tail recompute shares order 1's 5-date limit. |
| 6: one owner-signed prereg on ≥45 post-10-09 dates (114-cell edge map, §1c bound, shrinkage locator) | **Not ready** | The prereg is not drafted. It must state whether 10-10..10-14 count, because any order 1 read on them makes them non-fresh for order 6. |

**Recommendation.** Before any order 1 read, master or the owner should decide one of two options:

- (a) run order 1 as a labelled descriptive slice on 10-10..10-14, and have order 6's prereg exclude those dates;
- (b) hold 10-10..10-14 fresh for order 6, and read only the pre-fix stratum now.

## 2. Why the existing atlas cannot be pointed at the release

`src/weather/reporting/scorecards/loss_atlas.py` is B-bound and read-only until 12-13:

- `RANGE` is hard-coded to 08-01..09-29 (`:89`).
- `run_atlas` calls `check_range(*RANGE)`, `load_layout(DEV_FIRST, end)` and `make_folds`. It then runs
  `positive_control` against `CONTROL_EXPECTED` `{"all": 1.774, "00-16": 1.526}` (`:91`, `:338-357`, `:658-672`).
- `extract_regimes` refuses dates after `DEV_LAST`.

An in-process override of `RANGE` and `DEV_LAST` would make the positive control run on the new dates, where its
expected values do not apply, so it would raise `ControlFailed`. Overriding the control would defeat it. The
rep.py-style in-process override is therefore not enough here. **A new wrapper module is needed.**

## 3. The proposed wrapper module (needs the coordinator's allowlist check)

**`tools/research/released_window/served_market_blocks.py`** does not exist yet. It edits no B-bound file. It
imports `dev_scorecard_data` / `dev_scorecard` and `loss_atlas` read-only, from a clean pinned worktree. It does
only this, in order:

1. **EF §3 floor control.** It runs the dev scorecard control floor unchanged, on dev dates ≤ 09-29: baseline
   `1.6639158425`, hard `1.4979600580`, fixture sha `8ac77c08…`. It refuses on a mismatch.
2. **Atlas positive control.** It runs `loss_atlas.positive_control` on the unchanged dev layout
   `C:\swarm\v3layout`. That layout is read only, never rebuilt. It refuses on `ControlFailed`.
3. **Release scope.** Only after 1 and 2 pass, and only if row 80's `out_rep/look/receipt.json` exists, it sets
   `data.DEV_LAST = date(2026, 10, 14)` in-process. This is the same mechanism as `rep.py:232-235`, and no file is
   edited. It then loads the **release layout** built by `r80_layout.py` (`C:\t\r80\layout`). It refuses any date
   outside 10-01..10-14.
4. **Scoring.** It computes `sc.Table(layout, dates)` and `sc.score_rows(table, table.p_served, True)` per block and
   per market. The blocks are `00-05, 06-09, 10-12, 13-16, 17-23` plus `00-12, 00-16, all`. It reports crossed and
   fixed-market intervals, and `powered` against `CLUSTER_FLOOR`.
5. **Strata.** It reports two strata separately: 10-01..10-09 (pre-fix) and 10-10..10-14 (post-10-09). It never
   pools them into one verdict.
6. **Candidates.** It accepts only `served` and `market` columns. Any MG-2, MG-1 or B candidate is refused by name.
7. **Outputs.** It writes content-addressed outputs and a receipt. The receipt holds the control results, the
   layout manifest sha, the row 80 receipt sha, the dates, the override and the code shas. Its label is
   "descriptive, not countable" unless the order 6 prereg says otherwise.

The `FORBIDDEN_INPUT` pattern `88a|panel` (`loss_atlas.py:100`) still applies to every path it reads.

## 4. What needs a host export

- **The atlas re-base needs nothing beyond row 80's sub-manifest.** It reuses the same release layout. It reads
  no 88a and no order books.
- **Fixed-market intervals use the market column already in the layout.** If master wants book-level market
  prices instead, that is an 88a read, outside this note.
- **Toronto would need a °C extract path**, which is code work on master that is not yet scoped, and Toronto
  files in the export.

## 5. Archive rule

If any order ends in a ruled-out candidate, its prereg, the wrapper sha, the outputs, the receipts and the logs go
to `C:\archive\ruled-out\<row-folder>\` and are never deleted.
