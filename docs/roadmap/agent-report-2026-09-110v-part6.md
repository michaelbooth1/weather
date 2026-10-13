# Agent report 2026-09-110v Part 6 — optional Stage-A profiling

**Verdict: PASS on fixtures.** Per-step pyinstrument, tracemalloc and sampled
private-memory diagnostics are available behind `--profile-steps`; default
runs retain their prior behavior and write no profiling artifacts.

Branch `codex/stage-a-profile-20260927`; authorized integration base
`e3bc4dc88a785e989258ac9e24b286879568d8d1`.
Mission: [110v handoff](workstation-handoff-2026-09-110v-efficiency-fixes.md).

## Operator use and output

Add `--profile-steps --profile-out <unique-run-directory>` to the existing
approved daily-refresh invocation while retaining its admission, provenance,
release, task and stage arguments. Omission of `--profile-out` selects
`<backtest-root>/step_profiles`. No scheduled task was changed or executed.
Install the optional dependency with the project interpreter's
`-m pip install -r requirements-profiling.txt` before requesting pyinstrument
samples; no paid provider or credential is involved.

Each executed step emits its own small JSON: name, scope, PID, start time,
outcome, wall seconds, sampled peak private bytes, availability, traced peak,
and top twenty allocation sites. A separate bounded text file holds
pyinstrument output. Missing pyinstrument is explicitly reported; the other
measurements still run. Instrumentation errors cannot mask runner failures
or change successful outcomes, even with warnings configured as errors.

Windows PrivateUsage is sampled every 100 ms and at start/end, so very short
peaks can be missed. It measures this process only, never descendants.
Unsupported-platform private memory is null, not zero or an RSS substitute.
An existing process tracemalloc session is preserved and explicitly labeled
as such rather than pretending its all-process peak belongs to one step.

Profiling arguments reach isolated step children through the existing args
manifest. Child reports have scope `isolated_step`; parent reports have
`orchestrator` scope and include wait time. Do not add the two wall times or
misinterpret parent allocations as child work. A hard process kill may prevent
its terminal profile, while existing resource/containment receipts continue
to record the failure. The existing memory caps, deadlines, release binding
and resume order are untouched.

## Verification

**251 tests and 17 subtests passed** through workstation admission with all
seven repo-wide audits in every focused run. Coverage includes default-off,
real pyinstrument API, missing optional dependency, sampled memory, bounded
tracemalloc output, exception preservation, warning-as-error behavior,
preexisting tracing, CLI parsing and isolated-child propagation, plus existing
daily-refresh, resource-admission and child-receipt suites. Compileall passed.

Pyinstrument 5.1.3 was installed only into an ignored scratch dependency
directory for the real API fixture; the project environment was not changed.
No production Stage-A run, production data, venue call, credential access or
scheduled task mutation was used.

## Roll classification per file

Local `roll_verdict.ps1`: **UNDECIDABLE**, four live closure files absent.
Intended roll-free path, subject to authoritative production confirmation:

| File | Classification |
| --- | --- |
| `src/weather/operations/daily_refresh_profile.py` | New daily-refresh diagnostics |
| `src/weather/operations/daily_refresh_cli.py` | Daily-refresh CLI |
| `src/weather/operations/daily_refresh_status.py` | Daily-refresh step orchestration |
| `src/weather/operations/daily_refresh_step_child.py` | Daily-refresh isolated step entry |
| `tests/operations/test_daily_refresh_profile.py` | Test-only |
| `requirements-profiling.txt` | Optional dependency list; existing capture requirements unchanged |
| Operations design, this report, correspondence index | Roll-free documentation |

Update the branch to landed master and regenerate the correspondence index
before integration; this handback grants no production execution authority.
