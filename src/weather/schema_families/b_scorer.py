"""Schema records for the Rule B-1 forward edge test scorer: ``weather.calibration.b_scorer``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "b_rule",
        "b_rule_v1",
        "weather.calibration.b_scorer",
        "active",
        "Fenced binding block of Rule B-1 (MG-2 against the market): fixed constants and bound hashes "
        "(including the frozen L6 own-model state sha256, l6_state_sha256).",
    ),
    SchemaSpec(
        "b_look_consumed",
        "b_look_consumed/1",
        "weather.calibration.b_scorer",
        "active",
        "Consumed-look marker written (mode x) when the single B-1 look starts: at the fixed "
        "data/b_look/consumed-<rule_sha256>.json and beside the transfer manifest and mg2_look.json.",
    ),
    SchemaSpec(
        "b_void_record",
        "b_void_record/1",
        "weather.calibration.b_scorer",
        "legacy",
        "Retired operator-written VOID record (MG-2 void conditions, pre-look reads).",
        migration_notes="Retired 2026-10-26: VOIDs 1 and 4 read mg2.score's recorded section 7 results and "
        "pre-look reads from mg2_look.json; the scorer no longer reads a void record.",
    ),
)
