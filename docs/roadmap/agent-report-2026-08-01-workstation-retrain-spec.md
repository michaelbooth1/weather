# Workstation floor-preserving retrain specification - 2026-08-01

## Verdict

**The incumbent HGB consumes the observed floor. The objective fork wins.**
Across the 12 per-market HGB artifacts that produce the base temperature
distribution, all 168 market/hour bundles select the observed-high family and
all 168 split on it. `high_so_far` alone accounts for 267,253 tree splits
(17.63% of all 1,515,766 splits); the broader declared family accounts for
470,866 (31.06%). Direct `high_so_far` use rises from 6.87% of splits at hour 7
to 40.90% at hour 20. This is actual model consumption, not merely a field
present in a live dictionary.

The `feature_subset = "all"` metadata quoted in the handoff belongs to the
separate pooled direct-band artifact
`feature_model_hgb_f_pooled_v0_3.pkl`, not the per-market base HGBs that
produced the accepted `replayed_p`. I inventoried it separately. It also
consumes `high_so_far` at every hour, although lightly: 575 direct splits and
998 broad floor-family splits out of 37,765. Its selected current-max and
explicit band-relative floor fields have zero splits. That distinction changes
none of the conclusion: both relevant readings reject the claim that the model
is blind to the ordinary observed high.

The retrain should therefore change the learned quantity, not add another copy
of the same predictive signal. For a cutoff-time canonical floor bucket `F`
and final settlement bucket `Y`, the floor-available lane must predict the
non-negative continuation

`D = Y - F`, with `D in {0, 1, 2, ...}`,

then translate `P(D=d | X, F, floor_available)` to the absolute bucket
`F + d`. Its local-history/climatology prior must be conditioned to the same
support before blending. The exact canonical `F` is a control and target
origin, not a newly optimized weather feature. The existing hard-floor stages
remain in place as an independent defense.

This is a specification only. Nothing was fitted, trained, scored as a
candidate, written under `data/`, promoted, or served.

## Scope and read-only inventory

| Field | Value |
| :--- | :--- |
| Source | exact `origin/master` `cee1f2db09f310b65bbe018c58f3b50241bbc03a` |
| Topic branch | `codex/workstation-retrain-spec-2026-08-08a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\retrain-spec-2026-08-08a` |
| Declaration | `2026-08-01T23:51:00.6675122Z`, before any artifact result was inspected |
| Operation | deserialize tracked model artifacts; read selected names and sklearn HGB tree nodes; write only inventory evidence under the run root |
| Base serving inventory | 12 artifacts; hours 7-20; 168 bundles; 232,400 trees |
| Structural validation | 0 invalid feature indexes; 0 trees missing the required node schema |
| Reserved forward window | 2026-08-06 through 2026-08-19; **not enumerated, read, or evaluated** |

The inventory used the repository artifacts on the exact base. The base model
loader reads `feature_model_hgb{artifact_suffix}.pkl`
(`src/weather/model/model_features.py:54-71`), model identity fingerprints the
same template (`src/weather/model/model_identity.py:38-46`), and the immutable
release contract binds one such `feature_hgb` role per market
(`src/weather/operations/release_candidate_contract.py:253-289`). Those are
the artifacts that underlie the accepted base HGB replay.

### Base serving HGB: selected names and splits by hour

Every row aggregates the 12 market artifacts. All 168 bundles selected
`high_so_far`, `forecast_gap`, and `hours_at_peak`; the 98 bundles for seven
markets with the later observation schema also selected
`live_reading_minus_high`. Every bundle split on at least one member of that
family. More specifically, `high_so_far` had non-zero splits in 168 / 168
bundles, `hours_at_peak` in 166 / 168, `forecast_gap` in 154 / 168, and
`live_reading_minus_high` in all 98 bundles that selected it. None of the
serving-base artifacts selected a `trusted_current_max` or current-max
trust-state field; their frozen feature schemas predate that family.

