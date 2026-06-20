# Artifact Storage Policy

Last updated: 2026-06-20

Durable model and calibration artifacts live under `artifacts/`. Small JSON
calibration artifacts, manifests, and provenance files remain tracked in Git.
Binary model artifacts, especially `.pkl` HGB files under `artifacts/models/`,
must stay below repository-hosting limits or move to Git LFS/external artifact
storage before promotion.

## Thresholds

The local/CI audit command uses these default thresholds:

| Scope | Warn | Fail |
| :--- | ---: | ---: |
| Single artifact | 90 MiB | 100 MiB |
| Total tracked artifacts | 350 MiB | 500 MiB |

The audit measures unmanaged Git payload separately from restore-managed
payload. Git LFS or external artifact-store entries still appear in working
tree byte totals and checksum manifests, but do not count against the
unmanaged Git warning/failure budget.

## Storage Strategy

- Keep JSON model coefficients, calibration manifests, and registry files in
  normal Git unless they grow into the warning range.
- Track HGB pickle artifacts with Git LFS via
  `artifacts/models/hgb/*.pkl filter=lfs diff=lfs merge=lfs -text`.
- Move binary model artifacts that reach the warning threshold to Git LFS before
  adding a larger replacement artifact.
- If Git LFS is unavailable for the deployment environment, publish the binary
  to external artifact storage or a release asset and commit a small manifest
  containing the artifact id, SHA-256, size, schema/model versions, and fetch
  location.
- Do not delete a serving artifact until the replacement is load-tested and its
  provenance appears in `artifacts/manifests/model_artifact_registry.json`.
- Active model-variant registry entries must point promoted artifacts at
  managed `artifacts/` paths. Ignored `data/` artifact paths are allowed only
  for variants explicitly marked `shadow-only`.

## Audit Commands

Generate the provenance registry:

```powershell
python -m weather.artifacts registry
```

Generate the LFS/external restore manifest:

```powershell
python -m weather.artifacts externalization-manifest
```

Generate the size audit:

```powershell
python -m weather.artifacts size-audit
```

Run the promotion preflight and fail a local or CI job when storage or registry
artifact policy reaches `WARN` or `FAIL`:

```powershell
python -m weather.artifacts promotion-preflight --fail-on-warn
```

Nightly retrain should publish both
`artifacts/manifests/model_artifact_registry.json` and
`artifacts/manifests/model_artifact_size_audit.json`, plus
`artifacts/manifests/model_artifact_externalization.json` and
`artifacts/manifests/model_artifact_promotion_preflight.json`, before artifact
promotion or commit. Model loading still resolves artifacts through
`weather.artifacts`, so applying this policy does not change runtime lookup
paths.

## Restore

After checkout, restore LFS-managed HGB models with:

```powershell
git lfs pull --include="artifacts/models/hgb/*.pkl"
```

Then verify checksums and active registry coverage with:

```powershell
python -m weather.artifacts promotion-preflight --fail-on-warn
```

## Git Object Maintenance

The 2026-06-20 audit found `.git/objects` at `count: 52531`, `size: 2.11 GiB`,
with `size-pack: 536.37 MiB`. Do not rewrite history while active branches,
agents, or dirty worktrees depend on the current object graph.

After active branches are settled and the worktree is clean, run:

```powershell
git count-objects -vH
git gc --prune=30.days
git count-objects -vH
```

History-rewriting cleanup such as `git lfs migrate import` requires a separate
coordinated maintenance window and force-push plan.
