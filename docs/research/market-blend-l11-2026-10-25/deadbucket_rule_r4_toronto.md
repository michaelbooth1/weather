# Rule L11-deadbucket r4-toronto (lane L11, 2026-10-25): Toronto dead buckets 13:00-16:59, dated at capture, native Celsius

**Status.** Written 2026-10-25, before any Toronto book, price, trade-print or replay-snapshot row is read.
Only these have been read:

- the directory listing of the Toronto tapes folder (61 entries, including SHA256SUMS) and the sha256 of its
  SHA256SUMS file;
- the r2-toronto history JSON (already computed).

The Toronto dev-window IEM observations have not been fetched yet.

**Scope.** Research only: no orders, no live-readiness work, International Polymarket venue only. Development
window only:

- nothing dated after 2026-09-29 is read;
- no 88a, panel or settlement data for 2026-09-30..10-15 is read;
- no oracle.

Approved by master through the coordinator.

**Base rules:**

- **r4**, `C:\t\l11\deadbucket_rule_r4.md`, sha256 `fac8cd7211bb3c0e39edc8f95a7808c24fdf3a36558d9da5aab8462ff684a921`.
  It supplies the capture-time dating and every stage-A constant.
- **r2-toronto**, `C:\t\l11\deadbucket_rule_r2_toronto.md`, sha256
  `c754ddab8ed3634c0854444dded9d4831bf4ff955b5efd944fc54f582246ef3d`. It supplies the Celsius specifics, the
  station and the history.
- Everything in r4 applies unchanged, in native whole °C. **No Fahrenheit value is formed anywhere.**

**Code.** `weather.calibration.dead_bucket_toronto` on branch `claude/market-blend-l11-20261025`, with a
`--dating capture` option on its stage-a-scan phase.

**Change control.** Nothing below changes once this file's sha256 is recorded. Any change is a dated
clarification, written before the rows it affects.

## Inputs (pinned)

- **Tapes:** `C:\Users\Michael\Documents\github\weather\data\inbox\tapes-toronto-0801-0929`.
  - The SHA256SUMS sha256 is `a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0`. It is the
    file as delivered, with CRLF line endings.
  - The tapes are read-only and streamed. The code refuses any folder whose target date is after 2026-09-29.
- **Replay inputs:** `C:\Users\Michael\Documents\github\weather\data\inbox\replay-inputs-le0929`, SHA256SUMS
  `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82`, the 61 `highest-temperature-in-toronto-*`
  folders.
- **History:** the r2-toronto history `toronto_history.json`, sha256
  `3a652c232d388a83e41a1d67effa9f10b11293995bd751f1a142e04d777b7c9d`.
  - It covers CYYZ in Aug-Sep 2021-2025, with 304 days kept.
  - The 16:59 violation rate is 0.0, so with X = 2.0% Toronto is not excluded.
  - The expected-loss variant uses that rate.
- **Settlement proxy:** WU `max_temp_native` (whole °C, `temperature_unit` C) from
  `data/wunderground/cyyz/daily/daily_summary.csv`.
  - Only rows dated 2026-08-01..09-29 are kept, and rows with later dates are dropped before any value is
    parsed.
  - A day without a WU label is counted as `no_wu_label` and contributes nothing.
- **IEM CYYZ dev observations:** fetched after this rule by the existing `fetch --dev` phase (2026-07-30 00Z to
  2026-09-30 04Z). They are used only for the descriptive obs + 10 min dating and controls (a)2-3. Their sha256
  is recorded in the results.

## Buckets: Celsius parse check (declared)

- Every summary row's `range_label` is parsed with `weather.units.parse_temperature_band(expected_unit="C")`.
  The result is cross-checked against `bin_kind`, `bin_value`, `bin_value_hi` and `unit`, which must be C.
- A row that fails the parse or any cross-check is **never coerced**. It is skipped, counted, and its
  (label, kind, value, value_hi, unit) tuple is listed in the scan output and the results. Malformed rows are
  handled as in r3.
- **Dead-candidate buckets:** `lte X` (upper edge X °C) and `eq lo-hi` (upper edge hi °C). `gte` is never dead.
- **Settlement in whole °C:** `lte X` is YES iff WU max <= X, `eq lo-hi` iff lo <= WU max <= hi, and `gte X`
  iff WU max >= X.
- **Reported parse result:**
  - distinct labels parsed, and their parsed ranges;
  - distinct failures, with their rows;
  - days whose parsed bucket set is not a contiguous partition of the integers. Such days are reported and
    their buckets used as parsed.

## Dating: r4 capture time, native Celsius

- **Snapshot floor.** For each Toronto replay snapshot of the day (in receipt order):
  - its receipt is its own `captured_at_utc`;
  - its floor is H_s = floor(R_s + 0.5), where R_s is L8's
    `running_max_since_midnight({}, sources.metar.data, target_date, tz America/Toronto, unit "C", cutoff_hour 17, now=receipt)`;
  - R_s uses that snapshot's own captured METAR rows only;
  - H_s is in whole °C.
- **Dead bucket.** A bucket with upper edge `high` (°C) is dead when some snapshot captured at or before 16:59
  local has H_s > `high`. The comparison is integer °C against integer °C.
