# DRAFT, UNSIGNED: model-edge GO / NO-GO rule, 2026-10-19

> **Status: DRAFT-UNSIGNED, NOT ACTIVE.** Written on the workstation (model-edge week 1) for the owner's single
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

## 1. Master-agent synthesis (verbatim; binding text of the programme rule)

> **Source: master-agent model-edge synthesis 2026-10-19, relayed.** The full synthesis is on the capture host at
> `C:\tmp\agent-kit\model-edge-plan-20261019.md` and was not readable from the workstation; the block below is the
> excerpt master-agent relayed for verbatim inclusion. **PLACEHOLDER for any further synthesis text:** master-agent
> pastes any other section it wants bound here, verbatim, before the owner signs; nothing below was invented.

> "Instruments EDGE-1 (D0 2026-10-28), MG-1 (as signed) and NBM-2 are scored once each at their declared looks on promotion-countable dates, labels from the settlement ledger only. The primary estimand is fixed-market date-clustered, with crossed, per-market sign and input-removed falsifiers binding on any GO.
> GO (weather keeps maker priority): any arm, after Holm, has (a) an upper bound of R below 1.00 in a pre-declared block; or (b) a blend-minus-market upper bound below 0 with a gain of at least 5% of market Brier; or (c) a model-gated vs blind_re1 markout lower bound above 0 under both strictly_through and at_price fill rules, with net value clearing H = 1.00 per day per 100 deployed (DL:17).
> NO-GO (maker engineering moves to YouTube; weather capture and signed reads continue; a late GO reopens weather): for every one of A0, A1, A2, MG-1 and the NBM-2 arms, the lower bound of R is above 1.05 in every 00-16 block, the E2 upper bound is above -0.5% of market Brier, and E3 is either below 0.2 c/share upper bound or UNTESTABLE. The retrain is either scored or explicitly waived.
> Early NO-GO at Gate 1 (2026-12-07) if MG-1 is not GO, EDGE-1 has crossed futility in every arm, and no development survivor is queued.
> Otherwise INCONCLUSIVE: the owner decides on 2026-12-21. Both branches must be shown reachable before signing."

Reading notes (workstation, not part of the quoted text):
- "EDGE-1 (D0 2026-10-28)" is the OD-A6 "held" branch; if the owner rules OD-A6 "not held", D0 is 2026-10-25 (EDGE-1
  annex §2.1). The rest of the rule does not depend on the branch.
- "DL:17" is quoted as relayed. The hurdle it names is in DECISION_LOG 2026-09-22 (H = 1.00 net/day per 100 deployed)
  and 2026-10-15 (H also governs G1 and G4).
- "MG-1 is not GO" reads MG-1's own signed pass rule (MG-1 §4) plus the binding falsifiers of methods annex M7, which
  MG-1's own text largely shares (crossed disagreement, >= 8/11); the input-removed twin is not part of MG-1 as signed
  and is not added to it.

## 2. Per-instrument outcome labels (feed the programme rule)

### 2.1 E1 / E2 hypotheses (EDGE-1, later instruments under the methods annex)

| Label | Condition | Notes |
| --- | --- | --- |
| **GO-eligible** | Rejected by Holm at the final look (M6) **and** every falsifier holds (M7: crossed, >= 8/11 per-market sign, input-removed twin < 75% of the effect) **and** the GO thresholds of §1 (a) or (b) are met | E2 additionally needs the 5%-of-market-Brier gain. |
| **NO-GO (futility)** | Interim Z below the M4 boundary (c = 0.2656 for EDGE-1). Non-binding: the arm may keep accruing, but it counts as "crossed futility" for Gate 1. | Spends no alpha. |
| **NO-GO (final)** | Not rejected at the final look, or rejected but a falsifier fails. | No re-test on the same dates. |
| **UNTESTABLE** | The H3 power simulator, run before D0, gives MDE80 above the bar (M4.4). | Not a measured null; cannot satisfy a NO-GO clause that needs a bound; leaves the Holm family. |
| **VOID** | A validity condition fails (M8). | Dates spent; reported with the reason. |

### 2.2 The NO-GO clause needs bounds, not only failed passes

The §1 NO-GO requires, for every arm, **lower** bounds of R above 1.05 in every 00-16 sub-block (00-05, 06-09, 10-12,
13-16) and an E2 upper bound above −0.5% of market Brier. These are read at the final look from the reported
sub-block intervals (fixed-market, 95% two-sided percentile, no alpha). An arm that merely fails its GO test but whose
lower bound of R is at or below 1.05 in some 00-16 sub-block does **not** satisfy the NO-GO clause; the programme is
then INCONCLUSIVE unless another clause decides it.

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

