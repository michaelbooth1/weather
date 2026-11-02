# 3a Clarification 1 (2026-11-01): script pins, label and floor mechanics, dry run

**Status: CLARIFICATION, NOT RUN.** No label or observation has been read. This file pins the code that
the single 3a run will execute and states the mechanics `rule_3a.md` (sha256
`023b75ed6fcdd14ecc83e5f36f961077c3e338130f7f0434bb3836732088837a`) left to the script. It changes no
kill criterion, arm, bin, fold or gate. Section 3 records master's rulings of 2026-11-02 on the label
mechanics. The Opus review of this clarification and of the extractor comes before any real read; row
113 runs only after row 106's dev run and on the coordinator's go. The pins below are the files after
the first Opus review's fixes and the re-review's folds, including master's 2026-11-02 report additions
(sections 8 and 10).

## 1. Pinned files

| File | sha256 |
| --- | --- |
| `tools/research/pm_price_history/reliability_3a.py` | `6e5beb395fbab734dcdb7ad54fe91e440f3b87cb96062c752536c8b62f8fb108` |
| `tools/research/pm_price_history/l21_stats_e541ad401.py` (byte-identical copy of L21 `run_reliability.py` at `e541ad401110157c71b14b0bfa4589020bb6fe82`; checked at import) | `df12cc8cab980b2af71c55942ce9ec9bbc8422d17c5852bdfc7ae332e421f7a3` |
| `tools/research/pm_price_history/extract_bounded_v1.py` (O-1/O-2 extractor; not yet run on real files) | `65ce60f34a06f35488747cb60603701ab9aeb46a03d036bd973c457a9f6d945a` |

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
    (`power_restated.N`, `N_basis`). The final scored N, after `build_rows` also drops ladder-hours with
    an incomplete or zero-sum price ladder at the deciding hours (rule line 117), is reported separately
    as `N_final_scored_market_dates`, with the T2 MDE80 scaled to it, `MDE80_T2_at_N_final_scored`
    (about 0.150 at N = 695). The power gate is still the realised SE at step 5.
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
  deleted (best effort, a second Ctrl-C during the delete included), so a refused run normally leaves
  neither an output nor a staging directory, and nothing can show where a bad row sits. If the staging
  directory cannot be deleted, the run fails with the fixed message "delete <staging path> without
  reading it" and never lists its contents. Any later run refuses, printing only that path, while any
  `.staging-extract-*` directory exists under `--out-root`. Only after the extract, `manifest.json` and
  `SHA256SUMS` are written and the files made read-only is staging renamed to `extract-<kind>-<stamp>`;
  then the directories are made read-only. That directory bit is cosmetic on NTFS, where it does not
  stop writes; the files' read-only bit is the real protection. An existing final directory refuses
  before anything is read.
- The manifest lists `stations_without_source`: stations with no source file, or (hourly) no partition
  overlapping the window, as names only. It holds no count or date about any later row.

## 8. Review record

The first Opus review (2026-11-02) found no blocker and two majors: partial output left after a refused
extraction (fixed by section 7), and unfilled pins (filled in section 1 with the post-fix files). Its
minors and nits are the items in sections 2, 3, 5 and 7 above that mention the extractor pin, the step
names, the unparseable ladders, the label-based N, the check order, duplicate rows, read-only
directories, the names-only station list and the exact boundary tests.

The re-review of `936078c7e1975bb870b33ec3cad48cec60e87b71` was CLEAN. Its folds are in this version:
- best-effort staging deletion with a fixed failure message, and the stale-staging refusal (section 7);
- an LF-only receipt, so its sha is the same on every platform;
- the dry-run command line copied from the receipt (section 9);
- the T2 MDE80 at the final scored N (section 3);
- an L21 `labels` failure raised after step 2 has passed is recorded under its own key
  (`2_label_integrity__l21_labels`) and never overwrites the PASS record;
- the NTFS note (section 7);
- "ladder-hours" wording (sections 3 and 9).

## 9. Synthetic-only dry run

