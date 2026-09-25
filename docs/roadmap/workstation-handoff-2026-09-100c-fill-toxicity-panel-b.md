# Workstation handoff 2026-09-100c — 89a panel B selector (Clarification 12)

Written 2026-09-25 by the production agent. The owner approved Clarification 12 (DECISION_LOG 2026-09-25): a second,
separately frozen 89a panel, **panel B = 2026-09-25 to 2026-10-08 inclusive**, scored once after 10-08 settles. The text is
committed on `codex/fill-toxicity-desk-study-20260923` @ `0df126491` in
`docs/research/fill-toxicity-desk-study-preregistration-2026-09-23.md` ("Clarification 12"); read it first.

## 1. Build (same branch, on top of `0df126491`)

- In `src/weather/market/fill_toxicity_desk_study.py`: replace the single `START_DATE`/`FREEZE_DATE` pair with frozen panel
  constants `PANELS = {"A": (2026-08-15, 2026-09-23), "B": (2026-09-25, 2026-10-08)}` and a `--panel {A,B}` flag whose
  **default stays A** (so a bare command still reproduces the recorded panel-A run). `--max-dates` bounds apply per panel.
- Refuse to score panel B before every panel-B date is closed (the study's existing "closed date" notion); `--dry-run` may
  plan it at any time.
- Record the panel id in the report JSON/Markdown (`panel`, `panel_start`, `panel_end`) and in intermediates; nothing pools
  panels.
- Set `FROZEN_REF` to `0df1264910a36b75d01474f63f86b71920e22541` (the Clarification 12 commit).
- 88a inputs (100b adapter) are used for both panels unchanged; panel A will still find none.

## 2. Tests

Panel A default unchanged (existing tests pass untouched); panel B plans exactly the 14 dates; panel B scoring refuses
while any date is open; report carries the panel fields; `FROZEN_REF` equals the Clarification 12 commit; no panel mixes
dates from the other.

## 3. Boundaries and deliverables

No production run and no production data (the production agent runs panel B under the lease after 10-08 settles, earliest
~2026-10-09 night). No `.env`. Report: `docs/roadmap/agent-report-2026-09-100c-fill-toxicity-panel-b.md` (verdict first,
tests, the tip). Push is authorized.
