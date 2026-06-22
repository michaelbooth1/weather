# 216. Runtime-Identity Segmented Model Evidence [OPEN 2026-06-22 - MIXED COMMITS MUST NOT BLUR MODEL REVIEW]

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

- [ ] Add runtime-identity grouping to model review and promotion summaries.
- [ ] Add mixed-runtime warnings to daily progress and fleet observability.
- [ ] Prevent broad improvement/promotion claims from using unsegmented mixed
  runtime samples.
- [ ] Add taker/MM evidence grouping by runtime identity.
- [ ] Add a regression fixture from the June 21 mixed-commit day.

Acceptance: reports that include rows from multiple runtime identities show
separate metrics per identity and block unsegmented promotion or improvement
claims until a reconciliation report explicitly allows the aggregation.

Related: items 60, 117, 140, 163, 177, 209.
