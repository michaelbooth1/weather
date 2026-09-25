# Fail-forward recovery table

- **Owns:** the owner-approved list of guard states an agent may clear alone, the exact conditions for each, and the
  receipt each must write.
- **Read when:** a guard, marker or lock blocks production work and you are deciding whether to clear it or stop.
- **Do not use for:** anything not listed here (stop, notify the owner, continue other lanes — Operations agent role §6),
  live-trading controls (never), or evidence deletion (the verified archive path).
- **Verify with:** each row's named checks; a row whose checks cannot all be run is not satisfied.

Owner decision 2026-09-24: an understood, harmless blocker is cleared under these rows instead of stopping a night's work.
Each clearance writes a receipt embedding the exact bytes of what was cleared and the evidence checked, and is recorded in
`STATE_OF_PLAY.md`. If the local permission layer refuses the action, stop and notify the owner; never route around it.

| State | The agent may clear it when all hold | Receipt |
| --- | --- | --- |
| `data/alerts/quiet_window_merge_in_progress.json` in phase `prepared` or `preparing` (no merge commit recorded) | HEAD = the marker's `baseline_commit` = `origin/master`; no `.git/MERGE_HEAD`; tracked changes limited to `config/locations.json` and `config/location_market_events.json`; capture healthy per `status.ps1` | `data/alerts/quiet_window_merge_reconciliations/agent-retire-<ts>.json` with the marker bytes and SHA-256 and the git state, plus a `quiet_window_merge_history.jsonl` line; delete only if the marker hash is unchanged |

First use: 2026-09-24 09:14 (owner-approved one-time retirement of the 00:45 dry-run marker; receipt
`owner-approved-retire-20260924T091412.json`). Add a row only with an owner decision recorded in `STATE_OF_PLAY.md`.
