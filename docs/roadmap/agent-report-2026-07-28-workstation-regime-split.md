# Agent report - 2026-07-28 workstation regime split

Status: **THE POOLED BLEND REFUTATION DOES NOT SURVIVE THE
POST-BOUNDARY REGIME. THE MODEL-MARKET GAP REMAINS POSITIVE BUT CHANGES
MATERIALLY IN SIZE AND IN THE PREDECLARED SHAPE METRIC.
`NOT_ACCOUNTED_FOR` SURVIVES.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28f-does-the-week-survive-the-regime-split.md`
from exact `origin/master`
`9ad438a24de6a6675c798f6d81258d74806f2729`, merged into topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Reduced populations first

No stored-null or collision observation was filtered from the binary score.
The two frozen collision keys contribute 22 rows and two physical captures
each; one is PRE and one is POST.

| Population basis | PRE | POST | Total |
| :--- | ---: | ---: | ---: |
| Composite snapshot keys | **7,131** | **11,662** | 18,793 |
| Binary band rows | **78,452** | **128,293** | 206,745 |
| Valid noncollision simplexes | 7,130 | 11,661 | 18,791 |
| Valid-simplex rows | 78,430 | 128,271 | 206,701 |
| Physical capture groups | 7,132 | 11,663 | 18,795 |
| Global earliest hour representatives | 1,107 | 1,855 | 2,962 |

The regime label comes only from captured runtime ancestry. PRE means a
runtime ancestor of or equal to `4085a8fb6813`; POST means a runtime
descendant of or equal to `89f3b908a245`. The strictly intermediate
`aea4919c92d5` would have stopped the run, but was not present. All 22 observed
runtime commits reproduced their closed-world counts. Capture time was only a
cross-check: the last PRE capture is the frozen Dallas anchor at
`2026-07-02T17:56:46.255747-04:00`, and the first POST capture is the frozen
Houston anchor at `2026-07-02T18:14:19.095727-04:00`.

The bridge states also reproduced exactly:

| State | PRE | POST |
| :--- | ---: | ---: |
| Stored null, reconstructed numeric | 7,091 | 0 |
| Numeric exact | 0 | 11,601 |
| Both null | 40 | 61 |
| Numeric disagreement | 0 | 0 |

This is a regime label, not evidence that the predictor consumed the
persisted values.

## Direct answers

### 1. Replay-final does not still beat preblend

The direction reverses:

| Regime | Preblend Brier | Replay-final Brier | Preblend minus final | Verdict |
| :--- | ---: | ---: | ---: | :--- |
| PRE | 0.095099 | 0.082012 | **+0.013087** | Replay-final better |
| POST | **0.047572** | 0.049853 | **-0.002281** | Preblend better |

Positive exchange means replay-final improved on preblend. The PRE gain is
13.76% of preblend Brier; the POST result is 4.80% worse. Categorical Brier
agrees with the reversal: replay-final moves from 1.046030 to 0.902078 in PRE,
but from 0.523248 to 0.548334 in POST.

Under the handoff's explicit criterion, the pooled blend refutation was an
artifact of mixing the regimes. It is not a valid post-boundary conclusion.

### 2. The model-market gap remains, but not at the same size or shape

Raw market still has the lower binary Brier on both sides:

| Regime | Replay-final | Raw market | Final minus market | Reliability component | Resolution component |
| :--- | ---: | ---: | ---: | ---: | ---: |
| PRE | 0.082012 | 0.035878 | **0.046133** | 0.008756 | 0.037377 |
| POST | 0.049853 | 0.038280 | **0.011573** | 0.000322 | 0.011251 |

The gap shrinks by **0.034560 Brier points, or 74.91%**. That crosses both
predeclared materiality thresholds: 0.005 absolute and 20% relative.

The predeclared shape metric,
`RES_final / UNC - RES_market / UNC`, moves from **-45.23 percentage points**
in PRE to **-13.61 points** in POST, a **31.61-point** change. That crosses the
10-point shape threshold. Its sign does not flip: market retains greater
resolution.

The broad decomposition description remains resolution-dominated, despite the
material shape movement. Resolution supplies 81.02% of the PRE final-market
gap and 97.22% of the POST gap. Thus the honest answer is: **the market
advantage survives directionally, but neither its magnitude nor the frozen
shape metric is unchanged.**

The companion preblend-market gap also contracts, from 0.059221 PRE to
0.009292 POST. Its pairwise resolution-share gap moves from -48.87 to -12.69
percentage points, a material 36.17-point change without a sign flip.

### 3. Recorded still matches no alternative whole partition

Against preblend, replay-final, incumbent, and raw market, strict Decimal
whole-partition matches are zero in both regimes and on both partition bases.

| Regime / basis | Denominator | Preblend | Replay-final | Incumbent | Raw market | Recorded self |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| PRE valid composite | 7,130 | 0 | 0 | 0 | 0 | 7,130 |
| PRE physical capture | 7,132 | 0 | 0 | 0 | 0 | 7,132 |
| POST valid composite | 11,661 | 0 | 0 | 0 | 0 | 11,661 |
| POST physical capture | 11,663 | 0 | 0 | 0 | 0 | 11,663 |

At `1e-12` whole-partition tolerance, incumbent has one match in PRE and one
in POST on each basis; every other alternative still has zero. Those
tolerance matches are disclosed diagnostics, not strict identity.

On the collision-aware physical-row basis, the row results are:

| Regime | Comparator | Exact rows | Rows within `1e-12` | Comparable rows | Mean absolute delta |
| :--- | :--- | ---: | ---: | ---: | ---: |
| PRE | Preblend | 0 | 205 | 78,452 | 0.088914 |
| PRE | Replay-final | 0 | 184 | 78,452 | 0.059185 |
| PRE | Incumbent | 4,162 | 4,400 | 78,452 | 0.051019 |
| PRE | Raw market | 0 | 0 | 78,452 | 0.100782 |
| POST | Preblend | 0 | 536 | 128,293 | 0.072224 |
| POST | Replay-final | 0 | 584 | 128,293 | 0.035051 |
| POST | Incumbent | 4,953 | 6,006 | 128,293 | 0.013267 |
| POST | Raw market | 0 | 0 | 128,293 | 0.076310 |

Recorded self-control is exact on every row and every partition. Therefore
`NOT_ACCOUNTED_FOR_BY_PREDECLARED_EVALUABLE_FUNCTIONS` is robust to the
regime split, and the stronger zero-strict-whole-partition-match statement
also survives.

## Five-lane Murphy decompositions

All entries are pooled binary band-row units. Each row satisfies
`BS = REL - RES + UNC`; the maximum absolute identity residual is
`1.39e-17`.

| Regime | Lane | BS | REL | RES | UNC |
| :--- | :--- | ---: | ---: | ---: | ---: |
| PRE | Preblend | 0.095099 | 0.024645 | 0.012191 | 0.082645 |
| PRE | Replay-final | 0.082012 | 0.014566 | 0.015199 | 0.082645 |
| PRE | Incumbent | 0.081115 | 0.015008 | 0.016538 | 0.082645 |
| PRE | Recorded | 0.088757 | 0.019772 | 0.013660 | 0.082645 |
| PRE | Raw market | **0.035878** | 0.005810 | **0.052576** | 0.082645 |
| POST | Preblend | **0.047572** | **0.003902** | **0.038974** | 0.082645 |
| POST | Replay-final | 0.049853 | 0.005423 | 0.038214 | 0.082645 |
| POST | Incumbent | 0.063703 | 0.005961 | 0.024902 | 0.082645 |
| POST | Recorded | 0.064483 | 0.006112 | 0.024273 | 0.082645 |
| POST | Raw market | **0.038280** | 0.005101 | **0.049466** | 0.082645 |

The weighted PRE/POST scores reproduce every accepted pooled five-lane Brier
score at absolute tolerance `1e-12`.

## Named market-local hour cuts

The earliest representative was selected globally for each
`(market, target date, market-local hour)` before attaching the regime. No
later within-regime replacement was made.

| Cut | PRE / POST keys | PRE gain | POST gain | PRE final-market gap | POST final-market gap |
| :--- | :---: | ---: | ---: | ---: | ---: |
| Predawn 03-05 | 132 / 222 | +0.001358 | +0.001041 | 0.022856 | 0.012479 |
| Primary 09-14 | 327 / 444 | +0.006258 | +0.002530 | 0.021573 | 0.011929 |
| Evening 20-23 | 142 / 339 | **+0.049511** | **-0.011170** | 0.127176 | 0.011192 |

The corresponding row counts are 1,452/2,442, 3,597/4,884, and
1,562/3,729. Predawn and primary retain a smaller replay-final advantage on
both sides. Evening reverses sharply: PRE favors replay-final, while POST
favors preblend. The same evening reversal appears in categorical Brier:

| Regime | Preblend | Replay-final | Raw market | Incumbent | Recorded |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Evening PRE | 1.943569 | 1.398948 | 0.000007 | 1.278970 | 1.419616 |
| Evening POST | **0.000258** | 0.123123 | 0.000007 | 0.482913 | 0.448451 |

This localizes where the named-cut sign change is visible; it does not
identify the boundary's cause.

## Validation and authority

The final gate is `PASS_REGIME_SPLIT_HEADLINES_REMEASURED`. It binds:

- analysis JSON SHA-256
  `9ca018427e8a33703fe3152ec8165e5800b1a6d6e8426012ca44dde941e265ab`;
- receipt SHA-256
  `723b1a2d625b742625e5c84d3aabbd1c05e2a427a7065e716d0c3aa600ac8872`;
- frozen harness SHA-256
  `9a5689d237687c7ba11e779f35a284d1ea7665e7a2b427e4e9b477c8cfca7aac`;
- exact input hashes before and after scoring;
- the 18,793-key bridge join, all population/collision additivity, accepted
  pooled and named-cut reproduction, five-lane Murphy identities, Decimal
  agreement controls, and recorded self-controls.

The ignored evidence packet is under
`scratch/workstation-research-output/regime-split-20260728f-9ad438a2/`.
`data/` was not read or written. No model, blend, serving, configuration,
release, promotion, trading, deletion, or compression action was performed.
The boundary diff was not inspected.

Persisted feature evidence still does not prove serving-side predictor
consumption. Replay-final remains a retrospective hypothetical lane, recorded
remains a provenance control, and raw `market_yes` is not an executable CLOB
price.

Because the split changes the blend conclusion and materially changes the
model-market comparison, `-27g` Missions 2 and 3 remain queued and should be
restricted to the POST regime when resumed. They were not run here.
