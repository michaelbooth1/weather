# Workstation seasonal market-gap measurement — 2026-08-06

## Verdict

**NOT POWERED to choose World A or World B on the predeclared seasonal Brier-ratio contrast. Do not sequence the programme as though the retrain is the whole answer.**

Power is stated before any seasonal point is interpreted. At the predeclared
`+0.24` ratio-point effect — complete closure of the retained `1.24x` gap in
season — crossed date × market power is only **29.67% for base HGB** and
**50.23% for served replay**, below the `80%` gate. The corresponding 80%-power
minimum detectable effects are `0.5384` and `0.3620` ratio points.

The sealed seasonal points therefore do not authorize a directional story:
base C−B is `+0.1280` `[-0.2679, +0.5288]`; served C−B is `+0.1028`
`[-0.1695, +0.3596]`. Both intervals cross zero.

Two narrower findings do stand:

1. **The gap is present in season.** Served B is `1.4233x` market
   `[1.2428, 1.6589]`; base B is `1.7466x` `[1.5149, 2.0377]`. Their absolute
   Brier-gap intervals are also wholly positive. This measurement does not
   show the in-season collapse required by World A.
2. **A substantial resolution deficit is present in season.** It explains
   `84.70%` of the served B gap and `90.12%` of the base B gap. The seasonal
   resolution-gap contrast is powered against the retained full-resolution
   effect and crosses zero in both lanes. A full retained-gap resolution swing
   by season is therefore not supported, but the experiment still cannot call
   the total Brier-ratio contrast flat.

No fit, retrain, candidate, blend, sharpening, promotion, collection, provider
call, or serving change was performed.

## Power before point interpretation

One-sided noncentral-t sensitivity uses `alpha=0.05`, `df=11`, and the crossed
bootstrap standard error. The score reference is the predeclared `0.24`
ratio-point effect needed for the retained clean-regime gap to collapse from
`1.24x` to parity in season.

| Lane | Crossed SE | Power at +0.24 | 80%-power MDE | Gate |
| --- | ---: | ---: | ---: | --- |
| Base HGB | 0.202782 | **29.67%** | 0.538366 | **FAIL — do not interpret seasonal point** |
| Served replay | 0.136369 | **50.23%** | 0.362046 | **FAIL — do not interpret seasonal point** |

For the decomposition discriminator, the reference is the retained clean-panel
resolution contribution `0.0244102`. Base power is `99.86%` with MDE
`0.0130546`; served power is `99.9997%` with MDE `0.0098005`. Those powered
resolution contrasts are reported below.

## Exact reused population

This mission reuses `-09-31a` exactly. Its independently verified evidence
manifest is
`b65810a907ed9ab0dcbff553d4b12557fcd84e5c325afedaf484c5b6247fe576`.
Every selected `(market, target date, snapshot, record hash, capture hour)`
matches that seal; no row was re-admitted from newer workstation state.

| Stratum | D | M | MD | Hourly snapshots | Binary band rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| B, in season | 23 | 12 | 204 | 4,636 | 50,996 |
| C, out of season | 27 | 12 | 320 | 7,653 | 84,183 |
| Total | 50 | 12 | 524 | 12,289 | 135,179 |

The earliest admitted target is `2026-06-03`; the latest is `2026-07-30`.
Nothing crosses the `2026-07-31` artifact-provenance boundary. Settlement is
the predecessor's exact verified projection of
`data/settlements/<market>/ledger.jsonl`; admission remains
`promotion_countable=True`. `market_day_labels.csv` was not read.

## Brier result

The endpoint is mean one-versus-rest binary band Brier on identical captured
partitions. Market prices remain raw for comparability with the retained
skill-gap work. Base is the frozen per-market effective-hour HGB projected to
the captured bands. Served is the final distribution from the same validated
served-control replay used by `-09-31a`.

| Lane / stratum | Model Brier | Market Brier | Absolute gap [crossed 95%] | Model / market [crossed 95%] |
| --- | ---: | ---: | ---: | ---: |
| Base B | 0.065509 | 0.037506 | +0.028004 [+0.020586, +0.036192] | **1.7466 [1.5149, 2.0377]** |
| Base C | 0.073068 | 0.038977 | +0.034091 [+0.024558, +0.043987] | **1.8746 [1.5937, 2.2211]** |
| Served B | 0.053380 | 0.037506 | +0.015875 [+0.009773, +0.022788] | **1.4233 [1.2428, 1.6589]** |
| Served C | 0.059484 | 0.038977 | +0.020506 [+0.014671, +0.027112] | **1.5261 [1.3529, 1.7564]** |

