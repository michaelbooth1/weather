# Workstation width and lever-ceiling diagnosis — 2026-08-01

## Verdict

Width excess is **broad, but not global**. The model is wider than the market
on 74.63% of the 19,265 distributions, yet 25.37% are narrower; only 53.49%
are wider by more than 0.5 effective bands. Ten markets are wider on average,
while Chicago and Miami are narrower. Width is strongest overnight and in the
morning, weakest around hours 14–16, and especially associated with outcomes
that finish cooler than the forecast-high band.

The 7,513 severe rows outside the retained five bands do **not** reproduce one
clean third geometry. Two-thirds are wide, but they split between cool- and
warm-centre failures; the remaining third are near market width or narrower.
Centre displacement is more coherent than width: 81.27% of these rows are at
least half a band off the market centre, and those rows carry 84.56% of the
outside-five severe contribution.

The outcome-aware oracle ceilings make the engineering order plain:

| Exact-match oracle lever | Total positive excess Brier reduction | Fixed ≥30-point-tail reduction |
| :--- | ---: | ---: |
| Width only | **15.98%** | **10.94%** |
| Centre only | **58.67%** | **74.97%** |
| Centre and width | **73.57%** | **87.36%** |

**Recommendation: engineer centre first.** Do not build a global sharpening
candidate first. Even with perfect market-width knowledge and hindsight about
when to apply it, width alone has only a small severe-tail ceiling. Adding
width after the centre oracle contributes at most another 14.90% of total
positive excess and 12.38% of severe-tail positive excess on this window.

Every oracle figure in this report uses the realized outcome and is
**non-achievable, deliberately optimistic, and permanently invalid as
candidate, gate, promotion, or release evidence**.

## Source, run root, and evidence boundary

| Field | Value |
| :--- | :--- |
| Source | exact `origin/master` `1e6be0218c0e53dceb8b18584cfb7a67c21ce541` |
| Topic branch | `codex/workstation-width-ceiling-2026-08-04a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\width-ceiling-2026-08-04a` |
| Window | 2026-07-22 through 2026-07-30, inclusive |
| Inputs reused | accepted exact corpus and current-serving replay from `disagreement-map-2026-08-03a` |
| Input scale | 108 complete market-days; 19,265 snapshots; 211,915 band rows |
| Corpus identity | `promotion_corpus_v0.1`, SHA-256 `fc878cbc5290d45e93b36f9efdf796196708d125788da9458d3c1c8c2ef5fb72` |

The accepted replay remains exact for this task. The only changes from its
`e7c2cece` analysis base through `1e6be021` are the accepted band-mechanism
report and this handoff; no serving code or artifact changed. All replay and
derived result rows are wholly after the 2026-07-31 `rows[-1]` boundary.

## Definitions

Each snapshot has 11 mutually exclusive settlement bands. Model probability
sums are 1.0 to floating-point precision. Market yes-prices sum to 1.0152 on
average because they are captured prices rather than a probability simplex;
they are normalized only for distribution moments. Original raw prices remain
the benchmark in every Brier calculation.

- Centre is expected ordered-band index.
- Width is effective band count, `exp(-sum(p * log(p)))`.
- Width excess is model effective band count minus normalized-market effective
  band count.
- Forecast-band offsets use the market's native-unit whole-degree settlement
  rounding. Negative means the realized winner is cooler than the
  forecast-high band.
- The descriptive geometry cut is fixed at 0.5 effective bands for width and
  0.5 ordered bands for centre. It labels evidence; it is not a candidate gate.

## 1. Global width distribution

One independent width observation is retained per snapshot.

| Measure | Width excess |
| :--- | ---: |
| Mean / median | +0.737 / +0.605 effective bands |
| P10 / P25 / P75 / P90 | −0.722 / −0.004 / +1.417 / +2.284 |
| Model wider | 14,377 / 19,265 (**74.63%**) |
| Wider by >0.5 | 10,305 / 19,265 (**53.49%**) |
| Wider by >1.0 | 6,966 / 19,265 (**36.16%**) |
| Model narrower | 4,888 / 19,265 (**25.37%**) |

This is a common property, not a universal one. The median is only just above
the 0.5-band descriptive cut, and the lower quartile is effectively zero.

### By market

