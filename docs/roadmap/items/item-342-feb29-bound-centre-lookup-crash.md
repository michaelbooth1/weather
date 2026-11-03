# 342. Feb-29 Crash In The Bound P3d_N Centre Lookup And Serve Math [OPEN 2026-11-03 - MASTER ACCEPTED; FIX AFTER THE B LOOK, BEFORE 2028-02-29]

Goal: make the five bound `date(2001, month, day)` centre lookups total on Feb 29, without changing any output on
any other date, and make the related leap-year handling explicit and checked. The five lookups are
`nearest_centre` and `state_features` in `pooled_residual_model.py` and `mg_serve_core.py`, plus
`nearest_centre` in `mg2_p3d_n.py`.

Owner/package: `weather.calibration` and `weather.model` (`pooled_residual_model.py`, `mg_serve_core.py`,
`mg2_p3d_n.py`, all B-bound); C1 `weather.operations.base_retrain` and `weather.sources.forecast_history`;
C2 `weather.sources.reanalysis_synoptic`. Workstation research for the trace; master for landing and the rebind.

Source:
- Row 28 scoping (workstation lane L59, 2026-11-02) found the crash.
- Master accepted the item. Master's terms: no edit before the B look (12-13); the fix lands before 2028-02-29
  with a train/serve parity check; before B, a crash fails closed (loud, not silent).
- Master confirmed the five sites on the host at `df6e52df0` and ruled the scope (C1-C3, the fix design and the
  P2/P5 routing) on 2026-11-03. Both were relayed by the coordinator.
- Trace by lane L56 (drafts below).

Why this matters: each of the five sites raises `ValueError` on any Feb 29 that reaches it. None is reachable
before B, and a crash there is loud. But a bound state served on 2028-02-29, or a year-round refit through
`forward_fit`, would stop. The fix changes three B-bound files' shas, so it needs a release rebind and must not land
before the B look.

Checklist:

