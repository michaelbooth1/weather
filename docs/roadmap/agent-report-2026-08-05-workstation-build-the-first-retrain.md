# Workstation report 2026-08-05 — build the all-market base retrain, and make it refuse

## Verdict

The missing all-market per-market base-retrain lane now exists, is explicit-only,
and **refuses the retained production evidence**. The final preflight result is:

| Field | Result |
| --- | --- |
| Status | **BLOCK** |
| Fit authorized | **false** |
| Named blockers | **97** |
| Live registry | 12 markets, 1 C and 11 F |
| Candidate outputs | 5 per market, 60 total |
| Scheduled or registered | **no** |
| Ambient `forecast_daily.csv` reachable | **no** |
| Release path or pointer reachable | **no** |

All six required contaminant checks independently block today: forecast archive
coverage, point-in-time forecast binding, train/serve parity, class support,
candidate-specific calibration, and the July 31 artifact-provenance regime
boundary. The explicit argument, live-registry, candidate-isolation,
manifest-identity, and fleet-atomicity checks pass. A passing synthetic control
proves that the gate is satisfiable when every underlying record is exact and
hash-bound; it is not a permanent decorative BLOCK.

No HGB, LR, calibrator, or other model was fitted. Test doubles exercised the
fleet transaction boundary but did not invoke scikit-learn. No candidate was
frozen, no release or pointer was read or written by the retrain lane, no PIT
builder or serving path changed, no task was registered or modified, and no
provider call occurred.

## Scope and safety boundary

This branch starts exactly at refreshed `origin/master @
4f9bf149cbec0e08fd3b12bddf5cdf3d4977b9a3` and is
`codex/workstation-build-the-first-retrain-2026-09-12a`.

The retained-evidence run root is:

`scratch/runs/build-first-retrain-09-12a`

The proof uses the explicit alignment target `2026-07-31`. That date selects
the late-July seasonal training matrix; it is not a candidate freeze,
confirmation score, or serving target. The current reservation contract was
re-read before execution: **no dates are reserved today**. The confirmation
window remains armed but undated until a candidate is fitted and frozen.

Network use was limited to `git fetch` and the final exact-branch push. There
was no collection, provider probe, paid-source access, release/PIT mutation,
scheduled-task action, capture restart, promotion, floor change, settlement
score, or trading action.

## Prior work reconciled

| Prior branch | Reused | Superseded or deliberately excluded |
| --- | --- | --- |
| `codex/workstation-make-the-first-retrain-count-2026-08-25a @ 92bb5347` | The 12-market native-unit contract; target-aligned prior; contiguous serving support separate from `model.classes_`; candidate-only outputs; warm-tail requirements; candidate-specific OOF calibration. | Its recommendation to add the step to nightly scheduling. This mission explicitly requires an unwired manual lane. |
| `codex/workstation-train-serve-parity-gate-2026-09-03a @ af32501b` | The field-level parity implementation, exact exception policy, known-defect fixture, and tests are carried forward. The retrain preflight now consumes its self-contained report as a blocking prerequisite. | Inline ad-hoc parity samples. The standalone report is the authoritative seam. Release-path binding remains unimplemented. |
| `codex/workstation-consolidate-merge-queue-2026-09-01a @ 450f03c5` | The candidate-only per-market fitter from its base-retrain ancestor and the central lesson that independent contracts fail at their seam. The new evidence manifest binds source archive → exact coverage cell → feature record → parity/support/calibration/regime evidence. | Its nightly wiring, inactive-release construction, PIT implementation, and serving-path changes. Those are prohibited here. |

The candidate fitter is reused rather than rewritten. It freezes parent HGB
parameters and feature order, fits HGB and compatible LR outputs in native
units, derives fold-local contiguous support, and derives exact-distribution
calibration from blocked OOF rows. The orchestration around it is new because
the previous orchestration owned the wrong seam: it coupled fitting directly to
nightly scheduling and release construction.

## P1 — the all-market base-retrain step

