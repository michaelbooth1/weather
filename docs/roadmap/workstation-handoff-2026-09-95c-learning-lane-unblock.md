# Workstation handoff 2026-09-95c — unblock the learning lane

Written 2026-09-24 by the production agent. Serves **Q-11**. Host audit finding 2: the settled-day analysis barrier
(`data/backtest/settled_day_analysis_barrier.json` on production) is blocked by two maker gates
(`exchange_economics_rule_drift`, `maker_paper_score`), and the learning steps behind it — `data_retention_inventory`,
`daily_learning`, `market_beating_objective_scoreboard` — have not run since 2026-08-13. The paper maker roll is now paused
(owner 2026-09-24, retiring the old maker), so `maker_paper_score` can never clear.

## 1. Build (branch `codex/learning-lane-unblock-20260924` from `origin/master`)

In `src/weather/operations/daily_refresh_registry.py` (and whatever consumes it), make the learning, scoreboard and retention
steps depend on **settlement truth only**, not on maker/economics gates; keep those gates for maker-specific steps; treat a
paused paper maker as "not applicable" rather than BLOCK. Preserve every settlement-correctness dependency and the chain's
fail-closed behaviour for real settlement faults. Tests: barrier with blocked maker gates still runs the learning steps; a
real settlement fault still stops them; the paused-maker case. State whether the registry is imported by any capture loop
(the host audit found it in no live closure; the production agent takes the roll verdict).

## 2. Deliverables and boundaries

Report: `docs/roadmap/agent-report-2026-09-95c-learning-lane-unblock.md` (verdict first, before/after dependency graph, tests,
roll expectation, the tip). No `.env`, no production writes, no scheduled-task changes. Push is authorized.