- [ ] P2 (copy parity on 2024 and 2028, Feb 29 excluded) and P5 (pin today's `ValueError` on 2028-02-29) land through
  the L58 tests-only lane into combo C. Zero edits to B-bound files or `KNOWN_COPIES`; host `Test-BBoundHead`
  PASS on the tip.
- [ ] After the B look (12-13): the shared helper (Feb 29 -> Feb 28, 2001 reference kept) at all five sites, with
  P1, P3 and P4 passing, P5 replaced by P4, and the release rebind and `KNOWN_COPIES` update in the same change.
- [ ] C1: the base retrain and forecast-history Feb-29 target remap logs a count of remapped targets.
- [ ] C2: stays open. If a named path's allowlist selects a reanalysis-synoptic column, re-trace it and measure the
  size. The measurement is restricted to dev dates <= 2026-09-29 and reports counts, statistics and sha256s only.
- [ ] Before 2028-02-29: confirm the fix is on master, or that no state carrying these sites is served on that date.

Acceptance:
- All five sites return the Feb-28 centre on Feb 29.
- P1 shows zero differences on every non-Feb-29 date 2021-2028 for every bound centre set.
- P2 and P3 pass; the frozen-state vectors are byte-identical.
- P4 covers one train-path and one serve-path Feb-29 case.
- C1's count appears in its receipt.
- C3's linear behaviour is unchanged (any wrap change is a separate candidate).
- The rebind is recorded.

Evidence pointers (machine-local, evidence references only):
- the drafts `C:\t\docs-head-next\feb29_item_draft.md` (sha256
  `2c611f54bbcdac040eabd8078411b3656387b9611596a11a500da23c30e879a3`) and `feb29_item_draft_v2.md` (sha256
  `8f8f11baea1700426f3f68b2e36bb4205f63efb76dcceb9d02fcbf25ca448ec7`, the source of the findings below);
- the scripts and corpus hashes in Section 7.

Findings (trace at `df6e52df0`; Sections 1-7 are taken from draft v2):

### 1. Call sites

All five sites build a non-leap reference date, `date(2001, month, day)`. For month 2, day 29 this raises
`ValueError: day is out of range for month`. The same pattern exists in three files.

| File:line | Function | Failing expression | Exception |
| --- | --- | --- | --- |
| `src/weather/calibration/pooled_residual_model.py:940` (def :937) | `nearest_centre` | `ref = date(2001, d.month, d.day)` | `ValueError` |
| `src/weather/calibration/pooled_residual_model.py:1496-1497` (def :1491) | `state_features` | `date(2001, target_date.month, target_date.day)` inside the `min(state["centres"], key=...)` lambda | `ValueError` |
| `src/weather/model/mg_serve_core.py:447` (def :444) | `nearest_centre` (copy of prm) | `ref = date(2001, d.month, d.day)` | `ValueError` |
| `src/weather/model/mg_serve_core.py:536-537` (def :531) | `state_features` (copy of prm) | `date(2001, target_date.month, target_date.day)` | `ValueError` |
| `src/weather/calibration/mg2_p3d_n.py:204` (def :201) | `nearest_centre` (third copy; called by `serve_distribution` at :287) | `ref = date(2001, d.month, d.day)` | `ValueError` |

Three things are not affected:
- The centre side of each lambda (`date(2001, int(c[5:7]), int(c[8:10]))`) cannot fail. No bound centre is a
  Feb 29 (`AUG_SEP_CENTRES` prm:96 and core:55; `OCT_DEC_CENTRES` prm:91; `JAN_JUL_CENTRES` prm:92-95;
  `FORWARD_CENTRES` prm:1258; `GOLDEN_CENTRES` mg2_p3d_n:658).
- The day-of-year features (`tm_yday`, prm:1507, core:547, mg2_p3d_n:286, prm:432) do not fail on Feb 29.
  Train and serve use the same formula, so parity holds.
- All five sites are in B-bound files: `pooled_residual_model.py`, `mg_serve_core.py` and `mg2_p3d_n.py` are
  on the LANE_RULES list.

### 2. Today's reachability (why nothing has crashed)

- **MG-2 composite forward path.** `mg2_p3d_n.emit_rows` (:416) applies the rule §8 C5 coverage gate before
  `serve_distribution` (:499). The gate is `in_training_coverage` (:321-323), with
  `TRAINING_COVERAGE = ("08-01", "12-16")` (:318). A Feb-29 row never reaches :204. It is routed to the MG-1
  fallback, counted in `outside_training_coverage` and logged per row in `coverage_fallback` (:469-472). The
  composite writes it to `mg2_post_coverage_fallback.jsonl` (mg2_composite.py:1061-1065).
  - This is by rule and logged, so it is not the silent defect shape.
  - The MG-1 side on a Feb 29 was not traced: no Feb-29-specific construct was found by grep in the MG-1 code
    path.
- **prm dev scoring.** `nearest_centre(key[0])` at prm:1035 and prm:1226 runs only on dev rows (Aug-Sep;
  `N_DEV_FIRST/LAST` prm:1068-1069). Not reachable on a Feb 29.
- **prm forward export parity.** `state_features` at prm:1616 runs on forward training rows, centres
  Aug-Dec (prm:1258). Not reachable now. A future year-round refit through `forward_fit` (prm:1533) with
  Jan-Jul centres **would crash loudly** at :1616 on any 2024-02-29 row.
- **`mg_serve_core.state_distribution` / `state_features`** (core:531, :560). At df6e52df0 the only callers are
  the module itself and tests (`tests/model/test_mg_serve_core_state_parity.py:100-102`). Any direct serve on a
  Feb 29 would raise `ValueError`.
- **Fail-closed check.** No broad handler swallows the error on these paths:
  - `mg2_composite` catches only `mg2_p3d_n.P3dNRefused` (mg2_composite.py:324, :1036, :1051, :1070).
  - The `except ValueError` handlers near these paths parse `cutoff_hour` or ISO timestamps only (mg2_p3d_n:458-461,
    prm:1016-1019, r0_ols_floor_challenger:754-757, r0_ols_floor_devfit:84-88, mg_serve_core:323-327).
  - So a Feb-29 `ValueError` propagates and aborts the run: loud, as master requires.
- **Test gap.** `tests/model/test_mg_serve_core_parity.py:239-244` checks core == prm `nearest_centre` over 2026
  only (a non-leap year, every 5th day). No test exercises Feb 29.

### 3. Scope: bound or frozen runs and 2024-02-29

Key: (a) the run would crash; (b) a try/except, filter or calendar construction silently drops or alters the date;
(c) the date is not in the run's window. "Included, handled" means 2024-02-29 is in the window and is processed
with no crash and no drop.

| Run (name only) | Window | 2024-02-29 | Basis |
| --- | --- | --- | --- |
| B / MG-2 forward test (Rule B-1) | D0 2026-10-29..12-12 | (c) | forward 2026 dates; the coverage gate would route a Feb 29 to MG-1 (above) |
| MG-1 forward shadow | 2026 forward | (c) | — |
| P3d_N forward state (`forward_fit`) | Aug-Dec 2021-25 (`FORWARD_CENTRES`, `FORWARD_YEARS` prm:1258-1259) | (c) | train rows are Aug-Dec only; prm:1554 refuses other years |
| P3d_N dev fit / L2 dev scoring | Aug-Sep 2021-25 train, dev 2026-07-30..09-29 | (c) | prm:96, :1068-1069 |
| L2 pooled arms P0-P3, U0 | centres Aug-Dec | (c) | prm:104-114 |
| **L2 pooled arm P3F** (amendment 4, "L1's full-year corpus") | centres incl. `2026-02-22`, years 2021-25 where covered | **included, handled** | `window_days("2026-02-22", 2024)` (prm:181-186) is calendar arithmetic and yields 02-15..02-29; the trainer window uses leap reference year 2000; scoring is dev-only (no `nearest_centre` on a Feb 29) |
| **L1 R0 full-year retrain** (register X1) | full-year union, 2021-25 | **included, handled** | `dates_in_years` (r0_full_year.py:109-116) enumerates Feb 29; `in_window` (:98-101) uses year 2000, so it is leap-safe; the full-year arm trains on all rows (:314-316) |
| PIT forecast corpus, 12 built-ins, 2024 Jan-Jul (`ece9d1c2…`) | 2024-01-21..07-31 | **included, handled** | coverage rows 02-28 / 02-29 / 03-01 = 168 / 168 / 168, all `complete` (12 markets x 14 cutoffs) |
| PIT forecast corpus, 2024, denver-kden/london/madrid/munich/paris (`0850df30…`) | 2024-01-22..12-31 | **included, handled** | 70 / 70 / 70, all `complete` |
| PIT forecast corpus, 2024, seoul/shanghai/tokyo (`bd132674…`) | 2024-01-22..12-31 | **included, handled** | 42 / 42 / 42, all `complete` |
| PIT corpus Aug-Sep 2021-25 (`b455bd53…`) and the other 2021-23 / 2025 corpora | — | (c) | target ranges exclude 2024-02-29 (Section 5) |
| New-city training corpora (`06654742…`, `d519ab1d…`, `f8eaae6b…`) | to 2025-12-31; lineage incl. `0850df30…` / `bd132674…` | included by lineage; **row counts not checked** | builder `new_city_corpus.py` uses calendar arithmetic only (:71-93); per-date counts would need the data files, which were not opened |
| Production base retrain (`base_retrain`, years 2021-25, ±7 d; base_retrain.py:80-82) | per target | included for targets within 7 d of Feb 29; handled | anchor ± `timedelta` (:205-210); Feb-29 target remap is check sub-item C1 |
| L5 arm B full-year GFS day-1 linear (register X9) | full year | **not traced** | name only |
| R-P / R-P2 station pooling (rows 108/109) | LOYO 2021-25 Aug-Sep | (c) | — |
| Row 106 market reliability | dev 2026-08-01..09-29 | (c) | — |
| Row 113 history-tier reliability | 2025-12..2026-05 | (c) | 2025 and 2026 are not leap years |
| L52 price history | events 2025-01-22..2026-09-29 | (c) | — |
| X36-v5 (row 111) | 2026 Jan-May | (c) | — |
| K112 history tier | Dec-May | NOT RUN | a 2024 run would include the date; its code path was not traced |
| Sealed pre-boundary panel | 2026-05-27..07-30 | (c) | name only; not opened |
| PT-1, F8-MH, row 72, T+1, L6_G forward | 2026-27 forward | (c) | next Feb 29 is 2028 |

**No case (b) found on the bound P3d_N / MG-2 path.** Before B, any Feb-29 reach of the five sites is case (a),
which is loud. The coverage gate's fallback is rule-defined and logged per row.

#### Leap-year construct that needs no action

- `model_climatology.py:113-125` and `wu_history.py:956-965` use the leap reference year 2000.
- `model_climatology.py:259-263` has an `except ValueError -> date(2000, 2, 28)` that can never fire, because
  2000 is a leap year.
- `r0_full_year.py:100-101` and `tools/research/project_high.py:56` are also leap-safe.

### 4. Check sub-items (in scope by master's ruling, 2026-11-03)

#### C1. Feb-29 target silently remapped to Feb 28 (production base retrain and forecast history)

- **Code.** `base_retrain.py:198-204` and `forecast_history.py:188-195` catch the `ValueError` from
  `target.replace(year=...)`.
  - For a Feb-29 target in a non-leap training year, they use Feb 28.
  - Any other `ValueError` is re-raised.
  - Nothing is logged.
- **Effect.** Only the anchor for a Feb-29 target moves. No 2024-02-29 input row is dropped.
- **Not a bound-model defect** for B or MG-1. Next exercised on target 2028-02-29.
- **Fix requirement.** The remap stays explicit and becomes visible: the run logs a count of remapped targets,
  with the target date and years, in its receipt or run summary.

#### C2. reanalysis_synoptic day-of-year climatology: NOT CONFIRMED on the prm:240 trainer path (traced)

**What the code does.** It keys its climatology by `tm_yday`:
- `_doy_window` at `reanalysis_synoptic.py:256-259` (radius 15, `max_doy = 366`);
- `_normal_by_doy` at :262-269 and `_raw_metric_by_doy` at :295-302.

In a leap year every date after Feb 28 has a day-of-year one higher than the same month-day in other years.

**Trace of one date, file:line by file:line.** The date is target 2024-03-15, prior-day features.

1. **Feature build.** `build_reanalysis_synoptic_rows` (`reanalysis_synoptic.py:1048`):
   - the loop at :1076 reaches `local_date = 2024-03-15`;
   - :1077 sets `antecedent_date = 2024-03-14`;
   - :1108-1112 compute `features["reanalysis_prev_day_heat_anomaly"] = _heat_anomaly([2024-03-14], ...)`.
2. **Climatology.**
   - `_heat_anomaly` (:279-292) calls `_normal_max(2024-03-14, grouped_by_doy)` (:285).
   - `_normal_max` (:272-276) uses `_doy_window(2024-03-14)`: `tm_yday = 74`, so day-of-year 59..89.
   - It averages `grouped_by_doy` (built at :1064 by `_normal_by_doy`) over years other than 2024 (:275).
   - In 2021, 2022, 2023 and 2025, day-of-year 59..89 is **02-28..03-30**, but the month-day window around 03-14 is
     **02-27..03-29**. The window is offset by one day: it gains 03-30 and loses 02-27.
     This is calendar arithmetic, computed by `feb29_wrap.py` with no data read.
   - `soil_dryness_features` (:327-345, via `_seasonal_raw_values` :305-313) has the same offset.
3. **Storage and load.**
   - The feature row is written to `features/reanalysis_synoptic_features.csv` (`default_feature_path`, :222-224).
   - It is loaded by `load_reanalysis_synoptic_features` (:1176-1194) into an index keyed by `local_date`.
4. **Trainer extraction.** `pooled_residual_model.py:240` passes
   `reanalysis_synoptic_index=fm.load_reanalysis_synoptic_features(spec=spec)` into
   `fm.build_feature_records_for_model` (`feature_model.py:952`).
   - :995 passes `reanalysis_synoptic_index.get("2024-03-15")` to `build_historical_feature_record`.
   - That merges it into the record dict (`feature_store.py:1417-1419`). **The value reaches the record.**
5. **Trainer row.** `pooled_frame` (`pooled_residual_model.py:408`) keeps only
   `common = plan["numeric_feature_names"]` (:415-416) and copies only those columns, as `x_<column>` (:435-436).
   - The plan is `resolve_column_allowlist(f"r0:{market}", ...)` (:224-227).
   - It is built from the served feature list (`feature_column_allowlist.py:126-160` R0 mode, `:88-123`
     `served_feature_names`, `:206-261` `column_allowlist_plan`).
   - At df6e52df0 the served lists contain **no** reanalysis, soil or anomaly column: 24-29 feature names across
     all 12 `artifacts/models/coefs/feature_model_coefs*.json`.
   - **So the value never becomes a trainer-row column on this path.**
   - The bound P3d_N fit also keeps only `x_high_so_far` and `x_current_temp` (`DEV_KEEP_X`, prm:934).
6. **R0 full-year** passes `reanalysis_synoptic_index={}` (`r0_full_year.py:429`), so the feature is never loaded.

**Verdict.**
- The offset is real in the stored feature value.
- It is **NOT CONFIRMED** as reaching any trainer row of a bound or frozen run through prm:240.
- Master's size measurement was conditional on confirmation, so it was **not run**.
- It stays OPEN for any path whose allowlist selects a `REANALYSIS_SYNOPTIC_FEATURE_COLUMNS` column. These columns
  are in `FEATURE_COLUMNS`, `feature_store.py:268-293`, so such a path is possible. One example is a gated-family
  pooled validation.
- If such a path is named, the measurement is:
  - the max and median absolute difference between the day-of-year-keyed and month-day-keyed normal;
  - over target dates up to 2026-09-29 only;
  - reporting counts, summary statistics and input sha256s only.
- No bound model or frozen run is changed.

**Parity consequence.** If the fix later re-keys this climatology by month-day, that is a feature-value change.
It needs its own train/serve parity check: the same stored CSV row is served and trained. It is not part of the
Feb-29 crash fix.

#### C3. nearest_centre measures distance in a straight line within 2001, with no wrap at year end

**Check.** For every month-day of 2001 (365 days), I compared the bound linear choice
(`min(centres, key=abs((c - ref).days))`) with a circular choice (distance `min(x, 365 - x)`). Both use
`min()`'s first-in-tuple tie-break, so a tie counts as a difference only when the two tie-breaks pick different
centres. Calendar arithmetic only.

**Result.**

| Bound centre set | Differing month-days | Range | Example (linear vs circular) |
| --- | --- | --- | --- |
| `AUG_SEP` (prm:96, core:55) = `GOLDEN` (mg2_p3d_n:658) | 59 | 01-01..02-28 | 01-01: 08-08 vs 09-22 |
| `OCT_DEC` (prm:91; arm P2) | 137 | 01-01..05-17 | 01-01: 10-10 vs 12-24 |
| `JAN_JUL` (prm:92-95) | 78 (note a) | 10-15..12-31 | 12-31: 07-22 vs 01-08 |
| P3 = `OCT_DEC + AUG_SEP` (prm:108) | 106 | 01-01..04-16 | 01-01: 08-08 vs 12-24 |
| P3F = `JAN_JUL + AUG_SEP + OCT_DEC` (prm:115) | 0 | — | — |
| `FORWARD_CENTRES` (prm:1258; forward state prm:1573) | 98 | 01-01..04-08 | 01-01: 08-08 vs 12-09 |
| `VALIDATION_CENTRE` (prm:90; P0/P1/U0) | 0 | — | — |

Note a (master accepted):78 counts the 10-15 circular tie (01-08 and 07-22 are both 85 days away); an independent count that does not treat a tie as a difference when the linear pick is one of the tied centres gives 77.

**Reachability today.** None of these month-days reaches a bound call:
- Dev scoring uses `AUG_SEP` on Aug-Sep rows only (prm:1035, :1226).
- The MG-2 forward path is gated to 08-01..12-16 (mg2_p3d_n:318-323), and every differing range for `FORWARD`
  and `AUG_SEP` lies in Jan-May.
- P2, P3 and P3F training take the centre from the extraction payload, not from `nearest_centre` (prm:426).

**Disposition.** Recorded only. The Feb-29 fix stays bit-identical on non-Feb-29 dates, so any wrap change would
be its own later candidate, not part of this fix.

### 5. Fix design (master-confirmed)

- **One shared helper** for all five sites:
  `_ref_2001(month, day) = date(2001, month, 28 if (month, day) == (2, 29) else day)`. Feb 29 takes Feb 28's
  centre.
  - The 2001 reference is kept; no leap reference year is used.
  - Every non-Feb-29 date is unchanged by construction. This includes C3's linear behaviour, which is kept on
    purpose.
- `tm_yday` features are unchanged.
- **Timing.** Lands **after the B look (12-13) and before 2028-02-29**.
- **Same change.** The release rebind and the `KNOWN_COPIES` update (`tests/operations/test_mg_serve_core_host_import.py`)
  go in the same change, because the fix changes three B-bound files' shas.
- **C1** lands with the fix or separately; it is not B-bound. It adds the count of remapped targets.
- **Optional, after B:** decide whether a future year-round P3d_N refit covers Feb 29 explicitly, or keeps the C5
  coverage gate as the guard. Today a year-round `forward_fit` crashes loudly at prm:1616.

#### Parity checks

- **P1 exhaustive equality.** For every date 2021-01-01..2028-12-31 except the Feb 29s, new `nearest_centre` ==
  old for every set in C3's table. The same holds for `state_features`' centre choice on each frozen state's
  `centres`. Expect zero differences. This also pins C3's linear behaviour as unchanged.
- **P2 copy parity on leap years.** prm == core == mg2_p3d_n for `nearest_centre` and the `state_features` centre
  choice on every 2024 and 2028 date except Feb 29. This closes the 2026-only gap at
  `test_mg_serve_core_parity.py:239-244`. **ALLOWED pre-B** (see routing).
- **P3 frozen-state byte identity.** C1/C2 parity (`test_mg_serve_core_parity.py`,
  `test_mg_serve_core_state_parity.py`) and the `mg2_p3d_n` golden vectors give byte-identical emitted vectors on
  the bound dev and forward dates.
- **P4 Feb-29 cases**, in the fix change:
  - one train-path case: a 2024-02-29 record through `pooled_frame` and the export parity loop;
  - one serve-path case: `state_features` / `serve_distribution` on 2028-02-29.
  - Both must give a finite row equal to the Feb-28 centre choice. The C5 gate still routes MG-2 Feb rows to MG-1.
- **P5 fail-closed pin.** A test asserts today's `ValueError` on 2028-02-29 for all five sites. **ALLOWED pre-B.**
  **Marked for replacement by P4 in the fix change.**
- **C1 check.** The remapped-target count appears in the base retrain or forecast-history receipt for a Feb-29
  target.
- **C2 check (only if C2 is confirmed on a named path).** Parity of the stored reanalysis feature row between train
  and serve. This applies only if a re-keying lands.

#### Routing of P2 and P5 (recorded; the coordinator routes the tests separately)

- P2 and P5 ride the **L58 tests-only lane into combo C**.
- Conditions:
  - tests-only;
  - **zero edits to B-bound files or `KNOWN_COPIES`**;
  - host `Test-BBoundHead` PASS on the tip.
- Not written in this step.

### 6. Open items

- **OPEN, not investigated, no lane:** several year corpora end at 12-28 or 12-30 rather than 12-31.
  - `23ac87fa…`, `31ad5753…` and `eff3ad49…` end 2023-12-28.
  - `5723acb7…` and `e57e6a35…` end 2025-12-30.
- **C2:** open for any allowlist that selects a reanalysis-synoptic column (see C2's verdict).
- **Not traced:** L5 arm B full-year GFS (register X9); the K112 history tier (not run); the MG-1 side on a
  Feb 29.

### 7. Evidence

- **Code.** Every `file:line` above is at `df6e52df0f8a39d850f5fd1f81e50dd9a2d476b2`, read with `git show`
  (no checkout). This includes the served feature lists `artifacts/models/coefs/feature_model_coefs*.json`
  (feature names only).
- **Corpus counts.** Only the metadata keys `market_id`, `target_date`, `cutoff_hour_local` and `status` were read
  from `coverage.jsonl`, plus `years`, `market_ids`, `corpus_role` and `pit_corpora` from `manifest.json`.
  These are the WS paused-mirror copies under `data\training\`; host copies were not checked.
- **No values read.** No label, price, settlement, observation or outcome value was read, and no reanalysis
  feature value (C2 was not confirmed, so nothing was measured).

| Corpus | coverage.jsonl sha256 | manifest.json sha256 | 02-28 / 02-29 / 03-01 |
| --- | --- | --- | --- |
| `ece9d1c28454aa41113b022b92ff6600dcb4a5dab44a6851af5d895feea9281e` | `bb18106178cf1edff9eedafa7e18fb0e3a21f4f4797ff6ace0e4cae8205330e2` | `a854af986701f6e3608e25676bfc5e6cfec3c124936b22a19d5e6dc3c53e0f4f` | 168 / 168 / 168 |
| `0850df30ab9b67cfb4fa03aa04c1ec8b7b119a66555a2137f59d19a860117aad` | `a1ba805f0a2d9f5207b28a5b4a4b43956a5ae7ac69d175e3e920ded14440740d` | `3b53c16ab6d50df0d6adce22ef1f962c6dd5e82c22be71a0b3a30b020fb780de` | 70 / 70 / 70 |
| `bd13267465b8456472a7cf3a778127a8e4291e94711bc89e00d2a2798d61774a` | `76aa55cb2f1537841db9b46cdd94888414aedd5112a7b69b2094c41bfd866f1e` | `60c4812a08cd406702b97e1ab03b8c6cb44ca0e85cdf28a66f323111e85073a9` | 42 / 42 / 42 |
| `b455bd53d8f9…` (Aug-Sep 2021-25) | `cada541f4c3be471a537f63046635d41f1739adf7adbe8399a7188472be855b3` | `0dfc7ed028c14de5532e70e6d59395ce04e85a9d3f8e1efb87e4b47aa6418a88` | 0 (range 2021-08-01..2025-09-30, Aug-Sep) |
| New-city `066547423a78…` | not counted | `8f54330228a09061438740ff72076384b022bd82251992d2a0b3a605542b598a` | lineage only |
| New-city `d519ab1da43d…` | not counted | `05198ca0d2752b02c78cdb9af93f0b21f769d687122150821abe163fb32d61cf` | lineage only |
| New-city `f8eaae6bc4a3…` | not counted | `e820830c354466a966342d4caa786b67b9c63d0a940e4e8908f6ffb7a49cbf45` | lineage only |

The twelve other PIT corpora on the WS have no rows on any of the three dates; their target ranges exclude
2024-02-29.

- **Scripts.** Two new read-only scripts in the WS session scratchpad, each run once:
  - `feb29_cov.py` (sha256 `1433004769d17ceae7086dfaa030c20faced42276826c044fd0e51faecf455cf`; coverage metadata, about
    1.5 s);
  - `feb29_wrap.py` (sha256 `3666aaf8541dfe3229e7f85965b5a14a4f740be3f36d618fae3fc97b7bec7b10`; calendar arithmetic only,
    for C2's window trace and C3).
- **Limits kept.** No model, test suite or heavy command was run. Nothing under `C:\t\l2\p2`, no panel store and
  nothing dated 2026-09-30 or later was opened.
