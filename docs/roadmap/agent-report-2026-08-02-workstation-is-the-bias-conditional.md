# Workstation report — 2026-08-02: is the cool bias conditional?

## Verdict

**Yes. The cool bias is materially conditional, not a pooled-mean calibration
curiosity.** The constant component is real, but only 29.89% of the honest
cross-fitted raw-centre squared-error benefit comes from the constant shift;
70.11% is incremental conditional structure. Forecast-relative position and
the floor/support regime carry that structure. Hour contributes essentially
nothing, and a market fixed effect does not transfer after the other terms are
known.

That makes this the **main upstream mechanism**, not a roughly 1% curiosity.
The qualification is important: it is not yet a proven end-to-end repair. On
the five development dates, the held-out conditional transform closes 24.69%
of the raw-HGB-versus-market Brier gap with an interval excluding zero, but
only 5.39% of the served-model gap, whose pooled interval includes zero. Its
served severe-tail effect is much larger and consistent across all five dates.
This supports a future training-prior/support experiment after release #1; it
does not support a downstream corrector or any current candidate.

No repair, retrain, candidate, artifact, tuning, held-candidate scoring, fresh
date, floor change, release, pointer, serving, scheduler, capture, PR, merge,
or master action was performed.

## Direct answers

| Question | Answer |
| --- | --- |
| Conditional or unconditional? | **Conditional.** A leave-one-date-out constant shift accounts for 29.89% of the total cross-fitted raw-centre MSE improvement; the declared conditional terms add 70.11%. |
| Where is the condition? | Primarily **raw HGB relative to the cutoff-valid forecast** and **floor/support regime**. Hour is negligible. Market effects are large descriptively but add negative held-out value after the other terms. |
| Is 98.88% resolution / 1.12% reliability current? | **No.** It was a different 129-market-day, 206,745-row, 11-F-market population before the relevant POST/floor frontier. On this exact July 22–26 window the served gap is 89.43% resolution / 10.57% reliability; raw HGB is 83.43% / 16.57%. |
| Honest held-out pooled size | Raw conditional: `-0.007784` Brier, 24.69% of its market gap, interval `[-0.015137, -0.000868]`, four of five dates. Served conditional: `-0.001151`, 5.39% of its gap, interval `[-0.007011, +0.004711]`, three of five dates. Negative is improvement. |
| Honest held-out severe-tail size | On 1,565 incumbent-frozen severe band rows, conditional served SSE falls 25.53%, interval for mean SSE delta `[-0.168034, -0.070902]`; positive excess falls 30.06%; all five dates improve. It creates 502 new severe rows and retires 678. |
| What is wrong with the prior? | **Temporal/regime staleness plus insufficient warm/top support.** The empirical label prior is cool because early/mid-June target-season samples serve a warmer late-July regime; no explicit class weighting exists. Upper truncation materially amplifies six days but does not explain the remaining in-support bias. |
| Main event or curiosity? | **Main event as an upstream causal mechanism; not yet a production result.** The raw and severe-tail effects are too large for “~1% curiosity,” while the uncertain 5.39% served pooled effect requires fresh evidence before any repair claim. |

## Scope and causal contract

