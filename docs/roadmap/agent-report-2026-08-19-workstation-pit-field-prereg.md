# Agent report 2026-09-61a — PIT-field evaluation preregistration

**VERDICT: CONTINUE CONDITIONALLY. THIS DESIGN CAN DETECT A PLAUSIBLY MATERIAL EFFECT, BUT ONLY IF
THE CANDIDATE'S DATE × MARKET EFFECT FIELD IS COHERENT ENOUGH.** Under the frozen planning
assumption, the decision-10 primary MDE is **6.7900% of the out-of-season C gap** (`0.00143510`
Brier). A predeclared 10% gap-closing effect (`0.00211353` Brier) is therefore detectable. If the
date, market, and residual effect-component standard deviations are each about **7.36% of the gap**,
the MDE reaches 10% and the design is too blunt. That boundary, not the point assumption, is the P0
result.

I continued because the proposed class has a non-empty, plausible detectable region. I did **not**
claim that the fields will produce 10%, and I did not inspect their values. The protocol is frozen
before integration at
`docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json`, SHA-256
`336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146`. A later mission must execute
that artifact unchanged.

## P0 — candidate-class MDE, not the `-09-57a` proxy

The sealed C instrument is the retained `-09-56a` out-of-season stratum: **D=27 target-date
clusters, M=12 market clusters, 320 promotion-countable market-days, 7,653 snapshots, and 84,183
band rows**. Its incumbent excess-Brier gap is:

```text
G = 0.060112820 - 0.038977498 = 0.021135322 Brier
```

The candidate does not exist, so its paired effect field cannot be measured. I therefore froze an
explicit planning model instead of substituting `-09-57a`'s repair-minus-control field:

```text
delta[d,m] = mu + A[d] + B[m] + E[d,m]
a = SD(A) / G; b = SD(B) / G; c = SD(E) / G

MDE / G = max(
    0.032 × 1.3795627734,
    3.8649626733 × sqrt(a²/27 + b²/12 + c²/(27×12))
)
```

`3.8649626733` is `z_(1-0.0025/2) + z_0.8`: decision 10 is two-sided
`alpha=0.0025`, at 80% power. The first term carries the canonical approximately **3.2% unadjusted
12-market floor** into the campaign ledger: selection adjustment raises that lower bound to
**4.4146%**. A result below it may not be reported as this design's MDE even if a convenient
candidate field appears unusually constant.

The declared coherent-effect assumption is `a=b=c=0.05`. It gives:

| Quantity | Frozen planning value |
| --- | ---: |
| Candidate-specific formula term | **6.790047% of G** |
| Absolute primary MDE | **0.001435098 Brier** |
| Campaign-adjusted floor | 4.414601% of G |
| Plausible material target | **10.000000% of G = 0.002113532 Brier** |
| Equal-component boundary for detecting that target | **a=b=c=0.0736372** |
| MDE at `a=b=c=0.075` | **10.185071% of G — target no longer detectable** |

The same function is frozen for severity-tail SSE, substituting the candidate's actual frozen-tail C
gap and tail effect components. Under equal 5%-of-tail-gap components and full D=27/M=12 support,
its planning MDE is also 6.790047% of that endpoint's gap. If tail support has fewer date or market
clusters, the executor must use the smaller actual counts; it may not borrow the all-panel tail MDE.

This is why P0 is conditional rather than green. The design can see a 10% step under the stated
coherence assumption and cannot see it once equal component heterogeneity reaches roughly 7.36%.
The later executor must derive the actual MDE from this candidate's own full-pipeline effect field
before interpreting its point estimate. If actual primary MDE exceeds 10% of G, the frozen verdict is
`NO_GO_UNDERPOWERED_EFFECT_FIELD`.

### Why 10% is plausible enough to continue, but not evidence

The candidate is not another completeness repair. `-09-44a`'s at-most-0.6% precedent restored
already-trained station inputs and found no new skill. This protocol introduces a forecast
information class that the model has never seen: issue-time target-day radiative, cloud,
ventilation, convective, precipitation, and evaporative state. It is third-party weather-model
output—**own information under §0c**—and never a market price.

