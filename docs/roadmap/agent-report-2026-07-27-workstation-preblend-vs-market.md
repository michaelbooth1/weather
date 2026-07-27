# Agent report - 2026-07-27 workstation preblend versus market

Status: **MISSION 0 COMPLETE; MISSION 1 COMPLETE;
REPLAY-FINAL BEATS PREBLEND; WHOLESALE DISABLE NOT SUPPORTED; NO BLEND,
MODEL, SERVING, OR AUTHORITY CHANGE.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28d-preblend-vs-market.md`
from exact `origin/master`
`b1b6780ab75a1ca5533090b257749d6545b36f8c` on topic branch
`codex/workstation-preblend-vs-market-2026-07-28d`.

The information and scoring contract was frozen before any score was
calculated in
`scratch/workstation-research-output/preblend-vs-market-20260728d/predeclaration.md`,
SHA-256
`9e6b07311bb018a668b46cb28b95e48de0e2fae3260387cfda2d7169bedc355d`.

## Executive verdict

**The frozen corpus rejects the hypothesis that the reconstructed replay blend
manufactured the measured resolution deficit.** The replay-final candidate
beats preblend:

- in aggregate over all 206,745 accepted band rows;
- in aggregate over all 18,791 valid categorical partitions;
- in predawn 03-05, primary 09-14, and evening 20-23;
- in 20 of 24 individual hours against outcomes; and
- in 21 of 24 individual hours against the normalized market distribution.

The replay-final result is less sharp overall, but it is not merely better
calibrated. In both decomposition lanes it has **lower reliability error and
slightly higher resolution** than preblend.

| Question | Answer |
| :--- | :--- |
| Does preblend recover resolution that replay-final loses? | **No.** In the accepted binary CORP decomposition, replay-final resolution is `0.0249583` versus preblend `0.0246567`; in the market-soft categorical decomposition it is `0.253400` versus `0.249031`. |
| What does the blend cost in reliability? | It does not cost reliability on this corpus. Replay-final reliability error is lower: `0.00436974` versus `0.00761880` against outcomes, and `0.0306404` versus `0.0756399` against the soft market target. |
| Does preblend beat replay-final in the uncertain named windows? | **No.** Replay-final categorical Brier is lower by `0.012755` predawn, `0.045220` primary, and `0.074189` evening. |
| Where does preblend help? | Realized categorical Brier is lower only at hours 03, 15, 16, and 17. The market-soft score favors preblend only at 15, 16, and 17. |
| What is the hour-20 86/38 exchange? | The 86 aligned cases incur `+9.86869` aggregate categorical harm from final, while the 38 above-floor cases receive `20.18906` aggregate rescue. Harm/rescue is `0.488814`; replay-final wins the combined population by `0.0832288` categorical Brier per partition. |
| Does constant-alpha sensitivity authorize a config change? | **No.** Same-corpus realized Brier has a shallow minimum at `alpha=0.60`, only `0.002976` below stored replay-final. Stored replay-final is `0.000506` better than every constant alpha on the market-soft score. This is descriptive, not selected or forward-validated. |
| Is the system proven to have served replay-final? | **No.** The frozen replay has an empty active-registry contract and blocked-validation verdict `BLOCK`. `probability` is replay-final reconstruction; `recorded_probability` is the historical-output control. |
| Did failed source freshness collapse alpha to zero? | **No evidence of that mechanism in this artifact.** The source-state alpha map is empty, its artifact default is `null`, and dynamic source state is disabled. |

Decision rubric result:
**`FORECAST_LIMIT_DOMINATED_REPLAY_DIAGNOSIS /
WHOLESALE_DISABLE_NOT_SUPPORTED / NO_GLOBAL_ALPHA_DECISION`.**
Do not disable the blend on this evidence. The remaining replay-final-to-market
gap is resolution-dominated on this frozen panel. This does not prove that the
gap is structural or irreducible, nor does it prove future usefulness, active
serving, or optimal configuration.

## Mission 0 - the held branch is green

Mission 0 was completed first on
`codex/workstation-mm-measurable-2026-07-27c`.
Commit
`c6319fa12788ab68fd83154205185ae3def695fc`
(`Green MM ownership and schema ratchets`) is pushed at the same remote topic
branch identity.

It greens the three ratchets introduced by the measurable-MM work:

1. registers `mm_execution_evidence_v0.1`;
2. excludes the `mm_execution_v2` identity-algorithm domain separator from
   durable-schema interpretation; and
3. updates the module-size audit and ownership map for the enlarged
   `mm_paper_scoring` owner.

The commit changes only the registry/ratchet ownership files and their tests.
It does not change execution admission, paper scoring, live policy, or serving.

## Critical provenance correction

The handoff asked whether "we are serving a worse model than we built." The
available evidence can answer the replay comparison, but not that active
serving claim.

| Frozen field | Meaning in this report |
| :--- | :--- |
| `candidate_preblend_probability` | Candidate after its upstream postprocessing and partition normalization, captured before `current_blend` |
| `probability` | Reconstructed candidate **replay-final** after artifact-configured blend and cleanup |
| `current_probability` | Incumbent input to the reconstructed blend |
| `recorded_probability` | Historically recorded output control |
| `market_yes` | Raw Gamma market probability proxy; not executable CLOB pricing |
| `outcome` | Settled one-hot band label |

The exact pooled report has:

- `active_registry_contract = {}`;
- blocked-validation verdict `BLOCK`;
- no demonstrated active-serving binding.

Accordingly, this report uses **preblend**, **replay-final**, and
**historically recorded output** throughout. It does not call the replay-final
vector "served final."

The accepted prior
[simplex-authorization report](agent-report-2026-07-25-workstation-simplex-authorization.md#production-truth-latent-live-defect-active-replay-defect)
found `current_blend_enabled` effectively off in recorded live serving while
pooled artifacts bake it on. This workstation audit does not rederive that
host observation. Together, the evidence says the replay policy can be
diagnosed, but does not show that production was serving it.

The handoff's proposed source-freshness explanation is also not active in the
hash-pinned artifact:

- `current_blend_source_freshness_alpha = {}`;
- `current_blend_source_freshness_default_alpha = null`;
- `dynamic_source_state_enabled = false`.

The artifact instead has candidate default alpha `1.0`, an eight-market alpha
map, and ordered context rules at `0.35` or `0.50`. Alpha is candidate weight.
Failed `weather_forecast` / `wu_current` / `wu_history` states can be associated
with rows in this retrospective corpus, but they did not execute the proposed
default-zero source-state cap.

Finally, alpha is applied per band and ordered context rules can override
different bands differently. Stored replay-final is therefore a heterogeneous
row/band policy, not a constant `alpha=0.50` point.

## Frozen population and time contract

The standalone harness validated:

| Scope | Count |
| :--- | ---: |
| Band rows | 206,745 |
| Composite `(market, target date, snapshot)` keys | 18,793 |
| Valid 11-band simplex partitions | 18,791 |
| Valid simplex rows | 206,701 |
| Validated same-second collision keys / rows | 2 / 44 |
| US Fahrenheit markets | 11 |
| Market-days | 129 |
| Target dates | 12 |
| Earliest target-day market-local hour representatives | 2,962 |
| Predawn 03-05 partitions / rows | 354 / 3,894 |
| Primary 09-14 partitions / rows | 771 / 8,481 |
| Evening 20-23 partitions / rows | 481 / 5,291 |
| Hour-20 exact-joined partitions / rows | 124 / 1,364 |

The two collision keys are:

- `austin|2026-07-03|20260703T093322-0400`;
- `dallas|2026-06-30|20260701T002709-0400`.

Each contains two identical 11-band captures normalized jointly. All 44 rows
remain in the accepted binary CORP bridge. Metrics requiring one categorical
simplex exclude the two keys. Full-population hour selection happens before
exclusion and an excluded key is never replaced. Neither collision is the
earliest representative in its market/date/hour, so the earliest-hour and
named slices require no collision exclusion.

The encoded `captured_at_local` timestamp is treated as an instant and
converted through the exact market timezone in hash-pinned
`config/locations.json`. This conversion is material:

- reading the encoded ET clock directly yields only 2,800 target-date cells;
- market-local conversion yields the frozen 2,962;
- it reproduces 8,481 primary rows and the independent 124/1,364 hour-20
  population exactly.

The model-routing `cutoff_hour` field is not used as the analysis clock.

## Leakage and identity gates

The score was allowed only after all of the following passed:

- frozen vector, corpus, cohort, generator, pooled report, model artifact,
  accepted skill-gap output, hour-20 evidence, location registry, and relevant
  source-code hashes;
- identical pinned-input identities before and after scoring;
- exact row schema, variant, control, weather-only claim lane, artifact,
  postprocess schema, attribution schema, feature schema, target-date panel,
  native Fahrenheit family, market-day signatures, probability range, mass,
  and one-hot outcomes;
- preblend capture before the blend call in exact source;
- prediction-boundary settlement-label removal before deferred label join;
- artifact feature contracts containing neither `outcome` nor `market_yes`;
- artifact training maximum date `2025-07-14`, while evaluation begins
  `2026-06-28`;
- hash-pinned blocked-validation split audits with zero leakage;
- exact 86/38 independent hour-20 join;
- decomposition identities and alpha endpoints.

The runtime-focused test proves that the day scorer hides settlement until
after band prediction. A separate replay-parity test passes on the exact base.
The wider focused verification passed 51 tests plus six subtests across:

- skill-gap decomposition and market-local hour selection;
- current-blend validation and replay parity;
- `current_blend` model behavior; and
- bounded pooled-candidate replay and label hiding.

One residual limitation remains explicit: the exported CSV co-locates outcome
and forecast fields, and this queue did not authorize an exact full-corpus
label-perturbation replay. The exact artifact feature contract, source order,
zero-leak receipts, and focused runtime tests are strong evidence, but they are
not a complete dynamic call-graph proof for every one of the 206,745 rows.

## Method and units

Two scoring lanes remain separate.

### Realized-outcome lane

For valid partitions, categorical Brier is:

`sum_i (p_i - y_i)^2`

over the eleven mutually exclusive bands. The accepted bridge flattens every
band row, includes the 44 collision rows, and reports binary-band mean Brier.
Exact isotonic/PAV CORP components are computed within market and row-weighted
across markets:

`BS = REL - RES + UNC`.

Every market contributes one positive outcome among eleven bands per valid
partition, so binary uncertainty is `10/121 = 0.0826446`.

### Market-soft lane

Raw Gamma probabilities are normalized only for this lane:

`q_i = market_yes_i / sum_j market_yes_j`.

The expected categorical Brier of forecast `p` under soft market target `q`
is:

`||p-q||^2 + 1 - ||q||^2`.

PAV is fitted to flattened band components separately by market and every
binary component is multiplied by eleven, retaining categorical units.
Uncertainty is `10/11 = 0.909091`. Raw market probabilities remain raw in the
realized benchmark; normalization is not retroactively substituted there.

This follows the exact isotonic/CORP reliability-resolution-uncertainty
construction described in
[Dimitriadis, Gneiting, and Jordan](https://arxiv.org/abs/2008.03033).

## Pooled outcome result

Lower scores are better.

| Forecast | Rows | Binary Brier | Reliability | Resolution | Uncertainty |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Preblend | 206,745 | 0.065607 | 0.007619 | 0.024657 | 0.082645 |
| Replay-final | 206,745 | **0.062056** | **0.004370** | **0.024958** | 0.082645 |
| Raw market | 206,745 | **0.037369** | 0.004092 | 0.049368 | 0.082645 |
| Incumbent | 206,745 | 0.070310 | 0.006329 | 0.018663 | 0.082645 |
| Recorded output | 206,745 | 0.073694 | 0.007778 | 0.016728 | 0.082645 |

Replay-final improves binary Brier over preblend by `0.00355064`, or 5.41%.
The identity is:

- reliability-error reduction: `0.00324906`;
- resolution increase: `0.000301575`;
- total improvement: `0.00355064`;
- identity residual: below `7e-18`.

The raw market remains materially better. Preblend's gap to market is
`0.0282381`; replay-final's is `0.0246875`. Replay-final closes 12.57% of the
preblend-market gap but does not approach parity.

On categorical partition units, the same conclusion is:

| Forecast | Categorical Brier |
| :--- | ---: |
| Preblend | 0.721610 |
| Replay-final | **0.682558** |
| Raw market | **0.411113** |
| Normalized market | 0.410128 |
| Incumbent | 0.773332 |
| Recorded output | 0.810483 |

## Pooled market-soft result

| Forecast | Expected Brier | Reliability | Resolution | Uncertainty | Quadratic regret to market |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Preblend | 0.735700 | 0.075640 | 0.249031 | 0.909091 | 0.313539 |
| Replay-final | **0.686331** | **0.030640** | **0.253400** | 0.909091 | **0.264171** |
| Market `q` | **0.422161** | 0.000000 | 0.486930 | 0.909091 | 0.000000 |

Replay-final improves expected Brier by `0.0493683`, or 6.71%, and reduces
quadratic distance to the market by 15.75%. The decomposition says why:

- reliability error falls by `0.0449995`;
- resolution rises by `0.00436882`;
- their sum is the `0.0493683` improvement.

Preblend therefore does not recover hidden resolution in either scoring lane.
It loses both reliability and resolution.

## Sharpness

| Forecast | Effective bands, mean | Top probability, mean |
| :--- | ---: | ---: |
| Preblend | 3.4674 | 0.5903 |
| Replay-final | 3.9427 | 0.5242 |
| Normalized market | **2.6465** | **0.6680** |

Replay-final is less sharp than preblend in the pooled panel, as expected from
a hedge. The scoring decompositions show that the lost concentration is not
lost useful resolution on this corpus. The market remains both sharper and
substantially more resolved.

Sharpness is context-dependent. In primary 09-14, replay-final is actually
sharper by effective-band count (`4.4138` versus `4.6892`) and has a higher
mean top probability (`0.4388` versus `0.4026`). This is consistent with a
heterogeneous per-band replay policy, not a single convex mixture.

## Named hour cuts

### Scores

| Cut | Partitions | Preblend categorical BS | Replay-final categorical BS | Raw-market categorical BS | Final minus preblend | Preblend market-soft BS | Replay-final market-soft BS |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Predawn 03-05 | 354 | 0.839308 | **0.826553** | **0.646719** | -0.012755 | 0.844822 | **0.808540** |
| Primary 09-14 | 771 | 0.780792 | **0.735572** | **0.559357** | -0.045220 | 0.797431 | **0.742905** |
| Evening 20-23 | 481 | 0.573959 | **0.499770** | **0.000007** | -0.074189 | 0.581436 | **0.505261** |

The categorical replay-final gain is 1.52% predawn, 5.79% primary, and 12.93%
evening. The blend is not merely protecting an obscure tail: it improves all
three requested cuts.

### Market-soft decomposition

| Cut | Preblend REL | Final REL | Preblend RES | Final RES | Preblend effective bands / top p | Final effective bands / top p |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Predawn 03-05 | 0.084614 | **0.050226** | 0.148883 | **0.150777** | 4.8093 / 0.3838 | 5.0428 / 0.3982 |
| Primary 09-14 | 0.055791 | **0.030749** | 0.167451 | **0.196935** | 4.6892 / 0.4026 | 4.4138 / 0.4388 |
| Evening 20-23 | 0.147285 | **0.121953** | 0.474940 | **0.525783** | 1.0443 / 0.9935 | 2.5871 / 0.7238 |

Replay-final has both lower reliability error and higher resolution in every
named cut.

## All 24 market-local hours

`Delta cat` and `delta soft` are replay-final minus preblend; negative favors
replay-final.

| Hour | Partitions | Preblend cat BS | Replay-final cat BS | Raw market cat BS | Delta cat | Delta soft |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00 | 118 | 0.795435 | 0.771587 | 0.660036 | -0.023849 | -0.022209 |
| 01 | 118 | 0.795035 | 0.773823 | 0.668225 | -0.021212 | -0.018847 |
| 02 | 118 | 0.814798 | 0.811514 | 0.656575 | -0.003284 | -0.025309 |
| 03 | 118 | 0.818161 | 0.827074 | 0.654585 | +0.008913 | -0.021531 |
| 04 | 118 | 0.847549 | 0.819328 | 0.645419 | -0.028221 | -0.039452 |
| 05 | 118 | 0.852214 | 0.833256 | 0.640153 | -0.018957 | -0.047863 |
| 06 | 118 | 0.861303 | 0.820503 | 0.643048 | -0.040800 | -0.053154 |
| 07 | 121 | 0.848761 | 0.813175 | 0.646993 | -0.035586 | -0.053672 |
| 08 | 122 | 0.842750 | 0.806286 | 0.634992 | -0.036464 | -0.045470 |
| 09 | 126 | 0.837289 | 0.803498 | 0.613418 | -0.033791 | -0.058557 |
| 10 | 129 | 0.856345 | 0.806858 | 0.610202 | -0.049487 | -0.049446 |
| 11 | 129 | 0.811552 | 0.778956 | 0.596145 | -0.032597 | -0.049659 |
| 12 | 129 | 0.798756 | 0.739971 | 0.570660 | -0.058785 | -0.058693 |
| 13 | 129 | 0.769421 | 0.699072 | 0.511084 | -0.070350 | -0.078209 |
| 14 | 129 | 0.612704 | 0.586660 | 0.455892 | -0.026044 | -0.032688 |
| 15 | 129 | 0.487113 | **0.507948** | 0.320121 | +0.020835 | +0.026945 |
| 16 | 129 | 0.367245 | **0.416654** | 0.179437 | +0.049409 | +0.006606 |
| 17 | 129 | 0.404848 | **0.436092** | 0.073472 | +0.031244 | +0.009403 |
| 18 | 128 | 0.484311 | 0.452317 | 0.010643 | -0.031994 | -0.045228 |
| 19 | 126 | 0.587300 | 0.513511 | 0.000763 | -0.073788 | -0.078065 |
| 20 | 124 | 0.613220 | 0.529991 | 0.000012 | -0.083229 | -0.085193 |
| 21 | 121 | 0.578687 | 0.515771 | 0.000006 | -0.062916 | -0.064989 |
| 22 | 118 | 0.542440 | 0.475494 | 0.000004 | -0.066946 | -0.068962 |
| 23 | 118 | 0.559374 | 0.475880 | 0.000004 | -0.083494 | -0.085379 |

Hour 03 is the only realized outcome exception before 15:00, and its
market-soft result still favors replay-final. The coherent preblend-favored
window is 15-17. That local exception does not overturn the pooled or named-cut
result and has no ex-ante alpha-selection authority.

## Hour-20 86/38 exchange

Positive delta means replay-final harms Brier relative to preblend; negative
means replay-final rescues it.

| Population | Partitions | Preblend categorical BS | Replay-final categorical BS | Mean categorical delta | Mean band-row delta | Aggregate delta |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Floor-aligned | 86 | 0.000499 | 0.115252 | **+0.114752** | +0.010432 | +9.868688 |
| Above-floor | 38 | 1.999905 | 1.468614 | **-0.531291** | -0.048299 | -20.189058 |
| Combined | 124 | 0.613220 | **0.529991** | **-0.083229** | -0.007566 | -10.320370 |

The aggregate aligned-harm / above-floor-rescue ratio is `0.488814`; the
rescues are 2.046 times the harm. On a per-partition basis the ratio is
`0.215987`; one above-floor rescue is 4.630 times one aligned harm.

This separates two conclusions that must not be conflated:

1. replay-final is the better Brier hedge across these 124 cases; and
2. the accepted prior audit's impossible-mass/floor correctness problem
   remains a separate physical invariant defect.

A scoring hedge does not make impossible mass correct, and the physical defect
does not erase the hedge's measured score benefit.

The 86/38 split is outcome-defined. It has zero ex-ante gating or alpha
selection authority.

## Constant-alpha sensitivity

The sensitivity uses:

`p(alpha) = normalize(alpha * preblend + (1-alpha) * incumbent)`.

Thus `alpha=1` is preblend and `alpha=0` is incumbent. This endpoint-preserving
curve is separate from a serving-floor sensitivity that applies
`max(1e-12, u_i)` before normalization. Mean floor drift is below `4.4e-12`
at every endpoint and below `1.1e-12` elsewhere; it does not drive the result.

| Alpha | Realized categorical BS | Market-soft expected BS | Effective bands | Mean top p | Mean floor L1 drift |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.00 | 0.773332 | 0.770845 | 3.7366 | 0.5365 | 1.03e-12 |
| 0.05 | 0.758333 | 0.756674 | 3.8135 | 0.5305 | 5.68e-14 |
| 0.10 | 0.744641 | 0.743811 | 3.8712 | 0.5250 | 5.77e-14 |
| 0.15 | 0.732255 | 0.732254 | 3.9167 | 0.5200 | 5.87e-14 |
| 0.20 | 0.721176 | 0.722004 | 3.9518 | 0.5161 | 5.98e-14 |
| 0.25 | 0.711403 | 0.713060 | 3.9777 | 0.5135 | 6.10e-14 |
| 0.30 | 0.702938 | 0.705423 | 3.9951 | 0.5117 | 6.24e-14 |
| 0.35 | 0.695778 | 0.699093 | 4.0045 | 0.5110 | 6.39e-14 |
| 0.40 | 0.689926 | 0.694069 | 4.0062 | 0.5114 | 6.56e-14 |
| 0.45 | 0.685380 | 0.690352 | 4.0006 | 0.5134 | 6.72e-14 |
| 0.50 | 0.682140 | 0.687941 | 3.9879 | 0.5166 | 6.89e-14 |
| 0.55 | 0.680207 | **0.686837** | 3.9684 | 0.5204 | 7.08e-14 |
| 0.60 | **0.679581** | 0.687040 | 3.9422 | 0.5251 | 7.28e-14 |
| 0.65 | 0.680262 | 0.688549 | 3.9094 | 0.5305 | 7.54e-14 |
| 0.70 | 0.682249 | 0.691365 | 3.8699 | 0.5369 | 7.82e-14 |
| 0.75 | 0.685543 | 0.695488 | 3.8239 | 0.5439 | 8.18e-14 |
| 0.80 | 0.690143 | 0.700917 | 3.7709 | 0.5517 | 8.63e-14 |
| 0.85 | 0.696050 | 0.707653 | 3.7107 | 0.5602 | 9.25e-14 |
| 0.90 | 0.703263 | 0.715695 | 3.6425 | 0.5695 | 1.02e-13 |
| 0.95 | 0.711784 | 0.725044 | 3.5642 | 0.5796 | 1.21e-13 |
| 1.00 | 0.721610 | 0.735700 | 3.4674 | 0.5903 | 4.37e-12 |

Stored replay-final is a separate heterogeneous point:

| Result | Realized categorical BS | Market-soft expected BS | Effective bands | Mean top p |
| :--- | ---: | ---: | ---: | ---: |
| Stored replay-final | 0.682558 | **0.686331** | 3.9427 | 0.5242 |

The same-corpus realized minimum at `0.60` is only `0.002976` below stored
replay-final, and uniform `0.50` is only `0.000417` below it. Conversely,
stored replay-final beats the best constant-alpha market-soft score by
`0.000506`. The realized curve has a broad `0.50-0.65` basin.

This is not a configuration finding that warrants deployment:

- the minimum was observed on the evaluation corpus itself;
- no selection/confirmation split was predeclared;
- stored replay-final is not one scalar alpha;
- the objective changes which point wins; and
- active-serving binding is absent.

The defensible conclusion is only that the reconstructed policy sits near a
broad realized optimum and is at least as defensible as any constant alpha on
the market-soft objective.

## Host admission and containment

The successful run began during the moderate, non-protected host window. Fresh
admission at 16:21 ET measured:

| Gate | Result |
| :--- | ---: |
| Commit | 49.64% (`<70%`) |
| Free physical memory | 9.13 GiB |
| Free `C:` disk | 55.64 GiB (`>=50 GiB`) |
| Training / mirror / relevant audit processes | 0 |
| `WeatherTrainingWindow` / `WeatherDataMirror` matching task state | none returned |
| Protected window | false |

The `data\` ACL explicitly denied
`DeleteSubdirectoriesAndFiles, Write, Delete` to both the operator and offline
sandbox identities. The audit read no analytic input from `data\` and wrote
nothing below it. It made no network request and wrote only beneath the single
declared output root.

The repository's normal `venv` points to a removed Python 3.11 executable.
The audit used the already-accepted isolated Python 3.12.13 environment from
the measurable-MM queue. Every focused-test subprocess removed that
environment's `.pth` reference to the MM worktree, inserted the exact
`b1b6780a` source root first, imported `weather` from that root, and asserted
the resolved path before tests ran.

## Pre-score fail-closed corrections

No score was calculated until the final successful run. Earlier starts stopped
inside metadata or population validation and wrote no score output:

1. a hash-pinned generator receipt has a valid UTF-8 BOM; its reader was made
   BOM-tolerant without normalizing or rewriting the evidence;
2. Atlanta's daily band ladder changes between target dates, so the invalid
   global-per-market signature assertion was narrowed to the correct
   within-market-day invariant;
3. a direct encoded-clock check produced 2,800 rather than the frozen 2,962
   cells; independent streaming counts proved that market-timezone conversion
   exactly restores every frozen count, and the location registry was pinned;
4. an assertion initially assigned a same-second collision to a named slice;
   independent earliest-selection replay proved that neither collision is the
   earliest representative, so the final gate explicitly requires zero
   selected collisions.

These are provenance and scope corrections made before `load_vector()` could
return and before the harness computes any Brier or alpha result. The
predeclaration records the only material contract clarification: binding the
encoded instant to the already-declared market-local clock.

## Evidence packet

The ignored local packet is under:

`scratch/workstation-research-output/preblend-vs-market-20260728d`.

| Artifact | SHA-256 |
| :--- | :--- |
| `predeclaration.md` | `9e6b07311bb018a668b46cb28b95e48de0e2fae3260387cfda2d7169bedc355d` |
| `preblend_market_audit.py` | `fcc3c6ac3a6b8b8334e3e8ded3a84e0092b55503efbe53da644415da444e7b09` |
| `host_admission.json` | `b7ed6fed6fb690bdb35389889073d5bb866f91020d52bec649b58221b39338ba` |
| `self_test_receipt.json` | `a2f27f2bb684ecc4c9fae9f5091ce1dc62ab50bab85aaf48cad84cd9ed91d9e1` |
| `analysis_receipt.json` | `109b700569cdac577baf0950be316fd58cdf78dc23a0019c0354b194b6f2b2e4` |
| `preblend_market_analysis.json` | `2f6f815e2d081c0247a46c2fb931a60578c16fcc23c90ce67a0ee24dbea12ec6` |
| `score_summary.csv` | `fd691bf1e306a70d607b8d3a43f574cc8214a359c2e6f2d1bd56592a1003c70e` |
| `hourly_summary.csv` | `66ee4d13b3ce7f31cb613421a94fea638e11ffea9203bd569ca0b28fa9730dfa` |
| `population_exchange.csv` | `0199aec1e82959e9c3f67f27e1e9758d4abf129b747b63a1b768f4d3e4ead77c` |
| `alpha_sweep.csv` | `592bc828dac833a747a4dcbefc1b71feb28fecda5272ab4895e86f181a0f44cd` |
| `independent_validation_receipt.json` | `60e7ee68abb42b055c121e41af99c302444db78cfbdabf23bd5a4bbf25a9721f` |

The receipt rehashes all fifteen protected inputs before and after analysis.
The final input-identity-set SHA-256 is
`0981194ffa6bf665766e1c33476b027d0209a7483958c343c82ed348ea482f59`.
The thirteen synthetic checks include perfect/climatology/inverted scoring,
PAV identities, soft-target algebra, zero-component alpha endpoints,
market-local date crossing, hour boundaries, collision handling, population
exchange signs, and mutation detection.

An independent standard-library validator did not import the audit harness.
It streamed the frozen vector again, rechecked every input/output hash, and
made 212 exact or tolerance comparisons across population, categorical scores,
named cuts, CORP/PAV identities, the hour-20 exchange, and the alpha grid.
All 212 passed; maximum numeric absolute difference was `2.63e-14`.

The exact-source focused test set passed 51 tests and six subtests with one
non-failing physical-core-discovery warning. The repository documentation
audit passed across 18 agent files and 486 Markdown files. Staged-diff checks
found one new report and no whitespace error.

## Decision

The large tidy story in the handoff does not survive the leakage- and
provenance-sealed score:

- preblend is sharper, but its concentration is not useful enough;
- replay-final improves both reliability and resolution;
- replay-final wins the genuinely uncertain predawn and primary windows;
- the 38 above-floor rescues are more than twice the aggregate 86-case harm;
- the market still wins decisively; and
- the proposed failed-source alpha collapse was inactive.

Therefore:

1. **Do not disable or globally increase candidate alpha from this result.**
2. **Treat reconstructed replay-final as the better measured comparator on
   this corpus, without converting that result into an active-serving
   recommendation.**
3. **Treat the residual as a measured resolution gap, not proof of
   blend-induced resolution destruction and not proof of an irreducible
   forecast limit.**
4. **Keep the prior physical-floor finding separate; scoring benefit does not
   authorize impossible mass.**
5. **Require active-release binding and an untouched confirmation panel before
   any future configuration decision.**

This is a measured negative for the preblend hypothesis and a valuable answer.

## Missions 2+ and NOT-DONE / NOT-REHEARSED

The superseded ordering does not close
`workstation-handoff-2026-07-28c-scale-the-mm-corpus.md`. Its Missions 2+
remain live after this report.

### NOT-DONE

- No active-release, active-registry, or production-serving binding was
  established.
- No untouched confirmation panel selected a scalar alpha.
- No full-corpus label-perturbation replay was run.
- No model was fitted, tuned, trained, replayed with changed policy, or
  promoted.
- No blend, alpha, floor order, config, artifact, release, pointer, collector,
  scheduler, or serving surface changed.
- No CLOB execution, spread, fill, capacity, P&L, sizing, or trading claim was
  made.
- No new weather, market, order-book, reward, trade, or settlement data was
  fetched.
- No PR, merge, `master` push, live trade, or deployment occurred.

### NOT-REHEARSED

- Disabling `current_blend` or deploying `alpha=0.55`, `0.60`, or any other
  value.
- A postblend authoritative-floor projection.
- Active process reload or release adoption.
- Forward performance outside 2026-06-28 through 2026-07-10.
- Any market-making corpus-scale or after-cost decision from this score.

## Primary method references

- [CORP reliability-resolution-uncertainty decomposition and isotonic
  recalibration](https://arxiv.org/abs/2008.03033)
- [Murphy-diagram framework for forecast
  comparison](https://arxiv.org/abs/2005.01835)
