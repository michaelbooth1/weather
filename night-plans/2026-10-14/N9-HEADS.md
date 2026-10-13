# N9 landing night 2026-10-13 -> 2026-10-14 (workstation summary)

**Prerequisite:** master `4bc93ae5d`, which has N8 and the pyup parse fix (code tree = `67cedeb67`). All three heads are built directly on it.
The machine-readable plan is `landing-night-plan-2026-10-14-n9.json`. Its `plan_sha256` is `89ef5311…f1d6`; the file's own sha256 is in the report.

| Order | Head | Sha | Class (static) | Members | Pre-gate (base 4bc93ae5d) | Journal pinned touch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `claude/integration-20261014-n9-rs-r2` | dae4c96da | ROLL-SENSITIVE, 01:00-04:00 quiet window | DST-M2 (`claude/dst-m2-cache-age-utc-20261011` 79ca1fa2a), owner-approved 10-12 | PASS, 9682 passed / 62 skipped / 0 failed | none |
| 2 (last) | `claude/integration-20261014-n9-rf-r2` | 48becd401 | ROLL-FREE, guarded, 00:30-09:00 | rs + I-6 oracle-author test wrapper (`claude/oracle-author-test-lease-20261012` ff67ae21b) | PASS, 9707 passed / 62 skipped / 0 failed | none |
| fallback | `claude/integration-20261014-n9-rf-alone-r2` | f870a759d | ROLL-FREE | master + I-6 wrapper only | PASS, 9693 passed / 64 skipped / 0 failed | none |

Targeted queue runs:
- rs: 656 passed, 5 xfailed.
- rf: 128 passed, 15 skipped.
- rf-alone: 112 passed, 15 skipped.

Landing preflight (`--tests none`, bound to the plan): rs routes ROLL_SENSITIVE and rf routes ROLL_FREE_GUARDED. The only FAIL on either head is the correspondence-index check, which also fails on master `4bc93ae5d` by design (closeout regenerates it).

Superseded: the a1014edab builds `-n9-rs` f8e7b412b, `-n9-rf` fdaaf964d and `-n9-rf-alone` 1d672682b. All three passed their pre-gates; they differ from the r2 heads only by master's three parse-fix files.

## Landing constraints
- **rs.**
  - Lands in the quiet window via `quiet_window_merge.ps1`, and before 10-31.
  - `model_sources.py` is covered by the tree-wide runtime `source_fingerprint`. As for any `src/` merge, a release verified with `check_runtime=True` must be re-bound under the existing release process. No manifest pins the file, and the model pkl and `feature_names_sha256` are unchanged.
  - Train/serve parity is preserved. Training uses the historical defaults and replay reads the stored age. `source_*_age_minutes` changes only for spans that cross a DST transition.
  - The merge splits that event day's residual-corpus runtime identity, as any roll-sensitive merge does.
- **rf.**
  - Lands after RS recovery, last in the night. It is stacked, so landing it also lands rs.
  - If rs fails or is dropped, land **rf-alone** instead.
  - Activation: nothing to start. The first use is the oracle r1 setup's V2 proof run on 10-15, which requires `scripts\ops\oracle_author_test_run.ps1` in `$P`.
- The docs transaction requires 4 documents as of the final tip (preflight).

## Light path, not in this plan
`claude/oracle-cut-fixture-keep-20261012` 3ca741e2b: the oracle cut tool, its tests and the isolation runbook DRAFT. Master decides its path.
