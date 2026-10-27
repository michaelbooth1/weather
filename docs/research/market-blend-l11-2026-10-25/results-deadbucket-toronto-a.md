# Results: Toronto dead buckets, stage A under rule r4-toronto (lane L11, 2026-10-25)

**Evidence class.** Development window only (2026-08-01..09-29). Research only: no orders, International
Polymarket venue only. Nothing dated after 2026-09-29 was read, and no 88a, panel or settlement data for
2026-09-30..10-15 was read. No oracle.

**Headline, run 2.** This is the run of record: the labels are complete and Clarification 1 applies.

- **Primary.** `print_d1` at $25 over 08-10..09-29 gives **0.00 $/day, 95% CI [0.00, 0.00]**, from **0 trades
  filled**.
  - Two buckets reached `traded` on the book, but neither had a matching print in the fill window.
  - All 51 primary dates are labelled. The MDE80 was not computed, because the bootstrap was degenerate
    (every date is 0).
- **Parse check: PASS.** All 59 labelled days, plus the one unlabelled day, were checked:
  - 51 distinct °C labels parsed;
  - 0 failures and 0 label mismatches across 4,931,168 summary rows;
  - every day is a contiguous partition.
- **Controls:** all pass.
- **Reading: NOT WORTH PURSUING.**
- **Label-free measure (Clarification 1, descriptive only):** of 312 capture-dated dead buckets, **2** ever
  had a NO ask with value >= 0.005 between entry and 16:59. Their fillable size was 5 and 171.54 shares,
  176.54 shares in all.

## Pins

| Item | sha256 |
| --- | --- |
| Rule r4-toronto as registered (original) | `12902246a5358df5a2926314465e61dd4d1afaeedd408b994706e5b773c9f061` |
| Rule doc with dated Clarification 1 (`deadbucket_rule_r4_toronto.md`, in this folder) | `46c48626a1204e274e0fb9fa6951b71b587e39310a0f37e41b2d50172c0738bd` |
| Base rules r4 / r2-toronto | `fac8cd72...` / `c754ddab8ed3634c0854444dded9d4831bf4ff955b5efd944fc54f582246ef3d` |
| History `toronto_history.json` | `3a652c232d388a83e41a1d67effa9f10b11293995bd751f1a142e04d777b7c9d` |
| Toronto tapes SHA256SUMS | `a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0` |
| Replay inputs SHA256SUMS | `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` |
| IEM CYYZ dev obs | `bb85d7a554cca7803e542e60ba6c02125d75f888a2f589198e0eec33c7c0798f` |
| WU input 1, pinned `data/wunderground/cyyz/daily/daily_summary.csv` (rows end 08-10) | `1ced925a605b6f4e82fa20cbe238b9c91d841a9390da604bc648b630dac920e1` |
| WU input 2, appended `data/inbox/wu-cyyz-0811-0929/daily_summary_cyyz_0811_0929.csv` (50 rows, 08-11..09-29) | `c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a` |
| Run 2 scan `toronto_a_c1/toronto_stage_a_r4_scan.json` | `02fa8c7a28bbb02d92b7dc231cabeb2f9cce6a9068105cef7f9860c3a268a586` |
| Run 2 report `toronto_a_c1/toronto_stage_a_r4.json` | `3baf8558657e85f68d966bea6daa720fb2f53ebb6a09a23772fe93ba26f32a89` |
| Run 1 scan / report (pinned WU only; superseded) | `fece5da8...` / `e4ca09e4ae966804d1ebc9d146152be817ddcd24c26b44fb5fd334faa4307a30` |

**Code.** `weather.calibration.dead_bucket_toronto` at `b0447d13d` on `claude/market-blend-l11-20261025`.

**How the WU inputs are loaded.** The appended input is read as a separate file and the pinned file is not
edited. The load fails closed on any of these:

- a sha mismatch;
- a header mismatch;
- any date after 09-29;
- a duplicate `local_date`, within the appended file or against the pinned rows;
- a non-C unit.

Both shas are recorded in the scan's `wu_inputs`.

**Runs:**

- The scan went through `workstation_heavy.ps1 -Queue` with OMP/MKL/OPENBLAS=10 and `-MinAvailableMemoryGB 2`.
  It ran at 13:35 EDT, after a hold check, and took 55 s.
- The report ran directly, single-threaded, and is logged in `C:\t\l11\jobs\direct_runs.log`.

**What run 1 showed.** It used only the pinned WU file. 50 of its 51 primary dates were `no_wu_label`, so its
zero was missing data. Run 2 replaces it.

## Parse check (Celsius, native)

- **Days:** 59 labelled and 1 unlabelled (08-08). Clarification 1 now reads the books of unlabelled days for
  the label-free measure only.
