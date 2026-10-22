# DRAFT, UNSIGNED: model-edge GO / NO-GO rule, 2026-10-19

> **Status: APPROVED 2026-10-21 by the owner (relayed by master-agent; GO/NO-GO rule §5 decision block).
> The signature binds with the DECISION_LOG signing row carrying this file's raw SHA-256 (not yet written); the
> DRAFT/UNSIGNED wording below is the text as approved.** Previously: DRAFT-UNSIGNED, NOT ACTIVE. Written on the workstation (model-edge week 1) for the owner's single
> sign-off on Fri 2026-10-23. It authorises nothing by itself: no serving, promotion, Scheduler, capture or live
> change. **The owner keeps every no-go decision personally** (EXHAUSTION_REGISTER).
>
> **Signed SHA-256:** `________________________________________________________________` (left blank; recorded in the
> DECISION_LOG signing row).

- **Owns:** how the model-edge instruments' results become one programme decision (GO, NO-GO, early NO-GO,
  INCONCLUSIVE), the per-instrument outcome labels (GO-eligible, NO-GO, UNTESTABLE), and what each outcome triggers.
- **Read when:** scheduling or reading a model-edge look; writing the result; proposing a no-go or a promotion from
  these instruments.
- **Do not use for:** the statistics (the [methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md)); the
  EDGE-1 arms and dates ([EDGE-1 annex](edge1-annex-DRAFT-2026-10-19.md)); alpha accounting
  ([alpha ledger](alpha-ledger-DRAFT-2026-10-19.md)). MG-1 keeps its own signed pass rule; this file only reads
  MG-1's outcome.

## 1. Master-agent synthesis (relayed, amended where marked; binding text of the programme rule)

> **Source: master-agent model-edge synthesis 2026-10-19, relayed.** The full synthesis is on the capture host at
> `C:\tmp\agent-kit\model-edge-plan-20261019.md` and was not readable from the workstation; the block below is the
> excerpt master-agent relayed for inclusion, amended only where marked (reading notes). Nothing below was invented.

> "Instruments EDGE-1 (D0 per EDGE-1 annex §2.1), MG-1 (as signed) and NBM-2 are scored once each at their declared looks on promotion-countable dates, labels from the settlement ledger only. The primary estimand is fixed-market date-clustered, with crossed, per-market sign and input-removed falsifiers binding on any GO.
> GO (weather keeps maker priority): any arm, after Holm, has (a) an upper bound of R below 1.00 in a pre-declared block; or (b) a blend-minus-market upper bound below 0 with a gain of at least 5% of market Brier; or (c) a model-gated vs blind_re1 markout lower bound above 0 under both strictly_through and at_price fill rules, with net value clearing H = 1.00 per day per 100 deployed (DL:17).
> NO-GO (maker engineering moves to YouTube; weather capture and signed reads continue; a late GO reopens weather): for every one of A0, A1, A2, MG-1 and the NBM-2 arms **whose declared look has been read by the decision date** [B1], the lower bound of R is above 1.05 in every 00-16 block, the E2 upper bound is above -0.5% of market Brier **or E2 is UNTESTABLE or not scored** [B1], and E3 is either below 0.2 c/share upper bound or UNTESTABLE. **An arm that is UNTESTABLE, dropped, deferred past the decision date or unsigned neither blocks nor satisfies NO-GO; at least one arm must have been read** [B1]. The retrain is either scored or explicitly waived.
> Early NO-GO at Gate 1 (2026-12-07) if MG-1 is not GO, EDGE-1 has crossed futility in **every EDGE-1 hypothesis whose interim has been read** [B1], and no development survivor is queued.
> Otherwise INCONCLUSIVE: the owner decides on 2026-12-21. Both branches must be shown reachable before signing."

