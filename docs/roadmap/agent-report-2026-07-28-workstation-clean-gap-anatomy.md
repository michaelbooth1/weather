# Workstation clean-gap anatomy — 2026-07-28

Status: **PASS — THE BLEND COST AND BELOW-FLOOR DEFECT ARE THE SAME
POPULATION-LEVEL FAILURE MODE. THE CLEAN PREBLEND GAP LIVES IN GENUINELY
UNCERTAIN HOURS, NOT IN THE NEAR-RESOLVED EVENING.**

This report executes
[`workstation-handoff-2026-07-28g-where-does-the-clean-gap-live.md`](workstation-handoff-2026-07-28g-where-does-the-clean-gap-live.md)
from exact `origin/master`
`e7e93e587d6afdfeaf35fa543e10830ef36bc1cc` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Answer first: one defect, with an important qualification

The seventh candidate survives. The partitions in which replay-final
introduces rounded-floor-infeasible mass carry **132.10%** of the full POST
blend cost. The floor-clean and no-constraint groups offset part of that harm;
they do not share it.

| POST group | Composite keys | Binary rows | Final minus preblend BS | Contribution to full POST cost | Share of full cost |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Finite floor, replay-final violates | **7,193** | 79,123 | **+0.004886** | **+0.003013** | **132.10%** |
| Finite floor, replay-final clean | 4,408 | 48,499 | **-0.001829** | **-0.000692** | -30.32% |
| No stored floor constraint | 61 | 671 | **-0.007758** | **-0.000041** | -1.78% |
| **Full POST** | **11,662** | **128,293** | **+0.002281** | **+0.002281** | **100.00%** |

The three contributions reconcile the accepted POST headline to
`4.34e-19`. The violating group is not tiny: it is 61.68% of POST composite
keys. Its final lane is worse than preblend by `0.004885823` binary Brier,
while blending improves the floor-clean group by `0.001829474`.

This is a population-level answer, not a claim that below-floor mass and
score harm are one-to-one in every partition. Within the violating group,
5,521 simplexes are harmed and 1,672 helped; within the clean group, effect
signs also mix. What is decisive is that the aggregate cost is entirely
concentrated in the violating regime and is more than the net cost because
the other regimes rescue score.

The direct counterfactual corroborates that reading. On the identical 11,598
eligible POST simplexes, final projection gains `0.002723327` binary Brier
against a `0.002334290` final-versus-preblend penalty: **116.67% of the
eligible pooled blend penalty is recovered**. The projection is therefore
more than a diagnostic marker in aggregate. It is still not a deployment
proposal, and it is not per-case dominant; the worsening cases below matter.

## Denominator correction

The handoff's `0 / 124` versus `108 / 124` table was pooled, not POST. Exact
join to the accepted regime bridge gives:

| Historical hour-20 packet | PRE | POST |
| :--- | ---: | ---: |
| Cases | 40 | **84** |
| Replay-final violations | 24 | **84** |

For the 84 POST cases:

| Lane | Violations | Total below-floor mass |
| :--- | ---: | ---: |
| Preblend | **0 / 84** | `4.0994e-13` |
| Replay-final | **84 / 84** | `12.335400106` |
| Incumbent | **84 / 84** | `24.670800212` |
| Recorded | **84 / 84** | `22.877966435` |

Their mean `(preblend - final)` delta is `-0.010348633` in binary units
(`-0.113834967` categorical). They are only 924 of 128,293 POST band rows,
so they cannot alone carry the pooled `0.002281091` cost. That is why the
question-first test above uses every POST composite key and keeps the 61
no-floor instants visible.

## Where the clean gap lives

The clean preblend gap is a forecasting/sharpness problem in uncertain hours,
not an engineering deficit where the result is already publicly observable:

- On the globally selected cadence-neutral panel, genuinely uncertain
  partitions are 1,255 of 1,855 and carry **96.74%** of the weighted clean
  preblend gap. The 600 near-resolved partitions carry 3.26%.
- Predawn clean gap is `0.013521`; primary-hours gap is `0.014459`; evening
  gap is only `0.000022888`.
- The largest hourly clean gap is hour 08 (`0.017918`), followed by hours 06
  (`0.017467`) and 09 (`0.017349`). Hours 20–23 range only from `0.000045`
  down to `0.000009`.
