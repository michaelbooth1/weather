# Data Retention Policy

Use the data-retention inventory before pruning local `data/` files. The
report is read-only and exists to classify ownership, TTL policy, cleanup
requirements, and disk-growth pressure.

## Daily Report

Run directly:

```powershell
python -m weather.reporting.data_quality.data_retention_inventory --root data --out data\backtest\data_retention_inventory.json --report data\backtest\data_retention_inventory_report.md
```

The normal daily refresh also writes the same artifacts:

- `data/backtest/data_retention_inventory.json`
- `data/backtest/data_retention_inventory_report.md`

## Pruning Rules

- Classify files with the
  [Data Storage Class Contract](data-storage-class-contract.md) before cleanup:
  `canonical_evidence`, `analysis_projection`, and `operator_cache` have
  different review, rebuild-source, and deletion gates.
- Do not delete `snapshots`, `mm_runs`, `taker_runs`, or canonical historical
  source rows unless a reviewed cleanup manifest names the exact files.
- Run `python -m weather.operations.cleanup_preflight --manifest <cleanup.json>`
  before any cleanup workflow that could delete local data. A canonical
  evidence candidate requires operator review, exact paths, and current
  checksums.
- Closed market-day Parquet partitions live under
  `data/archive/closed_market_days/v0.1` and are analysis copies, not raw
  evidence replacements. Follow
  [Closed Market-Day Parquet Archive Contract](closed-market-day-parquet-archive-contract.md)
  for eligibility, manifest validation, reader fallback, and raw-evidence
  boundaries.
- Use `python -m weather.reporting.data_quality.backtest_artifact_retention` for large
  rebuildable `data/backtest` row exports; delete only from its cleanup
  manifest when paired reports or manifests exist.
- Prefer gzip tiering or externalization for large historical JSONL/CSV
  evidence before deleting local copies.

Routine provider caches may be pruned after TTL expiry when no replay,
promotion, or incident report references them. Forecast archives used for
settled replay evidence are not routine cache.

## Storage-Pressure Build

The workstation storage-pressure tools are manual and dry-run first. They are
not scheduled and a code merge performs no cleanup.

`config/storage_pressure.json` owns the capture switch. The checked-in value
`capture.write_order_books_long_csv=true` preserves current behavior. Missing,
malformed, wrong-schema, duplicate-key, or non-boolean policy also fails safe
to writing the projection. Setting the value to `false` skips only future
`order_books_long.csv` appends; summary CSV and canonical
`order_books.jsonl` capture continue, and existing long tables are untouched.

Plan replay-cache retention from explicitly named reachability roots:

```powershell
python -m weather.operations.replay_cache_retention --cache-root <replay-cache-root> --corpus <pinned-promotion-corpus.json> --registry config\model_variant_registry.json --active-release-pointer <artifacts\releases\current_release.json> --releases-root <artifacts\releases> --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The planner uses full cache keys and exact corpus/artifact/config identities.
It never selects by age, modification time, or LRU. Missing or changing roots,
unreadable subtrees, malformed entries, path/key mismatches, links, or any
other ambiguity retain every provisional candidate. The recommended quota is
10 GiB: it is deliberately far above the expected healthy cache working set
and therefore detects runaway identity/config accumulation. It is a diagnostic
ceiling, not an eviction policy; reachable entries are never selected even
when reachable bytes exceed the quota. Rebuildable candidates must use a
verified `production_static_context`; legacy artifacts that could consult
mutable climate, source-reliability, reanalysis, or marine sidecars are
retained. The plan also pins the genuine active pointer's exact identity plus
the complete retained release manifest and declared artifact inventory. Apply
resolves that same pointer through the strict
release-root-contained serving path. The resolved `release_id`,
`manifest_sha256`, and `release_dir` must match the approved plan; any active
release drift aborts cleanup and requires a new plan.

Apply also performs the real
`_compute_pooled_candidate_day` cache-off computation for every exact
corpus/artifact binding, compares the full six-field key plus `rows`,
`replay_results`, `coverage`, and `diagnostics`, writes a durable
`PRE_UNLINK` record, then repeats the computation and source/candidate
verification immediately before the exact-file unlink. A mismatch or compute
failure retains the candidate.

After reviewing every candidate, edit only the manifest's
`operator_review.approved`, `approved_by`, `approved_at_utc`, and `note`
fields. Then bind apply to the edited file and repeat every planning root:

```powershell
$manifestHash = (Get-FileHash -Algorithm SHA256 <review-output-outside-data>\replay_cache_retention_manifest.json).Hash.ToLowerInvariant()
python -m weather.operations.replay_cache_retention --apply --manifest <review-output-outside-data>\replay_cache_retention_manifest.json --expected-manifest-sha256 $manifestHash --cache-root <replay-cache-root> --corpus <pinned-promotion-corpus.json> --registry config\model_variant_registry.json --active-release-pointer <artifacts\releases\current_release.json> --releases-root <artifacts\releases> --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The standalone two-file fixture comparison does not prove an actual rebuild,
but can be run without unrelated plan inputs:

