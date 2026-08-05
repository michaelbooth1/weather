# Workstation first-retrain contract — 2026-08-02

## Verdict

**No. The scheduled nightly path does not refresh any per-market base HGB.** It
trains the F-family secondary and pooled candidate artifacts, then copies the
already-existing per-market base graph into an inactive release. Release #1
will make that graph immutable and loadable; by itself it will not make the
June base models fresh.

The June dates are **three separate events**, plus two other one-shot research
archives that happen to be June-aged:

1. the per-market base HGB/LR/late-day artifacts came from unscheduled manual
   `weather.calibration.feature_model` runs;
2. marine water-contrast is a one-shot research backfill whose logical horizon
   is June 13 and which has no daily owner; and
3. WU history/current availability was disabled in code on June 30.

There is no single failed pipeline to restart. The only registered production
training task runs the candidate-only orchestrator. The retired hosted workflow
is manual-only and invokes the base trainer for Toronto and NYC, not all 12
markets.

A direct base retrain is also **not ready to run safely**. The current CLI:

- has no explicit target-date or candidate-output argument;
- writes global artifact paths and a report below mutable `data/`;
- expands to the current 221-column feature schema instead of freezing the
  incumbent 19-base-feature contract;
- would get **zero** archived forecast/profile coverage for a late-July-aligned
  WU training window because the forecast archive stops its seasonal coverage
  at June 30; and
- would reproduce WU-populated training rows against WU-blind serving unless
  the separately specified feature contract repair lands first.

The upper-tail defect is partly seasonal and partly structural. Re-centring the
same prior-year WU cache on July 22–26 warms the empirical label prior in every
market, by `+0.15` to `+10.16` native degrees, and expands several hot-market
maxima. But the trainer defines HGB classes as only the labels observed in that
window. Even after date alignment, the required Dallas `108°F`, Denver
`101–102°F`, Houston `103–104°F`, and Seattle `95°F` classes remain absent in
the July 24 proxy. Reweighting cannot create an absent class. The first retrain
needs a target-date-aligned prior **and a separate contiguous serving-support
contract**; class weighting is not the first repair.

No repair, refresh, fit, candidate, artifact, score, fresh-date read, or
operational change was made.

## Scope and evidence boundary

This report is based exactly on
`codex/workstation-is-the-bias-conditional-2026-08-24a @
fd1a0bb70c8cc63e17e9f22152804ded474235fc`.

