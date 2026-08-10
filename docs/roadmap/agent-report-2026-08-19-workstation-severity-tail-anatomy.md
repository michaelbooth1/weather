# Agent report 2026-08-19 — workstation severity-tail anatomy

**VERDICT: GO — severity-tail membership is predictable ex ante from own information alone.** A
strict expanding-window diagnostic reaches forward AUROC **0.90260** with crossed 95% interval
**[0.88356, 0.91772]** on 40 date clusters, 12 markets, 455 market-days, 118,239 band rows, and
5,448 tail rows. Its crossed 80%-power characterization MDE is **0.02406 AUROC**, derived for this
estimand; the `-09-57a` paired-improvement MDE `0.0151764` was not reused. This does **not** accept
or reject a forecast candidate. It spends **no campaign-ledger decision**, scores no candidate on
C, and books no served improvement.

The actionable anatomy is predominantly the incumbent's own distribution shape: the modal band
and adjacent shoulders contain 84.33% of tail rows, and an own-band-only forward diagnostic reaches
AUROC 0.85207. Cutoff weather state adds collective forward information, but weather alone is not
established. The tail is diffuse across all 12 markets, is not a row-density artifact, and has no
established season or cutoff-hour discriminator. A future proposal may therefore investigate
**conditional** distribution reshaping behind an own-information tail-risk trigger; global
sharpening remains retired and the serving floor must never be weakened.

## Scope and evidence contract

I executed the handoff on base `5c3918815075d8c89c92d7d73d981a298aedfe4b` using the bundled
Codex Python 3.12 runtime. I installed nothing and made no network or provider call. All analysis
used retained, sealed pre-boundary material through `2026-07-30`; nothing on or after the
`2026-07-31` boundary was pooled.

The frozen repaired-surface target was constructed exactly as specified:

```text
repair_squared_error > market_squared_error
and abs(repair_probability - market_probability) >= 0.30
```

Market probability and market squared error were used only to construct that target. They did not
enter a characteristic, predictor, imputer, scaler, threshold, or proposal. Settlement outcome,
realized temperature, post-cutoff information, and provider-refetched values were likewise absent
from predictors. Allowed predictors were own model distribution/band state, market identity and
native unit, season/cutoff schedule, cutoff-captured own-weather state, and missingness indicators.

The retained panel SHA-256 is
`4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88`. Direct recomputation gives
135,179 rows and 5,930 tail rows (4.38678%). The full panel has D=50 / M=12 / 524 market-days / 12,289
snapshots; the positive tail itself has the handoff's D=49 / M=12 / 487 market-days. All 12,289
selected replay records matched their retained `record_hash`, across all 524 admitted replay files.

Unless stated otherwise, intervals below are two-sided percentile 95% intervals from 10,000
crossed target-date × market pigeonhole-bootstrap draws with shared weights. MDEs use two-sided
alpha 0.05 and 80% power. Rates are band-row rates in each named stratum.

## The concentration is real, not a row-density artifact

Raw band-row weighting reproduces the established headline:

- Tail row share: **4.38678% [3.61750%, 5.25669%]**.
- Share of all positive excess loss carried by the tail: **64.14022% [57.97074%, 69.75455%]**.

Every retained snapshot has exactly 11 band rows. Consequently, equal-snapshot weighting gives
the identical 4.38678% and 64.14022%. Equal-market-day weighting gives **4.41150%
[3.62744%, 5.27894%]** and **64.52864% [58.21880%, 70.13864%]**. Neither snapshot row density nor
market-day row density explains the concentration, so the `4.387% / 64.140%` finding remains live.

## P0 — what distinguishes a tail row

### 1. Band position dominates

| Own-distribution position | Tail rows / band rows | Tail prevalence (crossed 95%) | Share of tail rows (crossed 95%) | Share of all positive excess (crossed 95%) |
| --- | ---: | ---: | ---: | ---: |
| Centre / modal band | 3,268 / 12,289 | 26.5929% [22.1866%, 31.2218%] | 55.1096% [51.6518%, 58.9673%] | 28.4445% [25.4547%, 31.2633%] |
| Adjacent shoulders | 1,733 / 23,815 | 7.2769% [5.7528%, 9.1441%] | 29.2243% [25.1845%, 33.2086%] | 21.0394% [17.3132%, 25.1473%] |
| Other / extreme bands | 929 / 99,075 | 0.9377% [0.6162%, 1.2917%] | 15.6661% [11.7305%, 19.3769%] | 14.6564% [10.3139%, 18.8536%] |

