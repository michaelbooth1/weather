# Agent report 2026-09-10 — twelve-field seasonal challenger

**Verdict: `INCONCLUSIVE_UNDERPOWERED`.** The sealed transfer passed every
P0 integrity check. The outcome-blind design was committed before C outcomes
were opened, the candidate was fitted only on canonical in-season B, and
C-pre and C-post were evaluated separately. The all-leads challenger improved
C-pre Brier by `0.000555427` but worsened centre SSE by `1.341677301`; every
reported crossed interval spans zero. The predeclared leads-2-7 sensitivity
also has an adverse centre direction. The original decision rule therefore
does not permit a second research replication.

This result supersedes the prior `BLOCKED_MISSING_SEALED_CORPUS` disposition.
That blocked handback remains immutable history in commits `e741b599` and
`52510fca`; it is not rewritten or presented as though the corpus had been
available then.

## Git, input, and design identity

| Item | Exact value |
| --- | --- |
| Required/resumed branch tip | `52510fca68ef17bd5d76901ae38ce118e80e31ba` |
| Required/resumed tree | `c991c2ddc112368352533c60f50f8cb331e98cc8` |
| Frozen-design commit | `2b00573944c7bf79dc4e33115d841543cb0d22b5` |
| Frozen-design tree | `fc7046250cb25df4216be188f345a63384d83c2b` |
| Research implementation/result commit | `3544338badcd10ec7ce166e4c6b6beb7da1b47cb` |
| Research implementation/result tree | `402a1294cffb805df3d2f0e42e4db99f2a35a03a` |
| Branch | `codex/workstation-research-12field-seasonal-challenger-2026-09-86a` |
| Worktree | `C:\Users\Michael\Documents\github\weather\scratch\w\seasonal-challenger-09-86a` |

The final documentation commit/tree are necessarily reported in the outer
handback because a commit cannot contain its own hash.

## P0 — sealed-transfer integrity: PASS

`transfer-receipt.json` was read first. The transfer manifest was then hashed,
all 28 declared payloads were checked byte-for-byte against it, and all 24 CSVs
were independently checked against the two retained original manifests. A
second full P0 attestation after the experiment reproduced the same inventory;
no transferred file was modified, normalized, relocated, or rewritten.