`weather.operations.base_retrain` owns one explicit fleet plan. It enumerates
`weather.market.market_registry.all_specs()` at invocation and refuses anything
other than the exact live registry projection. The current projection is 12
markets with native units preserved end to end: Toronto is C and the 11 U.S.
markets are F.

Every market declares five immutable candidate outputs:

1. feature HGB;
2. compatible LR coefficients;
3. candidate-specific exact-distribution calibration;
4. fit receipt; and
5. fit report.

The command has no ambient target date, training timestamp, parent identity,
feature contract, evidence manifest, candidate directory, or runtime identity.
`run` additionally requires the literal `--execute-fit` flag. It remains absent
from `nightly_retrain.planned_steps()`, every PowerShell registration surface,
and every task definition.

After a future exact-PASS preflight, the runner fits into a new sibling staging
directory. A partial fleet remains in a non-releasable staging tree for audit;
only 12 exact PASS results with all 60 outputs and candidate-blocked-OOF
calibration are atomically renamed to the declared candidate directory. The
declared candidate path is rejected if it exists or overlaps `data/`, global
model/calibration artifacts, or `artifacts/releases/`.

This lane creates no release, copies no release component, resolves no active
pointer, and contains no promotion or scheduling call.

## P2 — fail-closed preflight

### Retained-production refusal

| Independent check | Today | Blockers | Production evidence and reason |
| --- | ---: | ---: | --- |
| `forecast_archive_coverage` | **BLOCK** | 36 | Each of 12 `data/forecast_history/<station>/manifest.json` files is hash-bound, but its declared season ends June 30, outside all target-aligned late-July dates. Each market also lacks the required exact coverage-matrix manifest and matching feature-record corpus. |
| `point_in_time_forecast_binding` | **BLOCK** | 24 | Each market lacks both PIT coverage-cell evidence and a PIT-bound feature-record corpus. The legacy stitched daily file is never consulted. |
| `train_serve_feature_parity` | **BLOCK** | 1 | The retained report is BLOCK with 220 blocking findings, 12/12 markets and 221/221 fields covered. |
| `class_support` | **BLOCK** | 12 | No current artifact declares contiguous native serving support separately from estimator classes. The check names Dallas 108°F, Denver 101–102°F, Houston 103–104°F, and Seattle 95°F as required warm-tail classes. |
| `candidate_specific_calibration` | **BLOCK** | 12 | No candidate-specific blocked-OOF plan or fit-receipt binding exists. The current component snapshot preserves the June 7 calibrated weights, feature-LR identity with no embedded generation timestamp, June 15 late-day coefficients, and June 10/July 7 probability-calibration identities rather than silently treating them as compatible with a changed HGB. |
| `artifact_regime_boundary` | **BLOCK** | 12 | There is no feature-record corpus carrying one exact artifact regime, code identity, and source-artifact hashes. The check treats `2026-07-31` as artifact provenance, never target-date age. |

The 97 blockers are expected rather than an implementation failure: 36 + 24 +
1 + 12 + 12 + 12. `fit_authorized=false` and the candidate directory does not
exist.

### Coverage is evidence, not an assertion

The coverage gate reconstructs the complete matrix from:

- every live market;
- the explicit target date's prior-year ±7-day seasonal window; and
- cutoff hours 07 through 20.

For every matrix cell, a future coverage manifest must carry an issue identity,
issue time, availability time, cutoff time, point-in-time flag, provenance
state, source-manifest hash, and cell hash. The feature-record JSONL must have
the exact same market/date/cutoff key and bind the same source-manifest and cell
hash. Extra, duplicate, absent, changed, stitched, post-cutoff, or unverified
cells block independently.

This closes the consolidation defect where a run could declare complete
coverage without proving that the fitted feature row came from those exact
bytes. Ambient `forecast_daily.csv` is not a fallback and is unreachable from
both evidence snapshotting and fitting.

### Point-in-time binding

