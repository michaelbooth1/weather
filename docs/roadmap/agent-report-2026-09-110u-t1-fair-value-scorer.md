# Agent report 2026-09-110u — T+1/T+2 fair-value reliability scorer

**IMPLEMENTED AND FIXTURE-VERIFIED; real scoring NOT RUN. Two inherited module-size audit failures remain.**

The requested scorer consumes sealed replay bundles and implements the unchanged
[frozen pre-registration](../research/t1-fair-value-preregistration-2026-09-25.md).
Its [operator contract](../operations/t1-fair-value-scoring.md) owns the CLI,
admission, deterministic reports and interpretation. No forecast or edge claim
was measured. No frozen choice was changed.

## Provenance and dependency

- Instruction: `docs/roadmap/workstation-handoff-2026-09-110u-t1-fair-value-scorer.md`
  read from `origin/codex/handoff-110k-20260926` at
  `f7b6eff7d1131991720f36226e14f38f9f90eb68` after fetching origin.
- Branch: `codex/t1-fair-value-scorer-20260927`.
- Implementation commit: `216e937f5e1c761e2cbb2eac2e8dfd6c1b4d1405`.
- Explicit stacked base: `origin/codex/maker-replay-harness-20260926` at
  `8ee7b8ad34c3d6ab8c073e93f90fc717586505ca`,
  [parent PR #100](https://github.com/michaelbooth1/weather/pull/100).
  Fetched master was `965374a0edc6fcb65d66e257be9e404cc9af8d60`; this is not a
  master-based implementation. Land the parent dependency before this branch.
- Isolated workstation worktree: `scratch/w/t1-fair-value-scorer-20260927` beneath
  the existing repository. The user's original checkout and other worktrees were preserved.
- Frozen pre-registration SHA-256:
  `835c77f61fb53b7053cf42b90f3a34611bccdd35920c18b673e3690591930740`.
  Its diff from the required base is empty. Estimator/provider files are unchanged.
- Reserved-window status checked on the fetched instruction branch: **NONE RESERVED**.
  This mission nevertheless read synthetic fixtures only, including its panel-date fixtures.

## Delivered behavior

The first complete captured minute in each event/lead/UTC hour is selected before
joining settlements. It requires every sibling, a full band partition, matching
contemporaneous two-sided YES mids and captured views. Retained point-in-time
inputs must reproduce the unchanged plugin view exactly. Captured mids are not
normalized; unavailable evidence never becomes 0.5 or a zero loss.

Paired mean band Brier is averaged over hours within market-day, then equally
over market-days. NBP/fallback and lead 1/2 have four separate tables plus one
pooled descriptive table. Fixed reliability bins include zero and one; empty
bins remain unavailable. The bootstrap independently draws date and market
multiplicities, multiplies them on observed cells, and uses 10,000 replicates,
seed 110, two-sided 90% percentile intervals and date-only sensitivity.
Undefined sparse draws are counted. Tables and reliability bins retain cluster
support; fewer than ten clusters in either dimension is UNDERPOWERED.

JSON and Markdown are deterministic for the same evidence and implementation.
The report includes export hashes, code tip/implementation hashes, selected
captures, input and settlement bindings, market-day losses, coverage and
exclusions. The envelope accepts the additive `release_calibration_method`
source-row field. T+0 remains excluded. Later settlement-only carry exports work
through the existing producer, tested end to end.

The unchanged registration says **after 2026-10-08**, so the code refuses before
**2026-10-09 UTC**, before reading inputs. There is no CLI date override. The
handoff's owner-approved actual scoring day remains **2026-10-15**, disclosed in
the replay execution manifest, with the same sealed bundles. The calendar gate
is not an authorization for earlier/repeated scoring. The future heavy scorer
requires the execution manifest's qualified admission path; no host allowlist
was expanded by this mission.

## Verification and limitations

On the non-capture workstation, all Python verification used
`scripts/ops/workstation_heavy.ps1` with the attending principal, its shared mutex
and child-tree containment. Busy-lease refusals were respected and retried later.

| Check | Result |
| --- | --- |
| Scorer, existing plugin, dry-run and bundle owner regressions (seven focused files) | **612 passed, 1 skipped**, 5.30 seconds |
| Repository-wide architecture, schema, path, module-size, agent-doc, knowledge-structure and roadmap/index audits (eight focused files) | **82 passed, 2 failed**, 22.78 seconds |
| Same module-size audit on a new clean detached worktree at exact base `8ee7b8ad` | **3 passed, same 2 failed**, 2.28 seconds |
| `compileall -q app src tests` through the wrapper | PASS |
| Staged diff whitespace and frozen-spec diff checks | PASS; frozen diff empty |

Both failures concern the unchanged `weather.operations.closed_day_projection_tiering`:
`test_current_warning_modules_have_complete_ownership_metadata_and_no_orphans`
and `test_current_warnings_stay_within_reviewed_ownership_allowance`.
The existing module exceeds the warning threshold without the required reviewed
ownership entry. The failing module, audit implementation/tests and ownership
document match the parent exactly. No gate was relaxed and no unrelated owner
file was changed to conceal this inherited blocker.

The scorer's 26 fixture cases cover earliest-date refusal before IO, native C/F,
local-date leads, panel/T+0 exclusion, missing first-minute books, identity and
clock corruption, tampered views, missing/unbound settlement, raw-byte tampering,
duplicate/unsealed exports, create-only reports, deterministic ordering, separate
strata, fixed bins, sparse bootstrap draws and 9-versus-10 cluster boundaries.
The unequal-hour oracle yields provider Brier **0.43**, mid **0.25**, difference
**0.18** across **2 synthetic dates, 1 market, 2 market-days** (UNDERPOWERED).
A separate sparse 2-date x 2-market fixture checks the crossed interval against
an independent multiplicity calculation. These are correctness controls, not
production estimates, measured power or evidence of edge.

No production-sized memory/runtime qualification or real calibration estimate
exists. Numeric detectable effect/power is unestablished; fallback spread is the
frozen engineering prior, not measured climatological error. Hashes bind export
bytes, not authenticity; settlement projections rely on the bounded producer.

## Reproduction

From the assigned branch root with its project interpreter, run the following
argument arrays through the workstation wrapper as documented in
[development](../development.md#separate-non-capture-workstation). Supply a fresh
explicit `--basetemp` under the host's temporary directory and delete only that
test directory afterwards. These paths exist in this branch; no production
`data/` or workstation mirror is required.

```text
-m pytest tests/market/test_maker_fair_value_score.py tests/market/test_maker_replay_bundle.py tests/market/test_maker_plugin.py tests/market/test_maker_plugin_110c.py tests/market/test_maker_plugin_110e.py tests/market/test_maker_plugin_dry_run.py tests/maker_core/test_replay_bundle.py -q
-m pytest tests/operations/test_import_architecture.py tests/operations/test_schema_registry.py tests/operations/test_path_policy.py tests/operations/test_module_size_audit.py tests/operations/test_agent_docs_audit.py tests/operations/test_knowledge_structure_audit.py tests/reporting/test_roadmap_backlog.py tests/reporting/test_correspondence_index.py -q
-m compileall -q app src tests
```

The repository-contract test calls the actual agent-doc audit, including read-only
roadmap and correspondence parity checks. The source report is committed before
regenerating its correspondence index, as required by the roadmap guide.

## Per-file roll disposition and operational boundary

The mechanical command was run from the isolated worktree:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch codex/t1-fair-value-scorer-20260927 -Base origin/codex/maker-replay-harness-20260926
```

It returned **UNDECIDABLE: no live closure evidence** (all four required capture
status files absent). No workstation mirror was substituted. Production must
rerun the tool against its retained current closures before integration.

| Changed file | Roll disposition / closure evidence |
| --- | --- |
| `src/weather/market/maker_plugin/fair_value_score.py` | UNDECIDABLE; no retained live closures on this fixture-only worktree |
| `src/weather/market/maker_fair_value_score.py` | UNDECIDABLE; same missing closure evidence |
| `src/weather/market/maker_fair_value_statistics.py` | UNDECIDABLE; same missing closure evidence |
| `tests/market/test_maker_fair_value_score.py` | UNDECIDABLE for exact closure membership; tests only |
| `docs/operations/t1-fair-value-scoring.md` | Roll-free document by the standing contract |
| `docs/operations/README.md` | Roll-free index link |
| This report and generated `docs/roadmap/correspondence-index.md` | Roll-free correspondence |

No schema-registry-family edit, model fit, candidate, promotion, real scored read,
provider query, credential read, production write, mirror access, registration,
restart, merge or live exchange action was performed. Publication is a topic
branch and draft PR only. CI/review and production adoption remain separate.
