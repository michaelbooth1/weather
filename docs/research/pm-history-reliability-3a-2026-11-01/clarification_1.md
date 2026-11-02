# 3a Clarification 1 (2026-11-01): script pins, label and floor mechanics, dry run

**Status: CLARIFICATION, NOT RUN.** No label or observation has been read. This file pins the code that
the single 3a run will execute and states the mechanics `rule_3a.md` (sha256
`023b75ed6fcdd14ecc83e5f36f961077c3e338130f7f0434bb3836732088837a`) left to the script. It changes no
kill criterion, arm, bin, fold or gate. Items marked **(for review)** fill a gap in the rule and need the
coordinator's and the Opus review's acceptance before the go.

## 1. Pinned files

| File | sha256 |
| --- | --- |
| `tools/research/pm_price_history/reliability_3a.py` | `@@R3A@@` |
| `tools/research/pm_price_history/l21_stats_e541ad401.py` (byte-identical copy of L21 `run_reliability.py` at `e541ad401110157c71b14b0bfa4589020bb6fe82`; checked at import) | `df12cc8cab980b2af71c55942ce9ec9bbc8422d17c5852bdfc7ae332e421f7a3` |
| `tools/research/pm_price_history/extract_bounded_v1.py` (O-1/O-2 extractor; not yet run on real files) | `@@EXT@@` |

The run passes `--expect-sha` equal to the 3a sha above and refuses otherwise; the extractor does the
same with its own sha. Any change to any of these files needs a new dated clarification.

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

## 3. Labels (O-1 extract only)

- **L1 (for review).** The rule says the winning band contains `native_high(row)`. The script uses the
  project's settlement bucket, `weather.sources.daily_summary.native_bucket(row)` (round-half-up of
  `max_temp_bucket_native`, `max_temp_bucket`, `max_temp_bucket_c`, first present), and resolves the band
  with `weather.backtesting.settlement_ledger.resolve_outcome`. Bands are whole degrees, and this is how
  the settlement ledger and every dev read settle; for a whole-degree high the two are identical.
- **L2.** "Every scored market-date has a WU row" (rule section 6 step 2) is enforced literally: a D
  market-date with no row, or a row without a numeric bucket, makes step 2 FAIL (UNTESTABLE).
- **L3 (for review).** A row whose `row_count` is below the settlement ledger's complete-day minimum
  (`COMPLETE_DAY_MIN_ROWS`, 18) is not settled by the ledger. Such market-dates are excluded and counted;
  if they exceed 2% of D market-dates, step 2 FAILS.
- **L4.** A ladder without exactly one winning band is excluded and counted; step 2 FAILS if fewer than
  99% of labelled D ladders have exactly one. Band tiling must hold for 100% of D ladders.
- Every label row's date passes through a refusal at 2026-05-26 (fail closed, date not echoed), and the
  extract's manifest must declare `last` ≤ 2026-05-26 with its SHA256SUMS re-verified.

## 4. Floor (O-2 extract only)

- Floor at T = the maximum `temp_native` over that station's hourly rows for the local date whose
  `local_time` (HH:MM) is ≤ T:00. A band is impossible when `kind != "gte"` and its upper whole degree is
  below `floor(floor + 0.5)`, exactly as rule section 4. Without `--hourly-extract` the verdict carries
  "(floor-unadjusted; conservative toward KILL)".

## 5. Price integrity

- Step 1 re-verifies the whole SHA256SUMS of the sealed run, and every file 3a reads is hashed again at
  the moment it is read; a file not listed refuses.

## 6. Order in code

Preflight (refuses a real run on memory, thread caps or an active heavy job) → 1 price integrity →
population → 2 label integrity → 3 synthetic → 4 training/F3 → 5 power → verdict and descriptives. F1/F2
as L21: no Δ is written until 5 passes; any other exception is a mechanical failure with a digit-free
message.

## 7. Synthetic-only dry run

@@DRY@@
