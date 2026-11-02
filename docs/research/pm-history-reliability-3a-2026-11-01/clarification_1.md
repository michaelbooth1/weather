# 3a Clarification 1 (2026-11-01): script pins, label and floor mechanics, dry run

**Status: CLARIFICATION, NOT RUN.** No label or observation has been read. This file pins the code that
the single 3a run will execute and states the mechanics `rule_3a.md` (sha256
`023b75ed6fcdd14ecc83e5f36f961077c3e338130f7f0434bb3836732088837a`) left to the script. It changes no
kill criterion, arm, bin, fold or gate. Section 3 records master's rulings of 2026-11-02 on the label
mechanics. The Opus review of this clarification and of the extractor comes before any real read; row
113 runs only after row 106's dev run and on the coordinator's go. The pins below are the files after
the first Opus review's fixes (2026-11-02, section 8).

## 1. Pinned files

| File | sha256 |
| --- | --- |
| `tools/research/pm_price_history/reliability_3a.py` | `5b2822b7d5939a841a2b9be638ad891af076bd1c4f3b82851061cfeab28eee80` |
| `tools/research/pm_price_history/l21_stats_e541ad401.py` (byte-identical copy of L21 `run_reliability.py` at `e541ad401110157c71b14b0bfa4589020bb6fe82`; checked at import) | `df12cc8cab980b2af71c55942ce9ec9bbc8422d17c5852bdfc7ae332e421f7a3` |
| `tools/research/pm_price_history/extract_bounded_v1.py` (O-1/O-2 extractor; not yet run on real files) | `a93779d0cf696c88b999a2bd566592a0f1e2bc5ebabaf992bef68eb7eb40db6e` |

The run passes `--expect-sha` equal to the 3a sha above and refuses otherwise; the extractor does the
same with its own sha. The 3a module also pins the extractor's sha (`EXTRACTOR_SHA256`) and refuses an
extract whose manifest records any other `script_sha256`. Any change to any of these files needs a new
dated clarification.

## 2. How the statistic is reused

- The 3a module imports the vendored L21 file and calls its `Pop`, `Stats`, `deltas`, `date_weights`,
  `interval`, `in_sample`, `step_training`, `step_power`, `arm_label`, `bin_table`, `calibration_line`,
  `control_summary`, `public`, `preflight`, `sanitise`, `git_tip` and `peak_mb` unchanged, with L21's
  seed and draw counts.
- LOMO (rule section 5) is L21's own `deltas` with its `starts` argument set to the calendar-month
  boundaries of the date-sorted cells instead of one group per date. `deciding`, `step_synthetic`,
  `pearson_point` and `crossed_interval` are re-stated in 3a only to pass those month groups; their
  arithmetic is L21's line for line. The synthetic tests check A2 and A3 at the point against a
  brute-force leave-one-month-out computation.
- Verdict text is L21's with the scope changed to "B12-HIST", plus the section 4 suffix when no hourly
  extract is given.
- **Step names.** The vendored L21 file is not edited, so its own `Untestable` exceptions carry L21's
  step numbers. 3a's C2 order is one higher, and the receipt maps them: L21 `labels` → `2_label_integrity`,
  `2_synthetic_controls` → `3_synthetic_controls`, `3_training_score_check` → `4_training_score_check`,
  `4_realised_power` → `5_realised_power`. A mapped failure keeps L21's original name in
  `l21_step_name`.

## 3. Labels (O-1 extract only): master's rulings of 2026-11-02, fixed before any read

- **L1, label value (ruling 1: ACCEPTED).** The winning band is the band holding the settlement bucket,
  `weather.sources.daily_summary.native_bucket(row)` (round-half-up of the first present of
  `max_temp_bucket_native`, `max_temp_bucket`, `max_temp_bucket_c`), resolved with
  `weather.backtesting.settlement_ledger.resolve_outcome`. This is the settlement-ledger path, and it
  replaces the rule's "contains `native_high(row)`" wording. It is valid because all of
  2025-12-01..2026-05-26 is before the 10-23 venue-rule events, so the labels are configured WU history
  under the venue-rule contract.
  - **Diagnostic (count only, never selects):** step 2 reports the number of labelled D market-dates
    where containment of the raw `native_high(row)` would pick a different band than the bucket
    (containment picking no single band counts as different), as
    `containment_diagnostic.containment_vs_bucket_differ`.
- **L2, partial WU days (ruling 2: ACCEPTED, exclude-and-count, fail closed).** The threshold is the
  settlement code's own: `COMPLETE_DAY_MIN_ROWS` (18) at `src/weather/backtesting/settlement_ledger.py:34`.
  It is applied at `settlement_ledger.py:498` (a day is complete when `row_count >= COMPLETE_DAY_MIN_ROWS`),
  and `src/weather/backtesting/venue_label_reader.py:205` treats `row_count < COMPLETE_DAY_MIN_ROWS` as
  incomplete. The script imports that constant and records its value and source in the receipt; 3a sets
  no number of its own. A D market-date whose row is below it is excluded and counted, reported per market
  and per month fold (counts only).
- **L3, missing WU rows (ruling 3: REVISED to exclude-and-count).** A D market-date with no row, or a row
  without a numeric bucket, is excluded and counted. Its dates are reported by market and month fold.
- **One combined cap (ruling 3).** Partial + missing must be ≤ 2% of D market-dates (integer-exact:
  `(partial + missing) × 100 ≤ 2 × n`, so exactly 2.0% passes); otherwise step 2 FAILS closed
  (UNTESTABLE). Coverage of the daily labels within D is established by this per-station
  missing-row count and the 2% combined cap; no maximum-date probe exists, since nothing about later rows
  may be reported. Band tiling and this cap are checked before winners, floors or the containment diagnostic
  are computed; a failing receipt carries none of them.
