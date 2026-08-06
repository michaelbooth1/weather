# Workstation endpoint re-power report — 2026-08-03

## Decision before `-08-16a`

**No: frozen severe-tail SSE is not honestly powered at `N=4`. Run `-08-16a` only with the
further pre-unblinding amendment below, as directional evidence collection—not as confirmation.**

The crossed date/market bootstrap raises the severe-tail fleet-date standard deviation from the
old analytical estimate `0.064670` to `0.082122`. Even if the old 25.53% direct-served diagnostic
effect were allowed to transfer, four-date power is only **72.94%**, the point-estimate requirement
is **N=5**, and the requirement at that proxy's nonzero crossed 95% lower improvement bound is
**N=15**.

That conditional calculation is still too generous. The 25.53% transform is not either frozen
`-08-16a` continuation candidate. Neither the base candidate nor the repaired candidate has an
endpoint-native severe-tail effect estimate inside the permitted evidence without scoring the held
candidates, which this mission forbids. Their honest required N is therefore **unknown**, not 5 or
15. The old `N=4` claim calibrated one instrument and assigned its power to another.

### Exact further amendment recommended for `-08-16a`

Add this block at the top of
`docs/roadmap/workstation-handoff-2026-08-16a-score-both-candidates.md`, after the existing amendment
and before any score is read:

> **AMENDED 2026-08-03 22:27 EDT, BEFORE ANY `-08-16a` SCORING — re-power correction**
>
> `-09-06a` invalidated the claim that frozen severe-tail SSE is powered at four dates. Under the
> predeclared crossed date/market bootstrap, the direct-served diagnostic proxy has 72.94% power at
> `N=4`, needs `N=5` at its point estimate, and `N=15` at its nonzero crossed 95% lower improvement
> bound. More importantly, that proxy is not an effect estimate for either frozen candidate, so
> their endpoint-native required N is not identified before this score.
>
> **Four changes, nothing else:**
>
> 1. Demote frozen severe-tail SSE from confirmatory primary to a **directional primary readout**.
>    Keep it as the headline tail estimate, but do not call either sign a confirmation.
> 2. Keep 09:00–14:00 fleet Brier directional. There is now **no confirmatory efficacy endpoint at
>    N=4** and no endpoint may be substituted after results are visible.
> 3. Run the two frozen artifacts on the four already-declared dates with the unchanged harness,
>    seed, repetitions, corrected max-T harm gate, deterministic safety gates, per-date reporting,
>    and choice-rule ordering. The output may identify a **directional leader for further study**,
>    but it cannot earn confirmation, promotion, or reserved-window entry by efficacy claim.
> 4. Both artifacts remain held after this run. Any later confirmation design must be dated and
>    pre-registered from candidate-native evidence or an explicit MDE target before any reserved
>    date is read.
>
> Frozen artifacts, application gate, date set, structural predictions, tie-break correction, and
> every deterministic safety contract are unchanged. The reserved window remains untouched.

This preserves the value of the already-declared matched score set without pretending that four
dates answer an efficacy question they cannot answer.

## Corrected MDE and N table

The analysis reuses the exact `-09-05a` crossed pigeonhole bootstrap: 2,000 replicates, seed 90501,
with target dates and markets independently resampled. Power is one-sided alpha 0.05 at 80%, using
a noncentral t and degrees of freedom capped by the 12-market dimension. MDE percentages are relative
to each endpoint's own baseline SSE or incumbent-market Brier gap. The reservation column uses the
unchanged 90 dates.