- **H3 power (filled 2026-10-19 from H3 = harness v3, `claude/harness-v3-20261019` @ `74a85c7f6e48c929f1a16a9fdb97e8800c998fde`, `docs/research/harness-v3-2026-10-19.md` ("H3 on MG-1's own development variance components")):**

  | Forward dates x 11 markets | MDE80 | Simulated P(GO given effect) | P(GO given null) | Verdict vs bar 0.0133 |
  | --- | --- | --- | --- | --- |
  | 20 | 0.0097 | 0.32 | 0.026 | TESTABLE (both branches reachable) |
  | 45 | 0.0085 | 0.40 | 0.027 | TESTABLE |
  | 90 | 0.0079 | 0.43 | 0.040 | TESTABLE |

  MG-1 development variance (dates <= 2026-09-29), half effect −0.0050 Brier at 00-16, bar 0.0133; the market component holds power near 40% at any season length (EF §10j). **Calibration caveat:** H3 over-predicted power by 2-5 points in the high-power regime (its injected-skill control); a mid-power calibration control is being added by Wed 10-21. These are MG-1-variance proxies; per-arm H3 runs on the frozen A0/A1/A2 hashes are still required before D0 (M4.4).
- **GO reachable:** H3 marks the design TESTABLE with both branches reachable at 20 dates (P(GO given effect) 0.32,
  P(GO given null) 0.026). At the half effect it is underpowered (0.40 at 45 dates).
- **NO-GO reachable:** H3's TESTABLE verdict covers the GO/no-GO branches of the primary test; the §1 NO-GO clause's
  sub-block lower-bound test (every 00-16 sub-block above 1.05) was not simulated. Workstation note, not a measurement: with 11 market
  clusters and four sub-blocks per arm, a lower bound above 1.05 in **every** sub-block needs a true ratio well above
  1.05 everywhere; the development served-to-market ratios of 1.43-1.84 per 00-16 sub-block (EF §10q, from stratum, before the repairs) suggest it can be
  reachable for A0, but that is INFERENCE until H3 shows it.
- **"NO-GO likely within ~20 dates" remains INFERENCE.** H3 (above) gives power, not the futility-crossing probability
  at n = 20; that number is still `<SLOT: H3 futility probability at n = 20>`.
- **Interim cost:** `<SLOT: computed by H3/H7>`. No figure is stated before then.

## 5. Owner questions for Fri 10-23 (one line each; master-agent lifts these verbatim)

- **(a) OD-A6:** Do the snapshot market vectors fall under the 88a panel hold for pre-registered forecast scoring? Default (recommended): not held, so EDGE-1 D0 = 2026-10-25 (held would give D0 = 2026-10-28).
- **(b) A1 vs t3-r3 no-peek:** EDGE-1 arm A1 contains the signed t3-r3 stage, whose no-peeking rule forbids outcome reads on its holdout before its look; how should A1 be scored? Default (recommended): A1's looks are deferred until after the t3-r3 look.
- **(c) E3 / OD-G2:** Does maker replay v2's `informed-v0` minus `blind_re1` count as the "model-gated vs blind_re1" arm of GO clause (c)? Default (recommended): it does not count, so E3 is UNTESTABLE for weather in this programme.
- **(d) NBM-2 window:** NBM-2 reads NBM guidance and so falls in MG-1's reserved family; may it use dates in MG-1's window (2026-10-15..provisional 2026-11-28)? Default (recommended): no, NBM-2 needs its own window unless the owner rules otherwise.
- **(e) Thresholds:** Accept the crossed falsifier at a one-sided 80% bound, UNTESTABLE at MDE80 > 0.05 on R, and A2 blending A0 (not A1)? Default (recommended): accept all three as drafted.

## 6. Owner decisions

- **OD-G1:** sign §1 as relayed (with any further master-agent paste) and §2-§3.
- **OD-G2:** whether replay v2's `informed-v0` − `blind_re1` counts as the §1 (c) "model-gated" arm; default: no, E3
  is UNTESTABLE for weather in this programme.
- **OD-G3:** the retrain: scored (which lane, which look) or explicitly waived, before any NO-GO is final.
- **OD-A6** (EDGE-1 annex §2.1): D0 2026-10-25 (not held) or 2026-10-28 (held).

## Sources

- Master-agent model-edge synthesis 2026-10-19 (relayed excerpt, §1); host file not read.
- [Exhaustion register](../../operations/EXHAUSTION_REGISTER.md) §3 (L1), §5 (orders 1, 11); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-09-22, 2026-09-25, 2026-09-27, 2026-10-15, 2026-10-17.
- [Informed maker design](../../operations/informed-maker-design-2026-09-25.md) ("Quoting policy `informed_v0`"); `src/weather/market/maker_shadow.py`; maker replay v2 registration DRAFT (`codex/maker-replay-v2-build-20261003`) §1, §12.
- [MG-1](../morning-guidance-read-mg1-preregistration-2026-10-04.md) §2, §4, §6; [EDGE-1 annex](edge1-annex-DRAFT-2026-10-19.md); [methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md).
