# Development and Verification

Status: canonical development guide. The root [README](../README.md) owns setup
and the full operator command catalog; this document owns change workflow and
verification expectations. The [Git workflow SOP](git-workflow.md) owns branch,
worktree, staging, commit, pull-request, integration, and cleanup procedure.

## Before editing

- Inspect `git status --short` and preserve unrelated changes.
- Read the nearest `AGENTS.md` and identify the owning package.
- Confirm whether the task touches local evidence, generated config, tracked
  artifacts, a scheduled task, release state, or a network service.
- Prefer a canonical `python -m weather...` entry point over a flat wrapper.

## Baseline commands

From the repository root on Windows:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
```

`pytest.ini` collects only `tests/` and exposes `src/`. The editable install is
still the primary package contract. CI uses Python 3.11 on Ubuntu, so production
modules must remain cross-platform even though scheduled operations are Windows
specific. Tests that actually execute Windows PowerShell, ACL, Scheduler, or
Job semantics carry precise non-Windows skips; their static and portable Python
contracts continue to run on Ubuntu, while executable Windows coverage remains
part of the admitted production-host bounded suite.

On the 16 GB production capture host, the commands above are not authority to
run a direct full suite or parallel verification. Focused tests run serially
only inside 00:30–09:00; the full suite uses
`scripts/ops/bounded_worktree_test_suite.ps1` with its 25-file chunks and
workload lease. The user-layer Codex hook rejects direct unbounded pytest at
every hour and rejects pytest/compileall outside that window.

On a separate non-capture workstation, including the 32 GB PC when it also
holds the portable live-executor assignment, ordinary local development and
verification are not subject to the capture-host timetable, 25-file wrapper,
or serial-only rule. Route recognized heavy Python work through
`scripts/ops/workstation_heavy.ps1` with an absolute repository root, absolute
Python path, and the documented base64 JSON argument contract. Its distinct
offline profile admits only the assignment's exact non-capture Windows
installation and attending principal and holds the same host-global mutex as
the portable launcher. Both paths own their complete child tree in a kill-on-
close Windows Job, so wrapped heavy work and launched live work cannot overlap.
Size concurrency to the workstation's current resources and finish heavy work
before sealing to avoid spending an attempt. This does not authorize
production `data/` access, Scheduler or capture mutation, credentials,
networked collectors, exchange contact, or live orders, and a workstation
PASS does not replace any explicitly required production-host qualification.

An attended PowerShell operator can build the bounded argument contract like
this (use `compileall` or an allowlisted `weather_heavy` module as appropriate).
This variable-based form is for a person at an interactive shell, not for a
Codex tool call:

```powershell
$repoRoot = (Resolve-Path .).Path
$pythonPath = (Resolve-Path .\venv\Scripts\python.exe).Path
$argumentJson = ConvertTo-Json -InputObject @("-m", "pytest", "-q") -Compress
$argumentBase64 = [Convert]::ToBase64String(
  [Text.Encoding]::UTF8.GetBytes($argumentJson)
)
& (Join-Path $repoRoot "scripts\ops\workstation_heavy.ps1") `
  -Kind pytest -PythonPath $pythonPath -ArgumentsBase64 $argumentBase64 `
  -RepoRoot $repoRoot
