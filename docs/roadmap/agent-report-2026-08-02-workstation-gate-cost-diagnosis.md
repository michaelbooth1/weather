# Workstation gate-cost diagnosis report - 2026-08-02

## Declaration - frozen before result inspection

Declared at `2026-08-02T18:45:24.5822043Z`. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\gate-cost-diagnosis-2026-08-17a`,
outside the replay mirror. `data/` and the mirror remain read-only.

This mission is diagnosis only. It may re-analyze the already-spent dates
`2026-07-22` through `2026-07-26` and `2026-07-31`. It will not read,
enumerate, evaluate, or substitute `2026-08-01` through `2026-08-03` or
`2026-08-06` through `2026-08-19`. It will not fit, select, tune, create a
candidate or variant, alter the frozen 20% floor-informativeness gate, or
change any smoothing parameter.

The exact stacked base is
`8377873e44e3f3af41811130a79b7cb4cfcb5066`. The analysis will describe the
frozen unsmoothed gated continuation output already scored on July 31. The D1
repair remains unscored and will not be evaluated here. Hypotheses will be
ranked only as future work with explicit falsification evidence.

## Verdict

**The gate leaves the primary objective mostly untouched.** On July 31 it
excluded 1,425 / 2,156 snapshots (66.09%), but within capture hours 09 through
14 it excluded **488 / 577 snapshots and 5,368 / 6,347 band rows: 84.58% by
either denominator**.

**The excluded two-thirds carry most of the remaining loss: 66.26% of the
incumbent's all-row positive excess, 61.82% of its frozen-severe positive
excess, and 56.07% of its severe rows. The gated candidate is therefore a win
on the easier qualified part while leaving most of the problem this project
called primary unchanged.** After applying the candidate, the excluded rows
are 81.21% of the remaining all-row positive excess and 80.10% of all remaining
severe rows.

The severe tail did not relocate across the gate. All 938 excluded incumbent
severe rows remain severe and unchanged. The qualified population moves
735 -> 233 severe rows; its 642 retirements minus 140 new rows produce the
entire all-row reduction of 502, from 1,673 -> 1,171.

Hour 17 is the already-diagnosed D1 mechanism, not random hour noise: all 22
qualified D1 snapshots on July 31 regress, all have the native D1 valley, and
their `+0.015870` Brier contribution overwhelms the D0 gain. Hour 14 is a
different child of the same broad continuation-allocation problem. It has zero
qualified D1 snapshots; 82.31% of its loss comes from D0 rows where a warm
continuation removes probability from the realized winner, concentrated in
Los Angeles, NYC, and Denver. The later-window hour-14 failure is recurrent,
but its market mix and magnitude are date-sensitive.

This result describes the frozen unsmoothed gated candidate. It does not score
the D1 repair, select a replacement, change the gate, or make a go/no-go
decision for the separately queued `-08-16a` comparison.

## Evidence boundary and method

| Field | Value |
| :--- | :--- |
| Handoff source | `origin/master` handoff `workstation-handoff-2026-08-17a-what-did-the-gate-cost-us.md` |
| Exact stacked base | `8377873e44e3f3af41811130a79b7cb4cfcb5066` |
| Topic branch | `codex/workstation-gate-cost-diagnosis-2026-08-17a` |
| Declaration commit | `a555e531` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\gate-cost-diagnosis-2026-08-17a` |
| Declaration time | `2026-08-02T18:45:24.5822043Z` |
| Fresh descriptive date | July 31 only: 12 market-days, 2,156 snapshots, 23,716 band rows |
| Development sensitivity | Accepted OOF validation rows for July 24-26 only: 36 market-days, 6,523 snapshots, 71,753 band rows |
| Frozen gate | `floor_available and floor_removed_mass > 0.20` |

Every input was hash-verified before parsing. Both replay readers used exact
date allowlists and would fail on any other date. Maximum accepted-replay /
floor-trace probability mismatch was `0.0`. The analysis did not inventory the
mirror or `data/`; it reused only the accepted POST-boundary gate and D1 run
outputs. It did not read or enumerate August 1-3 or August 6-19.

Positive excess below is `max(model Brier - market Brier, 0)` on each band,
weighted by the frozen harness's daily-first market-day denominator. Fixed-
severe positive excess uses the incumbent's frozen >=30-point severe
membership. Severe counts are unweighted band-row counts.

## 1. Who the gate excludes

### Primary 09:00-14:00 objective

| Population | Snapshots | Share | Band rows | Share |
| :--- | ---: | ---: | ---: | ---: |
| Excluded | **488** | **84.58%** | **5,368** | **84.58%** |
| Qualified | 89 | 15.42% | 979 | 15.42% |
| Total | 577 | 100.00% | 6,347 | 100.00% |

