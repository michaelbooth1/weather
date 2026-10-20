# DRAFT, UNSIGNED: model-edge pre-registration template and methods annex, 2026-10-19

> **Status: DRAFT-UNSIGNED, NOT ACTIVE.** Written on the workstation (model-edge week 1) for the owner's single
> sign-off on Fri 2026-10-23. It authorises nothing: no scoring, no reservation, no alpha, no code, no serving change.
> It binds only once the owner signs it (section 9). Once signed it is never edited; a change is a new dated amendment
> file that names this file and its signed SHA-256, states its motivation, and is written before the affected
> quantity is read.
>
> **Signed SHA-256:** `________________________________________________________________` (left blank; the hash of
> these bytes lives in the DECISION_LOG signing row, because a file cannot carry its own hash).
>
> **Data rule this draft was written under:** no label, settlement, market price, 88a, panel or score data for any
> UTC date >= 2026-09-30 was read; nothing for 2026-10-16..11-13 was read at all. Development numbers cited below are
> from dates <= 2026-09-29 and are sizing context, never evidence.

- **Owns:** (A) the fill-in template every model-edge instrument pre-registration uses; (B) the methods annex those
  pre-registrations cite by section number instead of restating: endpoints E1 and E2, single-shot scoring with
  pre-registration and arm-hash verification, the non-binding O'Brien-Fleming futility interim, date-clustered
  inference, and multiplicity.
- **Read when:** drafting, reviewing or scoring any instrument of the model-edge programme (EDGE-1, the NBM-2
  placeholder, later instruments); building the scorer or the power simulator.
- **Do not use for:** the instrument-specific arms, dates and falsifiers ([EDGE-1 annex](edge1-annex-DRAFT-2026-10-19.md));
  the alpha spent or reserved ([alpha ledger](alpha-ledger-DRAFT-2026-10-19.md)); what a result triggers
  ([GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md)). Signed instruments (MG-1, the evening-fix scorer, t3-r3 13-16)
  are **not** governed by this annex; they stay exactly as signed.

---

# Part A. Template (copy, fill every `<...>`, delete nothing)

```
# DRAFT, UNSIGNED: <instrument id> — pre-registration, <YYYY-MM-DD>

Status: DRAFT-UNSIGNED. Signed SHA-256: (blank; DECISION_LOG row).
Data rule: <what was and was not read while writing; embargo statement>.
Methods: this file adopts the model-edge methods annex
(`docs/research/model-edge-2026-10/prereg-template-and-methods-annex-DRAFT-2026-10-19.md`) at signed SHA-256
<64 hex>, sections M1-M8, except where section 9 below lists a deviation with its motivation.

0. Authority and scope        owner rows; what is NOT scored; interaction with every signed instrument (MG-1,
                              evening-fix, t3-r3, others in the alpha ledger) and why no date or family is double-spent.
1. Arms (frozen)              arm id, definition, frozen arm hash (M5.2), comparator, input-removed twin (M7.3).
2. Population and dates       markets (fixed list), D0 rule (non-outcome conditions only), countability rule,
                              interim N and final N in countable dates, calendar projection, DST/season segments.
3. Endpoints                  which of E1/E2 (M1, M2) per arm; the pre-declared block(s); weights.
4. Inference and multiplicity family members; alpha (one-sided); Holm order; seeds; draws (M3, M6).
5. Interim and final looks    information fraction; futility boundary table fixed now (M4); earliest read dates;
                              embargo gates.
6. Falsifiers (binding on GO) crossed, per-market sign, input-removed twin, plus instrument-specific (M7).
7. Validity / VOID            PIT, replay reproduction, arm-hash mismatch, coverage, leakage, comparator change (M8).
8. Power                      power-simulator run id and output hash; MDE per endpoint; UNTESTABLE test (M4.4).
9. Deviations from the annex  each with its motivation (or "none").
10. What this does NOT claim
11. Signature                 UNSIGNED; DECISION_LOG row carries the raw SHA-256 of this file and of each arm.
12. Owner decisions needed    OD-<id> list with defaults.
Sources
```

