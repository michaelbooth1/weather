# 131. Model Artifact Storage Growth Guard [COMPLETE 2026-06-18 - SIZE AUDIT AND STORAGE POLICY LIVE]

Goal: prevent tracked model artifacts from crossing repository-hosting limits
or making normal Git operations too expensive.

Source: 2026-06-18 repository hierarchy review. `artifacts/models` is about
353 MB locally, and the largest tracked pickle is about 98.93 MB. That is
close to GitHub's 100 MB hard file-size limit and leaves little room for the
next model family or larger training artifact.

Why this matters: model artifacts are durable project state, but large binary
files scale poorly in Git. A single artifact over the host limit can block
pushes, while repeated large binaries make clone, diff, and history operations
slower for every contributor and worker.

## Design

1. Set tracked-artifact size thresholds, including warning and hard-fail
   limits.
2. Decide the storage policy for large binaries: Git LFS, external artifact
   storage, compressed/versioned release assets, or an explicit cap on tracked
   models.
3. Add an artifact registry check that reports total artifact size, largest
   files, and files near the hard limit.
4. Keep small JSON calibration artifacts and manifests in Git unless they
   become too large.
5. Document how nightly retrain should publish or promote artifacts under the
   chosen storage policy.

- [x] Define warning and failure thresholds for individual artifacts and total
  tracked artifact size.
- [x] Choose Git LFS or an external storage strategy before adding larger
  model families.
- [x] Add an artifact-size audit command or CI check.
- [x] Update nightly retrain documentation for the chosen artifact publishing
  path.
- [x] Confirm model loading and provenance still work after the storage policy
  is applied.

Acceptance: no tracked artifact can silently approach or exceed repository
hosting limits. Operators have a documented artifact publishing path, model
loading preserves provenance, and CI or a local audit warns before artifact
growth becomes a release blocker.

## Completion

Completed 2026-06-18.

Implementation:

- Added `python -m weather.artifacts size-audit`, backed by
  `build_artifact_size_audit` and `write_artifact_size_audit`.
- Registered `model_artifact_size_audit_v0.1` in the schema registry.
- Set default warning/failure thresholds:
  - Individual artifact: warn at 90 MiB, fail at 100 MiB.
  - Total tracked artifacts: warn at 350 MiB, fail at 500 MiB.
- Documented the storage policy in
  `docs/operations/artifact-storage-policy.md`: small JSON/manifests remain in
  Git; binary model artifacts that hit the warning threshold must move to Git
  LFS or external artifact storage before larger replacements are promoted.
- Updated the retrain workflow to generate both the artifact provenance
  registry and size-audit manifest before committing artifacts.
- Kept model loading unchanged through `weather.artifacts`; the policy adds
  audit/provenance only and does not alter runtime lookup paths.

Current audit state:

- `python -m weather.artifacts size-audit --out artifacts\manifests\model_artifact_size_audit.json`
  reports `WARN`, not `FAIL`.
- Largest artifact:
  `artifacts/models/hgb/feature_model_hgb_f_pooled.pkl` at 98.93 MiB, above
  the 90 MiB warning threshold and below the 100 MiB failure threshold.
- Total tracked artifacts: 354.51 MiB, above the 350 MiB warning threshold and
  below the 500 MiB failure threshold.

Verification:

- `python -m pytest tests\test_artifacts.py tests\operations\test_schema_registry.py -q`
  passed.
- `python -m weather.artifacts registry --out artifacts\manifests\model_artifact_registry.json`
  passed and wrote the provenance registry.
- `python -m weather.artifacts size-audit --out artifacts\manifests\model_artifact_size_audit.json`
  passed and wrote the warning manifest.
