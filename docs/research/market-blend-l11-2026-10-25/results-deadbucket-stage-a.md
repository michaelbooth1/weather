# Dead-bucket stage A: book and trade-print fills (lane L11, 2026-10-25)

Development evidence only. Research only: no orders, International venue only.

- Rule: r2 `177e9acf…` (clarification 1). History: `564e6d8b…` (excluded set: none).
- Tapes: `data\inbox\tapes-us-0801-0929`, read-only, SHA256SUMS sha256
  `5c992a7335848025db545b2489b87c4777c570aebf3f072185534a86ccaf4ee3` (pinned and checked by the code).
- Code: `e03639dcf`.
- Scans: three per-market-group scans through `workstation_heavy.ps1`, run in parallel.
  - g1 `31b0b878…`, g2 `6d6b5df5…`, g3 `8f97e143…`.
  - A first attempt died on a CSV field over the 128 KiB limit. Seven oversized or torn summary rows are now
    counted and skipped, and none of them is used.
- Pooled report: JSON sha256 `4aa9bf7cb7300e4b92b8e0b3fe4bb097271a68c4fc7672ae2c3b28db33246caa`.
  - It ran directly with the venv python, single-threaded, while `C:\t\PREGATE_HOLD` was present. The
    coordinator authorised this: the report reads only the three scan JSONs and the history JSON, never the
    tapes, and took 1 s. The run is logged in `C:\t\l11\jobs\direct_runs.log`.
- Outputs are in `C:\t\l11\db_a` and are not committed.

## First scan launch and the relaunch (record)

**The bug.** The first launch ran code `e74e340ff`. `stream_summary` read `order_books_summary.csv` with
Python's `csv` module and its default 131,072-character field limit. Some captured summary rows carry a field
longer than that. The g1 and g2 scans stopped with `_csv.Error: field larger than field limit (131072)`
inside `stream_summary`, and the wrapper still exited 0.

**What was read before the fix.** Only the tracebacks: the tail of the g1 and g2 wrapper outputs, plus a
process listing.
- The g3 scan was still running and was killed (PIDs 68188 and its parent 30648).
- A scan writes its JSON and Markdown only after it finishes all of its markets. None of the three wrote an
  output, so no row, count, price or P&L from the first launch was seen.
- `C:\t\l11\db_a` was then emptied, and all three scans were relaunched from `e03639dcf`.

**The fix: code only, with no change to rule r2.** `e03639dcf` changes these lines of `stream_summary`:
- It raises the CSV field limit, so the reader no longer aborts.
- It skips any row whose field count differs from the header, or that has a field over 4,096 characters.
  Before the fix only short rows were skipped. Skipped rows are counted (`summary_bad_rows`); none is used.
- The rows that can be used are a few short numeric fields, which never come near 4,096 characters.

Nothing else changed: the entry time, q*, depth cap, print cap, fee, value threshold, durations, windows,
variants and readings are as in r2 `177e9acf…`, and the rule file was not edited.

The skip is a data-hygiene choice that r2 does not spell out. It removed 7 summary rows across the 621
scanned market-days. Its effect on the result was not measured, since that would need another tape scan.
A skipped row removes one capture. If that capture was the first one at or after entry, q* moves to the
next capture, which can change the price, or whether a trade happens, in either direction.

## Reading (pre-registered)

The **$25 primary, 08-10..09-29, trade-print fills with depth within 1%** is **$0.37/day [0.12, 0.69]**
(date-clustered, 48 dates, 12 of them non-zero), with MDE80 $0.41.

The lower CI bound is above 0, so the mechanical reading is: **worth an owner decision on a forward paper
test.**

## What the number is

- Of 3,106 dead buckets in non-excluded markets, 2,945 have no NO ask and no YES bid at any capture between
  entry and 16:59. The status for these is `no_capture`.
  - The book has already conceded: NO is bid at 0.999 with no ask, and YES is offered at 0.001 with no bid.
  - There is nothing to buy.
- 100 more buckets have an ask with no value after the fee. 61 trade.
- Fills are thin. In 08-10..09-29 there were 57 trades, and only 17 had a qualifying print within 5 minutes.
  They filled 255 of the 2,004 shares wanted at $25.
  - The $100 size adds little ($0.44/day), because prints bind before stake does.
