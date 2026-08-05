# Workstation continuation-candidate report - 2026-08-02

## Pre-registration - frozen before candidate fitting or result inspection

Declared at `2026-08-02T15:38:08.1509216Z`, before fitting or inspecting any candidate result. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\continuation-candidate-2026-08-12a`, outside the replay mirror. `data/` and the mirror remain read-only.

The experiment reads the accepted `2026-07-22` through `2026-07-30` corpus regenerated wholly after the `2026-07-31` `rows[-1]` regime boundary. Development fit/model selection is frozen to July 22-26 with market-day grouping and chronological blocked folds. July 27-30 is the one-time replay-score window and may not be used for fitting, tuning, selection, or threshold changes. The freshness gate applies only to those exact 108 declared market-day inputs. The reserved August 6-19 forward window will not be read, enumerated, evaluated, or substituted.

### Frozen catastrophic-slice bar

> **No protected slice may regress by more than the pooled improvement.**

Let pooled improvement be `I_pool = baseline_daily_first_Brier - candidate_daily_first_Brier`. For every protected slice, let `delta_slice = candidate_daily_first_Brier - baseline_daily_first_Brier`. A slice fails when `delta_slice > I_pool + 1e-12`. A non-positive pooled improvement cannot qualify. This bar is additional to, and does not relax, the harness's existing protected-slice regression flags or frozen hard gates.

Protected slice memberships are frozen to the harness definitions:

1. `market`: market ID.
2. `capture_hour`: local capture hour.
3. `floor_source`: canonical floor source, with `none` only when no floor is available and `unknown` treated as missing qualification provenance.
4. `binding_strength`: `no_floor`; floor-removed mass `<=1e-6`; `>1e-6` to `1%`; `>1%` to `5%`; `>5%` to `20%`; or `>20%`.
5. `forecast_relative_winner`: settled winner's ordered-band index minus the rounded forecast-high band index, bucketed as `<=-3`, `-2`, `-1`, `0`, `+1`, `+2`, `>=+3`, or `unknown`.
6. `D_class`: `no_floor`, `negative_invalid`, `D0`, `D1`, or `D2plus` from `Y-F`.

### Frozen candidate contract

For cutoff-time canonical floor bucket `F` and settled bucket `Y`, the floor-available lane learns non-negative continuation `D = Y-F`. `F` is control metadata and the absolute decode origin, not a predictor. Candidate native mass is translated to absolute bucket `F+D`; the incumbent local-history/climatology prior is conditioned to the same support before blending; and every existing hard-floor stage remains unchanged. Floor-unavailable rows retain the incumbent output.

No outcome, market probability, post-cutoff source state, target-date encoding, or future source state may enter the predictor matrix. Candidate choices and thresholds freeze before the one-time July 27-30 score.

## Verdict

**FAIL. Do not qualify this candidate.** The frozen blend improved the pooled
daily-first 11-band Brier point estimate from `0.052530132` to `0.050160417`
(`-0.002369714`) and strongly improved the incumbent-frozen severe tail, but
the one-sided 95% market-day bootstrap upper bound was `+0.003147121`, so the
total-Brier non-regression gate blocks. The candidate also breached the
pre-registered catastrophic-slice bar in **19 / 54** observed protected slices
and created newly severe rows at **2.66869%**, above the frozen **1.15535%**
cap.

The centre-selected severe tail did move in the intended direction. Fixed-tail
positive excess fell from `0.728976079` to `0.304494564`, a
`0.424481515` (**58.23%**) reduction, improved on all four score dates, and
severe rows fell from **3,893 to 3,405**. That gain is real but is not a
trade-off against the conjunctive failures.

The research candidate remains held. No release, promotion, pointer, serving,
or production action is authorized by this result.

## Execution identity and scoped freshness

| Field | Frozen value |
| :--- | :--- |
| Handoff source | `origin/master` `39ae1e5c` |
| Required base | held `codex/workstation-gate-harness-2026-08-09a` at `b9c62ead999bfb74175e0e2eb46d2d31e57f225b` |
| Topic branch | `codex/workstation-continuation-candidate-2026-08-12a` |
| Pre-registration commit | `961a4e1c` |
| Frozen implementation commit | `439040a8` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\continuation-candidate-2026-08-12a` |
| Declaration time | `2026-08-02T15:38:08.1509216Z` |
| Development fit/model-selection dates | 2026-07-22 through 2026-07-26 |
| One-time score dates | 2026-07-27 through 2026-07-30 |
| Reserved forward dates | 2026-08-06 through 2026-08-19; not read, enumerated, or evaluated |

