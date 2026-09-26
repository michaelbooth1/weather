# Agent report 2026-09-110j-d — verified archive storage families

**PASS — 160 tests and 40 subtests pass, including all four repo-wide audits. A 10,001-file synthetic raw-price subtree stages, verifies and restores byte-for-byte as one tar. Production execution and the live-closure merge verdict remain host-side.**
Branch `codex/cold-archive-lane-extensions-20260926`, independently based on
`origin/master` at `965374a0edc6fcb65d66e257be9e404cc9af8d60`. Built after A, B
and C were pushed. Assigned handoff read from
`origin/codex/owner-decisions-0926-day` at `ed075014161e6e0b0f8d3e9d0fc8dd265356d2c2`,
descendant of required `8cf764d26`. Owner decisions 1–9 approved; 10 retained,
11 declined. All execution here used synthetic files and local fixture seams.
No production data, credentials, Drive objects, venue calls, Scheduler or
production state were accessed or changed.

## Per-file roll classification

Python source below receives **roll-sensitive treatment** pending the production
tool's current imported-closure verdict. Tests and Markdown are roll-free.
The workstation contains no live closure evidence; no synthetic closure is
substituted for the production merge gate.

The repository tool returned **UNDECIDABLE: no live closure evidence**, naming
the absent loop, CLOB, observation-trigger and enrichment status files. It did
not certify any Python file as roll-free.

| File | Classification |
| --- | --- |
| `src/weather/cold_archive_locations.py` | roll-sensitive |
| `src/weather/market/market_microstructure_capture.py` | roll-sensitive |
| `src/weather/market/mm_paper_scoring.py` | roll-sensitive |
| `src/weather/market/mm_scoring_projection.py` | roll-sensitive |
| `src/weather/operations/bulk_cold_archive_crypt.py` | roll-sensitive |
| `src/weather/operations/cold_archive_catalog.py` | roll-sensitive |
| `src/weather/operations/cold_archive_families.py` | roll-sensitive |
| `src/weather/operations/cold_archive_reclaim.py` | roll-sensitive |
| `src/weather/operations/production_cold_archive_stage.py` | roll-sensitive |
| `src/weather/operations/production_cold_archive_stage_cli.py` | roll-sensitive |
| `src/weather/operations/production_cold_archive_transfer_core.py` | roll-sensitive |
| `src/weather/operations/storage_classes.py` | roll-sensitive |
| `src/weather/reporting/market/mm_input_age_postmortem.py` | roll-sensitive |
| `src/weather/reporting/scorecards/captured_input_parity_evidence.py` | roll-sensitive |
| `src/weather/reporting/scorecards/live_variant_settlement_scorecard.py` | roll-sensitive |
| `src/weather/reporting/source_gates/cross_hub_readiness.py` | roll-sensitive |
| `src/weather/schema_registry_data.py` | roll-sensitive |
| `tests/operations/test_cold_archive_catalog.py` | roll-free |
| `tests/operations/test_cold_archive_reclaim.py` | roll-free |
| `tests/operations/test_storage_archive_families.py` | roll-free |
| `docs/operations/cold-archive-locations.md` | roll-free |
| `docs/operations/data-storage-class-contract.md` | roll-free |
| `docs/operations/production-cold-archive-staging.md` | roll-free |
| `docs/roadmap/agent-report-2026-09-110j-d.md` | roll-free |
| `docs/roadmap/correspondence-index.md` | roll-free |

## Behavior and boundaries

The new hash-bound `owner_storage_families_v1` grouping orders rotated root
snapshot diagnostics, maker quote CSVs, variant/explanation tapes, then complete
raw-price event subtrees. It retains the conservative >30-day floor for every
family. The maker panel 2026-07-31 through 2026-08-08 stays hot even after it
ages out; both staging admission and reclaim enforce the exclusion. Active
diagnostics and observation-trigger rotations cannot enter the new grouping.

Ordinary archives remain bounded to 256 members/1 GiB. Only one complete
`price_history_raw` event subtree can use up to 16,384 members in a single tar;
oversize subtrees are refused, never split. Source enumeration before/after
streaming detects incomplete selections. Header/padding headroom reaches stage,
verification, encryption and transfer size bounds. Catalog publication checks
small markers against a pinned verified entry, avoiding repeated full catalog
reads for each member. Catalog and cache inventory bounds cover the larger tar.

Variant discovery retains archived logical names. Scorecard, captured-input
parity, maker scoring/discovery, input-age reports and raw-price response readers
resolve verified local restore caches. Missing off-site payloads demand restore;
they do not silently shrink the population. Parity uses original member mtime,
so restoring old evidence cannot pass a freshness gate. Source hashes refer to
the actual retained bytes and provenance paths remain logical originals.

**No event-day manifest backfill is required.** The production lane consumes
exact selections, owner proposal/approval, bound plans, native source identity,
stage/crypt/upload proofs and independent full restore receipts. It does not
require a current event-day manifest. Existing manifests and raw-price hash
reference manifests remain retained. The fixture-only verified archive API has
a different manifest contract and is not used for this campaign.