Ten percent is an explicit material-effect hypothesis for that new class, not a measured prior. It
is deliberately above the 3.2% structural floor and below the scale at which one would be quietly
assuming the information gap solved. The sensitivity boundary makes the conclusion auditable if a
reviewer believes 10% is too generous or the field less coherent.

## Frozen candidate and feature family

The mechanism is one **lead-1 target-day surface-heating and convective-budget tilt**, not a feature
or lead sweep. Only `open_meteo_previous_runs` rows with
`issue_time_basis=fixed_lead_day_offset`, `lead_days=1`, and issue time T−1 00:00 local are eligible.
The stitched endpoint and `stitched_continuous_archive` are forbidden by name; the protocol carries
the parity-fixture defect ID `stitched_forecast_high_without_issue_time`.

For local valid hours 07:00–20:00, the fixed twelve inputs are:

| Field | Frozen aggregation |
| --- | --- |
| `temperature_2m` | maximum, Celsius-equivalent |
| `cloud_cover` | mean |
| `shortwave_radiation` | sum |
| `wind_speed_10m` | mean |
| `cape` | maximum |
| `direct_radiation` | sum |
| `diffuse_radiation` | sum |
| `wind_gusts_10m` | maximum |
| `precipitation_probability` | maximum |
| `precipitation` | sum |
| `vapour_pressure_deficit` | maximum |
| `et0_fao_evapotranspiration` | sum |

Every feature is standardized within market using B only. No market one-hot, season, cutoff,
interaction, subset, alternate lead, or post-result transform may be added. Leads 2–7 are explicitly
excluded from this candidate.

The B-only fit is a 12-coefficient exponential tilt of the incumbent ordered distribution:

```text
r[b] = -1 + 2b/(K-1)
eta = x · beta
q[b] = p[b] exp(r[b] eta) / sum_j p[j] exp(r[j] eta)
```

It uses fixed L2 `lambda=0.01`, no intercept, one deterministic optimization from the zero vector,
and no hyperparameter tuning. Market probability does not enter the fit. Incumbent-zero bands stay
exactly zero, mass must remain within `1e-12`, and the observed-high floor is untouched.

Before C is accessible, the candidate must beat the incumbent on both its full-B training Brier and
a strict 13-date expanding-window B OOF Brier after an initial 10 dates. Failure closes decision 10
unused. No alternate feature family or rescue tuning is allowed.

## Endpoints and decision rule

The **primary** is total out-of-season C excess Brier versus market. The estimand is the reduction in
that excess, algebraically `Brier(incumbent) - Brier(candidate)`. The market remains a benchmark; it
is not consumed by the candidate.

The **secondary** is SSE on the C severity tail frozen from the incumbent before candidate scoring:
incumbent squared error exceeds market squared error and absolute incumbent/market probability
disagreement is at least 0.30. It uses identical rows for incumbent and candidate. This endpoint is
mandatory because `-09-60a` showed that where loss concentrates and where a remedy works can differ.

Decision 10 accepts only when every integrity and B-only gate passes, the actual primary MDE is at
most 10% of G, the primary two-sided `alpha=0.0025` crossed lower bound is above zero, **and the
secondary point improvement is non-negative**. The secondary crossed interval and MDE are required
readouts but need not exclude zero. A primary win that moves loss into the frozen tail is rejected.
An accepted result is labelled only `SELECTED_ON_PREBOUNDARY_PANEL`, never confirmed.

Inference is a 10,000-draw full-pipeline crossed target-date × market pigeonhole bootstrap. Every
draw separately resamples B dates and C dates, shares the market resample, recomputes B-only scaling,
refits the fixed candidate, and scores both endpoints. Power, support, SE, and MDE must be written and
hashed before C point estimates are emitted or interpreted.

## Negative control whose null cannot drift

The control is an **exact incumbent clone**: direct-copy `q_control=p_incumbent` on identical row
keys. Its primary and secondary improvements are algebraically zero row by row. This is not a
permutation expectation and does not depend on cluster prevalence, so it cannot repeat `-09-59a`'s
within-cell-permutation defect.