The freshness check resolved only the 108 manifest-declared July 22-30
market-day folders. All 108 exist, remain `complete`, coverage-clean, and
promotion-countable. The accepted manifest's two pre-existing one-record
missing-replay-input markers (Toronto July 24 and Los Angeles July 26) remain
recorded; all 19,265 pinned snapshots used by the accepted replay were present,
so no row or date was substituted. The corpus, replay summary, replay rows, and
floor trace reproduced their harness-accepted SHA-256 identities.

All probabilities and result rows used here came from the accepted replay
regenerated after the July 31 `rows[-1]` boundary. The score window never
entered fitting, preprocessing, temperature selection, blend selection, or
threshold selection. This remains heavily inspected retrospective development
evidence, not untouched forward confirmation.

## Candidate built

The fit produced all **168** incumbent market/hour groups from 10,837
floor-available development snapshots. Each group retained its parent
artifact's exact feature names and order. The canonical floor bucket `F` was
used only as target origin, decode origin, and control metadata; it was not
added to the predictor matrix. No outcome, market probability, target-date
encoding, post-cutoff state, or future state entered the predictors.

For each group, the candidate learned non-negative `D=Y-F`, temperature-scaled
the continuation probabilities, decoded them to `F+D`, hard-conditioned the
smoothed absolute prior to `Y>=F`, selected the model/prior weight on blocked
development folds, blended, and reapplied an exact-zero hard floor. The
one-time score covered 8,380 snapshots and 92,180 band rows: 8,325 used the
floor-available continuation lane and the 55 floor-unavailable snapshots were
copied exactly from the incumbent. There were zero negative continuations,
zero native-to-band mass or membership errors, zero sub-floor violations, and
zero failures in 8,266 raise-`F` metamorphic cases.

This is a research artifact, not a release artifact. It does not include a
candidate-specific production exact-distribution calibrator or an inactive
release graph, and it was not replayed through the production serving
constructor. Those omissions remain explicit NOT_EVALUABLE gates below.

## Frozen gate scorecard

| Gate | Result | Evidence |
| :--- | :---: | :--- |
| Corpus and target | **NOT_EVALUABLE** | Row checks pass; zero `Y<F`; canonical floor-source provenance is absent for 8,325 floor rows. |
| Total Brier non-regression | **BLOCK** | Point delta `-0.002369714`; one-sided 95% upper `+0.003147121`, required `<=0`. |
| Severe-tail improvement | **PASS** | Positive excess `0.728976079 -> 0.304494564`; severe rows `3,893 -> 3,405`; all four dates improve. |
| Newly severe cap | **BLOCK** | 2,460 new and 2,948 retired; new rate `2.66869%` versus `1.15535%` cap. |
| Near-floor allocation | **NOT_EVALUABLE** | Band proxy improves, but the incumbent has no native absolute-bucket export. |
| Probability mass | **NOT_EVALUABLE** | Band and candidate-native checks pass; only 8,325 of the required 16,760 native sides exist. |
| Floor invariant | **NOT_EVALUABLE** | Candidate stage/mass checks pass; paired canonical source/disposition receipt is absent. |
| Train/serve parity | **NOT_EVALUABLE** | No candidate C/F production parity receipt. |
| Captured-input replay | **NOT_EVALUABLE** | No inactive-release production-constructor replay receipt. |
| Release binding | **NOT_EVALUABLE** | Release #1 and an inactive candidate graph do not exist. |
| Catastrophic protected slice | **BLOCK** | 19 / 54 observed slices regress by more than pooled improvement `0.002369714`. |

The harness therefore reports `NOT_READY`, with hard statistical blocks in
total Brier, newly severe rows, and the catastrophic slice bar. Missing receipt
gates were not worked around or upgraded.

## Pooled and severe-tail movement