Each campaign still needs exact owner approval. Stage and upload grant no
delete authority; reclaim needs an independent complete workstation restore
finished within 24 hours, off-host metadata and key custody, adopted consumers,
a fresh exact-source protection review, native exclusive handles, canonical
cleanup preflight, immutable intent and per-file receipts. Root diagnostic
rotations have a closed-log/writer-free review instead of fictional settlement
status; protected-reference checks remain. Part A's diagnostic classification
is an integration prerequisite. Maker quote CSVs need canonical classification
because they contain captured decisions that cannot be recreated afterwards.

## Verification

The first frozen-source broad run completed **682 passed, 4 skipped and 22
subtests passed** with three failures: diagnostic reclaim required Part A's
classification; maker quote CSVs were unclassified on the base; the new packing
identifier needed the same explicit non-schema exclusion as existing grouping
identifiers. Those are fixed. The final focused run completed **160 passed and
40 subtests passed** in 199 seconds. It repeated the real 10,001-file synthetic
stage/verify/materialized-restore exercise and validated its manifest through
the encryption bridge. Every restored file matched its retained original.

Tests cover all four family layouts, exact campaign approval, EF 8bb exclusion,
age boundaries, incomplete-subtree refusal, bounded one-tar packing, existing
restore/custody/source fault gates, explicit Part A adoption, archived discovery,
JSONL and CSV cache reads, missing-input refusal and original-timestamp freshness.
Diagnostic positive integration fixtures supply Part A's exact registry row;
a separate negative test proves D refuses reclaim without its adoption.

Every focused run includes schema registry, import architecture, agent docs and
path-policy audits. Runs used `workstation_heavy.ps1 -Kind pytest`, the project
interpreter and `--basetemp C:/Users/Michael/AppData/Local/Temp/weather-110j-d`.
The final selection was:

```text
-m pytest -q tests/operations/test_storage_archive_families.py tests/operations/test_cold_archive_reclaim.py tests/operations/test_storage_classes.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py --basetemp <owned-temp-directory>
```

No cloud credentials or real transport were used; upstream upload/restore
receipts are synthetic sealed proof fixtures. Catalog, transport, stage/wrapper,
variant/parity, cross-hub, maker scoring/projection/input-age and microstructure
regressions also passed in the broader selection. The exact disposable fixture
directory is removed after committed-report verification.

## Production commands and integration

First obtain the production closure verdict after fetching:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/cold-archive-lane-extensions-20260926 -Base master
```

Land A before D's first diagnostic campaign. C and D independently edit some
reader functions: preserve C's canonical JSONL/projection adapters together
with D's archive discovery, original-mtime checks and logical source identity.
Regenerate the correspondence index after integration. Do not infer production
closure membership from workstation imports or synthetic status files.

After fresh owner review supplies an exact measured selection, plan from
metadata through the admitted workload lane:

```powershell
.\venv\Scripts\python.exe -m weather.operations.production_cold_archive_stage_cli plan --selection <absolute-selection-path> --selection-sha256 <raw-sha256> --output-path <new-absolute-plan-path> --chunk-grouping owner_storage_families_v1
```

The operation-specific requests bind exact paths, raw hashes, source tip, host,
owner and expiry. In the existing admitted production window, execute each
phase separately with a fresh attempt directory:

```powershell
.\scripts\ops\production_cold_archive_run.ps1 -Operation stage -ProductionRepoRoot <production-root> -RequestPath <stage-request> -RequestSha256 <stage-request-sha256> -OutputRoot <new-stage-output> -ExpectedSourceTip <reviewed-source-commit>
.\scripts\ops\production_cold_archive_run.ps1 -Operation upload -ProductionRepoRoot <production-root> -RequestPath <upload-request> -RequestSha256 <upload-request-sha256> -OutputRoot <new-transfer-output> -ExpectedSourceTip <reviewed-source-commit>
.\scripts\ops\production_cold_archive_run.ps1 -Operation download -ProductionRepoRoot <production-root> -RequestPath <download-request> -RequestSha256 <download-request-sha256> -OutputRoot <new-transfer-output> -ExpectedSourceTip <reviewed-source-commit>
```

Between stage and upload, use the existing admitted workstation encryption
bridge; after the independent download use its complete restore and recovery
publication. The exact required `--production-chunk` arguments and workload
wrapper are in [production-cold-archive-staging.md](../operations/production-cold-archive-staging.md)
and [cold-archive-locations.md](../operations/cold-archive-locations.md).
Retain every proof and new catalog marker. Only after all fresh reclaim gates:

```powershell
.\scripts\ops\production_cold_archive_run.ps1 -Operation reclaim -ProductionRepoRoot <production-root> -RequestPath <reclaim-request> -RequestSha256 <reclaim-request-sha256> -OutputRoot <new-reclaim-output> -ExpectedSourceTip <reviewed-source-commit>
```

These are handback commands, not a request to execute this campaign now.
