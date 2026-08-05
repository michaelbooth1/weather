# Agent Report - 2026-07-22 Workstation Morning Forecast Frontier

## 2026-07-23 rendering assurance correction

The structured result and every metric below remain unchanged. A deterministic
rerender audit found that the prose named only San Francisco when five markets
reverse the sign of their tune-versus-evaluation reach gap: Dallas, Denver,
NYC, San Francisco, and Toronto.  The renderer now enumerates all five without
changing selection, inference, multiplicity, or disposition. San Francisco is
the clearest warning among the tune-selected markets because its gap changes
from `+0.1854` to `-0.3657`.

The final same-input assurance rerender is
`scratch/workstation-research-output/followup-assurance/morning-frontier-generation-003/`.
Its JSON is `1,045,971` bytes with SHA-256
`6e327611e038c8b36955beecc668352e456cd0f1a67e9b9b798e0a0dddfb51ba`;
its Markdown is `6,032` bytes with SHA-256
`09226e53f6bfefd691e00eb925c128ada8e10e96a099be07adfc41d3d03ae933`.
Generation 002 and generation 003 are byte-identical. Parsed as structured
JSON, generation 003 is exactly semantically equal to the original provenance
JSON (`1,070,748` bytes; SHA-256
`92eadcb401b993375dc67d3527ca42da96ca3dd8eb94c3540c44316f0359a236`).
The byte difference from the original is therefore serialization/rendering
provenance, not a result change.

## Outcome

**RETROSPECTIVE, SPLIT-RESPECTING DIAGNOSTIC: THE MORNING MODEL IS ADVERSE TO
THE MARKET, BUT THE ORIGINAL CITY CLAIM LEAKED THE EVALUATION SPLIT.** At 09:00
local on the 15-date evaluation split (2026-06-22 onward), the forecast-defined
warm event occurred `0.2541` more often than model probability implied
(fleet-date bootstrap 95% CI `[+0.1620,+0.3673]`). The model was worse than the
market by `+0.1553` Brier (`[+0.0823,+0.2473]`) and `+0.4434` log loss
(`[+0.2583,+0.6853]`). The point-forecast absolute-error delta was `+0.7743 C`.

Those fleet estimates remain valid as historical diagnostics. The former
seven-city claim does not. It copied each source tracker's full-corpus verdict,
which had already read the evaluation dates, even though the aggregate claimed
selection did not use holdout. Schema `workstation_morning_frontier_v0.2`
repairs that defect by recomputing the fixed 09:00, `0.15`-margin city rule on
the tune split only and reporting later dates separately.

The corrected tune-only rule selects **Austin, Los Angeles, Miami, and San
Francisco**. Their later-date group is adverse to the market, but the group was
defined retrospectively after those dates had already been opened. It is not
preregistered or untouched confirmation. Dallas, Denver, NYC, San Francisco,
and Toronto reverse reach direction between tune and evaluation; San Francisco
is the clearest selected-market warning. The nonselected cities are adverse
too. Only Miami clears the joint city-level multiplicity standard. No serving
change or city policy is supported.

## Evidence classification and provenance

The canonical forecast tracker was run separately for all 12 markets against
the hash-verified 309-market-day promotion corpus and configured WU settlement
summaries. Cutoffs are 07:00, 09:00, 11:00, and 13:00 local. The fixed date
split is:

- tune: through 2026-06-21 (17 fleet dates);
- separately reported evaluation: 2026-06-22 through 2026-07-10 (15 fleet
  dates).

The split prevents the corrected city labels from directly reading later-date
outcomes. It does not restore prospective confirmation because the evaluation
results were inspected before this correction and selection rule were
formalized. Every result in this report is research-only historical evidence.

For inference, markets are averaged within each fleet date and whole dates are
then resampled 20,000 times with seed `20260722`. Binary reach is scored against
the model and market probability assigned to reaching the forecast bucket.
Positive model-minus-market losses mean the model is worse.

The original structured provenance artifact is
`scratch/workstation-research-output/workstream_a/morning_tracker/aggregate_morning_frontier.json`,
schema `workstation_morning_frontier_v0.2`, SHA-256
`92eadcb401b993375dc67d3527ca42da96ca3dd8eb94c3540c44316f0359a236`
and size `1,070,748` bytes. The assured generation-003 rerender identified
above is semantically exactly equal to this original JSON.
It was written outside the read-only `data/` mirror through the shared
exclusive-temp atomic writer. At 09:00 the full artifact contains 308
observations: 271 use configured daily-summary settlement and 37 use the source
tool's documented snapshot-high fallback. One record at each cutoff lacked
both model and market reach probabilities and was excluded explicitly.

## Fleet evaluation across cutoffs

The Brier and log-loss point estimates and bootstrap intervals are adverse at
all four cutoffs. The natural multiplicity family is the four cutoffs crossed
with those two scores (eight tests). Holm-adjusted sign-test evidence supports
both score deltas at 07:00, 09:00, and 11:00. At 13:00 each raw sign-test
`p=0.035156` becomes `0.070312` after Holm adjustment, so 13:00 is adverse in
direction and interval but not multiplicity-controlled decisive evidence.

