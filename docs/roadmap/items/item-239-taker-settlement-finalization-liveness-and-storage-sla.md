# 239. Taker Settlement Finalization Liveness And Storage SLA [COMPLETE 2026-06-22]

Goal: make taker settlement finalization, bot liveness, and artifact storage
reliable enough that strategy evaluation cannot be blocked by missing settled
PnL, disk exhaustion, or idle-but-alive processes.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
June 21 labels exist but the taker run was not finalized to `settled_pnl`. The
console log reports `No space left on device`, large backtest artifacts are
accumulating, and the bot process can be alive while effectively idle.

Why this matters: the strategy loop depends on timely settlement evidence. If
labels are available but finalization is missing, quality gates stay blind. If
storage or liveness checks are weak, daily evidence can silently stop.

## Design

1. Add a scheduled finalization scanner that finds labelable taker runs and
   writes `settled_pnl` artifacts within an explicit SLA.
2. Treat process liveness as recent useful output, heartbeat, CPU/write
   activity, and tape freshness rather than PID existence alone.
3. Add disk-space preflight checks before daily roll, bakeoff, and large
   artifact writes.
4. Add retention or tiering rules for large backtest and taker artifacts.
5. Alert when a run has labels available but no settlement finalization.

- [x] Add a finalization watchdog that scans all taker runs with available
  labels and creates missing `settled_pnl` outputs.
- [x] Add bot liveness checks based on recent tape writes and heartbeat age.
- [x] Add disk-space preflight and retention rules for large taker/backtest
  artifacts.
- [x] Add reports and tests for label-available/no-finalization and
  idle-process states.

Acceptance: labelable taker runs produce `settled_pnl` within the configured
SLA, disk-full risk is caught before writes, and an idle bot process is not
reported healthy merely because the PID exists.

Related: items 161, 198, 199, 202, 214, 238.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