- **Power (ruling 3).** MDE80 0.105 stays as stated in the rule. If more than 1% of D market-dates is
  excluded (integer-exact: `excluded × 100 > n`, so exactly 1.0% does not restate) for any label reason
  (partial, missing, or not exactly one winner), or because the ladder was dropped at load (bands that do
  not parse, a token file missing from the sealed run), the results restate N and MDE80 (T2, scaled by
  √(1,419 / N)). The denominator `n` here includes the ladders dropped at load.
  - The restated N is **label-based**, ruling 3 literally: D market-dates with exactly one winner
    (`power_restated.N`, `N_basis`). The final scored N, after `build_rows` also drops ladders with an
    incomplete or zero-sum price ladder at the deciding hours, is reported separately as
    `N_final_scored_market_dates`. The power gate is still the realised SE at step 5.
- **L4.** A ladder without exactly one winning band is excluded and counted; step 2 FAILS if fewer than
  99% of labelled D ladders have exactly one. Band tiling must hold for 100% of D ladders, and a D ladder
  whose band labels do not parse counts as a non-tiling ladder (`tiling.of_which_band_unparseable`), so
  any such ladder fails step 2 closed.
- Two daily rows for one station-date refuse the read (fail closed, nothing echoed) rather than letting
  the last row win; the extractor refuses the same among its in-range rows.
- Every label row's date passes through a refusal at 2026-05-26 (fail closed, date not echoed). The
  extract is read like the sealed run: the manifest and every data file are read through the extract's
  SHA256SUMS and hashed at the moment they are read, a file not listed there is refused, the manifest
  must declare `last` ≤ 2026-05-26 and must record the pinned extractor sha.

## 4. Floor (O-2 extract only)

- Floor at T = the maximum `temp_native` over that station's hourly rows for the local date whose
  `local_time` (HH:MM) is ≤ T:00. A band is impossible when `kind != "gte"` and its upper whole degree is
  below `floor(floor + 0.5)`, exactly as rule section 4. Without `--hourly-extract` the verdict carries
  "(floor-unadjusted; conservative toward KILL)".

## 5. Price integrity

- Step 1 re-verifies the whole SHA256SUMS of the sealed run, and every file 3a reads is hashed again at
  the moment it is read; a file not listed refuses.
- Events in the sealed run dated after 2026-05-26 are skipped silently and are not counted. The run holds
  prices only, never outcomes, so nothing about a later outcome is read either way.

## 6. Order in code

Preflight (refuses a real run on memory, thread caps or an active heavy job) → 1 price integrity →
population → 2 label integrity → 3 synthetic → 4 training/F3 → 5 power → verdict and descriptives. F1/F2
as L21: no Δ is written until 5 passes; any other exception is a mechanical failure with a digit-free
message.

## 7. Bounded extractor (O-1/O-2) behaviour after the review

- Everything is built in `.staging-extract-<kind>-<stamp>` beside the final directory. Each daily source
  is parsed in full before its output is written. On any refusal or exception the staging directory is
  deleted, so a refused run leaves neither an output nor a staging directory, and nothing can show where a
  bad row sits. Only after the extract, `manifest.json` and `SHA256SUMS` are written and the files made
  read-only is staging renamed to `extract-<kind>-<stamp>`; then the directories are made read-only. An
  existing final directory refuses before anything is read.
- The manifest lists `stations_without_source`: stations with no source file, or (hourly) no partition
  overlapping the window, as names only. It holds no count or date about any later row.

## 8. Review record

The first Opus review (2026-11-02) found no blocker and two majors: partial output left after a refused
extraction (fixed by section 7), and unfilled pins (filled in section 1 with the post-fix files). Its
minors and nits are the items in sections 2, 3, 5 and 7 above that mention the extractor pin, the step
names, the unparseable ladders, the label-based N, the check order, duplicate rows, read-only
directories, the names-only station list and the exact boundary tests.

## 9. Synthetic-only dry run

Run 2026-11-02 15:05 UTC on the WS, direct light run (PID 2924), with the pinned 3a sha above:
`python -m tools.research.pm_price_history.reliability_3a --run C:	\l52\historyun-20261102T004422Z
--out C:	\l52a\dryrun-20261102T150533Z.json --synthetic-only`. It opened no label or observation file.

| Item | Result |
| --- | --- |
| Receipt sha256 | `62c22714f7b1022772f0a3b9a74ee48ff2513dacdf6af71b4c200c35c4a55e8e` |
| Wall time, peak working set | 56.6 s, 218 MB |
| 1 price integrity | PASS: SHA256SUMS `5073afd8…fe71`, 43,195 files re-verified, 15,711 read and re-hashed |
| 2 label integrity | NOT RUN (needs labels); outcome-free tiling 1,419 of 1,419 D ladders, 0 unparseable |
| Deciding population | 1,355 ladder-hours, 695 market-dates, 169 dates, months 2025-12..2026-05; ladders with an incomplete mid at 07/10 are excluded and counted per market and hour |
| 3 synthetic controls | all four checks true; null A1/A2/A3 widest intervals cover 0, in-sample β̂ 1.01; planted β̂ 1.51 with A3 widest lower 0.108 > 0 |
| 4 training score (null) | ok |
| 5 realised power (null projection) | MDE80 A1 0.027, A2 0.070, A3 0.062; power at the edge ≥ 0.99 for all three arms |
| Verdict | NONE (synthetic-only; no real Δ exists) |

The deciding population is 695 market-dates, not the 1,419 D ladders: ladders without a mid within
±120 s at 07:00 or 10:00 local for every band are dropped by `build_rows` (the rule's completeness rule).
The null projection's realised SE already reflects that population, and its power passes the gate.