| Effective hour | Bundles selecting family / any family split | `high_so_far` | `forecast_gap` | `hours_at_peak` | `live_reading_minus_high` | Broad family / all splits |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 12 / 12 | 7,427 | 7,841 | 2,371 | 6,222 | 23,861 / 108,152 |
| 8 | 12 / 12 | 6,099 | 7,213 | 2,806 | 5,192 | 21,310 / 108,023 |
| 9 | 12 / 12 | 6,665 | 7,151 | 2,390 | 4,745 | 20,951 / 108,136 |
| 10 | 12 / 12 | 7,307 | 7,226 | 2,231 | 4,872 | 21,636 / 108,277 |
| 11 | 12 / 12 | 7,721 | 6,913 | 1,653 | 3,872 | 20,159 / 108,431 |
| 12 | 12 / 12 | 8,853 | 7,259 | 1,885 | 4,516 | 22,513 / 108,301 |
| 13 | 12 / 12 | 10,570 | 7,059 | 1,863 | 6,455 | 25,947 / 108,593 |
| 14 | 12 / 12 | 14,566 | 7,040 | 1,918 | 7,998 | 31,522 / 108,136 |
| 15 | 12 / 12 | 19,326 | 6,994 | 2,523 | 6,455 | 35,298 / 108,356 |
| 16 | 12 / 12 | 25,720 | 6,249 | 2,595 | 6,150 | 40,714 / 108,461 |
| 17 | 12 / 12 | 32,008 | 5,215 | 3,052 | 6,024 | 46,299 / 108,396 |
| 18 | 12 / 12 | 36,618 | 5,003 | 2,917 | 5,690 | 50,228 / 108,309 |
| 19 | 12 / 12 | 40,196 | 4,513 | 2,430 | 6,412 | 53,551 / 108,177 |
| 20 | 12 / 12 | 44,177 | 4,755 | 2,556 | 5,389 | 56,877 / 108,018 |
| **Total** | **168 / 168** | **267,253** | **90,431** | **33,190** | **79,992** | **470,866 / 1,515,766** |

This late-day increase is consistent with the observed high becoming a more
decisive predictor as the day resolves. A zero-split test would have supported
the missing-feature fork; the result is the opposite.

### The quoted pooled `feature_subset = all` artifact

The pooled v0.3 direct-band artifact selects 21 declared observed-high,
current-max, and band-relative floor fields in each hour's 278-column schema.
Only four ever split: `high_so_far` (575), `hours_at_peak` (406),
`forecast_gap` (5), and `nbm_prob_tmax_floor_gap` (12). Every selected explicit
current-max trust field and every selected explicit band/floor-relative field
has zero splits. Nevertheless, direct `high_so_far` has non-zero use at all 14
hours, so this model also cannot be described as floor-blind.

| Hour | `high_so_far` | `hours_at_peak` | Other floor-family | Broad family / all splits |
| ---: | ---: | ---: | ---: | ---: |
| 7 | 3 | 33 | 2 | 38 / 2,700 |
| 8 | 3 | 17 | 0 | 20 / 2,700 |
| 9 | 5 | 9 | 0 | 14 / 2,700 |
| 10 | 6 | 3 | 1 | 10 / 2,700 |
| 11 | 5 | 4 | 0 | 9 / 2,700 |
| 12 | 4 | 7 | 1 | 12 / 2,700 |
| 13 | 4 | 4 | 0 | 8 / 2,700 |
| 14 | 8 | 10 | 1 | 19 / 2,700 |
| 15 | 1 | 23 | 1 | 25 / 2,700 |
| 16 | 1 | 15 | 1 | 17 / 2,700 |
| 17 | 34 | 35 | 0 | 69 / 2,700 |
| 18 | 72 | 63 | 0 | 135 / 2,700 |
| 19 | 38 | 23 | 1 | 62 / 2,700 |
| 20 | 391 | 160 | 9 | 560 / 2,665 |
| **Total** | **575** | **406** | **17** | **998 / 37,765** |

