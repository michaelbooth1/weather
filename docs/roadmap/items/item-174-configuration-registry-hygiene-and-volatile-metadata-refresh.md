# 174. Configuration Registry Hygiene And Volatile Metadata Refresh [OPEN]

Goal: make configuration files clearly durable, generated, or deprecated so
runtime behavior does not depend on stale or placeholder registry state.

Source: the 2026-06-20 full repository cleanup audit. `config/locations.json`
was generated from a 2026-06-07 Gamma API snapshot, includes volatile active
event metadata, and lists locations not currently server-rendered.
`config/markets.json` is an empty placeholder. The model variant registry has
active or required entries pointing to ignored `data/backtest` candidate
artifacts.

Why this matters: configuration drift can look like a model or data bug.
Operators need to know which files are authoritative, which are generated, and
which are local shadow state.

## Design

1. Classify each config file as hand-authored, generated, deprecated, or
   local-shadow.
2. Split stable location facts from volatile active market/event metadata.
3. Add a regeneration command and freshness check for generated location
   metadata.
4. Remove, populate, or explicitly deprecate the empty market registry.
5. Enforce variant registry rules for promoted artifacts, shadow candidates,
   and ignored local paths.

- [ ] Add a config inventory report covering `locations.json`,
  `markets.json`, `model_variant_registry.json`, supplemental stations, and
  no-market extra locations.
- [ ] Refresh `locations.json` from the current source and record generated-at
  metadata.
- [ ] Move volatile active event fields out of durable location facts or mark
  them generated-only.
- [ ] Decide whether `markets.json` is removed, populated, or retained as a
  deprecated compatibility shell.
- [ ] Add validation that `artifact_required` variants do not point to ignored
  `data/` paths unless they are shadow-only and explicitly allowed.
- [ ] Review diagnostic-only extra locations and either backfill them or
  archive them with a clear reason.

Acceptance: every config file has a documented owner and freshness policy,
generated metadata can be refreshed deterministically, and registry validation
prevents active runtime dependencies on missing local-only artifacts.

