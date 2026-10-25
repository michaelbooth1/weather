"""Schema records for the MG-2 composite binding: ``weather.calibration.mg2_composite``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaLiteralExclusion, SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "mg2_rule",
        "mg2_rule_v1",
        "weather.calibration.mg2_composite",
        "active",
        "Fenced binding block of the MG-2 pre-registered rule: bound input, state and release hashes.",
    ),
)

EXCLUDED_SCHEMA_LITERALS = (
    SchemaLiteralExclusion(
        "nbm_v2",
        "weather.reporting.scorecards.free_source_candidates.l4_blend_candidate",
        "column_identifier",
        "Blend-candidate member column name for the NBM v2 parser mean, not a serialized artifact schema.",
    ),
)
