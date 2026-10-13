# MG-1 morning guidance read (captured NBM v2) — pre-registration, 2026-10-04

Status: **FINAL TEXT FOR SIGNATURE — UNSIGNED.** Nothing here is in force until the owner signs these exact bytes by
the procedure in §9. Until then nothing is reserved, no α is allocated, and no serving, config, model or Scheduler
change follows from this file.

- **What it is:** the frozen pre-registration of one zero-parameter morning candidate, MG-1 (the registered swarm
  control `r-t5-inc-c1`), scored against served on new dates only, with a narrow-scope date reservation.
- **Read when:** you are about to land the NBM v2 parser repair or the `nbm_v2_guidance_read_v1` shadow stage, score
  or inspect any morning guidance-read candidate on dates from 2026-10-15, or touch the reservation file.
- **Source:** the development draft `docs/research/model-parity-swarm-2026-10-04/d-morning-v2-guidance-prereg-draft.md`
  (swarm agent D-MORNING, PR #187, branch `codex/model-parity-swarm-20261004` at `8f717d49`), with the 2026-10-04
  owner decisions (§0.1) applied. Every number below is a development read on dates that 79a, 81a and 111h already
  inspected; **none of these numbers is evidence.**
- Reservation status re-read when this text was written: **NONE RESERVED**
  ([reserved-confirmation-window](../operations/reserved-confirmation-window.md)).

Once signed, this file is never edited: a change is a new dated amendment file that names this file and its signed
SHA-256, states its motivation, and is written before the affected quantity is read.

## 0. Authority and scope

### 0.1 Owner decisions this text implements (DECISION_LOG row 2026-10-04, verbatim)

> Model-parity swarm (PR #187, development) follow-ups approved: (1) build the evening late-day lock-in restoration (re-anchor to `max(history_max, guidance_floor)`, one re-anchored history view for S2-S5; no S7 gate) as a versioned serving-stage change with tests and a production replay check, landing in a quiet window; (2) land the NBM v2 parser repair (83a/83b/83c) with the v1-trained shadow variant re-versioned or quarantined; (3) sign MG-1 (captured v2 guidance read, 00-16 primary, new dates) after reviewing its final bytes; hold RV-1, t3-r3 and HG-1 until the evening fix is live; decline NBH-1 (no capture case); (4) MG-1 uses a narrow-scope reservation exemption (forecast scoring only; 88a desk-study panel UTC 10-15..10-30 and MM paper scoring untouched); (5) queue the 91a `-VerifyRetained` nightly-journal extension, the M0 METAR report-time keying fix and the Phase 3 shadow runner

Applied here:
- **MG-1 is the one candidate for signature** (item 3). This text is the final bytes the owner reviews; it is not
  signed until §9 is completed.
- **Narrow-scope reservation** (item 4): §7 reserves the dates only against the morning guidance-read
  (forecast-scoring) family. The 88a desk-study panel (UTC 2026-10-15..10-30) and MM paper scoring are untouched.
- **Parser repair first** (item 2): the first eligible date requires the landed, verified v2 parser (§3). The draft's
  "owner option" of evaluating a research re-derivation of v2 without landing is **not taken**.
- **Decided, recorded here so no agent re-opens them:** RV-1 (D3, t18-c1 frozen), t3-r3 (D2, 13-16 remaining rise)
  and HG-1 (D-HG, hour-gated MG-1) are **HELD until the evening lock-in fix is live**; NBH-1 (D1, t5-r1) is
  **DECLINED** (no capture case). None of them is pre-registered by this file. RV-1 and HG-1 read NBM guidance, so
  they belong to the reserved family and may not be scored on the dates §7 reserves without a new owner decision;
  t3-r3 (a METAR remaining-rise rule) does not read NBM guidance and is outside the reserved family.

### 0.2 What this is not

- **Not a discovery.** It is the known 79a/81a/111h route under a fixed name and form: "the served model under-uses
  NBM station guidance that production already captures."
  - EF §10h (79a): band probabilities read straight off the captured NBM percentiles, with no fitted parameter,
    beat served on matched morning rows.
  - EF §10j (81a): scored on every morning row, the gain halves (C1 −0.006672). Eleven market clusters cap
    confirmation power: about 40% for 81a-sized effects, so under the crossed rule it was not confirmable at any
    season length.
  - EF §10p (111h): with parser-v2 values the C1 route helps 00-12, harms 13-16 and 17-23, and closes "all hours"
    for 81a's C1 form. 111h also prohibits choosing an hour gate on its table.
- **What the swarm added** (PR #187, development):
  - The registered control `r-t5-inc-c1` uses captured `v2_mean` in T5's Gaussian form, with zero parameters, at all
    hours. It scores 00-16 **−0.0100 [−0.0179, −0.0035]** against served (from stratum, all rows, development).
  - T5's NBH candidate adds **no** 00-16 increment over it: paired +0.0027 [−0.0037, +0.0098], 5/11 markets
    (`r-t5-inc.md`).
  - T7 c1 shows that captured v2_mean, in a history-fitted Gaussian, carries about 90% of the MOS-consensus morning
    gain.
  - R-STAT-MG1 (`r-stat-mg1.md`): MG-1 stands within its family on resampling robustness (crossed, date-only,
    market-only, every leave-one-market-out and leave-one-week-out interval excludes 0) and **fails registry-wide
    multiplicity** (00-16 z −2.70 against the Bonferroni line 4.04 over 938 tests). That is why it needs this
    pre-registration on new dates.
  - So the morning route needs no new source. It needs the served path to read guidance it already has.

## 1. Candidate rule MG-1, fixed verbatim (c1's form, no hour gate)

This is the registered text of `r-t5-inc-c1` (swarm registry line `r-t5-inc-c1`, registry sha256
`9bf12872dc708f744e9efb651126106b99ef90f640599e7e7efbc5084c68b83f`, registered 2026-10-04T01:26:04 local), restated for
prospective use with production field names. The constants are the only "parameters", and all of them are fixed a
priori. The registry text, verbatim:

> R-T5-INC c1 (v2_mean-only control in t5-r1 form): at snapshot t, if captured v2_mean, v2_stddev and v2_available_at exist and v2_available_at <= captured_at_utc, mu = v2_mean, sigma = max(v2_stddev, 1); X ~ Normal(mu, sigma) discretised on integers (mass on [k-0.5,k+0.5)); final H = max(B, X), B = floor(F+0.5), F = harness rule-4 floor; band probability = P(H in band) (t5 band_probs, unchanged); otherwise served fallback. Zero fitted parameters, all local hours, no gate. Served-information control only (captured v2 is already served information).

The prospective rule, verbatim from the draft. The draft's blob at `8f717d49` is double-encoded (UTF-8 read as
Windows-1252 and saved again, so `≤` appears as `â‰¤`); the text below is that blob decoded back to UTF-8, with no
other change:

> **MG-1.** At snapshot *t* for a US11 market, local target date *D*:
> - **Eligibility.** The captured parser-v2 NBM read for (station, *D*) must have status `available`. Its bulletin
>   must be the newest one with issue time ≤ *t* (24 h lookback) whose v2 parse holds *D*'s maximum. Its
>   availability time is the first time production held the bulletin bytes (`response_received_at`, else
>   `fetched_at`, else `first_seen_at`), and that time must be ≤ `captured_at_utc`, asserted. Finite `v2_mean` and
>   `v2_stddev` are required, and so is a captured floor.
> - **Floor.** F = max of the finite captured `guidance_physical_floor`, `high_so_far` and `trusted_current_max`
>   (81a's floor), and B = floor(F + 0.5).
> - **Rule.** μ = `v2_mean`, σ = max(`v2_stddev`, 1) in native °F. X ~ Normal(μ, σ), discretised on integers
>   (mass on [k − 0.5, k + 0.5)). H = max(B, X). Band probability = P(H ∈ band):
>   - a band's lower edge is −∞ if it is `lte` or its low ≤ B, else low − 0.5;
>   - its upper edge is +∞ if it is `gte`, else high + 0.5;
>   - a non-`gte` band with high < B gets 0.
>
>   Then renormalise and apply the 81a floor mask. Code reference: `t5_nbh_latest.band_probs`.
> - **Fallback.** If the read is not eligible, or the floored mass is 0, the captured served vector is used unchanged.
> - **Scope.** No fitted parameter, no validity-flag drop, no recency or age rule, no hour gate, no pool with served.
>   It is applied at every local hour.

**Differences from 81a/111h C1, stated so nobody mistakes MG-1 for a re-run of them:**
- MG-1 uses a Gaussian from mean/stddev, where C1 used a linear CDF through five quantiles with normal tails.
- MG-1 does not drop sets that sit partly below the floor. It collapses them onto the floor bucket (H = max(B, X)),
  where C1 fell back to served.

The second difference is why MG-1's afternoon is near-neutral, where 111h C1 harmed it. Development, from stratum:
13-16 −0.0005 [−0.0092, +0.0077] and 17-23 +0.0082 [−0.0078, +0.0205]. Inside 13-16, the POST-HOC 15-16 slice reads
+0.0068 against rung 1 (R-STAT-MG1); it is a known cost, reported (§4), not a gate.

**No hour gate (DESIGN rule 8 / the 111h prohibition); no secondary gated arm.** HG-1 is held by the owner (§0.1).
MG-1 handles the stale afternoon through the floor collapse.

**Excluded alternatives (one candidate, one primary, no multiplicity inside this file):**
- RV-1 / T7 c1 (the same centre with history-fitted spread or offsets): extra frozen parameters and parity surface;
  RV-1 is held (§0.1).
- 81a C2, the 50/50 pool.
- Any MOS, NBE or NBH centre. These need new capture, and R-T5-INC/T7 show they add little in the morning; NBH-1 is
  declined (§0.1).

## 2. Serveability dependency: parser repair first, then a versioned guidance-read stage

**MG-1 is not serveable today.** The swarm read `v2_mean` from the 111h re-derivation (parser HEAD `2e17ce0eb`).
Production still runs parser v1. From the 12Z/13Z/19Z cycles, v1 takes tomorrow morning's **minimum** as today's
maximum (EF §10k). The v2 repair (83a/83b, `codex/nbm-target-fix-20260921` @ `2e17ce0eb`, plus the reuse index
`62e8ff044`; mission 83c's stacked integration, EF §10l) is built but **not landed**. The owner approved landing it on
2026-10-04 (§0.1, item 2).

The serving path is two changes, in this order. Each is versioned.

1. **Land the parser repair** (roll-sensitive, so a quiet-window merge under the merge rules in force).
   - Parser version 2 is recorded per manifest row, and replay dispatches on the recorded version, so old bytes
     replay under v1.
   - The four provenance columns stay diagnostics and are not selectable (83b Part A).
   - **Parity effect:**
     - The served headline model selects no NBM column (EF §10h), so its output should not change. A captured-input
       replay of one day must show this before landing.
     - The shadow variant `pooled_f_candidate_miami_current_fallback_v0_1` (artifact `feature_model_hgb_f_pooled_v0_3.pkl`
       selects all 15 `nbm_prob_tmax_*`) was trained on v1-parsed values. After landing it sees v2 values, which is a
       train/serve skew. It must be re-versioned or quarantined (owner decision 2026-10-04, item 2). It is already
       promotion-blocked.
   - The feature builder's floor-drop of individual NBM values still applies to the *model features*. MG-1 does not
     read those filtered features. It reads the unfiltered v2 read: `v2_mean`, `v2_stddev`, cycle key, issue time,
     valid time and availability time.
   - **Capture requirement:** those unfiltered values must be stored per snapshot as non-selectable diagnostics, or
     be reproducible by deterministic replay from the retained bulletin bytes plus the manifest row. 83b states the
     second already holds.
2. **Add a guidance-read serving stage `nbm_v2_guidance_read_v1`.**
   - It is a post-model distribution stage, so it needs no retrain and no training-feature change.
   - The stage version, parser version 2, the constants (σ floor 1 °F, 24 h lookback, integer discretisation,
     H = max(B, X), floor fields) and the code hash bind into the release manifest.
   - Captured-input replay must reproduce the stage's vector from stored inputs.
   - **During the evaluation window the stage runs in shadow:** it is computed and stored, not served. Served
     therefore stays the comparator.
   - Serving it would be a later promotion through the existing readiness and release gates, after a pass. A pass
     does not authorise promotion by itself.

**Comparator binding.** "Served" means the captured served vector of whatever release served that snapshot, with its
release id recorded.
- If a serving change that touches 00-16 lands inside the window, the look reports pre- and post-change segments
  beside the primary. The primary itself is computed over all window dates against the served vector of record.
- The approved evening lock-in restoration (§0.1, item 1) changes 17-23 and, if the S3-S5 re-anchoring is bundled,
  possibly 13-16. If it lands inside the window it is such a change: it is reported as segments and it changes the
  all-hours and 17-23 reported comparators. It does not move the first eligible date.

## 3. Dates and season

**First eligible date** D0 = the first local target date *D* that satisfies all of the following:
- (a) *D* ≥ **2026-10-15**, i.e. after 2026-10-14, the former exam settlement date;
- (b) parser v2 was landed and verified in production before the first T+0 snapshot of *D* in the earliest US
  timezone (Eastern 00:00). Verification means all three capture workers recovered, and manifests for a full prior
  day show `parser_version = 2` with v2 provenance on every US NBM row;
- (c) the MG-1 shadow stage and the unfiltered v2 diagnostics are being captured;
- (d) *D* is after the Toronto date of the owner's signature of this file (§9), which is the freeze;
- (e) *D* is promotion-countable.

D0 is fixed by these non-outcome conditions alone. The evaluation counts each promotion-countable date from D0
onward, with no skipping and no choice, until 45 are counted.
- **Realistic earliest:** the parser repair is approved but not yet landed when this text was written, and (b) needs
  a full verified day after landing, so expect late October at the earliest.
- **Freeze timing:** the freeze must not be timed around convenient dates (reservation file, binding rule 5).

**Season statement.**
- Every eligible date is **out of season.** Per DESIGN §6 and EF §1c lineage (with EF §1b.4 and §2), mid-October onward
  is outside the season the served model was trained on. It is also outside the Aug–Sep window where 79a, 81a, 111h and
  the swarm measured this route.
- The calendar leaves enough dates. The US daily-high markets list every day, and the planned N of 45 countable dates
  from late October ends around mid-December, later if countable days are missed.
- The season does **not** guarantee the effect transports. Out-of-season, the served model runs about 1 °F cool
  (EF §2), which might widen the guidance advantage. Autumn guidance spread and diurnal shape differ, which might narrow
  it. This text predicts neither.
- US DST ends 2026-11-01. Parser v2 is correct in both standard and daylight time (EF §10l), and there is no hour gate,
  so the bulletin-to-local-hour shift needs no rule.
- The settlement label is the venue winner. The venue resolves on weather.gov WRH hourly data (EF §10c).

## 4. Estimand and pass rule

**Primary (maker-relevant): MG-1 minus served, mean Brier, US11, local hours 00:00–16:59, all rows with explicit
served fallback.**
- Population: promotion-countable market-days on the 45 counted dates (§3).
- Brier is the mean binary squared error over the complete band support.
- Weights: equal snapshot weights within a market-day, then equal market-day weights, with no hour reweighting.
- **Fixed-market date-clustered inference:** the 11 markets are fixed, and dates are resampled as clusters
  (multinomial date bootstrap, 2,000 draws, seed **20261004**). The interval is a percentile 95% interval,
  one-sided α 0.025.
- **Pass** = the 95% upper bound < 0 **and** ≥ 8/11 markets have a negative per-market mean delta **and** the
  estimate is ≤ −5% of the window's own 00-16 served − market gap (the EF §1d bar).
- **One look**, after the 45th counted date has settled. No interim outcome look.

**Reported beside it, with no α:**
- the crossed date × market estimate and interval (81a's statistics, seed 20260921);
- **17-23 reported separately.** It is cosmetic for the maker but real for Brier, and its market Brier is about 0.0008,
  so ratios there are not interpreted;
- the blocks 00-05/06-09/10-12/13-16, and the 15-16 hours inside 13-16 labelled as the known development cost
  (§1), never as a gate;
- all hours;
- matched rows, labelled "selected on availability";
- ratio to market, and absolute candidate − market;
- the tail lens on the window's own rows (EF tail definition; this panel's share stated);
- the per-market table;
- coverage and fallback reasons;
- served release ids, and pre/post segments for any serving change inside the window (§2).

**The 2026-09-30 DECISION_LOG guardrails, verbatim** (row 2026-09-30 "Swarm items approved …"; exact bytes of that
row):

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only, amendment states its motivation)

How this text meets them:
- **Future and new dates only:** §3. All evaluation dates are ≥ 2026-10-15 and after the freeze.
- **Never 111h; no 79a/81a/111h re-read:** this estimand is never applied to 111h, and no 79a/81a/111h date is read
  for evaluation or sizing beyond the development numbers already published.
- **Crossed estimate beside:** yes (§4, reported list; falsifier 4).
- **Per-market and sign consistency:** part of the pass rule (≥ 8/11) and the per-market table.
- **Motivation for the estimand change:** under crossed clustering the 11 market clusters set a variance floor that no
  number of dates removes. EF §10j showed this, and the planning in §5 reproduces it. The maker quotes exactly these 11
  markets, so the decision-relevant claim is "does MG-1 beat served on our markets over future dates". The claim is
  not about a hypothetical population of markets. The cost is stated: a pass does not generalise to new markets.

## 5. Power (plug-in planning on the BEFORE stratum only; development, sizing, never evidence)

**Method:** registry `d-morning-plan1`; code `tools/research/model_parity/d-morning_power.py` (PR #187 branch);
output `C:\swarm\out\d-morning\power.json` (workstation); HARNESS_SHA256
`8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`.
- Population: the before stratum (2026-08-01..08-22), 230 market-days, 21 dates × 11 markets.
- MG-1 = `r-t5-inc-c1` rebuilt exactly. Before-stratum 00-16 estimate −0.01216 (crossed [−0.0209, −0.0037]), 10/11
  markets negative (San Francisco +0.012).
- The harness crossed MDE80 on the before stratum is **0.01246**.
- Planning effects for 00-16: e = half the before-stratum estimate, **0.00608** (the planning effect, per DESIGN
  "effect halved"); 81a-sized **0.006672**; and the full **0.01216**, which is optimistic.
- One-sided α 0.025, 2,000 draws, seed 20261004.

| N new dates | Fixed-market MDE80 | Fixed: power at 0.00608 (interval / + ≥8 of 11) | Fixed: power at 0.00667 (interval / joint) | Crossed MDE80 | Crossed: power at 0.00608 / 0.00667 / 0.01216 |
|---|---|---|---|---|---|
| 20 | 0.0066 | 0.75 / 0.59 | 0.83 / 0.67 | 0.0123 | 0.28 / 0.33 / 0.79 |
| 24 | — | 0.83 / 0.65 | 0.89 / 0.73 | — | — |
| 30 | 0.0051 | 0.90 / 0.70 | 0.95 / 0.78 | 0.0117 | 0.28 / 0.33 / 0.83 |
| 35 | — | 0.94 / 0.76 | 0.98 / 0.84 | — | — |
| **45** | **0.0044** | **0.98 / 0.80** | **0.995 / 0.86** | 0.0107 | **0.34 / 0.41** / 0.89 |
| 90 | 0.0031 | ~1 / — | ~1 / — | 0.0097 | 0.41 / 0.47 / 0.94 |
| unlimited | → 0 | — | — | **0.0085** | **0.54 / 0.62** / 0.97 |

- **The EF §10j cap, stated honestly.**
  - Under the crossed estimand, an 81a-sized effect has **41% power at 45 dates**, which reproduces EF §10j's ~40%.
  - It has only **62% power with unlimited dates**. The market-only floor MDE80 is 0.0085, larger than every
    half-effect.
  - **80% is unattainable on the crossed estimate** for any effect up to about the full development size. It is reached
    only at the full −0.0122 after about 30 dates.
  - That cap is why the primary is fixed-market (§4 guardrails). The crossed estimate is reported beside it, and a
    crossed point estimate of the opposite sign blocks a pass (falsifier 4).
- **The fixed-market estimand removes that floor.**
  - The interval condition alone reaches 80% at about 22–24 dates for the half effect.
  - With the ≥ 8/11 sign condition, joint power reaches **80% at 45 countable dates**. San Francisco's opposite sign
    in development makes the sign rule the binding condition.
  - **Planned N = 45 countable dates, with one look.**
- **Limits of these numbers:**
  - These are plug-in figures from 21 August dates. Out-of-season variance and effect may differ.
  - The from-stratum −0.0100 is not used to size anything: those dates were read before, so DESIGN rule 7 forbids
    using them for sizing.
  - Coverage in development was 99.3%. The planning does not divide by fill again.
- **17-23, which gets no α:**
  - Before-stratum development estimate +0.0020. Crossed MDE80 0.0203.
  - Fixed-market MDE80 at 45 dates 0.0053.
  - Evening harm of about +0.006 or more would likely show in the reported interval.

## 6. Falsifiers and void conditions (declared up front)

**Falsifiers.** Each one closes or limits the route, and no amendment may rescue it on the same dates.
1. **Route closed.** The primary 00-16 fixed-market estimate is ≥ 0, or its 95% upper bound is ≥ 0 at N = 45. The
   morning guidance-read route is then closed for US11 under the current rules.
2. **Immaterial.** The estimate is above −5% of the window's own 00-16 served − market gap (the EF §1d bar). The effect
   is then real but too small to justify a serving change.
3. **Not fleet-wide.** Fewer than 8 of 11 markets are negative. Report which markets; no serving proposal.
4. **Crossed disagreement.** The crossed point estimate has the opposite sign to the fixed-market one. The result is
   then reported as market-specific, not a pass.
5. **Harm guardrails.**
   - If the all-hours fixed-market interval lies entirely above 0, there is no all-row serving proposal.
   - If 17-23's interval lies entirely above 0, it is reported as evening harm.
   - **In both cases no hour gate may be added post hoc.** A gate needs its own pre-registration on new dates, fixed
     from the bulletin schedule alone.

**Void conditions.** If one fails, the look is VOID: no pass and no fail. The dates are spent and are not re-run.
- **PIT:** any MG-1 input with availability after `captured_at_utc`, or with `v2_period_kind` other than maximum.
- **Coverage:** 00-16 MG-1 coverage below 90% of snapshots (development 99.3%).
- **Replay:** captured-input replay does not reproduce the shadow vector on 100% of snapshots, to within 1e-12.
- **Window leakage:** before the look, any MG-1 vector or any morning guidance-read-family candidate was joined to an
  outcome (winner, settlement or Brier) on a reserved date, or MG-1 was modified (§7 scope). Uses §7 leaves
  untouched do not void the look.
- **Parser:** a parser version other than 2 appears on any eligible row.

## 7. Reservation block (81a form, narrow scope). INACTIVE until the owner signs

> **INACTIVE — becomes active only when the owner signs this file (§9).** Reserve the first 45 promotion-countable
> local target dates on or after the first eligible date D0 (§3; D0 ≥ 2026-10-15), for the frozen morning
> guidance-read candidate MG-1 (`nbm_v2_guidance_read_v1`, parser v2), bound to this file's raw SHA-256 and commit as
> recorded in the signing DECISION_LOG row.
> - **Primary:** equal market-day mean MG-1-minus-served Brier, US11, 00:00–16:59 local, all rows with served fallback,
>   promotion-countable, fixed-market date-clustered inference.
> - **Beside the primary:** the crossed date × market estimate, 17-23 separately, and per-market signs (≥ 8/11 required).
> - **α:** one-sided 0.025 for the single candidate. There are no interim outcome looks. The sealed pre-boundary
>   campaign ledger is not spent.
> - **Scope — narrow, owner decision 2026-10-04.** The reserved dates are reserved **only** against reading or
>   modifying the morning guidance-read (forecast-scoring) family: do not score, enumerate outcomes for, or join to an
>   outcome the MG-1 vector or any other candidate that reads NBM station guidance into band probabilities (including
>   the held RV-1 and HG-1), do not substitute reserved dates for such a candidate, and do not modify MG-1, without a
>   new explicit owner decision. Accrue 45 countable dates with the fixed 11-market support. No model fitting or
>   selection.
> - **Exempt and untouched:** the 88a desk-study decision panel (UTC 2026-10-15..10-30), MM paper scoring, and
>   every other use of these dates' captures, served vectors and settlements. Operational checks of the shadow stage
>   that join no outcome (coverage, PIT, replay reproduction, parser version) are permitted and are required by §6.

**Activation (after signature, by the production agent, in one docs change):**
1. The signing row is in DECISION_LOG (§9).
2. In [reserved-confirmation-window.md](../operations/reserved-confirmation-window.md), the `Status:` line and the
   reservation table change **in the same edit** (that file's rule), naming this file, its signed SHA-256, the
   start rule "first eligible date D0 per §3" and the size "45 countable dates", and recording this narrow scope and
   its exemptions verbatim as the explicit exemption that file's binding rule 4 requires. The file's trigger is
   "first retrain candidate frozen"; MG-1 is a serving-stage candidate, and applying the mechanism to it is the
   owner's 2026-10-04 decision (§0.1, item 4).
3. When D0 is determined by §3's non-outcome conditions, the status line is updated with the dated start.

If the owner does not sign, nothing is reserved; any later evaluation on new dates is a labelled development read and
claims no confirmation.

## 8. What this text does NOT claim

- **The development reads are not evidence.**
  - The from-stratum −0.0100 [−0.0179, −0.0035] (00-16, all rows) is a development read on 2026-08-23..09-29. 79a, 81a
    and 111h had already inspected those dates. It is not a holdout, a confirmation or evidence of edge (DESIGN rule 7).
  - The before-stratum −0.0122 was likewise inspected by 81a/111h. It is used here only to size the plan.
  - MG-1 does not pass registry-wide multiplicity in development (§0.2).
- **No market parity.** MG-1 still trails the market in development. From-stratum candidate − market is positive in
  every block, with every interval above 0 (00-16 +0.0142 [+0.0100, +0.0188]). A Brier gain over served is not a gain
  over market prices.
- **No serving result.** MG-1 has never run on the live path. Every value came from a research re-derivation of v2.
- **Unverified inputs (R-STAT-MG1, COMPLETENESS):** the `v2_mean` values were not re-derived from primary bytes, and
  parser v2's rejection of the 12Z/13Z/19Z NBP cycles as `target_max_not_in_cycle` was not checked. Because of that
  rejection MG-1 effectively reads the 07Z NBP maximum all day from about 06 local. MG-1 is defined as the landed
  parser v2's output; the void condition "Parser" (§6) holds its version fixed through the window.
- **The power figures are plug-in plans.** They are not achieved power, and they assume August variance holds out of
  season.
- **The closed threads stay closed.** Nothing here re-opens recalibration, hour gating, NBH capture for the morning
  (R-T5-INC closes it; NBH-1 declined), or the 111h all-hours C1 verdict. MG-1 is a different, frozen form, and it is
  evaluated only on new dates.
- **No authorisation beyond §7.** Nothing here authorises landing, serving, promotion, Scheduler work or live
  activity. The parser repair and the shadow stage land under their own approvals and gates.

## 9. Signature

**FINAL TEXT FOR SIGNATURE — UNSIGNED.**

- **Canonical bytes:** the git blob of `docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md` at the
  commit the owner names, as stored by git (LF line endings; the repository pins `* text=auto eol=lf`). Merging that
  commit to `master` does not change the blob.
- **Hash:** raw SHA-256 of those bytes, `git show <commit>:docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md | sha256sum`
  (Git Bash). The SHA-256 covers this file exactly as committed, so it cannot be written inside the file: the fields
  below stay blank forever, and the hash lives only in the signing record.
- **Signing record:** one DECISION_LOG row in the form used for the maker replay clarifications: "Owner signs the MG-1
  pre-registration: exact bytes of `<path>` at `<commit>` (PR `<n>`), raw SHA-256 `<64 hex>`, signed `<UTC time>`".
  The signature time is the freeze (§3 (d)).
- **After signature:** this file is never edited. Any byte change produces a new hash and needs a new signature; an
  amendment is a separate dated file (opening of this file). Activation follows §7.

| Field (recorded in the DECISION_LOG row, never here) | Value |
|---|---|
| Commit | (in the signing row) |
| Raw SHA-256 of the blob | (in the signing row) |
| Signed (UTC) | (in the signing row) |

## Sources

- PR #187, branch `codex/model-parity-swarm-20261004` at `8f717d49`, `docs/research/model-parity-swarm-2026-10-04/`:
  `d-morning-v2-guidance-prereg-draft.md` (the draft this text finalises), `SYNTHESIS.md` §0, §7, §8, §9, §11,
  `r-stat-mg1.md`, `r-t5-inc.md`; code `tools/research/model_parity/t5_nbh_latest.py` (`band_probs`),
  `d-morning_power.py`.
- Workstation outputs: `C:\swarm\out\r-t5-inc\report.md`, `C:\swarm\out\t7\report.md`,
  `C:\swarm\out\refute-pit-t7\c1_shift_results.json`, `C:\swarm\out\r-stat-mg1\stats.json`, `C:\swarm\registry.jsonl`.
- [81a pre-registration](morning-guidance-candidate-preregistration-2026-09-21.md) (reservation form) and
  [111h pre-registration](guidance-all-hours-preregistration-2026-09-29.md).
- `docs/operations/ESTABLISHED_FINDINGS.md` §1c, §1d, §2, §10c, §10h, §10j, §10k, §10l, §10p.
- [DECISION_LOG](../operations/DECISION_LOG.md) rows 2026-09-30 (swarm items) and 2026-10-04 (swarm follow-ups).
- [Reserved confirmation window](../operations/reserved-confirmation-window.md).
