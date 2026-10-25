# Rule L11-deadbucket r2-toronto (lane L11, 2026-10-25): the 13-16 dead-bucket check on Toronto, native Celsius

Written 2026-10-25 (about 05:05 EDT), before any Toronto tape row, any Toronto dev observation and any Toronto
history rate is read or computed. The Toronto tapes are not on this workstation yet (the coordinator will send
the verified local path); no Toronto dev METAR has been fetched. Research only: no orders, no live-readiness
work, International Polymarket venue only. Development window only (nothing dated after 2026-09-29 is read; no
88a, panel or settlement data for 2026-09-30..10-15). Approved by master through the coordinator ("item 1").

Base rule: r2, `C:\t\l11\deadbucket_rule_r2.md`, sha256
`177e9acfd7dc50b60d53bdd236ecef971ebcdf767f9dbf4cd0bd241579b17774` (rule plus clarification 1). **Everything in
r2 applies unchanged except the items below**, which make it native Celsius for one market. Code:
`weather.calibration.dead_bucket_toronto` on branch `claude/market-blend-l11-20261025`; the fill, fee, value,
latency, print-window, duration, ladder, bootstrap and reading are imported unchanged from
`weather.calibration.dead_bucket`. Nothing below changes after this file's sha256 is recorded; any change is a
dated clarification written before the rows it affects.

## Celsius specifics

- **Market:** toronto, station CYYZ, zone America/Toronto. One market; no excluded set beyond this market's own
  history test. PRIMARY5 does not apply.
- **Settlement proxy:** WU `data\wunderground\cyyz\daily\daily_summary.csv` `max_temp_native`, whole degrees
  Celsius (the file's `temperature_unit` must be `C` on every row read, else refused). There is no layout for
  Toronto, so the settled bucket is the one containing the WU whole-degree max: `lte X` settles YES when max <= X,
  `eq lo-hi` when lo <= max <= hi, `gte X` when max >= X.
- **METAR-only running max R(t):** IEM ASOS CYYZ, fetched by this module (`fetch` phase: `tmpc` and the raw METAR,
  report types 3 and 4, UTC windows 08-01T00Z..10-01T12Z of 2021-2025; the dev window 2026-07-30T00Z..
  2026-09-30T04Z (local midnight ending 09-29) is fetched only after the history file exists). Each observation's
  value is the METAR T-group in tenths of a degree C when the report carries one, else `tmpc`; COR reports
  dropped. R = L8's `running_max_since_midnight(..., unit="C", cutoff_hour=17)`; H = floor(R + 0.5) in C.
  - Fact recorded before writing (not a Toronto dev row): the local IEM CYYZ archive's Aug 2025 `tmpc` values
    are all whole degrees, and Canadian METARs normally carry no T-group. If the fetched reports carry no tenths,
    R is whole-degree and H = R. The fetched T-group share is reported; this rule does not switch to SWOB or any
    non-METAR source to obtain tenths.
- **Buckets:** each book-summary row's `range_label` is parsed with
  `weather.units.parse_temperature_band(label, expected_unit="C")` and must agree with `bin_kind`, `bin_value`,
  `bin_value_hi` (when given) and `unit` (`C`); a row that does not parse as Celsius or disagrees is skipped and
  counted (`label_mismatch`). Open-ended buckets: `X C or below` is `lte X` (upper edge X); `X C or higher` is
  `gte X` and is never dead. Dead: an `lte`/`eq` bucket with upper edge < H(16:59). No Fahrenheit value is formed.
- **Malformed rows (declared, as in the US run):** a summary row whose field count differs from the header or
  that has a field over 4,096 characters is skipped and counted (`bad`), never used.
- **Stage C is not run** for Toronto (it needs layout prices, which do not exist for Toronto).

## History and exclusion (before any dev row)

Aug-Sep 2021-2025, days kept when WU `row_count` >= 20 and >= 12 METAR rows are observed by 16:59 local; rates at
13:00, 14:00, 15:00, 16:00, 16:59 (decisive 16:59). **X = 2.0%**: if the 16:59 day-level violation rate (WU max <
H(16:59)) exceeds 2.0%, Toronto is EXCLUDED and stage A reports $0 by rule (the scan still runs for the record).
Causes as r2 section 2, with "tmpc only" in place of "tmpf only".

## Stage A (r2 clarification 1, unchanged)

- Entry window 13:00-16:59 local; entry = max(first-dead + 60 s, 13:00); first-dead = first observation with
  H > upper edge, plus 10 minutes. q* = NO best ask at the first capture >= entry, else 1 - YES best bid; value
  1 - q* - 0.05 q*(1 - q*) >= 0.005; filled = min(stake / q*, depth within 1%, prints in [entry, entry + 5 min]
  a NO buy at <= q* could have taken). Ladder $5 / $25 (primary) / $100; sensitivities depth within 5% and
  book-only.
- **Windows:** primary 2026-08-10..09-29 (the tape dates present); book-only 2026-08-01..08-09 reported
  separately, never pooled. The tapes' local path and SHA256SUMS sha256 are pinned in a dated clarification
  written before any tape row is read.
- **Reading (r2's): lower CI bound > 0 ⇒ worth an owner decision on a forward paper test; otherwise not worth
  pursuing.**

## (a) Positive control

The Toronto fixture tests must pass before any run: Celsius labels including the open-ended top and bottom, the
T-group comparison (24.6 C ⇒ H 25 kills the 24 C bucket and not the 25 C bucket), label mismatches skipped, and a
traded fixture bucket's P&L 0.6685 at $25 (7 shares at q* 0.90). The US r2 code path is unchanged (US stage-A
report `4aa9bf7cb7300e4b92b8e0b3fe4bb097271a68c4fc7672ae2c3b28db33246caa`).

## (b) Comparator fairness

As r2: nothing is traded as a comparator; value against $0, the same METAR-only floor and rule-4 rounding every
day, no calibration of the market price, the same fee, latency and sizes; labels are the WU settlement proxy the
market settles on.

## (c) Targeted loss slice

No Toronto loss atlas exists. Reference only: r2's 13-16 slice (atlas
`535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4`, 0.0224 in R, US PRIMARY5); no threshold here
depends on it.

## (d) MDE and clusters

Up to 51 date clusters in 08-10..09-29 (those with a Toronto tape folder) and 1 market cluster; MDE80 in $/day from
the date-clustered bootstrap is reported; the US 13-16 MDE80 was 0.41 for reference.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: 34 rows counted by this lane's rules so far (r2 32, r3 33, NBM 07-12 34). This check adds
1 K row (Toronto dead-bucket NO taker): K candidate 25 on 2026-07-31..09-29.
