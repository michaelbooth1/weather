# DRAFT, UNSIGNED, DEVELOPMENT: remaining-rise family deep dive and pre-registration draft (t3-r3)

> **DRAFT. UNSIGNED. DEVELOPMENT ONLY.** Written by swarm agent D2 on 2026-10-04 (about 03:10 America/Toronto)
> on the workstation. Nothing here is frozen. Nothing here is a reservation, an alpha allocation, a serving change,
> a config change or a merge. Owner approval is needed before any part of it takes effect. Every number comes from
> a development read of the 111h table (targets 2026-08-01..09-29). 79a, 81a and 111h had already inspected the
> from stratum (08-23..09-29), so **none of these numbers is evidence** (DESIGN rule 7).
> Reservation status re-read: **NONE RESERVED** (`docs/operations/reserved-confirmation-window.md`).
>
> HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`. Rows with a target after
> 2026-09-29: 0. Leakage-suspect groups: none, in all six D2 scores. Registry lines at D2's run: 133. D2 registered
> 7 ids (d2-c1, d2-c2, d2-c1s60, d2-r3f, d2-cov, d2-plan1, d2-pairs) before its first score.
> Code: `tools/research/model_parity/d2_remrise.py` (sha256 `2795968c…838bf`). Outputs: `C:\swarm\out\d2\`.

## 0. Verdict

1. **Treat the family as one route with two parts.**
   - **17-23 is mostly a serving defect, not information.** The family's 17-23 gain (-0.022 to -0.028 by member)
     is what an unconditional evening collapse onto the captured floor band also gets (-0.0287, R-STAT-T1). The
     restored production lock-in gets most of it (rung 1 = d-defect-r2, -0.0252). Restoring production's own
     stage is an owner decision on a serving fix. It needs a replay and the release gate. It is **not** a new rule
     to pre-register.
   - **15-16 (inside 13-16) is the part no restoration reaches.** Restoring the 13-19 h stages S3-S5 recovers only
     -0.0032 at 15-16 (D-RUNG1C). The remaining-rise rung t3-r3 beats rung 2 there by -0.0181 [-0.0251, -0.0112],
     11/11 markets. This is the part that needs a new rule, and so a pre-registration.
2. **The pre-registered candidate is t3-r3 ("floor + remaining rise"), as registered, with no change.**
   - It has zero tuned parameters. Its constants were fixed a priori: kernel sd 1 F, history running max at H:30,
     at least 20 rows. It needs one frozen lookup artifact, built from public IEM METAR history ending 2026-07-31.
   - Its serving form needs no new capture. D2's serve-form check **d2-r3f** anchors the table on production's
     captured 81a floor bucket instead of an IEM METAR join, and reproduces t3-r3: 13-16 differs by +0.0004
     [-0.0004, +0.0012] and 17-23 by +0.0005.
   - It has no hour gate and no guidance input, so it does not touch DESIGN rule 8.
3. **Proposed primary: 13-16 local, t3-r3 minus served, fixed-market date-clustered.** 17-23 is reported
   separately with no alpha.
   - **Power is the weak point, stated plainly.** The pass rule requires at least 8 of 11 markets negative. At the
     halved planning effect that rule cannot reach 80% power at any number of dates (17% joint power at 45 dates).
     It reaches 80% only if the full development effect carries over (86% at 45 dates).
   - Under the crossed estimand, 80% is unattainable at any number of dates even at the full effect: 73% with
     unlimited dates.
   - Section 6 gives the numbers and an owner option.
4. **The best combined candidate is POST-HOC and is not evidence:** d2-c1 = rung 2 x t3-r3, the band-wise
   product, renormalised, with no hour gate. Development scores against served:
   - 00-16: -0.0122 [-0.0198, -0.0057], 11/11 markets;
   - 13-16: -0.0121, 11/11;
   - 17-23: -0.0272, 11/11.

   After halving, the sizes are 00-16 -0.0061, 13-16 -0.0060 and 17-23 -0.0136. Its increment over rung 2 at 15-16
   is -0.0155 [-0.0204, -0.0108], 11/11. This is the obvious composed serving form, and it would need its own
   pre-registration (section 3).

## 1. The family, member by member (from stratum, all rows, candidate minus served, development)

17-23 is cosmetic for the maker but real for Brier. 00-16 is what matters to the maker. The two are kept apart
throughout.

| Member (rule) | 17-23 [95%] | 00-16 | 13-16 | Mechanism / attribution | Serveability |
|---|---|---|---|---|---|
| T1 decided-band collapse (t1-r2) | -0.0264 [-0.0379, -0.0175], 11/11, 89% of gap | -0.0009, WEAK | -0.0036. LEAD as scored, but WEAK-grade (fails at +1 h and under Bonferroni; refuters) | Collapse above the floor band once "decided". The decided condition contributes <= 0: the unconditional collapse gets -0.0287 (R-STAT-T1). | Zero-parameter at serve, but it ships frozen X/N/H and a q table (section 2) |
| T2 remaining-rise climatology (t2-r1) | -0.0282 [-0.0395, -0.0191], 11/11 | -0.0044, WEAK | -0.0133, LEAD; fragile family-wise (refuter) | Station x month x hour x deficit x slope pmf, with backoff | Frozen table with more cells and backoff. Inputs captured (T20 corrects T2's capture note). |
| **T3 floor + remaining rise (t3-r3)** | **-0.0219 [-0.0327, -0.0131], 11/11** | **-0.0043 [-0.0121, +0.0017], WEAK** | **-0.0116 [-0.0190, -0.0052], 10/11** | Unconditional remaining-rise rung, station x month x hour only | **Frozen table, no tuned constant, anchored on the captured floor (d2-r3f)** |
| T4 obs-trend nowcast (t4-r3) | -0.0265, 11/11 | LEAD as scored; WEAK at +1 h; 52% carried by LA | LEAD | The slope/sky/wind conditioning **harms** against the T2-style ablation. The gain is the T2/T3 structure. | Frozen table plus a fitted w |
| T7 MOS/NBE consensus (t7-r2) | -0.0280, 11/11 | -0.0148 LEAD, but about 90% of it is the captured-v2 control (c1). MOS increment about -0.001. | LEAD | The remaining-hours max floored is this family. The morning part is the MG-1 family. | Needs MOS capture (not worth it) |
| T15 diurnal projection (t15-r2) | -0.0221 [-0.0343, -0.0125], 11/11 | 00-09 LEADs come from the no-diurnal control | +0.0040 (null) | A tight sigma around the METAR max after 17 h is the T1 collapse again | Fitted sigma on the before stratum |

Common to the whole family: every member's 17-23 gain removes 79-97% of the 17-23 tail excess (T19). The 17-23
gain survives +1 h and +2 h availability shifts (refuters). The 13-16 gain does **not** survive them robustly.

## 2. Why t3-r3 and not T1: T1's serving-stage form and the 81a floor

**T1's serving-stage form (t1-r2), written as a stage:**
- It runs after the final calibrated distribution. At snapshot *t*, the high counts as decided when local time is
  past sunset (NOAA equation, zenith 90.833°), or when local hour >= 15 and the latest routine METAR is at least
  1 °F below the METAR running max (X = 1, N = 1, H = 15, frozen from history <= 07-31).
- When decided, the bands above the floor band B keep the historical residual-rise rate q(k) for k = 1, 2, 3 °F
  above B, from a 5-cell table (fallen|12-16, 17-19, 20-23; sunset|17-19, 20-23). The rest of their mass moves
  into B's band.
- t1-r1 is the full collapse: q = 0.

**T1's interaction with the existing 81a floor mask** (max of `guidance_physical_floor`, `high_so_far`,
`trusted_current_max`; B = round_half_up(F)):
- The floor is a lower-side constraint. It removes mass below B. T1 is an upper-side constraint. It shrinks mass
  above B.
- Both act on the same bucket B, so together they collapse the distribution onto B's band. They cannot conflict,
  and the floor is never weakened.
- On this table, `trusted_current_max` is null on 100% of rows (WU off). F is in effect `guidance_physical_floor`,
  the METAR maximum since local midnight (T20).
  - R-PIT-T1 attributes 28,561 of the decided 17-23 floors to `high_so_far`. After 07:00 that field is the station
    fallback running max, so it ties with the guidance floor.
  - 31 rows carry a captured floor 10 °F above the METAR max. That is a capture data-quality item, and it is
    immaterial to the estimate.
- The 81a floor stays the stricter of the two lower bounds: serving's own `hard_floor_bucket` excludes
  `guidance_floor` (D-DEFECT §5).
- The overconfidence calibration (S7) must be gated, or it re-spreads mass above B after any upper-side stage. On
  ATL 09-20 23:55 it moved the above-high mass from 0.031 to 0.087. **This applies to T1 and to t3-r3 alike** if
  either is inserted before calibration. Inserted after calibration, as scored here, neither needs the gate.

**Why T1 is not the pre-registered candidate:**
1. It only covers late afternoon and evening: 0% coverage at 13-14 and 27-39% at 15-16. Its 13-16 LEAD fails at
   +1 h (R-PIT-T1).
2. Its distinctive part, the METAR decided condition, adds nothing. The unconditional collapse is better by
   -0.0023 (R-STAT-T1).
3. In 17-23 it is dominated by restoring production's own lock-in (rung 1, -0.0252), which is not a new rule.
   Pre-registering T1 would test a new rule against a fix the owner can make without one.
4. It has more frozen content than t3-r3 in the place that matters. X/N/H were selected on a 181-point history
   grid, so it is "zero-parameter at serve" but not zero-selection.

**Why t3-r3 over T2/T4/T7/T15:**
- T2 beats t3-r3 by about 0.006 in 17-23, but it adds slope bins and a 3-level backoff. Its 13-16 edge over t3-r3
  is small (-0.0133 vs -0.0116).
- T4's added conditioning harms. T7 needs a new capture. T15 fits sigma on the before stratum.
- t3-r3 is the simplest statement of the mechanism that every member shares, and the refuters already checked it
  under six CI methods, leave-one-market-out and leave-one-week-out.

## 3. Combined candidate (POST-HOC; sizing only; effect halved; never evidence)

The ids were registered before scoring. All rows are from stratum, all-row, against served, with the before
stratum shown beside. "Halved" is the planning size.

| Candidate | 00-16 | 13-14 | 15-16 | 13-16 | 17-23 | all |
|---|---|---|---|---|---|---|
| t3-r3 (proposed) | -0.0043 [-0.0121, +0.0017] 7/11 (b -0.0049) | -0.0109 | -0.0126 [-0.0194, -0.0065] 11/11 | -0.0116 [-0.0190, -0.0052] 10/11 (b -0.0097) | -0.0219 11/11 | -0.0094 |
| ladder rung 1 (restore) | -0.0002 | — | — | -0.0006 | -0.0252 | -0.0073 |
| ladder rung 2 (restore + MG-1) | -0.0099 | -0.0075 vs r1 | +0.0068 vs r1 | -0.0002 vs r1 | +0.0018 vs r1 | -0.0066 vs r1 |
| **d2-c1 = rung 2 x t3-r3** | **-0.0122 [-0.0198, -0.0057] 11/11** (b -0.0164) | -0.0143 | -0.0101 | **-0.0121 [-0.0194, -0.0052] 11/11** | **-0.0272 [-0.0388, -0.0177] 11/11** | -0.0166 |
| d2-c1 halved (planning) | **-0.0061** | | | **-0.0060** | -0.0136 | -0.0083 |
| d2-c2 = rung 1 x t3-r3 (no parser landing) | -0.0013 [-0.0040, +0.0011] 5/11 | -0.0034 | -0.0102 11/11 | -0.0068 [-0.0115, -0.0023] 9/11 | -0.0278 11/11 | -0.0089 |

**Paired increments, development:**
- **d2-c1 minus rung 2:**
  - 15-16: -0.0155 [-0.0204, -0.0108], 11/11;
  - 13-14: -0.0066 [-0.0103, -0.0028], 11/11;
  - 17-23: -0.0037 [-0.0056, -0.0021], 11/11;
  - 00-16: -0.0021 [-0.0040, -0.0001], 9/11.
- **d2-c1 minus t3-r3:**
  - 13-16: -0.0004 [-0.0047, +0.0044]. The product keeps t3-r3's afternoon.
  - 00-16: -0.0079 [-0.0120, -0.0035], 11/11. It adds MG-1's morning.
  - 17-23: -0.0053, 11/11.
- **d2-c2 minus rung 1:**
  - 15-16: -0.0089, 11/11;
  - 17-23: -0.0024, 11/11.
- **Composing beats replacing at 13-14.** d2-c2 is worse than t3-r3 at 13-14 (+0.0075 [+0.0010, +0.0144],
  2/11): served's 13-14 drags the product.
- **Parity, d2-c1 minus market:**
  - 00-16: +0.0120 [+0.0078, +0.0164], ratio 1.245;
  - 13-16: +0.0120 [+0.0075, +0.0170], ratio 1.42;
  - 17-23: +0.0026 [+0.0009, +0.0054] (ratio not interpreted).

  It still trails the market in every block, and closes 50.5% of the 00-16 gap and 91% of the 17-23 gap.
- **Tail, this table's definition** (6.075% of band rows carry 70.38% of the excess; EF's 4.387% / 64.14% is a
  different panel), share of tail excess removed by d2-c1: 00-16 77%, 13-16 75%, 17-23 94%. t3-r3 alone: 00-16
  51%, 13-16 69%, 17-23 85%.

**Reading.** The composed route (restore the lock-in, MG-1 in the morning, and a t3-r3 factor) is the best thing
on the table, at all hours, with no hour gate and no new source. But:
- it is post-hoc;
- it depends on the parser landing (MG-1);
- the product rule double-counts information wherever both factors are sharp.

A future pre-registration of d2-c1 is possible only after this draft's candidate has been tested, or as a
separately powered arm with its own alpha. This draft does not register it.

## 4. Sensitivity (development)

**Availability +1 h:**
- **t3-r3s** (both history table and serve +60 min, registered by T3):
  - 13-16: -0.0071 [-0.0144, -0.0011], 8/11 (a LEAD only via the 5%-of-gap bar);
  - 17-23: -0.0216, 11/11;
  - 00-16: -0.0027.
  - Paired t3-r3s minus t3-r3: 13-16 +0.0045 [+0.0028, +0.0063], 0/11.
- **R-PIT-T3, serve-only +1 h:** 13-16 WEAK at -0.0052 [-0.0150, +0.0035], 6/11; NULL at +2 h. 17-23 stays at
  -0.0207 to -0.0225 under every shift.
- **The combined candidate at +1 h (d2-c1s60):** 13-16 -0.0091 [-0.0171, -0.0020], 10/11; 00-16 -0.0113; 17-23
  unchanged. Against d2-c1: 13-16 +0.0029 [+0.0015, +0.0043].
- **So 13-16 depends on fresh METAR.** It loses about 40% of its effect per hour of extra staleness. 17-23 does
  not depend on it.
- **Production freshness favours the stage.** Production picks up a new METAR max about 3.8 min after the valid
  time (T17/T20), and a snapshot arrives about every 9 min. The development basis was valid + 10 min, and about 7%
  of new maxima arrive later than that (R-PIT-T3).
- **The draft makes freshness a validity condition** (section 7). The owner-approved 2026-10-02 METAR cadence
  change (2-5 min, T-group tenths, SPECI; lands after 10-13) would make serve-time inputs fresher. If it lands
  inside the window, the look reports segments.

**Coverage loss** (t3-r3 removed on random market-days; served fallback):

| Market-days lost | 13-16 | 15-16 | 17-23 | 00-16 | Share of 13-16 effect kept |
|---|---|---|---|---|---|
| 0% (t3-r3) | -0.0116 [-0.0190, -0.0052] 10/11 | -0.0126 | -0.0219 | -0.0043 | 100% |
| 20% (d2-cov20) | -0.0093 [-0.0143, -0.0046] 10/11 | -0.0101 | -0.0163 | -0.0029 | 80% |
| 50% (d2-cov50) | -0.0060 [-0.0109, -0.0020] 10/11 | -0.0065 | -0.0104 | -0.0018 | 52% |

The effect scales about linearly with coverage, so a stage that is down on some days dilutes the estimate and does
not bias it. t3-r3 coverage is 94.9% of snapshots. The missing rows are almost all 00-05, before the first routine
row. In 13-23 coverage is above 99%.

**Serve form (d2-r3f, anchor = the production floor bucket, no IEM join):**
- vs served: 13-16 -0.0113 [-0.0185, -0.0050], 9/11; 17-23 -0.0215, 11/11; 00-16 -0.0036.
- vs t3-r3: 13-16 +0.0004 [-0.0004, +0.0012]; all hours +0.0007.
- Coverage 95.1%.

**This is the serveability result.** The captured `guidance_physical_floor` (the METAR maximum since local
midnight) is a sufficient serve-time anchor. The production stage needs no IEM, no new field and no current-temp
read.

## 5. Serveability and capture plan

**Class:** zero-parameter serving stage, plus one frozen history artifact. No new capture and no retrain.

**Inputs at serve:**
- the captured 81a floor F, read as `guidance_physical_floor` in practice;
- B = round_half_up(F);
- the market's station, the local target month and the local hour of the snapshot.

**Frozen artifact `remaining_rise_pmf_v1`:**
- 3,036 cells: station x calendar month x local hour.
- Each cell is the empirical pmf of e = daily routine-row max minus the running max at local H:30, from IEM
  asos.py routine METAR, COR excluded, temp_f = round_half_up(T-group °C x 1.8 + 32), with complete days of at
  least 20 rows, history 2024-05-01..2026-07-31.
- It is smoothed with a discrete Gaussian of sd 1 °F, and negative e is folded onto 0.
- The artifact's hash, its build code hash and its fit window bind into the release manifest. **No monthly
  refresh during the evaluation** (the table is frozen).
- The table already holds October, November and December cells from the 2024 and 2025 history. The
  out-of-season months are covered by the table's construction, but their effect was never measured.

**The stage `remaining_rise_floor_v1`:**
- Band probabilities are P(H = B + e) mapped to bands: `eq` [low, high] inclusive, `lte` <= high, `gte` >= low.
  Then the 81a floor mask and renormalisation.
- **Fallback to served** when F is missing, the cell is missing, the METAR payload is flagged `stale`, or the
  floored mass is 0.
- **Order:** after the final distribution, so the S7 calibration cannot re-spread mass above B.
- **Shadow only during the evaluation window:** computed and stored per snapshot, not served. Served stays the
  comparator.

**Parity items, stated:**
- History uses IEM valid + 10 min. Serve uses the latest report in the captured payload, about 3.8 min after valid.
- History excludes COR. Production does not filter COR.
- KBKF T-group tenths are the known unit edge (T16).
- The history table measures from routine rows. The production floor includes SPECI in the METAR rows.

None of these is a train/serve break for a post-processing stage. All are declared, and the d2-r3f check covers the
anchor difference.

**Capture cost:** zero bytes of new source. Per snapshot, store the stage vector (about 15 floats), the cell key and
the artifact hash. That is negligible against the retained payloads.

**Merge class:** a stage module that the supervisors import is **roll-sensitive**, so it lands in the 01:00-04:00
quiet window via `scripts/ops/quiet_window_merge.ps1`. The 2026-10-03 exam-period policy lift allows this, because
the change is not 88a capture code.

**Dependency on the owner's evening fix (rung 1):** none for this candidate. Section 7 says how each landing order
is reported.

## 6. Power (plug-in planning on the BEFORE stratum only; development; sizing, never evidence)

**Method:**
- Registry id `d2-plan1`; output `C:\swarm\out\d2\d2_run.json` → `power`.
- Population: the before stratum (2026-08-01..08-22), 21 dates x 11 markets. t3-r3 minus served market-day cells.
- One-sided alpha 0.025, 2,000 draws, seed 20261004.
- **Fixed-market:** dates resampled multinomially to N, markets fixed. **Crossed:** markets resampled too.
- Joint power adds "at least 8 of 11 markets negative", a plug-in that keeps the before-stratum per-market
  deviations. The from stratum is never used for sizing.

**Planning effects:**

| Block | Before-stratum estimate | Half effect (planning) |
|---|---|---|
| 13-16 | -0.00972 | 0.00486 |
| 15-16 | -0.01260 | 0.00630 |
| 00-16 | -0.00488 | 0.00244 |
| 17-23 | -0.02538 | 0.01269 |

**Per-market before-stratum means, 13-16:**
- Positive: Atlanta +0.0007, Denver +0.0061, Miami +0.0011.
- Small negatives: NYC -0.0023, Seattle -0.0061.
- Largest: LA -0.0378.

| Block, N new dates | Fixed MDE80 | Fixed power, interval only (half / full) | Fixed joint >= 8/11 (half / full) | Crossed MDE80 | Crossed power (half / full) |
|---|---|---|---|---|---|
| 13-16, 20 | 0.0038 | 0.93 / 1.00 | 0.22 / 0.80 | 0.0124 | 0.16 / 0.58 |
| **13-16, 45** | **0.0027** | **~1.00 / 1.00** | **0.17 / 0.86** | 0.0115 | 0.18 / 0.63 |
| 13-16, 90 | 0.0020 | 1.00 / 1.00 | 0.12 / 0.88 | 0.0110 | 0.21 / 0.67 |
| 13-16, unlimited | → 0 | — | falls with N at half | **0.0105** | **0.23 / 0.73** |
| 15-16, 45 | 0.0040 | 0.995 / 1.00 | 0.28 / 0.98 | 0.0110 | 0.35 / 0.90 |
| 00-16, 45 | 0.0024 | 0.83 / 1.00 | 0.02 / 0.33 | 0.0088 | 0.11 / 0.31 |
| 17-23, 45 | 0.0042 | 1.00 / 1.00 | 0.92 / 1.00 | 0.0139 | 0.72 / 1.00 |

**Statements required by DESIGN §6:**
- **The 11-market-cluster floor.**
  - Under the crossed estimand, the market clusters set a variance floor that no number of dates removes. At 13-16
    the unlimited-date MDE80 is 0.0105, larger than the half effect (0.0049) and even than the full before-stratum
    effect (0.0097).
  - **80% power is unattainable on the crossed estimate at any N**, even at the full effect (73% with unlimited
    dates). This matches EF §10j.
- **The fixed-market estimand removes the floor on the interval.** The interval condition alone reaches 80% at
  about 20 dates for the half effect.
- **The sign-consistency condition binds, and at the half effect 80% is unattainable.**
  - Three or four markets sit near zero or positive in development. At the half effect, joint power with at least
    8 of 11 is 22% at 20 dates and *falls* with N (17% at 45, 12% at 90), because more dates pin the per-market
    means to their plug-in values.
  - Joint power reaches 80% only if the full development effect carries over: 80% at 20 dates, 86% at 45.
- **Planned N = 45 countable dates, one look.** This matches the morning draft, so one calendar could serve both
  if the owner wants that.
- **Owner option (not the default):** keep sign consistency as a reported guardrail rather than a pass condition.
  The guardrail text requires "per-market and sign-consistency"; it does not say it must gate the pass. Then a
  45-date look has about 100% interval power at the half effect. The default here keeps it as a pass condition,
  for consistency with D-MORNING, and states the cost.
- **Limits of these numbers:**
  - Plug-in, from 21 August dates.
  - Out of season, both the variance and the effect may differ (section 8).
  - The 13-16 effect also loses about 40% per hour of staleness (section 4).

## 7. Draft pre-registration text (UNSIGNED)

### 7.1 Candidate (fixed verbatim)

The candidate is **t3-r3**, registry sha256 `ae86d0350391219d1f96a91e944335eec2e9216f95b0fdc58e9cda3185456559`,
restated for production as `remaining_rise_floor_v1` (section 5):
- The anchor is the captured 81a floor bucket B. Development showed this to be equivalent to the registered METAR
  running max (d2-r3f).
- The artifact is `remaining_rise_pmf_v1`, built exactly as the registered text describes, frozen, with its hash
  bound.
- No fitted parameter, no hour gate, no pool with served, no recency rule. It applies at every local hour, with
  fallback to served as in section 5.
- **Alternatives excluded, so there is one candidate, one primary and no multiplicity:**
  - T1 (section 2);
  - T2 and T4 (more cells, backoff, a fitted w);
  - T7 and T15;
  - the d2-c1 composition (post-hoc).

### 7.2 Dates

The **first eligible date** is the first local target date *D* that satisfies all of the following:
- (a) *D* >= **2026-10-15**, i.e. after 2026-10-14;
- (b) **its inputs are captured point in time in production**: the stage and the frozen artifact were deployed in
  shadow before the first T+0 snapshot of *D* in the earliest US timezone. Verified by all three capture workers
  recovered and one full prior day of stored stage vectors with the bound artifact hash;
- (c) *D* is after the Toronto date of the freeze commit;
- (d) *D* is promotion-countable.

Every countable date after it counts, with no skipping and no choice. The freeze must not be timed around
convenient dates.

The floor itself is already captured today (`guidance_physical_floor`), so (b) depends only on the stage landing.
That is a quiet-window merge. **The realistic earliest date is late October.**

### 7.3 Season statement

- **Every eligible date is out of season.** Mid-October onward lies outside the season the served model was trained
  on (DESIGN §6; the EF §1b.4 / §1c / §2 lineage). It is also outside the August-September window where the swarm
  measured this route.
- **The mechanism may weaken in autumn.** Autumn days have a smaller diurnal range and more frontal or advective
  highs, including highs set overnight or in the morning. The month-specific table carries this in principle (it
  holds Oct-Dec history cells), but the size of the 13-16 effect out of season is unmeasured. This draft predicts
  neither direction.
- **DST.** US DST ends 2026-11-01. The table and the stage both key on local clock hour, so no rule changes. The
  look reports pre- and post-DST segments beside the primary, with no alpha.
- The settlement label is the venue winner. The venue resolves on weather.gov hourly data (EF §10c).

### 7.4 Estimand

**Primary:** t3-r3 minus served, mean Brier, US11, **local hours 13:00-16:59**, all rows with explicit served
fallback.
- Population: promotion-countable market-days. Brier over the complete band support.
- Weights: equal snapshot weights within a market-day cell, then equal market-day weights.
- **Fixed-market date-clustered inference:** the 11 markets are fixed, and dates are resampled as clusters (2,000
  draws, seed fixed at freeze). The interval is a percentile 95%, one-sided alpha 0.025.
- **Pass** requires all three of:
  - the upper bound < 0;
  - at least 8 of 11 markets with a negative per-market mean;
  - an estimate <= -5% of the window's own 13-16 served minus market gap (EF §1d).

**Why 13-16 is primary, and why this is not an hour gate:**
- The candidate runs at every hour. Only the *scoring population* of the primary is the 13-16 block.
- It was chosen from development because that block is where no restoration reaches (D-RUNG1C) and it is
  maker-relevant (inside 00-16).
- Rule 8 concerns hour gates on NBP/NBM guidance. t3-r3 uses no guidance.

**Reported beside the primary, with no alpha:**
- the crossed date x market estimate and interval (81a statistics, seed 20260921);
- 00-16;
- **17-23 separately** (cosmetic for the maker, real for Brier; market Brier about 0.0008, so no ratio there);
- 13-14 and 15-16;
- all hours;
- matched rows, labelled "selected on availability";
- candidate minus market, with the ratio where interpretable;
- the tail lens (EF definition applied to the window's own rows, its share stated);
- per-market deltas;
- coverage and fallback reasons;
- METAR freshness at snapshot time;
- served release ids;
- the pre/post segments for DST, a METAR-cadence change and the rung-1 landing.

**The 2026-09-30 DECISION_LOG guardrails, verbatim** (row 2026-09-30, swarm items):

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never
> re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only,
> amendment states its motivation)

How this draft meets them:
- **Future and new dates only:** all dates are >= 2026-10-15 (section 7.2). The swarm's 111h-table numbers are used
  only for sizing (before stratum) and description, never as an evaluation input.
- **No 111h re-read:** no 79a/81a/111h date is re-read.
- **Crossed estimate beside:** yes.
- **Per-market and sign consistency:** the at-least-8-of-11 rule is a pass condition (owner option in section 6).
- **Motivation:** under crossed clustering the 11 market clusters set a variance floor that no number of dates
  removes. Section 6 shows it (MDE80 0.0105 > every planning effect), and EF §10j showed it before. The maker
  quotes exactly these 11 markets, so the decision-relevant claim is "does this stage beat served on our markets
  over future dates". The cost: a pass does not generalise to new markets.

### 7.5 Comparator binding and the rung-1 landing

"Served" means the captured served vector of whatever release served that snapshot, with its release id recorded.

If the owner lands the evening lock-in fix (rung 1, form A) inside the window:
- **13-16 is barely affected:** rung 1 moves 13-16 by -0.0006, and S3-S5 by a further -0.0020 (D-RUNG1C).
- **17-23 will turn against t3-r3:** t3-r3 minus rung 1 is +0.0035 [+0.0011, +0.0056], 1/11. That is expected, is
  not a failure, and is reported as a pre/post segment.

The owner should preferably land rung 1 **before** the first eligible date, so the comparator is stable.

### 7.6 Falsifiers and validity conditions (declared up front)

**Falsifiers.** None may be rescued by amendment on the same dates.
1. **Route closed.** The 13-16 fixed-market upper bound is >= 0 at N = 45. The remaining-rise stage is then closed
   for US11 out of season under the current rules.
2. **Immaterial.** The estimate is above -5% of the window's 13-16 gap.
3. **Not fleet-wide.** Fewer than 8 of 11 markets are negative. Report which markets; no serving proposal.
4. **Crossed disagreement.** The crossed point estimate has the opposite sign. Report the result as
   market-specific, not a pass.
5. **Harm guardrails.**
   - If 00-12 or all hours has a fixed-market interval entirely above 0, there is no all-hours serving proposal.
   - If 17-23 lies entirely above 0 while served is still pre-rung-1, it is reported as evening harm.
   - **No hour gate may be added post hoc.** A gated or composed form (for example d2-c1) needs its own
     pre-registration on new dates.

**Validity conditions.** If one fails, the look is VOID (no pass, no fail). The dates are spent.
- **PIT:** any stage input with an availability time after `captured_at_utc`.
- **Artifact:** the artifact hash differs from the frozen hash on any eligible row.
- **Coverage:** 13-16 stage coverage is below 90% of snapshots (development: above 99%).
- **Freshness:** the median age of the newest METAR row behind F, at 13-16 snapshots, is above 30 minutes. The
  development basis was +10 min, and the effect fades with staleness.
- **Replay:** captured-input replay does not reproduce the stored shadow vector to within 1e-12 on 100% of rows.
- **Window leakage:** any reserved-window date was read before the look.

## 8. Proposed reservation block (81a form). INACTIVE; owner decision required

> **PROPOSED, NOT ACTIVE.** Reserve the first 45 promotion-countable local target dates on or after
> {first eligible date per §7.2, >= 2026-10-15}, for the frozen remaining-rise stage t3-r3
> (`remaining_rise_floor_v1`, artifact `remaining_rise_pmf_v1` {artifact SHA-256}), bound to {this file's SHA-256
> and freeze commit}.
> - **Primary:** equal market-day mean t3-r3-minus-served Brier, US11, 13:00-16:59 local, all rows with served
>   fallback, promotion-countable, fixed-market date-clustered inference.
> - **Beside the primary:** the crossed date x market estimate, 17-23 separately, 00-16, and per-market signs
>   (>= 8/11 required).
> - **alpha:** one-sided 0.025 for the single candidate, with no interim outcome looks. The sealed pre-boundary
>   campaign ledger is not spent.
> - **Reserved dates:** do not read, enumerate outcomes, score, or substitute them for any remaining-rise /
>   decided-band / evening-collapse candidate, and do not modify t3-r3 or its artifact, without a new explicit
>   owner decision. Accrue 45 countable dates with the fixed 11-market support. No model fitting or selection.

**Collisions the owner must resolve before activation:**
- **The trigger does not fit.** The reservation file's trigger is "first retrain candidate frozen", and this is a
  serving-stage candidate. Applying the mechanism here is itself an owner decision.
- **Absolute vs narrow scope.** The file's binding rules make a declared window absolute, which would stop MM paper
  scoring and collide with the 88a desk-study panel (UTC 10-15..10-30, retention hold). **Narrow scope is
  recommended:** reserve only against reading or modifying the remaining-rise family. The candidate is frozen and
  zero-parameter, so unrelated research cannot fit to it.
- **Overlap with the morning draft (MG-1, D-MORNING).** Both drafts would reserve the same calendar.
  - Their candidates differ, their primaries are different hour blocks (00-16 vs 13-16, which overlap at 13-16), and
    each has its own one-sided 0.025.
  - If both are activated, the owner should state that the two alpha levels are separate families, or split 0.05
    across them.
  - Running both stages in shadow on the same dates is fine. Neither modifies the other.
- **Fallback if not activated:** run the evaluation as a labelled development read on new dates, with no
  confirmation claimed.

## 9. What this draft does NOT claim

- **No development read is evidence.** t3-r3's 13-16 -0.0116 and 17-23 -0.0219 come from previously inspected
  dates. The before-stratum figures are used only for sizing.
- **No market parity.** t3-r3 minus market is +0.0124 at 13-16 and +0.0079 at 17-23. d2-c1 still trails the market
  in every block.
- **No serving result.** The stage has never run on the live path. d2-r3f only shows that the captured anchor is
  sufficient on this table.
- **The evening fix is not decided here.** Rung 1 (restore and re-anchor the lock-in, gate S7, optionally bundle
  S3-S5) is an owner decision with its own replay and release gate. Nothing here makes it, and nothing was changed.
- **The power figures are plug-in plans.** At the halved effect, the default pass rule is underpowered (section 6).
- **Closed threads stay closed.** Recalibration, hour gating of guidance, NBH/NBS/MOS capture and the 111h all-hours
  verdict are not reopened. This draft authorises no landing, serving, promotion, reservation, alpha, Scheduler
  work or live activity.

## Sources

- **Swarm agent outputs (C:\swarm\out\):**
  - t1, t2, t3, t4, t7, t15 (the family);
  - refute-pit-t1, refute-stat-t1, refute-pit-t3, refute-stat-t3. **T1, refute-pit-t3 and refute-stat-t3 reports are
    orchestrator reconstructions**; the numbers cited are from their result.json or score files, or reproduced by D2;
  - d-defect, ladder, d-rung1c;
  - t20 (serveability), t19 (tail);
  - d2 (this run: `d2_run.json`, `*.score.json`, `run.log`).
- `docs/research/model-parity-swarm-2026-10-04/d-morning-v2-guidance-prereg-draft.md` (structure, reservation form,
  calendar overlap)
- `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md` (81a reservation form)
- `docs/operations/DECISION_LOG.md`: 2026-09-30 swarm row (guardrails); 2026-10-02 forecast-data plan (METAR
  cadence); 2026-10-03 merge-policy lift
- `docs/operations/ESTABLISHED_FINDINGS.md` §1b.4, §1c, §1d, §2, §10c, §10e, §10j, §10p
- `C:\swarm\DESIGN.md` §1 rules 1-9 and §6