| Endpoint | Honest effect input | Crossed/date SD | MDE at N=4 | MDE at N=90 | N at measured point | N at crossed 95% lower improvement bound |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| **Frozen severe-tail SSE** | 25.53% direct-served diagnostic proxy; **not a frozen-candidate effect** | 0.082122 | 0.135479 (28.31%) | 0.022982 (4.80%) | **5 for proxy; candidate N unknown** | **15 for proxy; candidate N unknown** |
| Pooled all-hour Brier | No endpoint-native effect; weak 3-date variance proxy only | 0.003151 | 0.005198 (24.33%) | 0.000882 (4.13%) | Unknown | No finite N at zero |
| 09:00–14:00 Brier | Actual propagated diagnostic: 0.003913, 18.32% gap closure | 0.009119 | 0.015044 (70.43%) | 0.002552 (11.95%) | **39**, conditional on point transfer | No finite N; interval crosses zero |
| Toronto 09:00–14:00 | Actual propagated point **worsens** Brier by 0.002565 | 0.003066 | 0.005059 (45.09%) | 0.000858 (7.65%) | No positive effect to power | No finite N |

The honest columns are now endpoint-native MDEs, conditional point-sensitivity N, and conservative
N at the crossed lower improvement bound. They replace the misleading shared “5.39% / 2.5%” labels.
One factual correction to the handoff is important: the old severe-tail row was already indexed on
25.53% and 12.76%, not 5.39% and 2.5%. The old power implementation also used analytical two-way
date/market clustered variance; it was the published `-08-23a`/`-08-24a` intervals that resampled
market-days as exchangeable units. The conclusion still changes because the corrected small-sample
crossed bootstrap makes the severe proxy itself underpowered at four dates.

## Does 09:00–14:00 move from 504?

**Materially, yes: 504 becomes 39 at the propagated 18.32% point effect.** This is not the naive
effect-only rescaling: the crossed bootstrap supplies `SE_5=0.0040783` and a fleet-date-equivalent
SD of `0.0091193`; the resulting one-sided noncentral-t calculation gives N=39. Four-date power is
16.71%. Ninety-date power would be 98.46% if that exact point transferred.

It does not make the stated primary objective unconditionally measurable. The point's crossed
interval is `[-0.013567, +0.003133]`, or `[-21.03%, +55.81%]` gap closure, so the defensible 95%
lower improvement bound is zero and has no finite required N. It is also a propagated diagnostic
correction, not either frozen `-08-16a` candidate. N=39 is useful sensitivity arithmetic, not a
license to declare the 90-day reservation powered.

## Significance-claim sweep

The sweep covered the load-bearing reports and held topic-branch reports that use market-day
bootstrap intervals. It did not rerun every subgroup. Claims whose original interval already
crossed zero remain non-significant; claims based on deterministic gates or target-date-block
inference are outside this defect.

| Published claim | Original inference | Crossed status | Disposition |
| --- | --- | --- | --- |
| `-08-23a` / `-08-24a`: raw HGB is systematically cool, about -1.2131 C-equivalent | Exchangeable 60 market-day bootstrap; `[-1.7928,-0.7035]` / `[-1.7647,-0.7426]` | Recomputed crossed interval **`[-2.2861,-0.3331]`** | **Survives.** The pooled cool-bias mechanism remains supported. |
| `-08-22a`: restoring the ten blinded fields improves frozen severe-tail SSE by 12.77% overall and 15.23% in the excluded lane | Exchangeable market-day ratio intervals `[8.60%,17.53%]` and `[9.43%,21.54%]` | Recomputed crossed intervals **`[6.14%,22.01%]`** and **`[5.15%,26.40%]`** | **Survives.** The severe-tail blindness cost remains; its pooled Brier claims already crossed zero. |
| `-08-24a`: raw conditional OOF Brier improvement, 24.69%, interval excluding zero | Exchangeable market-day interval `[-0.015137,-0.000868]` | `-09-05a` crossed interval **`[-0.022248,+0.001618]`** | **Does not survive.** Already superseded by the merged `-09-05a` report. |
| `-08-24a`: direct-served conditional severe-tail SSE improves 25.53% | Exchangeable interval `[-0.168034,-0.070902]` | Recomputed crossed interval **`[-0.198765,-0.056568]`** | **Sign survives; N=4 does not.** It is also not a frozen-candidate effect. |
| `-08-24a`: direct-served constant severe-tail interval excludes zero | Exchangeable interval `[-0.065825,-0.002402]` | Not rerun | **Doubtful, non-load-bearing.** Do not cite as significant until crossed. |
| `-08-23a`/`-08-24a`: every hour and selected markets/regimes have intervals excluding zero; especially 4–6-market-day above-support regimes | Exchangeable market-day subgroup bootstrap | Not rerun | **Doubtful/descriptive.** The pooled cool-bias claim survives, but subgroup significance does not inherit that result. Tiny support regimes are highest risk. |
| `-08-13a` and repeated by `-08-14a`: July 31 gated-candidate Brier non-regression PASS, upper `-0.002076` | Bootstrap across 12 market-days on one target date | A date dimension cannot be estimated from one date | **Within-date market evidence only.** It is not multi-date significance or confirmation; `-08-14a` correctly called replication not evaluable. |
| `-08-12a`: ungated candidate non-regression BLOCK, upper `+0.003147` | Exchangeable market-day bootstrap over four dates | Not rerun | **Conservative block remains usable.** Widening cannot turn failure to establish non-regression into proof of a win; do not interpret it as evidence of harm. |