The PIT check is a consumer contract only. No PIT corpus builder, source
adapter, pooled assembly, analog serving loader, active archive, or forecast
path was changed. A future PIT implementation can satisfy the contract only
with exact issue/availability evidence at or before each cutoff and matching
feature-record provenance.

### Class support

The class check does not demand that `model.classes_` manufacture observations.
It demands a separate contiguous range in the market's native unit, containing
all estimator classes and the predeclared warm-tail requirements. The reused
candidate fitter constructs that range fold-locally and maintains positive
smoothed prior mass. The current serving reader was intentionally not changed
here, so a serving-compatible reader for those fields remains a prerequisite
before spending the first fit.

### Calibrator binding

The preflight requires `candidate_specific_blocked_oof`, forbids inheriting the
incumbent calibrator, and requires a candidate fit-receipt binding. The runner
then verifies the emitted calibration's `fit_scope`, refuses unchanged
calibration bytes, and refuses partial-fleet publication. A declaration alone
therefore cannot make stale bytes pass the post-fit boundary.

### Regime boundary

Every feature record must carry exactly one `artifact_regime_id`, one code
identity hash, and source-artifact hashes. Each market and the fleet must remain
within one regime. Target dates may predate July 31 if the records are rebuilt
from one current artifact/code graph; mixing result rows or artifact identities
across the boundary fails.

## P3 — parity binding recommendation

I agree with the handoff's leaning: **bind train/serve feature parity as a
blocking precondition of the all-market base-retrain lane, not the release
path.**

The fit is the earliest irreversible statistical spend and the exact point at
which the two newly discovered blind fields would enter the HGB. Blocking there
prevents fresh contamination without changing Release #1 behavior, loading a
new module in serving, or creating another release-build risk. Release binding
can be considered later after the retrain lane exists, its representative
captured cycle is reviewed, and exact exceptions are ratified.

The retained parity report remains:

- schema `train_serve_feature_parity_v0.1`;
- status **BLOCK**;
- 220 blocking findings;
- 12/12 markets and 221/221 fields covered;
- 4/4 known defects rediscovered; and
- one exact trusted-floor exception.

The preflight accepts only a hash-bound full-fleet report whose status is exact
PASS. It does not import a summary boolean or duplicate parity logic inside the
trainer.

## P4 — the cool bias, conditionally

The existing evidence supports a cool base HGB but does not yet identify one
cause. The fleet raw-centre error is `-0.6641 °C-equivalent` with crossed date ×
market interval `[-1.1164, -0.2482]`. June is `-0.1996 [-0.6234, +0.2005]`,
which crosses zero; July is `-1.0586 [-1.6512, -0.4319]`. July minus June is
`-0.8590 [-1.5581, -0.1359]`. There is no August endpoint in that fixed
population, so age and temperature remain unresolved.

| World | What the first retrain means | How the spec changes | What differs in preflight |
| --- | --- | --- | --- |
| **Artifact age carries the defect** | A fresh target-season fit should reset raw centre error toward zero, then value decays as artifact age grows. | Every candidate receipt already binds `trained_at`; confirmation must also report artifact-age days, signed raw-centre error, Brier/log loss, and tail behavior under crossed date × market inference. The first run stays manual. After enough untouched post-fit ages, set `max_artifact_age_days` to the earliest age where a predeclared proper-score guardrail or cool-bias harm threshold fails, less a safety margin. No cadence is scheduled from the current two-month slope. | The six current checks remain. Before any recurring schedule is proposed, add a seventh cadence-policy check binding the measured age curve, threshold, margin, and candidate identity. Warm-tail support remains a guardrail because absent outcomes are real even if age is causal. |
| **Temperature level carries the defect** | Re-fitting the same objective on a warmer seasonal window can reproduce the cool tail. Recency alone is not the repair. | Contiguous warm-tail support becomes the causal intervention. The candidate must cover the required Dallas, Denver, Houston, and Seattle buckets, preserve positive mass, and improve tail proper score without fleet harm. Cadence remains manual/on-evidence rather than pretending freshness fixes structure. | No cadence-policy prerequisite is justified. The `class_support` check becomes the decisive repair gate; forecast/PIT/parity/calibration/regime checks are unchanged. |