Reading notes (workstation, not part of the quoted text):
- **Amended 2026-10-20 (independent review of bundle B, finding B1).** The quoted text is no longer verbatim at the
  points marked [B1]: as relayed, it required a bound for every one of A0, A1, A2, MG-1 and NBM-2, but under this
  bundle's own defaults A2 is closed in development, A1's look falls after 12-21 and NBM-2 has no dates before 2027,
  so NO-GO was unreachable and 12-21 could only give GO or INCONCLUSIVE. The relayed wording is in git at
  `2fa95f0fb99e90ab74c612800632f1abd5f53884`. Which arms count at each decision date: §2.4. Whether absent arms
  should block instead is owner question (i) (§5).
- "EDGE-1 (D0 per EDGE-1 annex §2.1)" replaces the relayed "(D0 2026-10-28)", which was the OD-A6 "held" branch
  only; D0 is 2026-10-25 or 2026-10-28 by the owner's OD-A6 ruling and the N12 clock (finding 9). The rest of the rule
  does not depend on the branch.
- **"No development survivor is queued"** means: no development survivor holds a `DRAFT` alpha-ledger row dated
  (`recorded_at`) before 2026-12-07 (finding 8).
- "after Holm" is read as "after the instrument's pre-specified multiplicity rule (M6)": EDGE-1's finals are staggered,
  so it uses a fixed sequence by default (annex §3; finding B2).
- "DL:17" is quoted as relayed. The hurdle it names is in DECISION_LOG 2026-09-22 (H = 1.00 net/day per 100 deployed)
  and 2026-10-15 (H also governs G1 and G4).
- "MG-1 is not GO" reads MG-1's own signed pass rule (MG-1 §4) plus the binding falsifiers of methods annex M7, which
  MG-1's own text largely shares (crossed disagreement, >= 8/11); the input-removed twin is not part of MG-1 as signed
  and is not added to it.

## 2. Per-instrument outcome labels (feed the programme rule)

### 2.1 E1 / E2 hypotheses (EDGE-1, later instruments under the methods annex)

| Label | Condition | Notes |
| --- | --- | --- |
| **GO-eligible** | Rejected under the instrument's multiplicity rule at its own final look (M6; EDGE-1: fixed sequence, annex §3) **and** every falsifier holds (M7: crossed, >= 8/11 per-market sign, input-removed twin < 75% of the effect) **and** the GO thresholds of §1 (a) or (b) are met | E2 additionally needs the 5%-of-market-Brier gain. |
| **NO-GO (futility)** | Interim Z below the M4 boundary (c = 0.2656 for EDGE-1). Non-binding: the arm may keep accruing, but it counts as "crossed futility" for Gate 1. | Spends no alpha. |
| **NO-GO (final)** | Not rejected at the final look, or rejected but a falsifier fails. | No re-test on the same dates. |
| **UNTESTABLE** | The H3 power simulator, run before D0, gives MDE80 above the bar (M4.4). | Not a measured null; **neither blocks nor satisfies NO-GO** (§1 as amended, §2.4); leaves the Holm family. |
| **CLOSED IN DEVELOPMENT** | The arm is degenerate on development dates (for EDGE-1 A2: every E2 blend weight w_b is 0.00, so A2 is the market and D ≡ 0). | A measured development null (exhaustion register), not UNTESTABLE; no forward instrument, no alpha; not scored, so it neither blocks nor satisfies NO-GO. |
| **VOID** | A validity condition fails (M8). | Dates spent; reported with the reason. |

### 2.2 The NO-GO clause needs bounds, not only failed passes

The §1 NO-GO requires, for every arm **whose declared look has been read by the decision date** (§2.4), **lower**
bounds of R above 1.05 in every 00-16 sub-block (00-05, 06-09, 10-12, 13-16) and an E2 upper bound above −0.5% of
market Brier, or E2 UNTESTABLE or not scored. These are read at the final look from the reported sub-block intervals
(fixed-market, 95% two-sided percentile, no alpha). An arm that merely fails its GO test but whose
lower bound of R is at or below 1.05 in some 00-16 sub-block does **not** satisfy the NO-GO clause; the programme is
then INCONCLUSIVE unless another clause decides it.