Every snapshot has 11 mutually exclusive bands, so the snapshot and band-row
percentages are exactly equal. Hours 09 and 10 are effectively wholly outside
the candidate lane; only by hour 14 does even one-third of the hour qualify.

| Hour | Excluded / snapshots | Excluded | Hour | Excluded / snapshots | Excluded |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 00 | 40 / 89 | 44.94% | 12 | 71 / 94 | 75.53% |
| 01 | 57 / 86 | 66.28% | 13 | 76 / 95 | 80.00% |
| 02 | 60 / 76 | 78.95% | 14 | 62 / 96 | 64.58% |
| 03 | 79 / 79 | 100.00% | 15 | 32 / 91 | 35.16% |
| 04 | 74 / 74 | 100.00% | 16 | 42 / 90 | 46.67% |
| 05 | 92 / 92 | 100.00% | 17 | 28 / 91 | 30.77% |
| 06 | 84 / 84 | 100.00% | 18 | 40 / 91 | 43.96% |
| 07 | 95 / 95 | 100.00% | 19 | 45 / 98 | 45.92% |
| 08 | 91 / 91 | 100.00% | 20 | 27 / 84 | 32.14% |
| 09 | 100 / 100 | 100.00% | 21 | 21 / 91 | 23.08% |
| 10 | 99 / 101 | 98.02% | 22 | 15 / 88 | 17.05% |
| 11 | 80 / 91 | 87.91% | 23 | 15 / 89 | 16.85% |

The market split is also broad rather than one bad market. Toronto is wholly
excluded because its floor never crosses the frozen threshold on July 31;
Los Angeles is the least excluded market at 37.29%.

| Market | Excluded / snapshots | Excluded | Market | Excluded / snapshots | Excluded |
| :--- | ---: | ---: | :--- | ---: | ---: |
| Atlanta | 153 / 183 | 83.61% | Los Angeles | 66 / 177 | 37.29% |
| Austin | 122 / 185 | 65.95% | Miami | 87 / 181 | 48.07% |
| Chicago | 152 / 178 | 85.39% | NYC | 118 / 177 | 66.67% |
| Dallas | 94 / 176 | 53.41% | San Francisco | 112 / 174 | 64.37% |
| Denver | 124 / 184 | 67.39% | Seattle | 90 / 175 | 51.43% |
| Houston | 118 / 177 | 66.67% | Toronto | 189 / 189 | 100.00% |

Forecast-relative position is the settlement winner's market-band index minus
the rounded forecast-high band index. The gate excludes most of every common
position, especially forecasts that land on the realized winner (`+0`) or one
band below it (`+1`).

| Winner relative to forecast | Excluded / snapshots | Excluded |
| :--- | ---: | ---: |
| `+0` | 574 / 766 | 74.93% |
| `+1` | 189 / 268 | 70.52% |
| `-1` | 473 / 749 | 63.15% |
| `-2` | 111 / 245 | 45.31% |
| `<=-3` | 66 / 95 | 69.47% |
| Unknown | 12 / 33 | 36.36% |

## 2. Where the remaining loss lives

| Incumbent loss measure | Excluded | Qualified | Total | Excluded share |
| :--- | ---: | ---: | ---: | ---: |
| All-row positive excess Brier | **0.304688** | 0.155137 | 0.459825 | **66.26%** |
| Fixed-severe positive excess | **0.207303** | 0.128027 | 0.335330 | **61.82%** |
| Severe band rows | **938** | 735 | 1,673 | **56.07%** |

The candidate reduces all-row positive excess only inside the qualified lane,
from 0.155137 to 0.070482. Excluded positive excess remains exactly 0.304688.
The resulting candidate total is 0.375169, of which **81.21%** is excluded.
The gate therefore improves the smaller loss pool and declines to touch the
larger one.

## 3. Did the severe tail move or relocate?

| Population | Incumbent severe | Candidate severe | New | Retired | Net |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Excluded | **938** | **938** | 0 | 0 | **0** |
| Qualified | 735 | 233 | 140 | 642 | **-502** |
| All rows | 1,673 | 1,171 | 140 | 642 | **-502** |

The all-row severe count falls by exactly the qualified-lane reduction, so the
gain is real and does not merely relocate severe membership across the gate.
But the excluded severe population retains its own unchanged and becomes
**938 / 1,171 = 80.10%** of the candidate's remaining severe rows. This is why
the qualified 30.71% severe-tail excess reduction and the unresolved primary
objective can both be true.

## 4. Why hours 14 and 17 fail

### Hour 17: the D1 mechanism recurs

