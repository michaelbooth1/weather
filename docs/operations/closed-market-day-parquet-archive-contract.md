# Closed Market-Day Parquet Archive Contract

Last updated: 2026-06-23

This contract defines the historical Parquet surface for closed market-days.
It does not change live collectors, current serving code, or active
`data/snapshots/<event_slug>/` text tapes. Conversion and reader migration are
owned by later roadmap items; this document defines the layout, manifest, and
fallback rules they must use.

The code-backed contract constants live in
`weather.operations.closed_market_day_archive`.

## Scope

The archive is an analysis copy for closed market-days. It makes settled or
otherwise closed historical snapshot folders compact and queryable while
preserving the original raw evidence and source hashes.

Non-goals:

- Do not convert active or unsettled market-day folders.
- Do not delete, rewrite, or move source `data/snapshots` tapes.
- Do not treat Parquet as a replacement for raw JSONL/order-book payloads.
- Do not make live readers depend on the archive.

## Archive Root

The v0.1 archive root is:

```text
data/archive/closed_market_days/v0.1/
```

Each market-day uses Hive-style partition directories:

```text
data/archive/closed_market_days/v0.1/
  local_date=YYYY-MM-DD/
    market_id=<market_id>/
      event_slug=<event_slug>/
        closed_market_day_archive_manifest.json
        artifact_family=<artifact_family>/
          data.parquet
```

Partition keys are `local_date`, `market_id`, and `event_slug`. The
`artifact_family` directory separates datasets inside the market-day partition.
Partition values must be path-safe strings without path separators or `..`.

## Eligibility

A snapshot folder is eligible for this archive only when all of these are true:

- The folder name is a registered market event slug and the target date can be
  parsed.
- The target date is strictly before the archive run's market-local date, or
  event metadata marks the market closed or resolved.
- No current collector, CLOB loop, observation trigger, or writer lock is
  actively writing the folder.
- The manifest records one finalization state:
  - `settled_countable`: settlement label exists with `quality_grade` of
    `complete` or `manual_override`.
  - `settled_non_countable`: settlement evidence exists, but the quality grade
    is not countable for promotion claims.
  - `closed_unlabeled`: the market is closed or past-date, but settlement
    labeling is missing; these partitions are diagnostic evidence only.

Active current-day folders, future target dates, and folders with fresh writer
locks are not eligible. A non-countable or unlabeled closed folder may be
archived to reduce historical text-scan cost, but its manifest must keep
`countable=false`; downstream promotion and model-skill reports must continue
to use settlement quality gates.

## Manifest

Every market-day partition must contain
`closed_market_day_archive_manifest.json` with schema version
`closed_market_day_archive_manifest_v0.1`, registered as
`closed_market_day_archive_manifest`.

Required top-level fields:

| Field | Requirement |
| :--- | :--- |
| `schema_version` | `closed_market_day_archive_manifest_v0.1` |
| `archive_root_version` | `v0.1` |
| `generated_at_utc` | UTC timestamp of the writer run |
| `writer` | Module or command that wrote the partition |
| `writer_version` | Writer implementation version |
| `source_folder` | Original `data/snapshots/<event_slug>` path |
| `partition` | Object with `local_date`, `market_id`, and `event_slug` |
| `finalization` | Object with `state`, `quality_grade`, `countable`, and evidence paths |
| `artifact_families` | Per-family source, Parquet, and raw-reference records |
| `validation` | Row-count, hash, schema, and eligibility validation result |
| `manifest_hash` | SHA-256 over canonical manifest JSON with `manifest_hash` excluded |

Per-source file records must include `path`, `bytes`, `sha256`, and `role`.
Parquet records must include `path`, `bytes`, `sha256`, `row_count`, `codec`,
and `schema_fingerprint`. The default Parquet codec is `zstd`.

## Artifact Families

The archive maps existing snapshot files to artifact families. Parquet datasets
are the default closed-day analysis representation when the source is present
and schema-safe. Raw evidence references remain permanent.