**MG-1 (finding 10).** MG-1 as signed reports a ratio to market for 00-16, not per sub-block (MG-1 prereg §4
reporting list, line 212). **Default: MG-1's NO-GO clause reads its 00-16 interval only** (lower bound of R above 1.05 at 00-16). Reading a
per-sub-block R for MG-1 instead would be a **new read of MG-1's reserved dates**, outside its signed reporting, and
would need its own owner decision before MG-1's look.

### 2.4 Which arms count at a decision date (B1)

An arm counts towards NO-GO at a decision date only if its declared look (the final; for early NO-GO, the interim)
has been read by that date. An arm that is UNTESTABLE, CLOSED IN DEVELOPMENT, dropped, deferred past the date, or
unsigned **neither blocks nor satisfies NO-GO**. At least one arm must have been read, otherwise the outcome is
INCONCLUSIVE. Under the bundle defaults:

| Arm | Look read by Gate 1 (12-07)? | Look read by 12-21? | Why |
| --- | --- | --- | --- |
| A0 | interim yes, if TESTABLE (not under the default bar) (earliest 11-15 / 11-18) | final yes, if TESTABLE (not under the default bar) (earliest 12-10 / 12-13) | EDGE-1 annex §2.1, §8 |
| A1 | no | no | looks deferred past the t3-r3 look (OD-E1 default (a)), which lands in Dec/Jan (question (b)) |
| A2 | — | — | CLOSED IN DEVELOPMENT (all four w_b = 0.00; annex §1.1); E2 not scored |
| MG-1 | its single look, if read by then | yes (45th countable date from D0 10-15, provisional last 11-28) | MG-1 §4-§6 as signed; its 00-16 interval only (§2.2 note) |
| NBM-2 | no | no | unsigned; no dates before 2027 under question (d)'s default |

So under the defaults the 12-21 NO-GO rests on A0 and MG-1, and early NO-GO on MG-1 not GO plus A0's interim. **But
under the default E1 bar H-A0 is UNTESTABLE** (MDE80 0.263 on R at 45 dates, EDGE-1 annex §8), so A0 drops out too and
both rest on MG-1 alone (§4; question (g)). If
the owner answers question (i) "absent arms block", NO-GO at 12-21 is unreachable under the defaults (only GO or
INCONCLUSIVE), and early NO-GO stays as written.

### 2.3 E3 (maker markout) — which document holds a model-gated arm

- **Forward dates: UNTESTABLE for weather.** The forward maker shadow on master quotes blind width:
  `src/weather/market/maker_shadow.py` `unavailable_fair_value` returns
  `Unavailable("weather_fair_value_provider_not_integrated", ...)` (lines 321-323 at `6aac6de81`; the docstring says the
  weather maker plugin is not on master). No model-gated arm exists on any EDGE-1 date.
- **Maker replay v2:** the registration (`docs/research/maker-replay-v2-registration-DRAFT.md` on
  `codex/maker-replay-v2-build-20261003`; DRAFT, UNSIGNED, signature target 10-22..23) holds **`informed-v0`** against
  `blind_re1` and `no_quote`, on panel UTC 2026-09-30..10-13, reading the live plugin's captured fair value
  (`outcome_view`). `informed-v0` uses fair value for width, asymmetry and band choice but never moves the centre in v0
  (informed-maker design, "Quoting policy"). Its estimand is **mean paired total modelled net per market/UTC-day**
  with `strictly_through` primary and the economic hurdle at k = 1; it is scored per fill bound. It is **not** a
  markout lower bound under both `strictly_through` and `at_price` as §1 (c) states.
- **Consequence:** §1 (c) can only be met through replay v2 if the owner rules that `informed-v0` minus `blind_re1`
  under replay v2's hurdles counts as "model-gated vs blind_re1" (OD-G2). Otherwise E3 is UNTESTABLE for weather in
  this programme, and the NO-GO clause's "E3 ... or UNTESTABLE" is met by that label.

## 3. What each outcome triggers

