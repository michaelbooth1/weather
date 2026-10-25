# Dead-bucket stage A, rule r3, early window (07:00-12:59 local, floor-killed buckets only): results

Development evidence only. Research only: no orders, no live-readiness work,
International venue only. Every tape, outcome and price read is dated on or
before 2026-09-29. This window is secondary under r3, and the reading below
does not re-tune anything on 13-16.

## Pins

| item | sha256 |
| --- | --- |
| rule r3 | `1abd3f1a8a9c5e30213b87303cdc518932f2ab99020b6eabb5d7dcc42189ae94` |
| r3 history (control PASS; 12:59 cutoff excluded no market) | `6d8660eeb7f0cf5fd9edf1eb87f003b327395cd543ea889c62fe86c91a4385b5` |
| tapes SHA256SUMS | `5c992a7335848025db545b2489b87c4777c570aebf3f072185534a86ccaf4ee3` |
| early scan g1 / g2 / g3 | `84dce4fb...0a48` / `9c428fe2...968b` / `6f4fbf9d...ebc6ede` |
| early report JSON | `5ec4a92e225bb2cd87d6a313e2f10f6742c2b2c5b5359eb5ec2a021a604e1d53` |

## Headline (primary window 08-10..09-29, print_d1)

**$25 primary: $0.00/day, 95% CI [0.00, 0.00], 0 of 48 dates nonzero.
Reading: NOT WORTH PURSUING.** Every rung, every market and the print_d5
sensitivity are also zero.

The rule passed 9 entries in 08-10..09-29, but none of them had a qualifying
trade print within [entry, entry + 5 min]. The print-capped fill is therefore
0 of the 237 shares wanted at $25.

## Sensitivity (not the reading)

The book_d1 variant (book depth only, ignoring prints) for 08-10..09-29:

- $25: $0.22/day [0.01, 0.60], 6 of 48 dates nonzero.
- $100: $0.79 [0.04, 2.22].
- PRIMARY5: $0.03 [0.01, 0.07].
- By market: Denver 6 dates ($0.03), Los Angeles 1 date ($0.17), San Francisco
  1 date ($0.01).
- By entry hour: mostly hour 12.

The lower bound is above zero only because the counterfactual assumes fills
that no trade print corroborates. It is also economically negligible, so it
does not change the reading.

Book-only 08-01..08-09, reported separately: zero.

## Mechanics

- Market-days: 574 scanned, 52 had no floor-killed bucket, 0 had no tape folder.
- Dead-bucket outcomes: `no_capture` 2,123, `no_value` 45, `traded` 9.
  - None of the traded buckets settled YES.
  - All 9 quotes came from the NO best ask.
  - Median time from first-dead to entry capture is 50 min (p90 145 min).

## Process notes

- The scans ran through the wrapper and were admitted before
  `C:\t\PREGATE_HOLD` appeared at 04:49:15.
- The report stage ran directly under the coordinator's small-aggregation
  condition. It read only the three scan JSONs and the history JSON, never the
  tapes, and ran single-threaded. The run is logged in
  `C:\t\l11\jobs\direct_runs.log`.
- The pre-registration times in the rule headers were estimates; see
  `results-deadbucket-r3-late.md`.
