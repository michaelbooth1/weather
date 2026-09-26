# Handoff 2026-09-110g — switch off the afternoon residual centering stage (owner-approved)

Written 2026-09-25 by the production agent. Owner decision 2026-09-25 (DECISION_LOG): switch the stage off pending
measurement; never refit it on its own output. Evidence: wide audit FV-1/FV-3, model-lanes audit 2026-09-25.

## Facts (verified by the production agent)

- The stage is enabled: `artifacts/misc/afternoon_residual_centering.json` `component.enabled = true`, hours 15-18.
- The runtime honours `enabled: false` → `reason: artifact_disabled`, distribution unchanged
  (`src/weather/model/calibration_runtime.py:227-230`).
- Serving has no bound release on this host (`artifacts/releases/` absent), so `toronto_model.load_afternoon_residual_centering`
  reads the global artifact (`src/weather/model/toronto_model.py:254-259`), **once at model construction** (`:147`).
- The artifact is pinned by SHA-256 and bytes in `artifacts/manifests/model_artifact_registry.json`
  (`registry_use: unreferenced`), and `release_candidate_contract.py:380-388` copies it into release candidates.

## Build (branch `codex/disable-afternoon-centering-20260926` from `origin/master`)

1. Set `component.enabled` to `false` in the artifact (no other field changes; keep the fitted contexts for later measurement).
2. Regenerate the registry entry with the repository's own registry tool (find its CLI; never hand-edit the hash), and any
   other manifest that pins the file.
3. Tests: a served-distribution test proving `artifact_disabled` leaves the distribution unchanged at 15:00-18:59; update any
   test that asserts the shipped artifact is enabled; release-candidate contract tests still pass.
4. Document the change in `docs/operations/ESTABLISHED_FINDINGS.md` §2 (the stage is now off; it was fitted in-sample on
   June data on a pipeline not served since 06-30) and in the model serving doc that owns calibration stages.
5. **Activation plan** in the report: which supervisors/processes construct the model and therefore must restart for the
   change to take effect, whether `roll_verdict.ps1` sees an artifact-only change (if not, the production agent restarts them
   deliberately in the quiet window and verifies snapshots carry `artifact_disabled`), and how to re-enable.

## Deliverables

Report `docs/roadmap/agent-report-2026-09-110g-disable-afternoon-centering.md` (verdict first, files, tests, activation
plan, the tip). The production agent lands it in the 01:00-04:00 window of **2026-09-26/27** with a verified restart. No
production data, no `.env`, no live trading.