| Artifact family | Source patterns | Raw evidence references |
| :--- | :--- | :--- |
| `snapshots_long` | `snapshots_long.csv`, `snapshots_long.csv.gz` | `snapshots.jsonl` |
| `features_long` | `features_long.csv`, `features_long.csv.gz` | `features.jsonl` |
| `components_long` | `components_long.csv`, `components_long.csv.gz` | `components.jsonl` |
| `forecasts_long` | `forecasts_long.csv`, `forecasts_long.csv.gz` | `forecasts.jsonl` |
| `forecast_payloads_long` | `forecast_payloads_long.csv`, `forecast_payloads_long.csv.gz` | `forecast_payloads.jsonl`, reconstructed forecast payload JSON |
| `source_status_long` | `source_status_long.csv`, `source_status_long.csv.gz` | `source_status.jsonl`, replay-input JSONL |
| `replay_inputs` | `replay_inputs.jsonl`, `replay_inputs_reconstructed.jsonl` | replay-input JSONL and `replay_input_status.json` |
| `replay_input_status` | `replay_input_status_long.csv`, `replay_input_status_long.csv.gz` | `replay_input_status.json` |
| `clob_tokens` | `clob_tokens.csv`, `clob_tokens.csv.gz` | `clob_tokens.jsonl` |
| `order_books_summary` | `order_books_summary.csv`, `order_books_summary.csv.gz` | `order_books.jsonl` |
| `order_books_long` | `order_books_long.csv`, `order_books_long.csv.gz` | `order_books.jsonl` |
| `price_history` | `price_history.csv`, `price_history.csv.gz` | `price_history.jsonl`, `price_history_raw_manifest.jsonl`, `price_history_raw/*.json` |
| `market_ws_events` | `market_ws_events.csv`, `market_ws_events.csv.gz` | `market_ws.jsonl` |
| `maker_execution_tape` | None; raw-reference-only | `mm_execution_tape.jsonl`, `mm_execution_tape.csv`, `mm_execution_tape_sessions.jsonl` |
| `clob_features_long` | `clob_features_long.csv`, `clob_features_long.csv.gz` | `clob_features.jsonl`, raw CLOB tapes |
| `variant_predictions_long` | `variant_predictions_long.csv`, `variant_predictions_long.csv.gz` | `variant_predictions.jsonl`, legacy `live_variant_predictions.jsonl` |

If a family is missing, the manifest records `status=missing_source`. If a
family is retained only as raw evidence because the JSONL shape is unstable,
the manifest records `status=raw_reference_only`.

Projection cleanup eligibility is stricter than archive readability. The
complete cleanup registry lives in
`weather.operations.closed_day_projection_registry`; it records exact
canonical rebuild sources, accepted canonical/Parquet/gzip/text
representations, and an explicit blocker for every ineligible family. At
present only
`order_books_long.csv` is eligible for verified gzip tiering. Every other
family remains blocked until its exact rebuild and every direct gzip reader
have fixture proof. The retained `order_books_long.csv.gz` is a serving
projection; `order_books.jsonl` remains canonical evidence.

The `maker_execution_tape` family is an optional event-day family. Every
member, including `mm_execution_tape.csv`, is permanent raw evidence whose
prefix bytes can be bound by a session receipt. Closed-day archiving records
the files as `raw_reference_only`, writes no Parquet dataset for the family,
and never deletes or tiers any member. The projection registry marks the whole
family explicitly ineligible for cleanup.

## Validation

A partition is valid only when the manifest validation result is `PASS`.
Validation must prove:

- The market-day is archive-eligible.
- The partition path matches the manifest partition keys.
- Every source file referenced by a Parquet dataset has a recorded byte count
  and SHA-256 hash.
- Every Parquet dataset has a byte count, SHA-256 hash, row count,
  compression codec, schema fingerprint, and artifact-family name.
- Parquet row counts match the source row counts after documented filtering or
  normalization.
  durable restore manifest.
- The manifest hash verifies after excluding the `manifest_hash` field.

Validation `WARN` or `BLOCK` partitions are retained only as diagnostics.
Readers must not prefer them over text tapes.

## Reader Fallback

Historical readers must use this preference order:

1. `validated_parquet`: read Parquet only for closed market-days with a v0.1
   manifest whose validation status is `PASS` and whose requested artifact
   family has a valid Parquet record.
2. `gzip_tiered_text`: if supported for the family, read the existing
   `.csv.gz` source under `data/snapshots`.
3. `text_tape`: read the current CSV or JSONL source under `data/snapshots`.

Live, active, current-day, missing-manifest, invalid-manifest, and unknown
artifact-family reads must fall back to the existing text layout. Reader
summaries should expose `source_mode`, manifest path or hash, source hash,
row count, and fallback reason.