## Specification

### 1. Hypothesis and boundary

The candidate hypothesis is:

> The incumbent is trained to predict an unconditional absolute final high,
> even when the runtime knows a valid lower bound. Re-expressing the target and
> the complete HGB/prior blend as a distribution of continuation above that
> bound will improve joint centre, scale, and near-floor modal allocation while
> preserving full-distribution Brier and the physical floor.

This is deliberately narrower than a general feature upgrade. Freeze, for each
market and hour, the parent release's exact `feature_names` and ordering.
Refit preprocessing on those columns inside each training fold, but do not
activate newly available weather columns, current-max columns, a market-price
feature, or a market x hour correction. The canonical floor is added as a
target/decode control, not to the HGB predictor matrix. This makes the first
experiment an objective test rather than an objective-plus-feature bundle.

The one necessary contract refinement is that training and serving must carry
the **same canonical floor bucket**. Live code currently computes

`F = max(effective_observed_floor_bucket, validated_current_max_floor_bucket)`

in `src/weather/model/model_distribution.py:285-303`. The training record must
derive that value through the same pure contract, including the WU-authoritative
path, empty-WU current-observation rescue, and the market-specific validated
current-max rule. Do not substitute `round(high_so_far)` when the canonical
floor is higher. Record the floor bucket, source/disposition, effective time,
and availability as control metadata. This closes exact parity for the rare
rescue/current-max case without changing which observation is authoritative.

### 2. Training target and loss

For each point-in-time training row:

- `Y` is the canonical final settlement high rounded once in the market's
  native settlement unit by the existing settlement rule.
- `F` is the canonical hard-floor bucket computable solely from source state at
  that row's effective cutoff.
- A floor-available row is valid only when both are integers and `Y >= F`.
  Any `Y < F` row is a corpus blocker with its provenance retained; it must
  never be clipped to zero or silently discarded.
- The label is `D = Y - F`. Thus `D=0` means the observed floor becomes the
  settled high, `D=1` means one native bucket of continuation, and `D>=2`
  carries the remaining upper tail.
- Fit the per-market, effective-hour HGB classifier to multiclass `D` with the
  existing cutoff-safe feature matrix. Fit the LR fallback to the same label.
  Class support is a declared contiguous non-negative native-bucket range; a
  fold lacking a class may emit zero model mass for it, but smoothing from the
  conditional prior must keep the declared evaluation support coherent.

The ordinary multiclass log loss remains the fitting loss so the model learns
a proper distribution. Model, temperature, and blend selection use nested
blocked out-of-fold predictions only. Selection is lexicographic:

1. reject any setting that regresses total full-distribution Brier or violates
   a hard safety gate;
2. among survivors, minimize full conditional-distribution Brier;
3. use Brier on the declared near-floor partition (`D=0`, `D=1`, `D>=2`) as the
   tie-break, then log loss.

No class reweighting may be chosen from July 27-30. If class weighting is later
proposed, it is a new predeclared experiment; it is not part of this first
objective test.

### 3. Conditional prior, blend, and decode

Changing only the HGB label is insufficient because the runtime currently
blends the HGB distribution with an unconditional local-history/climatology
prior (`src/weather/model/model_distribution.py:263-337,745-810`). The
candidate floor-available lane must do all of the following before any live
signal stage:

1. Obtain the existing absolute local-history or climatology prior `P0(Y=b)`.
2. Hard-condition it per row: set `P0(Y=b)=0` for `b<F` and renormalize over
   `b>=F`. This conditioning uses exact zero, not the later `1e-6` defensive
   multiplier.
3. Temperature-scale the HGB continuation distribution only on `D>=0`, then
   decode it to absolute buckets with `b=F+D`.