- Across full POST, preblend's `0.009292178` gap to raw market decomposes into
  a **reliability advantage** of `-0.001199395` and a **resolution deficit**
  of `+0.010491572`. The remaining clean gap is sharpness, not calibration.

This reverses the old pooled framing. The clean candidate is essentially at
the market in the near-resolved evening. Replay-final's evening catastrophe
is downstream blend damage. The remaining clean-model programme belongs in
forecasting during genuine uncertainty; the blend/floor repair is a separate
engineering win.

### Named cuts, full CORP decomposition

All values are binary band Brier/CORP components. Each decomposition was
refit by market on the selected cut; no hourly components were averaged.
Uncertainty is `0.082645` throughout the 11-band valid-simplex panels.

| Cut | n | Pre BS | Pre REL | Pre RES | Final BS | Final REL | Final RES | Market BS | Market REL | Market RES | Pre gap |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Predawn 03–05 | 222 | 0.074544 | 0.010421 | 0.018522 | 0.073503 | 0.010387 | 0.019529 | 0.061024 | 0.014090 | 0.035711 | 0.013521 |
| Primary 09–14 | 444 | 0.067949 | 0.006539 | 0.021235 | 0.065419 | 0.006537 | 0.023762 | 0.053490 | 0.007769 | 0.036924 | 0.014459 |
| Evening 20–23 | 339 | 0.000023 | 0.000023 | 0.082645 | 0.011193 | 0.011193 | 0.082645 | 0.000001 | 0.000001 | 0.082645 | 0.000023 |

### Resolvedness

Near-resolved retains the accepted definition: normalize the nonnegative raw
market vector, then classify `max(q) >= 0.95`. Genuinely uncertain is the
strict complement. The four-bin companion is retained in the machine-readable
analysis.

| Basis | Group | n | Pre BS/REL/RES | Final BS/REL/RES | Market BS/REL/RES | Pre gap |
| :--- | :--- | ---: | :--- | :--- | :--- | ---: |
| Cadence-neutral | Genuinely uncertain | 1,255 | 0.067209/0.005978/0.021413 | 0.065486/0.005742/0.022901 | 0.054247/0.007215/0.035612 | **0.012962** |
| Cadence-neutral | Near-resolved | 600 | 0.001221/0.000346/0.081770 | 0.011930/0.011147/0.081861 | 0.000306/0.000192/0.082531 | **0.000915** |
| All valid POST | Genuinely uncertain | 8,068 | 0.068415/0.005735/0.019964 | 0.066808/0.005743/0.021579 | 0.055280/0.007371/0.034736 | **0.013136** |
| All valid POST | Near-resolved | 3,593 | 0.000755/0.000363/0.082253 | 0.011766/0.011273/0.082151 | 0.000115/0.000056/0.082586 | **0.000640** |

The cadence-neutral four-way counts are 928 high-uncertainty, 216 moderate,
111 low, and 600 near-resolved. Their clean preblend gaps are `0.013711`,
`0.014286`, `0.004125`, and `0.000915`, respectively.

### All 24 market-local hours

The 2,962 global target-day `(market, date, local hour)` representatives were
selected before regime filtering; 1,855 are POST. There is no collision in
this panel.