| Cutoff | Obs | Fleet dates | Outcome - model p (95% CI) | Model - market Brier (95% CI) | Brier Holm p | Model - market log loss (95% CI) | Log-loss Holm p | Point MAE delta C |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 07:00 | 166 | 15 | +0.2683 `[+0.1782,+0.3837]` | +0.1702 `[+0.0944,+0.2704]` | 0.006836 | +0.5028 `[+0.3112,+0.7649]` | 0.006836 | +0.8214 C |
| 09:00 | 166 | 15 | +0.2541 `[+0.1620,+0.3673]` | +0.1553 `[+0.0823,+0.2473]` | 0.022156 | +0.4434 `[+0.2583,+0.6853]` | 0.006836 | +0.7743 C |
| 11:00 | 166 | 15 | +0.2498 `[+0.1611,+0.3632]` | +0.1618 `[+0.0965,+0.2579]` | 0.006836 | +0.4516 `[+0.2755,+0.6988]` | 0.000488 | +0.7716 C |
| 13:00 | 166 | 15 | +0.1713 `[+0.1083,+0.2445]` | +0.0874 `[+0.0467,+0.1336]` | 0.070312 | +0.2185 `[+0.1144,+0.3320]` | 0.070312 | +0.4638 C |

The adverse estimates decay by 13:00, consistent with a morning
information-adoption problem, but the corrected inference does not call every
cutoff decisive.

The result is also insensitive to fallback settlements or uneven full-fleet
coverage. At 09:00, restricting the evaluation split to configured
daily-summary settlements gives 154 observations on 14 dates:
outcome-minus-model reach `+0.2571`, model-minus-market Brier `+0.1600`, and log
loss `+0.4541`. Requiring both daily-summary settlement and all 12 markets
leaves 144 observations on 12 dates: reach gap `+0.1922`, Brier delta `+0.1162`,
and log-loss delta `+0.3510`.

## Corrected retrospective city analysis

The fixed rule classifies a city as `SKEPTICISM IS COSTING` only when its
tune-only mean `outcome_minus_model_reach` at 09:00 is strictly greater than
`0.15`. The source reports' full-corpus verdicts remain in the artifact only as
audit provenance and never participate in selection or inference.

| Market | Tune reach gap | Tune class | Evaluation reach gap |
| --- | ---: | --- | ---: |
| Atlanta | +0.1062 | Model calibrated | +0.2966 |
| Austin | +0.1776 | Skepticism is costing | +0.2395 |
| Chicago | -0.0899 | Model calibrated | -0.0328 |
| Dallas | -0.0018 | Model calibrated | +0.4195 |
| Denver | -0.1083 | Model calibrated | +0.5917 |
| Houston | +0.0102 | Model calibrated | +0.3451 |
| Los Angeles | +0.1609 | Skepticism is costing | +0.1723 |
| Miami | +0.4074 | Skepticism is costing | +0.5886 |
| NYC | -0.2577 | Skepticism is justified | +0.1598 |
| San Francisco | +0.1854 | Skepticism is costing | -0.3657 |
| Seattle | +0.0294 | Model calibrated | +0.0102 |
| Toronto | -0.1190 | Model calibrated | +0.0486 |

Five markets reverse reach-gap direction between tune and evaluation: Dallas,
Denver, NYC, San Francisco, and Toronto. San Francisco is the clearest
tune-selected stability warning: its tune gap is `+0.1854`, but its later-date
gap is `-0.3657`. Atlanta and Houston do not reverse sign, but were not selected
on tune and became strongly positive later. A fixed city label is therefore
not stable on this panel.

### Separately reported group results

The four tune-selected cities contribute 56 observations on 14 evaluation
fleet dates. Averaging cities within date gives:

- reach gap `+0.158678`, 95% CI `[+0.043547,+0.273741]`;
- model-minus-market Brier `+0.123001`, 95% CI
  `[+0.062100,+0.186215]`;
- model-minus-market log loss `+0.356629`, 95% CI
  `[+0.228749,+0.499195]`.

The eight nonselected cities are also adverse: Brier `+0.155209` and log loss
`+0.440222` over 110 observations on 15 dates. Thus the selected-group result
does not isolate a useful four-city policy; it mostly reflects the broader
fleet problem.

### City-level multiplicity

All 12 cities crossed with Brier and log loss form one joint family of 24
two-sided sign tests. Holm support additionally requires an adverse mean and a
bootstrap interval above zero on both metrics. Only **Miami** clears both:

- Brier delta `+0.3053594`, Holm-adjusted `p=0.0439453125`;
- log-loss delta `+0.9218210`, Holm-adjusted `p=0.0439453125`.

No other city supports both score claims after adjustment. Miami remains a
candidate for a separately preregistered future panel, not a production rule
from this retrospective sample.

## Implementation and regression coverage

`weather.reporting.research.workstation_morning_frontier` now:

- computes the fixed 09:00 city classification from tune rows only;
- retains embedded full-corpus verdicts as explicitly unused provenance;
- evaluates selected and nonselected groups only after freezing tune labels;
- emits one eight-test fleet Holm family and one 24-test city Holm family;
- requires adverse direction, positive bootstrap interval, and adjusted
  significance before calling a score supported;
- publishes JSON and Markdown through exclusive-temp atomic writers outside
  the supplied read-only data root.

The regression fixture deliberately makes the tune classification conflict
with both the source full-corpus verdict and the later-date direction. It proves
selection follows tune records, later dates remain separately reported, and
the source verdict cannot influence the selected set. Deterministic tests also
pin the tied Holm results `0.0703125` for the two 13:00 score tests and
`0.0439453125` for Miami's two tests in a 24-test family.

## Relationship to stage attribution

The historical `forecast_pull` stage moves mass toward the morning forecast
and improves Brier, but worsens log loss. This work does not justify a generic
confidence increase or a stable four-city transform. The useful next question
is narrower: preregister a genuinely future panel and test a guarded
forecast-adoption candidate with both Brier and log-loss constraints.

## Disposition

No serving parameter changed. The fleet-wide morning weakness is material
diagnostic evidence; the 13:00 multiplicity result is directional, the
four-city rule is retrospective, five markets reverse reach-gap direction,
San Francisco is the clearest selected warning, and only Miami has
city-specific Holm support. A future candidate must be specified before new
dates arrive and clear both proper scores on that untouched panel.
