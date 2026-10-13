# DRAFT, UNSIGNED: evening lock-in fix scoring — pre-registration, 2026-10-13

> **Status: DRAFT, UNSIGNED, NOT ACTIVE.** Written by the workstation (track T3) at the coordinator's request
> for the State of Play open commitment "Evening-fix scoring prereg". It authorises nothing: no scoring, no
> reservation, no alpha, no code change, no serving change. It binds only once the owner signs it (section 9), and
> it must never be landed on `master` without the owner.
>
> **Data rule this draft was written under:** it cites only the established findings, the findings digest, the
> retracted-claims register and development outputs on dates up to 2026-09-29. It reads, enumerates and cites
> nothing from 88a, the desk-study panel, settlement data or scores for 2026-09-30..2026-10-15.

## 0. Authority and scope

### 0.1 What is being scored

The **evening lock-in fix** that is live in production since the N3 merge night (2026-10-08 → 10-09):

| Piece | Commit | Owner row (DECISION_LOG) |
| --- | --- | --- |
| lockin-anchor-v3: re-anchor the late-day lock-in stages on the observed same-day high when WU printed history is empty (#191); `ML_MODEL_VERSION` v0.5.11 | merge `094f5b393` (2026-10-06 01:43) | 2026-10-05 (#191 lock-in floor rule) |
| #189: METAR rows keyed by observation time, not AWC `reportTime` (capture defect M0: a D-1 23:5x report can no longer become the day-D anchor) | `5e03609e3`, merged into N3 at `9e2af119f` | 2026-10-06 (B approval names #189 as the base of #246) |
| lockin-anchor-v4 (#246): the observed same-day METAR high is a floor at every hour, not only once a late-day stage acts; `ML_MODEL_VERSION` v0.5.12 | `91bf07863`, merged into N3 at `1bb083a3e` | 2026-10-06 (B approved), 2026-10-08 (B replay accepted; 3 Toronto no-METAR rows pre-existing; item 337 opened) |
| N3 landing on `master` | `6ad52c89f` (2026-10-09 01:20 EDT) | — |

The development finding behind the fix is EF §10q (rung 1, "restoring the late-day lock-in closes 85% of the 17-23
gap") and the RF entry "Evening decided-band / remaining-rise rules are an information lead — A SERVING DEFECT
(2026-10-04)". The served WU-history input is empty since paid access was disabled, so the five late-day lock-in
stages had zero strength and the untapered S7 calibration re-spread mass above a high that was already in
(D-DEFECT; AGENT_CONTEXT, late-day anchor).

**No roadmap item owns this fix's scoring.** The owner rows above and item 337 (the no-METAR floor gap) are the
nearest owners. Which item records the result is an owner decision (section 10, OD-A7).

### 0.2 What this is not

- **Not a promotion gate.** The fix is already served. This read answers "did the landed fix improve evening
  forecasts on new dates, and did it ever zero out a settled band", and it routes a pre-declared consequence
  (section 6) to the owner.
- **Not an MG-1, t3-r3 or maker read.** It reads no NBM guidance-read stage, no remaining-rise stage and no 88a or
  maker-shadow data.
- **No development number is evidence.** Every 111h-table figure below comes from previously inspected dates
  (2026-08-01..09-29) and is used for sizing only.

## 1. Arms and comparison (fixed)

Both arms are produced by **one paired captured-input replay** at one pinned code commit, so that the only difference
between them is the anchor path:

- **NEW (as served):** v0.5.12 code and the active v0.5.12 serving bundle, default switches
  (`late_day_lockin_legacy_wu_anchor = False`, `pre_lockin_same_day_floor = True`).
- **OLD (pre-restoration counterfactual):** the same code and bundle with `late_day_lockin_legacy_wu_anchor = True`
  (`src/weather/model/model_distribution.py`, the anchor builder). With the legacy switch the anchor source is the
  WU history only, so the observed anchor is absent, every late-day stage stays at its pre-v3 strength and the v4
  pre-lock-in floor does not fire either (it needs the observed anchor). OLD is therefore the v0.5.10 late-day
  behaviour on today's code. #189's keying only affects the observed anchor, so it has no effect on OLD.

**Why a replay and not "captured served vs a stored old vector":** the old model was never served on these dates,
so OLD exists only as a replay. Replaying NEW too (rather than using the captured served vector) keeps both arms in
one pipeline; the captured served vector is used only for the validity check in section 6.2.

**Tool:** `weather.backtesting.lockin_anchor_replay` already produces exactly these two vectors per snapshot. It
refuses target dates after `LAST_REPLAYABLE_DATE = 2026-09-29` and does not score. **A reviewed code change is a
precondition** (section 7): lift the date gate for the declared window only and add a scorer, written and tested on
dates <= 2026-09-29 only, landed before the read date. No one runs it on window dates before the read.

## 2. Population and dates

- **Markets: US11** (the 11 US markets of the 111h table, fixed in advance). Toronto is reported beside with no
  alpha, because the 3 known no-METAR rows (item 337) are pre-existing behaviour and its variance was never part of
  the sizing table. Including Toronto in the primary is an owner option (OD-A4).
- **Dates:** local target dates **2026-10-16 through 2026-10-27** (12 calendar dates). Every local day in the window
  starts after 2026-10-16 00:00 UTC, so all scored days are settled days >= 10-16 UTC, after the embargo.
- **Countable:** promotion-countable market-days only (the existing definition), with both replay arms present for
  at least 90% of the cell's 17-23 snapshots. Countability is decided from capture and replay metadata only, never
  from settlement or score.
- **Short-window extension (outcome-blind):** if fewer than 9 of the 12 dates have at least 9 countable US markets,
  the window extends date by date (10-28, 10-29) until 9 such dates exist or 10-29 is reached. This rule reads only
  countability metadata. No further extension. 11-01 (DST end) is never in the window.
- **Calendar segments reported, no alpha:** before and after the METAR cadence change (owner 2026-10-02; lands after
  10-13) if it lands inside the window, and before and after any served-release change.

## 3. Primary metric, estimand and decision rule

**Primary metric:** NEW minus OLD mean multi-band Brier score against the venue winner (the WU settlement proxy,
EF §10c), **local hours 17:00-23:59**, US11.
- Snapshot Brier: the mean of (p - outcome)^2 over the snapshot's captured band rows (its complete band support),
  with band probabilities computed inside each arm exactly as production records them (`bin_probability`).
- Weights: equal snapshot weights within a market-day cell, then equal market-day weights.

**Inference (fixed-market, date-clustered; the 2026-09-30 guardrails):** the 11 markets are fixed; dates are
resampled as clusters, multinomial, **2,000 draws, seed 20261016**, percentile 95% interval, **one-sided alpha
0.025**. The 2026-09-30 DECISION_LOG guardrails apply verbatim:

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never
> re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only,
> amendment states its motivation)

- New dates only (>= 10-16); the 111h table is used for sizing only and is never re-read as evidence.
- The crossed date x market estimate and interval (81a statistics) are reported beside the primary.
- Motivation for the fixed-market choice: under crossed clustering the 11 market clusters set a variance floor that
  no number of dates removes (EF §10j), and the decision concerns exactly these 11 markets.

**PASS (the fix is confirmed on new dates)** requires all three:
1. the upper bound of the fixed-market 95% interval < 0;
2. at least 8 of 11 markets with a negative NEW-minus-OLD 17-23 mean (default; OD-A3 offers a guardrail form);
3. materiality: the estimate is at most -5% of the window's own OLD-minus-market 17-23 gap (EF §1d).

**Outcomes and their pre-declared consequences** (all routed to the owner; nothing reverts automatically):

| Outcome | Condition | Consequence |
| --- | --- | --- |
| PASS | all three above | Recorded as an established finding (out-of-sample confirmation of EF §10q rung 1). No serving change. |
| NOT CONFIRMED | upper bound >= 0, or condition 2 or 3 fails, and the lower bound <= 0 | Recorded as not confirmed. The fix stays (it was landed on a code-trace defect, not on this read); no re-test on the same dates. |
| HARM | the lower bound of the fixed-market interval > 0 | Escalated to the owner as a serving-defect candidate with the per-market table; the legacy switch is the documented rollback, an owner decision. |
| SAFETY FAIL | section 3.1 count > 0 on METAR-backed rows | Escalated to the owner regardless of the Brier result. |

### 3.1 Safety count (pre-declared, no alpha)

Count countable US11 and Toronto market-days whose **settled band** receives NEW final mass below 1e-6 at any 17-23
snapshot while OLD gives it at least 1e-3 — a settled outcome zeroed by the anchor rule. Development: 0 settled
buckets below the anchor on the v3 replay. Rows with no METAR anchor (item 337's case) are counted separately and do
not trigger SAFETY FAIL.

### 3.2 Secondary (fixed-sequence gatekeeping; tested only if the primary PASSes)

**H2, the v4 increment is not harmful before lock-in:** v0.5.12 minus v0.5.12 with `pre_lockin_same_day_floor =
False` (= v3 without v4), mean Brier, **local hours 00-16**, US11, fixed-market interval as above. Non-inferiority:
pass if the one-sided upper bound is below **+0.0005** (margin proposed by this draft; OD-A5). It inherits the full
0.025 only through the fixed sequence, so the family-wise error stays at 0.025. No superiority claim is made: the v4
floor was approved on safety grounds (a hard zero below a METAR reading, DECISION_LOG 2026-10-06), and rung-1-type
00-16 effects in development were about -0.0002, far below any detectable size at this N.

### 3.3 Reported beside, no alpha

- the crossed date x market estimate and interval;
- 13-16, 00-12 and all hours, NEW minus OLD;
- NEW minus market and OLD minus market at 17-23 (ratios are not interpretable there: market Brier about 0.0008);
- per-market deltas and signs; Toronto;
- mass above the anchor bucket at 17-23, NEW and OLD (development v3 replay: 0.332 → 0.075);
- coverage, fallback and replay-reproduction statistics; served release ids;
- the calendar segments of section 2.

Market prices are taken only from the market vectors stored in the snapshot payloads, never from 88a tapes. If the
owner rules that the 88a desk-study hold covers those vectors too (OD-A6), the market rows are dropped before the
read.

## 4. Power (normal-approximation scaling of cited development numbers; sizing only, never evidence)

No new run was made for this draft. Every input below is a cited development number on dates <= 2026-09-29.

**Planning effects** (17-23, restoration minus served):
- rung 1 (r1), before stratum 2026-08-01..08-22: **-0.0295** (T27 reproduction -0.029553; EF §10q ladder);
- D-DEFECT emulation `d_defect_r1`, before stratum: -0.0248, 11/11 markets;
- from stratum (previously read, sizing context only): r1 -0.0252 [-0.0350, -0.0174], 11/11.
- **Planning value: half of the before-stratum r1 effect, 0.0148** (development effects shrink on new dates).

**Variance sources:**
- **Fixed-market:** the D2 plan's 17-23 fixed-market MDE80 at 45 dates, **0.0042** (`d2-remrise-prereg-draft.md`
  §6; before stratum, seed 20261004). That table is t3-r3 minus served, whose 17-23 gain is the same lock-in shape
  (RF entry above; R-PIT-T3: the METAR running max exceeds the captured floor in only 0.14% of 17-23 rows), so it
  is a proxy for the NEW-minus-OLD variance, not a measurement of it.
- **Crossed:** D-DEFECT's `d_defect_r1` before-stratum crossed MDE80, **0.0128 at 21 dates**
  (`C:\swarm\out\d-defect\d-defect-r1.md`, development).

**Scaling:** MDE80(N) = MDE80(N0) x sqrt(N0 / N); SE = MDE80 / 2.80 (one-sided 0.025, 80%). For the crossed figure
this also inflates the market component, which does not shrink with dates, so the crossed numbers are conservative.

| Countable dates N | Fixed MDE80 | Fixed power, half / full effect | Crossed MDE80 | Crossed power, half / full |
| --- | --- | --- | --- | --- |
| 12 (planned) | 0.0081 | ~1.00 / ~1.00 | 0.0169 | ~0.69 / ~1.00 |
| 9 (extension floor) | 0.0094 | ~1.00 / ~1.00 | 0.0195 | ~0.56 / ~0.99 |

**Statements:**
- The interval condition is well powered at 9-12 dates even at half the development effect.
- **The sign condition (>= 8/11) is not sized.** Development showed 11/11 negative in both strata, but with 9-12
  dates per market the per-market means are noisy and no plug-in joint power was computed. If the owner wants a
  sized sign condition, a light before-stratum bootstrap at N = 12 can be run on the development table before
  signature (OD-A3), or sign consistency can be a reported guardrail instead of a pass condition.
- **Season:** every window date is out of the August-September season where the effect was measured. The mechanism
  (empty WU history, zero lock-in strength, untapered S7) does not depend on season, but autumn evenings have
  smaller diurnal ranges and more advective highs, so the size may differ in either direction.

## 5. Read date, stopping and no-peeking rules

- **One look. First and only read: 2026-10-29** (local), after settlement for 10-27 is final; if the outcome-blind
  extension of section 2 applies, on the second day after the last window date, **no later than 2026-10-31**.
- **No interim look.** No one joins settlement to either arm, computes a Brier score, a market comparison, a
  per-market sign or any outcome-derived summary for window dates before the read date. This includes the
  development scripts, dashboards and the maker shadow tooling.
- **Allowed before the read (outcome-blind):** confirming that snapshots and stored served vectors exist, that the
  replay runs and reproduces the stored served vector (section 6.2), coverage and countability counts, release ids.
- **No stopping on results:** no early stop for success, futility or harm. The only early stop is operational: if
  the replay precondition (section 7) is not landed by 2026-10-28, the read is postponed (not cancelled) to the first
  day after it lands, the window is unchanged, and the postponement is recorded with its reason.
- **No re-test on the same dates.** An amendment states its motivation and applies only to dates after the read.
- **The result is written once** (the item the owner names, plus EF/RF as the outcome dictates), with the replay
  commit, the bundle hash and this file's signed hash.

## 6. Falsifiers and validity conditions (declared up front)

### 6.1 Falsifiers (cannot be rescued by amendment on the same dates)

1. NOT CONFIRMED or HARM per section 3.
2. SAFETY FAIL per section 3.1.
3. Crossed disagreement: the crossed point estimate has the opposite sign to the fixed-market estimate. The result is
   then reported as market-specific, not a PASS.

### 6.2 Validity conditions (failure makes the look VOID; the dates are spent)

- **Replay reproduction:** on rows served by v0.5.12, the NEW arm reproduces the stored served final vector within an
  L1 distance of 1e-9 on at least 99% of snapshots (thresholds proposed; OD-A2). The development `lockin_anchor_replay`
  floor check is part of this condition (exit 3 = VOID).
- **Pinned inputs:** both arms run at one pinned code commit with the v0.5.12 bundle hash recorded; any difference
  between arms other than the legacy switch voids the look.
- **Point in time:** no replay input with an availability time after the snapshot's `captured_at_utc`.
- **Coverage:** fewer than 9 countable dates after the extension rule.
- **Window leakage:** any window outcome read or scored before the read date.

## 7. Preconditions (owner and code)

1. **Signature** of this file (section 9).
2. **Replay date gate and scorer:** a reviewed code change, drafted on `claude/evening-fix-scorer-20261013`
   (unlanded). `weather.backtesting.lockin_anchor_replay` admits closed dates >= 10-16 for outcome-blind replay and
   keeps refusing 2026-09-30..10-15; `weather.backtesting.evening_fix_scorer` implements sections 2-3 and the
   section 5 gate: it refuses unless this file's SHA-256 is in DECISION_LOG (signature), and before 10-29 it refuses
   unless `--read-token` names a JSON token bound to that hash whose `decision_log_row` is recorded in DECISION_LOG
   (an early read is an owner decision recorded before it happens). Tests use synthetic fixtures only. It must land
   before 10-28. Neither module is imported by a capture loop; the formal verdict is `roll_verdict.ps1`'s.
3. **No conflict with reservations:** the MG-1 reservation (narrow scope, NBM guidance-read family, dates >= 10-15)
   does not cover the late-day anchor path, and this draft reads no 88a data. The owner confirms both readings
   (OD-A6).

## 8. What this draft does NOT claim

- No development figure is evidence; the fix was landed on a code trace plus a development replay, not on a score.
- No market parity at 17-23; the ratio there is not interpretable.
- No claim about 00-16 beyond the gated non-inferiority of section 3.2.
- No reversal: a NOT CONFIRMED or HARM result does not itself revert the fix.
- Nothing here touches OD30 (the 11-01 night rule) or its retirement, which shares the State of Play row but is a
  separate owner decision.

## 9. Signature

UNSIGNED. On signature the owner adds a DECISION_LOG row carrying this file's raw SHA-256 at the signed commit; the
hash lives only in that row, never in this file.

## 10. Owner decisions this draft needs (BLOCKED-ON-OWNER)

- **OD-A1** Sign or amend this draft (window 10-16..10-27, read 10-29, one look).
- **OD-A2** Replay-reproduction thresholds (proposed: L1 <= 1e-9 on >= 99% of v0.5.12-served snapshots).
- **OD-A3** Sign consistency (>= 8/11) as a pass condition (default) or a reported guardrail; optionally authorise a
  light before-stratum bootstrap at N = 12 to size it before signature.
- **OD-A4** Toronto in or out of the primary (default out, reported beside).
- **OD-A5** The H2 non-inferiority margin (+0.0005 Brier, 00-16) or drop H2.
- **OD-A6** Confirm the MG-1 narrow-scope reading and the 88a-hold reading for snapshot market vectors.
- **OD-A7** Which item owns the result, and who writes the replay date-gate change (section 7.2).

## Sources

- [Findings digest](../operations/FINDINGS_DIGEST.md) (model-parity swarm v2 bullet); [established findings](../operations/ESTABLISHED_FINDINGS.md) §1d, §10c, §10j, §10q.
- [Retracted claims and false leads](../operations/RETRACTED_AND_FALSE_LEADS.md): "Evening decided-band / remaining-rise rules are an information lead — A SERVING DEFECT (2026-10-04)".
- [DECISION_LOG](../operations/DECISION_LOG.md) rows 2026-09-30 (guardrails), 2026-10-05 (#191), 2026-10-06 (B, v4), 2026-10-08 (B replay, item 337).
- [MG-1 pre-registration](morning-guidance-read-mg1-preregistration-2026-10-04.md) (structure and estimand template).
- [Model-parity swarm synthesis](model-parity-swarm-2026-10-04/SYNTHESIS.md); [D2 draft](model-parity-swarm-2026-10-04/d2-remrise-prereg-draft.md) §6; D-DEFECT outputs (`C:\swarm\out\d-defect`, development, dates <= 09-29).
- `src/weather/backtesting/lockin_anchor_replay.py`; `src/weather/model/model_distribution.py` (anchor builder, v4 floor switch).
- [Item 337](../roadmap/items/item-337-no-metar-observed-floor-gap.md).
