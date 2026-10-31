# Agent report 2026-10-03 — capture families in status.ps1 and the cockpit

Workstation (Claude Code), implementation with fixtures only. Follows the
[lowest-temperature capture report](agent-report-2026-10-03-lowest-temperature-capture.md) (#172, `d01d7ce1`), which
left two gaps: `status.ps1` and the cockpit did not read a capture family's status. Branch
`codex/capture-families-status-20261003`, stacked on #172 (PR base `codex/lowest-temp-capture-20261003`).

## Verdict

**Built: both readers now cover every family in `config/capture_families.json`, with the 88a freshness alarms and a
disk-floor WARN instead of a false capture alarm.** The code is generic: nothing names `lowest_temperature`. Expected
roll-free. **Lands with #172, not before 2026-10-14.**

## What was built

| File | Change |
| --- | --- |
| `src/weather/reporting/market/capture_family_status.py` | New, read-only. Each configured family's bounded `data/maker_evidence_families/<id>/status.json` (journals are never read) becomes one row: state, status age, conditions / `max_conditions`, missing events, free GiB against the family floor (`above`/`below`/`stopped`), mean req/min (`http.requests` / `elapsed_seconds`), task state, severity and reason. `-m` CLI prints JSON and never crashes (a failure becomes one FLAG). |
| `scripts/ops/status.ps1` | Passes every `WeatherMakerEvidence*` task state as `--task-state`, adds the FLAGs and WARNs, prints one `FAMILY` line per family, and adds `capture_families` to `-Json`. |
| `src/weather/reporting/market/cockpit_snapshot.py`, `app/views/cockpit.py` | `health.capture_families`. The Health column shows one metric per family, with an error on FLAG and a warning on WARN. |
| `scripts/ops/register_maker_evidence_family_capture.ps1` | Refuses a `-TaskName` other than `WeatherMakerEvidence<PascalId>` for its `-Family`, the name the monitor looks for. The literal default is unchanged, so the task-inventory ratchet still links it to its `scheduled_tasks.json` row. |
| `docs/operations/passive-maker-evidence-capture.md`, `README.md` | Monitoring rules; cockpit sources. |

### Alarm rules (owner: the module and `passive-maker-evidence-capture.md`)

- These apply only while the family's task is registered and not Disabled, the same condition as 88a. A missing or
  unreadable status, an age over 180 s, or any state other than `CAPTURING` is a **FLAG**, with the text
  `CAPTURE_FAMILY <id>: ...`.
- `STOPPED_FAMILY_DISK_FLOOR` is a **WARN** whose reason says it is "a planned brake protecting 88a, not a capture failure".
  The disk itself is already alarmed by the disk lines.
- A floor status older than 180 s is still a FLAG, because each one-minute retry rewrites it. A stale one means the retries
  have died.
- A family that is unregistered or Disabled is INFO only, before 10-14 included.
- The cockpit cannot see the Scheduler, so it holds any family that has written a status to the alarms.
- The flag text is tested against `health_watchdog.ps1`'s capture, capacity and observability patterns. A family FLAG is
  therefore classed `scheduled_job` (MEDIUM). It is never escalated as graded capture.

## Tests

Fixture status files, in `tests/reporting/test_capture_family_status.py`:

- fresh
- stale
- DEGRADED / NO_ELIGIBLE_BANDS
- disk-floor stop
- stale disk-floor stop
- missing, malformed, non-object and timestamp-less status
- oversized status
- unregistered / disabled
- two families
- cockpit mode
- CLI
- watchdog-pattern safety
- the registrar/registry name convention

`tests/operations/test_monitoring_fixes.py` runs the exact `status.ps1` block in PowerShell with the Scheduler and Python
stubbed: argument forwarding, FLAG/WARN placement and the failure path. The cockpit snapshot and view tests are extended.
The full-suite result and CI conclusion are in the handback reply and on PR #182.

## Per-file roll verdict

No changed Python file is in any capture closure. `capture_family_status` is imported only by `cockpit_snapshot`, which only
`app/views/cockpit.py` imports; `status.ps1` runs it as `-m`. `.ps1`, docs and tests are roll-free. Expected verdict: roll-free.
**Production re-derives it with `scripts\ops\roll_verdict.ps1 -Branch codex/capture-families-status-20261003`.**
#172 itself stays roll-sensitive (it changes `maker_evidence_capture.py`).

## What was NOT done

No registration, no Scheduler change, no production read or write, no restart, no merge, no venue call.

## Reproduction (production host, in the admitted window)

```powershell
.\venv\Scripts\python.exe -m pytest -q --basetemp <short temp> tests\reporting\test_capture_family_status.py tests\reporting\test_cockpit_snapshot.py tests\app\test_cockpit_view.py tests\operations\test_monitoring_fixes.py
.\venv\Scripts\python.exe -m weather.reporting.market.capture_family_status --task-state WeatherMakerEvidenceLowestTemperature=Ready
.\scripts\ops\status.ps1 -Json
```

## Commit

Branch `codex/capture-families-status-20261003`. The head SHA is in the handback reply.