| Seasonal estimand, C−B | Point | Crossed 95% interval | Interpretation |
| --- | ---: | ---: | --- |
| Base absolute Brier gap | +0.006087 | [-0.006187, +0.018448] | Not distinguishable from zero |
| Base Brier ratio | +0.127973 | [-0.267946, +0.528784] | **Not powered; no direction claim** |
| Served absolute Brier gap | +0.004631 | [-0.004002, +0.012905] | Not distinguishable from zero |
| Served Brier ratio | +0.102839 | [-0.169461, +0.359603] | **Not powered; no direction claim** |

The ratios on this exact seasonal-distance corpus are not the retained clean
panel's pooled `1.24x`; they must not replace that finding. The `+0.1028`
served point is preserved because it was sealed, but converting it into a
"share seasonal" claim is forbidden by the 50.23% power result.

## Exact CORP/Murphy decomposition

The decomposition is market-stratified to prevent cross-market base-rate
mixing and satisfies `Brier = reliability - resolution + uncertainty`. Gap
contributions are model reliability minus market reliability and market
resolution minus model resolution; common outcomes make the uncertainty
contribution zero.

| Lane / stratum | Reliability gap [crossed 95%] | Share of gap | Resolution gap [crossed 95%] | Share of gap |
| --- | ---: | ---: | ---: | ---: |
| Base B | +0.002768 [+0.000074, +0.005324] | 9.88% | **+0.025236 [+0.019456, +0.031817]** | **90.12%** |
| Base C | +0.005740 [+0.002467, +0.009511] | 16.84% | **+0.028351 [+0.020621, +0.036492]** | **83.16%** |
| Served B | +0.002429 [-0.000121, +0.004792] | 15.30% | **+0.013445 [+0.008872, +0.019477]** | **84.70%** |
| Served C | +0.001867 [+0.000076, +0.003705] | 9.11% | **+0.018639 [+0.013644, +0.024530]** | **90.89%** |

| Seasonal decomposition contrast, C−B | Point | Crossed 95% interval | Power at retained full effect | Verdict |
| --- | ---: | ---: | ---: | --- |
| Base reliability gap | +0.002972 | [-0.001024, +0.007717] | — | Indistinguishable from zero |
| Base resolution gap | +0.003115 | [-0.006703, +0.012381] | **99.86%** | Full-effect seasonal swing not supported; interval crosses zero |
| Served reliability gap | -0.000562 | [-0.003229, +0.002391] | — | Indistinguishable from zero |
| Served resolution gap | +0.005193 | [-0.002742, +0.012046] | **99.9997%** | Full-effect seasonal swing not supported; interval crosses zero |

This is the mission's most useful bounded negative. Centre bias can be nearly
zero in season while the information deficit remains large. The experiment
does not prove that the *total* gap is flat, but it does refute treating an
unbiased centre as evidence that the sharpness problem disappeared.

## Base versus served

Serving improves both strata relative to base on this replay, but it does not
absorb the seasonal comparison in a detectable way. Served-minus-base seasonal
ratio contrast is `-0.0251` `[-0.2350, +0.1723]`. The absorption-problem
falsifier does not fire.

That does not turn the result into World A or World B: both base and served
primary contrasts fail the predeclared power gate. It only says the two lanes
do not disagree detectably on seasonality.

## Void recorded-output control

The captured `snapshots_long.csv:model_probability` field is not a valid
categorical distribution on every exact predecessor partition: **267 of 12,289
partitions (2.1727%)** fail mass, with minimum recorded mass `0.00010549`.
Using it would mix valid and partial distributions and would make the endpoint
depend on dropping sealed rows.

Per the handoff's void-control rule, the control was dropped and the rows were
not. Served uses the mass-valid replay-final distribution; base and served
maximum mass error is `9.99e-16`. The rejected recorded-output result remains
sealed in the ignored evidence bundle as a diagnostic and is not interpreted.

## Decision

The predeclared final verdict is **NOT_POWERED**, not World A and not World B.

- Do not claim the total gap is seasonal: both C−B ratio intervals cross zero
  and power is 29.67% / 50.23%.
- Do not claim the gap collapses in season: both in-season gap intervals are
  wholly positive, and the in-season resolution deficit is large.