| Market | Snapshots | Mean | Median | Model-wider share |
| :--- | ---: | ---: | ---: | ---: |
| Denver | 1,620 | +1.614 | +1.372 | 82.65% |
| Houston | 1,595 | +1.255 | +1.328 | 88.09% |
| Austin | 1,600 | +1.103 | +1.080 | 88.25% |
| Los Angeles | 1,535 | +0.922 | +0.761 | 92.12% |
| Dallas | 1,587 | +0.908 | +0.885 | 89.92% |
| Atlanta | 1,624 | +0.879 | +0.615 | 80.79% |
| Toronto | 1,703 | +0.865 | +0.330 | 65.65% |
| Seattle | 1,612 | +0.736 | +0.668 | 72.89% |
| San Francisco | 1,577 | +0.559 | +0.556 | 81.42% |
| NYC | 1,600 | +0.500 | +0.392 | 77.00% |
| Miami | 1,578 | **−0.212** | −0.134 | 35.04% |
| Chicago | 1,634 | **−0.285** | −0.165 | 43.21% |

The market split is material. A global sharpen would push Miami and Chicago
further in the direction where they are already narrower than the market.

### By realized band position relative to forecast high

| Winner offset | Snapshots | Mean width excess | Median | Model-wider share |
| :--- | ---: | ---: | ---: | ---: |
| `<=−3` | 442 | +0.671 | +0.632 | 81.67% |
| `−2` | 2,713 | **+1.191** | +0.981 | **92.22%** |
| `−1` | 6,464 | +0.793 | +0.771 | 82.01% |
| `0` | 6,271 | +0.639 | +0.408 | 68.73% |
| `+1` | 2,483 | +0.445 | −0.010 | 48.53% |
| `+2` | 392 | +0.515 | +0.267 | 54.34% |
| `>=+3` | 10 | +0.753 | +0.766 | 100.00% |
| Unknown forecast band | 490 | +0.469 | +0.293 | 96.94% |

Width excess is therefore concentrated most clearly when the realized winner
lands one or two bands cooler than forecast. A separate band-row view copies
the snapshot width onto each band and finds no sharp row-position boundary:
mean excess remains positive from `+0.609` to `+0.862` across the seven
relative-position buckets. The outcome-relative result above is the useful
slice; width is not confined to one quoted tail band.

### By capture hour

| Hour | Mean width excess | Model-wider share | Hour | Mean width excess | Model-wider share |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | +0.827 | 84.73% | 12 | +0.596 | 68.84% |
| 1 | +0.677 | 72.60% | 13 | +0.443 | 61.53% |
| 2 | +0.814 | 72.68% | 14 | **+0.196** | 55.54% |
| 3 | +0.800 | 63.99% | 15 | +0.321 | 61.33% |
| 4 | +0.945 | 68.47% | 16 | +0.247 | 60.63% |
| 5 | +1.006 | 72.80% | 17 | +0.519 | 77.08% |
| 6 | +1.033 | 74.30% | 18 | +0.659 | 87.44% |
| 7 | +1.067 | 74.49% | 19 | +0.828 | 88.02% |
| 8 | **+1.092** | 77.56% | 20 | +0.868 | 89.78% |
| 9 | +0.937 | 72.79% | 21 | +0.775 | 88.30% |
| 10 | +0.840 | 71.33% | 22 | +0.682 | 88.35% |
| 11 | +0.894 | 72.89% | 23 | +0.683 | 88.12% |

All hours are positive on average, but magnitude is not stable. It peaks near
hours 5–9, falls sharply at 14–16 as observations resolve the high, and then
returns late. That is an hour-conditioned distribution property, not evidence
for one constant global temperature.

## 2. The 7,513 severe rows outside the five retained bands

The counts reproduce the accepted map exactly: 9,032 ≥30-point market-right
rows, split into 1,519 inside and 7,513 outside the retained five. The outside
rows carry daily-normalized positive excess Brier `1.378686`: 80.21% of the
severe-tail contribution and 48.29% of all positive contribution.

Across those 7,513 rows:

| Shape measure | Result |
| :--- | ---: |
| Mean / median width excess | +0.951 / +1.120 effective bands |
| Mean / median centre displacement | −0.557 / −0.145 bands |
| Realized-winner probability, model minus market | −41.09 points mean |
| Model mode equals realized winner | 16.19% |
| Market mode equals realized winner | 70.80% |
| Mean absolute selected-band gap | 45.79 points |

The retained-five headline—market mode on the winner 94–99% of the time—does
not generalize intact. The outside market is less decisive, but it is still
the winner mode more than four times as often as the model.