| Programme outcome | Triggers | Does not trigger |
| --- | --- | --- |
| **GO** | Weather keeps maker priority (§1). The GO arm enters the **existing serving promotion path**: release binding, captured-input replay parity, readiness and release gates, roll verdict and quiet-window landing ([AGENTS.md](../../../AGENTS.md) contracts; MG-1 §2 "a pass does not authorise promotion by itself"). An E2 GO is labelled complementary information: it authorises building the blend as a maker fair-value input in shadow, not serving a blended forecast. Results go to EF and the digest; the alpha ledger records the spend. | No serving change, no promotion and no live order without those gates and an explicit owner request. |
| **NO-GO** (all clauses) | **Maker engineering moves to YouTube** (the owner's stated alternative vertical: DL 2026-09-25 "weather first, YouTube view model next"; DL 2026-09-27). Weather capture and the signed reads (MG-1, evening-fix, t3-r3) continue; a late GO reopens weather. The [exhaustion register](../../operations/EXHAUSTION_REGISTER.md) rows L1 and the scored arms are updated with their bounds and this file's verdict, scoped **"no out-of-season edge"** (every forward date is out of season). The retrain is scored or explicitly waived by the owner before the NO-GO is final (§1). | No deletion of capture or evidence; no change to signed instruments; no claim about in-season edge. |
| **Early NO-GO at Gate 1 (2026-12-07)** | As NO-GO, decided early when all three Gate-1 conditions of §1 hold. | Gate 1 sees EDGE-1's interim only (its final is after 12-07 in both OD-A6 branches); an early NO-GO does not stop EDGE-1 from reaching its final, which is reported when it arrives. |
| **INCONCLUSIVE** | The owner decides on 2026-12-21 with every bound in hand. | No automatic route either way. |
| **UNTESTABLE** (an arm) | Recorded in the exhaustion register as UNTESTABLE, not NULL (register §5 order 11 wording). | Never counted as evidence of no edge. |

## 4. Reachability (before signature)

§1 requires both branches shown reachable before signing. Status:

- **Source (updated 2026-10-20):** harness v3 (H3/H7), `claude/harness-v3-20261019` @ `2f3f3e8e6b542a419204afe802dae4545abc10d7`, `docs/research/harness-v3-2026-10-19.md` and its "Addendum 2026-10-20: master-agent rulings"; `HARNESS_V3_SHA256` at that tip `987e171775c596f6e50ac72b9bd54880399e4fafcc11865cdec0a2375970b4cf` (recomputed on the workstation with `v3_score.harness_v3_sha256()`; the addendum's runs used `35024814…`). Development reads only (dev dates 08-01..09-29).
- **GO power:**

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

- **Reachability of each branch (revised 2026-10-20, delta review item 4).** GO (default bar): only via MG-1's upper
  bound of R below 1, ≈ 0.025 under R = 1 and ≈ 0 at the development R; with H-A0 kept (bar ≥ 0.27), 0.17 at R = 0.95.
  GO is not meaningfully reachable under the defaults; the owner signs this as a NO-GO/INCONCLUSIVE instrument or
  raises the bar. (The 0.47-0.95 figures previously quoted here are MG-1's paired arm − served scale, not GO clause (a).)
  NO-GO:

  **Per-arm NO-GO reachability, one arm in isolation** (harness-v3 addendum; the relayed §1 rule applied per arm: lower bound of R above 1.05 in every 00-16
  block and E2 upper bound above −0.5% of market Brier; MG-1-like arm variance; 20,000 simulations per cell):

  | Scenario | P(NO-GO) at 20 dates | 45 dates | 90 dates |
  | --- | --- | --- | --- |
  | dev-observed R (1.171 / 1.205 / 1.250 / 1.945 by block) | 0.821 | 0.988 | 1.000 |
  | half effect, R = 1 + (R_dev − 1)/2 | 0.087 | 0.207 | 0.358 |
  | null, R = 1 | 0 | 0 | 0 |

  Sensitivity with served-vs-market variance components: 0.28-0.43 at the dev-observed R (20-90 dates). Every
  development-fit blend weight is **0.00**, so A2 is CLOSED IN DEVELOPMENT and E2 is not scored; under the amended §1
  that neither blocks nor satisfies NO-GO, and the per-arm NO-GO rests on the R clause alone. **If a draft freezes a
  non-zero blend weight, this simulation must be re-run.**

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
    A0-counted variant, which needs A0's interim and so does not apply under the default bar.) Question (l).
  - **GO side (INFERENCE, not simulated here):** with H-A0 UNTESTABLE and A1 deferred, the only E1 GO route at 12-21
    is an MG-1 upper bound of R below 1, about 0.025 under R = 1 and near 0 at the development R of 1.30; GO is
    reachable in name only under the defaults. With H-A0 in the family, its power at R = 0.95 is 0.17 (annex §8).

- **"NO-GO likely within ~20 dates" remains INFERENCE.** The supporting computation is P(NO-GO at 20 dates) = 0.821
  under the dev-observed R (MG-1-like variance); it falls to 0.087 at the half effect and 0.28 with served-vs-market
  variance, and forward dates are out of season, so it is not a forecast of the outcome.
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

## 5. Owner questions for Fri 10-23 (one line each; master-agent lifts these verbatim)

> **Owner decision 2026-10-21 (all of §5 and §6; relayed by master-agent).** The owner answered in chat with
> master-agent at 12:14 on 2026-10-21, verbatim: "Accept all, approve all, go all, I approve everything as
> recommended looks good to m". This decides every question (a)-(r) below with its recommended default, and every
> OD in this file, the EDGE-1 annex §12, the methods annex §10 and the alpha ledger §4 with its default, including:
> OD-G1 sign §1-§3 as amended at the [B1] marks; OD-A6 not held (D0 10-25 if N12 lands in time); OD-G2 no; OD-G3
> retrain waived for the 12-21 decision, best case a futility-only R0 from 11-17; (j) the Open-Meteo fetch yes; (k)
> the narrow retrain reservation with the exact (k) text. Each item below is marked and refers back here. D0 and the
> A0/A1 hash and logistics rows are not fixed by this decision; the signing rows go in DECISION_LOG.

- **(a) OD-A6:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): not held; D0 2026-10-25 if post-N12 code serves before the first T+0 snapshot of local 10-24, else 2026-10-28.]** Do the snapshot market vectors fall under the 88a panel hold for pre-registered forecast scoring? Default (recommended): not held, so EDGE-1 D0 = 2026-10-25 provided post-N12 code serving before the first T+0 snapshot of local 2026-10-24 in the earliest US timezone (held, or N12 later, gives D0 = 2026-10-28). **[PROPOSED AMENDMENT 2026-10-21 (pending owner): the clock moves to the 10-23/24 head; question (s) (A).]**
- **(b) A1 vs t3-r3 no-peek:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): A1's looks deferred until after the t3-r3 look (OD-E1 (a)).]** EDGE-1 arm A1 contains the signed t3-r3 stage, whose no-peeking rule forbids outcome reads on its holdout before its look; how should A1 be scored? Default (recommended): A1's looks are deferred until after the t3-r3 look. Under this default H-A1's final falls after 12-21 (the t3-r3 look lands in Dec/Jan), so **A1 adds nothing to the primary 12-21 decision** and nothing to Gate 1.
- **(c) E3 / OD-G2:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): it does not count; E3 is UNTESTABLE for weather in this programme.]** Does maker replay v2's `informed-v0` minus `blind_re1` count as the "model-gated vs blind_re1" arm of GO clause (c)? Default (recommended): it does not count, so E3 is UNTESTABLE for weather in this programme.
- **(d) NBM-2 window:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): no; NBM-2 needs its own window.]** NBM-2 reads NBM guidance and so falls in MG-1's reserved family; may it use dates in MG-1's window (2026-10-15..provisional 2026-11-28)? Default (recommended): no, NBM-2 needs its own window unless the owner rules otherwise. Under this default NBM-2 has no dates before 2027, so **NBM-2 is absent from the 12-21 decision and from Gate 1**.
- **(e) A2:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): E2 closed in development; no A2 instrument.]** Record E2 as closed in development (w_b = 0.00 in each sub-block on 07-31..09-29; no forward E2 instrument; H-A2 not in the family) unless the owner redefines A2? Default (recommended): closed. In plain terms: the blend weight fitted on development dates was 0.00 in every block, so the blend is the market price itself; this is a measured development null, not an untestable arm.
- **(f) A1 composition:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): keep A1 as a separate arm (A1-1 kept).]** A1 = A0 + t3-r3 + A1-1 (C-L13-BT, about 0.3% of the 00-16 gap, negligible), so A1 differs from A0 essentially by t3-r3; keep A1 as a separate arm, or drop A1-1 from it? Default (recommended): keep A1 as a separate arm, since t3-r3 is signed and A1 is its composite carrier, with its looks deferred per question (b).
- **(g) Thresholds:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): accept the 80% crossed falsifier and UNTESTABLE at MDE80 > 0.05 on R.]** Accept the crossed falsifier at a one-sided 80% bound and UNTESTABLE at MDE80 > 0.05 on R (5% of market Brier; the 5%-of-gap scale would be about 0.015 on R, stricter)? Default (recommended): accept both as drafted. **What the default does to H-A0:** its development MDE80 on R is 0.263 at 45 dates (served-vs-market variance, `resampled_power`; EDGE-1 annex §8), so H-A0 is UNTESTABLE before D0: no GO can come from A0, A0 neither blocks nor satisfies NO-GO, and the 12-21 NO-GO rests on MG-1 alone (§4). Alternatives: set the E1 bar at or above 0.27 on R (H-A0 stays in the family, but its power at R = 0.95 is 0.17), or read an UNTESTABLE A0's bounds for NO-GO only (a change to §1 and M4.4). H-A1 is measured, preliminary: UNTESTABLE at 20/45/90 dates, same as H-A0 (MDE80 0.263 on R at 45 dates; EDGE-1 annex §8), so under the default bar EDGE-1 has no testable hypothesis; the owner is choosing between the bar and the instrument.
- **(h) LA and SF live marine + SST refresh:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): yes, capture and features only.]** Build LA and SF live-marine registry entries (station choice per the Q-20 mechanism rule) and a scheduled SST water-contrast refresh, outcome-blind, as capture and features only; any model use goes through a later pre-registration? Default (recommended): yes. Station choice and candidates: EDGE-1 annex §13. Cost: a capture build plus one scheduled task, after the host Python C upgrade. Not an EDGE-1 arm.
- **(i) Absent arms at a decision date:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): no; an absent arm neither blocks nor satisfies NO-GO.]** Should an arm whose look has not been read by the decision date (A1, deferred past t3-r3; NBM-2, unsigned) block NO-GO, so that 12-21 can only give GO or INCONCLUSIVE under the defaults? Default (recommended): no; such an arm neither blocks nor satisfies NO-GO, which then rests on A0 and MG-1 (§2.4), or on MG-1 alone if H-A0 is UNTESTABLE (question (g)).
- **(j) RT-a, Open-Meteo Previous Runs fetch for the retrain:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): yes, fetch.]** Fetch the free Open-Meteo Previous Runs `temperature_2m_previous_day1..7` for 2021-2023, October-December target dates, US11, through the repository's own `weather.sources.forecast_training_corpus` (`plan --years 2021,2022,2023 --season-start 10-01 --season-end 12-31`, then `resume`, `materialize`; the season window is a CLI flag, `forecast_training_corpus.py:1576-1577`)? Default (recommended): **yes**, because it is the only route to a point-in-time forecast feature for the retrain candidate R0 (2021-2023 have no Oct-Dec PIT rows); **it is a download, so it needs the owner's own yes in chat**, not a relayed one. Runs on the workstation under `workstation_heavy.ps1`; the collector module has no HTTP client, so the request units are fetched by the separately authorized collector and staged, then published content-addressed to `data/training/pit_forecast_corpus/` (`DEFAULT_PUBLISH_ROOT`), never `data/forecast_history/`; R0's candidate `forecast_daily.csv` is built under a scratch data root. Expected size (**ESTIMATE**, the memo gives none): by construction 11 markets x 276 target dates x 14 cutoffs = about 42,500 daily rows and, at 24 valid hours each, about 1.0 million hourly rows, of the order of 10-40 MB daily and 0.3-1 GB hourly JSONL at 0.3-1 KB per row; a few hundred free-tier request units (INFERENCE from about 60 calls for the July window, EF §4b). Note: the sizing memo calls this "a production or master action"; running it on the workstation is the coordinator's placement, and either host needs the same owner yes.
- **(k) RT-b, narrow reservation for the retrain:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): yes, with the exact wording quoted in this item.]** Rule the retrain reservation narrow, MG-1-style, worded exactly: *"hold the dates only against retrain-family candidates; exempt EDGE-1, MG-1, the evening-fix scorer, t3-r3, maker scoring and every other use of those dates; the 20-date look is futility-only; the freeze is not timed to dodge dates."* Default (recommended): **yes**. Without it, freezing the first retrain candidate triggers the armed reservation as written (`reserved-confirmation-window.md` Trigger row, rules 3-4): it holds **every** date from 11-17 absolutely (not read, enumerated or evaluated) and **stops maker paper scoring** on them, colliding with EDGE-1 and MG-1 on the same dates.
- **(l) Gate 1 under the defaults:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): fold Gate 1 into 12-21 unless at least one EDGE-1 hypothesis is TESTABLE.]** Keep Gate 1 as an MG-1-only early NO-GO, or fold it into 12-21? Default (recommended): fold into 12-21 unless at least one EDGE-1 hypothesis is TESTABLE; H-A0 and H-A1 are both measured UNTESTABLE at 20/45/90 dates (H-A1 preliminary, EDGE-1 annex §8). (Under the defaults Gate 1 reduces to "MG-1 not GO", which fires ≈ 0.54 of the time even if MG-1 has a true half effect; §4.)
- **(m) OD-E2, EDGE-1 shape:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): sign as drafted.]** Sign EDGE-1 with arms A0/A1, N 20/45 and a fixed sequence (H-A0 then H-A1) over the members left at D0, or amend? Default (recommended): sign as drafted (EDGE-1 annex §3).
- **(n) OD-E3, declared block:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): 00-16 only.]** Test each arm at 00-16 only, or declare per-block hypotheses? Default (recommended): 00-16 only; sub-blocks are reported with intervals, no alpha (EDGE-1 annex §3).
- **(o) OD-E7, A0's binding twin:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): NWS hourly alone.]** Build T1 from the NWS hourly point forecast alone, or from Open-Meteo alone? Default (recommended): NWS hourly alone; T0 (climatology) stays non-binding either way (EDGE-1 annex §1.1).
- **(p) OD-T3, futility:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): β 0.20, c = 0.2656.]** Futility β 0.20 with one boundary c = 0.2656 for every hypothesis, or β 0.10 (c = −0.0472)? Default (recommended): β 0.20, c = 0.2656 (methods annex M4.2).
- **(q) OD-T4, E2 blend form:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): linear pool per block.]** Linear pool per block, or a log pool? Default (recommended): linear pool per block (methods annex M2; moot while E2 is closed in development).
- **(r) OD-T5, M2 replay reading:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): the replay runs, at the frozen hash on forward rows; development fits use the served vector of record.]** Does M2's "wherever the replay reproduces" mean "reproduces the served vector" (drops 75-96% of development rows: only 4-22% reproduce within 1e-9, code drift, M8) or "the replay runs"? Note A2's 0.00 fit was on the served vector of record, not M2's replay. Default (Recommended): "wherever the replay runs, at the frozen hash on forward rows; development fits use the served vector of record" (methods annex OD-T5).
- **(s) PROPOSED AMENDMENT 2026-10-21 (pending owner; not covered by the 10-21 decision block): A0 freeze and arm identity.** (A) Re-pin the A0 freeze from "the first master commit containing N12 `739c03eff`" to **the first master commit containing the 10-23/24 head `2960813738692a59f461aa3c59aeca5e3cf26feb`** (MG-1 bound + SD-1 + DST provider-label fix), because that owner-approved night changes A0's serving code after the N12 freeze; D0 = 2026-10-25 only if that head's code serves before the first T+0 snapshot of local 10-24 in the earliest US timezone, else 2026-10-28 or later (EDGE-1 annex §1.2). (B) Redefine the M5.2 code identity as the serving-path `STALE_CODE` fingerprint (plus `model_identity_hash`, artifact/config hashes, `ML_MODEL_VERSION`, stage versions and switches), with landings that change it forbidden until 12-21 and docs and out-of-closure, roll-free landings allowed (methods annex M5.2). Default (Recommended): adopt both. **Fallback if (B) is rejected:** the literal "code commit" rule stands, so all master landings are frozen from D0 to 12-21, docs included, or later rows are VOID: no DST follow-ups, no S2+S9 after the freeze, no docs heads, no Python follow-ups.