- **First-dead.** First-dead = the receipt of the first such snapshot, with no offset.
- **Entry.** Entry = max(first-dead + 60 s, 13:00).
- **Unchanged from r4 / r2 clarification 1:** book and prints from entry onward, q*, fills (depth within 1%,
  prints in [entry, entry + 5 min]), fee 0.05 q*(1 - q*), value >= 0.005, duration, and the $5 / $25 / $100
  ladder.
- **No replay snapshot.** A day without a replay snapshot is counted as `no_replay`.

## Windows of dates and readings

**Primary.** 2026-08-10..09-29, using:

- `print_d1` fills at $25;
- $/day for Toronto per date, averaged over dates;
- a date-clustered 95% CI (2,000 draws, seed 20260921).

**Other rows:**

- Book-only 2026-08-01..08-09 is reported separately and never pooled.
- Sensitivities: depth within 5%, and book-only on 08-10..09-29.
- Secondary: per entry hour 13-16, the ladder, expected-loss, durations and the trade count.

**Reading (r2's threshold).** If the lower CI bound is > 0, the result is worth an owner decision on a forward
paper test. Otherwise it is not worth pursuing. If any of controls (a)2-4 fails, the reading is NOT
INTERPRETABLE.

## (a) Positive control

1. **Fixture tests, before any dev row:**
   - Celsius labels, including the open-ended top (`X°C or higher`) and bottom (`X°C or below`) buckets, parse
     to °C ranges.
   - A Fahrenheit or malformed label is refused and listed, not coerced.
   - The floor comparison is in native °C.
   - A capture-dated Toronto death happens at the receipt of the first snapshot whose rows hold the killing
     METAR.
2. **Receipt after observation.** Take the buckets dead under both the capture dating and the IEM
   (obs + 10 min) dating. The share whose receipt is at or after the killing IEM observation must be >= 0.95.
3. **Celsius sanity.** On scanned days, the last snapshot's H_s at or before 16:59 must be within 1 °C of the
   IEM CYYZ H at 16:59 on >= 0.95 of days. A °F-valued floor would miss by about 20 or more, so this guards
   against any unit slip.
4. **History.** The r2-toronto history must be the pinned file, with a 16:59 rate of 0.0.

## (b) Comparator fairness

As r2: no comparator is traded, and value is measured against $0. Every day gets the same METAR-only floor and
rule-4 rounding (in °C). The market price gets no calibration. Fee, latency and sizes are the same throughout.
Labels are the WU settlement proxy in whole °C.

## (c) Targeted loss slice

r2's 13-16 dead-bucket slice: atlas `535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4`,
expected size 0.0224 in R (US PRIMARY5 floor-only). It is for the record only, since Toronto has no atlas slice.
No threshold here depends on it.

## (d) MDE and clusters

The primary has up to 48 date clusters (the 08-10..09-29 dates present) and 1 market cluster. MDE80 in $/day
comes from the date-clustered bootstrap. For reference, the US r4 primary's MDE80 was 0.06.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: r4 left 34 rows. This check adds 1 K row (Toronto dead-bucket NO taker, 13-16,
capture-dated), which is K candidate 25 on 2026-07-31..09-29. It is the first Toronto row.

## Clarification 1 (2026-10-25, before any 08-11..09-29 label or this measure's rows are read)

Approved by master through the coordinator. The original rule sha256 is
`12902246a5358df5a2926314465e61dd4d1afaeedd408b994706e5b773c9f061`. **The primary, every constant, the windows
and the reading stay exactly as registered above.**

1. **Settlement-proxy input.** The pinned `data/wunderground/cyyz/daily/daily_summary.csv` ends at 2026-08-10.
   A second, separate input is appended after it:
   - path `data/inbox/wu-cyyz-0811-0929/daily_summary_cyyz_0811_0929.csv`;
   - sha256 `c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a`;
   - 50 rows, 2026-08-11..09-29, with the same header.

   The pinned file is not edited. The code fails closed if the second input:
   - has a sha mismatch or a header mismatch;
   - has any row dated after 2026-09-29;
   - has a non-C unit;
   - has any `local_date` that duplicates another row in it or a row of the pinned file.

   Both input shas are recorded in the scan output. r4-toronto is then re-run unchanged.
2. **Label-free tradability (descriptive, secondary only; never part of the primary or the reading).**
   - For every capture-dated dead bucket, on every scanned tape day with or without a WU label, count whether
     **any** snapshot from entry to 16:59 has a NO best ask q with `value(q) = 1 - q - 0.05 q (1 - q) >= 0.005`.
     That is the rule's minimum.
   - Only the NO side's own ask counts. The 1 - YES-bid fallback does not count.
   - For those buckets, record the qualifying snapshot count and the first qualifying snapshot's time, ask and
     `ask_depth_1pct` / `ask_depth_5pct`. Also record the maximum `ask_depth_1pct` over qualifying snapshots,
     which is the fillable size in shares.
   - Report the totals: dead buckets, buckets with a qualifying NO ask, the sums of first-qualifying
     `ask_depth_1pct` and of maximum `ask_depth_1pct`, and the count per entry hour.
