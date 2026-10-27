# rule_rs (L2) withdrawn before any fit: family closed by L15 R-S 70908316

Recorded 2026-10-26 on the coordinator's instruction. It withdraws L2's `rule_rs.md` (sha256 `5fb593f4…`) and its
addendum 1 (`1b930b8e…`). The rule files and code stay in place as a record.

## What ran

Nothing was fitted, emitted or scored under this rule. No R-S row was joined to an outcome, label, price or market row.

The queued chain (task btp9uk7r0: pytest, then LOYO 13-16, then LOYO 07-12) was cancelled while it was still waiting
in the `workstation_heavy.ps1` queue:
- pytest never started, and the basetemp `C:\t\l2\pt3` was never created;
- `C:\t\l2\rungs\loyo\` is empty;
- no `rs_*` log or output exists.

## Why

L15's R-S (rule sha256 `70908316df5066fe5d000fa8d84d0ec2b1f384285a1d3f68b311b9d24cf93ff9`, branch
`claude/spread-info-20261026` @ `efd95d8b9`) was killed at gate 2. Its pre-registered kill reads:

> the NBM-published-spread predictor family is closed for P3d_N_fix, L6 and every NBM-anchored arm: NBP TXNSD, NBP
> percentile width (p90 − p10), and NBS XND/TSD at fresher cycles, under any transform, anomaly window, grid, hour
> grouping or rung name.

This rule's predictors are inside that scope:
- `nbm_sd` is the NBP TXNSD.
- `nbm_qw` is the NBP p90 − p10.
- Its arms are P3d_N_fix and P3d_H, which is P3d_N_fix plus HRRR columns and therefore NBM-anchored.
- A scale-HGB input is a transform under another rung name.

The kill's carve-out names only "GEFS member spread, multi-model dispersion, observed-state predictors". It does not
leave this variant open.

The name R-S is also L15's; this file does not reuse it for any future rung.

## What stands

The inputs-only NBS cycle-label check, `../rungl2/nbs_label_check.md` (sha256 `41e5d1af…`), is not affected.