| Metric | Incumbent | Candidate | Change | Gate |
| :--- | ---: | ---: | ---: | :---: |
| Daily-first 11-band Brier | 0.052530132 | 0.050160417 | **-0.002369714** | Point pass; bootstrap **BLOCK** |
| One-sided 95% upper delta | - | - | **+0.003147121** | **BLOCK** |
| Frozen severe positive excess | 0.728976079 | 0.304494564 | **-0.424481515 (-58.23%)** | **PASS** |
| Severe rows | 3,893 (4.223% of rows) | 3,405 (3.694%) | **-488** | **PASS** |
| Newly severe rows | - | 2,460 (2.669%) | cap 1,065 (1.155%) | **BLOCK** |
| Retired severe rows | - | 2,948 | retired > new | PASS component |

The fixed-tail positive-excess reductions by score date were all positive:
July 27 `+0.109130`, July 28 `+0.095659`, July 29 `+0.102971`, and July 30
`+0.116722`. The accepted headline described 4.26% of rows carrying 60.2% of
positive excess over the full window; this four-day score subset reproduces
the same concentration at 4.223%, and the candidate removes 58.23% of that
fixed-tail excess.

On 6,330 materially bound snapshots, the available band-relative proxy also
improved: three-way Brier `0.273697 -> 0.196651`, mode accuracy
`58.99% -> 62.65%`, and both floor-band and one-above one-vs-rest Brier moved
down. It cannot qualify the native gate because the accepted incumbent replay
does not contain its native bucket distribution.

## Failure attribution

Daily-first values below use the harness's per-band scale. Positive delta is a
loss relative to the incumbent.

| Stage | Brier | Delta versus incumbent | Finding |
| :--- | ---: | ---: | :--- |
| Incumbent | 0.052530132 | - | Reference |
| Continuation objective, temperature, and lossless `F+D` translation | 0.054125063 | **+0.001594931** | Objective component loses |
| Hard-conditioned prior alone | 0.081084367 | **+0.028554235** | Largest standalone loss |
| Frozen conditioned-prior/model blend | 0.050160417 | **-0.002369714** | Pooled point improvement |

Translation is not the loss mechanism: native mass summed to one, every native
bucket mapped to exactly one band, and the harness found zero mapping mismatch.
The continuation objective is weak on its own, and the conditioned-prior
component carries the largest standalone loss. Their frozen blend nevertheless
improves the pooled point estimate and severe tail. The candidate fails because
that gain is unstable across market-days and redistributed into too many new
severe and catastrophic slices, not because translation lost mass.

## Protected slices against the pre-registered bar

Pooled improvement is `0.002369714`. `FAIL` means the slice's candidate-minus-
incumbent daily-first Brier exceeds that number by more than `1e-12`. The
harness also found 26 slices with at least one ordinary Brier, fixed-tail, or
severe-count regression flag; the table retains tail reduction and severe
counts so those additional failures remain visible.

