# R-PIT-T5: PIT/leakage refutation of T5 (t5-r1, NBH latest cycle, max over remaining hours), development only

**Verdict: NOT DISQUALIFIED on PIT/leakage. Every claimed LEAD block passes this lens and survives +1 h and +2 h.
The 17-23 effect is not NBH skill, though.** It is the floor-collapse mechanism (the T1/T2 decided-band family):
a pure floor-collapse candidate that uses no NBH information scores the same or slightly better on the same rows.
The 00-16 claim, which is the one that matters to the maker, has no PIT defect. It is fragile on the market-sign
condition (8/11 in 00-05 and 00-16).

HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74 (recomputed, matches HARNESS.md).
Candidate code tools/research/model_parity/t5_nbh_latest.py sha256 bd97821b...c71d (matches T5 result.json).
I imported it unchanged. My code is tools/research/model_parity/r-pit-t5_shift.py (sha256 8d6b24f3...890a), plus
the scratch checks C:\swarm\out\refute-pit-t5\check_avail.py and reparse.py.
I registered no new rules. Rows after 2026-09-29: 0.

## Per-block judgement (t5-r1, from stratum, all rows, candidate minus served)

| block | +0 (reproduced) | +60 min | +120 min | mkts neg +0/+60/+120 | PIT verdict |
|---|---|---|---|---|---|
| 00-05 | -0.007261 [-0.014025,-0.000614] LEAD | -0.006361 [-0.012325,-0.000591] LEAD | -0.005238 [-0.010194,-0.000417] LEAD | 8/8/8 | stands (sign fragile, 8/11) |
| 06-09 | -0.008368 [-0.014926,-0.001455] LEAD | -0.008176 [-0.014362,-0.001589] LEAD | -0.007858 [-0.013796,-0.001545] LEAD | 9/9/9 | stands |
| 10-12 | -0.002876 [-0.010352,+0.005312] WEAK | -0.002916 WEAK | -0.003229 WEAK | 7/7/8 | not a LEAD (unchanged) |
| 13-16 | -0.009706 [-0.019511,-0.000989] LEAD | -0.009578 [-0.019444,-0.000833] LEAD | -0.009469 [-0.019397,-0.000584] LEAD | 9/9/9 | stands (upper CI close to 0) |
| 17-23 | -0.028234 [-0.039969,-0.018806] LEAD | -0.028227 LEAD | -0.028210 LEAD | 11/11/11 | PIT-clean, but NOT attributable to NBH (see below) |
| 00-16 | -0.007295 [-0.013586,-0.000908] LEAD | -0.006905 [-0.012873,-0.000848] LEAD | -0.006466 [-0.012023,-0.000840] LEAD | 8/8/8 | stands (sign fragile, 8/11) |

The +0 run reproduces the hunter's numbers exactly. Shifting availability attenuates the effect only mildly, and
mostly in 00-05: there the 07Z/12Z cycles and the 00Z cycle have long lags, so +2 h pushes 00-05 back to older
cycles. No class changes. The median latest-cycle age is 1.2-1.4 h at +0, 2.2-2.4 h at +60 and 3.3 h at +120.
The shift lowers coverage from 109,399 to 106,079 (+60) and 101,957 (+120) snapshots, because the latest cycle
no longer reaches local midnight. Those rows fall back to served in the all-row estimand.

## Availability re-derived from primary sources (rule 1)

- The only external input to t5-r1 is NBH TMP/TSD (C:\swarm\data\nbh\nbh_tidy.parquet, sha256 0124b674...d971,
  which matches the MANIFEST).
- available_utc equals the per-object S3 LastModified for all 1,608 cycles (0 mismatches against the manifest).
  available_utc is never earlier than cycle_utc. Measured lag: min 35.3 min, median 41.9 min, p99 136 min,
  max 857 min. Late or re-uploaded objects are kept at their measured (later) time, which is conservative.
- Live S3 HEAD on 24 random objects: Last-Modified and ETag match the manifest in 24/24.
- Re-downloaded blend.20260910/14/text/blend_nbhtx.t14z: the sha256 matches the manifest. The KLGA block header
  reads "9/10/2026 1400 UTC", and all 25 TMP values with their valid hours (15Z..15Z next day, fhr 1-25) match the
  tidy parquet exactly. Valid times are therefore parsed correctly, including the day rollover. The content comes
  from the object whose LastModified gates it. The raw object was held in memory only and never saved.