Run 2026-11-02 15:16 UTC on the WS, a direct light run (PID 9964), with the pinned 3a sha above. It opened
no label and no observation file. The command line, copied from the receipt's `command_line`, was:

```
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe C:\wt\l52\tools\research\pm_price_history\reliability_3a.py --run C:\t\l52\history\run-20261102T004422Z --out C:\t\l52\3a\dryrun-20261102T151627Z.json --synthetic-only
```

It was started as `python -m tools.research.pm_price_history.reliability_3a` from `C:\wt\l52`, so the
receipt shows the module's file path.

| Item | Result |
| --- | --- |
| Receipt sha256 (on-disk file, LF) | `a1067a79879985ca47117b91915fc45740604ba43809b8624da854dcd7ac0369` |
| Wall time, peak working set | 207.8 s, 217 MB. Two other heavy slots were busy; the earlier run of the previous pin took 56.6 s |
| 1 price integrity | PASS: SHA256SUMS `5073afd8…fe71`, 43,195 files re-verified, 15,711 read and re-hashed |
| 2 label integrity | NOT RUN (needs labels); outcome-free tiling 1,419 of 1,419 D ladders, 0 unparseable |
| Deciding population | 695 of 1,419 D market-dates, 1,355 ladder-hours, months 2025-12..2026-05 (section 10) |
| 3 synthetic controls | all four checks true. Null: A1/A2/A3 widest intervals cover 0, in-sample β̂ 1.01. Planted: β̂ 1.51, A3 widest lower bound 0.108 > 0 |
| 4 training score (null) | ok |
| 5 realised power (null projection) | MDE80 A1 0.027, A2 0.070, A3 0.062; power at the edge ≥ 0.99 for all three arms |
| Verdict | NONE (synthetic-only; no real Δ exists) |

The previous pin's dry run (15:05 UTC, PID 2924) gave the same numbers. Its receipt
(`C:\t\l52\3a\dryrun-20261102T150533Z.json`, on-disk sha256
`26925f47aae0cd737f246dc186c266a269d2c93870405939ed851a23e8985961`, CRLF) is superseded.

## 10. Addition of 2026-11-02 (master): deciding-population headline and fold split

Master accepted the 695 / 1,419 disclosure and added two report requirements. Both are computed by
`deciding_population` from prices alone: `build_rows` with no label and no floor, run right after the
sealed run loads and before step 2 reads any label. The exclusion is therefore outcome-blind and fixed
before any label read. Both appear in the receipt as `deciding_population` in every mode, and the
headline leads the printed summary.

- **(a) HEADLINE.** The receipt opens with "HEADLINE: deciding population 695 of 1419 D market-dates
  (1355 ladder-hours at 07:00/10:00 local), excluded on price completeness only: outcome-blind, fixed
  before any label read". `exclusions_by_market_hour` is the per-market × hour table of ladder-hours
  dropped for an incomplete (or zero-sum) mid. `MDE80_T2_at_kept` is the T2 MDE80 scaled to the kept
  market-dates (0.150 at 695).
- **(b) Fold split (counts only, no labels).** `kept_vs_excluded_by_month_fold` gives, per calendar-month
  fold, the D market-dates kept, excluded on price completeness, and dropped at load.

From the dry run (prices only):

| Market | Ladder-hours dropped at 07:00 | at 10:00 |
| --- | ---: | ---: |
| atlanta | 58 | 60 |
| austin | 30 | 34 |
| chicago | 62 | 66 |
| dallas | 68 | 69 |
| denver | 35 | 35 |
| houston | 39 | 39 |
| los-angeles | 49 | 50 |
| miami | 63 | 64 |
| nyc | 90 | 100 |
| san-francisco | 48 | 50 |
| seattle | 95 | 99 |
| toronto | 87 | 93 |

| Month fold | Kept | Excluded (price completeness) | Dropped at load |
| --- | ---: | ---: | ---: |
| 2025-12 | 79 | 63 | 0 |
| 2026-01 | 101 | 73 | 0 |
| 2026-02 | 115 | 81 | 0 |
| 2026-03 | 139 | 108 | 0 |
| 2026-04 | 142 | 218 | 0 |
| 2026-05 | 119 | 181 | 0 |

