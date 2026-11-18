"""Schema records for a look's capture-time --market file (master rulings 2026-11-03 on --market, MG-1 and B).

Producers: the capture-host price tool under ``tools/research/`` (``capture_price_export``, kept out of ``src/``
like R19's counts tool) and ``weather.calibration.mg1_market`` (the host concat). Both are registered steps of a
look path: they run on the capture host on the look morning, and their records carry counts, shas and booleans
only, never a price value.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "capture_price_export_receipt",
        "capture_price_export/1",
        "tools.research.capture_price_export",
        "active",
        "Per-date counts-only receipt beside the host's <D>.prices.csv (<D>.capture_prices.json, then "
        "<D>.SHA256SUMS last): the look id, per market the snapshot, row, priced, out-of-range and unkeyed counts, "
        "the R19 sidecar cross-check (or none_before_r19, disclosed) and the shas. No price value.",
    ),
    SchemaSpec(
        "mg1_market_manifest",
        "mg1_market/1",
        "weather.calibration.mg1_market",
        "active",
        "The manifest beside a look's market.parquet (mg1_market_manifest.json, mode x, written last): the look "
        "id, the layout and market shas, per date the price file shas and cross-check, the counts, and range_ok "
        "and duplicate_free (both true; mg1_look's pre-stamp check requires them). No price value.",
    ),
)
