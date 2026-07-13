# Tooling Instructions

These instructions apply under `tools/`.

- `tools/research/` contains local, often one-off analysis. Inspect scripts for
  network, memory, and output behavior before running them.
- Durable workflows and commands belong in an owning `src/weather` package with
  tests and a canonical `python -m weather...` entry point. Do not grow a tool
  into an undocumented production dependency.
- Root and duplicate helper scripts may be compatibility surfaces. Prefer the
  packaged owner or canonical `scripts/ops`/`scripts/launch` path in new docs.
- Write scratch/generated outputs under ignored `data/` or `scratch/`. Promote
  only reviewed historical reports to `docs/`, deterministic fixtures to
  `tests/fixtures/`, and qualified model state to `artifacts/`.
- Bound large local analyses and follow the host-load policy. Unit-test reusable
  parsing/analysis logic after moving it to its owner package.

## Update this file when

Update when tool classification, promotion paths, canonical command ownership,
or local-analysis safety changes.
