# Repository Instructions for Coding Agents

This repository is maintained primarily by coding agents. Keep guidance short,
durable, and linked to one canonical source instead of copying volatile facts.

## Start here

1. Read the user request and inspect `git status --short` before editing. Existing
   changes belong to the user unless the task says otherwise.
2. Read [the durable domain context](docs/operations/AGENT_CONTEXT.md).
3. Use [the documentation map](docs/README.md) to load only the context needed
   for the task.
4. Read the nearest nested `AGENTS.md` before changing files below it. Nested
   instructions supplement this file and take precedence for their subtree.

Do not use `.claude/settings.local.json` as project guidance. It is ignored,
machine-local state.

## Non-negotiable contracts

- Canonical domain implementation lives under `src/weather/`; `app/` owns the
  canonical Streamlit UI. The former root app/CLI helpers, flat `src/*.py`
  wrappers, and root script copies are retired and must not be reintroduced.
  `sitecustomize.py` and `weather/__init__.py` are intentional Windows/package
  bootstrap safeguards described by the path policy; do not grow domain logic
  in them.
- Built-in markets operate end-to-end in their native settlement unit.
  Legacy names ending in `_c` do not prove that a value is Celsius.
- Configured Weather Underground history is the settlement proxy. METAR, ECCC,
  NWS, Open-Meteo, marine, and related sources are supporting evidence unless a
  specific contract explicitly says otherwise.
- Paid weather-provider access is unsupported. Do not add credentials, required
  environment variables, or plans that depend on a paid weather source.
- Model changes must preserve train/serve feature parity, effective WU print
  cutoff semantics, probability mass, captured-input replay, and release
  binding. A plausible forecast is not proof of edge over market prices.
- `data/` is ignored local runtime state. Some local files are operationally
  durable evidence, but none can be assumed to exist in a clean checkout.
  Never delete or rewrite tapes, ledgers, or trading evidence casually.
- Keep ordinary work in research, shadow, dry-run, read-only, or paper modes.
  Live trading or promotion requires an explicit user request and the existing
  readiness/release gates.
- Build repository-owned paths with `weather.paths`; do not make runtime code
  depend on the current working directory.

## Repository map

| Path | Responsibility | Read next |
| --- | --- | --- |
| `src/weather/` | Canonical packages and CLIs | `src/weather/AGENTS.md`, `docs/architecture.md` |
| `app/` | Streamlit router and views | `app/AGENTS.md` |
| `tests/` | Deterministic tests and architecture ratchets | `tests/AGENTS.md` |
| `config/` | Durable registries and generated event metadata | `config/AGENTS.md` |
| `artifacts/` | Tracked model state, manifests, and releases | `artifacts/AGENTS.md` |
| `scripts/ops/` | Windows scheduled-task registration | `scripts/ops/AGENTS.md` |
| `docs/` | Canonical guides plus historical evidence | `docs/AGENTS.md` |
| `tools/` | Local helpers and research utilities | `tools/AGENTS.md`; prefer packaged `weather.*` CLIs for durable workflows |

## Development workflow

Run canonical commands from the repository root with the project interpreter:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```

Start with focused tests for the owner package, then expand verification in
proportion to risk. Network collectors, scheduled-task registration, artifact
manifest generation, promotion, and cleanup are stateful; inspect help and the
relevant runbook before running them. See [development.md](docs/development.md)
for the test matrix and definition of done. Follow the
[Git workflow SOP](docs/git-workflow.md) for branch/worktree isolation,
staging, commits, pull requests, integration, and cleanup.

## Knowledge ownership

- Product purpose, setup, dashboard, and operator command catalog: `README.md`.
- Agent workflow and task routing: this file and scoped `AGENTS.md` files.
- Domain invariants: `docs/operations/AGENT_CONTEXT.md`.
- Architecture and data flow: `docs/architecture.md`.
- Package/import ownership: `docs/operations/package-boundaries.md`.
- Git branches, worktrees, staging, commits, and pull requests:
  `docs/git-workflow.md`.
- Current work: generated `docs/roadmap/active-backlog.md`; numbered roadmap
  item files own item status, scope, and evidence.
- Dynamic truth: code, checked-in config, manifests, and generated reports—not
  copied counts or versions in prose.
- Dated roadmap and research documents are historical evidence unless a
  canonical index explicitly labels them current.

When behavior, CLI flags, paths, config, schemas, scheduled tasks, or operational
topology changes, update the owning documentation in the same change. Follow
[documentation-maintenance.md](docs/documentation-maintenance.md).

## Update this file when

Update this file only when repository-wide invariants, task routing, canonical
entry points, or required baseline checks change. Put subsystem details in the
nearest scoped `AGENTS.md` and link to their canonical source.