| Dimension | Slice | Days | Snapshots | Brier delta | Fixed-tail reduction | Severe baseline -> candidate | Frozen bar |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :---: |
| D class | D0 | 48 | 3,224 | -0.010914 | +0.222277 | 1,629 -> 484 | **PASS** |
| D class | D1 | 23 | 232 | +0.002559 | +0.006266 | 39 -> 66 | **FAIL** |
| D class | D2plus | 48 | 4,869 | +0.004101 | +0.195938 | 2,210 -> 2,840 | **FAIL** |
| D class | no_floor | 14 | 55 | 0.000000 | 0.000000 | 15 -> 15 | **PASS** |
| Binding strength | >1e-6 to 1% | 33 | 1,995 | +0.007064 | +0.108613 | 1,107 -> 1,167 | **FAIL** |
| Binding strength | >1% to 5% | 47 | 2,667 | +0.004903 | +0.052756 | 811 -> 1,257 | **FAIL** |
| Binding strength | >20% | 33 | 1,847 | -0.007972 | +0.209101 | 1,335 -> 423 | **PASS** |
| Binding strength | >5% to 20% | 47 | 1,816 | -0.002371 | +0.054011 | 625 -> 543 | **PASS** |
| Binding strength | no_floor | 14 | 55 | 0.000000 | 0.000000 | 15 -> 15 | **PASS** |
| Capture hour | 0 | 48 | 347 | -0.008244 | +0.027329 | 161 -> 103 | **PASS** |
| Capture hour | 1 | 48 | 325 | -0.012303 | +0.025463 | 147 -> 111 | **PASS** |
| Capture hour | 2 | 48 | 323 | -0.006711 | +0.021838 | 145 -> 110 | **PASS** |
| Capture hour | 3 | 48 | 315 | +0.008146 | +0.008237 | 121 -> 173 | **FAIL** |
| Capture hour | 4 | 48 | 318 | +0.004968 | +0.010461 | 145 -> 182 | **FAIL** |
| Capture hour | 5 | 48 | 357 | -0.002988 | +0.018807 | 166 -> 178 | **PASS** |
| Capture hour | 6 | 48 | 341 | -0.001681 | +0.016324 | 160 -> 163 | **PASS** |
| Capture hour | 7 | 48 | 345 | -0.002671 | +0.016477 | 184 -> 196 | **PASS** |
| Capture hour | 8 | 48 | 353 | +0.003292 | +0.017340 | 187 -> 201 | **FAIL** |
| Capture hour | 9 | 48 | 377 | +0.007051 | +0.010455 | 158 -> 223 | **FAIL** |
| Capture hour | 10 | 48 | 376 | +0.011843 | +0.011641 | 166 -> 301 | **FAIL** |
| Capture hour | 11 | 48 | 383 | +0.007601 | +0.016351 | 147 -> 209 | **FAIL** |
| Capture hour | 12 | 48 | 365 | -0.004290 | +0.020012 | 223 -> 212 | **PASS** |
| Capture hour | 13 | 48 | 367 | +0.011836 | +0.009359 | 144 -> 281 | **FAIL** |
| Capture hour | 14 | 48 | 357 | +0.018144 | +0.004348 | 156 -> 316 | **FAIL** |
| Capture hour | 15 | 48 | 358 | +0.001069 | +0.012798 | 149 -> 167 | **PASS** |
| Capture hour | 16 | 48 | 344 | -0.003286 | +0.012490 | 158 -> 151 | **PASS** |
| Capture hour | 17 | 48 | 354 | -0.005742 | +0.014780 | 125 -> 85 | **PASS** |
| Capture hour | 18 | 48 | 342 | -0.014380 | +0.020250 | 146 -> 18 | **PASS** |
| Capture hour | 19 | 48 | 351 | -0.013516 | +0.020905 | 177 -> 11 | **PASS** |
| Capture hour | 20 | 48 | 353 | -0.015380 | +0.028172 | 210 -> 12 | **PASS** |
| Capture hour | 21 | 48 | 344 | -0.014888 | +0.024018 | 193 -> 2 | **PASS** |
| Capture hour | 22 | 48 | 349 | -0.016069 | +0.029495 | 174 -> 0 | **PASS** |
| Capture hour | 23 | 48 | 336 | -0.016047 | +0.027132 | 151 -> 0 | **PASS** |
| Floor source | none | 14 | 55 | 0.000000 | 0.000000 | 15 -> 15 | **PASS** |
| Floor source | unknown | 48 | 8,325 | -0.002334 | +0.424482 | 3,878 -> 3,390 | **PASS** |
| Forecast-relative winner | +0 | 27 | 2,476 | +0.015080 | +0.060539 | 794 -> 1,369 | **FAIL** |
| Forecast-relative winner | +1 | 14 | 977 | +0.003432 | +0.035768 | 523 -> 466 | **FAIL** |
| Forecast-relative winner | +2 | 2 | 134 | -0.022031 | +0.001097 | 10 -> 25 | **PASS** |
| Forecast-relative winner | -1 | 37 | 2,817 | -0.011795 | +0.153431 | 1,514 -> 1,134 | **PASS** |
| Forecast-relative winner | -2 | 20 | 1,635 | -0.016194 | +0.147111 | 858 -> 358 | **PASS** |
| Forecast-relative winner | <=-3 | 6 | 174 | -0.015399 | +0.006241 | 58 -> 41 | **PASS** |
| Forecast-relative winner | unknown | 5 | 167 | -0.018721 | +0.020295 | 136 -> 12 | **PASS** |
| Market | Atlanta | 4 | 717 | -0.002194 | -0.000433 | 52 -> 306 | **PASS** |
| Market | Austin | 4 | 697 | +0.005674 | +0.034077 | 385 -> 305 | **FAIL** |
| Market | Chicago | 4 | 714 | +0.002261 | +0.068484 | 429 -> 351 | **PASS** |
| Market | Dallas | 4 | 691 | -0.024652 | +0.036950 | 512 -> 155 | **PASS** |
| Market | Denver | 4 | 688 | +0.005877 | +0.020804 | 226 -> 418 | **FAIL** |
| Market | Houston | 4 | 691 | -0.008052 | +0.041323 | 391 -> 282 | **PASS** |
| Market | Los Angeles | 4 | 676 | -0.022538 | +0.115910 | 541 -> 236 | **PASS** |
| Market | Miami | 4 | 696 | -0.008931 | +0.039972 | 475 -> 247 | **PASS** |
| Market | NYC | 4 | 699 | +0.022357 | +0.000157 | 82 -> 237 | **FAIL** |
| Market | San Francisco | 4 | 689 | -0.013959 | +0.059501 | 356 -> 128 | **PASS** |
| Market | Seattle | 4 | 698 | +0.006053 | +0.003279 | 242 -> 335 | **FAIL** |
| Market | Toronto | 4 | 724 | +0.009668 | +0.004458 | 202 -> 405 | **FAIL** |