The candidate must predeclare both diagnostics before fitting. A result where
freshness improves centre error only after support expansion does not identify
age alone; a factorial or otherwise identified follow-up is required. Neither
branch authorizes a serving-side offset or any weakening of the trusted floor.

## P5 — what remains before a first retrain is worth spending

1. Build and verify the real PIT forecast corpus against the exact matrix. The
   currently retained May 10–June 30 archive cannot supply it. Any provider
   probe or collection requires separate authorization.
2. Decide how to extend forecast coverage without silently changing the analog
   serving input at `model_features.py`; that serving/PIT change was explicitly
   excluded here.
3. Repair the field-level parity findings, especially training-populated but
   serving-blind gust/shift fields, then produce one exact-PASS full-fleet
   parity report.
4. Implement and test the serving-side reader for declared contiguous support
   without weakening the trusted observed-high floor or probability-mass
   contract. The candidate fitter emits the fields; this branch does not alter
   serving.
5. Freeze the exact parent feature order and prove every assembled feature row
   binds it, with no implicit 221-column expansion.
6. Supply one artifact-regime/code/source identity across all feature records.
7. Predeclare the age-versus-temperature diagnostic, candidate-specific OOF
   calibration, protected slices, native-unit checks, and post-fit fleet
   transaction receipt.
8. Restore a compatible project Python 3.11 runtime before the spend. This
   workstation's checked-out venv points at a removed Python 3.11 installation;
   static and preflight tests ran under the bundled runtime, but a real
   scikit-learn fit was intentionally neither possible nor attempted.
9. Obtain explicit operator authorization for the fit and resource window.
   The lane remains manual and no scheduled task should be added merely because
   its code exists.
10. At candidate freeze, compute confirmation N against endpoints that still
    stand under crossed date × market clustering. Then update
    `docs/operations/reserved-confirmation-window.md` immediately with the
    candidate identity, exact start/end dates, size, endpoints, and derivation
    **before any confirmation scoring**. An undeclared window reserves nothing.
    If no achievable endpoint is powered, do not freeze a confirmation window.

The fit becomes worth spending only after the preflight is exact PASS on real
evidence and the serving-support consumer exists. A candidate directory or
green unit test is not a reason to spend.

## Per-file roll-safety verdict

This verdict uses the exact `runtime_identity.source_scope_files` arrays in
`data/snapshots/loop_status.json`, `clob_loop_status.json`,
`observation_trigger_status.json`, and `clob_enrichment_status.json`; it does
not use `SOURCE_PATTERNS`.

| File | In a recorded capture-loop import closure? | Verdict |
| --- | --- | --- |
| `src/weather/schema_registry_data.py` | Yes: snapshot, CLOB, observation-trigger, and CLOB-enrichment closures. | **ROLLS all three capture loops. Quiet-window merge required.** |
| `src/weather/schema_registry_recent_data.py` | Yes: snapshot, CLOB, observation-trigger, and CLOB-enrichment closures. | **ROLLS all three capture loops. Quiet-window merge required.** |
| `src/weather/calibration/base_model_candidate.py` | No. | No capture roll from this file. |
| `src/weather/operations/base_retrain.py` | No. | No capture roll from this file. |
| `src/weather/reporting/scorecards/train_serve_feature_parity.py` | No. | No capture roll from this file. |
| `tests/operations/test_base_retrain.py` | No; tests are not runtime modules. | Roll-free. |
| `tests/reporting/test_train_serve_feature_parity.py` | No; tests are not runtime modules. | Roll-free. |
| `tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json` | No. | Roll-free. |
| `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md` | No. | Roll-free. |
| This report | No. | Roll-free. |

The branch as a whole is therefore **roll-sensitive** because both schema
registry files are already loaded by all three capture loops. It must be merged
only through the 01:00–04:00 quiet-window procedure. No capture process was
restarted or re-adopted during this mission.

