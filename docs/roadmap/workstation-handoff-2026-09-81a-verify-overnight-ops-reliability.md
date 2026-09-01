# Workstation handoff 2026-09-81a — verify overnight operations reliability

Written 2026-09-01 by the production agent. Execute on the assigned 32 GB
workstation. This mission verifies and, if necessary, repairs an unattended
operations change; it grants no production-host, provider, exchange, live,
credential, promotion, merge, or scheduled-task authority.

## 1. Source identity

- Source branch: `codex/overnight-ops-reliability-20260901`
- Implementation commit: `3e9b2c08c0f85468d1d5956cfd3bdcd0c7e3e2d3`
- Implementation tree: `d2d83251cd97a6f2f06997552f86e5954f77e82d`
- Workstation branch:
  `codex/workstation-overnight-ops-reliability-2026-09-81a`
- Report:
  `docs/roadmap/agent-report-2026-09-05-workstation-overnight-ops-reliability.md`

Fetch the source branch and require the implementation commit and tree above
to be an ancestor of its final handoff-only tip. Stop on any identity mismatch.
Create the workstation branch from the final source-branch tip. Do not merge,
delete, rewrite, or retarget any existing branch.

## 2. Why this exists

The September 1 overnight review found two concrete defects:

1. `WeatherSettlementBackfill20260830_0901a` returned 2 and wrote a `REFUSED`
   receipt because Windows serialized the inline Python `-c` program as only
   `import`. The configured Scheduler restart did not create another run.
2. `health_watchdog.ps1` launched nested `status.ps1 -Json` without an explicit
   repository root, received no parseable JSON, and made the unattended morning
   briefing blind.

The implementation replaces inline registry source with a canonical module,
adds one separately scheduled receipt-driven successor, and binds the nested
status call to the canonical root while preserving its child exit code. The
production host passed PowerShell AST parsing, exact module execution over all
12 built-in markets, agent-doc audit, roadmap lint/check, diff checks, and one
light watchdog pass with five real alerts and zero blind alerts. It did not run
pytest, compileall, a backfill, replay, or training after 09:00.

## 3. Verification mission

Read `AGENTS.md`, `docs/operations/STATE_OF_PLAY.md`,
`docs/operations/AGENT_CONTEXT.md`, `docs/operations/ESTABLISHED_FINDINGS.md`,
`docs/operations/RETRACTED_AND_FALSE_LEADS.md`,
`docs/operations/DELEGATION_CONTRACT.md`,
`docs/operations/HOST_LOAD_POLICY.md`, and the nested agent files before work.

Review every changed line and prove these behaviors:

- registry discovery executes
  `python -m weather.operations.settlement_backfill_registry`, imports the
  current checkout's canonical registry, returns the complete unique fleet,
  and cannot silently shrink the all-market denominator;
- the registrar creates exactly one primary and one successor, at least 30
  minutes apart and wholly inside 00:30-09:00, with S4U/Limited,
  `StartWhenAvailable=false`, `RestartCount=0`, `IgnoreNew`, `WakeToRun`, exact
  actions, and fail-closed readback;
- no second pair can overlap a running or still-due pair, while inert
  historical tasks remain evidence and do not freeze a later reviewed attempt;
- the successor validates the primary's exact executable, arguments, working
  directory, target, task state, run evidence, and receipt attribution; skips
  `SETTLED`; refuses ambiguity; invokes the canonical wrapper at most once; and
  succeeds only on a final all-market `SETTLED` receipt;
- a failed second-task registration disables the primary, and any readback
  mismatch disables both tasks;
- the watchdog passes `-RepoRoot`, captures `$LASTEXITCODE` before parsing, and
  retains an explicit blind alert for genuinely invalid JSON.

Add deterministic regression coverage where the source-only ratchets are not
enough. Exercise scheduled-task behavior only through mocks or an isolated
test double. Do **not** register, start, stop, disable, or delete real Windows
tasks on the workstation. Include at minimum the settled skip, running-primary
refusal, stale-receipt refusal, exact one-call retry success/failure, pair
registration/readback rollback, active-pair refusal, and inert-history
allowance. If a defect is found, repair it on the workstation branch and
explain the exact failure and new proof in the report.

Run the focused operations tests, compileall, documentation checks, and the
complete suite. Every pytest/compileall invocation must use the canonical
host-bound `scripts/ops/workstation_heavy.ps1` admission wrapper with an
absolute project interpreter and repository root. Do not bypass its mutex,
assignment, poison, or kill-on-close controls. Retain and poll every yielded
executor session until it finishes or terminate it explicitly.

Run the canonical roll verdict against the finished workstation branch:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch codex/workstation-overnight-ops-reliability-2026-09-81a
```

Report its exact exit code and per-file result; never derive roll sensitivity
by hand.

## 4. Boundaries

- No production `data/` access or copying. The workstation mirror is not
  production authority.
- No weather-provider, exchange, credential, account, geoblock, live-order, or
  network collector call.
- No real Task Scheduler mutation. Do not recreate the spent production task.
- No backfill, daily-refresh chain, training, replay, promotion, release, or
  model change.
- Do not weaken the time window, workload lease, Job containment, exact
  all-market settlement proof, train/serve parity, or release gates.
- Install nothing and add no LFS objects or large artifacts.
- Do not merge or open a non-draft PR. Push the finished topic branch at any
  hour, as the delegation contract allows.

## 5. Handback

Commit and push the workstation branch. The report must include:

- exact source, final commit, final tree, and `origin/<branch>` equality;
- files changed and why;
- focused test, compileall, docs audit/backlog, full-suite, and canonical roll
  verdict commands with exact results;
- proof that no real scheduled task or protected external system was touched;
- `PASS`, `REPAIR_REQUIRED`, or `BLOCKED`, with every remaining production-only
  step stated explicitly.

The production-only follow-up is a reviewed adoption decision and, no earlier
than a future admitted 00:30-09:00 window, registration of a fresh pair for an
actually open date. A green workstation branch does not authorize either.