| Hour | n | Pre BS | Pre REL | Pre RES | Final BS | Final REL | Final RES | Market BS | Market REL | Market RES | Pre gap |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00 | 74 | 0.071806 | 0.011402 | 0.022241 | 0.070910 | 0.013073 | 0.024807 | 0.062505 | 0.012646 | 0.032785 | 0.009301 |
| 01 | 74 | 0.071727 | 0.011380 | 0.022298 | 0.070932 | 0.012793 | 0.024506 | 0.062681 | 0.015725 | 0.035689 | 0.009046 |
| 02 | 74 | 0.072648 | 0.011499 | 0.021495 | 0.072160 | 0.013469 | 0.023954 | 0.062054 | 0.015012 | 0.035602 | 0.010593 |
| 03 | 74 | 0.072342 | 0.010450 | 0.020753 | 0.073644 | 0.012280 | 0.021281 | 0.061824 | 0.016300 | 0.037120 | 0.010517 |
| 04 | 74 | 0.075249 | 0.011754 | 0.019149 | 0.073567 | 0.012270 | 0.021348 | 0.060540 | 0.015679 | 0.037783 | 0.014709 |
| 05 | 74 | 0.076042 | 0.013095 | 0.019698 | 0.073298 | 0.012887 | 0.022234 | 0.060706 | 0.015829 | 0.037768 | 0.015336 |
| 06 | 74 | 0.078089 | 0.014902 | 0.019458 | 0.073030 | 0.014634 | 0.024249 | 0.060622 | 0.015526 | 0.037549 | 0.017467 |
| 07 | 74 | 0.076356 | 0.015132 | 0.021421 | 0.073871 | 0.014168 | 0.022941 | 0.060684 | 0.013758 | 0.035719 | 0.015672 |
| 08 | 74 | 0.077623 | 0.014693 | 0.019714 | 0.071991 | 0.014538 | 0.025192 | 0.059705 | 0.014001 | 0.036940 | 0.017918 |
| 09 | 74 | 0.076296 | 0.011487 | 0.017835 | 0.071072 | 0.013809 | 0.025381 | 0.058947 | 0.013458 | 0.037156 | 0.017349 |
| 10 | 74 | 0.075378 | 0.010848 | 0.018115 | 0.072630 | 0.012980 | 0.022995 | 0.058803 | 0.014439 | 0.038281 | 0.016575 |
| 11 | 74 | 0.072133 | 0.014402 | 0.024913 | 0.069019 | 0.013892 | 0.027517 | 0.057471 | 0.014017 | 0.039190 | 0.014662 |
| 12 | 74 | 0.069813 | 0.014023 | 0.026855 | 0.066906 | 0.012540 | 0.028278 | 0.054642 | 0.013672 | 0.041674 | 0.015170 |
| 13 | 74 | 0.065037 | 0.014082 | 0.031690 | 0.063382 | 0.011821 | 0.031084 | 0.050596 | 0.012539 | 0.044588 | 0.014441 |
| 14 | 74 | 0.049035 | 0.015118 | 0.048728 | 0.049505 | 0.013080 | 0.046219 | 0.040478 | 0.010869 | 0.053035 | 0.008557 |
| 15 | 77 | 0.038666 | 0.010248 | 0.054226 | 0.041242 | 0.014497 | 0.055900 | 0.027294 | 0.008508 | 0.063858 | 0.011372 |
| 16 | 78 | 0.016263 | 0.006277 | 0.072658 | 0.023430 | 0.012313 | 0.071528 | 0.013469 | 0.004818 | 0.073994 | 0.002794 |
| 17 | 82 | 0.007008 | 0.003175 | 0.078812 | 0.015596 | 0.010555 | 0.077603 | 0.005823 | 0.002497 | 0.079319 | 0.001184 |
| 18 | 84 | 0.002163 | 0.001189 | 0.081671 | 0.011736 | 0.010924 | 0.081833 | 0.000942 | 0.000401 | 0.082104 | 0.001221 |
| 19 | 85 | 0.002139 | 0.001188 | 0.081694 | 0.010397 | 0.009595 | 0.081842 | 0.000094 | 0.000094 | 0.082645 | 0.002045 |
| 20 | 84 | 0.000046 | 0.000046 | 0.082645 | 0.010395 | 0.010395 | 0.082645 | 0.000001 | 0.000001 | 0.082645 | 0.000045 |
| 21 | 85 | 0.000026 | 0.000026 | 0.082645 | 0.011675 | 0.011675 | 0.082645 | 0.000001 | 0.000001 | 0.082645 | 0.000026 |
| 22 | 85 | 0.000012 | 0.000012 | 0.082645 | 0.011456 | 0.011456 | 0.082645 | 0.000000 | 0.000000 | 0.082645 | 0.000011 |
| 23 | 85 | 0.000010 | 0.000010 | 0.082645 | 0.011236 | 0.011236 | 0.082645 | 0.000000 | 0.000000 | 0.082645 | 0.000009 |

## Where the floor mass is introduced

Preblend is clean **by construction**, then the downstream blend discards the
physical guarantee:

1. The hash-pinned artifact has `hard_floor_enabled=true`.
2. Band postprocessing returns a hard zero for a band strictly below
   `ROUND_HALF_UP(high_so_far)`.
