# DRAFT, UNSIGNED: 13-16 remaining-rise stage (t3-r3) — pre-registration, 2026-10-13

> **Status: SIGNED 2026-10-16 (section 11); the DRAFT/UNSIGNED wording below is the text as approved.** Written by the workstation (track T3) at the coordinator's request. It
> supersedes the pre-registration text in section 7 of the swarm's
> [D2 draft](model-parity-swarm-2026-10-04/d2-remrise-prereg-draft.md) on three points: the family-wise failure
> (section 2), the post-hoc 15-16 slice (section 3) and the holdout start (section 5). It authorises nothing: no
> code, no stage, no reservation, no alpha, no serving change. It binds only once the owner signs it, and it must
> never be landed on `master` without the owner.
>
> **Data rule this draft was written under:** it cites only the established findings, the findings digest, the
> retracted-claims register and development outputs on dates up to 2026-09-29. It reads, enumerates and designs
> nothing on 88a, panel, settlement or score data for 2026-09-30..2026-10-15, and no rule below reads those outcomes.

## 0. Why this block, and its standing

- **The largest residual after the two repairs.** EF §10q: after rung 2 (lock-in restoration + MG-1), the 13-16
  block remains at **+0.0231 [+0.0173, +0.0289], 1.81x** the market's Brier; the digest: "the largest residual is
  the 13-16 block (1.81x), where a no-source METAR remaining-rise rule helps but is fragile and fails family-wise
  (the 15-16 figure is a post-hoc slice)". Rung 1 moves 13-16 by only -0.0006, and re-anchoring S3-S5 recovers only
  -0.0020.
- **The owner hold is lifted by its own condition.** On 2026-10-04 the owner held t3-r3, RV-1 and HG-1 until the
  evening lock-in fix is live (MG-1 pre-registration §0.1). The fix is live since the N3 landing (2026-10-09). Moving
  t3-r3 forward is still an owner decision (OD-B1).
- **Outside the MG-1 family.** t3-r3 reads no NBM guidance, so the MG-1 narrow-scope reservation does not cover it.

## 1. Hypothesis and candidate (fixed verbatim)

**H1 (the single confirmatory hypothesis):** on US11 promotion-countable dates in the holdout of section 5, adding
the stage `remaining_rise_floor_v1` after the served final distribution **lowers the mean Brier score at local hours
13:00-16:59** relative to served.

**Candidate:** t3-r3, registry sha256 `ae86d0350391219d1f96a91e944335eec2e9216f95b0fdc58e9cda3185456559`, in its
serve form d2-r3f (anchor on the captured floor), exactly as D2 draft §5 and §7.1 specify:

**Features at serve (the complete list; nothing else enters):**
1. the captured 81a floor F = max of the finite captured values of `guidance_physical_floor` (the METAR maximum
   since local midnight), `high_so_far` and `trusted_current_max`, as the served 81a floor mask defines it; F is
   missing only when all three are missing;
2. B = round_half_up(F);
3. the market's station;
4. the local target month;
5. the local clock hour of the snapshot;
6. the frozen artifact `remaining_rise_pmf_v1` (3,036 cells, station x calendar month x local hour; IEM routine
   METAR, COR excluded, temp_f = round_half_up(T-group °C x 1.8 + 32), complete days >= 20 rows, history
   2024-05-01..2026-07-31, discrete Gaussian sd 1 °F, negative e folded to 0), its hash bound to the release.

**Stage:** P(H = B + e) mapped to bands, then the 81a floor mask and renormalisation; fallback to served when the
market's native unit is not °F, the artifact hash read at serve differs from the frozen hash, the snapshot's
station-local date is not the target date, F or the cell is missing, the METAR payload is flagged `stale`, or the
floored mass is 0 (each fallback row records its reason); placed **after** the final
distribution so S7 cannot re-spread mass above B; **shadow only** (stored per snapshot, never served). No fitted
parameter, no hour gate, no pooling with served, no recency rule, no refresh of the artifact during the holdout.

**Excluded alternatives** (so there is one candidate): T1, T2, T4, T7, T15, t3-r3s, d2-c1, d2-c2, and any hour-gated
or composed form.

## 2. The earlier family-wise failure, and the correction

### 2.1 What failed

- **SYNTHESIS §7 (development multiplicity):** Bonferroni over 134 registered rules x 7 hour-block groups = **938
  tests**, one-sided 0.025/938, z about 4.04. **t3-r3 at 13-16, z -3.26, does not pass.** T1 at 13-16 (about -2.6)
  and d2-c1 00-16 (about -3.4) do not pass either. The 17-23 family does (r1 -5.46, t3-r3 -4.22).
