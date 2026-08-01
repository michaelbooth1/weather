# Workstation centre-mechanism diagnosis — 2026-08-01

## Verdict

**The dominant hour-shaped displacement is manufactured when the incumbent
distribution is truncated at the trusted observed-high hard floor, not by
`forecast_centering` or `current_blend_alpha`.** The negative of that stage's
mean centre movement has `0.9882` correlation with the accepted 24-hour offset
profile. Before the floor, the market-minus-model centre remains positive at
every capture hour (`+0.392` to `+0.808` bands after live signals). The floor
creates the sign change (`-0.581` to `+0.485`); the plausible-high cap then
brings the cumulative 288-cell trace to `0.9948` correlation with the final
accepted displacement. Hour-aware exact-distribution calibration amplifies the
remaining shape but is not its source.

The complete per-market × hour surface is nevertheless **emergent, not a
single-constant defect**. The hard floor alone correlates only `0.4045` with
the 288 individual cells. The upstream HGB path cools the climatology prior by
`0.5497` ordered bands on average; the observation floor warms it by `0.5745`;
the plausible cap cools it by `0.2693`; smaller centering, floor, and
calibration stages finish the result. All 10,885 snapshots used HGB, so a
regime-router switch is not responsible.

Classification: **inherent modelling choices interacting through the day,
with a centre-moving calibration side effect; not a routing bug and not a
mis-set forecast/current blend constant.** The physical floor is doing what its
contract says. Its deterministic interaction with a cool pre-floor
distribution makes the disagreement predictable from market and clock time
alone. This traces market-minus-model disagreement; it does not prove that the
market, rather than the model, is correct when the market centre remains below
an already observed settlement floor.

## Scope and exact reproduction

| Field | Value |
| :--- | :--- |
| Source | exact `origin/master` `e200a42c216e8b492403d335b0a355531eef852d` |
| Topic branch | `codex/workstation-centre-mechanism-2026-08-06a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\centre-mechanism-2026-08-06a` |
| Declaration | `2026-08-01T22:13:39Z`, before the trace |
| Evidence re-read | 2026-07-22 through 2026-07-26 only |
| Scale | 10,885 snapshots; 60 market-days; 288 market × capture-hour cells |
| Active route | HGB on 10,885 / 10,885 snapshots |
| Final trace versus accepted replay | maximum absolute centre difference `0.0` |
| Reproduced fitted offsets | maximum absolute difference `1.33e-15` |
| Reserved forward window | 2026-08-06 through 2026-08-19; **not read or evaluated** |

The trace used the accepted pinned replay corpus and accepted fitted-offset
table; it did not refit either one. The replay-row SHA-256 remains
`bc1d4e80d65c98274be6d976ead97a391467124304fba14081e47a11aee5b2e8`,
and the fitted-offset SHA-256 remains
`1596c293ae316c97005a14f82e12dd9c6bd0440a047ed045703ce026253f9042`.
The trace retained each intermediate distribution, converted it through the
same ordered market bands, and asserted final equivalence snapshot by
snapshot. No decision was taken from July 27–30.

For the tables below, `stage effect` is expected ordered-band index after the
stage minus before it; positive moves the model warmer/higher. The accepted
target is market centre minus final model centre, so the profile comparison is
`correlation(-stage effect, accepted target)`.

## Centre path from inputs to served bands

The incumbent path is:

1. Load WU history/current and supporting observation/forecast sources; derive
   the effective cutoff, trusted current maximum, effective observed high,
   forecast ensemble, physical guidance states, and hard-floor bucket
   (`src/weather/model/model_distribution.py:139-334`).
2. Start from the local-history or climatology prior, select the effective-hour
   HGB component, ordinal-smooth it if configured, and blend it with the prior
   using the bundle's hour-specific feature weight
   (`model_distribution.py:745-810`, `model_features.py:91-104`).
3. Apply the sequential distribution stages listed below
   (`model_distribution.py:411-555`).
4. Convert the final native-unit distribution to each ordered market band.
   Market-bin calibration preserves distribution coherence, so it does not
   independently move this centre
   (`src/weather/model/calibration_runtime.py:518-526` and the tracked
   `probability_calibration*.json` artifacts).

Every production/replay stage was retained. A zero means the stage was a no-op
on this exact fit window, not that the function can never move a distribution.

