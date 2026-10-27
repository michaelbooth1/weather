# Rule L11-deadbucket r4 (lane L11, 2026-10-25): dead buckets 13:00-16:59, dated at capture

**Status.** Written 2026-10-25, before any tape, book or price row is read under this rule, and before any
replay-input snapshot row has been read by this lane. Only directory names and the replay root's `SHA256SUMS`
file (its sha256 and line count) have been read.

**Scope.** Research only: no orders, no live-readiness work, International Polymarket venue only. Development
window only:

- nothing dated after 2026-09-29 is read;
- no 88a, panel or settlement data for 2026-09-30..10-15 is read;
- no oracle.

Approved by master through the coordinator, after the look-ahead audit of 2026-10-25.

**Base rule.** r2, `C:\t\l11\deadbucket_rule_r2.md`, sha256
`177e9acfd7dc50b60d53bdd236ecef971ebcdf767f9dbf4cd0bd241579b17774` (the rule plus clarification 1), together
with r3's declared malformed-row skip.

- **Everything in r2 applies unchanged except how a bucket's death is dated**, as listed below. That covers
  the window, hours, dates, metric, dedupe, fills, fee, value bar, ladder, history, exclusion, CI and the
  pick/kill threshold.
- Code: `weather.calibration.dead_bucket` on branch `claude/market-blend-l11-20261025`, with a
  `--dating capture` option on the stage-a-scan and stage-a-report phases. The obs-dated path is unchanged.
- Nothing below changes once this file's sha256 is recorded. Any change is a dated clarification, written
  before the rows it affects.

**What is already known.** Stage A obs-dated gave $0.37/day [0.12, 0.69] at $25 (report `4aa9bf7c…`). The
look-ahead audit found that 41 of its 57 primary trades were not yet dead on the served floor at the book row.
Both results are known. Neither is used to choose anything here: every constant is r2's.

## The one change: capture-time dating

**Source.** Replay inputs at `C:\Users\Michael\Documents\github\weather\data\inbox\replay-inputs-le0929`.

- Its `SHA256SUMS` has sha256 `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` (732 lines).
  The code pins it.
- There is one `snapshots/<event>/replay_inputs.jsonl` per market-day.
- The code refuses any folder whose target date is after 2026-09-29.
- The files are read-only and are streamed line by line.

**Snapshot floor (primary).** For each replay snapshot of the market-day:

- its receipt instant is its own `captured_at_utc` (or `captured_at_local`, converted to UTC);
- its floor is H_s = floor(R_s + 0.5), where R_s is L8's
  `running_max_since_midnight({}, sources.metar.data, target_date, tz, unit, cutoff_hour=17, now=receipt)`;
- R_s is computed on **that snapshot's own captured METAR rows only**, with an empty station source, so the
  floor is METAR-only;
- snapshots are processed in receipt order.

**Dead bucket.** An `lte` or `eq` bucket with upper edge `high` is dead when at least one snapshot captured at or
before 16:59 local on the target date has H_s > `high`.

- Its **first-dead instant = the receipt instant of the first such snapshot**: the first captured snapshot whose
  own METAR rows contain the killing METAR. There is no +10-minute offset.
- The IEM observations are not used to date or select dead buckets under r4.

**Entry.** Entry = max(first-dead + 60 s, 13:00), as in r2. A bucket dead before 13:00 enters at 13:00.

**Book and prints.** Both are re-read from that entry onward exactly as in stage A (r2 clarification 1):

- q* is the first capture at or after entry.
- The fill is min(stake / q*, depth within 1%, prints in [entry, entry + 5 min]).
- No capture means no NO ask and no YES bid in [entry, 16:59].
- Duration, value >= 0.005, fee 0.05 q*(1 - q*), and the $5 / $25 / $100 ladder are all unchanged.

**Days without a replay snapshot.** A market-day with no replay snapshot before 16:59 contributes no dead
bucket. It is counted as `no_replay`.

**Descriptive only (not part of the reading):**

- the obs-dated first-dead (r2: IEM obs + 10 min) per bucket, and the r4 receipt minus that instant;
- the production-floor delay: the first layout snapshot whose served floor (the max of
  `guidance_physical_floor`, `high_so_far` and `trusted_current_max`) kills the bucket, relative to the r4
  receipt;
- counts of buckets that are dead under one dating but not the other;
- a count of non-monotone snapshot floors (H_s falling between consecutive snapshots).

## Malformed summary rows (declared)

As in r3: a book-summary row whose field count differs from the header, or that has any field longer than 4,096
characters, is skipped and counted. A replay line that is not valid JSON is skipped and counted
(`replay_bad_lines`).

## History and exclusion

The r2 history is reused unchanged:

- file `564e6d8b656893fa622ef273ce307800da68c06541e0224ddff33ee64fa87861`, decisive cutoff 16:59, X = 2.0%;
- the excluded set is empty;
- the expected-loss variant uses its rates.

## Windows of dates and readings

**Primary.** 2026-08-10..09-29, using:

- trade-print fills (`print_d1`) at $25;
- $/day summed over the kept markets per date, then averaged over dates;
- a date-clustered 95% CI (2,000 draws, seed 20260921).

**Other rows:**

- Book-only 2026-08-01..08-09 is reported separately and never pooled.
- Sensitivities as r2: depth within 5%, and book-only on 08-10..09-29.
- Secondary: per market, per entry hour 13-16, the ladder, expected-loss, PRIMARY5, durations and the trade
  count.

**Reading (r2's threshold).** If the lower CI bound is > 0, the result is worth an owner decision on a forward
paper test. Otherwise it is not worth pursuing. This reading replaces the suspended stage-A reading.

## (a) Positive control

1. **Fixture tests, before any dev row.**
   - A synthetic replay file holds three snapshots. A bucket must die at the receipt of the first snapshot
     whose rows contain the killing METAR, not at obs + 10 min.
   - A snapshot captured before that METAR's observation must not kill the bucket.
   - All existing obs-dated stage-A fixture tests must pass unchanged.
2. **Dev sanity, checked in the report before the reading.** Take the buckets dead under both datings. The share
   whose r4 receipt is at or after the killing IEM observation instant must be >= 0.95, because a METAR cannot
   be received before it is observed.
   - Below 0.95, the result is NOT INTERPRETABLE and is reported as such.
   - The r2 history rates must equal the pinned file's (Houston 16:59 rate 0.0033, every other market 0.0).

## (b) Comparator fairness

As r2: no comparator is traded, and value is measured against $0. Every market and day gets the same METAR-only
floor and rule-4 rounding. The market price gets no calibration. Fee, latency and sizes are the same
throughout. Labels are the WU settlement proxy.

## (c) Targeted loss slice

r2's 13-16 dead-bucket slice: atlas `535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4`,
expected size 0.0224 in R (PRIMARY5 floor-only). It is stated for the record only; no threshold here depends
on it.

## (d) MDE and clusters

The primary has 48 date clusters (the 08-10..09-29 dates present) and up to 11 market clusters. MDE80 in $/day
comes from the date-clustered bootstrap (`dev_scorecard.mde80`). For reference, the obs-dated stage-A primary's
MDE80 was 0.41.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: r3 left 33 rows. This check adds 1 K row (dead-bucket NO taker, 13-16, capture-dated),
which is K candidate 24 on 2026-07-31..09-29. It reuses the 13-16 rows already spent by r2.
