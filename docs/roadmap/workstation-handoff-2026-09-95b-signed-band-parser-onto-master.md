# Workstation handoff 2026-09-95b — signed band parser onto master

Written 2026-09-24 by the production agent. Serves Q-09 (settlement hardening). Host audit finding 7: the signed band parser
`016e1c92c` (2026-09-05) is not on master; it lives on `codex/audit-fixes-20260905` and `codex/48h-maker-*` only. Toronto's
first sub-zero highs arrive in about eight weeks, and a band parser that cannot read negative ranges would mis-settle them.
The forward plan cites a non-existent "item 335" for it.

## 1. Build

Branch `codex/signed-band-parser-20260924` from `origin/master`: bring the parser change onto master as a minimal, reviewed
change (cherry-pick or re-implement; never merge the stale branches wholesale). Keep native settlement units, WU cutoffs and
probability mass. Tests: negative and zero-crossing ranges (e.g. "-3 to -2 °C", "-1 to 0 °C", open-ended "-5 °C or below"),
the existing positive cases unchanged, and replay of recorded Toronto labels byte-identical. Say which files the capture loops
import (the production agent takes `roll_verdict.ps1` and lands it).

## 2. Deliverables and boundaries

Create the numbered roadmap item it belongs to (next free number under `docs/roadmap/items/`) and fix the forward plan's
"item 335" citation to it. Report: `docs/roadmap/agent-report-2026-09-95b-signed-band-parser-onto-master.md` (verdict first,
the diff scope, test counts, which modules are loop-imported, the tip). No `.env`, no production writes. Push is authorized.