4. Blend the conditioned prior and decoded HGB distribution with the nested-OOF
   selected feature weight. Both inputs now have support only at or above `F`.
5. Continue through the existing live-signal, hard-floor, cap, residual,
   continuation, lock-in, and exact-calibration stages. The existing trusted
   hard floor at `model_distribution.py:442,944-949` is retained unchanged as
   defense in depth. Exact-distribution calibration continues to hard-zero
   sub-floor buckets (`src/weather/model/calibration_runtime.py:351-412`).

Training evaluation must reproduce this same per-row conditioned prior,
temperature, blend, decode, and downstream path. Scoring a residual HGB by
itself is diagnostic only and cannot qualify the candidate.

### 4. Floor-unavailable and fallback lanes

The accepted replay had 103 / 19,265 snapshots without an active floor. A
continuation target is undefined there. The candidate release therefore binds
two explicit lanes per market/hour inside the verified base-model graph:

- **Floor available:** new conditional HGB, then conditional LR only. If both
  fail to materialize or decode, fail closed; do not silently route to an
  unconditional empirical distribution.
- **Floor unavailable:** an immutable copy of the parent release's absolute
  HGB/LR bundle and existing absolute-prior behavior. This lane is not refit in
  the objective experiment. Its subtree hash and parent release identity are
  recorded, and replay must prove it is prediction-identical to the parent.

The floor-available lane must never fall back to the parent absolute lane. The
release graph currently declares `bound_feature_hgb ->
bound_feature_lr_coefficients -> code_constant_empirical`
(`release_candidate_contract.py:371-378`); the new schema must make fallback
order lane-specific and serving must reject an old or incomplete route. No
ambient repository artifact is allowed after a release is bound.

### 5. Near-floor modal allocation

The target exposes the defect directly rather than through a post-hoc centre
shift. Every OOF and end-to-end evaluation record must retain:

- native `P(D=0)`, `P(D=1)`, and `P(D>=2)`;
- the ordered market band containing `F` and the immediately higher band;
- candidate/incumbent mode, settled winner, and whether each mode is the floor
  band, one above, or at least two above;
- conditional Brier for the three-way continuation partition;
- full 11-band Brier and severe-row membership.

On the materially bound subset, the candidate must improve three-way
near-floor Brier, improve settled-mode accuracy over the paired incumbent, and
not regress `D=0` or `D=1` one-vs-rest Brier separately. The accepted 22.64%
model settled-mode rate and 54.40% wrong-at-floor-or-one-above rate are
reference symptoms, not a promised candidate result and not permission to use
market prices as predictors.

### 6. Artifact and provenance contract

Introduce a new backward-readable artifact schema; do not overwrite or reinterpret
`feature_model_hgb_v0.2`. The new HGB and LR artifacts must record at least:

- `target_representation = continuation_from_canonical_floor_v1`;
- native unit, rounding contract, non-negative class support, and floor-control
  schema/version;
- exact per-hour parent feature-name list and its SHA-256;
- conditional HGB/LR model, imputer/scaler metadata, nested-OOF temperature and
  blend weight;
- immutable parent absolute-lane payload hash and parent release identity;
- training-corpus manifest, cutoff/effective-time contract, market-day grouped
  split plan, code/runtime identity, and leakage audit;
- OOF prediction and calibration receipts used to choose every parameter.

The final exact-distribution probability calibrator must be refit on the
candidate's nested OOF end-to-end distributions, constrained to preserve zero
sub-floor support. A stale calibrator trained on incumbent shapes is not
eligible. The late-day, forecast-error, settlement-lag, calibrated-weight, and
shared centering components are not retuned by this experiment; the immutable
candidate release rebinds their exact parent copies so the change remains
attributable.

## Qualification gates

All metrics compare candidate and incumbent on the exact same hash-bound
captured inputs, market rows, outcomes, market quotes, floor decisions, and
exclusion set. Aggregate by market-day first so a high-frequency capture loop
cannot dominate. Hard gates are conjunctive; no weighted score can compensate
for a failure.