- All of the money is Denver; every other market is $0.00/day.
- 0 traded buckets settled YES, and the history violation rate is 0.03%. P&L is therefore non-negative by
  construction on these dates, and the lower CI bound > 0 follows from any fill at all. The rule's
  expected-loss variant ($0.37) prices the history rate, but the dev window contains no tail event.
- Sensitivities on 08-10..09-29:
  - Depth within 5%: $0.43 [0.12, 0.82].
  - Book-only (no print cap): $3.94 [1.49, 7.29], Denver $3.22. That would be the bound if resting asks were
    takeable without a print.
- Book-only 08-01..08-09, reported separately: $0.53 [0.00, 1.20] (9 dates, Denver only).
- Durations: median 94 minutes, p90 230 minutes.
  - The residual NO asks on dead buckets stay up for hours, but almost no taker volume prints against them at
    those prices.
- The stage-C gross bound was $18.35/day. With real books and prints it falls about 50-fold to $0.37/day.

The full tables follow, as generated by the run.

# Dead-bucket stage A: book + trade-print fills (development evidence)

Rule `177e9acfd7dc50b60d53bdd236ecef971ebcdf767f9dbf4cd0bd241579b17774`; history `564e6d8b656893fa622ef273ce307800da68c06541e0224ddff33ee64fa87861`; tapes SHA256SUMS `5c992a7335848025db545b2489b87c4777c570aebf3f072185534a86ccaf4ee3`; excluded none.

## A_08-10..09-29 (variant print_d1): WORTH AN OWNER DECISION on a forward paper test (lower CI > 0; development evidence)

| row | $/day | 95% CI (date) | MDE80 | dates nonzero |
| --- | --- | --- | --- | --- |
| $25 primary (kept markets) | 0.37 | [0.12, 0.69] | 0.41 | 12/48 |
| $5 | 0.18 | [0.04, 0.40] | 0.25 | 12/48 |
| $25 | 0.37 | [0.12, 0.69] | 0.41 | 12/48 |
| $100 | 0.44 | [0.16, 0.79] | 0.44 | 12/48 |
| $25 expected-loss | 0.37 | [0.12, 0.69] | 0.41 | 12/48 |
| $25 PRIMARY5 | 0.37 | [0.12, 0.69] | 0.41 | 12/48 |
| $25 entry hour 13 | 0.05 | [0.01, 0.10] | 0.07 | 6/48 |
| $25 entry hour 14 | 0.16 | [0.02, 0.39] | 0.30 | 5/48 |
| $25 entry hour 15 | 0.01 | [0.00, 0.03] | 0.03 | 1/48 |
| $25 entry hour 16 | 0.15 | [0.00, 0.38] | 0.27 | 3/48 |
| $25 atlanta | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 austin | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 chicago | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 dallas | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 denver | 0.37 | [0.12, 0.69] | 0.41 | 12/48 |
| $25 houston | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 los-angeles | 0.00 | [0.00, 0.00] | 0.00 | 1/48 |
| $25 miami | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 nyc | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 san-francisco | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 seattle | 0.00 | [0.00, 0.00] | n/a | 0/48 |

## sensitivity_depth5_08-10..09-29 (variant print_d5)

| row | $/day | 95% CI (date) | MDE80 | dates nonzero |
| --- | --- | --- | --- | --- |
| $25 primary (kept markets) | 0.43 | [0.12, 0.82] | 0.50 | 12/48 |
| $5 | 0.18 | [0.04, 0.40] | 0.25 | 12/48 |
| $25 | 0.43 | [0.12, 0.82] | 0.50 | 12/48 |
| $100 | 0.68 | [0.23, 1.27] | 0.74 | 12/48 |
| $25 expected-loss | 0.43 | [0.12, 0.82] | 0.50 | 12/48 |
| $25 PRIMARY5 | 0.43 | [0.12, 0.82] | 0.50 | 12/48 |
| $25 entry hour 13 | 0.05 | [0.01, 0.10] | 0.07 | 6/48 |
| $25 entry hour 14 | 0.18 | [0.02, 0.48] | 0.39 | 5/48 |
| $25 entry hour 15 | 0.01 | [0.00, 0.03] | 0.03 | 1/48 |
| $25 entry hour 16 | 0.18 | [0.00, 0.44] | 0.28 | 3/48 |
| $25 atlanta | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 austin | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 chicago | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 dallas | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 denver | 0.43 | [0.12, 0.82] | 0.50 | 12/48 |
| $25 houston | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 los-angeles | 0.00 | [0.00, 0.00] | 0.00 | 1/48 |
| $25 miami | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 nyc | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 san-francisco | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 seattle | 0.00 | [0.00, 0.00] | n/a | 0/48 |