The shared reader entry points live in
`weather.operations.closed_market_day_archive`:

- `read_market_day_artifact(...)` returns an `ArtifactReadResult` with a
  pandas frame and `ArtifactReadProvenance`.
- `read_artifact_frame(..., include_provenance=False)` preserves the common
  frame-only call style; callers can opt into the full result by setting
  `include_provenance=True`.

For `validated_parquet`, the reader verifies the manifest hash, manifest shape,
manifest `PASS` validation status, Parquet file hash, and Parquet row count
before returning rows. For fallbacks, provenance reports
`gzip_tiered_text` or `text_tape`, source hash, row count, and a reason such as
`active_or_future_target_date`, `missing_archive_manifest`,
`archive_disabled`, or `parquet_family_unavailable`.

`weather.reporting.source_gates.source_family_inventory` is the first high-byte report
migrated to this boundary. Its JSON and Markdown outputs include
`historical_reader_summary` / "Historical Reader Sources" so operators can see
which artifact families came from validated Parquet versus fallback text.
`weather.reporting.scorecards.snapshot_evaluation` also reads closed-day snapshot and
replay-input history through this boundary and reports source-mode mix.

## Incremental Conversion

Closed-day conversion can run as a bounded, resumable daily/operator job:

```powershell
python -m weather.operations.closed_market_day_archive incremental-apply --max-scan-folders 25
```

The incremental status schema is
`closed_market_day_parquet_incremental_v0.1`. The command writes:

- `data/backtest/closed_market_day_parquet_incremental.json`
- `data/backtest/closed_market_day_parquet_incremental_report.md`
- `data/backtest/closed_market_day_parquet_incremental_cursor.json`

The cursor records each scanned folder's event-day manifest hash when present
and falls back to source-file stats otherwise. Unchanged folders are skipped,
failed folders are retried on the next pass, and the scan cursor advances
across the sorted snapshot folder list to avoid full-tree timeouts.

Daily refresh runs the same bounded incremental converter before historical
reader-heavy reports. Fleet observability reads the incremental status artifact
and surfaces conversion failures, blockers, bytes, and remaining scan backlog.

## DuckDB Operator Queries

DuckDB is optional operator tooling for this archive version. It is not a
pinned project dependency and production/reporting code must continue to use
the pandas/pyarrow reader boundary above unless a later roadmap item updates
the packaging policy. Operators who already have DuckDB installed can query
partitioned Parquet directly without loading the whole snapshot tree:

```python
import duckdb

con = duckdb.connect()
rows = con.sql("""
    SELECT
      event_slug,
      market_id,
      count(*) AS book_rows,
      avg(CAST(bid AS DOUBLE)) AS avg_bid,
      avg(CAST(ask AS DOUBLE)) AS avg_ask
    FROM read_parquet(
      'data/archive/closed_market_days/v0.1/local_date=*/market_id=*/event_slug=*/artifact_family=order_books_long/data.parquet',
      hive_partitioning = true
    )
    WHERE local_date >= '2026-06-01'
    GROUP BY event_slug, market_id
    ORDER BY book_rows DESC
    LIMIT 20
""").df()
print(rows)
```

## Forensic Evidence

Parquet is an analysis representation. The following remain forensic evidence
and must stay protected by reviewed cleanup manifests:

- `snapshots.jsonl`, `features.jsonl`, `components.jsonl`, `forecasts.jsonl`,
  `forecast_payloads.jsonl`, `source_status.jsonl`, `replay_inputs.jsonl`, and
  `replay_inputs_reconstructed.jsonl`.
- Raw CLOB tapes: `clob_tokens.jsonl`, `order_books.jsonl`,
  `price_history.jsonl`, `price_history_raw_manifest.jsonl`,
  `price_history_raw/*.json`, `market_ws.jsonl`, and capture status rows.
- Dedicated maker execution evidence: `mm_execution_tape.jsonl`,
  `mm_execution_tape.csv`, and `mm_execution_tape_sessions.jsonl`.
- Settlement labels, per-market ledgers, resolution specs, and reconciliation
  evidence.
- Archive manifests and Parquet partitions after Item 244 writes them.

CSV long tables are source material for v0.1 conversion and remain local text
fallbacks until a later cleanup item proves validated Parquet, durable raw
restore, and an explicit cleanup manifest. Item 243 authorizes no deletion.
