"""Schema records for the B-1 coverage counts and drop list (master ruling R19, B-1 Clarification 4).

Producers: the capture-host counts tool under ``tools/research/`` (run by ``scripts/ops``; master ruling R19
option b keeps it out of ``src/``) and ``weather.calibration.b_drop_list`` (workstation: log, verdict,
materialize). The sidecar record's name is ``b_coverage_sidecar``; its version literal is the only place under
``src/`` that names the host tool (a test pins this).

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "b_coverage_sidecar",
        "b_price_coverage/1",
        "tools.research.b_price_coverage",
        "active",
        "Per-date integers-only coverage sidecar beside the MG-2 input bundles (_b_coverage/<D>.json plus "
        "<D>.SHA256SUMS): per snapshot [rows, rows with an admitted capture-time price], the source byte "
        "ranges, the re-projected snapshots_long sha256 and whether it matches the bundle. No price value.",
    ),
    SchemaSpec(
        "b_coverage_receipt",
        "b_coverage_receipt/1",
        "weather.calibration.b_drop_list",
        "active",
        "Append-only workstation ledger rows (b_coverage_receipts.jsonl): one log row per verified sidecar and "
        "one verdict row per date, fixed once and never recomputed.",
    ),
    SchemaSpec(
        "b_drop_list",
        "b_drop_list/1",
        "weather.calibration.b_drop_list",
        "active",
        "The B-1 section 3 coverage drop list: the logged verdicts of exactly the concatenated look window's "
        "dates, written create-only before MG-2 score and read by b_scorer look as --drop-list.",
    ),
)
