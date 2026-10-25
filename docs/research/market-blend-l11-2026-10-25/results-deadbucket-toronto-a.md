# Results: Toronto dead buckets, stage A under rule r4-toronto (lane L11, 2026-10-25)

**Evidence class.** Development window only (2026-08-01..09-29). Research only: no orders, International
Polymarket venue only. Nothing dated after 2026-09-29 was read, and no 88a, panel or settlement data for
2026-09-30..10-15 was read. No oracle.

**Headline.** Primary $/day = **0.00, 95% CI [0.00, 0.00]**, with **0 trades**. The parse check **PASS**ed,
and controls (a)2-4 passed. Under the rule the reading is **NOT WORTH PURSUING**. However, the primary window
is **mostly unlabelled**: the pinned WU CYYZ daily summary ends at 2026-08-10, so 50 of the 51 primary dates
are `no_wu_label` and contribute nothing. The primary has therefore not measured 08-11..09-29 at all. What was
measured is the following: on the 9 labelled days, none of the 46 dead buckets ever showed a NO ask after
entry.

## Pins

| Item | sha256 |
| --- | --- |
| Rule r4-toronto (`deadbucket_rule_r4_toronto.md`, in this folder) | `12902246a5358df5a2926314465e61dd4d1afaeedd408b994706e5b773c9f061` |
| Base rule r4 | `fac8cd7211bb3c0e39edc8f95a7808c24fdf3a36558d9da5aab8462ff684a921` |
| Base rule r2-toronto | `c754ddab8ed3634c0854444dded9d4831bf4ff955b5efd944fc54f582246ef3d` |
| History `toronto_history.json` (r2-toronto) | `3a652c232d388a83e41a1d67effa9f10b11293995bd751f1a142e04d777b7c9d` |
| Toronto tapes SHA256SUMS (CRLF, as delivered) | `a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0` |
| Replay inputs SHA256SUMS | `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` |
| IEM CYYZ dev observations (`toronto_obs.parquet`, 9,977 rows) | `bb85d7a554cca7803e542e60ba6c02125d75f888a2f589198e0eec33c7c0798f` |
| Scan `toronto_stage_a_r4_scan.json` | `fece5da8588554bca9ed20f59e7bf82c5a2caa0a81e93bf1b1bfe6435e7469d6` |
| Report `toronto_stage_a_r4.json` | `e4ca09e4ae966804d1ebc9d146152be817ddcd24c26b44fb5fd334faa4307a30` |

**Code.** `weather.calibration.dead_bucket_toronto` at `bcb0ad945` on `claude/market-blend-l11-20261025`.

**Runs:**

- The scan went through `workstation_heavy.ps1 -Queue` with OMP/MKL/OPENBLAS=10 and `-MinAvailableMemoryGB 2`.
  It ran at 13:29 EDT, after the PREGATE_HOLD cleared, and took 10 s.
- The report ran directly, single-threaded, and is logged in `C:\t\l11\jobs\direct_runs.log`. It reads the
  scan only.

## Parse check (Celsius, native)

- **Labels:** 23 distinct labels parsed to whole-°C ranges, including the open bottom (`X C or below`) and
  open top (`X C or higher`) buckets.
- **Failures:** 0 distinct failures and 0 label-mismatch rows across 741,994 summary rows in the windows read.
  Nothing was coerced, and no Fahrenheit value was formed.
- **Partitions:** every scanned day's parsed bucket set is a contiguous partition of the integers.
- **Verdict: PASS.**
- **Scope.** The check covers the summary rows of the 13:00-16:59 window that the scan reads, on the
  9 labelled days only. Days without a WU label are skipped before their books are opened.

## Controls

| Control | Result |
| --- | --- |
| (a)1 fixtures | 26 of 26 focused tests pass: °C labels with open ends, a °F label refused and listed, °C floor, Toronto capture dating |
| (a)2 receipt at or after the observation | 46 of 46 buckets dead under both datings (share 1.00 against a minimum of 0.95). PASS |
| (a)3 Celsius sanity | Last snapshot H_s at 16:59 is within 1 °C of the IEM H on 9 of 9 days, with a maximum absolute difference of 0 °C. PASS |
| (a)4 history | Pinned file, 16:59 rate 0.0. PASS |

Capture receipt minus the killing IEM observation time: median 9.1 min (p10 7.9, p90 15.9; n = 46). That is
about 1 minute earlier than r2's obs + 10 min dating at the median.

Other counts:

- dead under capture dating only: 0;
- dead under obs dating only: 0;
- non-monotone snapshot steps: 17;
- bad replay lines: 0.

## Results

| Row | $/day (95% CI) | Dates |
| --- | --- | --- |
| Primary, `print_d1` at $25, 08-10..09-29 | 0.00 [0.00, 0.00] | 51, of which 50 have no WU label |
| Book-only 08-01..08-09 (separate) | 0.00 [0.00, 0.00] | 9, of which 8 are labelled |
| Sensitivity: book-only 08-10..09-29 | 0.00 [0.00, 0.00] | 51 |
| Ladder $5 / $25 / $100, per hour 13-16, expected-loss | all 0.00 | |

**Market-days:** 60 in total, 9 scanned, 51 `no_wu_label`, 0 `no_replay`.

**Buckets:** 46 dead, all `no_capture`, so trades = 0.

## Reading

1. **By the rule: NOT WORTH PURSUING** (the lower CI bound is not above 0). The controls pass, so the result
   is interpretable as far as it goes.
2. **The settlement-proxy gap.** The local `data/wunderground/cyyz/daily/daily_summary.csv` (file modified
   2026-08-12) has no rows after 2026-08-10. The r4-toronto rule pins that file and counts unlabelled days as
   contributing 0, so the primary's zero over 08-11..09-29 is missing data, not a measured null. The MDE could
   not be computed (degenerate bootstrap).
3. **Why the labelled days pay nothing.** On all 46 dead buckets of 08-01..08-10, the NO side had no ask at
   any snapshot from entry to 16:59. Its best bid was 0.999 throughout, so there was nothing to buy.
   - Where a NO ask existed before death, it was at 0.999. That is value 0.001, below the 0.005 minimum.
   - Toronto's dead buckets are priced out before r4's capture-dated death, as in the US late-receipt
     finding.
   - The descriptive check is `C:\t\l11\audit\tor_noask.py` (sha256
     `7426be51aa2f92675f3cd709ec95ad9ea9ae302f7ab3f06c81cd361b582cd7ba`). Its output is `tor_noask_out.txt`
     (sha256 `95f0b810de98fd9bfabf74778a4047da6f16fcd4809634ec2f26a5c196feff45`).
4. **What would close the gap.** Either a WU CYYZ daily summary for 08-11..09-29 (built only from rows dated
   on or before 09-29), or a dated clarification that measures tradability without labels. Tradability needs
   no label, since a bucket with no NO ask pays $0 whichever way it settles. Neither was done here, because
   both need an owner or master decision.

## Dev-window ledger

The r4-toronto K row is K candidate 25 on 2026-07-31..09-29, and it is the first Toronto row. The value is
0.00 [0.00, 0.00], with 50 of 51 primary dates unlabelled.