| Order | Stage | Observed action in this window | Active snapshots | Mean signed effect (bands) | Hour-profile match | Cumulative 288-cell match to final |
| ---: | :--- | :--- | ---: | ---: | ---: | ---: |
| 0 | Climatology/local prior | Baseline distribution | — | — | — | 0.3698 |
| 1 | HGB model path + feature blend | Cool shift | 10,885 | -0.5497 | -0.5099 | 0.4392 |
| 2 | Bucket transition | No-op | 0 | 0.0000 | — | 0.4392 |
| 3 | Live forecast/current signals | Small warm reweighting | 10,633 | +0.0593 | -0.0269 | 0.4387 |
| 4 | Trusted observed-high hard floor | Remove mass below the physical floor | 10,837 | **+0.5745** | **0.9882** | **0.9418** |
| 5 | Intraday tail target | No-op | 0 | 0.0000 | — | 0.9418 |
| 6 | Plausible-high cap | Cool the upper tail | 10,562 | -0.2693 | 0.3752 | **0.9948** |
| 7 | Forecast-shape stage | Skipped on the feature-model path | 0 | 0.0000 | — | 0.9948 |
| 8 | Ramp warm-tail dampening | Negligible cool shift | 163 | -0.0005 | 0.2187 | 0.9948 |
| 9 | Afternoon residual centering | Cool shift in active local-hour contexts | 1,814 | -0.0386 | **-0.5391** | 0.9760 |
| 10 | Validated current-max floor | No additional movement after the hard floor | 0 | 0.0000 | — | 0.9760 |
| 11 | Settlement-lag floor | Negligible warm shift | 976 | +0.0012 | -0.2730 | 0.9760 |
| 12 | Current-observed floor | Small warm shift | 10,781 | +0.0096 | 0.5250 | 0.9833 |
| 13 | WU floor residual | Numerical no-op | 0 | 0.0000 | — | 0.9833 |
| 14 | Late-day continuation | No-op | 0 | 0.0000 | — | 0.9833 |
| 15 | Late-day lock-in | Numerical no-op | 0 | 0.0000 | — | 0.9833 |
| 16 | Exact-distribution overconfidence calibration | Hour-aware temperature reshaping | 10,880 | +0.0351; mean absolute 0.0757 | **0.8304** | 1.0000 |
| 17 | Current-max boundary guard | Numerical no-op | 0 | 0.0000 | — | 1.0000 |

The explicitly hour-conditioned afternoon-centering artifact does not match the
symptom: its hour-profile correlation has the wrong sign, and adding it reduces
the cumulative cell correlation from `0.9948` to `0.9760`. It is not the source
of the displacement.

## Where the clock shape appears

Selected capture hours show the phase change. Residual columns are market
centre minus the model centre after the named stage.

| Capture hour | Accepted final offset | After HGB/model path | Hard-floor shift | After hard floor | After plausible cap | Exact-calibration shift |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | -0.173 | +0.475 | +1.018 | -0.581 | -0.137 | +0.036 |
| 5 | +0.827 | +0.554 | +0.051 | +0.461 | +0.785 | -0.045 |
| 11 | +0.775 | +0.761 | +0.204 | +0.485 | +0.747 | -0.026 |
| 15 | +0.102 | +0.889 | +0.892 | -0.084 | +0.118 | +0.067 |
| 17 | -0.209 | +0.803 | +1.091 | -0.351 | -0.146 | +0.190 |
| 20 | -0.326 | +0.754 | +1.168 | -0.470 | -0.229 | +0.138 |

The HGB/model path creates a broad cool displacement relative to the market,
but not the accepted hour profile. Its raw HGB component cools the prior by
`0.7374` bands on average, and the feature blend retains `0.7524` of that
movement. The inferred feature-blend weight rises from about `0.65` in early
capture-hour cells to `0.8725` late. Although that parameter is hour-keyed, it
has the wrong causal sign: `correlation(-model-path effect, target)` is
`-0.5099` by hour, and the blend weight itself correlates `-0.9479` with the
target profile. Increasing HGB weight makes the already-cool component more
important while the observed target is turning negative.

The hard floor is different. It has no hour-specific alpha. It applies a
`0.000001` multiplier to buckets below the trusted observed maximum
(`model_distribution.py:944-950`). Its clock shape comes from the normal
intraday evolution of the observed high and from the amount of pre-floor mass
left below it. That is why an hour-only lookup predicts the symptom even though
the stage consumes weather observations.

The plausible cap then cools the post-floor upper tail. Together, HGB path,
hard floor, and cap already produce nearly the complete market × hour surface.
The final exact-distribution calibrator selects `temperature_by_hour` using the
effective cutoff (`src/weather/model/calibration_runtime.py:351-416`). On an
asymmetric, floor-truncated distribution, temperature scaling is not
centre-neutral. Its own hour profile aligns at `0.8304` and it accounts for the
last mean absolute `0.0757` bands, but the displacement geometry already exists
before it.

## Explicit forecast/current-blend test

The named suspect is ruled out in two independent ways.

First, `forecast_centering` and `current_blend_alpha` belong to the pooled
candidate/shadow postprocessing path. Forecast centering runs only when the
candidate postprocess flag is enabled
(`src/weather/model/variant_prediction_runtime.py:894-903`). Live current blend
combines a candidate band probability with the incumbent
`band["model_probability"]`
(`src/weather/collection/live_variant_predictions.py:659-691`); replay current
blend combines `candidate_p` with the already-produced incumbent `replayed_p`
(`src/weather/calibration/pooled_candidate_replay.py:1409-1424`). Those stages
can pull a candidate toward the incumbent, but they cannot manufacture the
incumbent displacement measured here.