Both endpoint deltas must be exactly zero before interval construction and the copied arrays and row
keys must be byte-identical. A failure returns `INVALID_CONTROL_FAILURE`. Once C has opened, the
control may not be changed or “corrected”; decision 10 remains spent.

## What spends decision 10

This mission allocates decision 10 and spends **no alpha**. The ledger remains **7 of 20 spent, 13
available**; retired numbers 8 and 9 still cost no alpha.

Decision 10 is spent at the first post-freeze computation that combines candidate-dependent C state
with any C settlement outcome or market probability—including the clone control, candidate-native
MDE, endpoint, bootstrap draw, or a partial/failed attempt. Parser/schema/tests, PIT validation, C
features without outcomes or market, B fitting, and the B-only screen do not spend it.

This conservative trigger prevents an invalid control or failed analysis from becoming a free look.
Any change to population, features, lead, aggregation, fit, gate, endpoint, control, clustering,
alpha, or verdict rule requires disclosure and a newly numbered preregistration before another C
look.

## Frozen artifact and verification

| Artifact | SHA-256 |
| --- | --- |
| `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json` | `336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146` |
| `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.sha256` | contains the exact digest above |

The JSON parsed successfully with the bundled Codex Python 3.12 runtime and contains exactly 12
frozen feature entries. Nothing was installed.

Exact workstation verification:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$protocol = Join-Path $repo 'docs\roadmap\pit-field-evaluation-protocol-2026-09-61a.json'
Set-Location $repo

& $python -c "import json, pathlib; p=pathlib.Path(r'$protocol'); x=json.loads(p.read_text(encoding='utf-8')); assert x['status']=='FROZEN_BEFORE_DATA_INTEGRATION'; assert len(x['mechanism']['features'])==12; print(x['protocol_id'])"
Get-FileHash -Algorithm SHA256 -LiteralPath $protocol
```

## Roll verdict

`scripts\ops\roll_verdict.ps1 -Branch
codex/workstation-preregister-pit-field-evaluation-2026-09-61a` returned **ROLL_VERDICT_PENDING**
after report-content commit **REPORT_CONTENT_COMMIT_PENDING**. The final handback commit will replace
both placeholders without changing the frozen JSON or its hash.

Per-file expected classification, subject to the mechanical command above:

| File | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/operations/CAMPAIGN_LEDGER.md` | none | none | none | none | Roll-free documentation |
| `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json` | none | none | none | none | Roll-free documentation artifact |
| `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.sha256` | none | none | none | none | Roll-free digest |
| `docs/roadmap/agent-report-2026-08-19-workstation-pit-field-prereg.md` | none | none | none | none | Roll-free Markdown |

## Explicitly not done

- No staged PIT field value, production `data/`, workstation mirror, post-boundary row, C candidate
  outcome, or reserved date was read.
- No provider or exchange endpoint was called; no parser, schema, test, model, candidate, artifact,
  release, promotion, activation, pointer, or production state was created or changed.
- No settlement, chain, scheduled task, collector, supervisor, or loop was run, registered, or
  restarted. No order was placed and no trading mode was enabled.
- No market probability entered the proposed model. No observed-high floor, probability mass,
  admission rule, promotion gate, or harvest-only contract was weakened.
- No alpha decision was spent. No PR, merge, master update, branch deletion, or production checkout
  change occurred.

## Production-host acceptance commands

These use production-host paths and do not require workstation scratch evidence:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
$branch = 'origin/codex/workstation-preregister-pit-field-evaluation-2026-09-61a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-pit-field-prereg.md'
$protocol = 'docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json'
Set-Location $repo

git fetch origin
git show "${branch}:$report"
git show "${branch}:$protocol" | Out-Null
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
git show "${branch}:$protocol" | Set-Content -NoNewline -Encoding utf8 "$env:TEMP\pit-field-protocol.json"
Get-FileHash -Algorithm SHA256 -LiteralPath "$env:TEMP\pit-field-protocol.json"
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Branch: `codex/workstation-preregister-pit-field-evaluation-2026-09-61a`.

Base: `7b71de72264c38df4572f0433ed4d6c91f60420a`.

Report-content commit: `REPORT_CONTENT_COMMIT_PENDING`.
