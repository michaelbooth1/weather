# Repository Path Policy

Runtime code must not depend on the process current working directory for
repo-owned default paths.

Use `weather.paths` for durable repository locations:

- `artifacts/`: trained model artifacts and model-adjacent durable outputs.
- `config/`: checked-in operator and model configuration.
- `docs/`: roadmap, operations notes, research notes, and generated
  documentation committed to the repo.
- `data/`: runtime state, caches, reports, snapshots, tapes, and backtest
  outputs.

Default paths in modules, CLIs, app views, and scheduled-task helpers should be
absolute and built with `data_path()`, `artifacts_path()`, `config_path()`, or
`docs_path()`. Explicit CLI or function arguments may still be passed through as
`Path(value)`, so user-supplied relative paths remain relative to the caller's
current working directory.

Avoid discovering the repository by walking parents from `__file__` in app
views, tools, or production modules. Import `weather.paths` instead.
