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
        "Fenced binding block of Rule B-1 (MG-2 against the market): fixed constants and bound hashes.",
    ),
)
