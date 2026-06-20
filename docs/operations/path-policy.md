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
- `tests/fixtures/`: small deterministic test inputs that can be reviewed in
  normal Git diffs.

Default paths in modules, CLIs, app views, and scheduled-task helpers should be
absolute and built with `data_path()`, `artifacts_path()`, `config_path()`, or
`docs_path()`. Explicit CLI or function arguments may still be passed through as
`Path(value)`, so user-supplied relative paths remain relative to the caller's
current working directory.

Avoid discovering the repository by walking parents from `__file__` in app
views, tools, or production modules. Import `weather.paths` instead.

## Runtime Output Promotion

Keep `data/` local and ignored. A runtime output should graduate out of `data/`
only by explicit decision:

- Move durable trained model state, calibration artifacts, and provenance
  manifests to `artifacts/`.
- Move small deterministic unit/smoke-test inputs to `tests/fixtures/`.
- Move human-readable reports that should be part of project history to
  `docs/`.
- Leave caches, raw provider payloads, live tapes, backtest scratch output,
  loop status, diagnostics, and regenerated reports under ignored `data/`.

Unit tests should not depend on the developer's local `data/` tree. Tests may
create temporary `data/...` fixture layouts under `tmp_path`,
`tempfile.TemporaryDirectory`, or an equivalent temporary working directory.

## Import Policy

The primary import contract is an installed source-layout package:

```powershell
.\venv\Scripts\python.exe -m pip install -e .
```

Manual commands, CI, tests, launchers, and scheduled-task registration should
use canonical `python -m weather...` module execution through the project venv.
When commands run from outside the repository root, the package must be
available through the editable install or an explicit package path such as
`PYTHONPATH=<repo>\src`.

Two repo-root helpers are intentionally tracked:

- `weather/__init__.py` extends the repo-root `weather` namespace to
  `src/weather` for local subprocesses started with the repository root on
  `sys.path`.
- `sitecustomize.py` adds `src/` to `sys.path` for repo-root Python processes
  and applies Windows background-worker defaults that prevent scheduled
  `pythonw.exe` jobs from opening console child windows.

These helpers are a local Windows scheduled-worker safeguard, not a replacement
for setup. Task Scheduler scripts set the working directory to the repository
root and use the repo venv's `pythonw.exe`; that combination may load the
helpers before the editable install path is consulted. If either helper is
changed, run the runtime import tests and scheduled-worker smoke checks before
updating Task Scheduler registrations.

## Documentation Command Convention

Active runbooks, README examples, CI, launchers, and scheduled-task docs should
use canonical `python -m weather...` module execution. Do not add new
operator-facing examples that execute the flat compatibility wrappers or refer
to those wrappers as the current interface.

Historical audits, dated research records, and roadmap completion transcripts
may preserve legacy commands when changing them would distort what was run at
the time. Mark those sections as historical records or command transcripts when
the legacy command is retained intentionally.
