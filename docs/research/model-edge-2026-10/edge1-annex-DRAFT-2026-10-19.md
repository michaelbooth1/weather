# DRAFT, UNSIGNED: EDGE-1 — model versus market, forward instrument annex, 2026-10-19

> **Status: DRAFT-UNSIGNED, NOT ACTIVE.** Written on the workstation (model-edge week 1) for the owner's single
> sign-off on Fri 2026-10-23. It authorises nothing: no scoring, no reservation, no alpha, no code, no stage, no
> serving change. It binds only once the owner signs it together with the
> [methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md) (section 11).
>
> **Signed SHA-256:** `________________________________________________________________` (left blank; recorded in the
> DECISION_LOG signing row with the methods-annex SHA-256 and the three arm hashes).
>
> **Data rule this draft was written under:** no label, settlement, market price, 88a, panel or score data for any
> UTC date >= 2026-09-30 was read; nothing for 2026-10-16..11-13 was read, counted or enumerated. Every number is from
> development dates <= 2026-09-29 (sizing only) or computed from no data (the futility table).

- **Owns:** the EDGE-1 instrument: arms, dates (both OD-A6 branches), hypotheses, looks, falsifiers, and its
  interaction with MG-1, the evening-fix scorer and t3-r3.
- **Methods:** adopts annex sections M0-M8 unchanged; deviations are listed in section 9.
- **Read when:** building an EDGE-1 arm, freezing its hash, building the scorer, or scheduling or running its looks.
- **Do not use for:** what a result triggers ([GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md)); alpha accounting
  ([alpha ledger](alpha-ledger-DRAFT-2026-10-19.md)).

## 0. Why, and what EDGE-1 is not

- EF §1 / FD line 3: "the model does not beat the market, and the gap is missing information". That conclusion predates
  the serving repairs (lock-in v3 2026-10-06; v4 floor and M0 keying 2026-10-09), and the exhaustion register's first
  exit criterion (EXHAUSTION_REGISTER §5 order 1, L1) is a post-fix forward model-vs-market measurement, which is
  unregistered. EDGE-1 is that measurement, with a decision attached.
- **Not** a re-test of MG-1, the evening-fix scorer or t3-r3. Those stay exactly as signed (section 6).
- **Not** a promotion. A GO enters the existing release gates (GO/NO-GO rule §3); it serves nothing by itself.
- **Scope clause:** every EDGE-1 date is out of season (EF §2, MG-1 §3 season statement). A NO-GO means **"no
  out-of-season edge"** for these arms, not that no in-season edge exists.

## 1. Arms (frozen as hashes before D0; M5.2)