```powershell
python -m weather.operations.replay_cache_retention --rebuild-one-cache-entry <cache-entry.json> --rebuild-one-payload <rebuilt-payload.json> --output-root <proof-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

Plan closed-day projection tiering separately:

```powershell
python -m weather.operations.closed_day_projection_tiering plan --snapshots-root <data\snapshots> --as-of-date <YYYY-MM-DD> --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
python -m weather.operations.closed_day_projection_tiering rebuild-one --folder <closed-event-folder> --output-root <proof-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The projection registry names every closed-day archive family, its canonical
rebuild source, accepted reader representations, and its current blocker.
Only `order_books_long` is eligible. It requires finalized closed-day evidence,
a current event-day manifest, no writer lock, at least
`MIN_QUIET_SECONDS` of source-write quiescence, canonical `order_books.jsonl`,
and an exact byte-parity rebuild proof. Apply retains
`order_books_long.csv.gz` and removes only the verified same-folder
`order_books_long.csv`; it never treats the raw JSONL as disposable.

After reviewing the tiering plan, edit only
`operator_review.approved`, `approved_by`, `approved_at_utc`, `note`, and
`approved_plan_hash`; the last value must exactly equal the unchanged top-level
`plan_hash`. Apply uses the exact approved-manifest file identity:

```powershell
python -m weather.operations.closed_day_projection_tiering apply --approved-manifest <review-output-outside-data>\closed_day_projection_tiering_plan.json --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

Plan canonical warm representation through a separate registry and plan kind:

```powershell
python -m weather.operations.closed_day_projection_tiering warm-plan --snapshots-root <data\snapshots> --as-of-date <YYYY-MM-DD> --hot-window-days 30 --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The production point-in-time contract needs 14 contiguous target dates whose
latest target may be at most 7 days old. Its oldest possible target is
therefore 20 days old, making 21 the minimum warm age. The default 30-day hot
window adds 9 recovery days. The planner rejects a shorter window, a future
as-of date, any event inside the configured hot window, a non-final or stale
event-day manifest, a writer lock, insufficient write quiescence, and every
plain/gzip conflict.

The warm registry records all reader, delegated-reader, discovery, manifest,
and writer surfaces for the six measured high-payoff families. Only canonical
`order_books.jsonl` is currently eligible. `clob_tokens.jsonl`,
`replay_inputs.jsonl`, `variant_predictions.jsonl`,
`order_books_summary.csv`, and `clob_tokens.csv` remain blocked on specifically
named plain-file consumers.

After reviewing the warm plan, edit only the same five `operator_review`
fields described above and bind `approved_plan_hash` to the unchanged
top-level `plan_hash`. Apply is a representation replacement: it retains
byte-identical `order_books.jsonl.gz`, then physically removes only the
approved plain peer after the durable checkpoint and immediate re-verification.
Run it only in an operator-owned quiet window:

```powershell
python -m weather.operations.closed_day_projection_tiering warm-apply --approved-manifest <review-output-outside-data>\closed_day_warm_tiering_plan.json --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

Warm apply reruns `cleanup_preflight`, exact file and manifest identities,
finalization, hot-window, lock, and quiescence gates; holds the raw-tape writer
lock; writes deterministic gzip with `mtime=0`; verifies decompressed byte
length and SHA-256; and persists and re-reads both
`closed_day_warm_tiering_apply_receipt.json` and its Markdown peer before the
exact-file unlink. It refreshes the event-day manifest to PASS afterward and
supports receipt-bound recovery for an exactly staged deterministic gzip and
for interruption between unlink and manifest refresh. A normal failure before
unlink removes only a receipt-bound gzip created by that attempt and retains
the approved plain source. A retry re-verifies completed actions rather than
trusting receipt status. It stops on the first failure and never removes a
directory.

Current market-making runtime consumes `order_books_summary.csv`, which remains
untouched. Future full-depth corpus readers must use
`weather.market.order_book_tape`: tiered canonical JSONL first, then the
tiered long CSV. Either plain or gzip is accepted when it is the only
representation. When both peers exist, their complete decompressed bytes must
match before any rows are returned; a malformed or divergent pair fails
loudly. Gzip is streamed directly and does not require a restored plain working
copy. The long-table column contract has been unchanged since its introduction,
and gzip fallback is covered by fixture tests. Production 85-GiB replay remains
an operator rehearsal and is not implied by unit tests.

Every apply workflow requires an externally reviewed exact manifest,
`cleanup_preflight`, immediate identity/byte/SHA/key re-verification as
applicable to its artifact, and durable per-action JSON and Markdown receipts.
The tools stop on the first failure and never remove directories. Every
production data or mirror boundary must be supplied with a repeated
`--protected-root`; output is rejected if it overlaps any one of them, while
the source data root is independently derived and protected as well. Do not use
these commands against production data until the operator has reviewed the dry
run and scheduled the quiet window.

## Shared Forecast Payload CAS

New explicitly market-invariant forecast responses use the shared immutable
CAS under `data/forecast_payload_cas/`; their per-market append-only manifests
retain capture and extraction lineage. Inventory a possible legacy migration
without copying, rewriting, or deleting evidence:

```powershell
python -m weather.operations.forecast_payload_cas_migration
python -m weather.operations.forecast_payload_cas_migration --month 2026-07 --max-payload-bytes-read 8589934592 --max-elapsed-seconds 300
```

The command is dry-run only. It verifies legacy hash/restore/replay checks and
the shared references found in snapshot `forecast_payloads.jsonl` files. The
inventory is bounded by directory and tree-entry counts, manifest count and
bytes, JSONL line size, manifest rows, per-payload and aggregate payload bytes,
elapsed time, retained candidate detail, and physical-blob count; any reached
bound is explicit in the artifact. Use `--month YYYY-MM` for a bounded monthly
segment. The report counts a repeatedly referenced legacy file once by physical
file identity, includes verified legacy bytes, projected one-copy bytes, and
projected reclaimable bytes by month, and assigns a cross-month physical file to
its earliest observed month. Monthly one-copy projections are scenarios rather
than additive totals. Truncated results remain partial and must not be treated as
a complete reclaim total. That scan is explicitly
partial inventory, not global reachability: blobs absent from the scanned
references are non-authoritative observations, never deletion candidates. No
current cleanup review can authorize shared-CAS deletion.
The CLI returns `2` and prints `status=partial`, the stop reasons, and the
resume cursor when any bound or scan-integrity condition truncates inventory;
only a complete bounded scan returns zero.
Event-day manifests enumerate referenced shared blobs as external canonical
dependencies and remain blocked until both backup and restore evidence includes
their exact digests. Legacy market-local blobs remain canonical evidence.

## Update when

Update when retention CLI entry points, code-backed family eligibility,
hot-window bindings, approval/apply gates, protected-root requirements, or
shared-CAS deletion policy changes.
