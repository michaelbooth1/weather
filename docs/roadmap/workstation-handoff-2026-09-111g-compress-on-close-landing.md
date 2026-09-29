# Workstation handoff 2026-09-111g — bring 110j C (compress on close) to a green PR

Written 2026-09-29 by the production agent; owner approved 2026-09-29 as disk relief (allowed during the exam period).
Production disk falls about 11 GB/day net (2026-09-26→27: 80.8→70.0 GiB free), reaching the 50 GiB suite floor
around 10-03. 110j C was built and fixture-qualified on 2026-09-26
(`origin/codex/compress-on-close-20260926`, report `docs/roadmap/agent-report-2026-09-110j-c.md` on that branch) but no
PR was ever opened and the branch is behind master.

## Work

Merge `origin/master` into `codex/compress-on-close-20260926` (no rebase), fix what the merge or CI breaks, open a draft
PR, and get full GitHub CI green. Re-check the report's production steps against current master (paths, task names,
registrar). Estimate the daily reclaim from the report's own measurements; state clearly which numbers are measured
and which are projected.

## Deliverables

Report `docs/roadmap/agent-report-2026-09-111g-compress-on-close-landing.md`: PR, head SHA, CI conclusion, the
per-file roll verdict inputs, the exact production enable/registration steps, and the expected GiB/day.
