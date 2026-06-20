# 176. Local Generated State And Tooling Cleanup Sweep [OPEN]

Goal: remove or quarantine stale local generated state, retired research
stubs, and scratch outputs after active agents finish.

Source: the 2026-06-20 full repository cleanup audit. Ignored directories such
as `venv`, caches, `__pycache__`, `src/weather_market.egg-info`, and `scratch`
are present locally. `tools/research` also contains a mix of supported,
fixture-only, and retired scripts guarded by the research harness.

Why this matters: ignored local state is useful during development, but stale
generated files make audits noisy and can hide whether behavior is reproducible
from tracked source.

## Design

1. Wait until active agent work is complete before sweeping local generated
   state.
2. Produce a dry-run cleanup report that separates safe cache deletion from
   durable scratch/research outputs.
3. Promote durable scratch reports or scripts into `docs/research`,
   `tools/research`, or tests before deleting local copies.
4. Remove retired research stubs only after confirming the harness no longer
   needs them as explicit failure sentinels.
5. Normalize line endings in a controlled docs/code hygiene PR after dirty
   files settle.

- [ ] Add a local cleanup dry-run command that reports ignored generated files
  and sizes without deleting anything.
- [ ] Delete safe caches after active work finishes: `__pycache__`,
  `.pytest_cache`, `.ruff_cache`, and egg-info.
- [ ] Review `scratch/` for outputs worth promoting to tracked docs or tests.
- [ ] Review retired `tools/research` scripts and either remove them or keep
  them as documented harness fixtures.
- [ ] Ensure dependency pins are managed from one source or add a sync check
  for `pyproject.toml` and `requirements.txt`.
- [ ] Run a controlled CRLF-to-LF normalization pass consistent with
  `.gitattributes`.

Acceptance: local generated clutter can be cleaned reproducibly, durable
scratch findings are promoted before deletion, and repo audits no longer have
to manually filter stale local state.