## What would falsify this

- **The step was missing:** finding a current scheduled command that already
  fits all 12 per-market HGBs into candidate-only locations would falsify the
  motivating absence. The inspected nightly source still contains no
  `weather.operations.base_retrain` or all-market `feature_model` step.
- **Forecast coverage blocks:** a hash-bound archive whose season covers every
  reconstructed date, plus an exact complete market/date/cutoff matrix and
  matching feature-record cell hashes, would make this check pass.
- **PIT binding blocks:** verified issue and availability times at or before
  cutoff, one non-stitched issue identity, and exact feature provenance for
  every matrix cell would make this check pass.
- **Parity blocks:** an exact-PASS full-fleet report with no unclassified active
  feature finding would overturn the current BLOCK.
- **Class support blocks:** a contiguous native support declaration separate
  from estimator classes, containing every estimator and required warm-tail
  bucket, would make the check pass.
- **Calibration blocks:** a candidate-specific blocked-OOF plan and post-fit
  artifact bound to changed candidate-base bytes and its exact fit receipt
  would make the check pass.
- **Regime blocks:** one exact artifact regime, code identity, and source graph
  on every feature record would make the check pass even when target dates are
  earlier than July 31.
- **The preflight is decorative:** a fully repaired synthetic manifest already
  produces exact PASS; conversely, any production-evidence PASS with one of the
  six prerequisites absent would falsify the implementation and block use.
- **Fleet atomicity:** a Toronto/NYC-only or otherwise partial fake run appearing
  at the declared final candidate path would falsify the transaction boundary.
  The test leaves that path absent.
- **No release/PIT/scheduler reachability:** any write beneath
  `artifacts/releases/`, pointer mutation, PIT/serving edit, or nightly/task
  registration from this lane would falsify the stated boundary.
- **Roll safety:** a newer recorded import closure omitting both changed schema
  registry files from every capture loop would overturn the quiet-window
  verdict. The retained current closures include both files in all three.

## Evidence and verification

| Evidence | SHA-256 / result |
| --- | --- |
| Current evidence manifest file | `72cadea4ed766af20270598d99fa36e8c43e9e76c9f71983c1e0562e00215e8b` |
| Current evidence manifest self-hash | `342d13e528132246a54bd0dc632beb4ae2795c8d5029aef7feccb526175c5f3a` |
| Parent artifact identity | `tracked-base-c40a7e183c202f26` |
| Parent feature-contract identity | `tracked-parent-feature-contract-c40a7e183c202f26` |
| Retained parity report file | `4b3d25e2bc80e5090bc4df2ed64e58ecc5cbce2387874e262be5d2fd0a004ce2` |
| Retained parity report self-hash | `f4693e7e53e713613d6a85c7b1813de577e6db32265c4920cd1ee7d99a2a3295` |
| Current preflight file | `732f3ea96b3b859589ea326b76b2d1f389e1bdd093e8258a4bfcf5f9143e1d20` |
| Current preflight self-hash | `57dbc9adddc7b14c4358ab2a6c9500cf00a0cebf75ff43dd72e29c451d4b27b8` |
| Current preflight verdict | **BLOCK**, 97 blockers, `fit_authorized=false` |

Verification completed before the final documentation pass:

```text
tests/operations/test_base_retrain.py
7 passed

tests/reporting/test_train_serve_feature_parity.py
10 passed

tests/operations/test_import_architecture.py
21 passed

python -m weather.schema_registry audit --strict
registered=515 discovered=850 unregistered_versions=0 excluded_versions=8

python -m py_compile <three new source modules>
PASS

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 616 Markdown files)
```

The candidate fitter is the previously tested implementation from the held
base-retrain work. Its current copy compiles unchanged except for line-ending
and trailing-whitespace normalization. It was not imported through the
incompatible local scikit-learn extension and was not executed.

No PR was opened and no merge was performed.