| Gate | Frozen pass condition |
| :--- | :--- |
| Corpus and target | Every floor-available fitted/scored row has cutoff-available `F`, canonical source provenance, and `Y>=F`; zero clipped negative continuations; no target/outcome field enters predictors. |
| Total Brier non-regression | Paired mean full 11-band candidate Brier is no greater than incumbent overall. Report every market/hour slice; the one-sided 95% market-day-block bootstrap upper bound for candidate-minus-incumbent must be `<=0`. |
| Severe-tail improvement | On the incumbent-frozen `>=30` percentage-point market-right severe set, candidate daily-normalized positive excess Brier and severe-row count are both lower overall, and positive-excess reduction is positive on every confirmation date with eligible rows. Also report the unfrozen candidate severe set. |
| Newly severe cap | `new_severe_rows / eligible_band_rows <= 1,065 / (8,380 x 11) = 1.15535%`, the frozen rate implied by the accepted market x hour warning. On that original scale the cap is exactly 1,065. Candidate must retire more severe rows than it creates. This threshold is inherited evidence, not tuned on July 27-30. |
| Near-floor allocation | On materially bound rows, three-way (`D=0`,`D=1`,`D>=2`) Brier improves, settled-mode accuracy improves, and neither `D=0` nor `D=1` one-vs-rest Brier regresses. Report floor-band/one-above mode confusion by market and hour. |
| Probability mass | Every native distribution is finite, non-negative, and sums to 1 within `1e-12`; every mutually exclusive 11-band partition sums to 1 within `1e-12`; bucket-to-band mapping loses and duplicates no mass. |
| Floor invariant | Candidate and incumbent derive identical `F` and source/disposition from the same capture. Conditional-model, conditioned-prior, post-blend, post-hard-floor, post-calibration, and final served mass below `F` are exactly zero within `1e-12`. Bands made impossible by `F` receive their existing hard 0/1 answers. Raising `F` in a metamorphic fixture cannot leave mass below the raised floor. Existing hard-floor code and authority are unchanged. |
| Train/serve parity | Historical and live builders produce byte/canonical-value equivalent predictor fields and identical floor control from the same captured source payload, in both C and F markets. Artifact feature order, imputation, native NaN handling, class decode, prior conditioning, temperature, blend, and band conversion match. |
| Captured-input replay | Inactive-release replay through the production serving constructor exactly matches the candidate's recorded end-to-end probabilities within `1e-12`, route/lane, floor, artifact hashes, and release identity. Floor-unavailable rows exactly match the parent incumbent. Zero unbound/global fallback and zero unexpected empirical route rows. |
| Release binding | All changed and retained components are immutable manifest roles; complete per-market graph verification passes before any pickle is loaded; candidate build leaves the active pointer unchanged. |

Protected reports, not substitute gates, include total Brier and tail deltas by
market, capture hour, floor source, floor-binding strength, forecast-relative
winner position, and `D` class. A pooled pass with one catastrophic slice is a
review blocker even when the arithmetic hard gates pass.

## Leakage-safe execution and evaluation plan

Execution is blocked until release #1 exists. Once separately authorized after
that prerequisite, use this sequence:

1. **Freeze implementation and evidence contracts.** Land backward-compatible
   readers for both old and new artifact schemas. Freeze parent release,
   feature-name hashes, target/floor contract, training-data cutoff, split
   plan, hyperparameter grid, evaluation script, metrics, gates, and candidate
   output root before fitting.
2. **Historical blocked training.** Use the existing point-in-time historical
   training corpus, grouped by market-day. Preprocessing, HGB/LR fitting,
   temperature, blend, and exact-calibration selection occur inside nested
   chronological/blocked folds. A snapshot's later settlement may be its label
   but no post-cutoff source state may be a feature. Final refit may use only
   rows permitted by the frozen training cutoff.
