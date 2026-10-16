# Live launcher Ctrl+Break: root cause of the #230 host failures (2026-10-06)

**Status:** root-cause record for the owner. It changes no code. The test fix and
the regression guards are on PR #230 (`claude/integration-20261006-rf2`).

## Summary

The repository's `sitecustomize.py` drops Ctrl+Break in **test contexts only**.
The real live launch path is not affected.

- **The cause.** When the repository root is on `sys.path` at start-up,
  `sitecustomize.py` wraps `subprocess.Popen` and adds `CREATE_NO_WINDOW` to every
  child. It does this unless `WEATHER_ALLOW_CONSOLE_CHILDREN=1` is set.
  `weather.operations.windows_silent` does the same in the modules that call it.
- **Why the break is lost.** The runner's PowerShell child then gets a separate
  windowless console. Ctrl+Break is a console event that only reaches processes
  on the sender's console, so it never arrives.
- **Why the tests looked cooperative.** The test stub then reaches its own exit,
  and the runner still reports `cooperative=true`.
- **Where it happened.** This is what failed #230's two tests in the host bounded
  suite (chunks 16 and 18, 2026-10-06). The same tests pass wherever the repository
  root is not on the start-up path.
- **The live path.** `fixed_session_launcher.ps1.tmpl` starts the runner with
  `python -I -S -B`, so it never loads `sitecustomize` or `site`. Importing the
  runner under exactly that configuration leaves `Popen` unpatched and never
  imports `windows_silent`. The launcher child therefore shares the operator's
  console, which is the only production start path. (Workstation survey:
  operator console, then `Start-WeatherInteractiveProcessInJob`, then the runner.)

## Evidence

All of this uses stub scripts only: no credentials, no orders, no network. The
stub registers a `DebuggerStop` handler that writes `BREAK` when PowerShell
handles Ctrl+Break, so the evidence does not depend on console text.

| Runner process context (workstation) | Break delivered (BREAK marker) |
| --- | --- |
| Isolated or no `sitecustomize`. Tried with stdin as NUL, inherited, an open pipe and real console input (`CONIN$`); also via hidden `Start-Process`, `workstation_heavy`, and pytest in-process or as a child. | Yes, every run: 4 to 6 reps per context, 26–102 ms after the deadline |
| `PYTHONPATH` = repository root, so `sitecustomize` is loaded | **Never**, in every run |
| The same, with `WEATHER_ALLOW_CONSOLE_CHILDREN=1` | Yes, 38–84 ms |
| `-I -S` import of the runner, as the template does it | `Popen` unpatched; `windows_silent` and `sitecustomize` not loaded |

**Withdrawn.** An earlier report that the launcher "can park" after Ctrl+Break is
withdrawn. Its probes ran next to a scratch file named `bisect.py`, which shadowed
the standard-library `bisect` module, so they started recursive concurrent
runners.

## Method rule for future probes

- Run probes from a folder that contains no `.py` file named after a
  standard-library module.
- Cap the number of child processes in any probe driver.
- Check `sys.path` before trusting a surprising result.
- After an aborted probe, sweep for and stop leftover processes.

## What changed on #230 (tests and guards only)

- **Test harness.** The cooperative Ctrl+Break tests now start the runner exactly
  as the template does (`-I -S -B`, the template's bootstrap, the repository
  working directory, a shared console). The precondition is the stub's `BREAK`
  marker. Every outcome assert stays hard: cooperative, not forced, exit code,
  cleanup time.
- **Mutants that must fail.** A runner that sends no Ctrl+Break, and a helper that
  loads `sitecustomize`. Both still show a "cooperative" outcome, and both must
  fail the check.
- **Regression guards.** These fail CI if:
  - the template loses `-I -S` (Windows PowerShell evaluates the template's
    tokens);
  - importing the runner under that isolation patches `Popen`;
  - the runner's import closure ever reaches `windows_silent`, `sitecustomize` or
    `apply_windows_silent_subprocess_defaults`.
- **Runbook.**
  - `INTERNATIONAL_MM_LIVE_PILOT.md` records the isolation requirement.
  - The C3 keyless console rehearsal gains one step: at the real operator console,
    the interrupt path must show the stub's `BREAK` marker and a cooperative exit.

## Recommendation

- **Land #230 (#228 + #229 + this fix) in N2.** Use a fresh roll verdict and an
  independent review.
- **A stop-file or named-event cooperative stop is optional hardening, not
  required.** The property holds in the live path and is now testable on every
  host. Reconsider it only if a future live path runs the launcher without a
  shared console.
