# DRAFT, UNSIGNED, DEVELOPMENT: family T5 deep dive and NBH pre-registration draft

> **DRAFT. UNSIGNED. DEVELOPMENT ONLY.** Written by swarm agent D1 on 2026-10-04, about 03:05–03:30 America/Toronto.
> Nothing here is frozen. Nothing here is a reservation, an α allocation, a capture change, a serving change, a config
> change or a merge. Every number comes from a development read of the 111h table. The from stratum (2026-08-23..09-29)
> had already been read by 79a, 81a and 111h, and the before stratum (08-01..08-22) by 81a and 111h.
> **None of these numbers is evidence.** Reservation status re-read: **NONE RESERVED**
> (`docs/operations/reserved-confirmation-window.md`).
> HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`. Rows after 2026-09-29: 0.
> Leakage tripwire: none.

## Verdict first

**Recommendation: do not capture NBH, and do not activate this pre-registration.** The draft is written so the route
can be *closed* on a frozen form. It also gives a form to use if the owner wants an NBH test anyway (the 2026-09-30
DECISION_LOG row approved an "NBS/NBH probe after 111h").

- **Family T5 has one member route,** "NBH latest cycle, maximum over the remaining hours". The pre-registered
  candidate is **NBH-1 = `t5-r1` verbatim**, with its one open tie rule fixed (§2).
- **Every block's gain against served is already available without NBH:**
  - **00-12:** the captured NBM v2_mean read (MG-1 = `r-t5-inc-c1`) does better. Paired NBH-1 − MG-1:
    - 00-05 +0.0069 [−0.0000, +0.0145], 2/11 markets negative
    - 06-09 +0.0055 [−0.0018, +0.0139], 5/11
    - 10-12 +0.0062 [−0.0018, +0.0152], 5/11
  - **00-16 increment over MG-1:** **+0.0027 [−0.0037, +0.0098]**, 5/11, before stratum +0.0044. It has the wrong
    sign in both strata (R-T5-INC; reproduced exactly here).
  - **13-14:** NBH-1 − MG-1 is +0.0001 [−0.0076, +0.0083].
  - **15-16:** NBH-1 − MG-1 is −0.0185 [−0.0260, −0.0109]. This is truncation of the remaining-rise, and the
    no-source METAR rung does the same: NBH-1 − t3-r3 at 15-16 is +0.0005 [−0.0042, +0.0055] (LADDER).
  - **17-23:** NBH-1 is a floor collapse. A pure collapse that uses no NBH beats it by 0.0005 on the same rows
    (R-PIT-T5). Its −0.0047 [−0.0076, −0.0025] over ladder rung 2 equals the no-source collapse's own gain over rung 2
    (D-DEFECT d1, about −0.0033 beyond r2; LADDER §4).
- **No positive planning effect exists for the NBH increment,** because the development estimate has the wrong sign.
  80% power is therefore unattainable for any effect the data support. For a hypothetical 81a-sized increment
  (0.00667), fixed-market joint power with the ≥ 8/11 sign rule is 0.68 at 45 dates and 0.70 at 90. On the crossed
  estimate it is 0.65 at 45 dates.
- **17-23 is reported separately.** It is cosmetic for the maker and real for Brier, and it belongs to the
  evening-defect family (D-DEFECT), not to NBH.

## 1. What family T5 is, and why NBH-1 is the candidate

- **Members:** `t5-r1` (zero parameters), `t5-r2` (t5-r1 plus a per-block bias b and spread scale s fitted on NBH
  history 07-25..07-31), and the diagnostic `t5-d1` (+60 min). The board lists only T5 for this family.
- **Classes are identical for r1 and r2** (T5 raw_results), so the swarm made no within-agent selection.
- **Why NBH-1 = `t5-r1`:**
  1. It is the only member with zero fitted parameters. Its only constants are σ ≥ 1 °F, integer discretisation,
     H = max(B, X), and the eligibility rule.
  2. It is declared expectation-first. T5 registered its morning/night expectation and an afternoon falsifier
     before scoring.
  3. It was reproduced bit-exactly from the registry text alone (T23, to 1e-12).
  4. r2 adds a frozen parameter file (b, s per block) that was fitted on 7 days of July history. That buys no class
     change and adds a train/serve parity surface.
- **T1 is not a member of this family.** T1 is the decided-band collapse, family "remrise". The task asks for T1's
  serving form and its 81a interaction only if T1 is a member. The 17-23 overlap still has to be stated (§4.3).

## 2. Candidate rule NBH-1, fixed verbatim (registry `t5-r1`, sha256 `c6cd29cb…7231e2`)

> **NBH-1.** At snapshot *t* for a US11 market whose station is S and whose local target date is D, let
> E = local midnight ending D.
> - **Eligible cycles.** NBM NBH text-bulletin cycles (`blend.YYYYMMDD/HH/text/blend_nbhtx.tHHz`) are eligible only
>   if their availability time is ≤ `captured_at_utc`. In production, the availability time is the later of the
>   object's S3 LastModified and production's first-seen time of the bytes.
> - **Remaining-hours read.** For every top-of-hour UTC valid time v in (t, E], take TMP and TSD from the latest
>   eligible cycle (largest cycle time) that carries v. Older eligible cycles fill only hours the latest one lacks.
> - **Centre and spread.** μ = max TMP over those v. σ = max(TSD at the argmax v, 1 °F). **Tie rule, fixed here:**
>   when several v share the maximum TMP, the earliest such v supplies TSD. This matches `t5_nbh_latest.py` and
>   T23. T23 shows the choice changes σ in 13.9% of snapshots, so it is frozen and never revisited.
> - **Distribution.** X ~ Normal(μ, σ), discretised on integers (mass on [k − 0.5, k + 0.5)). Then H = max(B, X),
>   where B = floor(F + 0.5) and F = 81a's floor, the maximum of the finite captured `guidance_physical_floor`,
>   `high_so_far` and `trusted_current_max`. Band probability = P(H ∈ band), renormalised, and then the 81a floor
>   mask is applied.
> - **Fallback.** Served is used when there is no eligible cycle, any v in (t, E] is uncovered, there is no captured
>   floor, or the mass is 0.
> - **Scope.** Zero fitted parameters, no hour gate (DESIGN rule 8), no pooling with served, all local hours.
> - **DST rule (new; inactive in development).** E is computed in the market's IANA zone. On 2026-11-01 the
>   remaining-hours set follows the zone's wall clock, which gives a 25-hour local day.

## 3. Combined candidate (POST-HOC; sizing only, never evidence)

**`d1-t5-pc1`** (registered 03:01:31, before scoring):
- p = ½ NBH-1 + ½ MG-1 where both are covered; whichever one is covered otherwise; served if neither.
- Zero parameters, no gate.
- It was chosen *after* seeing T5, R-T5-INC and LADDER, so it is post-hoc. DESIGN halves its effect for sizing.

Development, from stratum, all rows (before stratum beside):

| Block | pc1 − served | pc1 − MG-1 (mkts neg; before) | pc1 − ladder rung 2 (mkts neg; before) |
|---|---|---|---|
| 00-05 | −0.0140 [−0.0211, −0.0079] | +0.0002 [−0.0032, +0.0036] (5; +0.0009) | +0.0002 (5; +0.0009) |
| 06-09 | −0.0150 [−0.0218, −0.0088] | −0.0011 [−0.0047, +0.0026] (7; +0.0005) | −0.0011 (7; +0.0005) |
| 10-12 | −0.0105 [−0.0164, −0.0048] | −0.0015 [−0.0054, +0.0027] (7; −0.0005) | −0.0015 (7; −0.0005) |
| 13-14 | — | **−0.0047 [−0.0088, −0.0007] (10; −0.0039)** | −0.0047 [−0.0088, −0.0007] (10; −0.0039) |
| 15-16 | — | −0.0145 [−0.0195, −0.0099] (11; −0.0110) | −0.0135 [−0.0185, −0.0091] (11; −0.0097) |
| 17-23 | −0.0190 [−0.0315, −0.0094] | −0.0272 (11) | **+0.0045 [+0.0024, +0.0065] (0; +0.0061)**, worse than rung 2 |
| **00-16** | **−0.0127 [−0.0188, −0.0073]** | **−0.0027 [−0.0061, +0.0007] (8; −0.0014)** | −0.0026 [−0.0059, +0.0008] (8; −0.0013) |

**Reading the table:**
- Pooling NBH with MG-1 adds about −0.0027 in 00-16 (halved for sizing: about −0.0014). The interval includes 0, so
  this is WEAK.
- The only interval that excludes 0 beyond rung 2 outside 15-16 is **13-14: −0.0047, 10/11 markets.** LADDER found
  the same borderline 13-14 signal for MOS/NBE t7-r2 (−0.0063).
- Part of that 13-14 gain may be the remaining-hours *form*, not NBH content. MG-1 reads a whole-day maximum.
  Nothing on this table separates the two, because v2 has no hourly path.
- At 15-16 the no-source t3-r3 rung beats rung 2 by −0.0181 (LADDER), which is more than pc1's −0.0135.
- At 17-23 pc1 is worse than rung 2.

**Power for pc1 − MG-1** (`d1-t5-plan2`, before stratum only):
- 00-16, at the halved effect 0.00135: fixed-market power 0.41 (interval) and 0.24 (joint with ≥ 8/11) at 45 dates;
  0.69 and 0.39 at 90. Crossed power 0.26 even with unlimited dates. **80% is unattainable.**
- 13-14, at the halved effect 0.0020: fixed joint power 0.09 at 45 and 90 dates. **Unattainable.**
- The 13-14 hint therefore cannot justify a capture. If the owner ever wants it tested, it needs its own
  pre-registration on new dates, written as a pool with no hour gate (rule 8).

## 4. Sensitivity

### 4.1 Availability (+15 min / +1 h / +2 h; R-T5-INC and R-PIT-T5)

NBH-1 − served, from stratum, all rows:

| Block | +0 | +15 min | +60 min | +120 min |
|---|---|---|---|---|
| 00-16 | −0.0073 [−0.0136, −0.0009] 8/11 | −0.0073 | −0.0069 [−0.0129, −0.0008] | −0.0065 [−0.0120, −0.0008] |
| 13-16 | −0.0097 | −0.0097 | −0.0096 | −0.0095 |
| 17-23 | −0.0282 | −0.0282 | −0.0282 | −0.0282 |

- No class changes.
- Coverage: 109,399 snapshots at +0, 106,079 at +60 min, 101,957 at +120 min.
- The increment over MG-1 stays wrong-signed under every shift tested (see §4.2: +0.0033 at +60 min with a 25%
  drop).
- Measured S3 lag (A-NBH, R-PIT-T5): median 42 min after the cycle; 00Z about 77 min; 12Z about 95 min; p99 136 min.
  Outliers reach +14 h (09-24 00-12Z). Those were never used, because newer cycles had already landed.

### 4.2 Coverage loss and capture cadence (`d1-t5-s1`, new in this dive)

| Variant | Coverage | Median cycle age, 00-16 (h) | 00-16 vs served | 13-16 | 17-23 | 00-16 NBH − MG-1 |
|---|---|---|---|---|---|---|
| all 24 cycles (t5-r1) | 98.73% | 1.3 | −0.0073 LEAD | −0.0097 | −0.0282 | +0.0027 |
| 10% of cycles dropped | 98.49% | 1.35 | −0.0072 LEAD | −0.0097 | −0.0282 | +0.0028 |
| 25% dropped | 97.47% | 1.46 | −0.0071 LEAD | −0.0097 | −0.0282 | +0.0029 |
| 50% dropped | 95.56% | 1.82 | −0.0067 LEAD | −0.0095 | −0.0282 | +0.0033 |
| every 3 h (00, 03, …, 21Z) | 95.86% | 2.32 | −0.0068 LEAD | −0.0095 | −0.0282 | +0.0032 |
| every 6 h (00, 06, 12, 18Z) | 92.75% | 3.78 | −0.0064 LEAD | −0.0095 | −0.0282 | +0.0036 |
| +60 min and 25% dropped | 94.28% | 2.46 | −0.0067 LEAD | −0.0096 | −0.0282 | +0.0033 |

- Dropped cycles are chosen at random, seed 20261004, and the same cycle is dropped for all 11 stations.
- The 00-16 interval excludes 0 in every variant. Example: every 6 h, −0.0064 [−0.0120, −0.0008].
- The 10-12 block stays WEAK.

**Readings:**
1. NBH-1 degrades gracefully. Most of its value survives a capture every 3 h, which is 8 objects a day.
2. Losing coverage moves the increment over MG-1 further toward harm, never toward an increment.

### 4.3 17-23, reported separately (cosmetic for the maker, real for Brier)

- **Against served:** NBH-1 is −0.0282 [−0.0400, −0.0188], 11/11 markets, before stratum −0.0320.
  - Candidate − market: +0.0016 [+0.0004, +0.0038].
  - The ratio to market is not interpreted, because market Brier is about 0.0008.
  - It removes 95.6% of the 17-23 tail excess (this table's tail: 6.075% of rows carry 70.38% of the excess; EF's
    4.387%/64.14% comes from the sealed in-season panel and is not mixed in).
- **Mechanism:**
  - In 97.5% of covered 17-23 snapshots the NBH remaining maximum is below the floor bucket. NBH-1 therefore puts
    nearly all of its mass on the floor band (R-PIT-T5, R-STAT-T5).
  - With the collapse rows set back to served, the effect is −0.0003 [−0.0016, +0.0003] (R-STAT-T5).
  - The unconditional no-source collapse scores −0.0287 on the same rows.
  - This is the D-DEFECT serving defect: the lock-in stages read a WU-only `history_max`, which has been None since
    2026-06-30.
- **The 81a floor:** NBH-1's B is the 81a floor bucket. H = max(B, X) moves below-floor mass *onto* the floor band
  before the 81a mask runs. That is stronger than the mask, and it never weakens the floor.
- **T1, for the record (not a member):**
  - Serving-stage form: frozen X = 1, N = 1, H = 15 plus a q table fitted on IEM METAR history up to 07-31. It needs
    the at-t METAR temperature, which production captures (T20).
  - 81a interaction: T1 removes mass *above* the running-max band, and the 81a floor removes mass *below* it. Both
    anchor on the same floor bucket.
  - The owner-decision fix for this whole evening family is D-DEFECT's proposal: re-anchor S1/S2 (and S3-S6) on
    `guidance_physical_floor` and gate S7. It is a proposal, not done.
- **NBH is not needed in 17-23**, and this draft claims nothing there.

### 4.4 The 00-16 robustness the refuters found (R-STAT-T5)

Against served:
- 00-16 is exactly at the 8/11 edge. Dropping any one of 5 markets, or week W36, takes the interval across 0.
- Bonferroni over 63 rules crosses 0.
- R-STAT-T5 downgrades 00-05 and 00-16 to WEAK. Only 06-09 and 17-23 stand.
- 13-16 is disqualified as an NBH lead: 51% of its rows are collapse rows, and they carry 78% of the delta.

## 5. Serveability and capture plan (design only; recommended: DECLINE)

- **Serveability class:** *needs new capture* (NBH text bulletin, hourly). NBH-1 also depends on landing the MG-1
  comparator's parser repair (83a/83b) if the primary in §7 is to be served side by side.
- **Capture design**, if the owner ever approves it:
  - **Source:** S3 `noaa-nbm-grib2-pds/blend.YYYYMMDD/HH/text/blend_nbhtx.tHHz`, anonymous HTTPS, free. NOMADS is
    the fallback.
  - **Cadence:**
    - Hourly is the registered form.
    - Every 3 h keeps most of the value (§4.2). It is a different candidate and would need its own freeze.
    - Poll from cycle + 35 min every 5 min, until the object appears or cycle + 6 h.
  - **Bytes:**
    - About 29 MB per national object. 24 objects a day is about 0.7 GB/day of download; every 3 h is about
      0.23 GB/day.
    - Extract the 11 station blocks (about 0.15 MB/day) and do not keep the raw object on the 16 GB host.
    - The 83b one-fetch-per-cycle reuse fix is a prerequisite (exam premortem §D blocker (c)).
  - **Stored per cycle:** station block text, cycle, S3 LastModified, ETag, sha256 of the full object, production
    `first_seen_at`, and parser version. Availability = max(LastModified, first_seen_at).
  - **Stored per snapshot**, as non-selectable diagnostics: μ, σ, the cycle used, the hours filled from older cycles,
    and the shadow NBH-1 vector. Captured-input replay must reproduce the vector from the stored station blocks.
  - **Code surface:**
    - a new text parser (TMP/TSD rows, fhr to valid time including the day rollover; R-PIT-T5 verified this on
      KLGA 09-10 14Z);
    - a payload contract;
    - a post-model shadow stage `nbh_remaining_max_v1`, version-bound in the release manifest;
    - a versioned train/serve parity change. The served model selects no NBH feature, so there is no retrain.
  - **Landing:** roll-sensitive. It goes through `scripts/ops/roll_verdict.ps1` and the 01:00–04:00 quiet window,
    after 10-13 under the exam-period merge policy.
- **Cost against value:** a new daily network job and parser for a source whose increment over captured inputs is
  null in 00-16 and is reproduced by no-source rungs in 15-16 and 17-23. T20 and LADDER reach the same conclusion
  independently.

## 6. Dates and season

**First eligible date** = the first local target date D that satisfies all of the following:
- (a) D ≥ **2026-10-15**, i.e. after 2026-10-14;
- (b) the NBH capture (§5) was landed and verified in production before Eastern 00:00 of D. Verification means all
  three capture workers recovered, and at least one full prior day shows 24/24 cycles for all 11 stations with the
  availability evidence recorded;
- (c) the comparator MG-1 is being captured in shadow on the live parser-v2 path. This requires 83a/83b to have
  landed (see the D-MORNING draft);
- (d) D is after the freeze commit's Toronto date;
- (e) D is promotion-countable.

Every countable date after that is counted, with no skipping. Today none of (b)-(c) is scheduled, so no first
eligible date exists yet.

**Season statement.**
- Every eligible date is **out of season.** Mid-October onward is outside the May–June season the served model was
  trained on (EF §1c and §4: "we evaluate in-season and serve out-of-season"). It is also outside the Aug–Sep window
  where every number here was read.
- Nothing guarantees that a null increment (or an effect) transports. Autumn NBH skill, diurnal shape and the
  timing of the 13-16 peak all differ.
- US DST ends 2026-11-01. The §2 DST rule handles that date.

## 7. Estimand

**Primary (maker-relevant): NBH-1 minus MG-1, mean Brier, US11, local hours 00:00–16:59, all rows with explicit
fallback.**
- **Fallback:** NBH-1 falls back to served. MG-1 falls back to served.
- **Why the comparator is MG-1 and not served:** the only decision NBH evidence can drive is "capture NBH or not".
  NBH-1 against served is already dominated by MG-1, which needs no new source.
- **Population and weights:** promotion-countable market-days; Brier over the complete band support; equal snapshot
  weight within a market-day, then equal market-day weight; no hour reweighting.
- **Fixed-market date-clustered inference:** the 11 markets are fixed, dates are resampled as clusters (2,000 draws,
  seed fixed at freeze), with a percentile 95% interval and one-sided α 0.025.
- **Pass** requires all three:
  - the upper bound < 0;
  - ≥ 8/11 markets with a negative mean;
  - an estimate ≤ −5% of the window's own 00-16 served − market gap (EF §1d bar).

**Reported beside it, with no α:**
- the crossed date × market estimate (81a statistics, seed 20260921);
- NBH-1 − served (00-16 and per block);
- **17-23 separately** (ratio not interpreted);
- 13-14 and 15-16 separately;
- NBH-1 − ladder rung 2, if that rung runs in shadow;
- matched rows, labelled "selected on availability";
- the tail lens on the window's own rows;
- the per-market table;
- coverage and fallback reasons;
- cycle-age distribution;
- served release ids.

**The 2026-09-30 DECISION_LOG guardrails, verbatim** (`docs/operations/DECISION_LOG.md`, row 2026-09-30, swarm items):

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never
> re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only,
> amendment states its motivation)

**How this draft meets them:**
- **Future and new dates only:** every date is ≥ 10-15 (§6).
- **No 111h, 79a or 81a read:** none of those dates is re-read.
- **Crossed estimate beside:** yes.
- **Per-market and sign consistency:** the ≥ 8/11 condition is in the pass rule.
- **Motivation:** with 11 market clusters, crossed resampling sets a variance floor that no number of dates removes
  (EF §10j). The maker quotes exactly these 11 markets. The cost is stated: a pass does not generalise to other
  markets.

## 8. Power and MDE80 (`d1-t5-plan1`; before stratum only, 21 dates × 11 markets; sizing, never evidence)

Settings: one-sided α 0.025, 2,000 draws, seed 20261004.

| Estimand, 00-16 | N new dates | Fixed MDE80 | Fixed power (interval / joint ≥ 8 of 11) | Crossed MDE80 | Crossed power |
|---|---|---|---|---|---|
| **NBH-1 − MG-1 (primary)**; planning effect: **none** (before +0.0044, wrong sign) | 45 | 0.0040 | at 0.003: 0.57 / 0.19; at 0.00667: 1.00 / **0.68** | 0.0081 | at 0.00667: 0.65 |
| | 90 | 0.0029 | at 0.003: 0.82 / 0.16; at 0.00667: 1.00 / **0.70** | 0.0072 | 0.73 |
| | unlimited | → 0 | joint is capped by market heterogeneity | 0.0059 | 0.87 |
| NBH-1 − served (beside); half effect 0.00386 | 45 | 0.0038 | 0.77 / **0.01** | 0.0127 | 0.11 |
| | 90 | 0.0027 | 0.98 / 0.01 | 0.0111 | 0.17 |
| | unlimited | — | — | 0.0109 | 0.18 |
| NBH-1 − served, 17-23 (no α) | 45 | 0.0049 | at 0.0133: 1.00 / 0.92 | 0.0140 | 0.74 |

**The power statement, plainly:**
- **80% power is unattainable** for the primary at any effect the development data support, because they support
  none.
- Even for a hypothetical 81a-sized increment, the ≥ 8/11 sign rule caps joint power at about 0.70. The cause is
  that 7 of 11 markets have the opposite (positive) sign in the before stratum. Five of them are at +0.008 or more:
  Atlanta, Austin, Denver, Los Angeles and NYC.
- **The 11-market-cluster floor:** the crossed MDE80 for NBH-1 − served is 0.0109 even with unlimited dates. That is
  larger than the full development effect (0.0077), so 80% is unattainable on the crossed estimate. This reproduces
  EF §10j's cap.
- For NBH-1 − served, the plug-in joint power is very low (0.01). Three markets (Atlanta, NYC, San Francisco) are
  positive in the before stratum, and the plug-in keeps their deviations fixed.
- Plug-in figures come from 21 August dates. Out-of-season variance may differ.

**Planned N**, if the owner activates anyway: 45 countable dates, one look.

## 9. Falsifiers and validity conditions (declared up front)

**Falsifiers:**
1. **Route closed:** the primary estimate is ≥ 0, or its upper bound is ≥ 0 at N = 45. "Capture NBH for T+0" is then
   closed for US11 under the current rules, and no amendment may revisit it on the same dates.
2. **Immaterial:** the estimate is above −5% of the 00-16 served − market gap. The effect is too small to pay for a
   capture.
3. **Not fleet-wide:** fewer than 8/11 markets are negative.
4. **Crossed disagreement:** the crossed point estimate has the opposite sign to the fixed-market one. The result is
   then reported as market-specific.
5. **Harm:** if NBH-1 − served in 00-16 has an interval entirely above 0, report it as harm. No hour gate may be added
   post hoc.

**VOID conditions** (the dates are spent and not re-run):
- any NBH input used before its availability time;
- 00-16 coverage below 90% (development: 98.7%);
- captured-input replay failing to reproduce the shadow vector to 1e-12 on 100% of snapshots;
- any reserved-window date read before the look;
- the MG-1 comparator not running on parser v2.

## 10. Proposed reservation block (81a form). INACTIVE; owner decision required; recommended NOT to activate

> **PROPOSED, NOT ACTIVE.** Reserve the first 45 promotion-countable local target dates on or after
> {first eligible date per §6, ≥ 2026-10-15}, for the frozen NBH remaining-hours candidate NBH-1
> (`nbh_remaining_max_v1`, registry `t5-r1` text plus the §2 tie and DST rules), bound to {this file's SHA-256 and
> freeze commit}.
> - **Primary:** equal market-day mean NBH-1-minus-MG-1 Brier, US11, 00:00–16:59 local, all rows with fallback,
>   promotion-countable, fixed-market date-clustered inference.
> - **Beside the primary:** the crossed date × market estimate, NBH-1 − served, 17-23 separately, and per-market
>   signs (≥ 8/11 required).
> - **α:** one-sided 0.025, single candidate, no interim outcome looks. The sealed pre-boundary campaign ledger is not
>   spent.
> - **Reserved dates:** do not read, enumerate outcomes, score, or substitute them for any NBH or remaining-hours
>   guidance candidate, or modify NBH-1, without a new explicit owner decision. Accrue 45 countable dates with the
>   fixed 11-market support. No model fitting or selection.

**Collisions the owner must resolve before activation** (the same as the D-MORNING draft):
- The reservation file's trigger is "first retrain candidate frozen", and NBH-1 is not a retrain.
- A declared window is absolute today. It would collide with MM paper scoring and with the 88a desk-study panel.
- A narrow scope, covering only the NBH and remaining-hours family, needs an explicit exemption in the reservation
  file.
- Sharing the MG-1 comparator with the D-MORNING reservation means both could run on the same dates. That is
  acceptable only if their α is accounted for separately.
- **Fallback if not activated** (recommended): run nothing. "Capture NBH for T+0" is closed by R-T5-INC, LADDER, T20
  and this dive.

## 11. What this draft does NOT claim

- **No development read is evidence.** NBH-1 still trails the market in every 00-16 block:
  candidate − market 00-16 is +0.0170 [+0.0113, +0.0225].
- **Nothing here is a serving or capture result.** NBH has never run on the live path.
- **Nothing reopens a closed thread:** hour gating, recalibration, NBH capture for the morning, and 111h all-hours C1
  all stay closed.
- **Nothing authorises** a capture change, landing, serving, promotion, a reservation, α, Scheduler work or live
  activity.

## Multiplicity and provenance

- **Registry:** 133 lines at 03:05, including this dive's `d1-t5-plan1`, `d1-t5-s1`, `d1-t5-pc1` and `d1-t5-plan2`.
  All four were registered before scoring.
- **Code:** `tools/research/model_parity/d1_t5_prereg.py` (the `plan2` argument runs the pc1 planning only).
  It imports `t5_nbh_latest` unchanged.
- **Reproduction:** exact. t5-r1 00-16 −0.007295, 17-23 −0.028234; r-t5-inc-c1 00-16 −0.010018; paired +0.002723.
- **Outputs:** `C:\swarm\out\d1\d1_results.json`, `d1_plan2.json`, `d1_t5_pc1_pool.score.json` and
  `d1_t5_s1_*.score.json`.
- **Sources:**
  - `C:\swarm\out\t5`, `r-t5-inc`, `refute-pit-t5`, `refute-stat-t5`, `t23`, `ladder`, `d-defect`, `t20`, `t19`
  - `docs/research/model-parity-swarm-2026-10-04/d-morning-v2-guidance-prereg-draft.md`
  - `docs/roadmap/audits/exam-premortem-2026-10-02.md` §D
  - `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md` (81a reservation form)
  - `docs/operations/ESTABLISHED_FINDINGS.md` §1c, §1d, §4, §10j
  - `docs/operations/DECISION_LOG.md` (2026-09-30)
