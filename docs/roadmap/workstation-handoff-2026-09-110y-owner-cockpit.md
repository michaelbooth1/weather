# Workstation handoff 2026-09-110y — owner cockpit page

Written 2026-09-27 by the production agent; owner approved (2026-09-27) after a Fable tools review. Base `origin/master` after
the 2026-09-27/28 landing, merged with `origin/codex/W-tracker-step1-20260927` (PR #110). Branch `codex/owner-cockpit-20260928`.

## Build

- `src/weather/reporting/cockpit_snapshot.py` (stdlib + `weather.paths`): reads `data/alerts/host_health_latest.json`,
  `data/alerts/disk_free_trail.jsonl` (tail only), `data/maker_evidence/status.json`, `docs/roadmap/work/W-*.yaml` via
  `worktrack`, and the wallet reader `/summary` and `/rewards` through `wallet_reader_client`. Every source optional with an
  explicit `unavailable` reason. Disk slope over the last 24 h and days to 50 and 40 GiB; exam dates (calibration
  2026-09-27..29, panel 2026-09-30..10-13, settlement 10-14, look 10-15; second candidate panel 10-16..10-29, look 10-31) as
  constants citing Clarification 1; closed 88a UTC dates counted.
- `app/views/cockpit.py`: Money / Work / Health / Exam columns; no mutation controls; fail-closed on any exception; the new
  default page. Mark the Control Room page "historical pilot view".
- **Embargo:** no policy P&L or policy comparison for panel dates.
- Tests on fixtures: missing sources, INCOMPLETE P&L, negative disk slope, waiting-on-owner older than 3 days.

Repo-wide audits in focused runs; no `.env`, no network in tests, no `data/`. Update the README dashboard section and
`app/AGENTS.md`. Push, draft PR, report `docs/roadmap/agent-report-2026-09-110y-owner-cockpit.md`, verdict first, roll
classification per file.
