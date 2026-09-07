# Config Inventory

Status: canonical configuration classification and freshness policy.

Checked-in files under `config/` are classified by owner and freshness policy:

| File | Classification | Policy |
| :--- | :--- | :--- |
| `locations.json` | Durable location registry | Hand-authored location, station, settlement, and source-plan facts. Volatile market-event fields are not stored here. |
| `location_market_events.json` | Generated snapshot | Current Gamma API active-event metadata by location, with a generation envelope binding exact registry bytes; stale after 7 days. |
| `markets.json` | Deprecated compatibility shell | Empty external override file retained for `weather.market.market_registry`; built-in `MarketSpec` definitions remain authoritative. |
| `model_variant_registry.json` | Hand-authored registry | Validate before promotion; active promoted artifacts must not point at ignored `data/` paths. |
| `supplemental_stations.json` | Hand-authored registry | Review when station provenance changes. |
| `no_market_extra_locations.json` | Local shadow registry | Active entries must be backfilled before training eligibility; evidence-free diagnostic entries are retained under `archived_locations`. |
| `storage_pressure.json` | Operator activation policy | `capture.write_order_books_long_csv=true` preserves current capture. Set it to `false` only in an operator-approved quiet window after the production dry-run; missing or invalid policy fails safe to writing the projection. |
| `international_live_execution_host.json` | Hand-authored execution-role registry | Binds one active portable Windows installation and token principal per production tip, separately identifies the dedicated capture host, and is `UNASSIGNED` until a reviewed relocation assigns both public IDs. |

Generate the current inventory:

```powershell
python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

Refresh generated market-event metadata:

```powershell
python -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json
```

On the production host, `scripts/ops/refresh_location_config.ps1` follows that
refresh with an independent live target-date validation and reports task
success only when its receipt is readable, dated today, and `PASS`. Keep the
validation after the refresh: the 07:05 paper-maker launch precedes the 09:30
daily chain that otherwise produces this gate.

Event and location counts are volatile. Read the generated JSON or run the
inventory command for current values rather than copying them into prose.

## Location configuration generations

`weather.market.location_config` owns the read-only pair contract. The existing
`location_market_events_v0.1` root remains compatible with metadata-only readers;
its additive `location_config_generation` envelope binds the exact registry
bytes (base64 and SHA-256), the source input registry hash, a portable source
identity, the canonical event payload hash and a deterministic generation ID.
The root repeats that ID so a partially removed envelope is invalid. The nested
schema is registered as `location_config_generation`.

A refresh captures the registry input bytes and previous metadata bytes before
fetching. Immediately before publication it acquires the existing OS pathname
transaction lock and rechecks both inputs; a changed input refuses the stale
producer. The writer flushes and fsyncs a complete temporary file, closes it
before Windows replacement, retains the existing bounded retries for transient
Windows sharing conflicts, atomically replaces the metadata envelope, and only
then rechecks the source registry again before optionally replacing its flat
projection. An intervening registry edit refuses that projection and preserves
the committed envelope. The lock serializes cooperating publishers; these
checks cannot exclude an arbitrary editor racing after the final check. POSIX
also fsyncs the parent directory. Temporary files are cleaned up after failure; the persistent
transaction lock must not be removed while writers can be active.

The metadata replacement is the commit point, including the first migration
from legacy files. If registry projection replacement fails afterward, the new
envelope still contains a complete pair. Generation-aware readers consume one
captured metadata buffer and its embedded registry, even when the separate
registry file differs or is absent. Inventory reports that projection as
`DRIFT` or `MISSING`; review the flat file and rerun the refresh to publish the
intended source. A manual registry edit takes effect for paired consumers only
after a successful refresh. A failure exit does not prove that no generation
was committed.

`--metadata-only` embeds the exact original registry bytes and never rewrites
the input file, preserving BOM, CRLF, spacing and non-ASCII text. Explicit
`--locations` and `--event-metadata` paths are supported on one volume. Source
identity is relative to the metadata directory and contains no absolute host
path; readers compare it with the requested pair and never open an embedded
path. The two paths must differ.

The pair reader returns `GENERATION_BOUND` only after validating the complete
envelope and hashes. With no generation fields, historical object payloads are
`LEGACY_UNBOUND`; inventory warns that consistency is unproved. The legacy
read captures the registry and then rereads metadata, including whether the
metadata file was absent. It returns legacy only when that metadata observation
is unchanged. If a valid first generation appeared meanwhile, it returns that
complete embedded pair; a change to another legacy payload refuses the read.
A partial, malformed or mismatched generation is an error and never becomes
legacy fallback, including on this second read. This detects migration by the
cooperating publisher; unchanged legacy files still provide no generation
binding. Missing legacy files may be treated as empty only by diagnostic
callers that explicitly opt in. Pair binding does not establish freshness,
event correctness, settlement-source equivalence or economic qualification.

Event validation and market-expansion scoring use this reader. Invalid pairs
produce explicit per-market `BLOCK` validation results with `INVALID` binding
and skip live fetching, so the CLI and daily chain replace any retained prior
`PASS` receipt. Candidate freezing copies its exact captured registry and metadata buffers into the
existing two config roles without JSON reserialization. The candidate and
independent release verifiers rehash those buffers against their trusted outer
role inventory, validate cross-binding, and compare the declared pair identity.
Frozen buffers are verified without following their original source path, so
release relocation preserves the binding. Older frozen legacy pairs remain
explicitly unbound. Metadata-only capture and economics readers retain their
existing root fields; they do not acquire a paired-registry guarantee merely
because an envelope is present.

## Update this file when

Update when a checked-in config file is added, removed, reclassified, changes
owner, or changes generation/freshness policy. The agent-doc audit fails when a
checked-in `config/*.json` file is missing from the table above.
