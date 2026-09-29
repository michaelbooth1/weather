# Workstation handoff 2026-09-111e — make the signed replay exam executable

Written 2026-09-29 by the production agent after the 2026-09-29 deep audit
([findings](audits/deep-audit-2026-09-29.md)). The owner approved drafting
[Clarification 2](../research/maker-replay-clarification-2-2026-09-29.md) (unsigned draft) and fixing the exam
tooling. Base: `origin/master` after the 2026-09-30 landing of integration PR #134 (if #134 has not landed, base on
`origin/codex/integration-20260929`). Branch `codex/exam-executability-20260930`. Never modify the signed files
`docs/research/maker-replay-{hurdles-preregistration,execution-addendum,clarification-1}-2026-09-27.md`.

## Goal

The 10-15 look can run end to end on production-sized data without consuming the look on an operational refusal, under
the rules Clarification 2 states. Implement to the draft; if a rule there is unimplementable or ambiguous, stop and
report instead of choosing.

## Defects to fix (all verified on the integration branch)

1. `maker_replay_night.py:159` writes per-condition `active_intervals`; `bundle.py:249` refuses unknown fields. Per the
   draft, bundles carry no intervals; the manifest supplies them. Remove the field from export (wrapper
   `-ExcludeUtc` becomes manifest-only) and keep the reader exact.
2. No calibration-bundle producer: add a bounded exporter for descriptor/coverage/trade records, all cities, one
   directory per UTC date, same hashing; and make panel export produce one all-city directory per date that
   `pack_io.load_days` accepts.
3. Nightly export reliability: memoise `ReleaseSources.for_event` projections per slug (the per-minute rebuild);
   accept growth of append-only inputs with an unchanged prefix hash instead of refusing; skip and flag an
   unterminated trailing line instead of parsing it; pin the nightly runner by wrapper and module hashes instead of
   `HEAD == ExpectedSourceTip`.
4. Ceilings: make the manifest bind ceilings derived by the draft's rule, and add the diagnostic-only measurement
   command (bytes, records, events, decisions, spans, peak memory, runtime; no scores) for one calibration date.
5. Look protection: move `reserve_attempt` so an operational refusal before any score is computed does not consume
   the look, recording the stop stage; add the score-free rehearsal mode restricted to calibration dates.
6. Authorization verifier: accept a second clarification hash (`maker-replay-2026-10-15-v2`), with tests that v1 rows
   still verify and that a v2 row missing the Clarification 2 hash refuses.
7. Quote-market set by the draft's rule, from 88a's sealed per-date inventories; no hand list.

## What would falsify this mission

If the measured calibration-day volume times the rule exceeds what a 16 GB host can hold, say so: the exam is then not
executable here as designed, and that is the finding. Do not weaken a rule to make it fit.

## Deliverables

Fixture tests per defect built with the production writers; the repo-wide audits; full GitHub CI green. Report
`docs/roadmap/agent-report-2026-09-111e-exam-executability.md` with the exact production commands for: the calibration
export of 09-27..09-29, the diagnostic ceiling measurement, calibration, and the 10-15 build/verify/enrol/look runbook.
