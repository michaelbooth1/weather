# Dead-bucket stage A, rule r4 (capture-time dating), 13:00-16:59 local: results

Development evidence only. Research only: no orders, no live-readiness work, International venue only. Every
tape, replay snapshot, outcome and price read is dated on or before 2026-09-29. This result replaces the
suspended obs-dated stage-A reading (see the look-ahead audit in `results-deadbucket-stage-a.md`).

## Pins

| item | sha256 |
| --- | --- |
| rule r4 (`deadbucket_rule_r4.md`, prereg_check PASS, recorded 05:03:47 EDT before any row) | `fac8cd7211bb3c0e39edc8f95a7808c24fdf3a36558d9da5aab8462ff684a921` |
| r2 history (reused unchanged; excluded none) | `564e6d8b656893fa622ef273ce307800da68c06541e0224ddff33ee64fa87861` |
| replay inputs SHA256SUMS | `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` |
| tapes SHA256SUMS | `5c992a7335848025db545b2489b87c4777c570aebf3f072185534a86ccaf4ee3` |
| r4 scans g1 / g2 / g3 | `bca51bad...714a` / `9d1fe239...ed64` / `b093fd0b...fa38` |
| r4 report JSON | `4ddf4d58399e66da3f25bea7791356689f229b1ef4b3d8d9140d4184f8a30c0f` |
| code (branch tip at the scans) | `e6cc2951d` |

## Headline (primary window 08-10..09-29, print_d1)

**$25 primary: $0.03/day, 95% CI [0.00, 0.09], MDE80 0.06. There are 21 trades, 3 of 48 dates are nonzero,
and only 6 trades had a qualifying print. Reading: NOT WORTH PURSUING (lower CI <= 0).**

The obs-dated stage A gave $0.37/day [0.12, 0.69] on 57 trades. Under capture-time dating that falls to $0.03
on 21 trades.

Other rows:

- The ladder: $5 $0.01, $100 $0.11 [0.00, 0.27].
- The depth-within-5% sensitivity: $0.04 [0.00, 0.09].
- Per market: Denver $0.02 on 2 dates, and Los Angeles, Miami and NYC on 1 date each. Every other market is
  zero.

Book-only sensitivity, 08-10..09-29 (not the reading): $1.01/day [0.02, 2.64]. That is 5 dates, and $0.96
comes from entry hour 13 (Houston $0.43 and Miami $0.43). It assumes fills that no trade print corroborates.
The print-capped primary is the r2 metric.

Book-only 08-01..08-09, reported separately: zero.

## Controls

- **Sanity (rule (a)2): PASS.** Of the 3,098 buckets dead under both datings, 3,011 (0.972, against a minimum
  of 0.95) have an r4 receipt at or after the killing IEM observation. The other 87 differ in the floor data
  (captured rows against IEM).
- The r2 history was reused at its pinned sha, with an empty excluded set.
- The fixture tests passed before the run: 19 in `tests/calibration/test_dead_bucket.py`, including 3 for r4.

## What changed and why (descriptive)

- **Receipt minus observation, all 3,098 dead buckets:** median 3.8 min (p10 2.8, p90 11.0).
  - For most buckets, the snapshot that killed it was captured faster than the +10 min that r2 assumed.
  - Most of these buckets died before 13:00, so their entry is 13:00 under both datings. Across all of them
    the median entry difference is 0, and only 4.2% enter later under r4.
- **The 57 obs-dated stage-A trades are exactly the late-receipt tail.**
  - Under r4 their entry is a median 5.0 min later (p10 -5.9, p90 +19.8).
  - 26 of them have no capture by the end of the window, 14 have no value at the later entry, and 17 still
    trade.
  - r4 adds 4 trades that stage A did not have.
  - This confirms the audit: the obs-dated $0.37 came from book rows read before the system had received the
    killing METAR.
- **Production floor:** on all 21 r4 trades, the layout's served floor kills the bucket in the same snapshot
  as the r4 receipt (delay median 0.0 min).
- **Other counts:**
  - Buckets dead under capture dating only: 10. Dead under obs dating only: 8.
  - Non-monotone snapshot-floor steps: 323. Under the rule, the first kill counts.
  - Malformed replay lines: 1, skipped.
  - Market-days: 621 scanned, 5 with no dead bucket, 0 without a replay folder.
  - Bucket outcomes: `no_capture` 2,942, `no_value` 145, `traded` 21. None of the traded buckets settled YES.

## Process notes

- The scans ran through `workstation_heavy.ps1` with OMP/MKL/OPENBLAS=10 and `-MinAvailableMemoryGB 2`, after
  `C:\t\PREGATE_HOLD` cleared at 05:11:30.
- The report and the per-bucket comparison ran directly under the small-aggregation condition. They read only
  the scan JSONs and the history JSON, single-threaded, and are logged in `C:\t\l11\jobs\direct_runs.log`.
- Nothing dated after 2026-09-29 was read. No 88a, panel or settlement data for 09-30..10-15 was read. There
  is no oracle.
