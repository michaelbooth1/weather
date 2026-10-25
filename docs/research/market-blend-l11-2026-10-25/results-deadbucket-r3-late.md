# Dead-bucket stage A, rule r3, late window (17:00-20:59 local): results

Development evidence only. Research only: no orders, no live-readiness work,
International venue only. Every tape, outcome and price read is dated on or
before 2026-09-29.

## Pins

| item | sha256 |
| --- | --- |
| rule r3 (`deadbucket_rule_r3.md`) | `1abd3f1a8a9c5e30213b87303cdc518932f2ab99020b6eabb5d7dcc42189ae94` |
| r3 history (`dead_bucket_history_r3.json`, control PASS) | `6d8660eeb7f0cf5fd9edf1eb87f003b327395cd543ea889c62fe86c91a4385b5` |
| tapes SHA256SUMS | `5c992a7335848025db545b2489b87c4777c570aebf3f072185534a86ccaf4ee3` |
| layout manifest | `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22` |
| late scan g1 / g2 / g3 | `5a4efcc5...0951` / `1d2c9e77...969e` / `8ca6257d...bd2` |
| late report JSON | `90cdf030ace9c17ad6442da0d8eeb36439e33c777363e77e0cc2086fa969cf3f` |
| report code | `d54b32dcfc68608d23ad343ef46b5bfebcbb55cbfb5bbb66794663e28d8c8cb2` |

The r3 history control reproduced r2's 13-16 rates exactly. At the late
window's decisive cutoff (20:59), no market reached the 2% exclusion bar, so
no market was excluded (the highest rate was Houston at 0.0033).

## Headline (primary window 08-10..09-29, print_d1)

**$25 primary: $0.00/day, 95% CI [0.00, 0.00], 0 of 48 dates nonzero.
Reading: NOT WORTH PURSUING.** The same holds for every variant (print_d5,
book_d1), every rung of the ladder ($5, $25, $100), expected loss, PRIMARY5,
every entry hour from 17 to 20, and every market. The bootstrap is degenerate
because every value is zero.

Book-only 08-01..08-09, reported separately and not part of the reading:
$25 $0.32/day [0.00, 0.90], 2 of 9 dates nonzero. Both dates are Denver, with
entry at hour 17.

## Mechanics

- Market-days: 621 scanned, 5 had no dead bucket, 0 had no tape folder.
- Dead-bucket outcomes: `no_capture` 3,087, `no_value` 30, `traded` 2. Both
  trades fall before 08-10, and neither settled YES.
- `no_capture` means the tape held no NO best ask and no YES bid for the dead
  bucket between entry and 20:59. By late afternoon the book has largely
  abandoned buckets that are already dead.
  - A spot count on two folders (Denver 09-16, Atlanta 08-20) found
    NO-ask rows at about 240 per hour from 18:00 onwards. Earlier in the day
    the count was about 400-860 per hour, while the total row count was
    unchanged.
  - This count was descriptive only. It was read after the report and did
    not change any rule.

## Process notes

- The report stage ran directly, not through `workstation_heavy.ps1`, under
  the coordinator's small-aggregation condition. It read only the three scan
  JSONs and the history JSON, never the tapes. It ran single-threaded and took
  1 s. The run is logged in `C:\t\l11\jobs\direct_runs.log`.
- The scans ran through the wrapper.
- The rule headers give pre-registration times of "about 04:35/04:55/05:05".
  Those were estimates written into the rules. The files were actually written
  around 04:30-04:40 on 2026-10-25. Each sha was recorded before any row in
  its window was read. The rule texts are unchanged.
- No re-tuning on 13-16. The early window (07:00-12:59, floor-killed only) is
  reported separately.