## sensitivity_book_only_08-10..09-29 (variant book_d1)

| row | $/day | 95% CI (date) | MDE80 | dates nonzero |
| --- | --- | --- | --- | --- |
| $25 primary (kept markets) | 3.94 | [1.49, 7.29] | 3.98 | 24/48 |
| $5 | 1.12 | [0.57, 1.81] | 0.89 | 24/48 |
| $25 | 3.94 | [1.49, 7.29] | 3.98 | 24/48 |
| $100 | 5.94 | [2.05, 11.44] | 6.62 | 24/48 |
| $25 expected-loss | 3.93 | [1.49, 7.28] | 3.98 | 24/48 |
| $25 PRIMARY5 | 3.27 | [1.02, 6.43] | 3.82 | 24/48 |
| $25 entry hour 13 | 0.41 | [0.18, 0.72] | 0.40 | 16/48 |
| $25 entry hour 14 | 1.31 | [0.38, 2.48] | 1.51 | 11/48 |
| $25 entry hour 15 | 0.78 | [0.06, 2.12] | 1.84 | 7/48 |
| $25 entry hour 16 | 1.44 | [0.03, 4.06] | 3.54 | 6/48 |
| $25 atlanta | 0.02 | [0.00, 0.05] | 0.05 | 1/48 |
| $25 austin | 0.04 | [0.00, 0.10] | 0.09 | 2/48 |
| $25 chicago | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 dallas | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 denver | 3.22 | [0.98, 6.37] | 3.83 | 23/48 |
| $25 houston | 0.43 | [0.00, 1.29] | 1.27 | 2/48 |
| $25 los-angeles | 0.02 | [0.00, 0.07] | 0.05 | 2/48 |
| $25 miami | 0.19 | [0.00, 0.56] | 0.56 | 1/48 |
| $25 nyc | 0.02 | [0.00, 0.06] | 0.04 | 2/48 |
| $25 san-francisco | 0.00 | [0.00, 0.00] | n/a | 0/48 |
| $25 seattle | 0.01 | [0.00, 0.03] | 0.03 | 1/48 |

## book_only_08-01..08-09_separate (variant book_d1)

| row | $/day | 95% CI (date) | MDE80 | dates nonzero |
| --- | --- | --- | --- | --- |
| $25 primary (kept markets) | 0.53 | [0.00, 1.20] | 0.90 | 3/9 |
| $5 | 0.11 | [0.00, 0.24] | 0.18 | 3/9 |
| $25 | 0.53 | [0.00, 1.20] | 0.90 | 3/9 |
| $100 | 1.04 | [0.00, 2.29] | 1.67 | 3/9 |
| $25 expected-loss | 0.53 | [0.00, 1.20] | 0.90 | 3/9 |
| $25 PRIMARY5 | 0.53 | [0.00, 1.20] | 0.90 | 3/9 |
| $25 entry hour 13 | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 entry hour 14 | 0.14 | [0.00, 0.42] | 0.42 | 1/9 |
| $25 entry hour 15 | 0.05 | [0.00, 0.15] | 0.15 | 1/9 |
| $25 entry hour 16 | 0.34 | [0.00, 1.01] | 1.01 | 1/9 |
| $25 atlanta | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 austin | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 chicago | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 dallas | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 denver | 0.53 | [0.00, 1.20] | 0.90 | 3/9 |
| $25 houston | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 los-angeles | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 miami | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 nyc | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 san-francisco | 0.00 | [0.00, 0.00] | n/a | 0/9 |
| $25 seattle | 0.00 | [0.00, 0.00] | n/a | 0/9 |

