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
| **A0** | The served model as served after 2026-10-09: `ML_MODEL_VERSION` v0.5.12 (lock-in v3 + v4 pre-lock-in floor + #189 keying), default switches, the active bundle; the captured served vector of record, release id per row. | E1 | code hash frozen on the **post-N12 master** (after N12 lands, now the 10-22/23 night) and before D0 (section 1.2) | **T1, public-forecast twin (binding):** `forecast_high` from the NWS hourly point forecast alone (section 1.1); T0 climatology-prior twin kept as a **non-binding** sanity control |
| **A1** | A0 + the t3-r3 stage `remaining_rise_floor_v1` (artifact sha256 `b727fe1a897f8786afcd89514f0bae4a82d9e03ad951f2d72db9e228dd2afb09`, as signed DL 2026-10-16) + the non-NBM development survivors listed below, composed in the listed order, **frozen as one hash**; shadow only. | E1 | one hash before D0, on the post-N12 A0 | A1 with the t3-r3 and A1-1 inputs blanked = **A0 exactly** (section 1.1) |
| **A2** | The E2 blend (M2): linear pool per block of **A0** and the snapshot market vector, weights w_b fit on 2026-07-31..2026-09-29 only, weight file frozen into the hash. | E2 | not frozen: **E2 closed in development** (w_b = 0.00 in each sub-block on 07-31..09-29); no forward E2 instrument; H-A2 not in the family (k recorded at D0, section 3) | none (A2 is the market itself; see section 1.1) |

### 1.1 Input-removed twins (M7.3), consistent with harness v3 control (f)

Harness v3 (`claude/harness-v3-20261019` @ `2f3f3e8e6`, `docs/research/harness-v3-2026-10-19.md` control (f);
`tools/research/model_parity/v3_arms.py` `input_removed`) builds every arm's twin by blanking the arm's declared
`INPUTS` and letting the arm fall back to served where it cannot build. That definition is used unchanged for A1. For
A0 it is degenerate: "the served arm has no inputs, so its twin is identical to it", which would make
effect_twin / effect_arm = 1 and fail falsifier 3 by construction. A0 therefore gets its own twin, declared here as the
one deviation from the generic mechanism (section 9).

**T1, the binding A0 twin (revised 2026-10-20, review finding M4): A0 with only the forecast the market plainly has.**
- **Definition:** a captured-input replay of the frozen A0 code in which **every forecast payload except
  `nws_hourly` is emptied** (`open_meteo`, `weather_forecast`, `eccc_citypage`, `global_ensemble`,
  `open_meteo_global_models`). `forecast_ensemble_metrics` then returns `forecast_high` = the NWS hourly point
  forecast's day maximum alone, and `forecast_gap` is recomputed from it by serving's own code
  (`model_features.py:1064-1068`); the `open_meteo_global_models` HGB feature is absent as its payload is. Every
  observation input, the bundle, its calibration and all post-processing are unchanged (as for T0 below).
- **Per-source forecast features (delta review item 6).** Emptying the other payloads also makes the per-source
  features derived from them missing (`model_features.py:669-716`, `:1069-1071`), which is T0's own objection to a
  missing marker. Rule: **per-source forecast features (`open_meteo_high`, `weather_high`, `eccc_city_high`,
  `open_meteo_global_models_*`) take the NWS day-max where the served bundle's 27 columns select them, or are declared
  missing with the T0 objection withdrawn for T1; verified against the bundle's column list before the T1 hash is
  frozen.** What the tracked artifacts show (code and manifests only, no labels): the per-market
  `artifacts/models/coefs/feature_model_coefs_<market>.json` (last changed `fe6881fea`, 2026-06-15; 24-29
  `feature_names` per cutoff hour, the same counts as the served bundles) select **none** of those per-source
  features in any US11 market. Their only forecast columns are `forecast_high` and `forecast_gap`, and **Miami** (29
  columns, as does the default `feature_model_coefs.json`) also selects `forecast_source_count` and
  `forecast_disagreement`. **Spec clarification, not a result (2026-10-21):** under T1 these take serving's own
  one-source values, `forecast_source_count` = 1 and `forecast_disagreement` = None (missing), because serving sets the
  disagreement only when at least two sources are present (`model_features.py:456-459`); this replaces the earlier
  "zero spread" wording. That is the intended "one public forecast" state as serving encodes it. The HGB pickles' own `feature_names` were not opened (binary artifacts); the check
  against them is the pre-freeze verification above.
- **Why `nws_hourly` (default):** the NWS point forecast for the settlement station's location is the free, public
  forecast any US market participant sees on weather.gov without querying an API; all 11 EDGE-1 markets are US.
  **Named alternative: Open-Meteo alone** (`open_meteo` kept, every other payload emptied), a free API but one a
  participant must query, so less plainly "had" by the market. The owner may choose it under OD-E7.
- **Not a feature-only swap (spec clarification, not a result, 2026-10-21).** T1 is a captured-input replay, so
  emptying the non-NWS payloads (`open_meteo`, `weather_forecast`, `eccc_citypage`, `global_ensemble`,
  `open_meteo_global_models`) also removes those sources from every post-processing step that reads the forecast
  votes, by construction; only the model features are named above, but the whole served path sees one source.
- **Rows with no captured `nws_hourly` value:** the twin takes A0's own vector on that row (counted and disclosed).
  This pulls effect_twin towards effect_arm, i.e. it makes falsifier 3 harder to pass, never easier.
- **Toronto (spec clarification, not a result, 2026-10-21).** Toronto has no `nws_hourly`, so T1 equals A0 (variant =
  base) on every Toronto row and Toronto contributes nothing to T1. No rule changes: Toronto is outside the US11
  population and is reported beside with no alpha (section 2), so falsifier 3 (computed on the declared US11 rows)
  and the 90% coverage clause (section 7, US11 arm coverage) are unaffected; the disclosed fallback count above will
  include every Toronto row if Toronto is reported beside.
- **What it tests:** whether A0's improvement over the market survives when its forecast information is cut down to
  what the market plainly has. If T1 reproduces 75% or more of A0's effect, the gain is not information the market
  lacks, and there is no GO (M7.3).
- **Produced how:** as T0 below (host captured-input replay, outcome-blind, before any join; pinned by its own hash).
  Spec only: the twin is not built in this draft. The binding T1 comparison is made on **forward** rows replayed at
  the frozen A0 hash (section 7). Any development-date T1 or T0 delta is "current-code replay ± twin", not
  "served ± twin" (the current code does not reproduce the development served vectors; section 7 evidence), and is
  sizing context only.

**T0, non-binding sanity control (forecast inputs removed, climatology prior in their place).** Kept beside T1 with no
binding role, because it cannot fail: a climatological `forecast_high` removes all forecast skill in 00-09, so
R_T0 ≫ 1 and effect_twin / effect_arm < 0.75 whenever H-A0 is rejected. It shows only that forecasts matter, not that
the gain is information the market lacks. It is not leaky (`model_climatology.py:121,234` drop every row with
year >= the target year), only trivially beaten. Its specification as drafted:
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
- **Note:** T0's handling of `forecast_source_count` / `forecast_disagreement` is unspecified here and follows serving.
- **Kept unchanged:** every observation input (`high_so_far`, `current_temp`, the METAR and live-reading features), the
  bundle and its calibration, and all post-processing (hard floor, observed floors, lock-in anchor and stages, v4
  pre-lock-in floor, calibration, overlock guard). NBM, NWS-grid and HRRR are already unused by A0 (lever-5 code check).
- **What it shows (non-binding):** T0 keeps everything that is calibration, shape or observation handling and
  removes only the forecast information, so it separates "forecasts matter" from "calibration and observation
  handling matter". It is reported beside T1 with no binding role.
- **Produced how:** by the host captured-input replay, outcome-blind, before any join; the twin vector enters the
  scorer as a precomputed arm input pinned by its own hash (replay commit, climatology file hashes, the substitution
  rule). Reported beside it with no binding role: **T0-prior**, which also removes the live observation features except
  the observed floor mask.

**A1 twin:** harness-v3-consistent. The declared inputs of the two added stages are blanked (t3-r3: its floor F
components and cell keys; A1-1: the observed bucket and cutoff), each stage falls back to served by its own rule, so the
twin is **A0 exactly**. Falsifier 3 then asks whether A0 alone already carries 75% or more of A1's improvement over the
market, i.e. whether t3-r3 + A1-1 contribute less than a quarter of it.

**A2:** **E2 closed in development** (w_b = 0.00 in each sub-block on 07-31..09-29); no forward E2 instrument; H-A2 not in the family (k recorded at D0, section 3). With w = 0 in every block, A2 **is** the market and D ≡ 0: the arm is degenerate, not
under-powered, so it is a **measured development null** (for the exhaustion register), not UNTESTABLE (M2, M4.4).
Verified against the development screen record (screens doc §9, lever 8, `claude/model-edge-screens-20261019` @
`4d3e25699a8afe3a34d9e979c6aa950b6ca16389`): C-L8-E2S (served + market, A2's construction, fit on the **served vector of
record**, not on M2's frozen-arm replay; see the methods annex M2 flag) has full-development
weights **0.00 / 0.00 / 0.00 / 0.00** for 00-05 / 06-09 / 10-12 / 13-16 (and 0.00 at 17-23 and 00-16), and 0.00 in both
2-fold fits; its out-of-fold blend − market is 0.0 exactly in every block. No date >= 2026-09-30 was read for this. The
owner may redefine A2 (OD-E5); a redefined A2 would need its own development fit and a re-run of the NO-GO simulation.

### 1.2 Freezing A0 after N12 (calendar, master-agent 2026-10-20)

- **N12** (`chain-r3` `739c03eff`, which includes #190, NBM parser v2) moved from the 10-19/20 night to the **10-22/23**
  night. `ML_MODEL_VERSION` stays **v0.5.12** in N12, so A0's version is unchanged, but N12 changes serving-path source
  (`model_features.py` and others). **A0's code hash is therefore frozen on the post-N12 master, after N12 lands and
  before D0**; T1, T0 and A1 are frozen on that A0.
- **"Post-N12 master" is pinned** as **the first `master` commit containing `739c03eff1e2f26c49759899e4e39b669d2c6628`**
  (N12's `chain-r3` tip, full SHA from `git rev-parse`). Its own full SHA goes in the A0 logistics row:
  `<SHA SLOT: first master commit containing 739c03eff1e2, filled once landed>`. Filling that slot is a
  **logistics fill, not a rule change** (DL 2026-10-13): the rule (that commit) is fixed here; only its identity is
  looked up after the landing.
- **Clock for "N12 lands by 10-24":** post-N12 code serving before the first T+0 snapshot of local 2026-10-24 in the earliest US timezone (one full prior day of stored
  vectors before D0 = 10-25). **If that is missed, D0 = 2026-10-25 is not reachable and D0 = 2026-10-28 applies**
  whatever OD-A6 says (the freeze plus one full prior day of stored vectors must precede D0). If it slips further, D0 is the first date satisfying
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
form before the A1 hash is frozen. Any development delta from that replay is "current code + stage − current code",
not "served + stage − served" (section 7 evidence); it sizes the stage, it does not reproduce the served vector.

**So A1 = A0 + t3-r3 + A1-1, and A1 differs from A0 essentially by t3-r3 only.** A1 is kept as a separate arm by
default because t3-r3 is signed and A1 is its composite carrier against the market (its looks deferred per section
6.3); the owner may instead drop A1-1 from it (OD-E6).

**Screened and not in A1:**
- **C-L7-V2Q** (captured NBM v2 quantiles): survives the kill rule but adds nothing over MG-1 (+0.00099 [−0.00094,
  +0.00292], 4/11), and it reads NBM guidance, so it belongs to MG-1's reserved family in any case.
- **Lever 8, the E2 blends (C-L8-E2S, C-L8-E2M):** killed; the development blend weight of C-L8-E2S is **0.00 in each
  of the four sub-blocks** (00-05, 06-09, 10-12, 13-16). Consequence for A2: A2 equals the market exactly, so E2 is
  **closed in development** (a measured development null, not UNTESTABLE); there is no forward E2 instrument and H-A2
  is not in the family unless the owner redefines A2 (OD-E5); E2 is then not scored,
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
| **Not held** (master-agent recommendation) | **2026-10-25** | 2026-11-13 | 2026-12-08 | 2026-11-15 (second local day after the 20th date's settlement; also after the 11-13 close of the maker-shadow scoring embargo, DL 2026-10-14/17; not the 88a desk-study panel, UTC 10-15..10-30) | 2026-12-10 |
| **Held** | **2026-10-28** | 2026-11-16 | 2026-12-11 | 2026-11-18 | 2026-12-13 |

- The calendar columns assume every date is countable; each missed date moves the look one date later. They are
  logistics (DL 2026-10-13), not rules.
- **The 10-25 branch also needs post-N12 code serving before the first T+0 snapshot of local 2026-10-24 in the earliest US timezone** (section 1.2); otherwise D0 = 2026-10-28.
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
  look under OD-E1 (a), so a single Holm step at one final cannot run). **Default: fixed sequence** over the members
  remaining in the family at D0, earliest final first. If both remain, H-A0 is tested
  first, at its own final, at 0.025; H-A1 is tested at its own final, at 0.025, **only if H-A0 was rejected**; if
  H-A0 is not rejected, H-A1 spends nothing and is reported with its intervals only (they still feed the NO-GO
  clause). This keeps the full 0.025 on the arm whose final is read first and on which the power figures (section 8)
  are computed; its cost is that an A1 that beats the market while A0 does not cannot give a GO.
  **Owner-visible alternative:** Bonferroni, each hypothesis at 0.025/k at its own final, with Holm only among
  hypotheses whose finals share one look (none under the defaults).
- **k is recorded at D0 after UNTESTABLE marking.** Under the default bar and the section 8 figures k is expected to be
  0 (H-A0 0.263; H-A1 measured, preliminary: UNTESTABLE at 20/45/90 dates, same as H-A0): EDGE-1 would then carry no hypothesis, no alpha and no GO route. The fixed
  sequence runs over the members remaining in the family at D0, earliest final first. (k is written in the signing
  follow-up row; with both members kept, the Bonferroni alternative would test each at 0.0125.)
- **Why 00-16 and not each sub-block:** declaring the four sub-blocks for each arm would make k = 8 and, under the
  Bonferroni alternative, each level 0.0031. The sub-blocks 00-05, 06-09, 10-12, 13-16 are reported with their intervals, no alpha; the GO/NO-GO
  rule's NO-GO test reads their **lower** bounds, which needs no alpha. Owner option OD-E3: declare per-block
  hypotheses instead.
- 17-23: differences only (M0 ratio floor), no alpha.
- **Seeds (fixed at signature):** fixed-market 20261023, crossed 20261024, 10,000 draws each (M3).

## 4. Looks

- **Interim (20 countable dates): futility only, non-binding, spends nothing.** Boundary per M4.2: **c = 0.2656** for
  each of H-A0 and H-A1 (α_d 0.025, β 0.20, t = 20/45). "EDGE-1 crossed futility in every arm" (GO/NO-GO Gate 1)
  means Z < c for **every EDGE-1 hypothesis whose interim has been read** by 12-07 (GO/NO-GO rule §1, §2.4).
- **Final (45 countable dates, per hypothesis at its own final):** the section 3 multiplicity rule (default fixed
  sequence H-A0 then H-A1), then the falsifiers (section 5) for each rejected hypothesis.
- **H-A1's interim and final are additionally gated by section 6.3** (the t3-r3 look).
- **UNTESTABLE arms are still scored (M4.4).** An UNTESTABLE hypothesis's arm is still scored at its declared looks with
  intervals only (no alpha, no Z, reported beside; it neither blocks nor satisfies NO-GO), so the L1 measurement is
  made whatever the bar (section 0: EDGE-1 is the exhaustion register's L1 exit measurement). The owner's other option
  is to read an UNTESTABLE arm's bounds for NO-GO as well (GO/NO-GO rule question (g), third alternative).

## 5. Falsifiers binding on any GO (M7, restated with EDGE-1 values)

1. **Crossed (date × market):** crossed point estimate on the same side and crossed one-sided 80% upper bound below 1
   (E1) or 0 (E2) [80% PROPOSED, OD-T2].
2. **Per-market sign:** R_m < 1 (E1) or D_m < 0 (E2) in **at least 8 of 11** markets, block 00-16.
3. **Input-removed twin:** effect_twin / effect_arm **< 0.75** on the same rows, using the section 1 twins (A0: T1;
   A1: A0). Evaluated **only for hypotheses rejected under M6**; **effect_twin <= 0 counts as < 0.75**. For A0 it is
   valid only under the section 7 replay condition.

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

EDGE-1 adds one family (members H-A0, H-A1 before UNTESTABLE marking; k recorded at D0 and expected to be 0 under the
default bar, section 3; 0.025 one-sided; fixed sequence by default) and reserves no date against any other family. It
spends no CAMPAIGN_LEDGER decision. Rows: [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md) `EDGE1-*`.

## 7. Validity (M8) plus EDGE-1 specifics

- A served-release change on the 00-16 path inside the window voids the A0/A2 dates after it unless a segment rule is
  signed before it lands; the #162 landing and any item-337 flip are such changes (EXHAUSTION_REGISTER L18).
- The A1 and A2 shadow stages must store their arm hash per snapshot; coverage below 90% in 00-16 voids that arm.
- **Falsifier 3 for A0 is valid only if the unmodified A0 captured-input replay reproduces the served vector of record
  per M8 (within 1e-9 on at least 99% of rows).** T1 is a replay joined to the served vector, the join EF §1k warns
  about; if the reproduction fails, falsifier 3 cannot be evaluated for H-A0 and does not hold (no GO from H-A0).
  **M8 is evaluated on forward rows replayed at the frozen A0 hash; development rows predate the freeze and are exempt
  (code drift, 490 capture commits).**
- **Evidence for the exemption (outcome-blind, development dates; 2026-10-21).** The unmodified current-code replay
  of each development snapshot was compared with the record's `recorded_distribution`, the served vector written by
  `snapshot_store.py` (a model output, not an outcome): codecheck branch `0941dc432afe8ff47291938479d17c2931ef3a6b`,
  `tools/research/model_edge_lever5/served_repro.py` (`run.py served`), 732 folders, 128,594 snapshots, 0 errors.
  **0 of 12 markets reach 99% within 1e-9**: the per-market share within 1e-9 is 0.040 (dallas) to 0.224
  (san-francisco), p99 max_abs 0.66-0.88. By hour band (share within 1e-9 / median max_abs): 00-05 0.247 / 0.0017;
  06-09 0.112 / 0.0063; 10-12 0.098 / ~0; 13-16 0.042 / 0.060; 17-23 0.004 / 0.275. Cause: code drift since capture.
  `model_version` differs on 100% of rows and `model_constants.py` / `model_distribution.py` changed on 100%; artifacts
  changed on 0 rows and model kind (hgb) differs on 0; no mismatched row has an identical identity; the development
  captures span 490 distinct capture commits. Consequence: any development "replay" is **current code**, not the
  served vector of record, and development twin or stage deltas are "current code ± twin", not "served ± twin".

## 8. Power

- **Power simulator (updated 2026-10-20):** harness v3 (H3/H7), `claude/harness-v3-20261019` @ `2f3f3e8e6b542a419204afe802dae4545abc10d7`, `docs/research/harness-v3-2026-10-19.md` and its "Addendum 2026-10-20: master-agent rulings"; `HARNESS_V3_SHA256` at that tip `987e171775c596f6e50ac72b9bd54880399e4fafcc11865cdec0a2375970b4cf` (recomputed on the workstation with `v3_score.harness_v3_sha256()`; the addendum's runs used `35024814…`). Development reads only (dev dates 08-01..09-29).

  | Forward dates x 11 markets | Parametric MDE80 | Parametric P(GO given effect) | Corrected (real-noise calibration) | P(GO given null) | Verdict vs bar 0.0133 |
  | --- | --- | --- | --- | --- | --- |
  | 20 | 0.0097 | 0.32 | ~0.22 | 0.026 | TESTABLE on the parametric MDE80 (re-confirm with `resampled_power`) |
  | 45 | 0.0085 | 0.40 | ~0.31-0.33 | 0.027 | TESTABLE on the parametric MDE80 (re-confirm) |
  | 90 | 0.0079 | 0.43 | ~0.35 | 0.040 | TESTABLE on the parametric MDE80 (re-confirm) |

  **90 dates (finding 12):** P(GO given null) = 0.040 exceeds the 0.025 design level, so **no extension of EDGE-1 to
  90 dates may be signed without a type-I correction** (a recalibrated critical value or a resampling check at that
  N); the 90-date row is sizing context only.

  **Scale (review finding M3):** this table is **MG-1's paired arm − served Brier against MG-1's own bar 0.0133
  Brier**, not the E1 test of R against the market. It sizes an arm − served contrast; it says nothing about whether
  H-A0 (R < 1) is TESTABLE. The E1 figure on R is below ("MDE80 per hypothesis").
  MG-1 development variance, half effect −0.0050 Brier at 00-16. **The parametric figures 0.32/0.40/0.43 are
  over-optimistic:** on real MG-1-like noise H3's parametric power is biased **high by 0.07-0.11 absolute**
  (predicted 0.581/0.410 at 20 dates vs empirical 0.473/0.309; at 45 dates 0.584/0.411 vs 0.516/0.323), so the
  half-effect power is **roughly 0.22-0.35** across 20-90 dates. Pre-registration power statements use the resampling
  estimator `v3_power.resampled_power`; a quoted parametric figure is reduced by ~0.10 at 20 dates and ~0.07-0.09 at
  45. The parametric MDE80 is optimistic in the same direction, so the TESTABLE verdict (0.0097 / 0.0085 / 0.0079
  against 0.0133) must be re-confirmed with `resampled_power` on the frozen arms before D0 (M4.4). The market
  component holds power near 40% or below at any season length (EF §10j).
- **MDE80 per hypothesis (filled 2026-10-20, review finding M3(ii); development dates only):**

  | Hypothesis | Forward dates x 11 | MDE80 on R (resampled_power) | Same in 00-16 Brier | Resampled power at R = 0.95 / 0.985 | Verdict vs bar 0.05 on R (vs ~0.015 contrast) |
  | --- | --- | --- | --- | --- | --- |
  | H-A0 | 20 | 0.308 | 0.0148 | 0.12 / 0.07 | UNTESTABLE (UNTESTABLE) |
  | **H-A0** | **45** | **0.263** | **0.0127** | **0.17 / 0.10** | **UNTESTABLE (UNTESTABLE)** |
  | H-A0 | 90 | 0.242 | 0.0117 | 0.20 / 0.12 | UNTESTABLE (UNTESTABLE) |
  | H-A1 (PRELIMINARY) | 20 | 0.308 (A1-1 envelope 0.302-0.312) | — | 0.124 / 0.069 | UNTESTABLE (UNTESTABLE) |
  | **H-A1 (PRELIMINARY)** | **45** | **0.263 (0.258-0.267)** | — | **0.166 / 0.098** | **UNTESTABLE (UNTESTABLE)** |
  | H-A1 (PRELIMINARY) | 90 | 0.242 (0.238-0.246) | — | 0.196 / 0.116 | UNTESTABLE (UNTESTABLE) |
  | H-A2 | — | none: E2 closed in development (section 1.1) | — | — | not in the family |

  - **Method:** `v3_power.resampled_power` (8,000 crossed resamples of dates and markets, seed 20261021) on the
    **served-vs-market** 00-16 influence table, z = (Brier_served − R̂·Brier_market) / mean(Brier_market) per (date,
    market) cell, re-centred and shifted; MDE80 is the shift at which the GO rate (upper 95% bound of R below 1) is
    0.80 (found as the 80th percentile of the per-resample GO thresholds in the estimator's own draw order, then
    re-checked: resampled_power at the MDE80 = 0.800). Not MG-1 paired variance.
  - **Inputs and provenance:** dev table 2026-08-01..2026-09-29 (the gate ticket covers 07-31..09-29; 55 balanced
    dates x 11 markets), `C:\swarm\v3layout` (manifest sha256 `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`),
    read through the harness-v3 gate (family `harness_v3_controls`, purpose control; `v3_controls.Dev` asserts no row
    after 09-29). Code: read-only `C:\wt\hv3` at `2f3f3e8e6b542a419204afe802dae4545abc10d7` (`HARNESS_V3_SHA256`
    `987e171775c596f6e50ac72b9bd54880399e4fafcc11865cdec0a2375970b4cf`; `v3_power.py` sha256
    `8d22ae13566b59e9ec1d642d2aebdc20fb2444eb0e2eb6843e0d16c6e0d22b37`; served arm code sha256 `b4e932e3…`). Probe:
    [`provenance/edge1-rpower-probe-2026-10-20.py.txt`](provenance/edge1-rpower-probe-2026-10-20.py.txt) (sha256 as run
    `088939af2af4940db65da0767e193e1657a6a25ea1ab2f83fea17faf2749bba7`), run once through
    `workstation_heavy.ps1 -Kind pytest -Queue` on 2026-10-20; output
    [`provenance/edge1-rpower-2026-10-20.json`](provenance/edge1-rpower-2026-10-20.json) (sha256 as written
    `d0ba9ff4ff34d7f65470ba0601afa74b736b5717f0ae07817846d6b88d7fcdcf`).
  - **H-A1, PRELIMINARY (filled 2026-10-21, master-approved; the A1 hash is not frozen and the t3-r3 stage is
    excluded: A1 = A0 + t3-r3 + A1-1, and this sizes served + A1-1 only).** MDE80 on R with served variance, the A1-1
    deviation envelope in brackets (table above); power at R = 0.95 / 0.985 as tabled, the worst envelope within 0.003
    of nominal. n: 55 balanced development dates (2026-08-01..09-29) x 11 markets, 00-16. Verdict: UNTESTABLE against
    both the 0.05 bar and the ~0.015 contrast. **No effect estimate exists: the arm's Brier was never computed (no R,
    sign, interval or per-cell value).**
    - Method: `v3_power.resampled_power` on the served-vs-market 00-16 influence table, z = (Brier_srv − R̂·Brier_mkt) /
      mean(Brier_mkt) per cell, 8,000 crossed resamples, seed 20261021; the served-variance figures reproduce the A0
      run exactly (asserted). A1-1 enters as a **bound, not a measurement**, because the lever-5 rows hold tv, not
      vectors: per-snapshot |ΔBrier| ≤ 4·tv/n_bands, under 2 adversarial and 32 random sign patterns; worst case 0.145
      R per cell. Those tv deltas are **current-code replay deltas** (section 7 M8 note), not served ± stage.
    - Provenance: harness `C:\wt\hv3` `2f3f3e8e6b542a419204afe802dae4545abc10d7`; `HARNESS_V3_SHA256`
      `987e171775c596f6e50ac72b9bd54880399e4fafcc11865cdec0a2375970b4cf`; `v3_power.py`
      `8d22ae13566b59e9ec1d642d2aebdc20fb2444eb0e2eb6843e0d16c6e0d22b37`; labels and prices via the `v3_controls.Dev`
      gate (<= 09-29); manifest `C:\swarm\v3layout\manifest.json`
      `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`; inputs: the lever-5 workstation replay rows
      (variant `bucket_transition_repointed`), archived at `C:\wt\workstation-chat\l-data\model-edge\lever5-ws-20261021`;
      probe [`provenance/edge1-a1-rpower-prelim-probe-2026-10-21.py.txt`](provenance/edge1-a1-rpower-prelim-probe-2026-10-21.py.txt)
      (sha256 as run `b3af958c8ec21273a824c09e830202f4f1b80b9059e8d8045f1cece96dd268cb`), output
      [`provenance/edge1-a1-rpower-prelim-2026-10-21.json`](provenance/edge1-a1-rpower-prelim-2026-10-21.json) (sha256 as
      written `294ca06a9b5bb26eaebd1c5c94bf34e9b1502f633f5f26508c9b3c8293f0aa23`; git normalises line endings, so the
      committed blob may hash differently); one run via `workstation_heavy`, 1 passed in 27 s.
    - The final H-A1 figure is still filled in the A1 logistics row before D0 on the frozen hash (t3-r3 included);
      k stays recorded at D0.
  - **Development context from the same run (sizing only):** served/market R 1.432 / 1.483 / 1.467 / 1.855 by block,
    1.510 at 00-16; market Brier 00-16 0.0483 (cell mean).
  - **Caveats:** the served vector of record stands in for A0 (it predates the 10-06 lock-in and 10-09 fixes and N12);
    the estimator resamples markets as well as dates, so it is more conservative than the fixed-market primary (M3).
    INFERENCE from the variance components in the same output: the market component dominates the crossed SE, so a
    dates-only resample would shrink the MDE80 by roughly half, to about 0.15 on R, still far above 0.05. The verdict
    is re-confirmed on the frozen hash before D0 (M4.4).
  - **What the default bar does to H-A0 (M3(iii)):** under MDE80 > 0.05 on R (and equally under the ~0.015 contrast),
    **H-A0 is UNTESTABLE before D0**: it leaves the family (k drops), it cannot give a GO, and under the amended NO-GO
    rule it neither blocks nor satisfies NO-GO. The EDGE-1 programme contribution then reduces to A1 (deferred past
    12-21), so the 12-21 NO-GO rests on MG-1 alone (GO/NO-GO rule §4). Owner question (g) carries the choice.
- UNTESTABLE test per M4.4 applied before D0 on the frozen hashes.
- **NO-GO reachability:**

  **Per-arm NO-GO reachability, one arm in isolation** (harness-v3 addendum; the relayed §1 rule applied per arm: lower bound of R above 1.05 in every 00-16
  block and E2 upper bound above −0.5% of market Brier; MG-1-like arm variance; 20,000 simulations per cell):

  | Scenario | P(NO-GO) at 20 dates | 45 dates | 90 dates |
  | --- | --- | --- | --- |
  | dev-observed R (1.171 / 1.205 / 1.250 / 1.945 by block) | 0.821 | 0.988 | 1.000 |
  | half effect, R = 1 + (R_dev − 1)/2 | 0.087 | 0.207 | 0.358 |
  | null, R = 1 | 0 | 0 | 0 |

  Sensitivity with served-vs-market variance components: 0.28-0.43 at the dev-observed R (20-90 dates). Every
  development-fit blend weight is **0.00**, so E2 is not scored; under the amended NO-GO (GO/NO-GO rule §1, §2.4) that
  neither blocks nor satisfies NO-GO, and the per-arm NO-GO rests on the R clause alone. **If a draft freezes a non-zero blend weight, this simulation must be re-run.**
  **Programme-level reachability (re-run 2026-10-20, review finding B1; supersedes the per-arm table as the §1
  test).** The amended §1 rule is applied over the arms read by each decision date under the bundle defaults (§2.4):
  at 12-21 A0 (45 dates) and MG-1 (45 dates from 10-15, its 00-16 interval only); A1, A2 and NBM-2 absent; E2 not
  scored and E3 UNTESTABLE hold. Early NO-GO at Gate 1 = MG-1 not GO (upper 95% bound of MG-1 − served not below 0;
  MG-1's other falsifiers ignored, so this is a lower bound) **and** A0's 20-date interim Z < 0.2656; "no survivor
  queued" is assumed. One joint draw per simulation over MG-1's and A0's overlapping windows (A0 starts 10 countable
  dates after MG-1 in the not-held branch, 13 in the held one), two-way MoM components (PSD) of a balanced
  55-date x 11-market development table of the seven variables (A0 = served-vs-market influence per block and at
  00-16; MG-1-like vs market at 00-16; MG-1-like − served at 00-16), 20,000 simulations, seed 20261032 / 20261035.
  Same run and provenance as the EDGE-1 annex §8 MDE80 (`provenance/edge1-rpower-2026-10-20.json`).

  | Scenario (R means) | A0 clause | MG-1 clause | **P(NO-GO), A0 counted** | **P(NO-GO), A0 UNTESTABLE (default bar): MG-1 alone** | P(early NO-GO) |
  | --- | --- | --- | --- | --- | --- |
  | A0 at served dev R (1.43 / 1.48 / 1.47 / 1.86), MG-1 at 1.302 | 0.995 | 1.000 | **0.995** | **1.000** | 0.061 |
  | A0 at MG-1-like dev R (1.17 / 1.20 / 1.25 / 1.95), MG-1 at 1.302 | 0.375 | 1.000 | **0.375** | **1.000** | 0.060 |
  | half effect, served-based | 0.438 | 0.833 | **0.412** | **0.833** | 0.539 |
  | half effect, MG-1-like-based | 0.073 | 0.833 | **0.072** | **0.833** | 0.515 |
  | null, R = 1 and MG-1 = served | 0.001 | 0.000 | **0.000** | **0.000** | 0.565 |

  Not-held branch shown; the held branch differs by at most 0.004 in every cell. Reading:
  - **NO-GO is reachable at the programme level** under the defaults (0.37-1.00 at the development-like R), and 0
    under the null. If the owner answers (i) "absent arms block", P(NO-GO at 12-21) = 0 by construction.
  - **With H-A0 UNTESTABLE** (the default bar, EDGE-1 annex §8), the EDGE-1 condition of early NO-GO has no
    hypothesis left; it is then read as vacuously met, and early NO-GO = MG-1 not GO (0.06 at the dev effect, 0.54 at
    half, 0.96 under the null), with the survivor condition.
  - **Under the defaults Gate 1 = "MG-1 not GO": P(early NO-GO) ≈ 0.96 under the null (correct), ≈ 0.54 if MG-1 has a
    true half effect (a false redirect; EDGE-1 then has no hypothesis to reopen weather).** (Simulated MG-1-not-GO
    column: 0.961 / 0.540 not held, 0.959 / 0.536 held. The 0.56-0.57 null figure in the early NO-GO column is the
    A0-counted variant, which needs A0's interim and so does not apply under the default bar.) GO/NO-GO rule question (l).
  - **GO side (INFERENCE, not simulated here):** with H-A0 UNTESTABLE and A1 deferred, the only E1 GO route at 12-21
    is an MG-1 upper bound of R below 1, about 0.025 under R = 1 and near 0 at the development R of 1.30; GO is
    reachable in name only under the defaults. With H-A0 in the family, its power at R = 0.95 is 0.17 (annex §8).

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

One, motivated in section 1.1: A0's input-removed twin (M7.3) is the public-forecast substitution twin T1
(`forecast_high` from `nws_hourly` alone), not the harness-v3 generic blank-inputs-and-fall-back twin, which is
identical to A0 for a served arm and would fail falsifier 3 by construction. T0 (climatology prior) is reported beside,
non-binding. A1 uses the generic mechanism unchanged.

## 10. What this draft does NOT claim

- No development figure is evidence; the A1 survivors are leads until scored here.
- No market-making result: E1/E2 are forecast endpoints. The maker endpoint E3 is a separate instrument
  (GO/NO-GO rule §2.3).
- No in-season claim (section 0 scope clause).

## 11. Signature

UNSIGNED. On signature the owner adds one DECISION_LOG row with this file's raw SHA-256, the methods annex's raw
SHA-256, the OD-A6 branch (D0), and the A0/A1 arm hashes. **The A0 hash (with T1/T0) may follow in a second logistics
row before D0, like A1's, provided section 1 is unchanged**, because N12 may not be on master by the signing; that row
also carries the full SHA of the pinned post-N12 master commit (section 1.2). k is recorded in the same row (section 3).

## 12. Owner decisions this draft needs

- **OD-A6 (88a hold for snapshot market vectors):** not held → D0 2026-10-25 (master-agent recommendation); held →
  D0 2026-10-28.
- **OD-E1:** the t3-r3 conflict (section 6.3): (a) default, (b), or (c).
- **OD-E2:** sign or amend (arms, N 20/45, multiplicity: fixed sequence H-A0 then H-A1 (default) or Bonferroni
  0.025/k at each own final, k recorded at D0).
- **OD-E3:** 00-16 declared block (default) or per-block hypotheses.
- **OD-E4:** the A1 survivor list as filled (A1-1 = C-L13-BT; logistics if it meets the section 1 rules).
- **OD-E6:** keep A1 as a separate arm (default) or drop A1-1 from it.
- **Question (h):** LA and SF live marine and the SST refresh, capture only (section 13); default yes.
- **OD-E7:** A0's binding twin T1 keeps `nws_hourly` alone (default) or Open-Meteo alone (section 1.1); T0 stays a
  non-binding sanity control either way.
- **OD-E5:** E2 closed in development (w_b = 0.00 in each sub-block on 07-31..09-29; no forward E2 instrument; H-A2
  not in the family) unless the owner redefines A2 (default: closed; the model added nothing beyond the market
  price on those dates). Proposed EXHAUSTION_REGISTER entry at signature (production docs change, not in this
  draft): "E2 frozen blend, served + market: CLOSED in development, all four w_b 0.00 (screens doc §9)".

## 13. Owner question (h): LA and SF live marine and the SST refresh (capture only; not an EDGE-1 arm)

Question (GO/NO-GO rule §5 (h)), default **yes**: build LA and SF live-marine registry entries and a scheduled SST
water-contrast refresh, **outcome-blind, as capture and features only**. Any model use goes through a later
pre-registration; nothing here enters A0, A1, T1 or any EDGE-1 date.

- **What the code has (checked 2026-10-20 on this branch's base, no data read):** `MARINE_CONTEXT_REGISTRY`
  (`src/weather/sources/marine_context.py:50-198`) is keyed by market id. It **does** hold one CO-OPS entry each under
  `los-angeles` (9410660, Los Angeles) and `san-francisco` (9414290, San Francisco), and both markets list the
  `marine_context` source (`src/weather/market/market_registry.py`). So the gap is not a missing key. It is that
  **live marine data has been dark since 2026-06-13** because the sidecar refresh is unscheduled, and
  `marine_water_contrast` is `disabled_unpinned` (EXHAUSTION_REGISTER S27; `pooled_training.py`). The LA/SF station
  choice has never been reviewed under the Q-20 rule. Whether the host's capture writes LA/SF marine rows today was
  not checked; it is a host coverage count.
- **Q-20 mechanism rule (OPEN_QUESTIONS Q-20; EXHAUSTION_REGISTER order 13):** a stated physical mechanism and a
  no-source control **before** capture. Stations are chosen on geography and mechanism only, without reading labels,
  scores or market prices.
- **LA candidates:** NDBC **46025** (Santa Monica Basin buoy: offshore SST and onshore-flow wind upstream of KLAX in
  sea-breeze and marine-layer regimes); CO-OPS **9410660** (Los Angeles, already registered: nearshore water and air
  temperature). Proposed: both, 46025 as the upstream SST source and 9410660 as the nearshore contrast.
- **SF candidates (proposed by the same rule):** NDBC **46026** (San Francisco bar, about 18 NM west: the Pacific SST and
  upwelling signal that drives the marine layer through the Golden Gate and San Bruno Gap towards KSFO); CO-OPS
  **9414290** (San Francisco, already registered: water at the Gate). Proposed: both. A south-bay CO-OPS gauge nearer
  KSFO is a third option, to be named at build time.
- **No-source control (declared now):** the same features computed from the climatological SST for the station and
  calendar day (prior years only), so that a later pre-registration can separate live marine information from
  seasonality.
- **Station IDs are proposed from public station listings and are to be verified against the NOAA station pages at
  build time.** No external fetch was made for this draft.
- **Cost:** one capture build (registry rows, a refresh entry point, tests on fixtures) plus one scheduled task, after
  the host Python C upgrade. It is a roll-sensitive serving-source change if a loop imports it (roll verdict decides).

## Sources

- [Methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md); [GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md); [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md).
- [MG-1](../morning-guidance-read-mg1-preregistration-2026-10-04.md); [evening-fix](../evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md) §3.3, §10; [t3-r3](../remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md) §5, §6, §8, §9.
- [Reserved confirmation window](../../operations/reserved-confirmation-window.md); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-10-04, 2026-10-13, 2026-10-15, 2026-10-16, 2026-10-17.
- [Exhaustion register](../../operations/EXHAUSTION_REGISTER.md) §0.2, §3 (L1, L18), §5; [findings digest](../../operations/FINDINGS_DIGEST.md); EF §1, §2, §5, §10h, §10q.