3. **Development window.** July 22-26 is inspected development evidence. It
   may be used to reject or choose among the predeclared candidate settings and
   to run the full end-to-end gates, but every use is labeled development, not
   forward proof. Any final refit that incorporates these dates is frozen
   before forward confirmation.
4. **July 27-30 quarantine.** Do not fit, tune, select, alter a threshold, or
   qualify the candidate from this window. Prior published numbers may explain
   inherited gates, but no new candidate outcome is read there.
5. **Freeze the candidate.** Build one immutable inactive release with code,
   runtime, artifacts, parent lane, corpus, OOF, gate, and replay receipts. The
   active pointer remains unchanged.
6. **Declare August 6-19 completeness without outcomes.** Only after August 19
   closes, enumerate the expected dates/markets/capture identities, source and
   quote freshness, release identity, floor-control availability, duplicate
   policy, and exclusion reasons. Hash that manifest and candidate first while
   settlement outcomes and candidate scores remain uninspected. Do not replace
   a missing day or market.
7. **One confirmation run.** Join outcomes, run the frozen candidate and
   incumbent exactly once on the declared manifest, and evaluate every gate.
   No rerun, tuning, threshold change, candidate rebuild, or window swap is
   allowed after unblinding. A failed gate rejects the candidate.

The confirmation is evidence for the frozen objective experiment only. It is
not automatic promotion authority; the normal reviewed promotion and
market-day-boundary contracts still apply.

## Roll footprint, restart, and rollback

### Expected source footprint

The implementation is roll-sensitive. The minimum expected owners are:

- `src/weather/calibration/feature_model.py` and its report/calibration helpers:
  continuation target, fold-local conditional prior, HGB/LR fit, nested
  selection, new artifact receipts;
- `src/weather/model/model_base.py`,
  `src/weather/model/model_distribution_signals.py`, and/or one small shared
  pure helper: expose the existing canonical floor decision to historical and
  live builders without changing its authority;
- `src/weather/model/feature_store.py` and
  `src/weather/model/model_features.py`: floor-control parity, new/old schema
  loading, lane selection, continuation decode, conditional fallback;
- `src/weather/model/model_distribution.py` and
  `src/weather/model/calibration_runtime.py`: condition the prior before the
  feature blend and preserve exact support through downstream calibration;
- `src/weather/calibration/probability_calibration.py`: refit and report the
  candidate-specific floor-preserving exact calibrator;
- `src/weather/model/model_identity.py` and
  `src/weather/schema_registry_data.py`: new schema and replay identity;
- `src/weather/release_contract.py`,
  `src/weather/operations/release_candidate_contract.py`,
  `src/weather/release_serving.py`, and
  `src/weather/operations/nightly_retrain.py`: lane-complete graph, immutable
  component binding, fail-closed load, training step, and qualification
  receipts;
- focused model/calibration/release tests plus the owning README, architecture,
  nightly-retrain, and artifact-storage documentation.

Tests must extend at least the feature-model calibration/ablation/skew suites,
live-floor and estimate-distribution suites, probability-calibration tests,
release-candidate contract, release serving, captured-input parity, artifact
registry/schema, and rollback lifecycle. Both native-unit families and every
market route are required.

### Artifact footprint

The inactive candidate produces new immutable versions of all 12 per-market
`feature_model_hgb*.pkl`, all 12 conditional LR
`feature_model_coefs*.json`, and candidate-specific per-market
`probability_calibration*.json`, plus the target/feature/floor schemas,
training-corpus and split manifests, OOF/calibration reports, leakage audit,
captured-input replay, gate scorecard, base-model graph, artifact registry, and
release manifest. Exact parent copies of unchanged base components remain
release-bound. The tracked incumbent artifacts are not overwritten during
research or candidate construction.

### Roll and restart