- **R-STAT-T3:** under a Bonferroni-40 interval (the registry size at its run) the 13-16 upper bound is **-0.0001**,
  marginal; it fails the -0.0133 line under every leave-one-market-out drop.
- **R-PIT-T3:** at serve-only +1 h METAR staleness 13-16 falls to WEAK -0.0052 [-0.0150, +0.0035], 6/11 markets;
  NULL at +2 h. It loses about 40% of its effect per hour of staleness. "Treat 13-16 as availability-sensitive, not a
  LEAD."
- The digest and EF §10q carry the summary: helps, but fragile and fails family-wise.

### 2.2 Why that failure does not transfer, and what replaces it

The 938-test correction answers the question "which of the rules searched on these dates is real?" — a selection
across many rules and blocks on **the same, already-inspected dates**. It is the right correction there, and this
draft does **not** overturn it: the development z -3.26 is not evidence, is not cited as support, and enters only as
a planning size (halved).

The confirmatory question here is different: one rule chosen in advance, tested once on dates that no rule search has
seen. The correction for that is **a single prespecified primary**:

- **one candidate** (section 1), **one block** (13:00-16:59), **one metric** (mean Brier vs served), **one
  estimand** (section 4), **one look** (section 6);
- **the whole one-sided alpha 0.025 is spent on that one test**; every other number is reported with no alpha and
  cannot rescue a failed primary;
- the selection that happened on development dates is paid for by **halving the planning effect** (winner's-curse
  shrinkage) and by the pre-declared falsifiers, not by a development-sized Bonferroni.

**Concurrent pre-registrations.** MG-1 (00-16, NBM read, dates >= 10-15) and the evening-fix scoring draft (17-23,
already-served fix, dates 10-16..10-27) also read new dates in the same season. Each answers a different serving
decision about a different stage, so the default here is **separate families, each at one-sided 0.025**. **Owner
option (OD-B3):** a programme-level family across the concurrently active pre-registrations with Holm at one-sided
0.025; with three members the worst case is 0.025/3 = 0.0083 for this test. Section 7 gives power under both.

## 3. The post-hoc 15-16 slice

- The 15-16 figures (+0.0270, 2.53x residual in EF §10q; t3-r3 15-16 -0.0126; "-0.0181 over rung 2") are
  **post-hoc**: the block was not a registered hour group, and the "-0.0181 over rung 2" figure is post-hoc twice
  (hour slice and comparator) and includes MG-1's +0.0068 harm there; against rung 1 it is -0.0113.
- **Declared exploratory only.** 15-16 (and 13-14) are reported beside the primary with no alpha. They are never a
  pass condition, never a rescue, and never a basis for an hour-gated serving proposal from this read. A 15-16-gated
  form needs its own pre-registration on dates after this look.

## 4. Estimand and decision rule

**Primary:** served-plus-stage minus served, mean Brier against the venue winner (WU settlement proxy, EF §10c), US11,
local 13:00-16:59, all rows with explicit served fallback, promotion-countable market-days; Brier over the complete
band support; equal snapshot weights within a market-day, then equal market-day weights.