| Arm | Definition | Endpoint | Frozen when | Input-removed twin (M7.3) |
| --- | --- | --- | --- | --- |
| **A0** | The served model as served after 2026-10-09: `ML_MODEL_VERSION` v0.5.12 (lock-in v3 + v4 pre-lock-in floor + #189 keying), default switches, the active bundle; the captured served vector of record, release id per row. | E1 | code hash frozen on the **post-N12 master** (after N12 lands, now the 10-22/23 night) and before D0 (section 1.2) | **T0, forecast-removed / climatology-prior twin** (section 1.1) |
| **A1** | A0 + the t3-r3 stage `remaining_rise_floor_v1` (artifact sha256 `b727fe1a897f8786afcd89514f0bae4a82d9e03ad951f2d72db9e228dd2afb09`, as signed DL 2026-10-16) + the non-NBM development survivors listed below, composed in the listed order, **frozen as one hash**; shadow only. | E1 | one hash before D0, on the post-N12 A0 | A1 with the t3-r3 and A1-1 inputs blanked = **A0 exactly** (section 1.1) |
| **A2** | The E2 blend (M2): linear pool per block of **A0** and the snapshot market vector, weights w_b fit on 2026-07-31..2026-09-29 only, weight file frozen into the hash. | E2 | not frozen: **E2 closed in development** (w_b = 0.00 in each sub-block on 07-31..09-29); no forward E2 instrument; H-A2 not in the family (k = 2) | none (A2 is the market itself; see section 1.1) |

### 1.1 Input-removed twins (M7.3), consistent with harness v3 control (f)

Harness v3 (`claude/harness-v3-20261019` @ `2f3f3e8e6`, `docs/research/harness-v3-2026-10-19.md` control (f);
`tools/research/model_parity/v3_arms.py` `input_removed`) builds every arm's twin by blanking the arm's declared
`INPUTS` and letting the arm fall back to served where it cannot build. That definition is used unchanged for A1. For
A0 it is degenerate: "the served arm has no inputs, so its twin is identical to it", which would make
effect_twin / effect_arm = 1 and fail falsifier 3 by construction. A0 therefore gets its own twin, declared here as the
one deviation from the generic mechanism (section 9).

**T0, the A0 twin (forecast inputs removed, climatology prior in their place):**
- **Ablated inputs:** every forecast source the served path reads into `forecast_high`, i.e. the votes pooled by
  `forecast_ensemble_metrics` (`model_features.py:365-414`): `open_meteo`, `weather_forecast`, `eccc_citypage`,
  `nws_hourly` (the NWS hourly point forecast, FD correction of 2026-10-19), `global_ensemble` and
  `open_meteo_global_models` (the latter also enters the HGB `forecast_high` feature directly,
  `model_features.py:1053-1061`). Their payloads are emptied in a captured-input replay of the frozen A0 code.
- **Replacement:** `forecast_high` is set to the station's climatological daily high for the target's calendar month
  from prior-year rows only (the serving climatology input, `daily_summary.csv` per station, target year dropped as the
  serving cache does), and `forecast_gap` is recomputed from it as serving does (`model_features.py:1064-1068`). A
  value, not a missing marker: blanking would send the HGB and the LR fallback down their missing-value paths, which
  would test the imputation rather than "no forecast information".
- **Kept unchanged:** every observation input (`high_so_far`, `current_temp`, the METAR and live-reading features), the
  bundle and its calibration, and all post-processing (hard floor, observed floors, lock-in anchor and stages, v4
  pre-lock-in floor, calibration, overlock guard). NBM, NWS-grid and HRRR are already unused by A0 (lever-5 code check).
- **Why this is the right falsifier:** T0 keeps everything that is calibration, shape or observation handling and
  removes only the forecast information. If T0 reproduces 75% or more of A0's improvement over the market
  (effect = 1 − R), then R is being driven by the model's calibration and its handling of observations the market also
  sees, not by forecast information, and there is no GO (M7.3).
- **Produced how:** by the host captured-input replay, outcome-blind, before any join; the twin vector enters the
  scorer as a precomputed arm input pinned by its own hash (replay commit, climatology file hashes, the substitution
  rule). Reported beside it with no binding role: **T0-prior**, which also removes the live observation features except
  the observed floor mask.

**A1 twin:** harness-v3-consistent. The declared inputs of the two added stages are blanked (t3-r3: its floor F
components and cell keys; A1-1: the observed bucket and cutoff), each stage falls back to served by its own rule, so the
twin is **A0 exactly**. Falsifier 3 then asks whether A0 alone already carries 75% or more of A1's improvement over the
market, i.e. whether t3-r3 + A1-1 contribute less than a quarter of it.

**A2:** **E2 closed in development** (w_b = 0.00 in each sub-block on 07-31..09-29); no forward E2 instrument; H-A2 not in the family (k = 2). With w = 0 in every block, A2 **is** the market and D ≡ 0: the arm is degenerate, not
under-powered, so it is a **measured development null** (for the exhaustion register), not UNTESTABLE (M2, M4.4).
Verified against the development screen record (screens doc §9, lever 8, `claude/model-edge-screens-20261019` @
`4d3e25699a8afe3a34d9e979c6aa950b6ca16389`): C-L8-E2S (served + market, A2's construction) has full-development
weights **0.00 / 0.00 / 0.00 / 0.00** for 00-05 / 06-09 / 10-12 / 13-16 (and 0.00 at 17-23 and 00-16), and 0.00 in both
2-fold fits; its out-of-fold blend − market is 0.0 exactly in every block. No date >= 2026-09-30 was read for this. The
owner may redefine A2 (OD-E5); a redefined A2 would need its own development fit and a re-run of the NO-GO simulation.

### 1.2 Freezing A0 after N12 (calendar, master-agent 2026-10-20)

- **N12** (`chain-r3` `739c03eff`, which includes #190, NBM parser v2) moved from the 10-19/20 night to the **10-22/23**
  night. `ML_MODEL_VERSION` stays **v0.5.12** in N12, so A0's version is unchanged, but N12 changes serving-path source
  (`model_features.py` and others). **A0's code hash is therefore frozen on the post-N12 master, after N12 lands and
  before D0**; T0, A1 and A2 are frozen on that A0.
- **If N12 slips past 10-24, D0 = 2026-10-25 is not reachable and D0 = 2026-10-28 applies** whatever OD-A6 says (the
  freeze plus one full prior day of stored vectors must precede D0). If it slips further, D0 is the first date satisfying
  the section 2 non-outcome conditions after the post-N12 freeze.
- **MG-1:** its bound-window change (`e342baca1`) moves to the **10-23/24** night, and MG-1's staging needs #190, so it
  is after 10-22/23. Neither changes EDGE-1 (section 6.1).

**A1 survivor list — filled 2026-10-20 from the development screens.** Source: `claude/model-edge-screens-20261019`
@ `4d3e25699a8afe3a34d9e979c6aa950b6ca16389`, `docs/research/model-edge-screens-2026-10-19.md` §2 (kill rule declared
before scoring at `efcd93dadc9d91957d51ffe42fe07cc874b32dcd`), §9 and §10; sealed single-shot pass: prereg sha256
`955d5643f8e0576c52b5194d063a8f2badc44589a196e84a3021a5aca999ac39`, result sha256
`b83ac660910d0ff395ebf2ac21317ace9306ca20f8639835bd45327520820be1`. Development dates <= 2026-09-29 only.

| # | Survivor id | Arm file and sha256 | Reads NBM? | Order in A1 | Development read (00-16, candidate − served) |
| --- | --- | --- | --- | --- | --- |
| A1-1 | **C-L13-BT**: the lever-5 bucket-transition stage re-pointed on the observed station high (bucket = round_half_up(captured `high_so_far`), serving's own prior and blend weight, max 0.12; then the 81a floor mask) | `tools/research/model_parity/me_arm_l13_bt.py`, `9bcfdd258981e7e0b265abcc6d18757b034948bf8362dc75b6e5e7dbe039f41c` (full serving-code and climatology hashes: screens doc §10) | NO (`READS_NBM_GUIDANCE = False`) | after the t3-r3 stage [PROPOSED; fixed with the A1 hash] | −0.000073 [−0.00016, −0.00001], 8/11 markets, input-removed twin 0; active on 13.2% of snapshots |

**A1-1 is negligible.** Its effect is about 0.3% of the 00-16 served-minus-market gap, below the 5% bar and below EF
§1d's 3.2% floor; power at the half effect is 0.19 / 0.20 at 20 / 45 dates (parametric, and over-optimistic per the
harness v3 2026-10-20 addendum). It is a serving-stage restoration (lever 5), not new information. It was screened as
a stage-level approximation **applied to the final served vector**; the lever-5 host replay must give its final-vector
form before the A1 hash is frozen.

**So A1 = A0 + t3-r3 + A1-1, and A1 differs from A0 essentially by t3-r3 only.** A1 is kept as a separate arm by
default because t3-r3 is signed and A1 is its composite carrier against the market (its looks deferred per section
6.3); the owner may instead drop A1-1 from it (OD-E6).

**Screened and not in A1:**
- **C-L7-V2Q** (captured NBM v2 quantiles): survives the kill rule but adds nothing over MG-1 (+0.00099 [−0.00094,
  +0.00292], 4/11), and it reads NBM guidance, so it belongs to MG-1's reserved family in any case.
- **Lever 8, the E2 blends (C-L8-E2S, C-L8-E2M):** killed; the development blend weight of C-L8-E2S is **0.00 in each
  of the four sub-blocks** (00-05, 06-09, 10-12, 13-16). Consequence for A2: A2 equals the market exactly, so E2 is
  **closed in development** (a measured development null, not UNTESTABLE); there is no forward E2 instrument and H-A2
  is not in the family (k = 2) unless the owner redefines A2 (OD-E5); E2 is then not scored,
  which under the amended NO-GO E2 clause ("or E2 is UNTESTABLE or not scored", GO/NO-GO rule §1, §2.4) neither
  blocks nor satisfies NO-GO.

**Not screened — host extract required (nothing here implies they were tested):**
- **Lever 6:** Toronto GEM/HRDPS and the captured-but-unscored ensemble members; the input is only on the capture host.
- **Six captured-not-scored sources:** S9 (GEFS `global_ensemble`), S11 (ECMWF AIFS), S13 (GEM/HRDPS, Toronto), S26
  (MRMS precipitation), S29 (AIGFS/GraphCast), S32; per-source values exist only in host payloads (screens doc §4-§5,
  EXHAUSTION_REGISTER order 12).

Rules for the list: a survivor must come from a development screen on dates <= 2026-09-29, read **no NBM station
guidance** (anything that does belongs to the MG-1 reserved family, reserved-confirmation-window.md), carry zero or
frozen parameters, and pass the screen's own training-score check (EF §5). An empty list is allowed (A1 = A0 + t3-r3).
Nothing may be added after the arm hash is frozen.

**A2 would use A0, not A1,** because A1 is not frozen before 10-22 and A1 inherits the t3-r3 conflict (section 6.3).
Owner option OD-E5 is now: record E2 as closed in development and carry no A2 (default), or redefine A2.

## 2. Population, D0 and looks

- **Markets:** US11, the 11 US markets of EF §10q / MG-1 / t3-r3 (fixed). Toronto reported beside with no alpha (no
  NBM, item 337 no-METAR rows).
- **Countable date:** M0 (at least 9 of 11 countable markets; ledger labels only).
- **Every countable date from D0 counts, no skipping, until 45.** Interim at the 20th, final at the 45th.

### 2.1 OD-A6 and the two D0 branches

OD-A6 is in the evening-fix pre-registration (§3.3 and §10): *"Confirm the MG-1 narrow-scope reading and the 88a-hold
reading for snapshot market vectors."* Its current status in DECISION_LOG:

- 2026-10-13 signing row: "OD-A6 states no labelled default; master is asking the owner".
- 2026-10-15 row (owner "approve all", relayed): **"A6 MG-1 does not cover the anchor path, and the scorer runs with
  `--no-market` (primary NEW vs OLD Brier; 10-16..10-27 market prices stay unread)"**.

So the MG-1 half of OD-A6 is ruled; the 88a-hold half was **sidestepped, not ruled**: the evening-fix read avoids
market prices instead of deciding whether stored snapshot market vectors are covered by the 88a panel hold. Master-agent
(2026-10-19, relayed) recommends that the owner rule them **"not held for pre-registered forecast scoring"**. Both
branches are drafted; the owner's ruling selects one, and that ruling is a dated DECISION_LOG row written before D0.

| Branch | D0 | 20th countable date (interim N), earliest | 45th countable date (final N), earliest | Interim read, earliest | Final read, earliest |
| --- | --- | --- | --- | --- | --- |
| **Not held** (master-agent recommendation) | **2026-10-25** | 2026-11-13 | 2026-12-08 | 2026-11-15 (second local day after the 20th date's settlement; also after the 11-13 panel close) | 2026-12-10 |
| **Held** | **2026-10-28** | 2026-11-16 | 2026-12-11 | 2026-11-18 | 2026-12-13 |

- The calendar columns assume every date is countable; each missed date moves the look one date later. They are
  logistics (DL 2026-10-13), not rules.
- **The 10-25 branch also needs N12 landed by 10-24** (section 1.2); otherwise D0 = 2026-10-28.
- **Embargo, binding in both branches:** the owner refused all descriptive reads of UTC 2026-10-16..11-13 until the
  panel closes, with scored reads only after the close under a signed pre-registration (DL 2026-10-17). Every EDGE-1
  join therefore happens after 11-13 whatever the branch; under the not-held branch the interim's 20th date is the
  close date itself, so the interim cannot run before 11-14.
- **Gate 1 (2026-12-07)** in the GO/NO-GO rule sees the EDGE-1 interim, never its final, in both branches.
- **D0 non-outcome conditions (both branches):** D >= the branch date; the A1 and A2 shadow stages deployed with their
  frozen hashes before D's first T+0 snapshot in the earliest US timezone, with one full prior day of stored vectors
  (t3-r3 §5(b) form); D after the Toronto date of the signature. If the stages are late, A0 still starts at the branch
  date and A1/A2 start at their own first eligible date; each arm then counts its own 45 dates, and the D0 per arm is
  recorded in the signing commit's follow-up docs change.
- **Seasonal segments reported, no alpha:** before/after DST end 2026-11-01 (OD30 lapses 11-02); before/after any
  served-release change.

## 3. Hypotheses (the EDGE-1 family, M6)

| Id | Arm | Endpoint | Declared block | H1 |
| --- | --- | --- | --- | --- |
| H-A0 | A0 | E1 | 00-16 | R < 1 |
| H-A1 | A1 | E1 | 00-16 | R < 1 |
| ~~H-A2~~ | A2 | E2 | 00-16 | not in the family: E2 closed in development (section 1.1; OD-E5) |

- **Family: one-sided α 0.025, finals staggered** (H-A0's final is earliest 12-10 / 12-13; H-A1's is after the t3-r3
  look under OD-E1 (a), so a single Holm step at one final cannot run). **Default: fixed sequence.** H-A0 is tested
  first, at its own final, at 0.025; H-A1 is tested at its own final, at 0.025, **only if H-A0 was rejected**; if
  H-A0 is not rejected, H-A1 spends nothing and is reported with its intervals only (they still feed the NO-GO
  clause). This keeps the full 0.025 on the arm whose final is read first and on which the power figures (section 8)
  are computed; its cost is that an A1 that beats the market while A0 does not cannot give a GO.
  **Owner-visible alternative:** Bonferroni, each hypothesis at 0.025/k at its own final, with Holm only among
  hypotheses whose finals share one look (none under the defaults).
- **k is recorded at D0** in the signing follow-up row, after any UNTESTABLE marking (M4.4) and OD-E5: under the
  defaults k = 2 (H-A0, H-A1; H-A2 is not in the family), so the alternative would test each at 0.0125.
- **Why 00-16 and not each sub-block:** declaring the four sub-blocks for each arm would make k = 8 and, under the
  Bonferroni alternative, each level 0.0031. The sub-blocks 00-05, 06-09, 10-12, 13-16 are reported with their intervals, no alpha; the GO/NO-GO
  rule's NO-GO test reads their **lower** bounds, which needs no alpha. Owner option OD-E3: declare per-block
  hypotheses instead.
- 17-23: differences only (M0 ratio floor), no alpha.
- **Seeds (fixed at signature):** fixed-market 20261023, crossed 20261024, 10,000 draws each (M3).

## 4. Looks

- **Interim (20 countable dates): futility only, non-binding, spends nothing.** Boundary per M4.2: **c = 0.2656** for
  each of H-A0, H-A1, H-A2 (α_d 0.025, β 0.20, t = 20/45). "EDGE-1 crossed futility in every arm" (GO/NO-GO Gate 1)
  means Z < c for **every EDGE-1 hypothesis whose interim has been read** by 12-07 (GO/NO-GO rule §1, §2.4).
- **Final (45 countable dates, per hypothesis at its own final):** the section 3 multiplicity rule (default fixed
  sequence H-A0 then H-A1), then the falsifiers (section 5) for each rejected hypothesis.
- **H-A1's interim and final are additionally gated by section 6.3** (the t3-r3 look).

## 5. Falsifiers binding on any GO (M7, restated with EDGE-1 values)

1. **Crossed (date × market):** crossed point estimate on the same side and crossed one-sided 80% upper bound below 1
   (E1) or 0 (E2) [80% PROPOSED, OD-T2].
2. **Per-market sign:** R_m < 1 (E1) or D_m < 0 (E2) in **at least 8 of 11** markets, block 00-16.
3. **Input-removed twin:** effect_twin / effect_arm **< 0.75** on the same rows, using the section 1 twins.

All three must hold for a GO; failing any one gives no GO from that hypothesis, with no amendment on the same dates.

## 6. Interaction with signed instruments (they stay exactly as signed)

### 6.1 MG-1 (`b044e0f1`, window bound D0 2026-10-15, provisional last 2026-11-28, may only move later)

- MG-1 reserves its dates only against NBM-guidance-to-band candidates (reserved-confirmation-window.md). **No EDGE-1
  arm reads NBM guidance**: A0's served model selects no NBM column (EF §10h); A1's survivors must be non-NBM (section
  1); A2 blends A0 with the market. Scoring the served vector and market vectors on reserved dates is in MG-1's
  exemption ("every other use of these dates' captures, served vectors and settlements").
- EDGE-1 never reads the MG-1 vector, its stage, or any NBM read; it never modifies MG-1. An arm hash that included
  any of them would be refused before D0.
- No (family, date) double-spend: MG-1's family is the morning NBM guidance read; EDGE-1's families are model-vs-market
  (E1) and blend-vs-market (E2).

### 6.2 Evening-fix scorer (prereg sha256 `16ed20df…`, window 10-16..10-27, outcome-blind extension to 10-29, one look 2026-10-29, `--no-market`)

- Its window ends before both D0 branches except for its extension dates 10-28 and 10-29, which overlap the "held"
  and "not held" EDGE-1 windows. Its family (NEW vs OLD lock-in anchor, 17-23) is different and it reads no market
  price, so there is no family double-spend; EDGE-1 reads nothing for 10-28/10-29 before the evening-fix read (10-29,
  latest 10-31) because the 10-17 embargo already holds every EDGE-1 join until after 11-13.
- A0 contains the evening fix. EDGE-1 does not test it; its 17-23 numbers are reported only as differences.

### 6.3 t3-r3 13-16 (signed sha256 `71cdb452…`, artifact `b727fe1a…`, one look at N = 45 from its first eligible date)

**Conflict, needs an owner decision (OD-E1).** A1 contains the t3-r3 stage. t3-r3 §6 forbids any settlement join,
Brier or market comparison on its holdout dates before its look, and §8 voids the look on "any holdout outcome read
before the look". Its first eligible date is not yet dated (stage deployment, §5), so its 45-date holdout will overlap
EDGE-1 in either branch. Scoring A1 at the EDGE-1 interim or final before the t3-r3 look would void t3-r3. Note also
that the reservation file records no t3-r3 reservation ("no date is held out against anything else") although DL
2026-10-15 took OD-B5's narrow default; the signed t3-r3 no-peeking rule binds either way.

Options (default **a**):
- **(a)** H-A1's looks are deferred until after the t3-r3 look; A1 keeps its frozen hash and its 45 dates, and its
  interim is skipped if the t3-r3 look comes later than the EDGE-1 final date (H-A1 is then final-only).
- **(b)** Drop t3-r3 from A1 (A1 = A0 + survivors), removing the overlap.
- **(c)** A new owner decision exempts A1 from t3-r3's no-peeking rule; this voids nothing only if the owner rules
  that A1-vs-market is not a t3-r3 outcome read, which this draft does not recommend.

### 6.4 Alpha ledger

EDGE-1 adds one family (k = 2 under the defaults: H-A0, H-A1; 0.025 one-sided; fixed sequence by default, section 3)
and reserves no date against any other family. It
spends no CAMPAIGN_LEDGER decision. Rows: [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md) `EDGE1-*`.

## 7. Validity (M8) plus EDGE-1 specifics

- A served-release change on the 00-16 path inside the window voids the A0/A2 dates after it unless a segment rule is
  signed before it lands; the #162 landing and any item-337 flip are such changes (EXHAUSTION_REGISTER L18).
- The A1 and A2 shadow stages must store their arm hash per snapshot; coverage below 90% in 00-16 voids that arm.

## 8. Power

- **Power simulator (updated 2026-10-20):** harness v3 (H3/H7), `claude/harness-v3-20261019` @ `2f3f3e8e6b542a419204afe802dae4545abc10d7`, `docs/research/harness-v3-2026-10-19.md` and its "Addendum 2026-10-20: master-agent rulings"; `HARNESS_V3_SHA256` at that tip `987e171775c596f6e50ac72b9bd54880399e4fafcc11865cdec0a2375970b4cf` (recomputed on the workstation with `v3_score.harness_v3_sha256()`; the addendum's runs used `35024814…`). Development reads only (dev dates 08-01..09-29).

  | Forward dates x 11 markets | Parametric MDE80 | Parametric P(GO given effect) | Corrected (real-noise calibration) | P(GO given null) | Verdict vs bar 0.0133 |
  | --- | --- | --- | --- | --- | --- |
  | 20 | 0.0097 | 0.32 | ~0.22 | 0.026 | TESTABLE on the parametric MDE80 (re-confirm with `resampled_power`) |
  | 45 | 0.0085 | 0.40 | ~0.31-0.33 | 0.027 | TESTABLE on the parametric MDE80 (re-confirm) |
  | 90 | 0.0079 | 0.43 | ~0.35 | 0.040 | TESTABLE on the parametric MDE80 (re-confirm) |

  MG-1 development variance, half effect −0.0050 Brier at 00-16. **The parametric figures 0.32/0.40/0.43 are
  over-optimistic:** on real MG-1-like noise H3's parametric power is biased **high by 0.07-0.11 absolute**
  (predicted 0.581/0.410 at 20 dates vs empirical 0.473/0.309; at 45 dates 0.584/0.411 vs 0.516/0.323), so the
  half-effect power is **roughly 0.22-0.35** across 20-90 dates. Pre-registration power statements use the resampling
  estimator `v3_power.resampled_power`; a quoted parametric figure is reduced by ~0.10 at 20 dates and ~0.07-0.09 at
  45. The parametric MDE80 is optimistic in the same direction, so the TESTABLE verdict (0.0097 / 0.0085 / 0.0079
  against 0.0133) must be re-confirmed with `resampled_power` on the frozen arms before D0 (M4.4). The market
  component holds power near 40% or below at any season length (EF §10j).
- **MDE80 per hypothesis H-A0/H-A1/H-A2:** `<SLOT: per-arm resampled_power run on the frozen hashes before D0>`;
  UNTESTABLE test per M4.4 applied before D0.
- **NO-GO reachability:**

  **NO-GO reachability** (the §1 NO-GO rule applied verbatim per arm: lower bound of R above 1.05 in every 00-16
  block and E2 upper bound above −0.5% of market Brier; MG-1-like arm variance; 20,000 simulations per cell):

  | Scenario | P(NO-GO) at 20 dates | 45 dates | 90 dates |
  | --- | --- | --- | --- |
  | dev-observed R (1.171 / 1.205 / 1.250 / 1.945 by block) | 0.821 | 0.988 | 1.000 |
  | half effect, R = 1 + (R_dev − 1)/2 | 0.087 | 0.207 | 0.358 |
  | null, R = 1 | 0 | 0 | 0 |

  Sensitivity with served-vs-market variance components: 0.28-0.43 at the dev-observed R (20-90 dates). Every
  development-fit blend weight is **0.00**, so E2 is not scored; under the amended NO-GO (GO/NO-GO rule §1, §2.4) that
  neither blocks nor satisfies NO-GO, and the per-arm NO-GO rests on the R clause alone. **If a draft freezes a non-zero blend weight, this simulation must be re-run.**
- **"NO-GO likely within ~20 dates" is INFERENCE;** supporting computation P(NO-GO at 20) = 0.821 under the
  dev-observed R.
- **Interim:**

  **Interim futility** (c = 0.2656, computed in closed form as 0.26560 at t = 20/45):

  | Statistic | Scenario | P(stop at 20) | Power cost of obeying the non-binding stop |
  | --- | --- | --- | --- |
  | arm − served, 00-16 | dev-observed (−0.0100) | 0.002 | 0.0002 |
  | arm − served, 00-16 | half effect (−0.0050) | 0.100 | 0.0013 |
  | arm − served, 00-16 | null | 0.603 | 0.0003 |
  | R vs market, 00-16 | dev-observed or half effect (arm worse than the market) | 1.000 | 0 |
  | R vs market, 00-16 | null, R = 1 | 0.617 | 0.0006 |

  Power cost: **computed, <= 0.0013 power (parametric)**. On the R-vs-market statistic any arm that trails the market
  crosses futility almost surely.
- Development sizing context only (dates <= 2026-09-29, EF §10q): A0-like served/market 00-16 ratio 1.49 (1.29 after
  both repairs, which includes MG-1, not an EDGE-1 arm). An E1 pass for A0 would need the post-fix out-of-season
  ratio to fall below 1 from that region; this draft predicts nothing.

## 9. Deviations from the methods annex

One, motivated in section 1.1: A0's input-removed twin (M7.3) is the forecast-removed climatology-prior twin T0, not
the harness-v3 generic blank-inputs-and-fall-back twin, which is identical to A0 for a served arm and would fail
falsifier 3 by construction. A1 uses the generic mechanism unchanged.

## 10. What this draft does NOT claim

- No development figure is evidence; the A1 survivors are leads until scored here.
- No market-making result: E1/E2 are forecast endpoints. The maker endpoint E3 is a separate instrument
  (GO/NO-GO rule §2.3).
- No in-season claim (section 0 scope clause).

## 11. Signature

UNSIGNED. On signature the owner adds one DECISION_LOG row with this file's raw SHA-256, the methods annex's raw
SHA-256, the OD-A6 branch (D0), and the A0/A1/A2 arm hashes (A1/A2 may follow in a second row before D0, logistics
only if the arm definitions above are unchanged).

## 12. Owner decisions this draft needs

- **OD-A6 (88a hold for snapshot market vectors):** not held → D0 2026-10-25 (master-agent recommendation); held →
  D0 2026-10-28.
- **OD-E1:** the t3-r3 conflict (section 6.3): (a) default, (b), or (c).
- **OD-E2:** sign or amend (arms, N 20/45, multiplicity: fixed sequence H-A0 then H-A1 (default) or Bonferroni
  0.025/k at each own final, k recorded at D0).
- **OD-E3:** 00-16 declared block (default) or per-block hypotheses.
- **OD-E4:** the A1 survivor list as filled (A1-1 = C-L13-BT; logistics if it meets the section 1 rules).
- **OD-E6:** keep A1 as a separate arm (default) or drop A1-1 from it.
- **OD-E5:** E2 closed in development (w_b = 0.00 in each sub-block on 07-31..09-29; no forward E2 instrument; H-A2
  not in the family, k = 2) unless the owner redefines A2 (default: closed; the model added nothing beyond the market
  price on those dates). Proposed EXHAUSTION_REGISTER entry at signature (production docs change, not in this
  draft): "E2 frozen blend, served + market: CLOSED in development, all four w_b 0.00 (screens doc §9)".

## Sources

- [Methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md); [GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md); [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md).
- [MG-1](../morning-guidance-read-mg1-preregistration-2026-10-04.md); [evening-fix](../evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md) §3.3, §10; [t3-r3](../remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md) §5, §6, §8, §9.
- [Reserved confirmation window](../../operations/reserved-confirmation-window.md); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-10-04, 2026-10-13, 2026-10-15, 2026-10-16, 2026-10-17.
- [Exhaustion register](../../operations/EXHAUSTION_REGISTER.md) §0.2, §3 (L1, L18), §5; [findings digest](../../operations/FINDINGS_DIGEST.md); EF §1, §2, §5, §10h, §10q.
