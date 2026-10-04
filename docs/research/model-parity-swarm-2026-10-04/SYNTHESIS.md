# Model-parity swarm v2: synthesis (DEVELOPMENT ONLY)

> **Every number in this document is a development read.** The from stratum (2026-08-23..09-29) had already been
> read by 79a, 81a and 111h, so it is not a holdout and nothing here is evidence or confirmation (DESIGN rule 7).
> The table is production's 111h Part-1 extract: 110,807 snapshots, 626 market-days, 57 dates, 11 US markets,
> targets 2026-08-01..09-29. HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74` on
> every score cited here. Rows with a target after 2026-09-29: 0. Leakage-suspect groups: none, in any score.
> Unless stated otherwise, figures are from stratum, all rows with served fallback (the primary estimand), with 95% W
> intervals (crossed date x market bootstrap, 2,000 draws). "b" is the before-stratum estimate (08-01..08-22).
> Every fix below is a **PROPOSAL for an owner decision**. No serving, config, capture or reservation change was made.
>
> Written by S-SYNTH on 2026-10-04, about 03:15-03:45 local, on the workstation. It reads every report under
> `C:\swarm\out\` (result.json `report_md` where report.md was blocked), the docs in this directory, the registry,
> PREFLIGHT.md and HARNESS.md. Where this synthesis computed a number itself, it read the agents' stored score
> files through `harness.table_lookup` and re-derived nothing.
> Revised by S-REVISE on 2026-10-04, about 03:50-04:15 local, to fold in the two late verification agents T27 and
> R-STAT-MG1 (section 11): the S7-gate wording, the 13-16 / 15-16 framing, the MG-1 survival basis and the §7 z values.

## 0. Verdict

1. **Free data that production already captures closes about half of this table's served-to-market gap, through
   two serving repairs and no new source.** Served/market Brier over all hours goes from 1.73x to 1.34x (pooled
   1.768x to 1.328x). The two rungs together close **54% [35, 70]** of the original served-market excess
   (LADDER rung 2, 11/11 markets).
   - **Evening (17-23): a serving defect, not missing information.** Production's late-day lock-in stages read
     WU-only `history_max`, which has been empty since WU was disabled on 2026-06-30, so they are a no-op.
     Restoring them, re-anchored on the captured METAR floor, closes **85% [76, 92]** of the 17-23 gap
     (−0.0254 [−0.0353, −0.0175], 11/11). This was confirmed on one real served payload (ATL 2026-09-20 23:55), and
     T27 re-implemented the rung independently from its rule text (−0.025373, 7e-6 from D-DEFECT; section 11).
   - **Morning (00-12): served under-uses the NBM v2 guidance it already captures.** A zero-parameter read (MG-1)
     closes 58%, 55% and 40% of the 00-05, 06-09 and 10-12 gaps. This is the known 79a/81a/111h family (EF 10h,
     10j, 10p), not a discovery. It depends on landing the 83a/83b parser repair.
2. **No external source adds anything that is not already in captured data plus those two repairs.** That covers
   NBH, NBS, MOS/NBE, Single-Runs HRRR (latest and time-lagged), ECMWF IFS, 12Z soundings, NWS revision direction,
   neighbour stations and cloud/GOES. **There is no capture case.** The one borderline sign is MOS/NBE t7-r2 at
   13-14, which is a post-hoc hour slice and is not an increment over the no-source remaining-rise rung.
3. **The largest residual after both repairs is the registered 13-16 block:** +0.0231 [+0.0173, +0.0289] above the
   market, ratio 1.81x. Inside it, the POST-HOC 15-16 slice reads +0.0270 [+0.0204, +0.0337] (2.53x). Restoring the
   13-19 h lock-in stages S3-S5 recovers only −0.0020 at 13-16 (−0.0032 at 15-16; D-RUNG1C). The no-source METAR
   remaining-rise rung **t3-r3** beats served at 13-16 by **−0.0116 [−0.0190, −0.0052], 10/11** (z −3.26) and rung 2
   by −0.0107 [−0.0166, −0.0051], 11/11 (comparator built after t3-r3 was read; z −3.58). **Neither passes
   Bonferroni** (R-STAT-MG1). The "−0.0181 over rung 2 at 15-16" is post-hoc twice (hour slice and comparator), and
   0.0068 of it is MG-1's own 15-16 harm; against rung 1 it is −0.0113. t3-r3 is a new rule, so it can only enter as
   a pre-registration on new dates.
4. **Parity is not reached in 00-16.** After the repairs, 00-16 stays at 1.29x (+0.0141 [+0.0098, +0.0186]). The
   best composed candidate (POST-HOC, d2-c1) reaches 1.25x. Nothing tested closes the 00-12 residual
   (+0.010 to +0.014, 1.18-1.26x).
5. **Survivors** (both refuters, not disqualified): the evening family's 17-23 effect, re-attributed to the serving
   defect; the morning v2 route (MG-1, and T18/RV-1 as its likelihood form); t3-r3 at 13-16, graded fragile (it fails family-wise). MG-1 survives on resampling robustness, not on multiplicity.
   **Everything else failed or was closed** (section 6).
6. **Multiplicity: 134 registered rule ids** from 26 agents (section 7).

## 1. The parity ladder, per block (development)

### 1.1 Rungs and when they were declared

Two ladders were declared in the registry before their first score.

**Ladder I: information baselines, then sources.** T3 registered these before scoring, as DESIGN §4 T3 asked:
- **I-0** served, with the harness floor (the floor-only rung: |Δ| < 0.0002 in every block).
- **I-1** climatology `t3-r1`.
- **I-2** persistence `t3-r2`.
- **I-3** floor plus remaining rise `t3-r3`, the remaining-rise rung. This is a station x month x local-hour pmf of
  (daily hourly-row max − running max), built from IEM METAR history up to 2026-07-31, with constants fixed a
  priori.
- **I-4** each external source's candidate, measured as its marginal over I-3 (or over the relevant control).

**Ladder II: the no-source serving ladder.** LADDER registered r0-r2 at 02:16:06; D-RUNG1C registered r1c at
02:38:26.
- **r0** served + floor.
- **r1** + evening lock-in restoration (= d-defect-r2: S1 heuristic + S2 learned lock-in, anchor B =
  round_half_up(81a floor), production constants).
- **r2** + MG-1 morning read (= r-t5-inc-c1, no hour gate) with the r1 lock-in on top.
- **r1c** r2 + S3-S5 (production's own 13-19 h stages, same re-anchoring).

The **5% bar** (EF 1d) is −5% of each block's from-stratum served-market gap: about −0.0012 (00-05), −0.0013
(06-09), −0.0011 (10-12), −0.0012 (13-16), −0.0015 (17-23) and −0.0012 (00-16). The LEAD rule passes on that bar
or on −0.0133 (the twice-81a line).

### 1.2 Ladder II (headline)

**Table A. Ladder II by block, development.** Δ is the marginal against the previous rung. "Gap closed" is the
share of the original served-market excess.

| Block | r0 served − market (ratio) | r1 Δ vs r0 | r2 Δ vs r1 | r2 − market (ratio) | r2 gap closed | r1c Δ vs r2 |
|---|---|---|---|---|---|---|
| 00-05 | +0.0244 [+0.0162, +0.0341] (1.43) | 0 | −0.0141 [−0.0234, −0.0067] 11/11 | +0.0102 [+0.0056, +0.0149] (1.18) | 58% [37, 76] | 0 |
| 06-09 | +0.0254 [+0.0168, +0.0351] (1.45) | 0 | −0.0139 [−0.0229, −0.0063] 11/11 | +0.0114 [+0.0062, +0.0172] (1.20) | 55% [33, 75] | 0 |
| 10-12 | +0.0228 [+0.0159, +0.0301] (1.44) | 0 | −0.0092 [−0.0164, −0.0027] 10/11 | +0.0137 [+0.0088, +0.0189] (1.26) | 40% [15, 62] | 0 |
| 13-16 | +0.0239 [+0.0179, +0.0304] (1.84) | −0.0006 [−0.0010, −0.0003] 11/11 | −0.0002 [−0.0086, +0.0077] 2/11 | +0.0231 [+0.0173, +0.0289] (1.81) | 4% [−36, 33] | −0.0020 [−0.0038, −0.0006] 10/11 |
| — 13-14 | | | −0.0075, 8/11 | +0.0190 [+0.0133, +0.0249] (1.49) | | −0.0007 [−0.0029, +0.0010] |
| — 15-16 | | | +0.0068 [−0.0009, +0.0146], 2/11 | +0.0270 [+0.0204, +0.0337] (2.53) | | −0.0032 [−0.0051, −0.0017] 11/11 |
| 17-23 | +0.0296 [+0.0206, +0.0412] (n.i.) | **−0.0252 [−0.0350, −0.0174] 11/11** | +0.0018 [−0.0015, +0.0052] 2/11 | +0.0063 [+0.0036, +0.0097] (n.i.) | 79% [63, 89] (r1: 85% [76, 92]) | −0.0001 |
| **00-16** | +0.0242 [+0.0176, +0.0318] (1.49) | −0.0002 | **−0.0099 [−0.0177, −0.0034] 10/11** | +0.0141 [+0.0098, +0.0186] (1.29) | 42% [19, 62] | −0.0005 [−0.0009, −0.0001] |
| all | +0.0258 [+0.0194, +0.0339] (1.73) | −0.0073 [−0.0102, −0.0051] 11/11 | −0.0066 [−0.0129, −0.0013] 10/11 | +0.0119 [+0.0085, +0.0155] (1.34) | 54% [35, 70] | −0.0004 |

Notes on Table A:
- "n.i." means not interpretable: the ratio is not read where market Brier < 0.005 (17-23 market Brier is about
  0.0008).
- r2 is slightly worse than r1 at 17-23 (+0.0018, not significant). The extra mass comes from MG-1's base on rows
  where the lock-in strength s < 1. At 15-16 MG-1 harms (+0.0068; the date-only and market-only intervals exclude 0,
  W does not). That is **consistent with** stale whole-day guidance (EF 10p; the 07Z cycle is about 14 h old there)
  at block level only: R-STAT-MG1 finds no age gradient inside the block.
- Gating MG-1 by hour or by s would be an hour gate chosen on this table, which rule 8 forbids. The schedule-only
  gate is the separate D-HG draft (section 8).
- **Residual after r2** (snapshot-weighted share of the remaining excess): 13-16 32%, 00-05 22%, 06-09 16%,
  10-12 15%, 17-23 15%.

### 1.3 Ladder I: baselines, the rung, and source marginals

**Table B. Candidate − served by block, development.** Read from the agents' score files. Cells give the from-stratum
estimate and the harness classifier; the rung row also gives the interval, the before-stratum estimate (b) and the
markets negative.

| Rung or candidate | 00-05 | 06-09 | 10-12 | 13-16 | 17-23 | 00-16 | all |
|---|---|---|---|---|---|---|---|
| I-1 climatology t3-r1 | +0.0052 NULL | +0.0050 NULL | +0.0072 NULL | +0.0145 [+0.0045, +0.0254] HARM | +0.0237 HARM | +0.0077 NULL | +0.0123 HARM |
| I-2 persistence t3-r2 | −0.0007 WEAK | −0.0009 WEAK | +0.0029 NULL | +0.0151 HARM, 0/11 | +0.0303 HARM | +0.0036 NULL | +0.0112 HARM |
| **I-3 rung t3-r3** | −0.0010 WEAK | −0.0021 WEAK | −0.0041 WEAK | **−0.0116 [−0.0190, −0.0052]** b −0.0097, 10/11, LEAD; gap 48% [28, 64] | **−0.0219 [−0.0327, −0.0131]** b −0.0254, 11/11, LEAD; gap 73% [61, 81] | −0.0043 [−0.0121, +0.0017] 7/11 WEAK; gap 18% | −0.0094 LEAD |

Source marginals over the relevant rung (paired, from stratum, from the refuters, LADDER and D-DEFECT):

| Source (agent) | 00-16 increment over captured v2 (MG-1 or its control) | 13-16 / 15-16 over t3-r3 | 17-23 over the no-source collapse or t3-r3 | Verdict |
|---|---|---|---|---|
| NBH (T5) | +0.0027 [−0.0037, +0.0098], 5/11, b +0.0044 (R-T5-INC) | 13-16 +0.0019 [−0.0027, +0.0073] (R-STAT-T5); 15-16 +0.0005 [−0.0042, +0.0055] (LADDER) | a pure collapse beats it by 0.0005 (R-PIT-T5) | null; close |
| NBS (T6) | r2 − c2: 00-05 +0.0006, 06-09 +0.0002, 00-16 +0.0003 [−0.0004, +0.0011] | 13-16 +0.0028 vs t3-r3 (T6); 15-16 +0.0010 / +0.0021 | r2 − c1 −0.0000 [−0.0004, +0.0004] | null; DISQ as a source lead (R-STAT-T6) |
| MOS/NBE (T7) | r1 − c1 00-16 −0.0015 [−0.0049, +0.0019] (R-STAT-T7); c1 carries ~90% of the morning gain | t7-r2 13-14 over r2 −0.0063 [−0.0119, −0.0006] 10/11, but vs t3-r3 −0.0031 [−0.0077, +0.0017]; 15-16 +0.0006 | t7-r2 17-23 = family | null; 13-14 borderline only |
| HRRR latest (T8) | r2 − c2 06-09 −0.0005 [−0.0058, +0.0039], 3/8 | 15-16 +0.0024 | r1 − c1 +0.0004 [−0.0001, +0.0010] | null; DISQ (R-STAT-T8) |
| HRRR lagged ensemble (T9) | none over captured hrrr_high or v2 | 15-16 +0.0017 | = family | NULL |
| ECMWF IFS (T10) | r2 − c2 00-16 +0.0031 [−0.0025, +0.0091] (worse) | 13-16 +0.0026 vs t3-r3, 4/11; 15-16 +0.0004 | r2 − c1 −0.0003 [−0.0009, +0.0002] | null; DISQ (R-STAT-T10) |
| Soundings (T11) | — | — | r1 17-23 −0.00073 [−0.0032, +0.0008], 2 markets drive it | WEAK, about 0 |
| NWS revision (T12) | 00-05 classifier LEAD is a blur artefact; placebo beats it | — | — | NULL |
| Neighbours (T13) | r3 HARM 06-09 | r3 13-16 −0.0006 (7/11) vs served | — | WEAK, about 0 |
| Cloud / GOES (T14) | r4 10-12 −0.0011 [−0.0026, +0.0002] vs served | — | — | WEAK, about 0 |
| Obs trend (T4) | — | slope/sky/wind conditioning harms against the T2-style ablation | t4-r3 = family | the gain is the T2/T3 structure |
| Diurnal projection (T15) | 00-09 LEADs come from the no-diurnal control | 13-16 +0.0040 (null) | t15-r2 = family (T1 mechanism) | family only |
| Settlement mechanics (T16) | — | rounding headroom NULL; true-max target HARM | t16-r1 = t2-r1 | NULL beyond family |
| EMOS (T18) | the only selected information is captured v2_mean; hrrr_high + forecast_high add −0.0005 [−0.0013, +0.0004] | — | over t3-r3 +0.0002 | v2 route, likelihood form |

**Within the remaining-rise family**, measured over the I-3 rung at 17-23:
- t2-r1 is about −0.006 better (paired, R-STAT-T2).
- The no-source unconditional collapse (d-defect-d1 / t6-c1) and the source "remaining-hours" forms are all about
  −0.0065 to −0.0068 better than t3-r3.
- None of that difference is source information. It is the collapse onto the floor band.

### 1.4 Gap closed by the leading candidates, per block

**Table C. Share of this table's served-market gap closed, development, from stratum.**

| Candidate | Serveability class | 00-05 | 06-09 | 10-12 | 13-16 | 17-23 | 00-16 | all |
|---|---|---|---|---|---|---|---|---|
| r1 evening restoration | zero-parameter serving stage | 0% | 0% | 0% | 3% [−1, 7] | **85% [76, 92]** | 1% | 29% [22, 35] |
| MG-1 alone (r-t5-inc-c1) | zero-parameter serving stage, after the parser repair | 58% [37, 76] | 55% [33, 75] | 40% [15, 62] | 2% [−38, 32] | −27% [−89, 19] | **41% [18, 61]** | 19% [−15, 44] |
| r2 = r1 + MG-1 | as both | 58% | 55% | 40% | 4% [−36, 33] | 79% [63, 89] | 42% [19, 62] | **54% [35, 70]** |
| r1c = r2 + S3-S5 | zero-parameter serving stage | 58% | 55% | 40% | 12% [−27, 42] | 79% [64, 89] | 44% [21, 63] | 56% [36, 71] |
| t3-r3 rung | zero-parameter stage + one frozen history table | 4% | 8% | 18% | **48% [28, 64]** | 73% [61, 81] | 18% [−9, 39] | 36% [16, 53] |
| t1-r2 decided band | zero-parameter at serve; frozen X, N, H + q table | 0% | 0% | 0% | 15% [5, 24] | 89% [78, 95] | 4% [1, 7] | 32% [24, 39] |
| t2-r1 remaining-rise climatology | frozen table with backoff | 2% | 5% | 21% | 55% [34, 71] | 95% [86, 99] | 18% | 44% [26, 59] |
| T18 t18-r1 EMOS | needs retrain (fitted stage); no new capture | 50% | 63% | 57% | 63% [48, 76] | 73% [60, 82] | 58% [45, 70] | 63% [51, 72] |
| RV-1 (D3, t18-c1 frozen) | frozen constants; parser repair | 48% | 60% | 55% | 62% [47, 75] | 72% [60, 81] | 55% [42, 67] | 61% [49, 70] |
| d2-c1 = r2 x t3-r3 (POST-HOC) | composed; parser repair | 53% | 49% | 46% | 50% [26, 69] | 91% [80, 97] | 50% [30, 68] | 64% [49, 76] |
| t7-r2 MOS/NBE (reference) | needs new capture (MOS) | 66% | 67% | 54% | 54% | 94% | 61% [46, 74] | 72% [61, 82] |

Reading Table C:
- t7-r2's larger 00-16 share is **not a MOS increment.** About 90% of it is the captured-v2 control t7-c1 (00-16
  50% [34, 63], −0.0122), and the MOS-specific part is about −0.001 to −0.0015, null.
- **The morning route's best forms (T18, RV-1, t7-c1) differ from MG-1 by spread modelling on captured v2, not by
  a source.** RV-1 − MG-1 in 00-16 is −0.0034 [−0.0078, +0.0007], 8/11: indistinguishable.

## 2. 00-16 and 17-23, kept apart

**17-23 is cosmetic for the maker and real for Brier.** The market already knows the high is in (market Brier about
0.0008). Served keeps 0.342 of its mass above the floor band per 17-23 snapshot, against the market's 0.012 and a
realised 0.006.
- The fix removes a Brier loss that never moved a maker quote.
- It does not create maker edge.

**00-16 is what matters to the maker.** The development ladder there is:
- served: 1.49x;
- r1 (evening fix): no change, −0.0002;
- r2 (MG-1): **1.29x**, −0.0099 [−0.0177, −0.0034] (10/11, b −0.0122);
- r1c: 1.28x;
- POST-HOC d2-c1 (r2 x t3-r3): 1.245x, −0.0122 [−0.0198, −0.0057], 11/11.

What reaches parity, and what does not:
- **No candidate reaches market parity in 00-16.**
- The two candidates that are serveable without a new rule leave +0.014 above the market.
- No evening number may be used to argue for maker edge.

## 3. T1: serving-stage form and floor interaction

**Form (t1-r2), as a stage.**
- It runs after the final calibrated distribution.
- At snapshot t, the high counts as decided when:
  - local time is past sunset (NOAA equation, zenith 90.833°); or
  - local hour ≥ 15 and the latest routine METAR is at least 1 °F below the METAR running max.
  - X = 1, N = 1 and H = 15 were frozen from IEM history up to 2026-07-31, on a 181-point grid with a pre-stated
    criterion.
- When decided, each band at k = 1, 2, 3 °F above the floor band B keeps the historical residual-rise rate q(k).
  q comes from a 5-cell table: fallen|12-16, 17-19, 20-23; sunset|17-19, 20-23. The rest of the mass above B moves
  into B's band.
- t1-r1 is the full collapse, q = 0.
- At serve it is zero-parameter, but it is not zero-selection: it ships frozen X, N, H and the q table.
- Inputs are all captured: the floor, the latest METAR temperature (`current_temp` / `metar_temp`) and the station
  coordinates. T20 corrects T2's note: production does capture the current temperature, and only the 111h extract
  lacks it.

**Interaction with the 81a floor mask.** The floor mask is the max of `guidance_physical_floor`, `high_so_far` and
`trusted_current_max`, and B = round_half_up(F).
- The floor is a lower-side constraint: it zeroes bands below B. T1 is an upper-side constraint: it shrinks mass
  above B. Both act on bucket B, so together they collapse onto B's band. They never conflict, and the floor is
  never weakened.
- On this table `trusted_current_max` is null on 100% of rows, so F is in effect `guidance_physical_floor` (the
  METAR maximum since local midnight). Before 07:00, `high_so_far` is only the current reading (T20).
- Serving's own `hard_floor_bucket` excludes `guidance_floor`, so the 81a mask stays the stricter lower bound.
- Calibration (S7) re-spreads mass above B whenever its taper is unfed. On ATL 09-20 23:55, which is the s = 0 defect
  state itself, it moved the above-high mass from 0.031 to 0.087. The taper reads the same `lockin_strength`
  (`model_distribution.py:544`), so a restored lock-in also restores the taper and needs no gate (T27, section 11).
  As scored (after calibration), T1 needs no gate either. Inserted before calibration as a stage that does not feed
  the taper, it would.
- D-CAP1 found a capture defect, M0 (section 9.4). On station-days where it fires, the floor itself is wrong, and
  T1, the restoration and every floored candidate inherit it.

**Numbers (development).**
- 17-23: −0.0264 [−0.0379, −0.0175], b −0.0295, 11/11. It closes 89% [78, 95] of the gap and removes 88.6%
  [80, 95] of the tail.
- It holds at +60 min (−0.0249) and +120 min (−0.0231), and survives Bonferroni.
- 13-16: −0.0036 [−0.0066, −0.0011], 9/11. The classifier says LEAD; the refuters grade it WEAK (it fails at +1 h
  and under multiplicity).
- 00-16: −0.0009, WEAK. 00-12 is untouched (0% coverage).

**Why T1 is not a candidate.**
- The unconditional evening collapse with no METAR condition scores better: −0.0287 against −0.0264 (R-STAT-T1).
  The "decided" condition carries none of the effect.
- Restoring production's own lock-in (r1, −0.0254) gets the same result with no new rule.
- T1 is therefore subsumed by the owner's serving fix and is not drafted.
- (T1's own report.md is "Reconstructed by the orchestrator from the agent's returned summary". The numbers above
  come from `t1_r2_decided_band.score.json` and R-STAT-T1.)

## 4. Tail effect

**Definition on THIS table.** Band rows where served SE > market SE and |p_served − p_market| ≥ 0.30. These are
**6.075% of band rows and carry 70.38% of the positive excess** (with equal market-day weighting, 6.088% and
70.44%).
- **EF's figures, stated beside: 4.387% / 64.14%.** They were measured on the sealed pre-boundary corpus (09-44a),
  which was not opened tonight.
- The difference is expected. It is not a defect, and it is no reason to change EF.
- The tail carries 90.4% of the 17-23 excess, 73.6% of the 13-16 excess and 59.7-63.6% of the earlier blocks.

**Tail excess removed (T19, from stratum, W intervals).**

| Candidate | 17-23 tail removed | 00-16 tail removed | 00-16 non-tail cost (in units of the 00-16 tail excess) |
|---|---|---|---|
| r1 evening restoration | 84.4% [77, 91], 11/11 | 0.9% | 0% |
| r2 | 87.9% [78, 94] | 71.2% [63, 79] | −26.8% |
| r1c | 88.0% [78, 94] | 72.2% [64, 80] | −25.7% |
| MG-1 alone | 46.9% [24, 64] (non-tail −77%) | 71.0% [63, 79] | −27.1% |
| t3-r3 | 85.2% [80, 89] | 51.0% [41, 60] | −32.0% |
| t1-r2 | 88.6% [80, 95] | 3.9% | −0.1% |
| No-source collapse t6-c1 | 97.0% [91, 100] | — (HARM outside 17-23) | — |
| t18-r1 | 83.7% [76, 89] | 67.3% [62, 72] | −6.2% |
| t7-r2 (MOS) | 95.0% | 70.5% | −5.5% |
| t5-r1 (NBH) | 95.6% | 60.3% | −28.2% |
| d2-c1 (POST-HOC) | 94% | 77% | — |

**Reading.** Per-market tail sign cannot rank candidates.
- 98 of 99 distinct candidate vectors improve the all-hours tail. Even the HARM baselines reach 11/11:
  climatology removes +34% of the tail.
- The reason is the definition: tail rows are chosen where served already lost to the market by at least 0.30.
- What separates candidates is the **non-tail cost**. There the history-fitted spread forms (T18, t7-r2) pay back
  far less (about −6%) than the zero-parameter MG-1 (about −27%). Most of that difference is the σ model on the
  captured v2 centre, not a source.
- The evening lock-in must stay on top of any MG-1 composition. MG-1 alone gives back 77% on 17-23 non-tail rows.

## 5. Serveability and capture cost per route

| Route | Class | New capture | Cost | Dependencies |
|---|---|---|---|---|
| r1 evening restoration: S1/S2/S6 with the restored strength reaching the S7 taper (S7 gate optional), bundle S3-S5 | zero-parameter serving stage | none | 0 bytes | replay through `estimate_distribution`; release gate; roll-sensitive merge in the quiet window; M0 fix |
| MG-1 morning read | zero-parameter serving stage | none | 0 bytes; store the stage vector | land 83a/83b (production's v1 parser reads a *minimum* as today's max on 75,049 of 110,807 rows); re-version or quarantine the shadow variant trained on v1 values; shadow stage |
| t3-r3 remaining-rise stage (15-16 residual) | zero-parameter stage + frozen artifact `remaining_rise_pmf_v1` (3,036 cells) | none; anchored on the captured floor (d2-r3f reproduces t3-r3 within +0.0004) | about 1 MB/month for an IEM history refresh, if ever; frozen during evaluation | versioned table builder (D-CAP2 M4); M0; shadow stage |
| RV-1 / T18 | needs retrain under DESIGN's taxonomy (three frozen constants plus the rung table) | none | 0 bytes | parser repair; release binding |
| T1 decided band | zero-parameter at serve; frozen X, N, H and q table | none | 0 | dominated by r1 |
| NBH | needs new capture | NBH text bulletin, hourly, fan-out per cycle | about 0.68 GB/day transferred (about 20.5 GB/month); about 5 MB/month of extracts; new parser and payload contract | not recommended |
| NBS | needs new capture | `blend_nbstx`, hourly | same order as NBH (about 29.6 MB per object) | not recommended (null increment) |
| MOS/NBE (IEM) | needs new capture | MAV/MET/MEX/LAV + NBE | about 5-6 MB/month of extracts; about 1.7 GB/month if raw NBE is kept | decline; optional research-only shadow for 13-14 costed in D-CAP2 §4.4 |
| HRRR multi-run (Single-Runs) | needs new capture | Open-Meteo Single-Runs | API budget | decline; production already captures `hrrr_high` (effective latency about 2.5-3.5 h, up to about 4.5 h) |
| ECMWF IFS direct | needs new capture | 00/12Z open data | about 4.5 GB per window | decline; already captured through Open-Meteo |
| Soundings, GOES, neighbours, NWS revision | — | — | — | null; no case |

## 6. Survivors, and why the others failed

### 6.1 Survivors (both refuters: not disqualified)

**The evening family at 17-23.** Members: T1, T2, T3, T4, T15 and T16, plus the 17-23 legs of T5-T10.
- The effect survives every check: +1 h and +2 h availability shifts, LOMO and LOWO, 36/36 dates, six CI methods,
  and Bonferroni (z −4.9 to −5.3).
- **Attribution: a serving defect** (D-DEFECT; LADDER rung 1). It is not information from any member. An
  unconditional collapse with no input does at least as well.
- **Rung 1 independently reproduced** (T27): re-implemented from the registry text and production stage code, it
  matches LADDER/D-DEFECT to 5.6e-5 on every block, and bit-exactly once D-DEFECT's two reading conventions are
  adopted. At 17-23 it clears Bonferroni at the full registry count (138 lines, and 134 x 7) in every resampling
  scheme: 11/11 markets, 57/57 dates, LOMO and LOWO far from 0.

**The morning captured-v2 route.**
- MG-1 is a registered control, not a hunted candidate: 00-16 −0.0100 [−0.0179, −0.0035], 10/11, b −0.0122,
  PIT-clean.
- **MG-1 survives its statistics refuter (R-STAT-MG1) on resampling robustness, not on multiplicity.** Crossed W,
  date-only, market-only, LOMO, LOWO and the 11-market t (p <= 0.006) all exclude 0 in 00-05, 06-09, 10-12 and
  00-16, but z is −2.6 to −3.3 against the 4.04 Bonferroni line in every block. Its input is effectively the 07Z NBP
  cycle from about 06 local onward, because parser v2 rejects the 12Z/13Z/19Z cycles as `target_max_not_in_cycle`;
  whether that rejection is right is an unverified validity condition beside the value re-derivation.
- T18 t18-r1 is LEAD in every block, and both refuters reproduce it to about 1e-17: 00-16 −0.0140 [−0.0195,
  −0.0089], 11/11. Its only selected information is captured v2_mean.
- This is the **known 79a/81a/111h family** (EF 10h, 10j, 10p), not a new finding. EF 10j's power cap applies (11
  market clusters, about 40% crossed power for 81a-sized effects).

**t3-r3 at 13-16.**
- 13-16 (registered block): −0.0116 [−0.0190, −0.0052], 10/11, b −0.0097. It stands within the block (robust to
  every resampling, LOMO and LOWO) and **fails family-wise** (z −3.26; R-STAT-MG1).
- 15-16 (POST-HOC slice): −0.0126, 11/11. Its −0.0181 over rung 2 is post-hoc twice and includes MG-1's +0.0068
  15-16 harm (section 0.3); it is not a finding.
- **Graded fragile.** It is WEAK at +1 h serve-only (−0.0052 [−0.0150, +0.0035], 6/11, R-PIT-T3), NULL at +2 h,
  and fragile family-wise (R-STAT-T3).
- It loses about 40% of its effect per hour of extra METAR staleness. Production's freshness (a new max picked up
  about 3.8 min after the valid time) favours it, but the draft makes freshness a validity condition.

**T7.** It stands statistically, but the MOS-specific increment is null.

### 6.2 Failed or closed, with reasons

**Climatology (t3-r1).** HARM in 13-16, 17-23 and all hours.

**Persistence (t3-r2).** WEAK in 00-09; HARM in 13-23, 0/11 markets at 13-16.

**T1 decided condition.**
- It adds nothing: the unconditional collapse is better by −0.0023.
- Its 13-16 LEAD is WEAK-grade.

**T2.**
- Its 17-23 gain is the family's.
- Its 13-16 result (−0.0133) is fragile family-wise and WEAK at +1 h. Its edge over t3-r3 is small and costs slope
  bins and backoff.

**T4.** The slope, sky and wind conditioning harms against the ablation. Its 00-16 result is 52% Los Angeles, and
10-12 fails LOO.

**T5 (NBH).**
- PIT-clean, and every claimed block holds at +60/+120 min.
- The 00-16 increment over captured v2 is null and has the wrong sign: +0.0027 [−0.0037, +0.0098], 5/11, b +0.0044.
  v2_mean carries 137% [57, 567] of T5's 00-16 gain.
- In 00-12 NBH is worse than v2_mean in the same form (+0.0055 to +0.0069).
- 13-16 and 15-16 are the remaining-rise family (vs t3-r3: +0.0019 and +0.0005), and 17-23 is the collapse.
- **"Capture NBH for the morning" is closed** (R-T5-INC, D1).

**T6 (NBS).** DISQ as a source lead: the increment is null against both the collapse control and the captured-v2
control. The 13-16 result fails Bonferroni (69 rules) and LOMO (LA). T21 reproduced it independently, and T24/T25
confirmed the availability basis 1608/1608.

**T8 (HRRR latest).**
- DISQ: 17-23 equals the no-source control.
- 06-09 is marginal and concentrated (LA 42%, LA + Dallas about 72%).
- It shows no increment over the rung or over the captured `hrrr_high`, and it is WEAK at +2 h.

**T9 (HRRR lagged ensemble).** NULL. It adds nothing as a centre or as a spread.

**T10 (ECMWF IFS).**
- DISQ: 17-23 is the collapse family.
- 13-16 is fragile (LOMO 6/11, LOWO 4/7 cross 0).
- 00-16 is worse than captured v2.
- T22 reproduced it exactly.

**T11 (soundings).** WEAK at about −0.0007, carried by 2 markets. The lower-bound variants are NULL, leaning harm.

**T12 (NWS revision).** NULL. The classifier LEAD is a blur artefact; placebo and direction-free controls beat it.

**T13 (neighbours).** r1 NULL, r3 WEAK and HARM at 06-09. The r2 LEAD equals the no-neighbour control.

**T14 (cloud / GOES).** About −0.001 with the right sign. The r1/r2 LEADs equal the no-cloud control.

**T15 (diurnal projection).** The 00-09 LEADs come from the no-diurnal control. 13-16 is null, and 17-23 is the T1
mechanism.

**T16 (settlement mechanics).**
- Rounding headroom is NULL: ASOS T-groups are whole °F except at KBKF.
- The true-max target is HARM. F2 shows that the 1-minute true max lands in a different band from the winner on
  67.8% of 230 days, while the venue label RS_ct matches the winner on 626/626.

**T17 (market information arrival).**
- WEAK at about −0.0001 (= the no-source control).
- Descriptive finding: the market's Brier falls at informative METARs.
- No route.

**MOS 13-14 (t7-r2 over r2).** −0.0063 [−0.0119, −0.0006], 10/11. This is a post-hoc hour slice and not an
increment over t3-r3 (−0.0031 [−0.0077, +0.0017]). Decline it.

## 7. Multiplicity

- **Registry count: 134 rule ids**, all unique, from 26 agents, in `C:\swarm\registry.jsonl` at synthesis time.
  - Per agent: ladder 17; d2 7; d3 7; t7 7; t8 7; t9 7; t6 6; t10 6; t14 6; d-defect 5; t11 5; t13 5; 4 each for d1,
    r-t5-inc, t1, t2, t3, t4, t12, t15 and t18; 3 each for d-rung1c, t5, t16 and t17; d-morning 1.
  - The count includes controls, paired comparisons, diagnostics and planning ids. Byte-identical duplicates exist,
    for example ladder-r1 = d-defect-r2 and t10-c2 = r-t5-inc-c1.
  - So 134 is a conservative denominator.
  - T22 has score files and no registry rows. It re-implemented a registered rule, so it adds no rule.
- **Refuters used smaller counts at their own time.** These counts grew during the night, so the 134 here
  supersedes them:
  - R-STAT-T1: 35 lines;
  - R-STAT-T6: 69;
  - R-STAT-T8: 92;
  - R-STAT-T7: 371 tests;
  - T19: 116.
- **Bonferroni over 134 rules x 7 block groups = 938 tests** (one-sided 0.025/938, z about 4.04). The z values
  below are from the W draws under a normal approximation, and are development only. R-STAT-MG1 recomputed the ones
  given to two decimals (the synthesis had r1 about −5.6, t3-r3 17-23 about −4.4, r2 about −3.7); no pass/fail
  changed. The registry reached 138 lines with the late agents' diagnostics.
  - **Pass:**
    - the 17-23 family: r1 z −5.46, t3-r3 −4.22, T1 about −4.9;
    - T18 t18-r1 00-16, about −5.2;
    - RV-1 00-16, about −4.9 (its constants are in-sample on the before stratum);
    - t7-r2 00-16, about −4.6 (but about 90% of it is captured v2).
  - **Do not pass:**
    - MG-1 00-16, −2.70 (it survives on resampling robustness, not multiplicity);
    - r2 all hours, −3.60;
    - t3-r3 13-16, −3.26;
    - d2-c1 00-16, about −3.4;
    - T1 13-16, about −2.6.
  - Even the passing results are development reads on previously inspected dates. Passing Bonferroni here makes
    them worth a pre-registration, not established.
- **POST-HOC items, which are never evidence:** d2-c1, d2-c2, RV-1's choice over d3-z1, and every "halved" planning
  size.

## 8. Drafts on the table (all DRAFT, UNSIGNED, development)

| Draft | Candidate | Primary | Planned N | Power (plug-in, before stratum) | Dependencies and notes |
|---|---|---|---|---|---|
| D-MORNING `d-morning-v2-guidance-prereg-draft.md` | MG-1 (= r-t5-inc-c1, no hour gate) | 00-16, fixed-market, date-clustered | 45 countable dates, one look | fixed-market joint (interval + ≥ 8/11) 0.80 at 45 dates at the half effect 0.00608. Crossed: 0.34-0.41 at 45 dates and 0.62 unlimited for an 81a-sized effect; **80% unattainable on the crossed estimate** (EF 10j) | parser repair first; shadow stage `nbm_v2_guidance_read_v1`; first eligible ≥ 2026-10-15 |
| D3 `d3-t18-prereg-draft.md` | RV-1 (t18-c1 frozen: a −1.015, b 1.141, σ 2.355 °F) | 00-16 | 45, one look | fixed joint 0.945 at 45 at the half effect 0.0071 (normal approximation, less conservative); crossed floor MDE80 about 0.0077, so 80% is unattainable | RV-1 is worse than r1 at 17-23 by +0.0038 [+0.0010, +0.0066]: keep the lock-in on top. It is indistinguishable from MG-1 in 00-16 |
| D2 `d2-remrise-prereg-draft.md` | t3-r3 unchanged, anchored on the floor (d2-r3f) | 13-16 | — | **weak point:** joint 17% at 45 dates at the half effect; 86% only at the full effect; crossed 73% even unlimited | freshness is a validity condition; land r1 first so the comparator is stable |
| D-HG `d-hg-hour-gated-composite-prereg-draft.md` | HG-1: MG-1 inside gate G (`captured_at_utc` < 12:00Z on D, from the NBM schedule alone), served outside | separate arm with its own α | — | nothing scored (rule 8) | the local close moves one hour earlier at the end of DST (11-01) |
| D1 `d1-t5-prereg-draft.md` | NBH-1 (= t5-r1, tie rule fixed) | — | — | 80% unattainable: the development increment has the wrong sign | **recommendation: do not capture, do not activate**; it exists to close the route on a frozen form |

**Collisions the owner must resolve for any activation** (D-MORNING §7, D2, D3, D1, D-HG):
- **Trigger mismatch.** The reservation file's trigger is "first retrain candidate frozen", and these are serving
  stages.
- **Absolute scope.** A declared window is absolute. That stops MM paper scoring and collides with the 88a desk-study
  panel (UTC 10-15..10-30). A narrow, family-only scope needs an explicit recorded exemption.
- **Shared calendar.** MG-1, RV-1, HG-1 and t3-r3 would all read the same future dates. Sign one per family, or
  split α.
- **Season.** Mid-October onward is out of season (EF 1c). Every draft is scored out of season, and M0's carry-over
  rate rises to 2.2% of station-days in Oct-Dec.

## 9. Owner decisions this enables

1. **Approve or decline the evening WU-anchor serving fix (proposal).**
   - Required: re-anchor S1/S2 (and S6) on `lockin_high = max(history_max, guidance_floor)`, with `max_times` from
     the METAR rows, so that the restored strength also reaches the calibration taper (`model_distribution.py:544`).
     If the lock-in were re-implemented as a separate post-calibration step, or the taper kept reading the
     WU-anchored strength (still 0), calibration would re-add about 0.010 above the high at 17-23 (T27).
   - Optional: an explicit S7 gate above `lockin_high`. On top of the taper it is worth −0.00008 [−0.00015,
     −0.00002] at 17-23 (T27): helpful, negligible, not required. LADDER's r1b − r1 (+0.0004) comes from stage order,
     not from the gate.

   D-RUNG1C recommends bundling the S3-S5 re-anchoring, since it is the same defect: −0.0032 at 15-16, 11/11.
   - Development effect: 17-23 −0.0252, 85% of the gap; 00-16 unchanged.
   - It needs a captured-input replay through `estimate_distribution` (the r1/r1b band emulation is not a replay),
     the release gate, and a roll-sensitive quiet-window merge.
   - It is cosmetic for the maker.
2. **Land the 83a/83b NBM parser repair.** It is the prerequisite for every morning route (MG-1, RV-1, HG-1, d2-c1),
   and it is a versioned train/serve parity change. The shadow variant trained on v1-parsed NBM values must be
   re-versioned or quarantined.
3. **Sign or reject the drafts.**
   - MG-1 or RV-1 for 00-16. They are indistinguishable in 00-16; RV-1 is the better all-day stage. Sign one, or
     split α.
   - t3-r3 for 13-16. It is underpowered at the half effect; consider the owner option in D2 §6.
   - HG-1 only as a separate α arm.
   - Decline NBH-1.
   - Resolve the reservation collisions above. If none is activated, run each as a labelled development read on new
     dates.
4. **Approve the METAR capture fixes (D-CAP1 M0; D-CAP2 M1-M3).**
   - **M0 is new and a real defect.** Production keys METAR rows by AWC `reportTime`, the nominal hour, so a 23:5x
     report enters the next day's running max.
   - It was confirmed on the captured floor at KLGA 2026-09-19 and KMIA 2026-08-29 (351 snapshots). On KMIA 08-29
     every floored candidate gave the winner 0 all day.
   - Rate: 0.3-0.6% of station-days in Aug-Sep, 2.2% in Oct-Dec, up to 5.4% at KLGA.
   - The fix is to key on `obsTime`: a parse-only, versioned change.
   - M1 persists `receiptTime`. That fixes KBKF, where valid + 10 min is optimistic (T26).
5. **Close the failed routes in canon.**
   - Capture NBH for the morning: closed with R-T5-INC.
   - Close NBS, MOS/NBE (default decline; optional 13-14 shadow), Single-Runs multi-run HRRR, direct ECMWF IFS, 12Z
     soundings, GOES, neighbour anomaly, NWS revision direction, rounding headroom and the true-max target.
   - Record that the 17-23 "lead" is a serving defect, not information.
   - Record T24's correction: the late S3 uploads are upstream delays (08-31, 09-14, 09-23) plus one transfer backlog
     (09-24 00-12Z). They are not "re-uploads".

## 10. Orchestration deviation, and other caveats

- **Refuter allocation.** The original refuter cap counted refuters per LEAD, not per family. Because T1-T4, T15 and
  T16 are one family (remaining-rise), it spent about six families' worth of refuters on that one family. The
  orchestrator fixed this at about 01:30 local with a family-aware cap (restart note 01:27; steering 01:50: "No more
  refuters for this family").
  - The Fable refuters went to T1, T4 and T2, all in the remaining-rise family.
  - The source families (T5-T10, T18) got Opus refuters, plus the targeted R-T5-INC.
  - Consequence: no source lead went unrefuted, but the Fable budget went to the family later shown to be a serving
    defect.
- **Missing or reconstructed reports.**
  - Reconstructed by the orchestrator from the agent's returned summary: F1, T1, T5, A-NBH, A-IEM-2, refute-pit-t3
    and refute-stat-t3. Numbers from these are cited from score or result files.
  - Blocked by the tool guard, with the text in result.json: R-STAT-T7 left only `stats.json` and a phase-log line;
    T19, T20, T24 and r-pit-t3 have result.json `report_md`.
- **The lock-in rungs are band-level emulations** applied to the served final bands. They are not replays.
  D-RUNG1C depends on a declared forecast proxy, because the hourly forecast rows are not in the extract; two
  proxies agree.
- **Clusters.** 11 market clusters. Plug-in power assumes August variance holds out of season.
- **Data defects found along the way.**
  - `trusted_current_max` is null on 100% of rows.
  - 31 rows carry a captured floor 10 °F above the METAR max.
  - M0 (above).
- **Completeness critic and canon writer follow.** This document makes no canon edit.

## 11. Late verification (T27, R-STAT-MG1)

Both finished after this synthesis was first written. Neither contradicts a number in it.
- **T27 (`t27.md`): rungs 1 and 2 REPRODUCED independently** from the registry text and production stage code, without
  reading D-DEFECT's or LADDER's code before scoring. Rung 1 at 17-23: −0.025373 [−0.035311, −0.017489] against
  −0.025366; rung 2 within 2.3e-4; classes identical. Rung 1 at 17-23 clears Bonferroni at 138 and at 938 tests in
  every resampling scheme.
- **T27 on the S7 gate: not necessary; helpful by a negligible amount.** Restoring the lock-in strength also feeds
  the calibration taper (`model_distribution.py:544`), which at strength 1 makes calibration the identity. Across
  17-23, untapered calibration would add 0.0098 above the high, the production taper adds 0.0011, and a gate removes
  that last 0.0011 for −0.00008 Brier. The ATL 23:55 payload's 0.031 → 0.087 is the no-lock-in defect state itself.
  LADDER's r1b − r1 (+0.0004) comes from stage order. What IS required is that the restored strength reaches the
  taper. These are band-level emulations; the `estimate_distribution` replay remains the confirmation step.
- **R-STAT-MG1 (`r-stat-mg1.md`): no SYNTHESIS number contradicted** (recomputed to 4 dp). MG-1 stands within its
  family on resampling robustness and fails registry-wide multiplicity. t3-r3 stands within the registered 13-16 block
  and fails family-wise. 15-16 is a post-hoc slice. Its four wording fixes are applied in sections 0.3, 1.2, 6.1 and
  7. It adds one unverified validity condition for MG-1: parser v2's rejection of the 12Z/13Z/19Z NBP cycles.
- **COMPLETENESS verdict item 2 is now partly closed.** Rungs 1-2 have an independent re-implementation (T27), and
  MG-1 and t3-r3 have a statistics refuter (R-STAT-MG1). Still open: the captured-input replay through
  `estimate_distribution`, the `v2_mean` value re-derivation, and a from-text re-implementation of t3-r3.

**Files added by the late agents:**
- `docs/research/model-parity-swarm-2026-10-04/t27.md`; code `tools/research/model_parity/t27_indep_r1.py` and
  `t27_indep_r1_stats.py`; outputs in `C:\swarm\out\t27\`.
- `docs/research/model-parity-swarm-2026-10-04/r-stat-mg1.md`; code `tools/research/model_parity/r-stat-mg1_refute.py`;
  outputs in `C:\swarm\out\r-stat-mg1\`.
