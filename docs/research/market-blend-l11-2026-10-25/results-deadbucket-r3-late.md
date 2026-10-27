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
