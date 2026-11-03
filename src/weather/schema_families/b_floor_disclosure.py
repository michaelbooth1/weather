"""Schema records for B-1's post-look floor-zeroed-band disclosure: ``weather.calibration.b_floor_disclosure``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "b_floor_disclosure",
        "b_floor_disclosure_v1",
        "weather.calibration.b_floor_disclosure",
        "active",
        "Descriptive, non-deciding post-look disclosure of B cells whose paying band the rule-4 floor zeroed (any "
        "cause), Delta(07-16) without them, and SPECI attribution only from a flag in B's bytes.",
    ),
    SchemaSpec(
        "b_floor_disclosure_receipt",
        "b_floor_disclosure_receipt_v1",
        "weather.calibration.b_floor_disclosure",
        "active",
        "Receipt of the B floor disclosure: module sha, B look and receipt shas, and the B input shas it read.",
    ),
)