The sole declared output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\make-first-retrain-count-2026-08-25a`,
outside the mirror. `data/` was read-only. The new inventory read tracked code,
configuration and artifacts; immutable prior aggregate evidence for July
22–26; source manifests whose horizons end in June; and only the sorted
**pre-2026** prefix of WU history plus pre-2026 hourly files needed to measure
target-season coverage. It read zero current-year WU rows.

It did not read, enumerate, evaluate, or substitute August 1–3 or August 6–19.
It did not read July 27–31 outcomes. July 31 remains the `rows[-1]` POST-regime
boundary. `-08-16a` remains queued for 2026-08-05 04:30.

## 1. Does nightly refresh the base artifacts?

**No.** The code trace is complete:

1. [`planned_steps()`](../../src/weather/operations/nightly_retrain.py#L1263)
   schedules settled-day freshness, daily learning, the experiment queue,
   F-family secondary training, the F-family pooled band model, artifact
   registry, promotion refresh, qualification, and shadow A/B. There is no
   `weather.calibration.feature_model` command.
2. The two statistical training commands are
   [`family_secondary_command()`](../../src/weather/operations/nightly_retrain.py#L384)
   and
   [`pooled_feature_command()`](../../src/weather/operations/nightly_retrain.py#L482).
   Neither emits a per-market `feature_model_hgb*.pkl`.
3. The registered Windows task invokes only
   `python -m weather.operations.nightly_retrain run` and describes itself as
   candidate-only; see
   [`register_nightly_retrain.ps1`](../../scripts/ops/register_nightly_retrain.ps1#L64).
   The training-window wrapper delegates to that same orchestrator.
4. Release construction enumerates the seven existing base components for each
   market in
   [`_base_model_source_components()`](../../src/weather/operations/release_candidate_contract.py#L257)
   and copies them into the candidate at lines 342–349. It freezes the current
   HGB; it does not build a new one.
5. Serving first loads the release-bound `feature_hgb` and only falls back to a
   global pickle when no pointer exists; see
   [`_read_feature_model_hgb()`](../../src/weather/model/model_features.py#L59).
   An active release explicitly forbids global fallback.
6. The separate one-market trainer is
   [`feature_model.main()`](../../src/weather/calibration/feature_model.py#L1142).
   It writes `feature_model_coefs*.json`, `feature_model_hgb*.pkl`, and
   `late_day_model_coefs*.json` to global repository artifact paths at lines
   1626–1652.
7. The hosted
   [`Nightly Candidate Build`](../../.github/workflows/retrain.yml#L1) disabled
   its schedule on July 29. Its manual-only body runs the base trainer for only
   `toronto` and `nyc` at lines 57–58. That is two markets, not a fleet refresh.

Therefore the first release candidate will bind the same June base bytes unless
a new all-market base-training step is deliberately implemented. A green
nightly status is not evidence that those bytes changed.

## 2. June 13 is three events, not one

| Event | Effective date | Owner and evidence | Relationship |
| --- | --- | --- | --- |
| Per-market base fit | Production-host handoff: HGBs June 10–13, Toronto June 13. The tracked forensic content epochs span June 9–14. | Manual `weather.calibration.feature_model --market …`; no registered all-market caller. The same route emits HGB, LR and late-day artifacts. | Independent unscheduled model build. |
| Marine sidecar horizon | Logical last date June 13; manifests generated June 25. | Seven one-shot `marine_water_contrast_backfill_v0.1` manifests; no daily refresh task. Five markets have no explicit sidecar. | Independent research backfill. It is not selected by the incumbent HGB. |
| WU serving break | June 30, commit `5735b573aa284da070fba9b751d3a48f5819aca4`. | `fetch_wu_history()` and `fetch_wu_current()` fail before network with `paid_provider_disabled`; July 2's free station fallback retained only temperature/current max. | Later policy regression plus incomplete parity implementation. |

The coincidence is explained by a concentrated June build period, not a shared
scheduler. Forecast history and reanalysis are further one-shot corpora,
generated June 23. Their existence does not supply a restartable daily owner.

## 3. Complete base-training and serving-graph inventory

### Inputs read by `feature_model`

[`feature_model.main()`](../../src/weather/calibration/feature_model.py#L1142)
loads exactly four persisted data families before building rows: WU daily/hourly
history, forecast daily/long archives, marine water-contrast, and reanalysis
synoptic. The historical row builder additionally declares feature groups for
which it always emits empty values.

| Input | Last retained refresh/horizon | Late-July aligned coverage | Retrain consequence |
| --- | --- | --- | --- |
| WU daily summary + hourly history | No generation manifest is bound to the trainer. The read-only cache has prior-year history through December 31, 2025. `historical_target_cache()` excludes the target year and selects only prior years within `±7` calendar days. | 163–165 usable rows per U.S market and 660 for Toronto for each July 22–26 centre. | The cache can move the seasonal label prior, but “current data refresh” does **not** add current-year outcomes. Exact source hashes, selected dates, row counts and cutoff contract are currently absent from the artifact. |
| Open-Meteo historical forecast daily + long/profile | All 12 manifests generated June 23; latest 2026 target is June 23; the durable code window is May 10–June 30 for every year. | **0 rows for every market and every aligned centre.** | Parent-selected `forecast_high`/`forecast_gap` and all archived profile fields become train-missing. This is a hard preflight failure, not an optional stale feature. |
| Marine water-contrast | Seven manifests generated June 25 with logical max June 13; Atlanta, Austin, Dallas, Denver and Toronto have no explicit sidecar. | **0 rows** for every aligned centre. | Exclude the family by exact feature allowlist for this first refresh, or first create a separately authorized PIT archive and gate. Silent inclusion is forbidden. |
| Reanalysis synoptic | All 12 summaries generated June 23 with logical max June 13. | All aligned U.S WU rows have a matching prior-year sidecar. Toronto has 390/660 because reanalysis begins in 2000 while its WU history is deeper. | Not date-poisoned for the prior-year target season, but coverage is asymmetric and the one-shot lineage must be hash-bound. Do not infer freshness from the June 13 top-level horizon alone. |
| U.S guidance, MRMS precipitation, ECCC gridded | **Never populated by this trainer.** `build_historical_feature_record()` calls `empty_us_guidance_features()`, `empty_mrms_precip_features()`, and `empty_eccc_gridded_features()`. | 0 by construction. | The current 221-column schema contains these live families. A blind rerun would change the artifact contract while fitting them entirely missing. Freeze an allowlist or build PIT parity first. |
| Current-max trust fields | Derived from the same WU historical row, not a separate archive. | Training sees WU-validated history; current serving often sees station support with WU absent. | A new-schema retrain would introduce another train/serve regime mismatch unless the WU/free-source contract is repaired first. |

The forecast coverage result is especially important. The archive manifest's
season window, not its file modification time, is the operative contract. A
fresh base pickle built today from those files would still contain no
late-July/August historical forecast signal.

### Base graph frozen into a release

Release construction copies seven components per market. “Last refresh” below
uses embedded generation time where present; Git movement/storage commits are
not treated as statistical refits.

| Component | Fleet | Last model-generation evidence | First-retrain disposition |
| --- | ---: | --- | --- |
| Feature HGB | 12 | Host HGBs June 10–13; tracked content first appeared June 9–14. | **Refresh all 12** into an immutable candidate; require changed hashes. |
| Feature LR fallback | 12 | Same manual trainer; tracked JSONs June 13 except Miami June 14. | Refresh under the identical target/support/feature contract or bind an explicitly compatible parent lane. |
| Late-day LR | 12 | Same trainer; tracked fleet update June 15. | Keep parent copies for the isolated morning prior/support experiment unless late-day is separately declared in scope. Do not accept the CLI's incidental overwrite. |
| Calibrated empirical weights | 12 | Embedded `generated_at` June 7. | Inventory as stale, but pin parent hashes for attribution unless a separate OOF recalibration is predeclared. |
| Exact probability calibration | 12 | Toronto June 10; eleven U.S markets July 7. | **Refit candidate-specific calibration** from the new candidate's blocked OOF distributions. A shape calibrator from the old HGB is not compatible evidence. |
| Forecast-error model | 12 | Toronto June 23; eleven U.S markets July 7. | Pin exact parent hashes unless explicitly re-estimated as a separate change. |
| Settlement-lag model | 12 | Toronto June 10; eleven U.S markets July 7. | Pin exact parent hashes unless explicitly re-estimated as a separate change. |

This table also answers “what else froze”: calibrated weights, LR fallbacks and
late-day coefficients are June-aged; forecast and reanalysis feature archives
are one-shot June products; marine is a June one-shot; and several newly
declared historical feature families have never had an archive at all. The
July 7 calibration/error/lag files did not share the June freeze, but nightly
still only copies them and does not prove compatibility with a changed HGB.

## 4. Upper-class support deficiency

### Classes required by observed permitted evidence

The active HGB class set is empirical and non-contiguous: final fitting passes
`y = final_bucket` directly to `HistGradientBoostingClassifier.fit()`. No code
pads the class range. To cover the maximum permitted July 22–26 settlement and
the ceiling of the cutoff-valid forecast, these are the missing warm classes:

| Market | Active maximum | Settlement / forecast maximum | Missing active classes required now | July 24-aligned prior-year WU result |
| --- | ---: | ---: | --- | --- |
| Austin | 102°F | 103°F / 103.2°F | **103–104°F** | Max 109°F; 103–104 present. Date alignment repairs this observed range. |
| Dallas | 102°F | 108°F / 107.4°F | **103–108°F**; active support also skips 101°F | Max 111°F, but **108°F is still absent** in every July 22–26-centred window. |
| Denver | 100°F | 101°F / 101.2°F | **101–102°F** | Max only 98–99°F. Alignment does not repair it. |
| Houston | 98°F | 102°F / 103.5°F | **99–104°F** | Max 102°F; 103–104 remain absent, and some centred windows also lack 101°F. |
| Seattle | 92°F | 94°F / 94.1°F | **93–95°F**; active support also skips 89–91°F | Max 94°F; 95 remains absent. |

These five markets account for six settlement-above-maximum market-days:
Austin, Dallas, Houston and Seattle once each and Denver twice. Those six days
were 10% of the 60 morning market-days but carried 48.41% of signed cool
displacement. Forecast exceeded the active maximum on 237/2,868 snapshots
(`8.26%`).

The structural issue is broader than the challenged maxima. Near their warm
ends, active Dallas skips 101°F, Los Angeles skips 82, 84–85 and 87–90°F, NYC
skips 92 and 96–99°F, San Francisco skips 91–95°F, and Seattle skips 89–91°F.
Those holes are an unavoidable consequence of equating “classes observed in a
small seasonal sample” with “classes the serving distribution may represent.”

### Seasonal alignment helps, but does not finish the job

The July 24 proxy uses the same WU cache and exact `±7` prior-year rule as the
trainer, but centres it on the permitted late-July date. It is a label/support
inventory, not a fit or score.

| Market | Active fitted label prior | Aligned label prior | Shift | Aligned minus July 22–26 settlement mean |
| --- | ---: | ---: | ---: | ---: |
| Atlanta | 86.23°F | 90.24°F | +4.02°F | +1.44°F |
| Austin | 92.66°F | 96.96°F | +4.30°F | -0.64°F |
| Chicago | 79.68°F | 84.04°F | +4.37°F | +4.04°F |
| Dallas | 91.18°F | 97.25°F | +6.07°F | -1.75°F |
| Denver | 82.39°F | 89.11°F | +6.72°F | **-6.29°F** |
| Houston | 91.04°F | 94.00°F | +2.96°F | -0.20°F |
| Los Angeles | 70.25°F | 75.29°F | +5.04°F | **-3.11°F** |
| Miami | 88.58°F | 90.84°F | +2.26°F | -1.56°F |
| NYC | 78.37°F | 87.28°F | +8.92°F | +4.88°F |
| San Francisco | 70.48°F | 70.64°F | +0.15°F | +0.64°F |
| Seattle | 69.55°F | 79.71°F | +10.16°F | +0.71°F |
| Toronto | 23.75°C | 27.01°C | +3.27°C | +1.81°C |

This establishes the distinction:

- **seasonal staleness is real:** moving the target window warms all 12 label
  priors and would recover much of several large gaps;
- **refresh alone is insufficient:** it leaves required classes absent in four
  of the five challenged markets and leaves large in-support prior gaps in
  Denver and Los Angeles; and
- **reweighting is the wrong first tool:** it cannot add missing classes and
  would change probability meaning. If in-support warm underallocation remains
  after alignment and support completion, weighting or an ordinal/residual
  objective is a new predeclared experiment.

The serving support must therefore be declared separately from
`model.classes_`: a contiguous native-bucket range with a smoothed prior that
can carry positive mass on every declared bucket. Fitted HGB classes may remain
the observed labels, but they cannot remain the definition of representable
outcomes.

## 5. Specification for the first post-release base retrain

### Required implementation boundary

Add a distinct **all-market base-model candidate step** to the nightly
orchestrator. It must not call the current CLI unchanged. The new step must:

1. accept an explicit target date, parent release ID, training as-of/cutoff,
   feature-contract ID, corpus manifest, candidate directory and runtime ID;
2. run all 12 registered markets in native units;
3. write only immutable candidate paths, never the global artifacts or `data/`;
4. emit HGB and compatible LR artifacts plus candidate-specific probability
   calibration, receipts and reports;
5. copy every intentionally unchanged graph component from the parent by exact
   hash; and
6. build an inactive release only after the complete 12-market graph verifies.

The statistical change for run one is narrow: target-date-align the base prior,
separate contiguous serving support from observed HGB classes, and otherwise
freeze the parent feature-name contract and hyperparameters. Do not silently
activate the other 202 populated schema columns.

Before fitting, choose and prove one feature-contract lane from the prior
contract-repair specification:

- exact public WU-history parity with the artifact-era normalized contract; or
- a new versioned METAR/ECCC historical/live adapter trained and served through
  the same definitions.

If neither lane passes, **do not run the retrain**. Training on populated WU
surface fields and serving them blind is known train/serve skew.

### Data and support contract

- Select only prior-year WU rows in the explicit target date's `±7` window;
  record every selected local date, daily/hourly source hash, unit, row count,
  label bucket and exclusion reason.
- Extend the historical forecast daily/profile archive through that same
  seasonal window for every selected year and market. Parent-selected forecast
  fields require 100% date-level coverage or an explicitly frozen missingness
  policy proven equal at train and serve. Today's measured 0% fails.
- Exclude marine, new guidance, MRMS, ECCC gridded and other new families from
  the first run unless each has a separately hash-bound PIT archive and frozen
  allowlist. Reanalysis may enter only where its declared coverage and parent
  feature contract permit it.
- Define fold-local and final support as a contiguous native integer range.
  Its upper edge must be at least the larger of the training-label maximum and
  the ceiling of the maximum cutoff-valid training forecast, plus a
  predeclared `2°C`-equivalent margin (`2` buckets in C markets, `4` in F
  markets). Construct it from each training fold only. Alpha-smoothed prior
  mass must keep every declared class representable; no validation outcome may
  choose an edge.
- Preserve unweighted proper multiclass loss for this first test. Do not tune a
  warm-class weight from the permitted development dates.

### Fail-closed preflight

| Check | Required result |
| --- | --- |
| Scheduler plan | Exactly one declared all-market base step exists; its plan receipt names all 12 markets and all candidate outputs. Absence is a hard failure even if other nightly steps pass. |
| Parent/release | Active parent release resolves and all 84 market-component roles verify by hash. Candidate output directory is new and inactive. |
| Target/cutoff | Explicit target date and training as-of are present in CLI, corpus and every artifact; no ambient-date default is allowed. Target year is excluded from base labels unless a separately approved PIT extension says otherwise. |
| WU corpus | Every market has a frozen selected-date manifest, native labels, sufficient hourly rows and no post-cutoff predictor. Counts must match the preflight declaration and clear the repository minimum; large changes from the late-July proxy (163–165 U.S, 660 Toronto) require review. |
| Forecast archive | Every parent-selected forecast daily/profile field has complete expected-date coverage and PIT issue-time provenance. Current `0/N` aligned coverage fails immediately. |
| Feature allowlist | Candidate names equal the frozen parent allowlist or an explicitly approved new schema. All-missing training fields, live-only fields, unapproved 221-column expansion, and feature-order drift fail. |
| Train/serve parity | Historical and live builders emit equivalent values, units, categories, missingness and cutoff behavior from the same captured payload for every selected field. The known WU-blind surface fields fail until repaired. |
| Sidecars | Each allowed sidecar has schema, generated time, logical horizon, selected-row coverage and SHA-256. Marine's current zero aligned coverage fails if marine is allowed; it is harmless if excluded. |
| Class support | Support is contiguous, native-unit correct, fold-local, margin-complete and covers every permitted training label/forecast. `classes_` holes do not truncate the final raw distribution. |
| Output isolation | Repository globals, `data/`, active pointer and parent release hashes are unchanged after a dry output-path probe. Any write outside the candidate root aborts. |
| Fleet atomicity | All 12 HGB/LR pairs and candidate calibration complete or none is releasable. Toronto/NYC-only success is failure. |

### Post-run evidence and success conditions

The first run is successful operationally only if:

- all 12 HGB hashes and their compatible LR/calibration hashes are new, while
  every declared parent component and the active pointer is unchanged;
- every artifact records target date, training as-of, native unit, row and
  class counts, contiguous support, feature-name hash, source-manifest hash,
  code/runtime identity, blocked split plan and OOF calibration receipt;
- inactive-release serving replay exactly reproduces the recorded candidate
  distribution with zero global fallback;
- all probability mass, native-unit, floor, captured-input replay and release
  binding invariants pass; and
- blocked OOF plus the already-permitted development corpus show total
  Brier/log-loss non-regression, smaller raw centre bias, fewer
  settlement/forecast-above-support cases, improvement on the incumbent-frozen
  severe tail, and no increase beyond the inherited new-severe cap.

These are development/OOF checks, not forward proof. The already reserved
post-August-19 confirmation remains a single frozen run under the prior
sequence. This mission did not inspect it.

## 6. Failure modes and reasons the first retrain may not improve

| Failure | What would happen | Detection |
| --- | --- | --- |
| Nightly remains candidate-only | Release #1 repeatedly rebinds June HGBs. | Base-step plan receipt and 12 changed HGB hashes. |
| Hosted workflow is mistaken for fleet training | Only Toronto and NYC refresh. | Exact market-set equality, not unit-family coverage. |
| Current CLI is run directly | Global artifacts and a `data/.../analysis` report are mutated; no inactive candidate boundary. | Output-isolation probe and before/after repository hash inventory. |
| Ambient target date drifts | Restart timing changes the seasonal corpus without changing the command. | Required explicit target date in every receipt. |
| Forecast archive is not extended | Selected forecast features are missing for every training row while live serving has them. | 100% selected-date/field coverage gate; current corpus fails 0/N. |
| WU contract remains broken | The new model learns WU trajectory/surface state and serves medians/zero categories again. | Feature-value/missingness parity gate, not a boolean replay receipt. |
| Current 221-column schema is accepted implicitly | The run becomes an uncontrolled feature expansion with several never-archived families. | Frozen feature allowlist/hash. |
| Empirical classes remain serving support | Dallas/Denver/Houston/Seattle still cannot represent required warm outcomes. | Contiguity, margin and forecast-exposure audit. |
| Old probability calibrator is copied | A calibrator fitted to old distribution shapes distorts the new support. | Candidate-specific OOF calibration lineage. |
| Partial fleet failure is tolerated | Markets mix target dates, schemas or generations. | Atomic complete-graph gate. |

Even a correctly aligned run is not guaranteed to improve. The July proxy
still leaves the empirical prior `6.29°F` cool in Denver, `3.11°F` cool in Los
Angeles, `1.75°F` cool in Dallas and `1.56°F` cool in Miami, while it becomes
materially warmer than the five-day settlement mean in Chicago and NYC. Most
U.S market/hour fits still have only about 165 rows. Support completion can
reduce truncation yet worsen proper score if it spreads mass without a good
conditional signal. Those are exactly why the run must remain an inactive,
blocked-OOF-qualified candidate rather than an automatic consequence of
release #1.

## Evidence and handback

The read-only inventory outputs are:

| Evidence | SHA-256 |
| --- | --- |
| `analysis-declaration.md` | `f46d5e40cc658b9281f5defba4a2ef0e6fc982342856649859f1521caca8d27c` |
| `seasonal-support-by-market-date.csv` | `33d9ffd8202b14dc69e9b30521c971b2faf10a045e401eb35786f6eaadb8b79e` |
| `training-input-inventory.csv` | `729cfee9946b8a1b09d6a7de2d5c8277dddbb0fbe552583ccfae63211a79d19e` |

The decision handback is: **release #1 is necessary for immutable binding, but
it is not sufficient to restart base learning.** Implement the candidate-safe
all-market base step and make the WU-parity plus forecast-archive preflights
pass before spending the first retrain.

No production host, mirror, credential, paid provider, release, pointer,
serving process, scheduler, capture, ACL, PR, merge, or master state changed.