### Geometry cross-section

| Geometry | Rows | Row share | Outside severe contribution share |
| :--- | ---: | ---: | ---: |
| Wide, cool-shifted | 2,195 | 29.22% | 28.42% |
| Wide, warm-shifted | 2,016 | 26.83% | 25.69% |
| Wide, centred | 806 | 10.73% | 6.56% |
| Near-market width, cool-shifted | 664 | 8.84% | 9.24% |
| Near-market width, warm-shifted | 375 | 4.99% | 6.24% |
| Near-market width, centred | 303 | 4.03% | 4.18% |
| Narrow, cool-shifted | 518 | 6.89% | 8.05% |
| Narrow, warm-shifted | 338 | 4.50% | 6.92% |
| Narrow, centred | 298 | 3.97% | 4.70% |

Width is the majority phenotype—66.78% of rows and 60.68% of contribution—but
it is not a single geometry. Only 10.73% of rows are wide while remaining
centred. Combining widths, cool shifts account for 44.95% of rows and 45.71%
of contribution; warm shifts account for 36.32% and 38.85%. The outside tail
therefore extends both prior geometries and adds meaningful narrow/near-width
failures. The coherent shared condition is **wrong centre or wrong allocation
around the winner**, not globally excessive width alone.

### Where it is

| Market | Outside severe rows | Contribution share | Mean width | Mean centre shift |
| :--- | ---: | ---: | ---: | ---: |
| Denver | 1,289 | 19.41% | +1.940 | −1.201 |
| Los Angeles | 989 | 15.55% | +1.294 | +0.086 |
| Chicago | 743 | 12.24% | **−0.286** | +0.667 |
| Houston | 883 | 11.17% | +1.099 | −0.590 |
| Seattle | 676 | 9.60% | +0.714 | −1.574 |
| Miami | 664 | 9.45% | **−0.133** | −0.951 |
| Austin | 594 | 5.97% | +1.173 | −0.312 |
| Dallas | 675 | 4.85% | +1.078 | −1.213 |
| Toronto | 311 | 4.24% | +0.997 | −0.588 |
| NYC | 301 | 3.62% | +0.766 | +0.317 |
| San Francisco | 282 | 2.83% | +0.657 | +0.681 |
| Atlanta | 106 | 1.07% | +0.600 | −0.970 |

The top six markets carry 68.01% of the outside contribution, but disagree on
both width and centre sign. Denver is wide/cool; Chicago is narrow/warm; Miami
is narrow/cool. This is not a five-band repair queue hiding under new names.

The erroneous band is usually close to forecast high: offset `0` carries
34.84% of outside contribution, `−1` 22.15%, and `+1` 18.88%. Those three
buckets together carry 75.87%. Far-tail thinning is therefore not the main
description. The general source-freshness label is again non-discriminating:
7,495/7,513 rows (99.76%) share the same
`failed:weather_forecast,wu_current,wu_history` state that covers 99.57% of the
full replay.

## 3. Outcome-aware oracle ceilings

### Construction and why it is an oracle

For each snapshot, the model and market are normalized over the 11 ordered
bands for moment calculation. Each complete correction is constructed from
the model distribution:

- **width:** preserve model expected band index and match market entropy, hence
  market effective band count;
- **centre:** match market expected band index and preserve model entropy;
- **both:** match both market expected index and market entropy.

Centre moves use an exponential tilt of the model probabilities. Entropy is
then adjusted at fixed centre along a convex path toward the feasible
minimum- or maximum-entropy distribution. Exact corrections match requested
means within `4.5e-15` bands and entropy within `8.9e-16`.

Some width/centre pairs are impossible on the fixed 11-band support. The
primary oracle applies a correction only when the moment pair is exact;
infeasible snapshots remain unchanged. It then uses the realized one-hot
outcome to choose, separately for every snapshot, whether the original or
fully corrected distribution has lower summed positive excess Brier. That
hindsight selector is the source of the “ceiling” and makes the result
non-achievable and unusable as later evidence.

| Lever | Exact moment pairs | Hindsight-selected exact corrections | Total reduction | Tail reduction | Severe rows after, including new |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Width | 14,676 / 19,265 (76.18%) | 6,361 | `0.456066` (**15.98%**) | `0.188064` (**10.94%**) | 8,074 |
| Centre | 18,808 / 19,265 (97.63%) | 14,316 | `1.674968` (**58.67%**) | `1.288544` (**74.97%**) | 1,525 |
| Both | 19,265 / 19,265 (100%) | 13,746 | `2.100339` (**73.57%**) | `1.501385` (**87.36%**) | 918 |

