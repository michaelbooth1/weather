"""Schema records for the MG-2 composite binding: ``weather.calibration.mg2_composite``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "mg2_rule",
        "mg2_rule_v1",
        "weather.calibration.mg2_composite",
        "active",
        "Fenced binding block of the MG-2 pre-registered rule: bound input, state and release hashes.",
    ),
    SchemaSpec(
        "mg2_release_binding",
        "mg2_release_binding/1",
        "weather.calibration.mg2_composite",
        "active",
        "release-binding.json written by mg2_composite bind-release from verified loads: rule, function, "
        "coefficient part, P3d_N state and L6 state sha256s, the release file hashes and the build commit.",
    ),
)
