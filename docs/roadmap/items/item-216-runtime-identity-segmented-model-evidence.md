# 216. Runtime-Identity Segmented Model Evidence [COMPLETE 2026-06-22 - SEGMENTED CLAIM GATES LIVE]

Goal: segment model performance, live-forward evidence, and promotion review by
runtime identity so snapshots produced by different code commits or artifact
hashes cannot be aggregated as one homogeneous model run.

Source: the 2026-06-21 log review found mixed runtime identities in same-day
snapshots: commit `5b6f5af2d396` produced `1337` snapshot rows and commit
`2e3672d99680` produced `1109` snapshot rows. The active loop status reported
current code, but same-target-day model review could blur pre- and post-restart
behavior.

Why this matters: live-forward evidence is only meaningful if the code and
artifact identity behind each row is known. Mixing commits can hide regressions,
inflate sample counts, or let a restarted model inherit evidence from a
different runtime state.

## Design

1. Treat runtime identity hash, git commit, dirty fingerprint, and artifact hash
   as grouping dimensions for model review, taker strategy evidence, and MM
   evidence.
2. Add warnings when a target date has mixed runtime identities and any report
   attempts to make a broad model-improvement or promotion claim.
3. Require promotion gates to pass either within one runtime identity or through
   an explicit cross-runtime reconciliation report.
4. Surface runtime transitions in snapshot, taker, MM, daily-progress, and
   fleet reports.

- [x] Add runtime-identity grouping to model review and promotion summaries.
- [x] Add mixed-runtime warnings to daily progress and fleet observability.
- [x] Prevent broad improvement/promotion claims from using unsegmented mixed
  runtime samples.
- [x] Add taker/MM evidence grouping by runtime identity.
- [x] Add a regression fixture from the June 21 mixed-commit day.

## Completion Notes

Implemented `weather.reporting.serving_gates.runtime_identity_evidence` as the shared
runtime segmentation gate. It groups snapshot rows by git commit, dirty/source
fingerprint, runtime code state, markets, target dates, and trading run
identity. The June 21 mixed-commit fixture now blocks unsegmented broad and
promotion claims unless `runtime_identity_reconciliation.json` explicitly
allows the aggregation.

Daily progress, fleet observability, progress audit, and promotion refresh now
surface runtime identity status, segment rows, reconciliation status, and the
`mixed_runtime_identity_unsegmented` blocker. Progress audit adds the blocker
to the core model trend threshold failures; promotion refresh adds it to
promotion readiness blockers. Taker run summaries now stamp runtime identity,
and MM run summaries are grouped through their existing runtime payloads.

Verification:

- `python -m pytest tests\reporting\test_runtime_identity_evidence.py tests\reporting\test_progress_audit.py -q`
- `python -m pytest tests\reporting\test_daily_progress_ledger.py tests\reporting\test_fleet_observability.py -q`
- `python -m pytest tests\market\test_taker_bot.py tests\market\test_market_making_run.py tests\reporting\test_trading_evidence.py -q`
- `python -m pytest tests\reporting\test_daily_learning.py tests\operations\test_nightly_retrain.py -q`

Acceptance: reports that include rows from multiple runtime identities show
separate metrics per identity and block unsegmented promotion or improvement
claims until a reconciliation report explicitly allows the aggregation.

Related: items 60, 117, 140, 163, 177, 209.