The centre-minus-shoulder prevalence contrast is **+19.3160 percentage points [15.8026,
23.1529]**, MDE 5.2065 points, power 1.000. Shoulder-minus-extreme is **+6.3393 points [4.8800,
8.0123]**, MDE 2.2235 points, power approximately 1.000. The tail is therefore a
centre-and-shoulder overconfidence phenomenon, not an extreme-bin phenomenon.

This survives a forward test. The band family—schedule plus own probability, rank, distance from
mode and expectation, entropy, effective band count, CDF position, and bin shape—has AUROC
**0.85207 [0.81556, 0.88834]**, MDE 0.05203. That is ex-ante ranking, not a hindsight label.

### 2. Market incidence varies, but the tail is diffuse

The following gives within-market tail prevalence and each market's share of tail rows. Share
intervals use the fully crossed resampling and therefore include structural zero when a named
market is absent from a resample; fixed-market concentration follows the table.

| Market | Tail rows | Within-market prevalence (crossed 95%) | Share of tail rows (crossed 95%) |
| --- | ---: | ---: | ---: |
| Atlanta | 338 | 3.036% [2.113%, 4.040%] | 5.700% [0.000%, 20.383%] |
| Austin | 415 | 3.635% [2.718%, 4.654%] | 6.998% [0.000%, 23.919%] |
| Chicago | 540 | 4.846% [3.584%, 6.191%] | 9.106% [0.000%, 29.341%] |
| Dallas | 439 | 3.845% [2.960%, 4.748%] | 7.403% [0.000%, 25.279%] |
| Denver | 639 | 5.475% [4.388%, 6.657%] | 10.776% [0.000%, 33.144%] |
| Houston | 421 | 3.866% [3.036%, 4.819%] | 7.099% [0.000%, 24.491%] |
| Los Angeles | 753 | 6.852% [5.302%, 8.478%] | 12.698% [0.000%, 37.296%] |
| Miami | 500 | 4.492% [3.574%, 5.421%] | 8.432% [0.000%, 27.520%] |
| NYC | 515 | 4.622% [3.420%, 5.912%] | 8.685% [0.000%, 28.617%] |
| San Francisco | 469 | 4.168% [3.302%, 5.112%] | 7.909% [0.000%, 26.196%] |
| Seattle | 516 | 4.691% [3.620%, 5.828%] | 8.702% [0.000%, 28.725%] |
| Toronto | 385 | 3.211% [2.274%, 4.260%] | 6.492% [0.000%, 21.900%] |

With the 12 named markets fixed and dates resampled, tail-share HHI is **0.08739 [0.08598,
0.09177]**, equivalent to **11.44 effective markets** out of 12; row-share HHI is 0.08339. The HHI
increment is +0.00400 [0.00251, 0.00832], but its MDE is 0.00421 and power only 0.757, so I do not
promote a directional concentration claim. Los Angeles and Denver together hold only 23.47% of
tail rows versus 16.76% of all rows. This falsifies the “one or two markets” operational-fix route.

F-native markets contain 93.51% of tail rows and have 4.501% prevalence [3.728%, 5.394%]; the only
C-native market, Toronto, has 3.211% [2.274%, 4.260%]. That unit split is confounded with market
identity and is not a unit effect. F markets' legitimate lack of pressure fields was retained as
missingness/source state, never filled with post-cutoff or market information.

### 3. Season and cutoff do not carry an established concentration shift

In-season B prevalence is **3.5316% [2.5746%, 4.6455%]** on D=23 / M=12 / 204 market-days;
out-of-season C is **4.9048% [3.9024%, 6.0305%]** on D=27 / M=12 / 320. C-minus-B is **+1.3731
points [-0.0497, 2.7464]**, MDE 1.9732 points, power 0.496. The observed ordering is descriptive,
not an established seasonal move.

Tail prevalence is 3.9854% in 07:00–08:00, 4.6117% in 09:00–14:00, and 4.6472% in 15:00–20:00.
Primary-minus-early is **+0.6263 points [-0.2027, 1.3803]**, MDE 1.1279 points, power 0.343.
Late-minus-primary is **+0.0354 points [-1.4272, 1.5742]**, MDE 2.1470 points, power 0.050.
There is no licensed cutoff gate.

### 4. Own-weather state is secondary, not a standalone regime

Within-market standardized hindsight contrasts put tail rows at higher current temperature
(+0.220 SD [0.066, 0.364], 98.9% coverage), higher high-so-far (+0.210 SD [0.015, 0.385], 98.9%),
and faster two-hour warming (+0.437 SD [0.272, 0.580], 25.3%). Observed wind speed is lower
(-0.260 SD [-0.432, -0.060], 30.3%). Rise from 07:00, hours at peak, forecast gap, forecast-source
disagreement, humidity, pressure trend, and minutes since cutoff all have intervals spanning zero.
These are descriptive associations; the limited trajectory coverage matters.

