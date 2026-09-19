# Repository Instructions for Coding Agents

The always-loaded entry point for every coding agent (Codex reads it directly;
Claude Code through `CLAUDE.md`). It owns repository-wide rules and task routing
only, links to owners for detail, and never carries status, counts, or dates.

## Start here — every task

1. Read the user request and inspect `git status --short` before editing. Existing
   changes belong to the user unless the task says otherwise.
2. Read [the state of play](docs/operations/STATE_OF_PLAY.md): the only file about
   *right now* — objectives, critical path, closed decisions, answered questions.
   Every other canonical file is durable. Re-read it after a context compaction.
3. Read the nearest nested `AGENTS.md` before changing files below it. Nested
   instructions supplement this file and take precedence for their subtree.

## Read when — load only what the task needs

| If the task involves | Read before acting |
| --- | --- |
| Acting on the 16 GB production capture host (ops, scheduler, merges, recovery) | [Operations agent role](docs/operations/OPERATIONS_AGENT_ROLE.md) |
| Any heavy command: tests, compileall, training, replay, bulk scans | [Host load policy](docs/operations/HOST_LOAD_POLICY.md) |
| Model, measurement, or research | [Findings digest](docs/operations/FINDINGS_DIGEST.md) first; then only the sections it cites in [established findings](docs/operations/ESTABLISHED_FINDINGS.md) and [retracted claims and false leads](docs/operations/RETRACTED_AND_FALSE_LEADS.md). Skipping the digest makes agents re-derive known results or rebuild retracted ones. |
| Domain semantics: settlement, units, source roles, floors | [Durable domain context](docs/operations/AGENT_CONTEXT.md) |
| A cross-host mission: writing a handoff, executing one, verifying a handback | [Delegation contract](docs/operations/DELEGATION_CONTRACT.md) (its standing boundaries bind every mission) and [the roadmap agent guide](docs/roadmap/AGENTS.md) |
| Reading dated evidence or settled market-days for evaluation | [Reserved confirmation window](docs/operations/reserved-confirmation-window.md) — read its status line; the rest applies only if it says a window is reserved. When one is reserved, that contract overrides handoffs and role text. |
| Live trading, the maker pilot, maker economics | [International MM live pilot](docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md) and [item 330](docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md) |
| Branches, worktrees, commits, pushes, pull requests | [Git workflow SOP](docs/git-workflow.md) |
| Anything else | [Documentation map](docs/README.md) — routes every canonical document by task |

Dated roadmap and research documents are historical evidence, not instruction,
unless a canonical index labels them current, and the `docs/roadmap/` correspondence
is too large to read. Open a dated file only when the digest, a numbered item, or
the user's task names it. Never use `.claude/settings.local.json` or machine-local agent
memory as project guidance; durable knowledge lives in this repository.

## Non-negotiable contracts

- Canonical domain implementation lives under `src/weather/`; `app/` owns the
  Streamlit UI. The former root app/CLI helpers, flat `src/*.py` wrappers, and
  root script copies are retired and must not be reintroduced.
  `sitecustomize.py` and `weather/__init__.py` are intentional bootstrap
  safeguards described by the path policy; do not grow domain logic in them.
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
- **Heavy work on the dedicated 16 GB capture host is time-gated, leased, and
  serial** — independently of whether a diff is roll-free.
  [The host load policy](docs/operations/HOST_LOAD_POLICY.md) owns the detail.
  - Agent-started or ad-hoc heavy work (full test suite, compileall, training,
    bulk replay, bulk scans) is allowed only 00:30–09:00 local and must hold the
    shared lease from `scripts/ops/workload_admission.ps1`. Separate resource
    checks do not make overlapping heavy jobs safe.
  - The sole scheduled exception is the repository-owned Stage-A daily chain,
    09:30–11:55 under an absolute child-tree teardown deadline. The 12:00–18:00
    graded window and 18:00–00:30 near-close window are protected.
  - Never launch pytest, compileall, replay, training, or bulk scans through
    parallel agents or parallel tool calls. **A direct full pytest run is
    forbidden at every hour**; use the 25-file bounded suite,
    `scripts/ops/bounded_worktree_test_suite.ps1`, in the admitted window.
  - The user-layer Codex hook and the one-minute S4U guard enforce this policy.
    Do not bypass either, and always retain and poll or terminate any yielded
    executor session ID.