The inventory's operational consequence is narrow: keep the pooled cool-bias and causal-blindness
severe-tail mechanism findings, retract the raw conditional significance claim, keep the conditional
severe sign only as a diagnostic, and stop carrying any one-date or subgroup interval as confirmation.

## Recommended reservation-file diff — not applied

The reservation remains **2026-08-06 through 2026-11-03 inclusive**. I did not edit
`docs/operations/reserved-confirmation-window.md`. The exact proposed replacement is preserved at
`C:\Users\Michael\Documents\github\weather\scratch\runs\repower-endpoints-2026-09-06a\reserved-confirmation-window.proposed.md`
(SHA-256 `dd5b5668a661b86a73f626f07dc4bb0f221eff4583c1f9a78deae8aba41fdfdf`).

Its recommended diff:

```diff
@@ The previous 14-date window and all following design text @@
-The previous 14-date window was chosen by calendar convenience. It was never a powered
-confirmation and must not be described as one retrospectively: its 09:00–14:00 minimum detectable
-effect was **32.30% of the served gap**, giving **10.96% power** at the optimistic effect.
+The previous 14-date window was chosen by calendar convenience. It was never a powered
+confirmation and must not be described as one retrospectively. The 90-date reservation remains
+untouched and must not be shortened; the corrected arithmetic below changes its interpretation,
+not its boundary.

 ## What changed, and why

-`-08-04a` derived the honest served-level effect range for the first retrain as **0 to 5.39% of the
-served incumbent-versus-market Brier gap**. The 24.69% raw-HGB closure does not survive the
-downstream floor, blend, cap and calibration stages.
-
-Fleet N required at 80% power, alpha 0.05 one-sided, two-way clustered by target date and market:
-
-| Endpoint | N at 5.39% | N at 2.5% midpoint |
-| --- | ---: | ---: |
-| **Frozen severe-tail SSE** | **4** | **9** |
-| Pooled all-hour Brier | 53 (weak 3-date variance proxy) | 246 |
-| 09:00–14:00 Brier | 504 | 2,337 |
-| Toronto-only, any endpoint | 3,350 | 15,550 |
-
-**90 dates covers the two endpoints that are actually powered, with buffer for the weak pooled
-variance estimate.** It does not cover the 09:00–14:00 slice, and nothing practical does.
+Replace this section with the `-09-06a` endpoint-native table in this report: severe-tail proxy
+N=5 / lower-bound N=15 / frozen-candidate N unknown; pooled N unknown; 09:00–14:00 conditional
+point N=39 and lower-bound N infinite; Toronto has no positive effect. State that the old severe
+row used 25.53%, not 5.39%, and that the 90 dates remain untouched but are not unconditionally
+powered.

 ## Endpoints for the first retrain's confirmation

-- **Primary: frozen severe-tail SSE, fleet, paired, clustered by date and market.** It is powered at
-  achievable N, and it is where the conditional correction improved *all five* held-out dates.
-- **Guardrail: pooled all-hour Brier non-regression, fleet.** The primary endpoint alone is
-  narrow — a candidate could improve the incumbent's worst rows while degrading elsewhere. This
-  catches that.
-- **Harm gate: one-sided two-way-cluster max-T, familywise error 5%.** Replaces the frozen
-  53–54-slice bar, which falsely rejects a uniformly better candidate 99.885%–99.9905% of the time.
-- **Reported but not confirmatory: the 09:00–14:00 slice.** Report it, label it directional, and do
-  not call it a confirmation.
+- **No efficacy endpoint is honestly confirmatory at N=4 for `-08-16a`.** Severe-tail SSE and
+  09:00–14:00 Brier are directional readouts only.
+- Retain pooled all-hour Brier as a safety/estimation guardrail, not a powered confirmation.
+- Retain the corrected max-T harm gate and every deterministic safety gate.
+- Keep 09:00–14:00 fleet Brier as the primary objective. A future confirmation must register a
+  candidate-native effect or explicit MDE target before reading reserved evidence.

 **Toronto-only evaluation is not viable at any endpoint.** Fleet or nothing.

 ## Standing consequence for the primary objective

-The 09:00–14:00 slice remains the thing we are trying to *fix*. It is no longer the thing we can
-*confirm* in a single shot. Those are different claims and conflating them is how this project
-previously called an underpowered Toronto result a win.
+The 09:00–14:00 slice remains the thing we are trying to fix. Its conditional point-sensitivity N
+moves materially from 504 to 39, but zero remains inside the crossed interval. Preserve all 90 held
+dates as an estimation and possible confirmation resource; do not call them powered until a
+pre-unblinded endpoint-native design input is recorded.
```

