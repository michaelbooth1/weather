# 141. Variant Learning Operational Gates [COMPLETE 2026-06-18 - VARIANT LEARNING BLOCKING GATE LIVE]

Goal: prevent daily and nightly operational status from reporting success when
variant learning evidence is blocked or stale.

Source: 2026-06-18 model-variant data audit. `daily_refresh` can finish with
top-level status `ok` even when `model_variant_evidence_growth` is `ALERT`,
`shadow_ab_monitor` is `ALERT`, `snapshot_evaluation` is `FAIL`, and
`daily_learning` is `BLOCKED`, because escalation is controlled by optional
flags or by thrown exceptions.

Why this matters: the status artifact is the operator's first signal. If it
says `ok` while the learning loop is blocked, stale variant evidence can
survive for days and automated retrain/promotion reviews can treat the run as
healthy.

## Design

1. Add an explicit daily-refresh gate for variant evidence freshness and
   independent evidence growth.
2. Treat `model_variant_evidence_growth == ALERT` as `critical` by default
   when active variant shadow evidence is stale, missing, or rows grow without
   independent observations.
3. Preserve opt-out flags for research runs, but make production scheduled
   tasks fail closed.
4. Include the first variant-learning blocker in `daily_refresh_status.json`,
   `daily_refresh_report.md`, `nightly_retrain_status.json`, and daily
   learning.
5. Add tests proving `ok` is impossible when the configured variant-learning
   SLA is blocked.

- [x] Add `--fail-on-variant-evidence-alert` or equivalent default-on
  production behavior.
- [x] Promote stale/missing active-variant shadow evidence to top-level
  `critical`.
- [x] Surface the first blocker and remediation command in daily and nightly
  reports.
- [x] Update Task Scheduler/runbook commands to use production fail-closed
  defaults.
- [x] Add regression tests for top-level status, report rendering, and daily
  learning propagation.

Acceptance: a scheduled refresh cannot report `ok` when active variant
evidence is stale, missing, or blocked by the independent-evidence SLA; the
status and report name the remediation command.

## Implementation update - 2026-06-18

Implemented `variant_learning_gate` in `weather.operations.daily_refresh` with
schema registry coverage, report rendering, and default-on critical escalation
for blocked active-variant shadow coverage, missing current variant evidence,
or independent-evidence SLA alerts. Production scheduled refresh commands now
pass `--fail-on-variant-evidence-alert`; `--allow-variant-evidence-alert`
remains as the research opt-out.

Daily learning now promotes a blocked variant-learning gate into a P0 blocker
with the remediation command, and nightly retrain status carries the
`variant_learning_gate` from the daily learning summary. Regression coverage
proves the daily run cannot remain `ok` under blocked variant-learning evidence
unless the explicit research opt-out is used.

Verification: `python -m pytest -q tests\operations\test_daily_refresh.py tests\reporting\test_daily_learning.py tests\operations\test_nightly_retrain.py tests\operations\test_schema_registry.py`
passed with 43 tests.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - VARIANT LEARNING BLOCKING GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