```

For a Codex tool call, replace every `C:\absolute\weather` placeholder with the
same real repository root, then submit this exact literal shape as one line:

```powershell
& 'C:\absolute\weather\scripts\ops\workstation_heavy.ps1' -Kind pytest -PythonPath 'C:\absolute\weather\venv\Scripts\python.exe' -ArgumentsBase64 'WyItbSIsInB5dGVzdCIsIi1xIl0=' -RepoRoot 'C:\absolute\weather'
```

The hook accepts the wrapper owned by that absolute repository root, in the
exact parameter order shown, with literal absolute paths and a literal
canonical base64 value. A sibling worktree or clone is accepted only
when its workstation wrapper, workload-admission script, and Windows Job helper
are byte-identical to the installed hook's reference checkout. Compute the
base64 value in a light command, then submit the wrapper invocation as a second
command; backtick continuations, chained commands, variables, `Join-Path`, and
other dynamically expanded forms fail closed.

### Starting workstation verification from the capture controller

The capture host's hook distinguishes one literal SSH transport from local
heavy work. The original ambient-config form (`ssh weather-workstation ...`)
remains rejected: SSH configuration can itself start local processes through
`Match exec`, `ProxyCommand` or `LocalCommand`.

Use the Windows system OpenSSH executable, existing workstation identity key
and known-hosts file under the controller user's `.ssh` directory, an explicitly
reviewed RFC1918 IPv4 address, and the exact token order below. Replace every
placeholder with a literal value. Paths use forward slashes and may contain
only ASCII letters, digits, underscores, dots and hyphens; spaces, traversal,
quotes, variable expansion, command chaining and additional options are refused.

```text
C:/Windows/System32/OpenSSH/ssh.exe -F none -T -n -o BatchMode=yes -o StrictHostKeyChecking=yes -o PermitLocalCommand=no -o ProxyCommand=none -o ProxyJump=none -o ClearAllForwardings=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 -o HostName=<workstation-ip> -i C:/Users/<controller>/.ssh/id_ed25519_workstation_codex -o UserKnownHostsFile=C:/Users/<controller>/.ssh/known_hosts -l <workstation-user> weather-workstation C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <remote-repo>/scripts/ops/workstation_heavy.ps1 -Kind pytest -PythonPath <remote-python.exe> -ArgumentsBase64 WyItbSIsInB5dGVzdCIsIi1xIl0= -RepoRoot <remote-repo>
```

This grants transport only. Independently review the exact remote checkout and
wrapper dependency bytes before dispatch, preserve source identity evidence,
and retain/poll the SSH executor session through terminal exit. The controller
cannot hash remote files as though their paths were local. The remote wrapper
must still prove the tracked non-capture Windows installation and attending
principal, acquire its host-global mutex, and contain its full child tree in
the Windows Job. A refused admission or uncertain remote termination remains
fail-closed. Changing the SSH route grants no source, capture, exchange,
Scheduler or deletion authority.

The controller also admits the exact offline module
`weather.operations.workstation_cold_archive_stage` through this transport.
The reviewed remote checkout must contain the adapter and independently admit
it in its workstation wrapper. This module stages only an explicitly declared
provisional mirror copy; its validation, encryption, create-only evidence and
source-retention gates remain mandatory. This controller admission does not
install the adapter on production or authorize production hashing, upload,
restore or deletion. Those actions retain their separate mission and host-load
requirements; the disk-headroom policy is unchanged.

`-F none` ignores both user and system SSH configuration; strict host-key
checking uses existing trust and cannot enroll a new host in this lane. The
hook validates the same base64/module arguments as local workstation calls.
It still rejects every local workstation-wrapper launch on the capture host,
unknown capture-host identity, all ambiguous remote forms, and unsupported
remote destinations. See the official [SSH command manual](https://man.openbsd.org/ssh.1)
and [SSH configuration manual](https://man.openbsd.org/ssh_config.5).

The focused [host-load hook workflow](../.github/workflows/host-load-hook.yml)
runs the policy tests on Windows and Linux when hook code or its tests change.
It uses no application fixtures or credentials and provides a verification
path while an installed hook prevents dispatch of its own proposed repair.

## Focused verification matrix

| Change | Minimum focused verification |
| --- | --- |
| Streamlit router/view | `pytest tests/app -q` |
| Source adapter/history | matching `tests/sources` tests; no live network in unit tests |
| Model/distribution/features | matching `tests/model`; C and F paths; mass/floor/cutoff checks |
| Training/calibration | matching `tests/calibration`; train/serve schema and artifact compatibility |
| Snapshot/forecast collection | matching `tests/collection`; atomicity, cadence, and replay persistence |
| Market, maker, or taker logic | matching `tests/market`; keep execution non-live |
| Daily/nightly/supervisor behavior | matching `tests/operations`; use status/dry-run paths |
| Reports, gates, roadmap | matching `tests/reporting`; verify fail-closed evidence behavior |
| Package/import/path changes | `tests/operations/test_import_architecture.py` |
| Canonical docs/agent files | `python -m weather.operations.agent_docs_audit` |
| Roadmap item/index or generated backlog | roadmap lint plus `roadmap_backlog --fail-on-lint --check` after regeneration |

Run the full suite for cross-owner changes, release/evidence contracts, shared
utilities, or before handing off a broad refactor.

## Stateful command boundaries

The following categories require inspection before execution because they can
write local or tracked state, use the network, change scheduled tasks, or affect
serving:

- source backfills and location-event refresh;
- Windows task registration and loop start/restart/stop commands;
- artifact registry, size, externalization, and promotion-preflight generators;
- cleanup, retention, migration, and archive commands;
- candidate creation, release promotion/rollback, and any live exchange mode.

Use `--help`, read the relevant [operations runbook](operations/README.md), and
prefer status, audit, dry-run, read-only, shadow, or paper modes. Never assume an
argument-free registration example is valid; the script parameter block is the
executable source of truth.

## Model-change evidence

A model improvement claim needs more than unit tests. Preserve training/live
feature parity, run captured-input or frozen-tape replay as appropriate, compare
against market prices with proper scoring, inspect protected slices and data
quality, and keep the candidate inactive until promotion and release gates pass.
Exact gates evolve and belong to the release/runbook code, not copied prose.

## Definition of done

- The intended behavior is implemented through the correct owner.
- Focused tests pass; broader checks match the change risk.
- New behavior is deterministic and network-free under unit tests.
- Schemas, fixtures, manifests, and documentation are updated together where
  their source contracts changed.
- No secrets, machine-specific paths, ignored runtime files, or unrelated user
  changes entered the diff.
- Documentation links and knowledge contracts pass the agent-doc audit.

## Update this file when

Update when baseline checks, test ownership, CI platforms, stateful command
boundaries, or the repository-wide definition of done changes.
