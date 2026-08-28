# Repository Instructions for Coding Agents

This repository is maintained primarily by coding agents. Keep guidance short,
durable, and linked to one canonical source instead of copying volatile facts.

## Start here

1. Read the user request and inspect `git status --short` before editing. Existing
   changes belong to the user unless the task says otherwise.
2. **Read [the state of play](docs/operations/STATE_OF_PLAY.md) — always, first, whatever
   the task.** It is ~90 lines and answers *what is happening right now*: the current
   critical path, decisions that are closed, and the questions already answered that you
   must not spend the session re-deriving. The other canonical files are durable and say
   nothing about today. If you are resuming after a context compaction, start here.
3. **For production-host operations, read the
   [operations agent role](docs/operations/OPERATIONS_AGENT_ROLE.md) before acting and the
   [reserved confirmation window](docs/operations/reserved-confirmation-window.md) before
   accessing dated evidence.** The reserved-window contract overrides handoffs and role text.
4. Read [the durable domain context](docs/operations/AGENT_CONTEXT.md).
5. **For any model, measurement, or research task, read
   [established findings](docs/operations/ESTABLISHED_FINDINGS.md) and
   [retracted claims and false leads](docs/operations/RETRACTED_AND_FALSE_LEADS.md).**
   The dated correspondence under `docs/roadmap/` is ~600 files and cannot be read;
   those two files are its distilled state. Skipping them causes agents to
   re-derive known results or rebuild retracted ones.
6. **For a cross-host mission — writing a handoff, executing one, or verifying a
   handback — read [the delegation contract](docs/operations/DELEGATION_CONTRACT.md).**
   Its standing boundaries bind every mission whether or not the handoff restates them.
7. Use [the documentation map](docs/README.md) to load only the context needed
   for the task.
8. Read the nearest nested `AGENTS.md` before changing files below it. Nested
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
- The trading product is **International Polymarket only**. Polymarket US code,
  fixtures, and historical evidence are compatibility surfaces, not an allowed
  platform for new probes, credentials, live-readiness, or order mutation.
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
- On the dedicated 16 GB capture host, agent-started or ad-hoc heavy work is
  allowed only from 00:30–09:00 local and must hold the shared lease from
  `scripts/ops/workload_admission.ps1`. The repository-owned Stage-A daily
  chain is the sole scheduled exception: it may run 09:30–11:55 under an
  absolute child-tree teardown deadline. The 12:00–18:00 graded window and
  18:00–00:30 near-close window are protected; separate resource checks do
  not make overlapping heavy jobs safe.
- That timetable does not govern a separate non-capture workstation. The
  32 GB workstation may run ordinary implementation, tests, training, and
  replay work without the capture-host window or lease, including when that
  same physical PC is assigned the portable live-executor role, but never
  while a sealed live attempt is active. End heavy workstation processes
  before sealing or launching a live stage, and do not start them until that
  stage has terminal cleanup evidence. Live work still requires the exact
  host-bound `portable_execution_v1` International
  Stage 0/1 lane in `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`; this
  workstation allowance grants no capture, production-state, Scheduler,
  credential, exchange, unattended-trading, or live-order authority.
- **Merging code on the production host can restart live capture.** Supervisors
  fingerprint the source files they have imported, so landing a change to a
  loop-imported module triggers a `STALE_CODE` readoption restart. Inside the
  12:00-18:00 graded window that can cost a streak day — the #1 operational
  objective. **Get the verdict from `scripts\ops\roll_verdict.ps1 -Branch <b>`;
  never derive it by hand.** Roll-sensitive branches merge in the 01:00-04:00
  quiet window via `scripts/ops/quiet_window_merge.ps1`, which consults that
  verdict, merges locally, proves all three capture workers recovered, and
  only then invokes `WeatherOneShotPush` and verifies `origin/master`.
  New scheduled integrations use immutable per-attempt manifests and receipts
  through `docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md`: a failed attempt is
  frozen, but a reviewed repair or one bounded unchanged retry may create a new
  attempt instead of freezing the entire night.
  **A roll-free branch does not need the quiet window** — requiring it of every
  branch is what backed the merge queue up to 25 branches. Markdown, `docs/`,
  `config/` and `.ps1` are roll-free. **Pushing a branch never rolls anything**,
  at any hour: the fingerprint is over the production working tree, not remote
  refs. See [the delegation contract](docs/operations/DELEGATION_CONTRACT.md) §3
  and [the code-soak streak runbook](docs/ops/streak-soak.md).
- **Heavy work on the 16 GB production host is time-gated independently of merge
  sensitivity.** Before a full test suite, training, bulk replay, or other heavy command, read
  [the host load policy](docs/operations/HOST_LOAD_POLICY.md) and use its repository-owned
  workload admission path. Do not treat a roll-free diff as permission to consume protected
  capture resources.
- Codex verification on the production host is serial as well as time-gated.
  Never launch pytest, compileall, replay, training, or bulk scans through
  parallel agents or parallel tool calls. A direct full pytest run is forbidden
  at every hour; use the repository-owned 25-file bounded suite in the
  00:30–09:00 admitted window. The user-layer Codex hook and one-minute S4U
  guard enforce the host load policy; do not bypass either control, and always
  retain and poll or terminate any yielded executor session ID.
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
- **What is happening right now, and what is already decided or answered:
  `docs/operations/STATE_OF_PLAY.md`.** Rewritten, never appended, capped at ~90
  lines. Every other canonical file is durable and deliberately says nothing
  about today.
- Current work items: generated `docs/roadmap/active-backlog.md`; numbered roadmap
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
