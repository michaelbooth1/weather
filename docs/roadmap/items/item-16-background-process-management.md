# 16. Background Process Management [COMPLETE]

- [x] Replace ad hoc background loops with a small managed runner.
- [x] Track process PID, start time, last heartbeat, last snapshot, and errors.
- [x] Add a heartbeat-based status command.
- [x] Add pause/resume via dashboard flag.
- [x] Add a command to stop/restart the snapshot loop cleanly.
- [x] Document the recommended OS supervisor setup for always-on capture.

Codex update (2026-05-31): `src.snapshot_tracker` now has `--loop`,
`--status`, `loop_status.json`, `diagnostics.jsonl`, pause flag support, and
health tests. The missing piece is process lifecycle control: stop/restart
without relying on manual process management.

Implementation status (2026-06-10): complete. Motivated by the 2026-06-10
02:24 incident: the loop died silently and the fleet lost ~7 hours of tapes.
`snapshot_tracker` gained `--stop` (PID-verified terminate), `--start-detached`
(detached spawn with console log + provisional status so a racing ensure
cannot double-start), `--restart` (the deploy-new-code one-liner), and
`--ensure` (the supervisor verb: noop on fresh heartbeat or pause, start after
death/reboot, kill-and-restart a hung process with a live PID and stale
heartbeat; ERRORING loops are left visible rather than masked by restarts).
`scripts/register_snapshot_supervisor.ps1` registers the Windows Task
Scheduler task that runs `--ensure` every 10 minutes and at logon (current
user, no stored credentials). Supervisor actions are appended to
`diagnostics.jsonl`. Verified live: task registered and returned result 0,
`--restart` swapped the running loop, ensure no-ops on the healthy loop, and
the first post-restart capture wrote v0.5.6 snapshots. Decision logic is
unit-tested in `tests/test_loop_supervisor.py` (7 tests).

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