- That timetable binds only the capture host. A separate non-capture workstation
  (the 32 GB PC, even while it holds the portable live-executor assignment) may
  run implementation, tests, training, and replay without the window,
  bounded-suite, or serial rules, but heavy commands there must use
  `scripts/ops/workstation_heavy.ps1` and should finish before a live attempt is
  sealed (the host load policy owns the wrapper, mutex, and child-tree contract).
  This grants no capture, production-state, Scheduler, credential, exchange,
  unattended-trading, or live-order authority; live work still requires the
  host-bound `portable_execution_v1` lane in
  [the portable execution-host runbook](docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md).
- **Merging code on the production host can restart live capture.** Supervisors
  fingerprint the source files they have imported, so landing a change to a
  loop-imported module triggers a `STALE_CODE` readoption restart. Inside the
  12:00–18:00 graded window that can cost a capture day, and capture evidence is
  the first operating objective (streak *contiguity* is not; established
  findings §0d). **Get the verdict from
  `scripts\ops\roll_verdict.ps1 -Branch <b>`; never derive it by hand.**
  Roll-sensitive branches merge in the 01:00–04:00 quiet window via
  `scripts/ops/quiet_window_merge.ps1`, which consults that verdict, merges
  locally, proves all three capture workers recovered, and only then invokes
  `WeatherOneShotPush` and verifies `origin/master`. New scheduled integrations
  use immutable per-attempt manifests and receipts
  ([runbook](docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md)): a failed attempt
  is frozen, but a reviewed repair or one bounded unchanged retry may create a
  new attempt instead of freezing the night. **A roll-free branch does not need
  the quiet window**: Markdown, `docs/`, `config/` and `.ps1` are roll-free.
  **Pushing a branch never rolls anything**, at any hour: the fingerprint is over
  the production working tree, not remote refs. See
  [the delegation contract](docs/operations/DELEGATION_CONTRACT.md) §3 and
  [the capture-day grading and guarded-merge runbook](docs/ops/streak-soak.md).
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
| `scripts/ops/` | Windows scheduled-task registration and host wrappers | `scripts/ops/AGENTS.md` |
| `docs/` | Canonical guides plus historical evidence | `docs/AGENTS.md`, `docs/README.md` |
| `tools/` | Local helpers and research utilities | `tools/AGENTS.md`; prefer packaged `weather.*` CLIs for durable workflows |

## Development workflow

Run canonical commands from the repository root with the project interpreter:

```powershell
# Workstation/CI only. Capture host: direct full pytest is FORBIDDEN AT EVERY HOUR;
# focused tests and compileall run serially 00:30-09:00; the full suite runs only
# through scripts\ops\bounded_worktree_test_suite.ps1.
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```

Start with focused owner-package tests, then expand in proportion to risk.
Collectors, task registration, manifest generation, promotion, and cleanup are
stateful; read help and the runbook first. [development.md](docs/development.md)
owns the test matrix, host rules, and definition of done.

## Knowledge ownership and keeping docs true

[documentation-maintenance.md](docs/documentation-maintenance.md) owns the
ownership map, change triggers, checks, and the line budgets for always-loaded
files (this one included). The rules agents most often break:

- Today's state, closed decisions, and answered questions live only in
  `docs/operations/STATE_OF_PLAY.md` (rewritten, never appended). An owner
  decision goes there and into its numbered item.
- A measured result goes to the findings digest and established findings; a
  claim found wrong goes to retracted claims. Work status goes to the numbered
  item under `docs/roadmap/items/`, never into an `AGENTS.md`.
- Exact versions, counts, hashes, and active state belong to code, config,
  manifests, and generated reports — never copied into prose.
- When behavior, CLI flags, paths, config, schemas, scheduled tasks, or
  topology changes, update the owning document in the same change. `README.md`
  owns product purpose, setup, dashboard, and the operator command catalog;
  `docs/README.md` owns document routing; this file, `CLAUDE.md` (import only),
  and scoped `AGENTS.md` files own agent rules.

## Update this file when

Update only when repository-wide invariants, task routing, canonical entry points,
or baseline checks change. Subsystem detail goes in the nearest scoped `AGENTS.md`.