| July 31 hour-17 component | Snapshots | Delta contribution | Severe incumbent -> candidate |
| :--- | ---: | ---: | ---: |
| Excluded | 28 | 0.000000 | 6 -> 6 |
| Qualified D0 | 33 | **-0.009802** | 30 -> 3 |
| Qualified D1 | 22 | **+0.015870** | 6 -> 31 |
| Qualified D2plus | 8 | +0.002558 | 6 -> 9 |
| All hour 17 | 91 | **+0.008626** | **42 -> 43** |

Every qualified D1 snapshot regresses. Their mean native distribution is
`P(D0)=0.6801`, `P(D1)=0.0571`, and `P(D>=2)=0.2628`; all 22 have
`P(D1) < P(D>=2)`. Dallas, Denver, and Austin own all 22. Their average winner-
probability reductions are respectively 41.04, 35.33, and 21.82 percentage
points. This is the exact D1 valley / floor-over-anchor mechanism previously
diagnosed, and its `+0.015870` loss is 1.84 times the net hour loss because the
large D0 gain partly hides it.

The mechanism also appears in the already-spent OOF validation rows. At hour
17, all 8 qualified development D1 snapshots regress; 6 / 8 have the native
D1 valley and their mean snapshot delta is `+0.101669`. Pooled July 24-26 hour
17 is a slight loss (`+0.000938`) with date deltas `+0.009533`, `+0.002892`,
and `-0.009610`. The frozen July 27-30 aggregate passed at `-0.005742`, while
July 31 fails at `+0.008626`. That sign variation is composition: D0 wins can
mask recurrent D1/D2plus losses. It is not evidence that the D1 failure first
appeared on July 31.

### Hour 14: cold-miss over-continuation, not D1

Hour 14 has 62 excluded snapshots and 34 qualified snapshots. The excluded
rows are exact ties; the qualified rows alone contribute the full `+0.007065`
delta and move 27 -> 44 severe rows (32 new, 15 retired). There are **zero
qualified D1 snapshots**.

| Qualified hour-14 group | Snapshots | Mean snapshot delta | Hour-delta contribution | Mean winner-probability change | Candidate native `D0 / D1 / D2+` |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Los Angeles, D0, forecast `<=-3` | 8 | +0.037372 | **+0.003114** | -0.1374 | 0.126 / 0.350 / 0.523 |
| NYC, D0, forecast `-1` | 8 | +0.032665 | **+0.002722** | -0.2521 | 0.136 / 0.203 / 0.661 |
| Denver, D2plus, forecast `+1` | 2 | +0.077070 | +0.001427 | -0.4412 | 0.009 / 0.093 / 0.898 |
| Dallas, D2plus, forecast `-1` | 8 | -0.002130 | -0.000178 | +0.0104 | 0.011 / 0.085 / 0.903 |
| Miami, D0, forecast `+0` | 8 | -0.000251 | -0.000021 | +0.0394 | 0.940 / 0.060 / 0.000 |

Actual D0 rows contribute `+0.005815`, or **82.31%** of the net hour loss.
Across the whole hour, the candidate reduces the realized winner probability
by 3.65 points on average; winner-band loss is `+0.004667`, **66.05%** of the
net delta, with diffuse losing-band mass adding the rest. Los Angeles, NYC,
and Denver contribute 102.81% of the net loss before Dallas and Miami offsets.

The precise mechanism is therefore **over-continuation on a day whose realized
high stopped colder than the forecast path**. For D0 rows the strong floor is
already the winner, but the continuation distribution places only 12.6-13.6%
on D0 in Los Angeles and NYC and pushes most mass into D1/D2plus. Denver puts
89.8% in the broad D2plus tail but spreads it away from the actual winning
band. This shares the parent error of misallocated continuation mass with D1,
but it is not the D1 ordinal valley: there are no qualified D1 outcomes and a
D1-only repair cannot by itself restore D0 mass.

The hour-wide effect is unstable on the three development validation dates
(`+0.000785`, `+0.000117`, `-0.005252`; pooled `-0.001450`), but it then failed
both the frozen July 27-30 aggregate (`+0.018144`) and July 31 (`+0.007065`).
The failure is therefore recurrent rather than a single July 31 accident;
the exact market concentration and magnitude remain one-day evidence.

## 5. What to try next, and what would falsify it

These are future hypotheses, not choices made from July 31. No item below was
fit, replayed, thresholded, or scored in this mission.