The fixed baselines are total daily-normalized positive excess Brier
`2.854773` and severe-tail positive excess `1.718715`.

Width's low exact feasibility is itself diagnostic. For 4,433 snapshots the
market entropy is below the minimum possible while retaining the model centre;
for 156 it is above the maximum. Those rows cannot be “perfectly sharpened”
without moving centre. Centre-only has 457 infeasible pairs; both is feasible
everywhere because the observed market distribution proves the target moment
pair exists.

A liberal sensitivity clips infeasible entropy targets to the nearest
feasible boundary before using the same hindsight selector. It raises width
only to 19.43% total and 13.20% tail, centre to 59.66% and 76.43%, and leaves
both unchanged. The ranking is not an artifact of the strict infeasibility
rule.

The oracle can create new severe rows because it selects on summed
snapshot-level positive excess, not each band independently: width creates 36,
centre 189, and both 13. This is another reason none of these rows may be used
as a deployable transform or gate result.

## Recommendation

After release #1, the first measured candidate should target **centre**, with
market-safe/weather-derived signals and explicit train/serve parity. It should
be evaluated against:

- aggregate Brier and calibration;
- the frozen ≥30-point-tail contribution and count;
- protected market, hour, and forecast-relative-position slices; and
- probability-mass and non-tail regressions.

Width should remain a secondary, conditional lever. The evidence rejects a
single global sharpen: two markets are already narrow on average, hours 14–16
have little excess, a quarter of all snapshots are narrower, and the exact
width oracle captures only 10.94% of severe-tail contribution. A later width
candidate is justified only after a centre candidate leaves a measurable
wide residual and must be market/hour conditioned rather than constant.

No candidate was built, fitted, tuned, scored, or authorized here.

## Leakage posture

Feature/outcome leakage: **PASS for retrospective description only**.
Evaluation independence: **FAIL by construction for every oracle claim**.

- The global width inventory itself uses only contemporaneous model and market
  distributions. Outcome-relative slices and all severe-row geometry use the
  realized winner descriptively.
- Oracle targets use the contemporaneous market moments, and the per-snapshot
  selector directly uses the realized outcome. This is intentional hindsight,
  not a proxy for an achievable model.
- July 22–30 is previously inspected engineering evidence and current code
  postdates some target days. It is not operationally untouched or a forward
  holdout.
- The oracle CSVs are terminal diagnostic artifacts. They must never be fed
  into training, candidate selection, a bound scorecard, or promotion proof.

## Machine-readable evidence and guardrails

All generated evidence is under the one declared run root outside the mirror:

- `width-ceiling-analysis.json` — full width, tail, and oracle summary;
  SHA-256 `c28e36915a8f87ddb063f6f9b5f0221304a7918ad5c668b2f0c0bee3c0968bcf`.
- `snapshot-width.csv` — all 19,265 snapshot distributions and width moments;
  SHA-256 `693be1c1ac6ed1e84b4c4a8714273ecfe2a966a06ede2f4f2d37ec656b265c85`.
- `outside-five-severe-rows.csv` — the exact 7,513-row geometry inventory;
  SHA-256 `1dc8f5fbc1c2eb2c940d8d6c190b2ce2d93745cea107679b47ef1ed636c9e4e2`.
- `oracle-ceilings.csv` — the three forced, strict, and boundary-sensitivity
  summaries; SHA-256
  `ff3469477fb2c97e926bb7e6f7112fffcddd3bafc52b16573ee7270b529d484e`.
- `oracle-snapshot-decisions.csv` — outcome-aware decision audit; SHA-256
  `06e4b83fe15d162ceff24239406b52ae961a408d1f4ae067d3d12bf2db04aac7`.

The validation script independently reasserted 19,265 snapshots, 211,915 band
rows, the 9,032/7,513/1,519 severe split, prior positive-excess totals, oracle
feasibility counts, and lever ordering.

`data/` and the mirror remained read-only. No candidate, fit, tuning,
transform, production artifact, PR, merge, master push, promotion, pointer,
serving, scheduler, capture, mirror, or ACL change occurred. No sync credential
was read or exposed.