The decisive forward weather-only family has AUROC **0.54832 [0.49180, 0.60039]**, MDE 0.07782 and
power 0.413, while Brier improvement is negative. Weather alone is therefore **not established**.
The full-minus-band paired AUROC increment is **+0.05053 [0.01903, 0.08255]**, MDE 0.04528, so the
captured weather fields add collective information after band state overall. The increment is
+0.11715 [0.03456, 0.16351] in B but only +0.02646 [-0.00332, 0.05848] in C; that asymmetry bars a
blanket weather-regime claim.

METAR-surface rows have 2.5909 points more tail prevalence than WU-history-surface rows [1.3673,
3.7876], MDE 1.7132 points, power 0.989. Source, market, cutoff, and feature availability are
confounded, however, and `-09-44a` already closed input completeness as a gap lever. This is not
evidence of a station defect. The cheapest future discriminator would be a predeclared forward
ablation of physical state versus source/missingness within market and cutoff; it remains
characterization, not a candidate test.

## Decisive forward predictability test

The predeclared design sorted target dates ascending, trained on the first 10 dates, and scored five
successive blocks of eight dates each. Every block used an expanding prior-date training set.
Median imputation, standardization, categorical levels, and missingness indicators were fitted
inside each training fold. All 20 ridge-logistic fits converged in 7–12 iterations, every training
log loss beat its fold's prevalence-only loss, and every last training date preceded its first test
date.

| Own-information family | Forward AUROC (crossed 95%) | AUROC MDE from 0.5 | Brier improvement over fold-training prevalence (crossed 95%) |
| --- | ---: | ---: | ---: |
| Schedule: market/unit + season + cutoff | 0.49298 [0.43398, 0.55117] | 0.08360 | negative |
| Band: schedule + own band/distribution state | 0.85207 [0.81556, 0.88834] | 0.05203 | interval spans zero |
| Weather: schedule + cutoff-captured weather | 0.54832 [0.49180, 0.60039] | 0.07782 | negative |
| Full: schedule + band + weather | **0.90260 [0.88356, 0.91772]** | **0.02406** | **+0.00864 [0.00467, 0.01292]** |

For the full diagnostic, average precision is **0.37123 [0.29351, 0.44716]** against 4.6076% OOF
prevalence. The top 5% of forward scores has precision **39.6957% [31.9234%, 46.7568%]** (8.62×
the OOF base rate), recalls **43.0984% [35.1181%, 50.6393%]** of tail rows, and contains **27.4150%
[20.8605%, 34.1216%]** of all positive excess loss.

Stratified robustness preserves the result: full AUROC is **0.88794 [0.85733, 0.91480]** in B
(D=13 / M=12 / 135 market-days / 34,056 rows) and **0.90745 [0.88823, 0.92444]** in C
(D=27 / M=12 / 320 market-days / 84,183 rows). These are diagnostic tail-membership rankings,
not forecast candidates scored on C.

### Negative-control correction

The initially declared within-date × market label permutation was a defective control for global
AUROC: permuting only inside each cell preserves date/market prevalence, so its expected global
AUROC need not be 0.5. Its result, 0.53201 [0.51220, 0.54994], is preserved as invalid rather than
discarded. Before correcting it, I froze and hashed the OOF predictions, primary crossed draws, and
v1 result. I then changed only the control to 500 deterministic **global** OOF-label permutations,
which preserve total prevalence while destroying feature-target association. No fit, score, target,
primary draw, threshold, or decision rule changed.

The corrected null has mean AUROC **0.49985**, SD 0.00397, 95% range [0.49221, 0.50737], and maximum
0.51243. The observed 0.90260 exceeds all 500 draws. The numerical average-precision summaries
were also recomputed to remove zero-weight 0/0 draws; all 10,000 final draws are finite. This
correction repairs an invalid expectation and numerical summary, not an unfavorable result.

## P1 — ranked direction, not a candidate decision

