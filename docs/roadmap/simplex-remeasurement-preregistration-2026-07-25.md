# Simplex repair remeasurement preregistration — 2026-07-25

Status: frozen before observing any authorized paired-PIT, repaired
model-versus-market, or repaired ablation result.

This preregistration executes
`workstation-handoff-2026-07-25-simplex-authorization.md`, file SHA-256
`93dd938c80fea03e15b3e480b8de9304dadfa1d55accc18a45d06f5b50dcf1f5`.
The pulled master is
`8f816f56f58b01be49290addbcbc94b64bbc542c`, which contains the handoff and
the stated host-operations commit `5093af0b`.

## Fixed identities and boundaries

- Baseline code:
  `0975622723129f47e179a4a188017773fbfa95fd`.
- Repaired code and documentation:
  `803b3de68e7de35bc9213aff5d94d6479b002ba6`; the executable repair code
  ends at `55fcc7b9`.
- Declared output root:
  `C:\Users\Michael\Documents\Codex\w24b`.
- Authorization mission root:
  `C:\Users\Michael\Documents\Codex\w24b\authorization-20260725`.
- Pre-execution mirror-ACL receipt SHA-256:
  `330ed6d1e2def87c6e7d7302bd0f2be1c1291d68013f25c9689e2d6294361f45`.
  The fresh canary was denied and absent afterward.
- The authorized `promotion_refresh` may write only candidate-local routing
  evidence below its paired run root. It does not authorize a candidate,
  release, pointer, registry change, serving adoption, or any other
  promotion surface.

The production-host measurement supplied by the handoff is accepted input and
will not be rederived. The live implementation contains the same ordering
defect, but recorded production partitions are currently unit-mass because the
blend is not active there. The live defect is therefore **latent**, not
currently active. The replay defect is active when a pooled artifact enables
the contextual blend.

## Paired PIT expectation

The baseline and repair will use the identical V6b staged source, receipt,
locked dates, routing-generation contract, folds, bootstrap settings, and
support inventory.

The frozen V6b identities are:

- staging-receipt semantic SHA-256
  `f2b05a343005084bab6cd3528a032422d545945d38c5ccc9586011bc8e59a952`;
- staging-receipt file SHA-256
  `b34533452e1d63699cbe1fee93a4fdb56a2b84ae92e908fbc9f938095f598f09`;
- preselection hash
  `e398abf58b43d2889a0faf4fdd43ad7633bc6d228bc00c5556e4a7c49610422c`;
- window-lock ID
  `9d3be4615516039bb61697f28c44dfcfdac201d58276d9260632abc63b7722d9`;
  and
- locked dates `2026-07-09..2026-07-22`.

Preregistered expectation:

1. `09756227` reaches PIT and returns `BLOCK` with one or more
   `probability_simplex_failure` exclusions.
2. `803b3de6` returns PIT `PASS` with zero simplex exclusions.
3. If the baseline does not reproduce a simplex failure, the pair does not
   establish a `BLOCK`-to-`PASS` transition even if the repaired side passes.
4. Any repaired simplex exclusion is a second defect and will be attributed
   before any positive conclusion.

V6b is genuinely complete-grade but does not contain every source day behind
the prior 93 genuine-day failures. A separate repaired qualification over the
original frozen compatibility graph will therefore answer the literal residue
question. The original canonical corpus file SHA-256 is
`8a5d03748ca7d9d407282d65a2fac22f1b47de259fde7781bf3ff48faf94eafb`;
it contains 23,518 band rows and 2,138 cutoffs. Expected result: genuine
failures `93 -> 0` and synthetically upgraded failures `56 -> 0`. Any nonzero
residue is a second defect.

## Full-suite expectation

The prior authoritative report is
`docs/roadmap/agent-report-2026-07-24-workstation-lock-blocker-fixes.md`
at commit `06a38069`, file SHA-256
`15be104205139095ccd6efc4c3303f668877d72bd0c8bd5870831ef5dcdb2f06`.
Its converged machine-readable failure set is
`C:\Users\Michael\Documents\Codex\2026-07-24\pull-origin-master-and-execute-docs\work\weather-lock-blocker-fixes\.pytest_cache\v\cache\lastfailed`,
SHA-256
`cdf3844bda6d12cd2179393de8b0fd98ca51efc7485c7dddb00cabef30e346c0`.

Expected failures are the same five pre-existing nodes plus the same seven
Windows executor child-working-directory/path fixture nodes. A failure is new
if its node ID is outside that exact set or its traceback has a different
mechanism. Any calibration, replay, model, simplex, or probability-mass
failure is new. Passing a known-failure node is acceptable.

The exact expected nodes are:

- `tests/app/test_app_architecture.py::test_app_files_do_not_mutate_sys_path_or_import_legacy_wrappers`;
- `tests/model/test_source_cache_ttl.py::TestSourceCacheTtl::test_stale_forecast_served_within_long_ttl`;
- `tests/model/test_source_cache_ttl.py::TestSourceCacheTtl::test_stale_observation_dropped_past_short_ttl`;
- `tests/operations/test_module_size_audit.py::test_current_warning_modules_have_complete_ownership_metadata_and_no_orphans`;
- `tests/operations/test_module_size_audit.py::test_ownership_document_lists_every_current_warning`;
- `tests/operations/test_experiment_executor.py::test_executor_records_verified_terminal_disposition_and_declared_artifacts`;
- `tests/operations/test_experiment_executor.py::test_timeout_budget_kills_tree_and_records_unmeasured_inconclusive`;
- `tests/operations/test_experiment_executor.py::test_unexpected_output_tree_is_quarantined_without_recursive_cleanup`;
- `tests/operations/test_experiment_executor.py::test_sandbox_blocks_absolute_serving_mutation_and_original_hash_is_unchanged`;
- `tests/operations/test_experiment_executor.py::test_sandbox_denies_undeclared_external_read_but_allows_verified_run`;
- `tests/operations/test_experiment_executor.py::test_sandbox_denies_staged_input_mutation_and_parent_input_is_unchanged`;
  and
- `tests/operations/test_experiment_executor.py::test_queue_change_before_commit_records_superseded_and_discards_output`.

## Model-versus-market expectation

### Recorded-live headline control

The published control has 35,618 hourly rows over 141 market-days:
model Brier/log loss `0.07191 / 0.24078` versus market
`0.03734 / 0.11823`, a Brier gap of `+0.03458`. Its source document SHA-256
is `7c383fe064dc0c23f44b9805bada66ef557340195457df35d9bd9f5f8778e1df`.

This scorer reads recorded model probabilities and bypasses the repaired
pooled replay producer. Expected baseline/repair movement is exactly zero.
It is a frozen control, not proof that the repair was exercised.

### Repair-active pooled replay

The exact pooled artifact is
`artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl`, 6,310,781 bytes,
SHA-256
`3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c`.
It is identical at both code identities and enables contextual blending plus
partition normalization.

The source manifest is the read-only
`data/backtest/promotion_corpus.json`, file SHA-256
`4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5`
and corpus hash
`d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f`.
The candidate-owned fixed window is `2026-06-28..2026-07-10`:
141 market-days, 12 markets, 20,586 snapshots, 226,479 bands, and subset
corpus hash
`a59c59a4fcc4071bf707650b859bf3fc7754d79d3d3517f6997c4a8a3d6438a1`.

Expected repaired behavior:

- every nondegenerate snapshot partition sums to one;
- current, recorded-market, label, and matched-key populations are unchanged;
- candidate Brier improves slightly, expected absolute change below `0.001`;
  and
- the existing positive candidate-minus-market gap does not close or change
  sign.

The old moving-corpus pooled report is context only: candidate Brier
`0.05156638`, market Brier `0.03556944`, gap `+0.01599694`, file SHA-256
`57f1bfc720d4f84787cabfb6f4b295b551539eec3044197419f7b0f704ca9092`.
The paired run, not that old report, owns the new comparison.

Materiality is fixed before observation:

- absolute candidate-Brier movement below `0.001`: immaterial to the
  model-quality conclusion;
- movement from `0.001` through less than `0.003`, when it also closes less
  than 20% of the paired gap: diagnostic/indeterminate and insufficient to
  revise the headline conclusion;
- movement at least `0.003`, or closure of at least 20% of the paired
  candidate-market gap: material and subject to a second
  leakage/provenance audit before any favorable claim; and
- any gap sign crossing: conclusion-changing but presumptively suspect until
  that audit passes.

Results will be compared on identical keys overall and by market, target date,
and hour/regime. Row-count changes block interpretation.

## Per-source ablation expectation

`weather.backtesting.replay_ablation` directly instantiates the generic live
model and does not call the repaired pooled replay producer. Its implementation
is byte-identical at the baseline and repair identities. Therefore the paired
source-ablation result is expected to be exactly identical; movement above
`1e-12` is treated as cohort or execution drift rather than repair lift.

The pinned clean horizon has 51 market-days from `2026-06-03..2026-06-13`,
5,586 snapshots, 61,446 bands, 2,623 identity records, and subset corpus hash
`5d11e7abb00cb944df8b6b8fd0dde127e39b7bc3d8d5fb3965893a712b7d4336`.
Its sorted `(market_id, target_date)` key-set SHA-256 is
`52d76b22c62c8c7ece138691cdacd1e9974c8145a5b51224b82bb33263642f19`.
The retained mixed-horizon source report is context only, file SHA-256
`2f08e0e7de6df6a552c0488d716a6d2a0807f4a387079f131fcbfeb5aa49a315`.
Its clean 51-day `all_forecasts` section records base Brier `0.04681714`,
market Brier `0.03732287`, ablated Brier `0.08504397`, and source value
`+0.03822683`.

For any future nonzero source-ranking claim, materiality requires an absolute
source-value delta of at least `0.001` and a paired whole-fleet-date bootstrap
interval excluding zero. Smaller sign or rank changes remain diagnostic only.

No result in these lanes authorizes promotion or restates the standing
model-versus-market conclusion until all prescribed leakage and identity
checks are complete.