The excluded share is highest in 2026-04 (61%) and 2026-05 (60%), against 41% to 44% in the earlier
folds. This is disclosed, not corrected: completeness is a price property fixed before any label read.

**Master's ruling on the power flag (2026-11-02), recorded before any outcome read**

- **Run as frozen.** Row 113 runs at the 695 price-complete market-dates. The completeness rule (rule
  line 117) is not loosened.
- **How an underpowered null reads: already fixed by the frozen rule, so nothing is added.**
  `rule_3a.md` (sha256 `023b75ed…837a`) covers it in three lines:
  - line 192: step 5's power gate on the realised SE; a run that misses it is UNTESTABLE;
  - line 217: KILL is only "at edge size", every arm's widest interval inside ±0.2236;
  - line 218: any other result, including a 95% interval that contains 0 without lying inside
    ±0.2236, is NOT KILLED. It is SCREEN-POSITIVE only when a lower bound is above 0.
  - No verdict in the rule reads "no effect".
  - MDE80 0.150 at 695 is below the 0.2236 edge, so a KILL at edge size stays meaningful at this N.
  - The suggested INCONCLUSIVE sentence would relabel a KILL whose interval contains 0, so it would
    change a frozen verdict. Per the ruling it is not added.

**Cause of the Apr/May exclusion gap: price-coverage counts only**

Counted on 2026-11-02 from the sealed run alone (prices and event metadata; no label, no outcome) by a
scratch counter (sha256 `0c07be115b04c41f4ca9000d6d0df66fdcfc9ee6a3f754afa23438514be00ecc`). It
re-hashed every file it read and reproduced the 1,355 kept ladder-hours. Shares below are per ladder-hour
(market-date × 07:00/10:00), so they differ slightly from the market-date shares above.

- **Mechanism (established).** In every excluded ladder-hour in every month, at least one band token has
  a price history that **ends before T**: its last point is earlier than 07:00 or 10:00 local on the
  event day. No excluded ladder-hour comes from any of these:
  - a missing token file (all present; nothing dropped at load);
  - an empty history;
  - a history that starts after T;
  - a gap inside the history around T.
  It is band-level coverage, not ladder-level: in most excluded ladder-hours only some bands fail; all
  bands fail in 4% to 14% of them.

| Month | Bands per ladder | Ladder-hours excluded | Failing bands interior (not end bands) |
| --- | ---: | ---: | ---: |
| 2025-12 | 7.0 | 134 of 284 (47%) | 60% |
| 2026-01 | 7.0 | 149 of 348 (43%) | 65% |
| 2026-02 | 8.1 | 167 of 392 (43%) | 64% |
| 2026-03 | 10.2 | 220 of 494 (45%) | 71% |
| 2026-04 | 11.0 | 441 of 720 (61%) | 75% |
| 2026-05 | 11.0 | 372 of 600 (62%) | 76% |

- **What coincides with the gap (established as counts, not as cause):**
  1. Five markets first appear in late March (austin, denver, houston, los-angeles, san-francisco;
     7 ladders each in March) and fill the Apr/May cells. About 70% of their ladder-hours are excluded:
     212 of 300 in April and 187 of 270 in May.
  2. Excluding those five markets, the other seven still go from 43% to 47% before March to 55% in April
     (229 of 420) and 56% in May (185 of 330). In April chicago, dallas and miami rise to 68% to 87%,
     while atlanta, nyc, seattle and toronto fall to 23% to 47%.
  3. Every market's ladder grows to 11 bands in April (7 in Dec–Jan, 8 in Feb, 10 in Mar). The
     completeness rule needs every band covered, and the failing bands are increasingly interior bands.
- **Why those band histories end before the event morning: cause not established.** The counts show the
  mechanism (histories ending before T) and its correlates (new markets, 11-band ladders, a few older
  markets) but cannot show why the histories end early. Establishing that would need venue-side
  information this run does not hold. It changes nothing in the frozen run.
