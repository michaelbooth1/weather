"""Schema records for item 343b's offline year-round refit: ``weather.calibration.yearround_refit``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

_OWNER = "weather.calibration.yearround_refit"

SCHEMAS = (
    SchemaSpec(
        "yearround_refit_fit_manifest",
        "yearround_refit_fit_manifest/1",
        _OWNER,
        "active",
        "Value-free manifest of row 28 candidate B's frozen forward state (state, sidecar and upstream shas, "
        "training row-key and bucket-space shas, centres, windows, versions, archive path).",
    ),
    SchemaSpec(
        "yearround_refit_shadow_receipt",
        "yearround_refit_shadow_receipt/1",
        _OWNER,
        "active",
        "Receipt of one weekly as-of-capture shadow emission batch of candidate B (input shas, window, counts "
        "and shadow_rows_sha256; no label or price).",
    ),
    SchemaSpec(
        "yearround_refit_equivalence",
        "yearround_refit_equivalence/1",
        _OWNER,
        "active",
        "Equivalence report of the module against the frozen row-28 v12 runner: PASS or FAIL, counts and "
        "max abs differences only.",
    ),
    SchemaSpec(
        "yearround_refit_forward_receipt",
        "yearround_refit_forward_receipt/1",
        _OWNER,
        "active",
        "Owner-approved forward embargo-line record that emit requires (state and fit-manifest shas, forward "
        "prereg sha, window, approval record).",
    ),
    SchemaSpec(
        "yearround_refit_records_manifest",
        "yearround_refit_records_manifest/1",
        _OWNER,
        "active",
        "Records-root manifest of the bound extract_market windows (file and decompressed-payload shas, "
        "fail-closed extracts, covered years).",
    ),
)
