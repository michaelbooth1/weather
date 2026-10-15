# DRAFT, UNSIGNED, DEVELOPMENT: T18 family deep dive and pre-registration draft (rung x captured NBM v2 likelihood, RV-1)

> **DRAFT. UNSIGNED. DEVELOPMENT ONLY.** Written by swarm agent D3 on 2026-10-04, about 03:10-03:30
> America/Toronto, on the workstation. Nothing here is frozen. Nothing here is a reservation, an alpha allocation,
> a serving change, a config change or a merge. Owner approval is needed before any part of it takes effect.
> Every number comes from a development read of the 111h table (targets 2026-08-01..09-29). 79a, 81a and 111h had
> already inspected the from stratum (08-23..09-29), so **none of these numbers is evidence** (DESIGN rule 7).
> Reservation status re-read: **NONE RESERVED** (`docs/operations/reserved-confirmation-window.md`).
>
> HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`. Rows with a target after
> 2026-09-29: 0. Leakage-suspect groups: none in any D3 score. Registry lines when D3 finished: 134. D3 registered
> 7 ids (d3-z1, d3-z1s60, d3-z1cov, d3-z1f, d3-pairs, d3-plan1 at 03:01:42; d3-plan2 at 03:06:21), each before the
> score that used it. Code: `tools/research/model_parity/d3_t18_zero.py` and `tools/research/model_parity/d3_plan2.py`.
> Outputs: `C:\swarm\out\d3\` (`d3_run.json`, `d3_plan2.json`, `*.score.json`).

## 0. Verdict

1. **The T18 family is one route: "the METAR remaining-rise rung multiplied by a Gaussian likelihood centred on
   the captured NBM v2 mean".**
   - The family has one member, T18. It survived both refuters. R-PIT-T18 found no leakage, and 00-16 stays LEAD at
     +1 h under all four shift variants. R-STAT-T18 reproduced it to about 1e-17 and found no disqualifying defect.
   - Its new information is captured NBM v2_mean alone. hrrr_high and forecast_high add -0.0005 [-0.0013, +0.0004]
     in 00-16, which is NULL. So the "best three sources" reduce to two: METAR, through the rung, and NBM v2.
   - **00-16 (the part that matters to the maker).** It is the known 79a/81a/111h family, "served under-uses its own
     captured v2 guidance" (EF §10h/§10j/§10p), now applied as a likelihood on the rung.
   - **17-23.** It is the remaining-rise / D-DEFECT family. Against the t3-r3 rung its 17-23 increment is +0.0002,
     so T18 must not be credited with the evening.
2. **Pre-registered candidate: RV-1 = t18-c1 with its constants frozen and anchored on production's floor bucket.**
   Inputs are the rung and v2_mean only. The constants are a = -1.015, b = 1.141 and sigma = 2.355 F, fitted once on the
   before stratum (labels are the IEM METAR daily hourly-row max, never a winner), plus the frozen history rung
   table (≤ 2026-07-31). Why this member (section 2):
   - **It is the simplest serveable form that keeps the family's effect.** One source, three frozen constants, one
     frozen table, no hour gate, and no live fitting. In 00-16 it carries about 95% of t18-r1's increment over the
     rung (-0.0091 of -0.0096).
   - **The strictly parameter-free form, D3's post-hoc d3-z1, is dominated.** d3-z1 sets a = 0, b = 1 and takes sigma
     from the bulletin. Against RV-1 it is +0.0054 [+0.0019, +0.0095] at 15-16 and +0.0059 [+0.0031, +0.0094] at
     17-23, with 0-1/11 markets negative. Its 00-16 is no better (+0.0020 [-0.0015, +0.0059]). Section 2 states this
     choice as a disclosed forking path.
   - **"Zero-parameter at serve" is used here in the T1 sense** (frozen constants, nothing fitted at serve). Under
     DESIGN's strict serveability taxonomy, T18 is "needs retrain (fitted stage)". RV-1's constants already exist
     and would only be frozen and release-bound. It needs no new capture, but it depends on landing the parser repair.
3. **What RV-1 adds over the drafts already written.** RV-1 is effectively MG-1 (D-MORNING) plus the t3-r3 rung
   (D2), composed in **one likelihood with no hour gate**. The rung's prior is sharp late in the day, so it dominates
   the stale whole-day bulletin there with no gate. This is the composition LADDER said "is a pre-registration
   question only (rule 8)".

   Paired, from stratum (development):

   | block | RV-1 - MG-1 | RV-1 - ladder rung 2 | markets negative (vs rung 2) |
   |---|---|---|---|
   | 00-16 | -0.0034 [-0.0078, +0.0007], 8/11 (indistinguishable) | | |
   | 13-14 | | -0.0084 [-0.0144, -0.0031] | 11/11 |
   | 15-16 | | -0.0196 [-0.0260, -0.0136] | 11/11 |
   | 17-23 | -0.0297 [-0.0378, -0.0220] | | |

   **But in 17-23 RV-1 is worse than the restored lock-in** (ladder rung 1 = d-defect-r2): +0.0038 [+0.0010, +0.0066],
   1/11 markets. If RV-1 replaced the served vector after the D-DEFECT fix lands, the evening would lose about 0.004.
   That interaction is an owner decision (section 4).
4. **Proposed primary:** RV-1 minus served, 00-16 local, US11, all rows with served fallback, fixed-market
   date-clustered. Beside it: the crossed estimate, and 13-16 and 17-23 separately with no alpha.
   - **Power (plug-in, before stratum, sizing only):**
     - Fixed-market joint pass (interval plus at least 8/11 markets): 81% at 20 dates and 94.5% at 45, at the
       halved effect of 0.0071. At the 81a-sized 0.00667 it is 84% at 30 dates.
     - **Crossed 80% is unattainable at any number of dates** for the halved effect. The 11-market-cluster floor
       MDE80 is about 0.0077, above 0.0071.
     - The plan is N = 45 countable dates, one look (section 6).

## 1. The family, members and refuter state

| member | rule | 00-16 vs served (from) | 17-23 vs served (from) | refuters |
|---|---|---|---|---|
| T18 t18-r1 (fitted, 3 sources) | rung x N(m, sigma); m = mu_rr + a + Σ b_k (max(S_k,R) - mu_rr); sources chosen by before-stratum NLL | -0.0140 [-0.0195, -0.0089] 11/11 LEAD | -0.0218 [-0.0325, -0.0132] 11/11 | PIT: stands (00-16 LEAD at +1 h in 4/4 variants, +2 h in 3/4). STAT: stands; Bonferroni over 112 x 7 p = 2.4e-4 for 00-16 |
| t18-c1 (attribution control, v2 only; **RV-1's form**) | same with v2_mean only | -0.0134 [-0.0190, -0.0083] 11/11 LEAD | -0.0215 [-0.0323, -0.0129] 11/11 | registered after r1's read (disclosed by T18). Needs a new pre-registration (rule 7) |
| d3-z1 (D3 POST-HOC, strictly parameter-free) | a = 0, b = 1, sigma = max(v2_stddev, 1) | -0.0114 [-0.0186, -0.0054] 11/11 LEAD | -0.0156 [-0.0271, -0.0067] 11/11 | not refuted; post-hoc, sizing only |

**T1 is not a member of this family.** The required T1 statement belongs to the remaining-rise family's deep dive
(D2). RV-1 does share T1's mechanism through the rung. Its interaction with the 81a floor is in section 3.

**Increments, from stratum, paired on the same rows and the same floor (W intervals):**

| block | RV-1 - t3-r3 rung | RV-1 - MG-1 | RV-1 - ladder r2 (MG-1 + lock-in) | RV-1 - ladder r1 (D-DEFECT) | d3-z1 - RV-1 |
|---|---|---|---|---|---|
| 00-05 | -0.0107 [-0.0148, -0.0064] 10/11 | +0.0024 [-0.0017, +0.0069] 3/11 | +0.0024 3/11 | -0.0117 10/11 | +0.0011 [-0.0022, +0.0043] |
| 06-09 | -0.0130 [-0.0181, -0.0076] 10/11 | -0.0012 [-0.0061, +0.0033] 5/11 | -0.0012 5/11 | -0.0152 11/11 | +0.0023 [-0.0024, +0.0072] |
| 10-12 | -0.0084 [-0.0119, -0.0046] 10/11 | -0.0034 [-0.0086, +0.0012] 8/11 | -0.0034 8/11 | -0.0125 11/11 | +0.0016 [-0.0024, +0.0060] |
| 13-14 | -0.0052 [-0.0088, -0.0015] 10/11 | -0.0084 [-0.0144, -0.0031] 11/11 | -0.0084 11/11 | -0.0159 11/11 | +0.0019 [-0.0020, +0.0062] |
| 15-16 | -0.0015 [-0.0043, +0.0014] 8/11 | -0.0205 [-0.0269, -0.0145] 11/11 | -0.0196 [-0.0260, -0.0136] 11/11 | -0.0128 11/11 | +0.0054 [+0.0019, +0.0095] 1/11 |
| 13-16 | -0.0034 [-0.0063, -0.0003] 10/11 | -0.0145 [-0.0203, -0.0093] 11/11 | -0.0140 11/11 | -0.0142 11/11 | +0.0037 [+0.0002, +0.0077] |
| **17-23** | +0.0004 [-0.0011, +0.0023] 5/11 | -0.0297 [-0.0378, -0.0220] 11/11 | +0.0020 [-0.0012, +0.0048] 3/11 | **+0.0038 [+0.0010, +0.0066] 1/11** | +0.0059 [+0.0031, +0.0094] 0/11 |
| **00-16** | **-0.0091 [-0.0123, -0.0055] 10/11** | -0.0034 [-0.0078, +0.0007] 8/11 | -0.0033 [-0.0077, +0.0009] 8/11 | -0.0132 11/11 | +0.0020 [-0.0015, +0.0059] |
| all | -0.0064 [-0.0088, -0.0038] 10/11 | -0.0110 [-0.0163, -0.0060] 11/11 | -0.0018 [-0.0054, +0.0016] 6/11 | -0.0083 11/11 | +0.0031 [-0.0001, +0.0066] |

Read as: in 00-16 the source information is v2. In 00-12 RV-1 is indistinguishable from MG-1, and in 13-16 the rung
is what helps. In 17-23 the restored lock-in beats every member of this family.

## 2. Choice of the pre-registered member, and why

**The candidates considered:**
- **t18-r1** (5 constants, 3 sources). Rejected. hrrr_high and forecast_high add nothing measurable.
  forecast_high's coefficient is -0.27, a correction to served's own output. Imputing a missing hrrr_high
  interacts badly on the 0.2% of rows where it is absent (R-STAT-T18 §6). It also needs an Open-Meteo HRRR capture
  whose run time production cannot see (T20).
- **t18-c1 = RV-1** (3 constants, 1 source). **Chosen.**
- **d3-z1** (no constants). Rejected on the evidence below.

**Why not the strictly parameter-free d3-z1:**
- In the from stratum, d3-z1 is worse than RV-1 at 15-16 (+0.0054, 1/11 markets negative) and at 17-23 (+0.0059,
  0/11). It is also worse than the bare rung at 17-23 (+0.0063 [+0.0030, +0.0105], 0/11).
- The before stratum points the same way in the evening: 17-23 +0.0038, 1/11 markets. In the morning it slightly
  favours d3-z1 (00-16 -0.0012, 6/11).
- **Probable mechanism (a hypothesis, not tested):** the bulletin mean forecasts the day's maximum, and the hourly-row
  settlement maximum sits below it. RV-1's fitted shift a ≈ -1 F absorbs that. d3-z1 cannot absorb it, so it keeps
  mass above the high late in the day.

**Forking path, disclosed.** This choice between two forms was informed by from-stratum reads. The choice is
allowed only because the evaluation is on **new dates**. It adds one more fork to the swarm's multiplicity count:
134 registry lines when D3 finished. The constants themselves were fitted on the before stratum only (rule 3), and
R-STAT-T18 §7 shows the form is stable. Refit on 08-01..08-11, its b_v2 is 1.08 against 1.09, and it holds on
08-12..08-22.

**RV-1, fixed verbatim (proposed text for freezing):**

> **RV-1.** At snapshot *t* for a US11 market and local target date *D*:
> - **Anchor.** F = max of the finite captured `guidance_physical_floor`, `high_so_far` and `trusted_current_max`
>   (81a's floor). B = floor(F + 0.5). If F is missing, the captured served vector is used unchanged.
> - **Rung.** p0(e), e = 0..40 F, is the frozen remaining-rise pmf for (station, calendar month of *D*, local hour of
>   *t*). It is built from routine non-COR IEM METAR history with local dates ≤ 2026-07-31, the hourly-row daily max on
>   days with ≥ 20 routine rows, and the running max at H:30. It is smoothed with a discrete Gaussian kernel (sd 1 F)
>   and negative rises are folded to 0. This is the t3-r3 / T18 `rise_table.parquet` construction, frozen as one
>   artifact with its sha256. If the cell is missing, served is used.
> - **Guidance.** Use the captured parser-v2 NBM read for (station, *D*) only if its availability time (production's
>   first receipt of the bulletin bytes from NOMADS, `response_received_at`) ≤ `captured_at_utc`, asserted, and its
>   period is *D*'s maximum. S = v2_mean.
> - **Model.** mu_rr = B + Σ_e e p0(e). m = mu_rr + a + b (max(S, B) − mu_rr), with **a = −1.0153, b = 1.1405,
>   sigma = 2.3553 F** (frozen; values rounded to 4 dp from `t18_controls.json` `theta_c1`, to be copied exactly at freeze).
>   P(H = B + e) ∝ p0(e) · exp(−0.5 ((B + e − m) / sigma)²).
> - **No v2 read:** m = mu_rr + a, the same constants. The text must choose this branch or "pure rung" at freeze.
>   D3 recommends T18's implementation, which imputes S = mu_rr so the source term is 0. Freeze exactly that.
> - **Bands.** Band probability = Σ of P(H = k) over the integers k in the band; `lte`/`gte` are open-ended.
>   Renormalise, then apply the 81a floor mask.
> - **Scope.** No hour gate, no other source, no fitting at serve, applied at every local hour.

**Serve-form check.** Anchoring on the floor bucket B instead of the IEM METAR join (diagnostic d2-style, registered
as part of d3-plan2) changes almost nothing:
- 00-16: -0.0002 [-0.0010, +0.0007]
- 13-16: +0.0002
- 17-23: +0.0003 [+0.0000, +0.0007]

So the frozen form can use production's own field, and no IEM join is needed at serve. B ≥ R on 29% of rows, because
the floor also takes `high_so_far`. B < R on 0.6%.

## 3. Interaction with the 81a floor and with the D-DEFECT fix

- **Floor.** RV-1 puts zero mass below B by construction (e ≥ 0), so the 81a floor mask is idempotent on its output.
  RV-1 never weakens the floor (rule 4). Rows without a floor fall back to served, as in 81a.
- **D-DEFECT.** The evening serving fix restores S1/S2 (and possibly S3-S5) re-anchored on the floor and gates S7. It
  is a proposal awaiting an owner decision. It and RV-1 are alternative evening paths.
  - RV-1 replaces the served vector. So if RV-1 were ever served at every hour, it would bypass the restored lock-in.
  - On this table that costs +0.0038 at 17-23 (1/11 markets).
  - D3 does not propose an hour split, which would be a gate chosen on this table (rule 8).
  - **Options for the owner:**
    - (a) evaluate RV-1 against the served comparator of the window and report 17-23 without alpha (default);
    - (b) a later, separately pre-registered variant that applies the restored lock-in on top of RV-1, as ladder
      rung 2 did on MG-1. It was not scored tonight and is not proposed here.
- **Comparator binding.** If the D-DEFECT fix lands inside the window, 17-23 and part of 13-16 of "served" change.
  The look reports pre- and post-change segments beside the primary. The primary block, 00-16, is almost untouched by
  rung 1: -0.0002 per LADDER.

## 4. Combined candidate (POST-HOC, effect halved, never evidence)

The family's combined candidate is the rung x v2 likelihood itself. It already combines the two surviving ideas,
MG-1's v2 read and t3-r3's rung. **Sizes for drafting only (development, from stratum, halved):**

| candidate | 00-16 vs served | halved | 13-16 | 17-23 | all |
|---|---|---|---|---|---|
| RV-1 (t18-c1) | -0.0134 [-0.0190, -0.0083] 11/11 | **-0.0067** | -0.0150 | -0.0215 | -0.0158 |
| d3-z1 (parameter-free) | -0.0114 [-0.0186, -0.0054] 11/11 | -0.0057 | -0.0113 | -0.0156 | -0.0126 |
| t18-r1 (as registered) | -0.0140 [-0.0195, -0.0089] 11/11 | -0.0070 | -0.0152 | -0.0218 | -0.0162 |

**Parity view for RV-1** (candidate - market, from stratum):

| block | RV-1 - market | ratio | gap closed |
|---|---|---|---|
| 00-16 | +0.0108 [+0.0067, +0.0145] | 1.22 [1.13, 1.32] | 55% [42, 67] |
| 17-23 | +0.0083 [+0.0056, +0.0111] | not interpreted (market Brier < 0.005) | 72% |
| all | +0.0101 [+0.0070, +0.0130] | 1.29 | 61% |

**Tail lens (this table's definition: 6.075% of band rows carry 70.38% of excess; EF's 4.387%/64.14% comes from
the sealed panel and is not comparable):** RV-1 removes 67% [61, 72] of the 00-16 tail excess and 83% [76, 89] of
17-23. d3-z1 removes 71% and 74%.

**RV-1 still trails the market in every block.** A Brier gain over served is not a gain over market prices.

## 5. Sensitivity

**+1 h availability.** METAR enters at valid + 70 min and v2 at receipt + 60 min. Frozen constants. From stratum:

| block | c1-lag60 vs served | cost vs RV-1 | markets negative (vs served) |
|---|---|---|---|
| 00-16 | -0.0092 [-0.0145, -0.0043] | +0.0042 [+0.0031, +0.0056] | 10/11 |
| 00-05 | -0.0071 | | |
| 06-09 | -0.0141 | | |
| 10-12 | -0.0055 [-0.0112, +0.0000] | | weakest |
| 13-16 | -0.0104 | | |
| 17-23 | -0.0217 | -0.0002 | |

- The loss comes mostly from the rung's METAR timing, not from v2. R-PIT-T18 found the same: the v2 increment over
  the rung is unchanged under delay.
- Production picks up a new METAR maximum about 3.8 min after valid time (T20), so +60 min is very conservative.
- R-PIT-T18's +2 h for t18-r1: 00-16 LEAD in 3 of 4 variants, WEAK in the harshest.
- The same shift on d3-z1 costs +0.0025 in 00-16 (d3-z1s60).

**Coverage loss.**
- Development coverage was 94.9% of snapshots: 93.0% in 00-16 and 99.7% in 17-23. The misses are mostly hour 0,
  before the first METAR row. With the floor anchor, coverage is 95.1%.
- **Whole-day v2 outage on one date in five** (d3-z1cov, measured on the d3-z1 form; RV-1 has the same v2 dependence):
  00-16 costs +0.0011 [-0.0009, +0.0033], and 17-23 changes by -0.0016. The rung carries the outage days.
- A v2 availability gap therefore degrades the stage toward the rung (00-16 rung vs served -0.0043, WEAK). It does not
  break it.

**Availability basis.** v2 availability must be named as production's NOMADS receipt (`response_received_at`), not
S3 LastModified. 0.78% of rows, mostly 2026-09-24, received the bulletin from NOMADS before the S3 copy existed
(R-PIT-T18 §2).

## 6. Serveability and capture plan

**Class:** a post-model serving stage with frozen constants (three numbers plus one table). There is no retrain of the
served model, **no new capture**, and **no new source**. Strictly under DESIGN it is "needs retrain (fitted stage)",
because the constants were fitted. They are frozen now, not refit.

**Dependencies, in order** (each one is a versioned train/serve parity change, an owner decision, roll-sensitive, and
lands only in the quiet window after the 10-13 exam-period merge policy):
1. **Land the parser repair (83a/83b, `2e17ce0eb` plus the reuse index `62e8ff044`; integration 83c).**
   - Production still serves parser v1, which after 13Z reads tomorrow's minimum as today's maximum (EF §10k).
   - RV-1's constants were fitted on parser-v2 values from the 111h re-derivation. The live v2 read must reproduce that
     re-derivation exactly, including the period selection.
   - D-MORNING notes the 111h extractor's last+1-day indexing quirk. Before freezing, a captured-input replay of one
     day must show live v2 equal to the 111h extractor's value on 100% of rows. If they differ, the constants are void
     and RV-1 cannot be frozen.
   - The shadow HGB variant that selects `nbm_prob_tmax_*` must be re-versioned or quarantined, as D-MORNING §2 says.
2. **Capture, per snapshot, as non-selectable diagnostics:** `v2_mean`, `v2_available_at`, cycle and issue time,
   period kind, and the three floor fields. These already exist or can be replayed deterministically. Disk cost is
   negligible, a few numbers per snapshot.
3. **Add the shadow stage `rung_v2_likelihood_v1`.**
   - It binds the constants, the rung-table sha256, parser version 2 and the code hash into the release manifest.
   - It is computed and stored, not served, during the window.
   - Captured-input replay must reproduce the stored vector to 1e-12.
   - Serving it later goes through the readiness and release gates. A pass does not authorise promotion by itself.

**Season of the rung table.** The table has station-month cells for every month, including October-December from
2024-2025 IEM history (about 15.1-15.6k station-hour rows per month), so the out-of-season months are covered. The
constants (a, b, sigma) were fitted on August and are **out of their season** from mid-October on.

## 7. Dates and season

**First eligible date** = the first local target date *D* that satisfies all of the following:
- (a) *D* ≥ **2026-10-15**, i.e. after 2026-10-14;
- (b) parser v2 was landed and verified in production before the first T+0 snapshot of *D* (Eastern 00:00), with all
  three capture workers recovered and a full prior day of manifests at `parser_version = 2`;
- (c) RV-1's inputs (v2 read with receipt time, the floor fields) and the shadow stage have been **captured point in
  time in production** for *D*;
- (d) *D* is after the freeze commit's Toronto date;
- (e) *D* is promotion-countable.

After that, count every countable date, with no skipping. The 2026-10-03 DECISION_LOG row closed the maker-replay exam
NOT EXECUTED and left UTC 2026-09-30..10-13 unread. Those dates are not eligible here.

**Season statement.**
- Every eligible date is **out of season.** The served model's in-season archive is May 10–Jun 30. Every date served
  after that is out of season (EF §4 and §1c, where the gap was measured as fit-in-season, score-out-of-season).
- Mid-October onward is also outside the Aug–Sep window in which RV-1's constants were fitted and the family was
  measured.
- Transport is not assumed. The guidance-vs-served advantage may widen (served runs cool out of season, EF §2) or
  narrow (autumn diurnal shape and guidance spread). This draft predicts neither.
- US DST ends 2026-11-01. The rung is keyed on local hour and there is no gate, so no rule is needed.
- Label = the venue winner (weather.gov hourly data, EF §10c).

## 8. Estimand

**Primary (maker-relevant):** RV-1 minus served, mean Brier, US11, local hours 00:00–16:59, all rows with explicit
served fallback.
- **Population and weights:** promotion-countable market-days; equal snapshot weights within a market-day; equal
  market-day weights.
- **Fixed-market date-clustered inference:** the 11 markets are fixed; dates are resampled as clusters (multinomial
  date bootstrap, 2,000 draws, seed fixed at freeze); percentile 95% interval; one-sided alpha 0.025.
- **Pass** = all three of:
  - the upper bound < 0;
  - at least 8/11 markets with a negative per-market mean;
  - the estimate ≤ −5% of the window's own 00-16 served − market gap (EF §1d bar).

**Reported beside it, with no alpha:**
- the crossed date x market estimate and interval (81a statistics, seed 20260921);
- **13-16 and 17-23 separately.** 17-23 is cosmetic for the maker but real for Brier. Its market Brier is about
  0.0008, so ratios there are not interpreted.
- the blocks 00-05/06-09/10-12;
- all hours;
- matched rows, labelled "selected on availability";
- the paired increment over MG-1's frozen read, if MG-1 also runs in shadow;
- the tail lens with the window's own share;
- per-market table, coverage and fallback reasons, and served release ids.

**The 2026-09-30 DECISION_LOG guardrails, verbatim** (`docs/operations/DECISION_LOG.md`, row 2026-09-30, swarm items):

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never
> re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only,
> amendment states its motivation)

**How each guardrail is met:**
- **Future and new dates only:** section 7, all ≥ 2026-10-15.
- **Never 111h, and no re-reading of 79a/81a/111h:** none of their dates is evaluated. The 111h table is used here only
  as development context, never as evaluation.
- **Crossed estimate beside:** yes.
- **Per-market and sign consistency:** part of the pass rule (at least 8/11).
- **Motivation:** under crossed clustering the 11 market clusters set a variance floor that more dates cannot remove
  (EF §10j; section 9 reproduces it for RV-1). The maker quotes exactly these 11 markets. The cost: a pass does not
  generalise to new markets.

## 9. Power and MDE80 (plug-in on the BEFORE stratum; sizing only, never evidence)

**Setup:**
- Registry `d3-plan2`; RV-1 minus served cells, 00-16, 21 dates x 11 markets.
- The before-stratum estimate is **-0.0143** (10/11 markets negative; San Francisco +0.0006).
- This estimate is **in-sample** for RV-1's own constants. That is a further reason to plan at half of it.
- Simulation: resample N dates with replacement, keep the market structure, re-centre on the planning effect;
  date-cluster normal 95% bound; 2,000 sims; seed 20261004.

**Fixed-market estimand:**

| planning effect | N = 20 | 30 | 45 | 60 | 90 |
|---|---|---|---|---|---|
| half, 0.0071: interval only | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| half, 0.0071: **joint (+ at least 8/11)** | **0.81** | 0.90 | **0.945** | 0.97 | 0.99 |
| 81a-sized, 0.00667: joint | 0.75 | 0.84 | 0.89 | 0.93 | 0.97 |

**Crossed estimand, the 11-market-cluster floor:**
- The market-only SE of the 00-16 cell means is 0.00275, so the **MDE80 with unlimited dates is about 0.0077**.
- That is above the halved effect, 0.0071. Power at unlimited dates is about 74% at the halved effect and about 68% at
  the 81a size.
- **80% is unattainable on the crossed estimate at any number of dates** unless the full development effect carries
  over. This reproduces EF §10j's cap.

**Caveats:**
- The simulation's normal-approximation bound is less conservative than D-MORNING's bootstrap. D-MORNING needed 45
  dates for 80% joint power at 0.0061 on MG-1.
- August variance may not hold out of season.
- The sign rule is the binding condition: San Francisco is near zero.

**Plan: N = 45 countable dates, one look.** Reasons:
- margin for the optimistic approximation and for out-of-season variance;
- it aligns with MG-1's planned window, if both are signed.

**17-23 gets no alpha.** Its crossed floor MDE80 is about 0.0134. Fixed-market joint power at half its before effect
(0.0129) is 97% at 45 dates.

## 10. Falsifiers and validity conditions (declared up front)

**Falsifiers:**
1. **Route closed:** the 00-16 fixed-market estimate is ≥ 0, or its upper bound is ≥ 0 at N = 45.
2. **Immaterial:** the estimate is above −5% of the window's 00-16 served − market gap.
3. **Not fleet-wide:** fewer than 8/11 markets are negative.
4. **Crossed disagreement:** the crossed point estimate has the opposite sign. The result is then reported as
   market-specific, not a pass.
5. **Harm guardrails:**
   - If the all-hours fixed-market interval lies entirely above 0, there is no serving proposal.
   - If 17-23's interval lies above 0, it is reported as evening harm.
   - In either case, no hour gate may be added post hoc.
6. **No rescue on the same dates:** an amendment may not change a, b, sigma or the rung table on the same dates.

**Validity conditions** (if one fails, the look is VOID and the dates are spent):
- **PIT:** any v2 availability after `captured_at_utc`, or a v2 period other than the maximum.
- **Parser:** any eligible row not on parser version 2.
- **Parity:** a live v2 that differs from the 111h-extractor definition on the pre-freeze replay day.
- **Replay:** replay does not reproduce the shadow vector to 1e-12.
- **Coverage:** 00-16 coverage below 85% (development 93.0%).
- **Window leakage:** any reserved-window date was read before the look.

## 11. Proposed reservation block (81a form). INACTIVE; owner decision required

> **PROPOSED, NOT ACTIVE.** Reserve the first 45 promotion-countable local target dates on or after
> {first eligible date per section 7, ≥ 2026-10-15}, for the frozen rung x NBM-v2 likelihood candidate RV-1
> (`rung_v2_likelihood_v1`; constants a −1.0153, b 1.1405, sigma 2.3553 F; rung table sha256 {at freeze}; parser v2),
> bound to {this file's SHA-256 and freeze commit}.
> - **Primary:** equal market-day mean RV-1-minus-served Brier, US11, 00:00–16:59 local, all rows with served fallback,
>   promotion-countable, fixed-market date-clustered inference.
> - **Beside the primary:** the crossed date x market estimate, 13-16 and 17-23 separately, and per-market signs
>   (at least 8/11 required).
> - **Alpha:** one-sided 0.025 for this candidate. If MG-1 is also signed for the same dates, a family alpha of 0.05
>   one-sided, 0.025 each. No interim outcome looks. The sealed pre-boundary campaign ledger is not spent.
> - **Reserved dates:** do not read, enumerate outcomes, score, or substitute them for any NBM-guidance-read or
>   rung-likelihood candidate, or modify RV-1, without a new explicit owner decision. Accrue 45 countable dates with
>   the fixed 11-market support. No model fitting or selection.

**Collisions to resolve before activation** (the same as D-MORNING §7, plus one):
- **Trigger mismatch.** The reservation file's trigger is "first retrain candidate frozen". RV-1 is a frozen-constant
  serving stage.
- **Absolute window.** A declared window is absolute. That stops MM paper scoring and collides with the 88a desk-study
  panel. A narrow scope (reserve only against this family) needs an explicit exemption recorded in the reservation
  file.
- **One family, one window.** MG-1, RV-1, HG-1 (D-HG) and D2's t3-r3 13-16 primary all read the same future dates
  through overlapping mechanisms. D3's recommendation: if only one 00-16 guidance candidate is signed, RV-1 and MG-1
  are indistinguishable on 00-16 in development, and RV-1 is the better all-day stage (13-16 and 17-23). The owner
  picks, and the alpha is split if more than one is signed.
- **If the reservation is not activated,** run the evaluation as a labelled development read on new dates, with no
  confirmation claimed.

## 12. What this draft does NOT claim

- **The development numbers are not evidence.** The from stratum was read before. The before stratum is in-sample for
  RV-1's constants.
- **No market parity.** RV-1 trails the market in every block.
- **No serving result.** RV-1 has never run on the live path, and v2 here is a research re-derivation.
- **No new source and no capture case.** NBH, NWS grid, HRRR and forecast_high add nothing once v2 is in (T18
  selection, R-T5-INC).
- **Closed threads stay closed:** hour gating chosen on this table, recalibration, NBH for the morning, and the 111h
  all-hours C1 verdict.
- **No authorisation.** Nothing here authorises landing, serving, promotion, a reservation, alpha, Scheduler work or
  live activity.

## Sources

**Swarm outputs:**
- `C:\swarm\out\t18\report.md`, `t18_run.json`, `t18_controls.json`
- `C:\swarm\out\refute-pit-t18\report.md`
- `C:\swarm\out\refute-stat-t18\report.md`
- `C:\swarm\out\ladder\report.md`
- `C:\swarm\out\d-morning\report.md`
- `C:\swarm\out\r-t5-inc\report.md` (cited through COMMON.md)
- D-DEFECT and D-RUNG1C summaries in `C:\swarm\COMMON.md`
- `C:\swarm\out\d3\d3_run.json` and `d3_plan2.json`

**Repository documents:**
- `docs/operations/DECISION_LOG.md` (rows 2026-09-30 and 2026-10-03)
- `docs/operations/ESTABLISHED_FINDINGS.md` §4, §1c, §1d, §2, §10c, §10h, §10j, §10k, §10l, §10p
- `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md` (81a reservation form)
- `docs/operations/reserved-confirmation-window.md`
- `docs/research/model-parity-swarm-2026-10-04/d2-remrise-prereg-draft.md`
- `docs/research/model-parity-swarm-2026-10-04/d-hg-hour-gated-composite-prereg-draft.md`