- **Labels:** 51 distinct labels parsed to whole-°C ranges, including open bottom and top buckets.
- **Failures:** 0 distinct failures and 0 label mismatches. Nothing was coerced, and no °F value was formed.
- **Partitions:** no day fails to be a contiguous partition.
- **Malformed rows:** 1, on 09-03, handled as in r3.
- **Verdict: PASS.**

## Controls

| Control | Result |
| --- | --- |
| (a)1 fixtures | 27 of 27 focused tests pass, including the appended WU input failing closed and the label-free measure |
| (a)2 receipt at or after the observation | 306 of 306 buckets dead under both datings (share 1.00 against a minimum of 0.95). PASS |
| (a)3 Celsius sanity | Last H_s within 1 °C of the IEM H at 16:59 on 60 of 60 days, maximum absolute difference 1 °C. PASS |
| (a)4 history | Pinned file, 16:59 rate 0.0. PASS |

Capture receipt minus the killing observation: median 8.5 min (p10 7.6, p90 10.3; n = 306).

Other counts:

- dead under obs dating only: 1;
- dead under capture dating only: 0;
- non-monotone steps: 49;
- bad replay lines: 0.

## Results (run 2)

| Row | $/day (95% CI) | Nonzero dates / dates | MDE80 |
| --- | --- | --- | --- |
| **Primary**, `print_d1` at $25, 08-10..09-29 | **0.00 [0.00, 0.00]** | 0 / 51 | n/a (degenerate) |
| Sensitivity: depth within 5% | 0.00 [0.00, 0.00] | 0 / 51 | n/a |
| Sensitivity: book-only, 08-10..09-29 | 0.041 [0.00, 0.118] | 2 / 51 | 0.108 |
| Book-only 08-01..08-09 (separate, never pooled) | 0.00 [0.00, 0.00] | 0 / 9 | n/a |
| Ladder $5 / $25 / $100, per hour 13-16, expected-loss | all 0.00 [0.00, 0.00] | | |

**Market-days:** 60 in total, 59 scanned, 1 `no_wu_label` (08-08), 0 `no_replay`.

**Dead buckets on labelled days:** 306.

| Status | Buckets |
| --- | --- |
| `no_capture` (no NO ask and no YES bid from entry onward) | 302 |
| `no_value` (NO ask 0.999) | 2 |
| `traded` | 2 |

**Trades:** 2 on the book, 0 with prints, and 0 settled YES.

The two book trades:

| Date and bucket | First NO ask | Depth within 1% | Book-only $25 P&L |
| --- | --- | --- | --- |
| 09-03, 28 °C | 0.62 at 14:11 | 5 shares | +1.84 |
| 09-19, 16 °C | 0.99 at 13:10 | 171.54 shares | +0.24 |

Neither bucket printed in [entry, entry + 5 min], so `print_d1` fills nothing.

## Label-free tradability (Clarification 1; descriptive, secondary, not part of the primary or the reading)

| Measure | Count |
| --- | --- |
| Capture-dated dead buckets (306 on labelled days, 6 on 08-08) | 312 |
| With any NO ask of value >= 0.005 between entry and 16:59 | 2 (first entry hour 13: 1, 14: 1) |
| Fillable size, first qualifying `ask_depth_1pct`, summed | 176.54 shares |
| Fillable size, maximum `ask_depth_1pct`, summed | 176.54 shares |

The two buckets are the same two as the book trades above.

- **09-03, 28 °C:** a 5-share NO ask at 0.62 that sat for 211 snapshots.
- **09-19, 16 °C:** 171.54 shares at 0.99, whose value is 0.0095, over 110 snapshots.

None of the 6 dead buckets on the unlabelled day had a qualifying ask.

## Reading

1. **By the registered rule: NOT WORTH PURSUING.** The primary is 0.00 with a degenerate CI over 51 fully
   labelled dates, the controls pass, and the result is interpretable.
2. **Why it is zero.** Toronto's dead buckets are priced out before the capture-dated death. 302 of 306 have
   no NO ask (NO bid 0.999) from entry to 16:59.
   - Only 2 of 312 dead buckets ever offered value.
   - Their combined size, about 177 shares, would be worth about $2 over 51 days even on book fills, and
     neither printed.
   - This matches the US r4 finding that the obs-dated edge came from the late-receipt tail.
3. **The book-only sensitivity is not a signal.** Its 0.041 $/day comes from 2 dates, and one of them is a
   stale 5-share ask. Its lower bound is 0.00.

## Dev-window ledger

The r4-toronto K row is K candidate 25 on 2026-07-31..09-29, and it is the first Toronto row. The value is
0.00 [0.00, 0.00], from 0 trades. Clarification 1 adds no K row, because its measure is descriptive.
