# Artifact Instructions

These instructions apply to `artifacts/`.

- Durable model, calibration, provenance, and release artifacts belong here.
  Mutable or unqualified training outputs belong under ignored
  `artifacts/candidates/` until an explicit release workflow copies verified
  files into an immutable release.
- Do not edit pickle files or generated calibration/model JSON by hand. Use the
  owning producer, preserve schema and provenance, and review the resulting
  diff.
- HGB pickle compatibility depends on the exact scikit-learn pin. Restore
  LFS-managed models after checkout before validating or serving them.
- Treat `artifacts/releases/<release-id>/` as write-once. Never hand-edit a
  release manifest or `artifacts/releases/current_release.json`; use
  `weather.operations.release_lifecycle` and its proof-gated promote/rollback
  commands.
- Do not delete a serving or rollback artifact until its replacement is
  load-tested and the reviewed storage/release policy permits removal.

Artifact registry, size-audit, externalization, and promotion-preflight
commands write generated manifests by default. Run them only as part of an
intentional artifact change, then review every tracked manifest diff:

```powershell
.\venv\Scripts\python.exe -m weather.artifacts registry
.\venv\Scripts\python.exe -m weather.artifacts externalization-manifest
.\venv\Scripts\python.exe -m weather.artifacts size-audit
.\venv\Scripts\python.exe -m weather.artifacts promotion-preflight --fail-on-warn
```

Before handoff, run the focused artifact/release tests and the promotion
preflight. Follow `docs/operations/artifact-storage-policy.md` for thresholds,
Git LFS/external storage, restore, and Git maintenance. Do not rewrite Git
history or migrate LFS objects during ordinary artifact work.

## Update this file when

Update when artifact classifications, LFS/pickle constraints, generated
manifests, immutable release behavior, or the required artifact checks change.