- valid_utc - cycle_utc == fhr for every row. NBH cycles run 2026-07-25 00Z..2026-09-29 23Z. No forecast issued
  on or after 09-30 exists in the input.
- Code: StationIndex.remaining keeps only cycles with avail <= t, including the fallback cycles. It uses only
  valid hours strictly after t, up to local midnight ending D. h.assert_point_in_time runs on every covered
  snapshot's latest cycle.
- IEM and Open-Meteo feed lags do not apply to t5-r1. It uses no METAR, MOS or Open-Meteo input. METAR appears
  only in the t5-r2 history fit, which is restricted to local dates <= 07-31 and is not the candidate under test.

## Rules 2-5 and 8 checked in code

- Rule 2 (no market input): inputs come from h.candidate_inputs(), whose allow-list excludes
  p_market_yes/bid/ask/mid and raises on forbidden columns. t5 reads only station, captured_at_utc/local, date,
  floor, n_bands, local_hour, and kind/low/high from the bands table.
- Rule 3 (no settlement leakage): no winner, settlement_high or is_winner is read; the allow-list blocks them.
  t5-r1 has zero fitted parameters. The harness leakage tripwire fired in no group, in any run.
- Rule 4 (floor): score() always applies the floor mask, and unfloored=True is never passed. The candidate
  additionally takes H = max(round(floor), X), which only strengthens the floor.
- Rule 5 (dates): asserts date <= 2026-09-29, and the harness reports 0 rows after that date. Nothing from
  maker_evidence, exam roots or the sealed panel is opened.
- Rule 8 (no hour gate): t5-r1 applies at every local hour with no where= gate. Block labels are used only for
  reporting.

## Is the 17-23 effect the remaining-rise family in disguise? Yes.

- In 17-23 the NBH remaining-hours max lies below the floor bucket in 97.5% of covered snapshots, and more than
  2 F below it in 91.9%. So t5-r1 almost always puts nearly all its mass on the floor band.
- I ran a labelled diagnostic, not a rule: pure floor collapse (probability 1 on the floor band), using no NBH
  information, on the same 31,935 covered 17-23 snapshots. It gives -0.028699 [-0.040428, -0.019371]
  (before -0.032849), 11/11 markets. On the same rows t5-r1 gives -0.028234 [-0.039969, -0.018806]
  (before -0.032000).
- NBH therefore adds nothing in 17-23: it is +0.0005 worse than collapsing with no forecast at all. The 17-23 LEAD
  belongs to the T1/T2 decided-band family and must not be counted as an independent NBH lead, or double-counted
  with T1/T2 in the synthesis.
- This is not leakage. The floor is captured at t.

For contrast, mu < floor in 1.4% (00-05), 0.8% (06-09), 8.9% (10-12) and 49.8% (13-16) of covered snapshots.
00-09 is genuine guidance replacement. Half of 13-16 is collapse, so part of the 13-16 LEAD (-0.0097) is probably
the same mechanism. Splitting it out is a statistics or deep-dive question; this PIT lens does not test it.

## Defects found (none disqualifying on PIT)

1. 17-23 attribution: the effect is floor collapse, not NBH skill. NBH adds +0.0005 against pure collapse.
2. 13-16 is about 50% collapse rows. The NBH-specific share of the 13-16 LEAD is unmeasured.
3. 00-05 and 00-16 meet the market condition only at its edge (8/11), at +0, +60 and +120 alike. Under +120 the
   00-05 estimate falls to -0.0052. It passes only through the 5%-of-gap bar (needs <= -0.00122); the -0.0133
   line is not reached in any 00-16 block.
4. Serving would need new capture. NBH is not captured in production, and the S3 lag (median 42 min, 00Z about
   77 min, 12Z about 95 min) has to be honoured at serve time.

## Files

- C:\swarm\out\refute-pit-t5\rpit_t5_r1_plus{0,60,120}.score.json
- rpit_t5_diag_collapse_1723.score.json
- rpit_t5_r1_only_1723_samerows.score.json
- rpit_t5_r1_only_0016.score.json
- rpit_t5_results.json
- check_avail.py, reparse.py, klga_block.txt

All numbers are development reads on a previously inspected from stratum.

Note: a tool guard blocked writing report.md and the repo copy refute-pit-t5.md; this text is the full report.

