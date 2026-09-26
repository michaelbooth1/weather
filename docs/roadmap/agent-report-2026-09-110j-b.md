# 110j Part B — remove exactly rebuilt order-book gzip twins

**PASS — 110 tests and 40 subtests pass, including all four repo-wide audits. The synthetic inventory qualifies 1 of 4 days; no production inventory or files were accessed. Production roll verdict is UNDECIDABLE without capture closures, so use roll-sensitive treatment pending its gate.**

Branch: `codex/order-books-long-twin-delete-20260926`; independent base
`965374a0edc6fcb65d66e257be9e404cc9af8d60`. Executed after Part A was pushed.
Implements owner decision 6 from handoff 110j at `ed075014161e6e0b0f8d3e9d0fc8dd265356d2c2`.

`plan-twins` selects, `prove-twins` streams the exact writer-format CSV rebuild
without staging a full long table, and existing `apply` removes only the
approved gzip projection. The same-folder canonical `order_books.jsonl.gz`
must remain present. Strict age >14 days, no split representations, current
PASS manifest, exact identity, quiescence and writer exclusion remain gates.
Both source and reference are rebound after rebuild. Apply proves again under
the raw writer lock, checkpoints UNLINK_PENDING and repeats before unlink.
It refreshes the event manifest afterwards, retaining a truthful partial
receipt on failure. Gzip JSONL now participates in manifest inspection and
canonical storage classification, so backfilled manifests can describe it.

Synthetic inventory: one 15-day-old matching pair qualifies; one folder
without raw gzip, one with a split raw tape, and one exactly 14 days old are
blocked. Tests also refuse altered source/reference/manifest, active locks,
missing proof, malformed gzip and differing rows. The raw bytes survive the
successful apply. The approximately 93 production raw-less folders mentioned
by the handoff were not examined and cannot qualify under these rules.

The compressed-byte cap defaults to 1 GiB. Before mutation, a fixed local-date
ledger under the data root reserves the complete plan across all attempts;
another output root, plan date or larger later budget cannot reset it.
Failed attempts consume their reservation. A manual PowerShell wrapper holds
the host lease and bounds the complete child Job through 09:00/runtime teardown.

## Per-file roll classification

| File | Classification |
| --- | --- |
| `src/weather/operations/closed_day_projection_tiering.py` | Roll-sensitive treatment: closure membership UNDECIDABLE on clean workstation. |
| `src/weather/operations/closed_day_projection_registry.py` | Roll-sensitive treatment: same evidence limit. |
| `src/weather/operations/event_day_manifest.py` | Roll-sensitive treatment: same evidence limit. |
| `src/weather/operations/storage_classes.py` | Roll-sensitive treatment: same evidence limit. |
| `scripts/ops/closed_day_projection_twins_run.ps1` | Roll-free; PowerShell is outside Python capture closures. |
| `tests/operations/test_closed_day_projection_tiering.py` | Roll-free. |
| `docs/operations/data-storage-class-contract.md` | Roll-free. |
| `docs/operations/data-retention-policy.md` | Roll-free. |
| `docs/roadmap/agent-report-2026-09-110j-b.md` | Roll-free. |
| `docs/roadmap/correspondence-index.md` | Roll-free; generated. |

No schema-registry change; existing plan/rebuild/receipt schemas carry the
additional operation. The budget journal uses the existing receipt schema.
`roll_verdict.ps1` returned UNDECIDABLE, missing all four live closure files.
No closure names are invented from static imports. Production re-runs:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/order-books-long-twin-delete-20260926 -Base master
```

## Exact production commands

From the production repository root, only in its admitted window; use new
review directories for each campaign. The wrapper checks the shared lease,
current memory evidence and free disk before starting Python:

```powershell
.\scripts\ops\closed_day_projection_twins_run.ps1 -Command plan-twins -OutputRoot scratch/twin-review/selection -MaxBytes 1073741824
.\scripts\ops\closed_day_projection_twins_run.ps1 -Command prove-twins -ApprovedManifest scratch/twin-review/selection/closed_day_projection_tiering_plan.json -OutputRoot scratch/twin-review/proof
# Owner reviews and completes operator_review in the proved JSON, binding its plan_hash.
.\scripts\ops\closed_day_projection_twins_run.ps1 -Command apply -ApprovedManifest scratch/twin-review/proof/closed_day_projection_twins_proved.json -OutputRoot scratch/twin-review/apply
```

Absent/stale manifests require the owning event-manifest backfill before the
plan. Do not weaken validation or fabricate PASS. See the amended retention
policy for failure recovery and the nightly reservation ledger.

## Verification and boundaries

The project interpreter ran via `workstation_heavy.ps1 -Kind pytest`:

```text
-m pytest -q tests/operations/test_closed_day_projection_tiering.py tests/operations/test_event_day_manifest.py tests/operations/test_storage_classes.py tests/market/test_order_book_tape.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py --basetemp <owned-temp-directory>
```

Initial failures exposed a fixture younger than the existing two-hour quiet
gate, an old registry expectation and an untracked-wrapper ratchet; those
were corrected without changing production gates. The complete set then
passed. PowerShell parsed with zero errors; native production execution is
not claimed. `git diff --check` passed. Test basetemp is removed after runs.

No production data, credentials, venue calls, registration, production write,
restart or merge. No source tape was deleted. Branch commits and generated
index commit are available via `git log origin/master..HEAD`; production
adoption and owner campaign approval remain separate.