1. Deploy the backward-compatible code while the parent release remains active;
   old-schema replay must be exact before and after this code roll. Because the
   loader and distribution code are loop-loaded, this deployment consumes an
   operator-timed fleet roll/restart budget.
2. Training, inactive release construction, verification, and inactive shadow
   do not change the active pointer and require no serving adoption restart.
3. If separately promoted at a reviewed market-day boundary, use the target
   manifest's exact `expected_live_runtimes` list. Promotion returns
   `restart_required=true`; every listed release-bound worker must be
   coordinated onto the new pointer and prove its runtime identity and health
   before adoption is complete. No scheduler definition changes are part of
   this specification.

### Rollback

Keep the parent release immutable and named as `rollback_target`. At a reviewed
market-day boundary, invoke the existing release lifecycle rollback, verify the
parent manifest and pointer transition, then perform the required coordinated
restart and attach runtime-identity and health proof. Do not copy old artifacts
over new ones, clear a process cache as a substitute for the operator roll, or
mix candidate and parent component roles. Rollback restores the complete parent
graph, including its absolute target and probability calibration.

## Falsification and interpretation

The objective hypothesis is falsified for this design if an exactly replayed,
floor-invariant conditional candidate fails to improve both near-floor
allocation and the frozen severe tail without regressing total Brier on the
one reserved confirmation run. It is also falsified if its apparent
development benefit disappears outside July 22-26, is confined to a small
market/hour slice, or requires activating new features, market prices, a
post-hoc market x hour shift, or weakening the floor.

In that event, abandon this continuation-objective candidate. Preserve the
validated hard floor and return to diagnosis of conditional scale/calibration
or a separately specified weather-feature mechanism. Do not soften the floor,
do not revive the failed per-market constant, and do not mine July 27-30 or
August 6-19 for a replacement threshold.

A floor/mass/parity/release-binding failure rejects the implementation before
it tests the statistical hypothesis. Fixing such a bug does not authorize a
second unblinded confirmation run.

The maximum **44.65 percentage points of the severe-tail baseline** remains a
hindsight-perfect centre-replacement ceiling inside the mechanism-linked
subset. It is not an expected retrain gain, power target, or promotion gate.
Any achievable floor-preserving retrain must land lower; its actual effect is
whatever survives the frozen end-to-end gates and the single forward
confirmation.

## Evidence and guardrails

Read-only inventory outputs under the one declared run root:

| File | SHA-256 |
| :--- | :--- |
| `analysis-declaration.md` | `11f0221738d9e6cf5117ab258b5bc14e9ef412812f01d630ba834de27f2a19ca` |
| `inventory_floor_consumption.py` | `8b6d5c890e37590b95b448f5303b3caf3ce05d4167dbffafebb6251e36e9d87b` |
| `floor-consumption-inventory.json` | `bf06d707712579777b02820a7e2eaae64adfc3d6469b2dc32aac71f6f306239e` |
| `floor-consumption-per-hour.csv` | `938f650ae23182b1306b5f20af5bfb27951b841be2d7249fbbe32673ae49d9d4` |
| `validate_floor_consumption.py` | `da97e8b66c82e7f481f222e5cbd61c20cd8ed9161fa6b50b693d9986ee9d58c5` |
| `validation-summary.json` | `2ba70ffa0845e842f7f3a4cf03f9475f2b66ea75578084387f47b52df4d8d8d8` |

The independent validator returned `PASS`. It rehashed all 14 inventoried
artifacts, checked all 296,380 trees represented by the base and reference
inventories for complete/mapped split structure, re-derived every published
per-hour and total count, and asserted zero current-max or explicit band-floor
splits in the quoted pooled v0.3 artifact.

`data/` and the replay mirror remained read-only. No August 6-19 path was
enumerated. No model, candidate, artifact, config, serving, promotion, pointer,
scheduler, capture, mirror, ACL, or credential state changed. No sync
credential was read or exposed. The handback is documentation-only and is
roll-free. No PR, merge, or master push was made.