| Proof | Exact value |
| --- | --- |
| Destination | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-20260810` |
| Transfer receipt SHA-256 | `0fd8c9dc14d07ee76d42bded4ea965b69fdb81668474d41862607a3aec7343ca` |
| Transfer manifest SHA-256 | `1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a` |
| Front original manifest SHA-256 | `f1366001341ad6bf96242dc42a9ed47310051079a033e035e850f0f486d1d28d` |
| Back original manifest SHA-256 | `0f52e100a979e5aeb2949d94734682045b5fa294ca0f0cb0d88c1de078ebc735` |
| Canonical payload-inventory SHA-256 | `c2502bd1865eb323a3ee6337c14be9043167382215aa8fb29cb4ea020978545c` |
| Canonical CSV-contract SHA-256 | `17063b1365adf2fe18163034494a1de8dd8de4a1d38aefd3dfa880d53fe5b751` |
| Final P0 receipt file SHA-256 | `aa4423676a057d46709b38e38eb0d89f223d64316acc7148649a555a17976466` |
| Files / CSVs / bytes | `28 / 24 / 171,401,140` |
| Declared rows | `1,645,056` |
| Markets / fields / leads | `12 / 12 / 1-7` |
| Front segment | `2026-06-03` through `2026-06-23`; `508,032` rows |
| Back segment | `2026-06-24` through `2026-08-09`; `1,137,024` rows |
| Source / issue basis | `open_meteo_previous_runs` / `fixed_lead_day_offset` |
| Non-null coverage | `100.0%` |
| Available disk at final attestation | `113,456,943,104` bytes (`105.66 GiB`) |

The destination is a regular directory, not a reparse point. Its owner is
`DESKTOP-RFCD2GH\Michael`. The explicit, non-inherited ACL entry for
`DESKTOP-RFCD2GH\CodexSandboxOffline` remains `Deny` with
`DeleteSubdirectoriesAndFiles, Write, Delete`. The frozen workstation mirror
was also verified non-reparse and retained its separate explicit agent deny.

## Outcome-blind design freeze

The design was written and committed at `2b005739` before any C outcome,
market-probability, market-price, or settlement value was loaded.

| Binding | Exact value |
| --- | --- |
| Canonical design SHA-256 | `11e65dcc4d240e70d15d866013ac27d8c37e6f0e8daaa23831437e293d699816` |
| Design file SHA-256 | `43a264c51987c96382c45dccfbd57150b6c8c4f8d6486517e2577aa067f51b43` |
| Retained repaired surface SHA-256 | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |
| Post-boundary source inventory SHA-256 | `23afdee097d00979aaad01ee4da146d5faf6f5711e819cc8e4eed9f3502ad16a` |
| Forecast aggregate SHA-256 | `857e1390a3a353cc6f3c327ab9c13007617120889052e8773bb1e58b0bb189b5` |
| Forecast rows / daily lead-field aggregates | `959,616 / 68,544` |

The common path is the repository pooled-band
`HistGradientBoostingClassifier`, one model per effective cutoff hour 07-20,
with `max_iter=90`, `max_leaf_nodes=31`, `learning_rate=0.05`, and seed `42`.
Both arms use the same admitted rows, equal market-day weights, median imputer,
band coordinates, market identity, band-kind encoding, disabled fixed
postprocessors, normalization gamma `1.25`, and current probability pipeline.
The baseline is the temperature-only PIT forecast refit through that path; the
challenger changes only the forecast-information surface to the predeclared 12
fields. No hyperparameter search occurred. Market probabilities are an
evaluation benchmark only and never enter a model feature.

Primary features aggregate local hours 07-20 and leads 1-7. The sensitivity
recomputes both arms on leads 2-7. Fit uses canonical in-season B only. C-pre
ends on 2026-07-30; C-post begins on the `b77cfbed` provenance boundary,
2026-07-31. No row or bootstrap draw pools those cohorts.

## Support and exclusions

| Cohort | Dates | Markets | Market-days | Snapshots | Band rows | Tail rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fit B | 23 | 12 | 204 | 4,636 | 50,996 | n/a |
| C-pre | 27 | 12 | 320 | 7,653 | 84,183 | 4,077 |
| C-post directional | 9 | 3 | 27 | 2,891 | 31,801 | 1,752 |

B and C-pre had zero post-admission exclusions and zero missing forecast
features. C-post inspected 18,031 ledger rows and admitted 107 of 120 latest
labels. Explicit C-post exclusions were: 8 market-days without a
promotion-countable label, 45 without tape, 372 non-target-day snapshots, and
1,535 snapshots outside cutoff hours. Frozen-mirror C-post support exists only
for San Francisco, Seattle, and Toronto, so it is directional and is not
substituted for the twelve-market C-pre claim.

## C-pre locked evaluation

Centre quantities are computed in each market's native settlement unit, as
frozen. Tail support is fixed by the incumbent-versus-market severe-error
definition before candidate comparison. Probability mass error is the maximum
absolute simplex residual.

| Arm | Bias | MAE | SSE | Brier | Severe-tail SSE | Modal hit | Mass error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Incumbent diagnostic | -0.495368123 | 1.691600060 | 5.973847104 | 0.060112820 | 0.486324692 | 0.470403763 | 6.66e-16 |
| Market benchmark | 0.101989662 | 0.939942653 | 1.783824966 | 0.038904900 | 0.068802731 | 0.648503855 | 8.88e-16 |
| Primary baseline | 1.422415022 | 2.413943629 | 10.114024182 | 0.077905696 | 0.308129546 | 0.331895989 | 6.66e-16 |
| Primary 12-field | 1.475324395 | 2.511648115 | 11.455701483 | 0.077350269 | 0.311182972 | 0.313994512 | 6.66e-16 |
| Leads-2-7 baseline | 1.435220092 | 2.468525634 | 10.449252255 | 0.077784290 | 0.317108877 | 0.337384032 | 6.66e-16 |
| Leads-2-7 12-field | 1.405481987 | 2.546312696 | 11.203575710 | 0.077927988 | 0.319743645 | 0.307461126 | 5.55e-16 |

Crossed target-date by market inference used 20,000 shared-weight pigeonhole
draws, seed `8602026`, percentile 95% intervals, and two-sided normal plug-in
power. Positive “improvement” favors the challenger; Brier is reported as
challenger minus baseline, where negative favors the challenger.

| Endpoint | Point | 95% interval | Power | 80%-power MDE |
| --- | ---: | ---: | ---: | ---: |
| Primary centre-bias change | -0.052909372 | [-0.410247737, 0.238211723] | 0.061824 | 0.462968 |
| Primary centre-MAE improvement | -0.097704486 | [-0.445888949, 0.184089470] | 0.093441 | 0.449537 |
| Primary centre-SSE improvement | -1.341677301 | [-4.678093564, 1.065943194] | 0.148211 | 4.145053 |
| Primary Brier delta | -0.000555427 | [-0.004691350, 0.003748432] | 0.057623 | 0.006046 |
| Primary severe-tail SSE improvement | -0.003053426 | [-0.021018041, 0.017178348] | 0.061494 | 0.027097 |
| Primary modal-hit improvement | -0.017901477 | [-0.059059637, 0.023183958] | 0.137559 | 0.058484 |
| Leads-2-7 centre-SSE improvement | -0.754323455 | [-3.349899059, 1.016852057] | 0.103011 | 3.148074 |
| Leads-2-7 Brier delta | 0.000143699 | [-0.003987685, 0.004374914] | 0.050534 | 0.005897 |

Every interval crosses zero, so power and MDE are reported for every endpoint.

### C-pre per-market concentration

| Market | Snapshots | Centre-SSE improvement | Brier delta |
| --- | ---: | ---: | ---: |
| Atlanta | 621 | 0.412744747 | -0.006855280 |
| Austin | 646 | -0.330078905 | -0.000173105 |
| Chicago | 645 | 0.001741601 | -0.001994946 |
| Dallas | 646 | -0.859370899 | -0.001258848 |
| Denver | 644 | -0.779787750 | -0.003307671 |
| Houston | 646 | 0.730438313 | -0.005446880 |
| Los Angeles | 646 | 5.382240827 | -0.004290158 |
| Miami | 645 | 0.054946100 | -0.002174379 |
| NYC | 622 | -1.037788230 | 0.006437166 |
| San Francisco | 646 | -15.697949054 | 0.012098505 |
| Seattle | 599 | -2.657903248 | 0.000554271 |
| Toronto | 647 | -1.329975068 | -0.000170934 |

The aggregate centre improvement is negative, so a favorable-improvement
concentration fraction is undefined (`null`) rather than fabricated; the
original maximum-one-market-at-most-35% gate fails.

## C-post directional evaluation

| Arm | Bias | MAE | SSE | Brier | Severe-tail SSE | Modal hit | Mass error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Incumbent diagnostic | -0.516774669 | 1.889249884 | 7.418211615 | 0.067946758 | 0.471583740 | 0.378761674 | 4.44e-16 |
| Market benchmark | 0.431814448 | 0.933725363 | 1.836106327 | 0.046484261 | 0.082918566 | 0.558976133 | 4.44e-16 |
| Primary baseline | 2.957214704 | 3.355908631 | 17.480149179 | 0.092646417 | 0.358067330 | 0.144586648 | 4.44e-16 |
| Primary 12-field | 3.186672053 | 3.425218974 | 17.394069486 | 0.095078403 | 0.357692663 | 0.075752335 | 4.44e-16 |
| Leads-2-7 baseline | 2.553374799 | 3.102251426 | 15.770574329 | 0.094181307 | 0.367766069 | 0.112763750 | 4.44e-16 |
| Leads-2-7 12-field | 3.005883680 | 3.201486816 | 15.380322109 | 0.094113682 | 0.362251703 | 0.074368731 | 4.44e-16 |

| Endpoint | Point | 95% interval | Power | 80%-power MDE |
| --- | ---: | ---: | ---: | ---: |
| Primary centre-bias change | -0.229457349 | [-1.218786441, 0.740158995] | 0.075045 | 1.384420 |
| Primary centre-MAE improvement | -0.069310343 | [-0.917047466, 0.776206492] | 0.053171 | 1.168220 |
| Primary centre-SSE improvement | 0.086079693 | [-8.069447625, 7.063893285] | 0.050064 | 10.220726 |
| Primary Brier delta | 0.002431986 | [-0.005308718, 0.014993797] | 0.075471 | 0.014551 |
| Primary severe-tail SSE improvement | 0.000374667 | [-0.065336699, 0.048855844] | 0.050019 | 0.081607 |
| Primary modal-hit improvement | -0.068834313 | [-0.237094616, 0.028099815] | 0.168582 | 0.194023 |
| Leads-2-7 centre-SSE improvement | 0.390252220 | [-5.778761966, 8.017248722] | 0.051607 | 9.235607 |
| Leads-2-7 Brier delta | -0.000067625 | [-0.008499988, 0.009880582] | 0.050024 | 0.013088 |

C-post per-market primary centre-SSE improvements / Brier deltas were San
Francisco `-3.435710031 / -0.001042071` (934 snapshots), Seattle
`3.613480366 / 0.007918785` (945), and Toronto
`0.042559898 / 0.000514735` (1,012). The maximum-one-market concentration is
`13.721724818`; it is unstable because the three-market aggregate improvement
is near zero and is reported only as a directional warning.

## Decision rule

| Original C-pre condition | Result |
| --- | --- |
| Centre SSE improvement positive and crossed interval excludes zero | FAIL |
| Challenger-minus-baseline Brier nonpositive and upper bound no worse than +0.002 | FAIL |
| Leads-2-7 sensitivity has the same favorable centre direction | FAIL |
| Probability mass and captured-input parity pass | PASS |
| Maximum one-market contribution at most 0.35 | FAIL |
| No market/outcome/settlement-derived model input | PASS |

The unchanged rule maps this pattern to `INCONCLUSIVE_UNDERPOWERED`, not
`GO_TO_SECOND_RESEARCH_REPLICATION` and not an established-harm `NO_GO`.

## Model and result hashes

| Object | SHA-256 |
| --- | --- |
| Primary baseline aggregate model | `c1d6c4a0114948406a139ddbd5d03fc7f6a21cc6f0c8f69d93c8bc8a54847a79` |
| Primary 12-field aggregate model | `26169d50b7b4a52fdab844846f3ccc304181e36da0919c6dc17bde864f61a91f` |
| Leads-2-7 baseline aggregate model | `959ca994a56f11a5ae8d3637338224778176872aecabd195e4290584518046f7` |
| Leads-2-7 12-field aggregate model | `a4bf1292196800b21f38bf7e08f7cb75c5e3f72b8d23a8f991451a109a2193ac` |
| Canonical result | `3ca4a3594e89bcd556cb1a5a7756bdcdeef4b3a75e6543b79a6add4d337039af` |
| Result file | `2bc71ccb93cd072face8fdd352b792a7485e434ccb5c87e938565ed080b97906` |
| Independent verification file | `344fbf1f51bbc2cb131ee3d9dd147a7f1cba06384f6936af2f78fca5a6f3b2c6` |

All four variants refitted deterministically across all fourteen cutoff models.
Independent result verification passed 68 checks: 12 top-level bindings and 56
individual model-file hashes. Exact per-cutoff hashes remain in the 47,621-byte
local result receipt at
`scratch\runs\seasonal-challenger-2026-09-86a\result.json`; no model was
promoted, released, frozen as a candidate, or connected to serving.

## Verification

Every Python verification command below ran through
`scripts/ops/workstation_heavy.ps1` under `workstation_offline_v1`.

| Check | Result |
| --- | --- |
| P0 full transfer validation before outcome access | PASS |
| P0 full re-attestation after experiment | PASS |
| Independent result/model verification | PASS (68 checks) |
| Seasonal-challenger focused tests | PASS (6 passed) |
| Hook parity plus challenger tests | PASS (37 passed) |
| Schema-registry plus challenger tests | PASS (14 passed) |
| Complete workstation suite, 372 files in 15 bounded chunks | PASS (4,305 passed, 23 skipped, 13 warnings, 866 subtests passed) |
| Compileall (`app`, `src`, `tests`) | PASS (exit 0) |
| Agent-document audit | PASS (18 agent files, 832 Markdown files) |
| Roadmap lint/generated-view check | PASS (`Roadmap backlog: OK`; generated view matches sources) |
| `git diff --check` | PASS |
| Canonical roll verdict at implementation commit | `UNDECIDABLE: no live closure evidence` (exit 1; all four required supervisor-status snapshots absent on this workstation) |

The canonical roll verdict was obtained only from
`scripts/ops/roll_verdict.ps1 -Branch
codex/workstation-research-12field-seasonal-challenger-2026-09-86a`; it was not
derived by hand. No merge was attempted.

## Prohibited-actions audit

| Action | Result |
| --- | --- |
| Refetch, provider, or other network data call | none |
| Transfer-server contact or restart | none; authority remained closed |
| Transferred-file mutation, normalization, relocation, or manifest invention | none |
| Production or frozen-mirror write | none |
| Scheduler, capture, exchange, or credential access | none |
| Market price, outcome, or settlement-derived model feature | none |
| Pooling across the 2026-07-31 provenance boundary | none |
| Release, pointer, promotion, activation, serving change, candidate freeze, or confirmation window | none |
| Training outside canonical in-season B | none |
| PR merge or reconciliation execution | none |