**Retrain prerequisite (not an owner question).** Master's trainer no longer reproduces each served model's columns (it builds 229 columns of schema v1.16 for Atlanta; the served bundle has 27 of v0.3), so R0 needs a **per-model column allowlist** in `weather.calibration.feature_model`: its own head, branch `claude/retrain-column-allowlist-<date>` (name TBD), **build by 10-27, land by 10-30**, alongside the about-10-30 owner deadline that gates an 11-17 start; roll verdict from `scripts\ops\roll_verdict.ps1`, never by hand. The served F-market models still select `pressure` and `pressure_trend_3h`, which the training policy `native_station_pressure_train_serve_v1` calls unservable (sizing memo r2.2). **Verdict (unchanged):** the retrain is **waiver-only for the programme decision** (OD-G3); the best case is a futility-only arm R0 from 11-17. Source: `docs/research/retrain-sizing-memo-2026-10-19.md` r2 on `claude/retrain-sizing-memo-20261019` @ `7428e5feff55ac360d4120d3656d15ccfda7f05d`.

## 6. Owner decisions

- **OD-G1:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): sign §1-§3 as amended at the [B1] marks.]** sign §1 as amended at the [B1] marks, and §2-§3.
- **OD-G2:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): no.]** whether replay v2's `informed-v0` − `blind_re1` counts as the §1 (c) "model-gated" arm; default: no, E3
  is UNTESTABLE for weather in this programme.