Second, the incumbent's actual forecast/current interaction was traced rather
than inferred. On the HGB path, current maximum and forecast cluster are merged
into a peak signal and multiplicatively reweight the distribution
(`model_distribution.py:1321-1354`, `1439-1447`). This live-signal stage moved
the centre only `+0.0593` bands on average; its hourly effects range from
`+0.0261` to `+0.0924`, and its profile match is `-0.0269`. There is no evidence
that a mis-set forecast/current blend weight creates the symptom.

The observation-weighting intuition was directionally useful but named the
wrong mechanism: the material current-observation action is the hard physical
floor, not a convex blend alpha.

## Bug / constant / modelling-choice classification

- **Bug: no evidence.** Final results reproduce the accepted replay exactly;
  all snapshots route through HGB; candidate-only postprocessors are not being
  accidentally applied; and the stage order follows the documented call path.
- **Mis-tuned constant: not the primary diagnosis.** Feature blend is
  hour-keyed but points the wrong way. Afternoon centering also fails the
  profile test. Exact-distribution temperature is hour-keyed and amplifies the
  final `0.0757`-band remainder, but it is intentionally optimizing
  overconfidence, not centre, so this trace alone does not establish that its
  constant is wrong under its owning objective.
- **Inherent/emergent modelling choice: yes.** A cool HGB/prior blend is
  followed by a physically necessary observed-high truncation, an upper-tail
  cap, and non-centre-neutral probability calibration. Their activation and
  asymmetry evolve predictably with local time. No one stage explains the full
  288-cell surface, but the hard floor explains the clock-shaped phase change.

## Hypothetical fix and roll footprint — not implemented

Do **not** weaken or soften the trusted observed-high floor to make the centre
look more like the market. That would restore probability mass to temperatures
that the settlement high has already exceeded and would trade an explanatory
disagreement for a correctness defect.

The smallest safe source-directed experiment would keep the floor invariant
and make the distributions around it coherent:

1. constrain or retrain the effective-hour HGB distribution so it does not
   repeatedly place material mass below an already known floor; and
2. require exact-distribution calibration to preserve the expected centre (or
   explicitly gate mean drift) after floor truncation while retaining its
   probability-calibration objective.

The second item alone would address only the final `0.0757` mean-absolute-band
amplifier, not the main phase change. A complete source fix would touch the HGB
training/feature contract and per-market feature artifacts, base distribution
assembly in `src/weather/model/model_distribution.py`, calibration runtime and
trainer parity, and the per-market probability-calibration artifacts. That is
a **roll-sensitive serving-model and artifact change** requiring fresh
train/serve parity evidence, captured-input replay, full probability-mass and
floor-invariant checks, release binding, and an operator-timed roll. A post-hoc
market × hour shift would be smaller code but would be the symptom corrector
this mission explicitly declined to refine.

## Evidence and guardrails

All generated evidence is under the single declared run root outside the
mirror:

- `investigation-declaration.md` — frozen boundary and questions; SHA-256
  `785a76eee10f66c1e2e02f24eb48eaa75edf45c77440fc95545381e083e22152`.
- `trace_centre_stages.py` — deterministic retained-stage trace; SHA-256
  `5f41ff86634bb666549a6d32903ef4599a974bac1e6cdf501c7135652df0e0bc`.
- `full-mechanism-summary.json` — scope, routes, exact checks, and stage
  summaries; SHA-256
  `637d9e1001755128798e3f82632e8600cc3ef4c9abecbb84eb129f79ed4d9a58`.
- `full-stage-summary.csv` — one row per sequential stage; SHA-256
  `f21679b29f1a3ab3cbd1683d47ac33eede81be9162b09ac5a881c124c31570e1`.
- `full-hour-profile.csv` — accepted and traced profiles by capture hour;
  SHA-256
  `b82ea75b6ee07219d5a3ab6172bb9ee373f1ab030b342934419e826e9b314ebb`.
- `full-stage-cell-profile.csv` — all 18 stages × 288 cells; SHA-256
  `9929ec9131f518db630c71d58eb613541d2ebe52c0b4a4ee64a626464e45634c`.
- `full-snapshot-stage-centres.csv` — 206,815 retained sequential/component
  rows; SHA-256
  `a6988b21eb5dddcf7db3e06c3082f7dbc461405ddd25a7ac238a3c075172d1bb`.
- `feature-component-v2-summary.json` and
  `feature-component-v2-hour-profile.csv` — descriptive, no-fit HGB component
  and blend attribution; SHA-256
  `ad679718c0fd93bb4ff592c1cfb5715a81ac8c124cc72b8be9d5b038b8f97b2f`
  and
  `75733bdacc29da121604ada1f93a0ee561c0c069161b6ee93657eb2b0a3646a1`.

`data/` and the mirror remained read-only. No fit, candidate, correction,
transform, parameter or production-artifact change, PR, merge, master push,
promotion, pointer, serving, scheduler, capture, mirror, or ACL change
occurred. No sync credential was read or exposed.