3. Gamma-1.25 candidate normalization changes those zeros only to
   epsilon-scale positive values.
4. `candidate_preblend_probability` is captured.
5. Per-band incumbent mixing runs.
6. Gamma-1 `max(1e-12, mixed)` mass restoration runs, with no second physical
   floor.

Across all 11,600 valid finite-floor POST simplexes, preblend has **zero**
cases over `1e-9`, total below-floor mass `3.3789e-11`, and maximum
per-partition mass `4.3081e-14`.

The artifact algebra was independently reconstructed for every POST generator
group, including Austin as one 22-row normalization group:

```text
r_j = alpha_j * preblend_j + (1 - alpha_j) * incumbent_j
w_j = max(1e-12, r_j)
final_hat_j = w_j / sum_G(w)
```

All 128,293 POST rows reproduce: 84,047 are bit exact and 44,246 require only
the predeclared eight-ULP tolerance. Maximum absolute error is `3.33e-16`;
there is no materially ambiguous violating partition. The effective alpha
row counts are:

| Alpha | POST band rows |
| ---: | ---: |
| 0 | 1,708 |
| 0.2 | 1,016 |
| 0.35 | 36,901 |
| 0.5 | 88,429 |
| 1 | 239 |

The export omits `current_max_disposition`, so the algebra identifies
membership in the final alpha-0.5 rule but cannot distinguish
`support_only`, `quarantined`, and `null_before_reset`. It uniquely classifies
8,038 POST generator groups as members and 3,624 as nonmembers. No exact
disposition claim is made.

For all 11,601 finite-floor POST generator groups, replay-final's
`682.255306888` below-floor mass decomposes as:

| Source | Below-floor mass |
| :--- | ---: |
| Candidate carry | `1.6063e-11` |
| **Incumbent introduction** | **`682.255306887`** |
| Numerical-floor restoration | `4.8801e-10` |
| Maximum partition residual | **`2.22e-16`** |

The residual is zero at scoring precision. The blend merely propagates the
incumbent violation; it does not create an unexplained second source.

### Incumbent shape

Among 11,600 valid finite-floor POST simplexes, incumbent violates in 7,225
and carries `1,363.939243` total mass. On the cadence-neutral finite-floor
panel, it violates in 1,187 of 1,830 and carries `228.399051`.

It is broad by market: Dallas has 15.15% of full-scope mass, Houston 12.22%,
Denver 11.39%, Atlanta 10.84%, and Los Angeles 10.15%. It is sharply late by
hour: hours 23, 22, 21, and 20 carry 12.69%, 12.43%, 12.00%, and 10.08%,
and every finite-floor case in each of those hours violates. Printed-floor
bins 95–99 and 90–94 carry 28.54% and 26.94%; 100–104 carries another
12.47%.

That is the shape of a broadly floor-unaware incumbent/postblend path, not a
single western market or one stale-input pocket.

## Price of rounded-floor projection

The primary projection population is selected before exclusions:

- 11,662 POST composite keys;
- minus 61 no-constraint keys;
- minus the one Austin collision without replacement;
- minus two off-target-date keys;
- equals **11,598 target-day finite-floor valid simplexes**.

The evening panel is the same globally selected cadence-neutral 20–23 cut
used above: 339 simplexes. Projection exact-zeros strictly-below-floor bands
and renormalizes survivors without an epsilon floor. Raw market remains the
gap baseline; projected normalized market is labelled sensitivity only.

Categorical Brier is exactly 11 times binary Brier on these 11-band
simplexes. Full before/after CORP decompositions follow.

### Pooled