- Do not claim flat total gaps: the primary seasonal ratio test cannot decide
  that statement.
- Do not expect the retrain to close the sharpness deficit merely because it
  repairs centre bias. The evidence supports treating retraining as a
  precondition, not as an established complete answer to objective #2.

No collection or fitting is authorized by this result. A decision-grade rerun
needs enough independent date clusters to reduce the served ratio MDE from
`0.3620` to at most the `0.24` reference under the same crossed design.

## Evidence and independent verification

The ignored workstation evidence root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\market-gap-seasonal-2026-09-34a`.
It is not a production-host reproduction path and is not assumed to exist in a
clean checkout.

Final evidence-manifest SHA-256:
`40bf8ea7f780602721abcc0ba1f62502d88437225747f0d08137e0f5c12cc8bf`.
The manifest seals 47 files, including the predecessor inputs, exact 135,179
band rows, score/decomposition draws, void diagnostic, finalizer, and verifier.

| Evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| Declaration | 5,381 | `cb0fb650ac9cf8b1506545bfbaad5a65e767301dbca58eca6f06abf5b3a9e9aa` |
| Measurement script | 69,800 | `1de8b986d4bd75a38879345bb83f068e956b13f7d2454cdd5e3249f5a6d93c13` |
| Finalizer | 14,530 | `8f066e5ae581cf6d5838a8988b6896106a2abedfffffa7937a731ec0f368b816` |
| Final summary | 31,902 | `2867e9b522e805f6b898bb9ee9f792ef0f2bfcdc01f2021e5dd1fd66cead1138` |
| Band rows | 35,944,760 | `c6f4257cfbcb157f5d6ae748d5431c91b5a90a4f77b1b17f12aa156c6cf61316` |
| Score draws | 5,472,277 | `2c8b185b41b9a3a43a2fa54a49d907df36df77dfd35a874a5e226e4b5dafb324` |
| Decomposition draws | 1,351,081 | `0f588b3be2432e5d2093a9840942976831c2ffdcb9394e833902f815aedea68d` |
| Independent verifier | 13,384 | `54472dd413a4cb8623f47f3e2b391d1f37e71bedc785bca0f8627e84889dcba3` |
| Verification receipt | 1,629 | `50a8bd7e4def6325a6b39528fa30bc01c7bde2b943390772979e25dfff1c3752` |

The independent verifier passed 11 groups of checks: final and predecessor
hash binding; exact population; boundary and winner integrity; base/served
mass; the 267-partition void control; score points and crossed intervals;
score power/MDE; exact CORP/Murphy identities; component intervals;
resolution power/MDE; and absorption/final-decision logic.

## Repository verification

The branch changes one Markdown report only. The ignored evidence, restored
local Python runtime, and ignored scratch dependencies are not tracked.

Commands run before handback:

```powershell
git diff --check
git diff --stat origin/master...HEAD
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 -Branch codex/workstation-is-the-market-gap-seasonal-2026-09-34a
```

Exact results are recorded after the report-content commit below.

## Safety, roll verdict, and actions not taken

The reserved confirmation window was checked at run time and reported no
reserved dates. No reserved date was opened or consumed.

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Roll verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-06-workstation-is-the-market-gap-seasonal.md` | None | None | None | None | Roll-free; Markdown cannot enter a Python import closure |

No source, test, config, artifact, ledger, tape, release, pointer, scheduler,
task, or production `data/` file was changed. No model was fit or retrained. No
candidate was produced. No market blend or global sharpening was evaluated. No
provider, collector, paid source, fresh observation, or exchange endpoint was
called. No production write, registration, capture restart, PR, merge, or
master action was performed.

## Production-host reproduction and acceptance commands

These paths exist on the production host and reproduce the committed handback,
changed-file scope, documentation audit, and mechanical roll verdict. They do
not pretend that ignored workstation evidence exists there.

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-is-the-market-gap-seasonal-2026-09-34a'
$report = 'docs/roadmap/agent-report-2026-08-06-workstation-is-the-market-gap-seasonal.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Expected changed-file scope is exactly the one Markdown report above and the
expected roll verdict is `ROLL-FREE`.

Branch:
`codex/workstation-is-the-market-gap-seasonal-2026-09-34a`.

Base: `origin/master @ 5f0eb855e41912864d879a67d5804eeb7be7ee99`.

Report-content commit: `PENDING`.

No PR was opened and no merge was performed.