**Comparator:** the captured served vector of v0.5.12 (lock-in restoration, v4 pre-lock-in floor and #189 live),
with its release id per row. The served model's own v4 floor now does natively what the development harness applied
as the 81a mask, so the development comparator ("served + harness floor") and today's comparator agree on the lower
side; the stage's gain is the upper-side remaining-rise shape. Any served-release change inside the holdout is
reported as a segment; a change on the 13-16 path voids the dates after it (section 8).

**Inference:** fixed-market date-clustered; 11 markets fixed; date multinomial bootstrap, 2,000 draws, seed fixed at
freeze; percentile 95%; one-sided alpha 0.025 (or the Holm-adjusted level under OD-B3). The 2026-09-30 guardrails
apply verbatim (as in the D2 draft §7.4): new dates only, never 111h, crossed estimate beside, per-market and sign
consistency, amendments state their motivation.

**PASS** requires: (1) the upper bound < 0; (2) at least 8 of 11 markets negative (default; OD-B4 offers a guardrail
form); (3) the estimate at most -5% of the window's own 13-16 served-minus-market gap (EF §1d).

**Reported beside, no alpha:** the crossed estimate and interval; 13-14 and 15-16 (exploratory, section 3); 00-16;
17-23; all hours; per-market deltas; matched rows (labelled selected on availability); stage-minus-market; METAR
freshness; coverage and fallback reasons; segments for DST (11-01), the METAR cadence change and any release change.

## 5. Holdout

The **first eligible date** is the first local target date D such that:
- (a) **D >= 2026-10-16**;
- (b) the stage and the frozen artifact were deployed in shadow before D's first T+0 snapshot in the earliest US
  timezone, verified by all three capture workers recovered and **one full prior day** of stored stage vectors with
  the bound artifact hash;
- (c) D is after the Toronto date of the freeze commit (this file's signature and the artifact hash);
- (d) D is promotion-countable.

Every countable date from the first eligible date counts, with no skipping or choice, until **N = 45 countable
dates**. The stage does not exist yet; it needs code, review and a roll-sensitive quiet-window merge, so the realistic
first eligible date is **late October or November**, and the read falls in **December or January**. No outcome on
2026-09-30..10-15 is read, scored or used for any choice in this design, and the stage cannot have produced any
vector for those dates.

**Season:** every holdout date is out of the measured August-September season; the artifact holds October-January
cells from 2024-2025 history, but the effect there was never measured. US DST ends 11-01 and lies inside the holdout;
the table and the stage key on local clock hour, so no rule changes, and pre/post segments are reported.

## 6. Look, stopping and no-peeking rules

- **One look**, on the second local day after the 45th countable date's settlement is final.
- **No interim look:** no settlement join, Brier, market comparison or per-market sign on holdout dates before the
  look. Allowed before it: outcome-blind checks only (stage vectors stored, artifact hash, coverage, fallback reasons,
  METAR freshness, countability).
- **No stopping on results** for success, futility or harm. The operational stops are the validity conditions of
  section 8 and a served-release change on the 13-16 path.
- **No re-test on the same dates;** an amendment states its motivation and applies only to later dates.

## 7. Power (plug-in, before stratum 2026-08-01..08-22 only; sizing, never evidence)

Source: the D2 plan (`d2-plan1`, `C:\swarm\out\d2\d2_run.json` → `power`; D2 draft §6), t3-r3 minus served market-day
cells, 21 dates x 11 markets, 2,000 draws, seed 20261004. Before-stratum 13-16 effect **-0.00972**; planning half
effect **0.00486**. Per-market 13-16 before-stratum means: ATL +0.0007, DEN +0.0061, MIA +0.0011, NYC -0.0023,
SEA -0.0061, LA -0.0378.

| 13-16, N countable dates | Fixed MDE80 | Fixed interval power, half / full | Fixed joint >= 8/11, half / full | Crossed MDE80 | Crossed power, half / full |
| --- | --- | --- | --- | --- | --- |
| 20 | 0.0038 | 0.93 / 1.00 | 0.22 / 0.80 | 0.0124 | 0.16 / 0.58 |
| **45 (planned)** | **0.0027** | **~1.00 / 1.00** | **0.17 / 0.86** | 0.0115 | 0.18 / 0.63 |
| 90 | 0.0020 | 1.00 / 1.00 | 0.12 / 0.88 | 0.0110 | 0.21 / 0.67 |

**Under the Holm option (OD-B3), worst case one-sided 0.0083** (normal approximation from the fixed MDE80 at 45
dates: SE = 0.0027/2.80 = 0.00096): fixed interval power at the half effect is about Φ(5.04 - 2.39) ≈ 1.00; the
binding constraint is unchanged.

**Statements:**
- **The interval condition is well powered** at 45 dates even at the half effect and even under Holm.
- **The sign condition binds.** Three or four markets sit near zero or positive in development, so joint power at the
  half effect is 17% at 45 dates and falls with N. It reaches 80% only if the full development effect carries over.
  This is the draft's weak point, stated, not hidden. **Owner option OD-B4:** keep sign consistency as a reported
  guardrail (the 2026-09-30 text requires it reported, not necessarily gating); the interval power at the half
  effect is then about 1.00.
- **The crossed estimate cannot reach 80% at any N** (unlimited MDE80 0.0105 > the full effect; EF §10j). It is
  reported, not gated.
- **Staleness discount:** the effect loses about 40% per hour of staleness (R-PIT-T3); production picks up a new
  METAR maximum about 3.8 min after valid, and the 2026-10-02 cadence change makes it fresher. The freshness validity
  condition below protects the planning assumption.
- **Season:** both effect and variance may differ out of season, in either direction.

## 8. Falsifiers and validity conditions (declared up front)

**Falsifiers** (cannot be rescued by amendment on the same dates):
1. **Route closed:** the 13-16 fixed-market upper bound >= 0 at N = 45. The remaining-rise stage is closed for US11
   out of season under the current rules.
2. **Immaterial:** estimate above -5% of the window's 13-16 gap.
3. **Not fleet-wide:** fewer than 8 of 11 markets negative (if a pass condition).
4. **Crossed disagreement:** crossed point estimate of opposite sign; reported as market-specific, not a pass.
5. **Harm guardrails:** a fixed-market interval entirely above 0 at 00-12, 17-23 or all hours rules out an all-hours
   serving proposal; no hour gate may be added post hoc.

**Validity conditions** (failure makes the look VOID; dates are spent):
- **PIT:** any stage input with an availability time after `captured_at_utc`.
- **Artifact:** artifact hash differs from the frozen hash on any eligible row.
- **Coverage:** 13-16 stage coverage below 90% of snapshots (development above 99%).
- **Freshness:** median age of the newest METAR row behind F at 13-16 snapshots above 30 minutes.
- **Replay:** captured-input replay does not reproduce the stored shadow vector within 1e-12 on 100% of rows.
- **Comparator:** a served-release change on the 13-16 path inside the holdout voids dates after the change, unless
  the owner pre-declares a segment rule before it lands.
- **Leakage:** any holdout outcome read before the look.

## 9. Reservation (PROPOSED, NOT ACTIVE; owner decision)

As D2 draft §8, narrow scope: reserve the first 45 countable dates on or after the section-5 first eligible date
against reading, scoring or modifying the remaining-rise / decided-band / evening-collapse family and against
modifying t3-r3 or its artifact, without a new explicit owner decision. Unrelated research is not blocked (the
candidate is frozen and zero-parameter). The reservation file's trigger ("first retrain candidate frozen") does not fit
a serving-stage candidate; applying it here is itself an owner decision (OD-B5). If not activated, the evaluation is a
labelled development read on new dates with no confirmation claimed.

## 10. What this draft does NOT claim

- No development read is evidence; the 13-16 -0.0116 (z -3.26) failed family-wise on reused dates and stays failed.
- The 15-16 slice is not evidence of anything.
- No market parity: t3-r3 minus market is +0.0124 at 13-16 in development.
- No serving result: the stage has never run on the live path.
- Nothing reopens recalibration, guidance hour gating, NBH/NBS/MOS capture or the 111h all-hours verdict.

## 11. Signature

SIGNED: owner approved 2026-10-16 ~09:22 via master-agent relay (amended text of `9485901dd`, OD-B1a/b applied).
The DECISION_LOG row of 2026-10-16 carries this file's raw SHA-256 at the signed commit and the artifact hash; the
hashes live only in that row.

## 12. Owner decisions this draft needs (BLOCKED-ON-OWNER)

- **OD-B1** Release t3-r3 from the 2026-10-04 hold (its condition, the evening fix live, is met) and authorise the
  shadow stage and frozen artifact to be built, reviewed and merged in a quiet window.
- **OD-B2** Sign or amend this draft (single primary 13-16, N = 45, one look, holdout >= 10-16 subject to section 5).
- **OD-B3** Alpha families: separate per pre-registration (default) or Holm across concurrently active ones.
- **OD-B4** Sign consistency as a pass condition (default; joint power 17% at the half effect) or a reported guardrail.
- **OD-B5** Reservation scope and trigger (narrow, section 9), and the calendar overlap with MG-1 (both shadow stages
  may run on the same dates; neither modifies the other).

## Sources

- [Findings digest](../operations/FINDINGS_DIGEST.md); [established findings](../operations/ESTABLISHED_FINDINGS.md) §1d, §10c, §10j, §10q.
- [Retracted claims and false leads](../operations/RETRACTED_AND_FALSE_LEADS.md): "Evening decided-band / remaining-rise rules are an information lead — A SERVING DEFECT (2026-10-04)".
- [Swarm synthesis](model-parity-swarm-2026-10-04/SYNTHESIS.md) §0.3 and §7; [R-STAT-T3](model-parity-swarm-2026-10-04/refute-stat-t3.md); [R-PIT-T3](model-parity-swarm-2026-10-04/refute-pit-t3.md); [D2 draft](model-parity-swarm-2026-10-04/d2-remrise-prereg-draft.md) §2-§9.
- [MG-1 pre-registration](morning-guidance-read-mg1-preregistration-2026-10-04.md) §0.1 (the 2026-10-04 hold), §4 (estimand template).
- [DECISION_LOG](../operations/DECISION_LOG.md) row 2026-09-30 (guardrails).
- [Evening-fix scoring draft](evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md) (concurrent family).
