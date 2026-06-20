# 172. Artifact Storage Externalization And Git Object Store Cleanup [OPEN]

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

- [ ] Classify all files under `artifacts/` by active registry use and
  reproducibility requirement.
- [ ] Externalize or LFS-track the largest promoted `.pkl` artifacts.
- [ ] Add manifest checksums and restore instructions for externally stored
  models.
- [ ] Add a CI or local preflight that blocks artifact promotion above warning
  and failure thresholds.
- [ ] Audit `.git` loose objects and document a safe maintenance command for
  after active branches are settled.
- [ ] Update variant registry validation to distinguish promoted artifacts from
  local candidate artifacts.

Acceptance: no active model promotion depends on an unmanaged large binary in
Git or an ignored local `data/` path, the artifact audit returns below warning
thresholds, and Git maintenance can be run safely after in-flight work lands.

