# Artifact Storage Policy

Last updated: 2026-06-18

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

Warnings are allowed so current large artifacts can remain loadable while a
storage migration is scheduled. Failures block promotion/commit because they
risk rejected pushes or unusable clones.

## Storage Strategy

- Keep JSON model coefficients, calibration manifests, and registry files in
  normal Git unless they grow into the warning range.
- Move binary model artifacts that reach the warning threshold to Git LFS before
  adding a larger replacement artifact.
- If Git LFS is unavailable for the deployment environment, publish the binary
  to external artifact storage or a release asset and commit a small manifest
  containing the artifact id, SHA-256, size, schema/model versions, and fetch
  location.
- Do not delete a serving artifact until the replacement is load-tested and its
  provenance appears in `artifacts/manifests/model_artifact_registry.json`.

## Audit Commands

Generate the provenance registry:

```powershell
python -m weather.artifacts registry
```

Generate the size audit:

```powershell
python -m weather.artifacts size-audit
```

Fail a local or CI job when the audit reaches `WARN`:

```powershell
python -m weather.artifacts size-audit --fail-on-warn
```

Nightly retrain should publish both
`artifacts/manifests/model_artifact_registry.json` and
`artifacts/manifests/model_artifact_size_audit.json` before artifact promotion
or commit. Model loading still resolves artifacts through `weather.artifacts`,
so applying this policy does not change runtime lookup paths.