The 19 catastrophic failures are concentrated in `D1`/`D2plus`, weakly bound
rows, hours 3-4, 8-11, and 13-14, forecast-relative `+0`/`+1`, and Austin,
Denver, NYC, Seattle, and Toronto. The strong late-day gains do not erase those
failures. Atlanta is a separate ordinary slice blocker: its pooled Brier passes
the catastrophic bar but its fixed-tail excess regresses and severe count
rises sharply.

## What the harness could not judge

1. **Canonical floor source/disposition.** The accepted floor trace predates
   those fields, so all 8,325 floor-available rows remain `unknown`; the corpus
   and paired floor-decision receipt gates are NOT_EVALUABLE.
2. **Native incumbent continuation.** Candidate native output is complete and
   maps losslessly, but the incumbent accepted replay is band-only. Native
   probability mass and native near-floor qualification cannot be claimed.
3. **Candidate-specific exact calibration.** This research fit uses the frozen
   conditioned-prior/model blend plus an exact hard floor, not a refitted
   production exact-distribution calibrator.
4. **Train/serve and captured-input parity.** No candidate artifact reader or
   production serving constructor was rolled, and no inactive candidate
   release exists. The parity and exact replay receipts are absent.
5. **Release binding.** Release #1 does not exist and the mission forbids
   touching it, so graph completeness, immutable roles, pre-pickle
   verification, and pointer invariance remain NOT_EVALUABLE.

These are evidence limits, not passes. The available band-level statistical
failures already reject this candidate without relying on any unavailable
gate.

## Evidence and guardrails

Verification completed with 41 focused candidate, harness, schema-registry,
import-architecture, and agent-documentation tests passing; the agent docs
audit passed; and the changed modules plus `app`, `src`, and `tests` compiled.
The repository-wide suite reached 3,280 passed tests, 820 passed subtests, and
4 skips. Its 17 unrelated Windows integration failures are host constraints:
13 experiment-executor fixtures exceed the legacy Windows path limit from this
deep linked-worktree path (`WinError 206`, independently reproduced), and four
PowerShell task/provenance fixtures are blocked by this runner's script
execution policy. No candidate or harness test failed.

| Output | SHA-256 |
| :--- | :--- |
| Research candidate artifact | `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85` |
| Candidate summary | `28d48154a194ebb9ad2c0e93246e32a4e9c08bc9502dde2867b19f69cca0e189` |
| Candidate replay rows | `f616bfa24306ee0cbbd08e9d38617c7843011651991f53d79ef750b595a95763` |
| Candidate native distributions | `9636d22103199a55155f181478c183318e12f7f880af43817ce439e428bff89b` |
| Harness scorecard | `f8749577b8f9ea10655b81f10144ee86d7b7aaf70d775feb01bb7782716357a0` |
| Protected slices | `77a5f9423fc25604521ac0eb0ac8bdeb9016e7591d573c3c1252901b6e5cb17a` |
| Harness report | `03a5c2b62e97efee76fadb04455cfd0b34b98ade5d52ce1b12661ab1247e12c3` |

Every output is beneath the one declared run root outside the mirror. `data/`
and the replay mirror remained read-only. No reserved forward date, production
host, sync credential, paid provider, release, promotion, pointer, serving,
scheduler, capture, mirror topology, or ACL state was accessed or changed. No
PR, merge, or master push was made.
