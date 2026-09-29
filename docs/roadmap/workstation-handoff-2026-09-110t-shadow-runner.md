# Workstation handoff 2026-09-110t — Phase 3 shadow runner (public reads only)

Written 2026-09-27 by the production agent (owner-approved). Implement `docs/operations/maker-shadow-runner-design.md`
(PR #108) so the design's "≥ 7 days of live-forward shadow agreeing with replay" clock can start during the replay panel.
Branch `codex/shadow-runner-20260927`, base `origin/codex/maker-replay-harness-20260926` merged with PR #108's branch.

## Build

- `src/maker_core/shadow/` plus a thin weather composition layer: public-read-only adapter with an endpoint allow-list and
  no mutation methods; frozen session manifest; per-minute hash-chained quotes tape; freshness timers; drills (kill, stale
  feed, terms change, gap). Extend the import ratchet so venue-mutation, credential and RE-1 adapters are unreachable from
  the runner's import closure.
- **Economics embargo:** no P&L or policy-comparison output for panel dates (2026-09-30..10-13) until the scored look on
  2026-10-15; nightly evaluation emits decision-level agreement with replay only.
- Runs on the workstation only; no production process, no orders, no credentials.

## Deliverables

Fixtures only with a recording transport in tests. Repo-wide audits and maker-core boundary tests. Push, draft PR, report
`docs/roadmap/agent-report-2026-09-110t-shadow-runner.md`, verdict first, exact workstation start command. The owner starts
the first shadow session.