Summary: `{"status": {"no_capture": 2945, "no_value": 100, "traded": 61}, "traded_08_10_on": 57, "traded_with_prints_08_10_on": 17, "traded_on_days_without_trade_parts_08_10_on": 6, "filled_shares_print_d1_25": 255.09380783503454, "wanted_shares_25": 2003.824702228693, "traded_settled_yes": 0, "quote_source": {"no_ask": 61, "one_minus_yes_bid": 0}, "duration_min": {"n": 61, "median": 94.03326324999999, "p90": 230.0}, "market_days": {"scanned": 621, "no_dead": 5, "no_tape_folder": 0}, "scanned_days_without_trade_parts_08_10_on": 41}`

## Look-ahead audit (2026-10-25, master ruling)

**The ruling.** The floor used at a book row must be built from METAR rows received at or before that row's
capture time. This audit used the existing scan and stage-C outputs plus the layout snapshot fields. Nothing was
re-scanned and nothing was re-scored.

**How the code dates the floor.** `dead_bucket.first_dead` makes a bucket dead at the IEM `valid_utc` of the
first market-station METAR (role `market`, not COR) whose H exceeds the bucket edge, **plus an assumed 10 min**.

- Entry is that time plus 60 s, and the book row is the first capture at or after entry.
- Every trade's book row is therefore at or after the killing METAR's valid time plus 11 min.
  - Median lag: stage A 13-16 11.1 min, r3 early 11.3, r3 late 11.1, stage C 14.2.
- No row uses a METAR *observed* after the book timestamp. But the obs file holds no receipt time, so whether the
  METAR had actually been *received* by then rests on the 10-minute assumption alone.

**The served-floor test.**

- Proxy for receipt: the production floor (max of `guidance_physical_floor`, `high_so_far`,
  `trusted_current_max`) on the **latest layout snapshot captured at or before the book row**.
  - The latest snapshot is a median 5.0 min older than the book row, and at most 9.2 min older.

| run | trades | not yet dead on the served floor at or before the book row | $/day those carry |
| --- | --- | --- | --- |
| Stage A 13-16, 08-10..09-29 | 57 (61 incl. 08-01..08-09) | **41** (45 incl.) | **$0.366 of $0.372** ($25 print_d1); book_d1 $3.21 |
| r3 early | 9 | 6 | $0 (the reading was already zero) |
| r3 late | 2 (both before 08-10) | 2 | $0 |
| Stage C | 83 | 26 (the snapshot that priced the trade did not itself show the bucket dead) | not split (C is a non-executable bound) |

- Stage A, 57 primary trades: the served floor first killed the bucket a median **15.5 min** after the METAR's
  valid time (IQR 8.9-19.8, max 186).
- Only 16 trades, carrying **$0.005/day**, were dead on the served floor within 12 min of the valid time.

**Reading.**

- On this proxy, almost all of stage A's $0.37/day [0.12, 0.69] comes from book rows taken *before* the system
  showed the floor. It is consistent with the stage-C note that mispricing lasts about 10-15 min after the
  *assumed* availability: the market may simply be waiting for the same METAR.
- **The $0.37 is overstated. Treat it as an upper bound, not as development evidence of edge.**
- Its reading (lower CI > 0, "worth an owner decision on a forward paper test") is **suspended** until a
  no-look-ahead rescan.
- The r3 nulls stand and are firmer.

**Caveats.**

- The served floor is not L8's METAR-only floor.
- Its delay mixes METAR receipt with the production poll cadence, and layout snapshots are a few minutes apart.

**What an exact answer needs (not run).**

1. **A rescan of the replay inputs.** For each traded bucket, find the first captured snapshot whose own
   `sources.metar.data.rows` contain the killing METAR. That gives the received time.
2. **A rescan of the tapes.** Take the book row and the prints at that later entry.

Both are heavy. Neither has been run.

Script `C:\t\l11\audit\lookahead.py` (sha 431257da...); output `lookahead_out.txt` (sha 529d8d9e...).