| Rank | Direction | Evidence / honest error bar | Effort and served-gain status |
| ---: | --- | --- | --- |
| 1 | Conditional own-distribution shape trigger around modal/shoulder overconfidence | Band AUROC 0.852 [0.816, 0.888]; centre+shoulders contain 84.33% of tail rows. Full top 5% recalls 43.10% [35.12%, 50.64%] of the tail and 27.42% [20.86%, 34.12%] of positive excess. | Low-to-medium diagnostic/engineering effort. Actual forecast/SSE improvement is **unmeasured and may be zero**; these are addressability ceilings, not booked gain. Any later candidate must conditionally widen/redistribute mass, preserve total probability, and never weaken the floor. |
| 2 | Add captured temperature/trajectory state to the band trigger | Full-minus-band AUROC +0.0505 [0.0190, 0.0826] overall; C-only interval crosses zero. | Medium effort because sparse trajectory coverage and source/missingness require fold-honest handling. Incremental served gain remains unmeasured. Cheapest next discriminator is the forward ablation above. |
| 3 | Market-specific operational remediation | Effective market count 11.44/12; largest two markets contain 23.47% of tail rows. | Low effort to inspect, but no one/two-market fix can address most of the endpoint. Do not pursue without independent station-quality evidence. |
| 4 | Season or cutoff gating | C-minus-B, primary-minus-early, and late-minus-primary all fail their own MDE/power requirements. | Low implementation effort but unsupported expected gain; **NO-GO** on current evidence. |

This mission did not fit a forecast candidate, did not modify probabilities, did not test tail SSE
improvement, and did not use a campaign confirmation slot. If a later mission turns the first or
second direction into a candidate, it must declare and spend a decision explicitly; nothing here
authorizes that step.

## Independent verification and retained receipts

An independent verifier reloaded the frozen panel and OOF evidence, recomputed the target and all
main point metrics, recomputed all crossed standard errors/intervals and the characterization MDE,
checked the feature boundary, checked strict chronology and fit sanity, checked the global
permutation control, and bound the anatomy/stratum outputs. It returned `PASS` on every check.

Workstation-retained evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\runs\severity-tail-anatomy-2026-09-59a`.

| Retained artifact | SHA-256 |
| --- | --- |
| `analysis-v2.json` | `1714f6c8f88feb1eec044dd56af934bce30932a8179f3e8adc615a0187ecc361` |
| `anatomy-contrasts.json` | `9eaa8306bf17f968f4e27762683c1b5638fb8742d2a134d63367325ada348393` |
| `forward-stratum-readout.json` | `200f74a29e49457ff12208fb1afcf88c11a6d66ad7c9d10647f16b2d66989b96` |
| `evidence-manifest-final.json` | `d9bc2e2f13131f7da1ba9df2e03f0e96a4d64af9d037c4d7485c993dfc738745` |
| `verification.json` | `a77c533e2fccd4286d0b466e468e9721e80ecd1238b949c7324367d59ac167b8` |

### Exact workstation evidence reproduction

These paths exist on the workstation that retains the sealed inputs. The first command is
long-running. It performs no network or provider call.

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$run = Join-Path $repo 'scratch\runs\severity-tail-anatomy-2026-09-59a'
Set-Location $repo
& $python (Join-Path $run 'analyze_severity_tail.py')
& $python (Join-Path $run 'finalize_v2.py')
& $python (Join-Path $run 'derive_anatomy_contrasts.py')
& $python (Join-Path $run 'derive_forward_strata.py')
& $python (Join-Path $run 'verify_severity_tail.py')
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $run 'verification.json')
```

## Safety, files, roll verdict, and production handback

What I did **not** do: no new data, provider or exchange call; no registration; no scheduled-task,
chain, settlement, release, pointer, or production-data write; no loop start/restart; no serving-floor
change; no live trading; no promotion; no PR; no merge. The workstation branch was only committed
and pushed as required.

The only tracked file changed is this report:

| Changed file | Retained-closure membership | Roll verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-19-workstation-severity-tail-anatomy.md` | none | roll-free |

The final per-file result below will be bound from
`scripts\ops\roll_verdict.ps1 -Branch codex/workstation-anatomy-of-the-severity-tail-2026-09-59a`
after the report-content commit; it is not hand-derived.

- Mechanical roll verdict: `PENDING_REPORT_CONTENT_COMMIT`
- Report-content commit: `PENDING_REPORT_CONTENT_COMMIT`
- Branch: `codex/workstation-anatomy-of-the-severity-tail-2026-09-59a`

Exact production-host acceptance commands (production path from the delegation contract):

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
$branch = 'codex/workstation-anatomy-of-the-severity-tail-2026-09-59a'
Set-Location $repo
git fetch origin $branch
git show "origin/$branch`:docs/roadmap/agent-report-2026-08-19-workstation-severity-tail-anatomy.md"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\roll_verdict.ps1 -Branch "origin/$branch"
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
git rev-parse "origin/$branch"
git ls-tree -r --name-only "origin/$branch" | Select-String 'agent-report-2026-08-19-workstation-severity-tail-anatomy.md'
```
