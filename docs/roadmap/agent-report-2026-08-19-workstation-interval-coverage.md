# Workstation report 2026-09-62a — interval coverage at alpha=0.0025

## Verdict

**NOMINAL `alpha=0.0025` DOES NOT MEAN 0.0025 UNIFORMLY ON THIS PANEL. THE
OUT-OF-SEASON C PRIMARY IS CALIBRATED, IN-SEASON B IS CONSERVATIVE, AND THE
THIN SEVERITY TAIL UNDER-COVERS. PROPOSE `q=3.1098893` AS A DISCLOSED
CONSERVATIVE AMENDMENT BEFORE DECISION 10; DO NOT ALTER ITS FROZEN PROTOCOL.**

The fatal positive control passed before any panel simulation ran. In the
known balanced Gaussian control at D=M=200, the point estimator is exactly
normal with known SD `0.1`. The oracle-SD interval rejected at `0.05130` and
`0.00290`; the identical 499-draw crossed-bootstrap-SD interval rejected at
`0.05205` and `0.00285`. All four rates were within the predeclared four-null-
Monte-Carlo-SE tolerance, and mean bootstrap SD was `0.0996458`, or `0.99646`
of the exact SD. The harness therefore passed its stop gate.

One first full invocation was stopped before its positive control reached the
first 2,000-replication progress mark and before any panel result existed: the
implementation was pathologically constructing 200-bin count tensors. The
successful run replaced only that control's algebra with direct uniform
cluster-index resampling. Direct indices and their multinomial counts define
the same pigeonhole draw; the frozen model, 20,000 replications, 499 draws,
seeds, thresholds, and panel implementation did not change.

On 50,000 independent true-zero panels, the required severity-tail endpoint
rejected **170 times, `0.00340`**, at nominal `0.0025`. Its 95% Wilson interval
is **[`0.002927`, `0.003950`]**, which excludes `0.0025`; Monte-Carlo SE is
`0.000260`. The restoring studentized quantile is **`3.1098893`**, versus the
current normal `3.0233414`, so the interval-SD multiplier is `1.02863`.

This is not a generic M=12 result. Out-of-season C rejected `0.00240`
[`0.002008`, `0.002869`] and is nominal; in-season B rejected zero times and is
strongly conservative. The fitted component mix differs sharply by endpoint,
and the conclusion is explicitly conditional on the real `-09-44a`
repair-minus-control field used to set those components.

The simulation spends no decision and allocates none. Campaign accounting is
unchanged at **7 of 20 spent, 13 available; decision 10 remains allocated and
unspent**. No candidate state, outcome, market probability, or repair
probability was read. The last input date is `2026-07-30`.

## Frozen design and evidence boundary

The protocol and all random seeds were committed at `9169cc26` before the
coverage pilot or full simulation:

| Item | Binding value |
| --- | --- |
| Predeclaration | `docs/roadmap/interval-coverage-predeclaration-2026-09-62a.json` |
| Predeclaration file SHA-256 | `757b17e76aadb4f34f1c796c259b7c05715fcb1ab9d351a43498a75ed653a17f` |
| Canonical-JSON SHA-256 used by outputs | `926b2aad09be0f94ec83660bb6f051acfa902706b32277f8736c63d081c212bf` |
| Master seed | `20260962` |
| Simulation script | `tools/research/interval_coverage_09_62a.py` |
| Paired input | `scratch/runs/gap-remeasure-repaired-2026-09-44a/paired-band-rows.csv` |
| Paired input SHA-256 | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` |
| Input support | 135,179 rows, 50 dates, 12 markets, through `2026-07-30` |

The reader requested only target date, stratum, market id, and the market,
control, and repair squared errors. It did not request `outcome`,
`market_probability`, or `repair_probability`. The frozen severity-tail
membership is reproduced without those columns by the binary-Brier identity

```text
abs(p_repair - p_market)
= abs(sqrt(repair_squared_error) - sqrt(market_squared_error)).
```

Together with `repair_squared_error > market_squared_error` and the frozen
30-point threshold, the identity reproduced exactly D=49, M=12, 487 occupied
cells, and 5,930 rows. The support checks also reproduced C as D=27, M=12,
320 cells, 84,183 rows and B as D=23, M=12, 204 cells, 50,996 rows.

`docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json` was not edited;
its SHA-256 remains
`336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146`.

## Method

For each endpoint, the observed paired field is

```text
repair_squared_error - control_squared_error.
```

I estimated the unbalanced additive model

```text
delta[d,m,j] = date_effect[d] + market_effect[m] + residual[d,m,j]
```

by Henderson method 3. The date and market sums of squares are the nested
least-squares reductions after the other effect; residual variance is the
full date-plus-market residual mean square. A negative raw component is
predeclared to truncate to zero. This is a method-of-moments projection of the
real field, not a guessed component split.

Each true-zero replication independently draws mean-zero Gaussian date,
market, and row-residual effects using the endpoint-specific fitted variances.
For an observed cell of size `n`, its synthetic paired-delta sum is

```text
n * (date_effect + market_effect) + sqrt(n) * residual_sd * N(0,1).
```

Thus the actual D x M occupancy, missing cells, row counts, and fixed endpoint
denominators are retained. A bootstrap draw independently resamples D dates
and M markets with replacement, multiplies their pigeonhole weights, and
recomputes the complete ratio or mean endpoint. The interval is exactly
`point +/- z(1-alpha/2) * bootstrap SD`, with `ddof=1`.

### Components taken from the observed field

| Endpoint | Component | Raw variance | Simulated SD | Variance share |
| --- | --- | ---: | ---: | ---: |
| C | date | `3.413123e-06` | `0.00184746` | 0.22724% |
| C | market | `5.961853e-07` | `0.00077213` | 0.03969% |
| C | residual | `1.497987e-03` | `0.03870384` | 99.73307% |
| Severity tail | date | `4.216880e-04` | `0.02053504` | 4.75302% |
| Severity tail | market | `1.252892e-04` | `0.01119327` | 1.41219% |
| Severity tail | residual | `8.325022e-03` | `0.09124156` | 93.83479% |
| B | date | `3.763564e-09` | `0.00006135` | 0.01070% |
| B | market | **`-8.471470e-09` raw; `0` simulated** | `0` | 0% |
| B | residual | `3.515777e-05` | `0.00592940` | 99.98930% |

The crossed bootstrap's mean SD divided by the true repeated-panel point SD
was `1.05740` for C, `1.03420` for the severity tail, and `1.54069` for B.
That last ratio explains B's conservatism; the severity tail's far-tail
studentization, rather than its mean SD alone, is the exposed case.

## Bootstrap-draw budget and interval-width stability

The predeclared pilot used 600 independent panels and nested prefixes of 499,
999, 1,999, and 3,999 draws. It selected the smallest count whose mean SD was
within 0.5% and median paired absolute SD difference within 3% of 3,999 for
all endpoints. **499 draws passed before full coverage was observed.**

| Endpoint | 499-draw mean SD difference vs 3,999 | Median paired absolute difference | 95th percentile paired difference |
| --- | ---: | ---: | ---: |
| C | 0.1860% | 1.8429% | 5.9115% |
| Severity tail | 0.1851% | 2.0555% | 6.1251% |
| B | 0.1582% | 1.9749% | 6.5777% |

Reducing bootstrap draws saved computation without reducing the number of
coverage replications. The 50,000 panel replications give an expected 125
rejections at `alpha=0.0025` under exact calibration.

## Empirical coverage

The table reports the actual two-sided rejection rate under a true-zero
effect. `q*` is the empirical quantile of `abs(point / bootstrap_sd)` that
restores the nominal rejection probability in this simulation.

| Endpoint | Nominal alpha | Rejections / 50,000 | Empirical alpha [95% Wilson] | MC SE | `q*` | `q* / z` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **C primary** | 0.05 | 2,122 | `0.04244 [0.04071, 0.04424]` | `0.000902` | `1.896560` | `0.96765` |
| **C primary** | 0.0025 | 120 | **`0.00240 [0.002008, 0.002869]`** | `0.000219` | `3.006595` | `0.99446` |
| **Severity tail** | 0.05 | 2,454 | **`0.04908 [0.04722, 0.05101]`** | `0.000966` | `1.953295` | `0.99660` |
| **Severity tail** | 0.0025 | 170 | **`0.00340 [0.002927, 0.003950]`** | `0.000260` | **`3.109889`** | **`1.02863`** |
| **B fit** | 0.05 | 173 | `0.00346 [0.002982, 0.004014]` | `0.000263` | `1.290806` | `0.65859` |
| **B fit** | 0.0025 | 0 | `0 [0, 0.0000768]` | `0` plug-in | `2.019972` | `0.66812` |

At 50,000 replications, the predeclared smallest detectable positive coverage
error at 80% power and two-sided 5% test size was:

- `0.0006486` absolute at nominal `0.0025` (0.0649 percentage points);
- `0.0027517` absolute at nominal `0.05` (0.2752 percentage points).

The severity-tail excess is `0.00090`, larger than the first threshold. This
mission therefore resolves the ledger-scale error; it is not an alpha=0.05-
only partial answer.

## Correction and consequences

The endpoint-specific result would leave C at `z=3.0233414` and use
`q=3.1098893` for the thin tail. A simpler conservative operator amendment is
to use the maximum measured restoring quantile, **`3.1098893`**, for both
required endpoints. That is a proposal, not an applied change.

MDE includes the 80%-power quantile as well as the test quantile. Therefore
the binding factor changes from

```text
(3.0233414 + 0.8416212) / (1.9599640 + 0.8416212) = 1.3796
```

to

```text
(3.1098893 + 0.8416212) / (1.9599640 + 0.8416212) = 1.4104552.
```

The correction is a `1.0223929` multiplier on the current ledger MDEs:

| Section 1d proxy endpoint | Current ledger MDE (gap share) | Corrected conservative MDE (gap share) |
| --- | ---: | ---: |
| In-season ratio | `0.004215` (0.9958%) | **`0.004309` (1.0181%)** |
| Out-of-season ratio | `0.052052` (9.5993%) | **`0.053218` (9.8143%)** |
| Severity-tail SSE | `0.020937` (4.8734%) | **`0.021406` (4.9825%)** |
| 09:00-14:00 Brier | `0.002314` (12.9265%) | **`0.002366` (13.2160%)** |

These remain planning proxies. Section 1d's rule that each candidate must use
its own effect field is unchanged.

The unadjusted 12-market asymptotic floor remains about `0.0173` ratio points,
or 3.2% of the out-of-season gap. Under the old ledger multiplier it was
4.414601%; under the conservative correction it becomes **4.513457%**, about
`0.02441` ratio points using the `0.0173087` asymptote.

The programme-level conclusions survive:

- **The practical >=5% step size survives, narrowly:** 5% remains above the
  corrected 4.51% campaign floor.
- **The 2026-10-16 D=73 confirmation date survives unchanged.** That schedule
  is an alpha=0.05 one-off confirmation curve, and neither C nor the severity
  tail under-covered at 0.05. This mission supplies no basis to widen its
  `z=1.959964` critical value.
- **Decision 10's 10%-of-gap power gate still admits its declared plausible
  coherent effect.** Applying the conservative factor moves the `a=b=c=0.05`
  P0 MDE from 6.790047% to **6.942096%** of `G`, still below 10%. The boundary
  tightens from `a=b=c <= 0.0736372` to approximately **`0.0720244`**; the
  `0.075` case remains invisible (10.413145%). Candidate-native MDE remains
  binding when decision 10 is eventually executed.

The operator should either (a) disclose and hash an amendment using
`q=3.1098893` for the tail, or (b) conservatively use that quantile for both
required endpoints. Until then, `-09-61a` remains byte-for-byte frozen and
the report does not pretend the amendment has been applied.

## Reproduction and retained outputs

Run from the production repository root with the bundled Codex 3.12 runtime;
install nothing:

```powershell
& 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  tools\research\interval_coverage_09_62a.py validate
& 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  tools\research\interval_coverage_09_62a.py pilot
& 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  tools\research\interval_coverage_09_62a.py full
```

Scratch evidence:

| Output | SHA-256 |
| --- | --- |
| `validation.json` | `56286eee7d18db1640f2beef2e7cbaf1fabb119fb002cd688a9cf6b91c5b0c3f` |
| `pilot.json` | `3171c87b60d772ef33ace59068027a1ea3b72a4e3b4829c55068d98fbab40df1` |
| `positive-control.json` | `2786d17ffe85771be4218dc742307dab8440b6956bad549c14e256c7c0ebb349` |
| `coverage.json` | `7baaef64b3e9312aecf07f9d2fcb5c71edbad3e82d8692723454ae7b2e9bacab` |

All four are under
`scratch/runs/interval-coverage-2026-09-62a/`. Scratch is local retained
evidence, not assumed to exist in a clean checkout; the committed script,
protocol, seeds, support checks, and input hash make it reproducible where the
retained `-09-44a` field exists.

## Safety and accounting

- No post-`2026-07-30` row was read or pooled.
- No C outcome or probability column was read.
- No candidate, provider, exchange, production `data/`, chain, settlement,
  serving-floor, promotion, activation, or trading state was touched.
- The PIT fields remain own-information under section 0c; this mission did not
  consume any benchmark as a feature.
- No alpha was spent and none was allocated: **7 of 20 spent, 13 available**.
- Decision 10 remains **allocated and unspent**.
- The frozen `-09-61a` protocol was not edited.