| Lane | Binary BS before→after | REL before→after | RES before→after | Categorical BS before→after | Binary gain | Raw-market gap closed | Improved/equal/worse |
| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: |
| Preblend | 0.047339→0.047339 | 0.003891→0.003891 | 0.039196→0.039196 | 0.520733→0.520733 | 0.000000 | 0.0% | 0/11,598/0 |
| **Replay-final** | **0.049674→0.046950** | **0.005448→0.004289** | **0.038419→0.039983** | **0.546411→0.516454** | **0.002723** | **23.8%** | 5,731/4,407/**1,460** |
| Incumbent | 0.063563→0.055131 | 0.005984→0.005216 | 0.025065→0.032729 | 0.699196→0.606443 | 0.008432 | 33.3% | 5,176/4,375/**2,047** |
| Recorded | 0.064331→0.055778 | 0.006122→0.005645 | 0.024436→0.032512 | 0.707637→0.613557 | 0.008553 | 32.7% | 5,204/4,375/**2,019** |
| Normalized market sensitivity | 0.038098→0.037971 | 0.005125→0.005115 | 0.049672→0.049789 | 0.419078→0.417677 | 0.000127 | n/a | 5,872/4,375/**1,351** |

Replay-final's gain splits into `0.001159` reliability and `0.001564`
resolution. Its raw-market gap falls from `0.011463348` to `0.008740021`.

### Evening 20–23

| Lane | Binary BS before→after | REL before→after | RES before→after | Categorical BS before→after | Binary gain | Raw-market gap closed | Improved/equal/worse |
| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: |
| Preblend | 0.000023→0.000023 | 0.000023→0.000023 | 0.082645→0.082645 | 0.000258→0.000258 | 0.000000 | 0.0% | 0/339/0 |
| **Replay-final** | **0.011193→0.003557** | **0.011193→0.003557** | **0.082645→0.082645** | **0.123123→0.039129** | **0.007636** | **68.2%** | **339/0/0** |
| Incumbent | 0.043901→0.020902 | 0.015130→0.008832 | 0.053873→0.070575 | 0.482913→0.229922 | 0.022999 | 52.4% | 298/0/**41** |
| Recorded | 0.040768→0.018385 | 0.013934→0.007593 | 0.055810→0.071853 | 0.448451→0.202235 | 0.022383 | 54.9% | 311/0/**28** |
| Normalized market sensitivity | 0.000003→0.000001 | 0.000003→0.000001 | 0.082645→0.082645 | 0.000036→0.000015 | 0.000002 | 71.1% | 339/0/0 |

Evening final projection recovers 68.36% of the final-versus-preblend
penalty, not all of it. Projected final remains `0.003533667` worse than
clean preblend. The blend also distorts feasible-band mass; below-floor mass
is the dominant but not exclusive per-partition arithmetic effect.

### Important surprise: projection is not per-case dominant

Projection improves every evening replay-final case and improves every lane
in aggregate, but it makes many pooled cases worse:

| Lane/scope | Worse cases | Maximum categorical worsening |
| :--- | ---: | ---: |
| Replay-final, pooled | **1,460** | `0.128746` |
| Replay-final, evening | 0 | `0` |
| Incumbent, pooled | **2,047** | `0.281211` |
| Incumbent, evening | **41** | `0.280186` |
| Recorded, pooled | **2,019** | `0.212419` |
| Recorded, evening | **28** | `0.148800` |
| Normalized market sensitivity, pooled | **1,351** | `0.457819` |
| Preblend, either scope | 0 | `0` |

All 6,946 scope/lane worsening rows over `1e-12` are preserved in
`projection_worse_cases.csv`. They represent 6,877 unique
partition/lane pairs across 2,587 distinct partitions; 69 evening rows are
also members of the pooled population and therefore appear once per requested
scope. The surprise is mathematically possible because zero-and-renormalize
is conditioning on the feasible set, not Euclidean projection under
categorical Brier: it can increase probability on multiple wrong surviving
bands enough to hurt an individual outcome. The aggregate prize remains
positive, but the counterfactual is not a safe blanket-serving recommendation.

## Frozen estimand and caveats

- Regime is captured-runtime commit ancestry only. POST contains 11,662
  composite keys, 128,293 binary rows, 11,661 valid simplexes, and the one
  accepted Austin collision.
- Every POST floor bridge row is either numeric-exact between stored and
  reconstructed (11,601) or both-null (61). The PRE stored-versus-reconstructed
  disagreement is outside this estimand; reconstructed values are never
  substituted.
- The floor is the stored capture-time feature rounded with decimal
  `ROUND_HALF_UP`. The accepted stored rounded-settlement gate has zero
  exceedances. This does not erase the separately reported historical
  non-monotonicity of the feature path.
- Raw market probabilities are the score comparator. Normalization is used
  only for resolvedness and the explicitly labelled market projection
  sensitivity.
- Binary CORP is exact per-market PAV, row-count weighted. Collision rows are
  retained for the accepted binary headline and excluded without replacement
  from categorical, resolvedness-simplex, and projection metrics.

## Execution, verification, and authority

The single write root was:

`C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\clean-gap-anatomy-20260728g-e7e93e58`

Fresh admission at 20:55 ET recorded 48% committed memory, 63.16 GiB free
disk, and no competing research, training, copy, or compression process. The
first attempt stopped before corpus access on sandbox Git ownership. The
second stopped at the projection scope gate because all repeated evening
captures numbered 1,967 rather than the predeclared named-cut estimand of
339. The final harness uses a process-local Git safe-directory value, selects
the global-before-POST evening panel, was rehashed, reran self-tests, and was
readmitted before the successful bounded pass. Global Git config was not
changed.

The primary verifier passes fixed-input hashes, full-POST contribution
reconciliation, every hour/named-cut Murphy identity, all 128,293 alpha
reproductions, attribution residuals, every projection score/gain identity,
and worse-case counts.

A separate standard-library implementation reread the hash-pinned vector and
bridge without importing the primary harness. It rebuilt the POST population,
Decimal floor masks, group loss ledger, projection and exact per-market PAV,
hour-20 split, alpha schedule algebra, named cuts, and resolvedness. It passes
with **zero discrepancies**. Maximum independent CORP identity residual is
`1.04e-17`; it independently confirms 11,598 projection keys, 6,946
cross-scope worsening rows, 6,877 unique partition/lane pairs, and 2,587
distinct partitions with any worsening.

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Predeclaration | 7,282 | `6ecebad0efda8cbd31a223489db60949f1c96398c2d3d59013bc257244805b71` |
| Final harness | 78,379 | `5144604823e205afd0c89f7196e8025a5f271bf0174dc704d97bed699d119e3a` |
| Analysis | 5,889,209 | `45c70f758a79e34c198a4d465d7e4ee098b5acffff55e07cdc4e13d78aa6adbc` |
| Primary verification receipt | 3,012 | `4d824c67cd2bcb179d3206aacdb4544361c1bc9ef7dfeea55e6fa1ba2684b030` |
| Independent validator | 48,161 | `5225bcc01b4a1ae08012c7f0852b3df06504dfd331b468952ae2d7fd0a6a9000` |
| Independent validation receipt | 25,369 | `a299a7f097f43498840445c23161de8493bea97ef8a8df768ae625227f9a46f3` |
| Final gate | 5,049 | `c7cefa362b3ccc3e0d2f1b95e9f3b6450d6e51ace1f1704d5df8c892df0da7bb` |
| Full alpha attribution CSV | 2,674,005 | `b7a58f8ffac5a85bb4f384564bcf4fc7068d348cec7b2ad8bf1870a4482db919` |
| Exhaustive projection-worsening CSV | 1,676,037 | `2cce97b41161aecb3a17c2e1df16cc1a6ed667398052a774857fbc543b62e47f` |
| Execution manifest | 10,289 | `678181dc7ec3461ea15fa18ebc9ac4e48ff328c41b7987cda01bd8f7f8b42b30` |

The gate is
`PASS_POST_CLEAN_GAP_LOCALIZED_AND_PROJECTION_PRICED` and grants no
downstream authority.

## Handback and next queue

- **DONE:** POST-only same-defect test, all-hour/named/resolvedness unmixing,
  construction proof, exact-alpha attribution, incumbent characterization,
  and priced per-lane projection.
- **ANSWER:** the blend cost and floor violation are the same harmful
  population-level mode; clean/no-floor blending offsets it.
- **DECISION:** the clean residual gap is overwhelmingly a genuinely
  uncertain-hours forecasting/sharpness deficit. The near-resolved evening
  deficit is an engineering blend defect.
- **NOT DONE:** no source-boundary cause hunt; no vendor or full-book read; no
  Missions 3+ of `-28c`.
- **NOT CHANGED:** `data/`, model, blend, alpha, floor order, config, artifact,
  serving, release, pointer, collector, scheduler, sizing, promotion, or
  trading state.
- **NOT APPLIED / DELETED / COMPRESSED:** any real data.

Missions 3+ of `-28c` remain queued for the next 01:00–08:30 window exactly as
requested.