Rules for the template:
- A field may say `PLACEHOLDER — <who fills it, by when>`; a signed file may not contain a placeholder that changes a
  rule. Placeholders for logistics (dates of a look, row counts) follow DECISION_LOG 2026-10-13 ("logistics need no
  signature").
- Every number is either fixed in the file or named as the output of a hash-pinned tool run whose hash is in the file.
- A development number is labelled "development, dates <= 2026-09-29, sizing only".

---

# Part B. Methods annex (sections M1-M8)

## M0. Common definitions

- **Snapshot:** one captured served payload for a market at `captured_at_utc`, with its band rows.
- **Market probability:** `p_market_yes` per band from the market vector **stored in the snapshot payload**, the column
  the model-parity harness uses (`tools/research/model_parity/harness.py`, `MARKET_COLUMNS`). Never 88a tapes; never a
  price joined from another capture. Whether those stored vectors fall under the 88a panel hold is the open OD-A6
  question (EDGE-1 annex §2.1); no instrument reads them for dates the hold covers.
- **Label:** the venue winner from the settlement ledger `data/settlements/<market>/ledger.jsonl` **only**; never
  `market_day_labels.csv`, never a tape-derived proxy (EF §5, §10d). A market-day without a ledger row is
  non-countable, decided before any score.
- **Countable:** `promotion_countable` market-days (EF §5), with both the arm vector and the market vector present for
  at least 90% of the block's snapshots. Countability is decided from capture, replay and ledger-presence metadata
  only, never from a score. A **countable date** is a local target date with at least 9 countable markets in the
  instrument's fixed market list (proposed; instrument may tighten).
- **Snapshot Brier:** mean over the snapshot's complete band support of (p − outcome)², p as the arm records it.
- **Weights:** equal snapshot weights within a market-day cell, then equal market-day weights (MG-1 §4 form).
- **Blocks (local clock hour):** 00-05, 06-09, 10-12, 13-16 (EF §10q ladder), their union 00-16, and 17-23. **R is not
  computed for any block whose window market Brier is below 0.005** (harness `RATIO_MARKET_FLOOR`); 17-23 is
  therefore reported as differences only (market Brier there is about 0.0008, EF §10q).

## M1. Endpoint E1 — arm versus market, Brier ratio

For arm a and block b over the countable market-days of the look:

    R_ab = Σ w · Brier_arm(a) / Σ w · Brier_market        (ratio of weighted means, weights as M0)

- Inference is on log R_ab (M3). **H1(E1): R_ab < 1** (the arm beats the market's own prices in block b).
- An instrument pre-declares, per arm, **the block(s) its E1 primary tests**; every declared (arm, block) pair is one
  hypothesis in the family (M6). All other blocks are reported beside with no alpha.
- E1 is a **market-parity** endpoint. EF §1 places served in-season at 1.423x and EF §10q at 1.29x (00-16 after both
  repairs, development); a pass would be the first measured parity. Shrinkage toward the market is **not** an E1
  arm (EF §1c: it closes the gap by construction); market prices are never arm inputs for E1.

## M2. Endpoint E2 — frozen-weight model + market blend ("complementary information")

    q_blend = normalise( w_b · p_model + (1 − w_b) · p_market )     per block b, linear pool

- **Weights:** one w_b per block b in {00-05, 06-09, 10-12, 13-16} (00-16 uses the per-block w of each row's block),
  fit by minimising the M0-weighted mean Brier of q_blend on **development dates 2026-07-31..2026-09-29 only**
  (EF §5: never pool across the 07-31 provenance boundary; nothing >= 09-30 is touched). w_b is constrained to
  [0, 1], fitted on a grid of step 0.01, ties to the smaller w (less model). The fit script, its input manifest hash
  and the resulting w vector are frozen into the arm hash (M5.2) **before D0**.
- **Model component on development dates:** the captured-input replay of the frozen model arm (not the served vector
  of record, which carried the pre-10-06 lock-in defect, EXHAUSTION_REGISTER §0.2) wherever the replay reproduces;
  rows the replay cannot produce are dropped from the fit, counted and disclosed.
- **Endpoint:** D_E2 = Brier(q_blend) − Brier(market), per declared block, M0 weights, with the materiality test
  stated against market Brier (E2 GO needs a gain of at least 5% of market Brier; [GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md)).
  R_E2 = Brier(q_blend)/Brier(market) is reported beside.
- **Label: "complementary information".** A blend that beats the market shows the model carries information the
  market's prices do not; it is **not** a claim that the model alone beats the market (that is E1), and it is not by
  itself an edge or a trading result. It is reported under that label in every summary.
- **Degenerate fit:** if every w_b the instrument declares is 0.00, the blend **is** the market and D ≡ 0. The arm is
  then **closed in development** (a measured development null for the exhaustion register), not UNTESTABLE (M4.4): it
  gets no forward instrument and no hypothesis, and it neither blocks nor satisfies a NO-GO clause.
- **Training-score rule (EF §5):** the frozen blend's Brier on its own development fit dates is computed and reported
  first; a blend that does not beat the market on its own training dates is reported and its forward look still
  runs, but GO under E2 then also needs the owner's explicit acceptance.

## M3. Date-clustered inference

- **Primary: fixed-market, date-clustered** (DECISION_LOG 2026-09-30 guardrails, verbatim in MG-1 §4). The market
  list is fixed in advance; dates are resampled as clusters, multinomial date bootstrap, **10,000 draws** (enough for
  percentile tails at the smallest per-hypothesis level, 0.025/k), seed fixed in the instrument file at signature.
- **Statistic:** log R*_ab per draw (ratio of re-weighted sums, M1); D*_E2 per draw.
- **One-sided p-value:** p = (1 + #{draws with log R* >= 0}) / (1 + draws) for E1; the same with D* >= 0 for E2. The
  instrument's level-α_j decision is equivalent to the one-sided (1 − α_j) percentile upper bound of R being below 1
  (E1) or of D below 0 (E2).
- **Crossed date × market** estimate and interval: the 81a/harness crossed weight method
  (`crossed_weights` in `tools/research/missing_information/methods.py`), 10,000 draws, seed = instrument seed + 1. Reported beside; binding
  as a falsifier (M7.1). Its power is capped by the 11 market clusters at any N (EF §10j, MG-1 §5); that is why it is
  not the primary.
- **Interim z for futility:** Z = −log R̂_ab / SD*(log R*_ab) for E1 and Z = −D̂ / SD*(D*) for E2, both from the
  fixed-market draws (positive Z = arm better than market).
- **Never:** exchangeable market-day resampling (EF §5); pooling strata or the 07-31 boundary; re-reading 79a, 81a,
  111h as evidence.

## M4. Interim: non-binding O'Brien-Fleming futility, boundaries fixed now

### M4.1 Design

- **One interim, futility only, non-binding.** No efficacy stop exists, so the interim spends **no alpha**, and because
  the futility boundary is non-binding, ignoring it cannot inflate the type I error: the final test keeps its
  fixed-design level. No GO can be declared at the interim.
- **Spending:** Lan-DeMets O'Brien-Fleming-type **beta**-spending, β = 0.20,
  β(t) = 2 − 2Φ(z_{1−β/2} / √t). Information fraction t = n_interim / n_final in countable dates.
- **Boundary:** stop for futility (recommend; non-binding) if Z_interim < c, where
  c = (z_{1−α_d} + z_{1−β}) √t + Φ⁻¹(β(t)), and α_d is the per-instrument design level.

### M4.2 Boundary table (fixed before any join; computed 2026-10-19 with `scipy.stats.norm`, no data)

For the EDGE-1 schedule t = 20/45 = 0.4444, β(t) = 0.05456:

| Design level α_d (one-sided) | Drift under the design alternative | Futility boundary c | P(stop) under the null, normal approx. |
| --- | --- | --- | --- |
| **0.025 (default; per-instrument level)** | 1.8677 | **0.2656** | 0.605 |
| 0.0125 (Holm middle step) | 2.0553 | 0.4532 | 0.675 |
| 0.00833 (Holm first step, k = 3) | 2.1571 | 0.5549 | 0.711 |

- **Default: c = 0.2656 for every EDGE-1 hypothesis.** It is the least eager of the three to stop, which suits a
  non-binding rule whose purpose is to stop work early only when an arm is clearly not heading to the final pass.
- Recomputing with β = 0.10 gives c = −0.0472 at α_d = 0.025 (owner option; fewer stops, slightly more power kept).
- The design alternative is the effect at which the 45-date fixed design has 80% power (its MDE80); the power cost of
  the interim, if the boundary were treated as binding, is **computed: <= 0.0013 power (parametric)** (H7, harness v3
  addendum 2026-10-20; c reproduced in closed form as 0.26560). On an R-vs-market statistic an arm that trails the
  market crosses this boundary almost surely (P(stop) 1.000 at the dev-observed and half effects; 0.617 under R = 1).
- If the interim falls at a different countable-date count than declared (a missed date, an operational postponement),
  the boundary is recomputed **with the formula above at the actual t**, before the join, and the recomputation is
  recorded in the look receipt (M5.4).

### M4.3 What the interim may and may not read

- It reads exactly the M1/M2 statistics and Z for each declared hypothesis, on the first n_interim countable dates.
- It does not compute or print per-market signs, the crossed interval, twins, blocks other than the declared ones, or
  any other summary. Its output is "futility crossed: yes/no" per hypothesis plus Z and c, written to the receipt.
- Any embargo or reservation that forbids reading a date (EDGE-1 annex §6) also forbids the interim on it; the interim
  then waits.

### M4.4 Power simulator and UNTESTABLE

- Before signature, the instrument names one hash-pinned run of the power simulator (**H3**, harness v3, being built on
  `claude/harness-v3-20261019`; run id and output SHA-256 recorded in the instrument file) that reports, per declared
  hypothesis, the MDE80 at n_final under M3, from development dates <= 2026-09-29 only.
- **UNTESTABLE** (pre-declared): a hypothesis whose MDE80 exceeds its bar is marked UNTESTABLE **before D0**; it keeps
  no alpha (it leaves the Holm family, and the family's k drops), and it cannot produce GO or count towards NO-GO as a
  measured null. Bars: E1 — **MDE80 on R greater than 0.05**, i.e. a 5% Brier gain over the **market's own Brier**
  (about 0.0025 Brier at a 00-16 market Brier near 0.049); the same materiality scale as the E2 GO (b) line
  [PROPOSED; owner may set another]. **Correction 2026-10-20 (review finding M3):** this is **not** the scale of the
  EF §1d bar or of harness `LEAD_GAP_SHARE` (`harness.py:57`), which is 5% of the served − market **gap**: about 1.45%
  of market Brier at 1.29x, i.e. **about 0.015 on R**. That gap-share bar is stated for contrast only; it is stricter
  (it would mark UNTESTABLE anything the 0.05 bar does, and more). E2 — MDE80 on D greater than 5% of market Brier
  (the GO (b) materiality line). The MDE80 is computed on the **endpoint's own scale** (R vs market, served-vs-market
  variance), never by borrowing an arm − served MDE in Brier units.
- **Power estimator for pre-registration statements:** `v3_power.resampled_power` (crossed resampling of the
  development cells, re-centred and shifted). The parametric H3 power is biased **high by 0.07-0.11 absolute** on real
  noise (harness v3 (H3/H7), `claude/harness-v3-20261019` @ `2f3f3e8e6b542a419204afe802dae4545abc10d7`, `docs/research/harness-v3-2026-10-19.md` and its "Addendum 2026-10-20: master-agent rulings"; `HARNESS_V3_SHA256` at that tip `987e171775c596f6e50ac72b9bd54880399e4fafcc11865cdec0a2375970b4cf` (recomputed on the workstation with `v3_score.harness_v3_sha256()`; the addendum's runs used `35024814…`). Development reads only (dev dates 08-01..09-29)); if a parametric figure is quoted, subtract ~0.10 at 20 dates and ~0.07-0.09 at 45, and label it
  parametric. Example: MG-1's half-effect parametric 0.32 / 0.40 / 0.43 at 20 / 45 / 90 dates is roughly
  **0.22-0.35** corrected; the parametric MDE80 (0.0097 / 0.0085 / 0.0079, TESTABLE against 0.0133) is optimistic in
  the same direction and is re-confirmed with `resampled_power` before D0.
- **NO-GO reachability** must be simulated with the NO-GO rule applied verbatim (harness `simulate_nogo`); a frozen
  non-zero E2 blend weight requires a re-run (the development fit is 0.00 at 00-16).
- Any statement such as "NO-GO is likely within ~20 dates" stays **INFERENCE**; cite the supporting computation
  (for EDGE-1: P(NO-GO at 20) = 0.821 under the dev-observed R, MG-1-like variance).

## M5. Single-shot scoring with pre-registration SHA and arm-hash verification

### M5.1 Scorer contract (code precondition; not built)

A scorer module (proposed name `weather.backtesting.model_edge_scorer`, to be written and tested on synthetic fixtures
and development dates <= 2026-09-29 only, landed before the first look, roll-free if no capture loop imports it; the
formal verdict is `scripts\ops\roll_verdict.ps1`'s) refuses to compute anything unless **all** hold:

1. **Pre-registration SHA:** the raw SHA-256 of the instrument file and of this annex, computed from the bytes at run
   time, each appears in a DECISION_LOG signing row (the evening-fix scorer pattern).
2. **Arm hashes:** for every arm, the arm hash recomputed at run time (M5.2) equals the hash in the signing row.
3. **Look identity:** the look id (`interim` or `final`) has no earlier receipt in the instrument's append-only receipt
   file; a second run of the same look refuses (exit non-zero, nothing printed beyond the refusal).
4. **Date gate:** the countable-date count reaches the look's n from countability metadata alone, and the local run
   date is on or after the look's earliest read date. **The date gate is not run on embargoed dates before the close**
   (today: UTC 2026-10-16..11-13 before the panel closes; not even the outcome-free count).
5. **Embargo and reservation gates:** no date the alpha ledger marks as reserved against this instrument's family, and
   no date inside an owner embargo in force (today: UTC 2026-10-16..11-13 refused until the panel closes, DL
   2026-10-17), is joined. A date the gate drops is counted, not read.
6. **Early-read token:** before the earliest read date the scorer refuses unless given a JSON read token bound to the
   instrument SHA-256 whose `decision_log_row` quotes a later owner row verbatim (evening-fix §7 form).

### M5.2 Arm hash

SHA-256 over a canonical JSON manifest listing: code commit (full 40-hex from `git rev-parse`), the SHA-256 of every
artifact and config the arm reads (model bundle, stage artifacts, blend weight file), `ML_MODEL_VERSION`, stage
versions and switches, and for E2 the weight-fit input manifest hash. The manifest file itself is committed beside
the instrument. A shadow stage stores this hash per snapshot; a mismatch on any eligible row is a VOID condition (M8).

### M5.3 One look per declared look

- The interim (M4) and the final are the only joins. Outcome-blind checks are allowed any time: vectors stored, arm
  hash per row, coverage, fallback reasons, replay reproduction, countability, release ids.
- **No re-test on the same dates**; an amendment applies only to dates after the look.

### M5.4 Receipt

Each look writes one receipt (JSON, append-only) with: instrument and annex SHA-256, arm hashes, scorer commit, input
manifest hash (dates, markets, snapshot ids), seeds, draws, the boundary used, every declared statistic, and the
SHA-256 of the result payload. The result is written once into the owning item and EF/RF, citing the receipt hash.

## M6. Multiplicity

- **Within an instrument:** every declared (arm, endpoint, block) hypothesis is one member of the instrument's family.
  Family-wise one-sided α = 0.025, **Holm step-down** on the M3 p-values: order p_(1) <= ... <= p_(k); reject
  H_(j) while p_(j) <= 0.025/(k − j + 1); stop at the first non-rejection. Holm needs every member's p-value at one
  look.
- **Staggered finals:** when the members' finals fall on different dates, Holm cannot run. The instrument then
  pre-specifies, before signature, **either** a fixed sequence (the earliest final first at the full 0.025; each later
  hypothesis tested at 0.025 only if every earlier one was rejected) **or** Bonferroni 0.025/k per hypothesis at its
  own final, with Holm only among members sharing a look. k is recorded at D0, after UNTESTABLE markings.
- **Interim:** spends nothing (M4.1).
- **Reported-beside quantities** carry no alpha and can neither rescue a failed primary nor create a GO.
- **Across instruments:** each signed instrument is its own family at its own alpha, recorded in the
  [alpha ledger](alpha-ledger-DRAFT-2026-10-19.md) (MG-1, evening-fix and t3-r3 as signed; the t3-r3 OD-B3 default of
  separate families was taken, DL 2026-10-15). A new instrument may not reuse a (family, date) cell the ledger already
  holds; overlapping dates are allowed only for different families and only where no reservation forbids them.
- **Sealed pre-boundary panel** (06-03..07-30): governed by [CAMPAIGN_LEDGER](../../operations/CAMPAIGN_LEDGER.md)
  (α 0.0025 two-sided per decision, q = 3.1098893); the model-edge programme may use **at most 2** of its remaining
  decisions, stratum B only, on batched development survivors only (alpha ledger row CL-B).

## M7. Falsifiers binding on any GO

A hypothesis that passes M6 is GO-eligible only if **every** falsifier below holds. A falsifier failure cannot be
rescued by amendment on the same dates.

1. **Crossed inference (date × market):** the crossed point estimate is on the same side (R̂ < 1; D̂ < 0) **and** the
   crossed one-sided 80% upper bound is below 1 (E1) or 0 (E2). The 80% level is PROPOSED because a 0.025 crossed
   level is unattainable at 11 market clusters (EF §10j); owner option to set it.
2. **Per-market sign:** at least 8 of the 11 fixed markets have the per-market R_m < 1 (E1) or D_m < 0 (E2) in the
   declared block.
3. **Input-removed twin:** each arm declares, before D0, a twin that is the same arm with the inputs it claims as its
   information removed and every other stage (floor mask, lock-in, fallbacks) unchanged; the twin's hash is frozen
   with the arm. With effect = 1 − R (E1) or −D (E2), the falsifier **holds only if effect_twin / effect_arm < 0.75**
   on the same rows. If the twin captures 75% or more of the effect, the effect is not attributable to the claimed
   information, and there is no GO.
   The default construction is harness v3 control (f) (`v3_arms.input_removed`: blank the arm's declared inputs and
   fall back to served). For a served-model arm that construction returns the arm itself, so such an arm must declare
   a substitution twin, as a section-9 deviation. The binding substitution must be one that **can fail**: replace the
   claimed information with what the market plainly has (EDGE-1 T1: the public NWS point forecast alone), not with a
   no-skill prior, which any skilled arm beats trivially (EDGE-1 T0, kept non-binding). The falsifier is evaluated only
   for hypotheses rejected under M6; effect_twin <= 0 counts as < 0.75; a replayed twin is valid only if the
   unmodified arm's replay reproduces its vector per M8.

## M8. Validity conditions (failure makes the look VOID; the dates are spent)

- **PIT:** any arm input with an availability time after the snapshot's `captured_at_utc`.
- **Arm hash:** mismatch on any eligible row (M5.2).
- **Replay reproduction:** where an arm is replayed, it reproduces its stored shadow vector within 1e-12 L1 on 100% of
  rows (shadow stages) or the served vector within 1e-9 on at least 99% (served arms; evening-fix §6.2 form).
- **Coverage:** arm coverage below 90% of snapshots in a declared block.
- **Comparator change:** a served-release change on a declared block's path inside the window voids the dates after
  it unless a segment rule was declared before it landed.
- **Leakage:** any outcome, market price or score on a window date read before its look, by anyone, including
  descriptive reads the owner has refused (DL 2026-10-17).
- **Label source:** any label not from the settlement ledger.

# Part C. Prereg-only candidates (named; no instrument, no alpha, no date yet)

A candidate listed here may be scored on dates >= 2026-09-30 **only** through its own signed pre-registration built
from Part A; it is never run as a development read on new dates, and it gets an alpha-ledger row when drafted.

| Candidate | Definition | Why prereg-only | Constraints fixed now |
| --- | --- | --- | --- |
| **110g re-fit** | Re-fit the afternoon residual-centering stage's per-context residual shifts against **settlement** (ledger labels), on the post-2026-06-30 serving pipeline, and score the re-fitted stage on A0. | EF §2 (110g owner decision 2026-09-25): the stage is disabled "pending a separate measurement" and "must never trigger a refit on its own output"; EXHAUSTION_REGISTER L19 and §5 order 16: "whether a re-fitted centering helps the post-10-09 path is unmeasured". | Fit on development dates 2026-07-31..2026-09-29 only, against captured-input replays of the frozen A0 (not the served vectors of record, which carried the pre-10-06 lock-in defect); contexts and shifts frozen into an arm hash; the fit's own training score reported first (EF §5); the W-0004 activation receipt verified before any forward look (register order 16); forward scoring as an E1 arm with A0 as its input-removed twin. |

## 9. Signature

UNSIGNED. On signature the owner adds a DECISION_LOG row carrying this file's raw SHA-256 at the signed commit
(`git show <commit>:<path> | sha256sum`, LF bytes).

## 10. Owner decisions this draft needs

- **OD-T1** Sign or amend M1-M8.
- **OD-T2** The E1 UNTESTABLE bar (proposed MDE80 > 0.05 on R = 5% of market Brier; contrast 5% of the gap, about
  0.015 on R) and the crossed falsifier level (proposed 80%).
- **OD-T3** Futility β (0.20 default; 0.10 option) and the single boundary c = 0.2656 for all hypotheses.
- **OD-T4** E2 blend form (linear pool per block, default) or a log pool.

## Sources

- [Findings digest](../../operations/FINDINGS_DIGEST.md); [established findings](../../operations/ESTABLISHED_FINDINGS.md) §1, §1c, §1d, §5, §10c, §10d, §10j, §10q.
- [MG-1 pre-registration](../morning-guidance-read-mg1-preregistration-2026-10-04.md) §4-§9 (estimand, weights, signature form).
- [Evening-fix scoring pre-registration](../evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md) §5-§7 (one look, read token, replay validity).
- [t3-r3 13-16 pre-registration](../remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md) §2.2 (single primary), §8.
- [CAMPAIGN_LEDGER](../../operations/CAMPAIGN_LEDGER.md); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-09-30, 2026-10-13, 2026-10-15, 2026-10-16, 2026-10-17.
- `tools/research/model_parity/harness.py` (market columns, ratio floor, crossed weights).
