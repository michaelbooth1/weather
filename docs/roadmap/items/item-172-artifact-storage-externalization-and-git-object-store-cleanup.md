# 172. Artifact Storage Externalization And Git Object Store Cleanup [COMPLETE 2026-06-20 - LFS ARTIFACT PREFLIGHT PASS]

Goal: keep model artifacts and Git history below the repository storage policy
limits while preserving reproducible promoted models.

Source: the 2026-06-20 full repository cleanup audit. Tracked `artifacts/`
contains roughly 355 MB. The largest artifact,
`artifacts/models/hgb/feature_model_hgb_f_pooled.pkl`, is roughly 98.9 MB,
just below the 100 MiB failure threshold, and the total artifact audit is
already in warning territory. The local `.git` object store also has more than
2 GiB of loose objects.

Why this matters: the current artifact path is close to blocking normal Git
workflow. Future pooled or candidate models can exceed repository limits unless
the storage boundary is changed before the next promotion.

## Design

1. Re-run the model artifact size audit and confirm which tracked artifacts are
   promoted, active, historical, smoke-only, or superseded.
2. Decide the durable artifact backend: Git LFS, object storage, or an external
   artifact registry with checked-in manifests.
3. Move near-limit binary artifacts behind that backend before adding larger
   `.pkl` files.
4. Keep small manifests, provenance, hashes, and model registry references in
   Git.
5. Add a cleanup path for local Git object bloat that is safe for a dirty
   worktree and active agents.
6. Update artifact promotion checks so active registry entries cannot point to
   ignored local data paths unless explicitly marked shadow-only.

- [x] Classify all files under `artifacts/` by active registry use and
  reproducibility requirement.
- [x] Externalize or LFS-track the largest promoted `.pkl` artifacts.
- [x] Add manifest checksums and restore instructions for externally stored
  models.
- [x] Add a CI or local preflight that blocks artifact promotion above warning
  and failure thresholds.
- [x] Audit `.git` loose objects and document a safe maintenance command for
  after active branches are settled.
- [x] Update variant registry validation to distinguish promoted artifacts from
  local candidate artifacts.

Acceptance: no active model promotion depends on an unmanaged large binary in
Git or an ignored local `data/` path, the artifact audit returns below warning
thresholds, and Git maintenance can be run safely after in-flight work lands.

## 2026-06-20 implementation

Selected Git LFS as the durable backend for HGB pickle artifacts and added the
repository attribute:

```text
artifacts/models/hgb/*.pkl filter=lfs diff=lfs merge=lfs -text
```

`weather.artifacts` now classifies artifacts by active registry use,
reproducibility requirement, storage backend, managed bytes, unmanaged Git
bytes, SHA-256, and restore command. It also writes:

- `artifacts/manifests/model_artifact_registry.json`
- `artifacts/manifests/model_artifact_externalization.json`
- `artifacts/manifests/model_artifact_size_audit.json`
- `artifacts/manifests/model_artifact_promotion_preflight.json`

The generated promotion preflight is `PASS`: `102` artifacts, `361.85 MiB`
managed by Git LFS, `5.61 MiB` unmanaged Git payload, and zero errors or
warnings. `git lfs status` confirms all `artifacts/models/hgb/*.pkl` files are
staged as LFS objects, including the largest
`feature_model_hgb_f_pooled.pkl`.

The two active registry entries that previously referenced ignored
`data/backtest/*.pkl` candidate files now point at managed artifact paths:

- `artifacts/models/hgb/item50_feature_model_hgb_f_pooled_v0_3_candidate.pkl`
- `artifacts/models/hgb/item35_density_full_candidate.pkl`

`weather.reporting.candidate_lifecycle.variant_registry` now errors on active promoted variants
that point at ignored `data/` artifact paths and only warns for variants
explicitly marked `shadow-only`.

The Git object audit is documented in
`docs/operations/artifact-storage-policy.md`: `git count-objects -vH` reported
`count: 52531`, `size: 2.11 GiB`, `size-pack: 536.37 MiB`. The safe post-branch
maintenance command is `git gc --prune=30.days`; history rewriting via
`git lfs migrate import` remains a separate coordinated maintenance window.

Verification:

- `python -m pytest -q tests\test_artifacts.py tests\reporting\test_variant_registry.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py tests\operations\test_path_policy.py`
  passed with 34 tests and 5 subtests.
- `python -m weather.artifacts promotion-preflight --out artifacts\manifests\model_artifact_promotion_preflight.json --fail-on-warn`
  returned `PASS`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - LFS ARTIFACT PREFLIGHT PASS`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