The topic branch is stacked exactly on
`codex/workstation-why-is-the-morning-cool-2026-08-23a @ b893857e`. The sole
output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\is-bias-conditional-2026-08-24a`,
outside the mirror. All accepted inputs and `data/` remained read-only.

The analysis uses exactly July 22–26, effective cutoff 09–14: 12 markets, 60
market-days, 2,868 snapshots, and 31,548 binary band rows. It did not read,
enumerate, evaluate, or substitute July 27–31, August 1–3, or August 6–19.
July 31 remains the excluded `rows[-1]` POST boundary.

The method was declared before scoring:

1. Average raw `HGB expected native class - WU settlement` within each
   market-day and convert only pooled deltas to Celsius-equivalent.
2. Describe hour, market, forecast-relative position, and regime with 2,000
   market-day-cluster bootstrap replicates.
3. Use five leave-one-date-out folds. Each shift is fit on four dates and
   applied to the fifth; no validation outcome or market price is a feature.
4. Compare an intercept-only shift with an additive conditional shift over:
   hour, market, cutoff-valid `raw HGB centre - forecast high`, and the cross of
   frozen gate lane with `forecast high > artifact class maximum`.
5. Exponentially tilt only the held-out ordered probability simplex to the
   fitted centre. A served transform cannot increase probability below the
   accepted floor band. There were zero floor projections and maximum simplex
   error `4.44e-16`; feasible-support clipping occurred on 222 raw-conditional
   and 189 served-conditional snapshots and is disclosed.
6. Freeze the severe tail from the incumbent: positive incumbent-minus-market
   squared-error excess and absolute incumbent-minus-market probability
   distance at least 0.30. Corrected lanes cannot redefine membership.

These are ephemeral diagnostic transforms, not trained weather models,
candidates, artifacts, or selectable serving policies.

## 1. Constant versus conditional structure

The recomputed daily-first raw bias is `-1.213093 °C-equivalent`, with cluster
interval `[-1.764725, -0.742578]`. The slightly different endpoints from the
accepted `-08-23a` interval come from this mission's separately declared
bootstrap seed; the point estimate reproduces exactly.

### Cross-fitted centre decomposition

All quantities below are squared ordered-band centre error, daily-first. The
constant and conditional shifts are genuinely out of fold.

| Target | No shift | Constant OOF | Full conditional OOF | Constant share of total benefit | Conditional share |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw HGB centre | 3.6303695 | 2.8649532 | **1.0692230** | 29.89% | **70.11%** |
| Served centre | 1.5884627 | 1.5864725 | **1.1244987** | 0.43% | **99.57%** |

The raw constant shift averages `+0.9905` bands out of fold. The full shift
averages `+0.9251` bands but has standard deviation `1.3143`; its conditional
deviation from the fold constant has RMS `1.3665` bands. A single warm offset
therefore misses variation at least as large as the offset itself.

Shapley-averaging the incremental held-out raw-centre improvement over every
ordering of the four declared feature blocks gives:

| Conditional block | Incremental MSE reduction | Share of conditional increment |
| --- | ---: | ---: |
| Forecast-relative position | +1.015994 | 56.58% |
| Floor/support regime | +0.865053 | 48.17% |
| Hour | +0.001003 | 0.06% |
| Market | **-0.086320** | -4.81% |
| **Total conditional increment** | **+1.795730** | **100.00%** |

Market is not “irrelevant.” Its five-date descriptive levels are large, but a
separate market intercept adds noise when the forecast-relative and support
state are already known. With only five dates, the defensible transferable
claim is about forecast/support state, not a fleet of per-market offsets.

### Hour is nearly unconditional

Every hour remains cool and the differences are small:

| Hour | Raw bias, °C-equivalent | 95% cluster interval |
| ---: | ---: | ---: |
| 09 | -1.1490 | [-1.6971, -0.6455] |
| 10 | -1.1822 | [-1.7393, -0.7026] |
| 11 | -1.2901 | [-1.8003, -0.8157] |
| 12 | -1.3122 | [-1.8997, -0.7981] |
| 13 | -1.1532 | [-1.7140, -0.6608] |
| 14 | -1.1920 | [-1.8021, -0.6970] |

This explains the near-zero held-out hour contribution. “Morning” exposes the
base defect because floor masking is weaker, not because 09–14 owns a distinct
clock-conditioned bias.

### Forecast-relative position is strongly conditional

The declared feature is raw HGB centre minus cutoff-valid forecast high. It
uses neither settlement nor market price.

| Raw HGB relative to forecast | Snapshots / market-days | Raw bias, °C-equivalent | 95% cluster interval |
| --- | ---: | ---: | ---: |
| At least 2 °C below | 827 / 27 | **-2.8959** | [-3.7665, -2.1787] |
| 1–2 °C below | 718 / 35 | -0.8508 | [-1.1307, -0.5826] |
| Up to 1 °C below | 827 / 38 | -0.0739 | [-0.3157, +0.1575] |
| Above forecast | 481 / 25 | +0.3273 | [-0.0035, +0.6601] |
| Forecast missing | 15 / 1 | -1.2058 | single cluster |

The raw bias largely disappears once HGB has caught up to the forecast and
becomes severe when it has not. That is conditional information loss, not a
global calibration offset.

### Support/floor regime is strongly conditional

| Frozen regime | Snapshots / market-days | Raw bias, °C-equivalent | 95% cluster interval |
| --- | ---: | ---: | ---: |
| Excluded, forecast in support | 2,233 / 52 | -0.6956 | [-1.1057, -0.3475] |
| Qualified, forecast in support | 398 / 24 | -1.5929 | [-2.1869, -1.0627] |
| Excluded, forecast above support | 42 / 4 | -5.0181 | [-6.5496, -3.4867] |
| Qualified, forecast above support | 195 / 6 | **-5.9144** | [-7.6456, -4.3851] |

Floor qualification selects distributions with more impossible cool mass; it
does not cause the raw bias. Forecast support exceedance identifies the most
severe base-model failures before the floor can mask them.

### Market dispersion is real but not a transferable offset

All entries are normalized to Celsius-equivalent solely for comparison.

| Market | Raw bias | 95% cluster interval |
| --- | ---: | ---: |
| Atlanta | -0.5871 | [-1.4416, +0.0677] |
| Austin | -0.6740 | [-2.1553, +0.3032] |
| Chicago | +0.2446 | [-0.6978, +1.1048] |
| Dallas | -2.0528 | [-4.4341, -0.6265] |
| Denver | -3.4521 | [-5.2824, -1.3543] |
| Houston | -0.3322 | [-2.1024, +0.8277] |
| Los Angeles | -2.6235 | [-3.1540, -2.1876] |
| Miami | -0.9107 | [-1.2964, -0.5754] |
| NYC | -0.7410 | [-1.7149, -0.0482] |
| San Francisco | -0.0709 | [-0.3538, +0.2788] |
| Seattle | -3.1139 | [-6.4544, -0.4676] |
| Toronto | -0.2436 | [-0.7725, +0.2075] |

This table is descriptive with only five clusters per market. The negative
held-out market Shapley value blocks the tempting conclusion that twelve
market-specific downstream corrections are warranted.

## 2. Reliability/resolution reconciliation

The historical 98.88/1.12 headline is not wrong for its original corpus. It is
stale for this question because it used 129 market-days, 206,745 binary rows,
11 F markets, and an older mixed population. The later POST/floor 09–14
frontier had already moved to 87.97% resolution / 12.03% reliability on its
accepted population.

Using the repository's exact market-stratified, bin-free CORP/isotonic Murphy
identity on only these 31,548 July 22–26 morning rows gives:

| Lane versus raw market | Brier gap | Reliability contribution | Resolution contribution |
| --- | ---: | ---: | ---: |
| Raw HGB | +0.0315322 | +0.0052253 (**16.57%**) | +0.0263069 (**83.43%**) |
| Served incumbent | +0.0213608 | +0.0022570 (**10.57%**) | +0.0191038 (**89.43%**) |

The bias therefore lands predominantly in lost resolution on its exact
development population. The floor and other downstream stages reduce both the
gap and the visible reliability share, but do not reverse the conclusion.

The held-out transforms show why the constant/conditional distinction matters:

| Transform | Brier improvement | Reliability reduction | Resolution increase |
| --- | ---: | ---: | ---: |
| Raw constant | **-0.000430** | +0.000031 | **-0.000462** |
| Raw conditional | **+0.007784** | +0.002322 (29.83%) | **+0.005462 (70.17%)** |
| Served constant | **-0.000786** | +0.001289 | **-0.002075** |
| Served conditional | **+0.001151** | +0.000672 (58.37%) | +0.000479 (41.63%) |

Positive is improvement. Both constant shifts reduce reliability error, as
expected, but lose more resolution than they gain and worsen Brier. The raw
conditional transform gains primarily through resolution. Downstream masking
attenuates that to a smaller served effect split across both components.

## 3. Held-out causal size: pooled and severe tail

Primary scoring is snapshot-first mean binary-band Brier, matching the
accepted POST frontier. Intervals bootstrap market-day clusters over fixed
out-of-fold predictions; fold signs are reported because there are only five
dates.

| Lane | Brier | Delta from base | 95% cluster interval | Dates improved | Share of base market gap closed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw HGB | 0.080266 | — | — | — | — |
| Raw constant OOF | 0.080697 | **+0.000430** | [-0.005966, +0.006408] | 3 / 5 | -1.37% |
| Raw conditional OOF | **0.072483** | **-0.007784** | **[-0.015137, -0.000868]** | 4 / 5 | **24.69%** |
| Served incumbent | 0.070095 | — | — | — | — |
| Served constant OOF | 0.070882 | **+0.000786** | [-0.002000, +0.003751] | 2 / 5 | -3.68% |
| Served conditional OOF | **0.068944** | **-0.001151** | [-0.007011, +0.004711] | 3 / 5 | **5.39%** |
| Raw market | 0.048734 | — | — | — | — |

Negative deltas improve. Daily-first sensitivities preserve the signs:
constant/conditional raw `+0.000353 / -0.007935`, and constant/conditional
served `+0.000783 / -0.001353`.

The served pooled result is honest and deliberately not oversold: its interval
crosses zero and it regresses July 23 and July 26. The raw result is larger,
improves four dates, and excludes zero. This is consistent with the trusted
floor masking an upstream defect rather than a direct served-centre shift being
the eventual implementation.

### Incumbent-frozen severe tail

The 1,565 frozen severe rows are 4.96% of band rows. Conditional correction has
a much larger and more stable effect there:

| Metric | Constant OOF | Conditional OOF |
| --- | ---: | ---: |
| Fixed-tail mean SSE delta | -0.013979 | **-0.122150** |
| 95% cluster interval | [-0.065825, -0.002402] | **[-0.168034, -0.070902]** |
| Fixed-tail SSE reduction | 2.92% | **25.53%** |
| Fixed-tail positive-excess reduction | 3.61% | **30.06%** |
| Dates with lower fixed-tail SSE | 4 / 5 | **5 / 5** |
| Severe rows after transform | 1,598 | **1,389** |
| New / retired severe rows | 390 / 357 | **502 / 678** |

The all-five-date tail consistency is the strongest score consequence. The 502
new severe rows are also why this diagnosis cannot be promoted into a candidate
or gate claim. A future upstream fit still needs the inherited total-Brier,
fixed-tail, and new-severe protections on fresh post-August-19 evidence.

## 4. What is specifically wrong with the training prior?

The evidence separates four related claims:

1. **Temporal staleness — supported and primary.** The exact fitted label prior
   is `-2.7506 °C-equivalent` below these outcomes. Live fitted features warm it
   by `+1.5375`, but raw HGB remains `-1.2131`. The artifacts date to June 9–14
   and reconstruct `±7`-day target-season rows while serving July 22–26. Most
   morning artifact-hours have only 164 or 165 fitted rows.
2. **Warm-class underweighting — a symptom, not an explicit weighting bug.**
   Every artifact uses unweighted categorical log loss. Its empirical prior
   puts too little mass on the warm classes for this window because the source
   sample is cooler/staler; there is no explicit warm-class weight to turn up.
3. **Upper truncation — a material amplifier, not the whole cause.** Settlement
   exceeds fitted maximum class on 6/60 market-days. Those days account for
   48.41% of signed cool displacement, and cutoff-valid forecast exceeds class
   maximum on 8.26% of snapshots. The other 54 days remain cool at `-0.6953`
   `[-1.0427, -0.3647]`.
4. **Serving-regime mismatch — supported but not uniquely identified.** Bias
   rises from `-0.6956` in the excluded/in-support regime to roughly `-5` to
   `-5.9` when forecast is above support. Five dates cannot separate seasonal
   drift from a transient hot synoptic regime or geography, but they do prove
   the prior/support contract is mismatched to rows the serving system sees.

The eventual first hypothesis should therefore combine a target-date-aligned
prior refresh with upper class-support extension. A pure reweighting does not
fix absent top classes, and a support-only change leaves the significant
in-support bias. Operationally that is retrain-shaped work and remains blocked
on release #1 plus its own fresh post-August-19 evidence. No work begins here.

## Limitations and decision boundary

- Five dates are enough for honest leave-one-date-out measurement, not enough
  for production confidence or stable per-market offsets.
- Extreme support regimes have only 4–6 contributing market-days, although
  their intervals exclude zero.
- The conditional transforms are simple diagnostic probability tilts. They
  size predictable displacement but do not reproduce a future HGB retrain's
  downstream nonlinear path.
- The served pooled interval crosses zero, two held-out dates regress, and new
  severe rows remain material. The verdict is about mechanism and experiment
  priority, not readiness.

Plainly: **do not retire this line as a 1% curiosity. Treat the upstream
training-prior/support mismatch as the main model mechanism to test after the
existing release and evidence sequence, while retaining every current floor
and gate.**

## Evidence and verification

An independent verifier did not import the analysis harness. It reconstructed
all four leave-one-date-out shifts with an independent normal-equation
pseudoinverse, re-ran market-stratified PAV/CORP, probability scores, floor
constraints, and severe membership, and passed 17,267 comparisons. Maximum
absolute numeric delta was `2.35e-12`.

The final evidence-manifest SHA-256 is
`056e9b6123191df12b4286cead475eae7cbf5073b9024cad279cf1448755c4ed`.

| Evidence | SHA-256 |
| --- | --- |
| Declaration | `f2bb38ceb2f34ae232de9e3e274726a824e31fbafb635ce1698836ebd2d4bd74` |
| Analysis harness | `4e73543e8fd675630cb067c14bb01d50d4d3391ecac5fcdf92440cf5fdf31b0f` |
| Conditional group table | `5c5d531a158ef39217c9bbd6e27cb85777adbcc811508159112fd80b19782d77` |
| Summary | `3daa3a3d9e7c22f06dbca77e40b81c5c065fc373f5237ab9bd1aae2b71d185d5` |
| CORP decomposition | `61196bb8f196ebf0f92edcd4d0762bf169b9cb4eb2cff5fa6fefb00d2db91521` |
| OOF snapshot transforms | `fe3f6588d7bdc655b6c2cb630147c5590d74d96099acc94ad03fc3a397aaaeba` |
| OOF score table | `dd51652f2666d460d2b350c5f5f40248ab41cec60f893fbfb11cf6f1a5879fbe` |
| Independent verifier | `0609fe88544a34fe99fe20848c5aae2156a7714403aba1e477e86226f4c5db2d` |
| Verification receipt | `a57161a683d42c340ddc200cbb1cb35a72eb34a5fb0b68306d061f3826f10bb3` |

`-08-16a` remains queued for 2026-08-05 04:30. No production host, mirror,
credential, paid provider, release, pointer, serving, scheduler, capture, ACL,
PR, merge, or master state changed.