- **OD-G3:** **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): retrain waived for the 12-21 decision; best case a futility-only R0 from 11-17.]** the retrain: scored (which lane, which look) or explicitly waived, before any NO-GO is final.
- **OD-A6** (EDGE-1 annex §2.1): **[decided 2026-10-21 by owner (relayed by master-agent; GO/NO-GO rule §5 decision block): not held (D0 10-25 if N12 lands in time, else 10-28).]** D0 2026-10-25 (not held) or 2026-10-28 (held).

## Sources

- Master-agent model-edge synthesis 2026-10-19 (relayed excerpt, §1); host file not read.
- [Exhaustion register](../../operations/EXHAUSTION_REGISTER.md) §3 (L1), §5 (orders 1, 11); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-09-22, 2026-09-25, 2026-09-27, 2026-10-15, 2026-10-17.
- [Informed maker design](../../operations/informed-maker-design-2026-09-25.md) ("Quoting policy `informed_v0`"); `src/weather/market/maker_shadow.py`; maker replay v2 registration DRAFT (`codex/maker-replay-v2-build-20261003`) §1, §12.
- [MG-1](../morning-guidance-read-mg1-preregistration-2026-10-04.md) §2, §4, §6; [EDGE-1 annex](edge1-annex-DRAFT-2026-10-19.md); [methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md).