1. **Highest expected value - cutoff-valid forecast-residual distribution for
   excluded 09-14 rows.** Predict final-high residual and uncertainty relative
   to the contemporaneous forecast using market, hour, ensemble/source
   disagreement, current temperature/high trajectory, warming rate, forecast
   peak timing, cloud/solar/precipitation, and explicit source-availability
   fields already captured at cutoff. This directly targets the hour-14 cold
   miss and the larger excluded population without pretending the floor is
   informative. The [prior frontier](agent-report-2026-07-31-workstation-frontier.md)
   found 87.97% of 09-14 excess was a resolution/information deficit, and the
   [earlier skill-gap analysis](agent-report-2026-07-25-workstation-skill-gap.md)
   assigned 78.93% of positive excess to high forecast-disagreement cases. **Cheap:**
   audit captured-feature coverage and pre-register grouped OOF on the spent
   July 22-26 dates. **Needs confirmation:** any frozen candidate requires the
   untouched confirmation window and the full protected gates. **Falsified
   by:** no excluded-09-14 Brier improvement against both incumbent and market,
   unstable date/market signs, loss concentrated outside the target window,
   or new severe/catastrophic slices despite pooled gain.

2. **High-value comparator - market x hour centre baseline, then weather-
   conditioned residual centre.** The existing
   [time-conditioned centre probe](agent-report-2026-08-01-workstation-centre-predictability.md)
   recovered 49.06% of the accepted centre ceiling and cut fixed-tail excess
   36.78%, while a market-only constant failed. Use the market x hour surface
   as an auditable benchmark, not the final mechanism, and require weather
   features to explain deviations from it. **Cheap:** the benchmark and
   leakage/train-serve inventory use spent evidence only. **Needs
   confirmation:** the weather-conditioned lane, because the prior hour-only
   probe slightly regressed total Brier and created 1,065 new severe rows.
   **Falsified by:** failure to beat the hour-only comparator, total-Brier
   regression, or a result that is only a static market/hour lookup.

3. **Medium expected value - conditional scale after centre.** Once residual
   centre is credible, estimate spread from cutoff-valid forecast disagreement
   instead of applying global sharpening. Existing
   [width work](agent-report-2026-08-01-workstation-width-ceiling.md) found centre
   more coherent and width-alone's severe-tail ceiling small; hour 14 also
   shows winner under-allocation plus diffuse losing mass. **Cheap:** a
   centre-preserving width oracle and coverage audit on spent dates. **Needs
   confirmation:** any learned scale candidate. **Falsified by:** no incremental
   gain after centre, or lower entropy that raises log loss, new-severe rate,
   or calibration error.

4. **Lower/long-horizon expected value - acquire missing time-valid information,
   not a paid source.** Continue collecting complete ensemble runs, observation
   trajectory, cloud/solar/precipitation, and source-health evidence so an
   early-day residual model has a larger causal corpus. The
   [historical marine lead](agent-report-2026-08-01-workstation-band-mechanisms.md)
   is not a current-serving mechanism: current artifacts select zero marine
   features and source removal changed no prediction. **Cheap:** feature
   selection/ablation and missingness inventory. **Expensive:** waiting for
   enough new settled market-days and proving train/serve parity. **Falsified
   by:** no incremental information beyond market and hour in blocked-date
   evaluation. Paid-provider access remains out of scope.

Lowering the floor gate is not on the list. The measured 1% and 5% lanes failed
the catastrophic bar, and this diagnosis says the excluded objective needs a
different early-day information mechanism rather than a different cut point.

## Evidence and guardrails

The final evidence manifest is
`C:\Users\Michael\Documents\github\weather\scratch\runs\gate-cost-diagnosis-2026-08-17a\final-evidence-manifest.json`,
SHA-256 `6fa9ecb3e1cdc45e60466e7c02bbedac262d987d8b2b97c8ba8c4f7e6ba956f6`.
Key outputs are:

| Output | SHA-256 |
| :--- | :--- |
| `gate-cost-diagnosis.json` | `48cbfc5f414a97dba7597d038fbdfd83f3b82b70a0451d93300880c6b1ed262c` |
| `remaining-loss.json` | `51852bc0167eca6fa9291512c4a08f38bc16f638f35ea94ef6d6fbfef0168058` |
| `excluded-by-capture-hour.csv` | `751004435b087b30000bc73efddf3abf225846ad46eea3caecdd0d696375dee7` |
| `excluded-by-market.csv` | `9c04452df22ad49a39cd12b609e4ef9a2cebbcc14767a14cac1ef87217d39e6a` |
| `excluded-by-forecast-relative-position.csv` | `40acc4e0fe3455957ead83378b1348c1a9ed7dc34fb2ed131da1a44eb20d03c5` |
| `hour-14-17-snapshot-casebook.csv` | `8b738f90fa94f7677655aa9b5af8b71ff4971d05dea9164f53437358e56a97d6` |
| `hour-14-17-group-casebook.csv` | `122c449a56ae82cdd41b2bbc0ef575567f3473e8ed86b2e01c346baf53af913d` |

`data/` and the replay mirror remained read-only. No candidate, variant,
threshold, refit, smoothing change, promotion, pointer, serving, scheduler,
capture, production-host, sync-credential, mirror-topology, ACL, paid-provider,
PR, merge, or master push action occurred.
