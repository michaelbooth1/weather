# Rule L11-deadbucket r3 (lane L11, 2026-10-25): dead buckets at entry hours outside 13-16

Written 2026-10-25 (about 04:35 EDT), before any row of this check is read: no stage-A scan, history rate,
layout snapshot or tape row has been computed for the 17:00-20:59 or 07:00-12:59 windows. Research only: no
orders, no live-readiness work, International Polymarket venue only. Development window only (nothing dated
after 2026-09-29 is read; no 88a, panel or settlement data for 2026-09-30..10-15). Approved by master through
the coordinator ("item 2").

Base rule: r2, `C:\t\l11\deadbucket_rule_r2.md`, sha256 `177e9acfd7dc50b60d53bdd236ecef971ebcdf767f9dbf4cd0bd241579b17774`
(rule plus clarification 1). **Everything in r2 applies unchanged except the entry window, its end-of-window
quantities and the history cutoff that goes with them**, listed below. Code: `weather.calibration.dead_bucket`
on branch `claude/market-blend-l11-20261025`, a `--window` option added to the history, stage-a-scan and
stage-a-report phases; the 13-16 path is unchanged. Nothing below changes after this file's sha256 is recorded;
any change is a dated clarification written before the rows it affects.

The 13-16 result ($0.37/day [0.12, 0.69] at $25, report `4aa9bf7c…`) is known. It is not re-run, not
re-reported and not used to choose anything here: every constant below is r2's.

## Windows

| window | role | entry window (local) | dead by | running-max cutoff | history cutoff | entry hours |
| --- | --- | --- | --- | --- | --- | --- |
| late | **primary new reading** | 17:00-20:59 | 20:59 | 21 (rows at or before 21:00, and at or before `now`) | 20:59 | 17, 18, 19, 20 |
| early | secondary reading | 07:00-12:59 | 12:59 | 13 | 12:59 | 7, 8, 9, 10, 11, 12 |

For each window W = [start, end]:

- Dead bucket: an `lte` or `eq` bucket with upper edge `high` < H(end), H = floor(R + 0.5), R the METAR-only
  running max of r2 (L8's `running_max_since_midnight`, IEM obs `37d97195…`, `tgroup_f` else `tmpf`, COR dropped),
  with `cutoff_hour` as in the table (`now` always bounds it). Early: only buckets killed by this floor by 12:59
  count; nothing else (no forecast, no model) marks a bucket dead.
- First-dead = the first observation with H > `high`, plus 10 minutes (r2). Entry = max(first-dead + 60 s,
  start). A bucket dead before `start` enters at `start`.
- q*, fill (min of stake / q*, depth within 1%, prints in [entry, entry + 5 min] that a NO buy at q* or better
  could have taken), fee 0.05 q*(1 - q*), value >= 0.005, P&L, the $5 / $25 / $100 ladder: exactly r2
  clarification 1. "No capture" = no NO ask and no YES bid at any capture in [entry, end].
- Duration: from entry to the first capture whose NO value < 0.005 or with no ask, capped at `end`.
- Prints are read in [first entry of the day, end + 5 min].

## Malformed summary rows (declared)

A book-summary row whose field count differs from the header, or that has any field longer than 4,096
characters, is skipped and counted (`summary_bad_rows`), never used (code `e03639dcf`, as in the 13-16 run).

## History cutoff and exclusion (computed before any dev row of this check)

- The r2 history phase is re-run under this rule with two cutoffs added, 12:59 and 20:59 (same days kept as r2:
  WU `row_count` >= 20 and >= 12 METAR rows by 16:59; Aug-Sep 2021-2025).
- The decisive cutoff is the window's history cutoff (20:59 late, 12:59 early). **X = 2.0%** (r2): a market whose
  decisive day-level violation rate exceeds 2.0% is excluded from that window. The expected-loss variant uses
  that rate.

## Windows of dates and readings

- **Primary: 2026-08-10..09-29**, trade-print fills (`print_d1`), $25, $/day summed over the window's kept
  markets per date, mean over dates, date-clustered 95% CI (2,000 draws, seed 20260921). Book-only
  2026-08-01..08-09 reported separately, never pooled. Sensitivities as r2: depth within 5%, book-only on
  08-10..09-29.
- Secondary per window: per market, per entry hour (the table), the ladder, expected-loss, PRIMARY5, durations.
- **Reading (same thresholds as r2), per window: lower CI bound > 0 ⇒ worth an owner decision on a forward paper
  test; otherwise not worth pursuing.** The late window is the primary new reading; the early window is a
  secondary reading reported with the same threshold.
- Only the new windows are reported. Nothing is pooled with 13-16.

## (a) Positive control

The r3 history must reproduce r2's history rates at 13:00, 14:00, 15:00, 16:00 and 16:59 exactly, per market
(r2 history `564e6d8b…`: Houston 16:59 rate 0.0033, every other market 0.0, excluded set empty), before any
window row is computed. The stage-A fixture tests (13-16 path) must pass unchanged, plus fixtures for each new
window.

## (b) Comparator fairness

As r2: no comparator is traded; value is against $0, with the same METAR-only floor and rule-4 rounding in every
market and day, no calibration of the market price, the same fee, latency and sizes; labels are the WU
settlement proxy.

## (c) Targeted loss slice

No loss-atlas slice exists for dead buckets outside 13-16. The reference is r2's 13-16 slice (atlas
`535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4`, expected size 0.0224 in R, PRIMARY5
floor-only), stated for the record only; no threshold here depends on it.

## (d) MDE and clusters

Primary: 48 date clusters (the 08-10..09-29 dates present), up to 11 market clusters. MDE80 in $/day from the
date-clustered bootstrap (`dev_scorecard.mde80`), reported per window; the 13-16 primary's MDE80 was 0.41 for
reference.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: r2 counted 31 rows before it and added 1 K row (32). This check adds 1 K row (dead-bucket NO
taker, windows 17-21 and 07-13): K candidate 23 on 2026-07-31..09-29.