The proposed full-file text—not the abbreviated unified-diff body above—is the exact handover. It
requires the explicit dated operator decision demanded by the file and has deliberately not been
applied here.

## Evidence boundary and receipts

The only analysis population is POST-regime July 22–26, effective cutoffs 09–14: five dates, 12
markets, 60 market-days, and 2,868 snapshots. July 27–31, August 1–5, and the reserved August 6–
November 3 window were not read, enumerated, evaluated, or substituted. No fit, retrain, candidate,
held-candidate score, fresh replay, artifact mutation, release action, provider call, archive write,
or data write occurred. The required Git fetch happened before the handoff's no-network constraint
was known; analysis itself used only hash-bound local evidence.

| Item | Value |
| --- | --- |
| Exact base | `d6aa5ef7eaa3433f382f816987c4a71e50e4a21d` |
| Topic branch | `codex/workstation-repower-endpoints-2026-09-06a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\repower-endpoints-2026-09-06a` |
| Declaration time | `2026-08-04T02:14:42.3229945Z` |
| Analysis JSON SHA-256 | `38b57117ef4e3cbc98d03dcfdf84eaaeee971f2532051981812cf3ffb78197b9` |
| Analysis script SHA-256 | `170311988068ebd5c5e22ea819ea74485d452bd5e9123fdd3a90124dd6db9449` |
| Declaration SHA-256 | `7b2f071209a4413b1c36cd24ea2ac0aa083da6846bfef3de3a87298bc50bdb1e` |
| Verification SHA-256 | `86ee146e9145da26fb90a661bf3bee0d6fa578f365fd3c586342f4a112cfae99` |
| Evidence manifest SHA-256 | `05bcd31ccc5a6e38e6a2d29c5210ae92855839941dbc339f33716e6e464d7637` |

All eight declared source hashes reproduced before analysis. The 24-check independent verifier
passed. The analysis reproduced `-09-05a`'s
09:00–14:00 point and interval exactly, reconstructed all 1,565 frozen severe rows and 55
tail-bearing market-days, and retained the trusted observed-high floor unchanged.

Repository verification: `weather.operations.agent_docs_audit` passed with 18 agent files and 602
Markdown files. The tracked reservation source has an empty diff; only this historical report is
the intended repository change.
