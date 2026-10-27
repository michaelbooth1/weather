"""Schema records for the MG-3 release binding: ``weather.calibration.pooled_residual_model``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "mg3_release_binding_legacy",
        "mg3_release_binding/1",
        "weather.calibration.pooled_residual_model",
        "legacy",
        "MG-3 release-binding.json before clarification 0712-1: rules, RN-1, data and code files, states and an "
        "unverified flat weights_sha256; no L6 partner.",
        migration_notes="Superseded by mg3_release_binding/2 (0712-1, f9e25a90). Not readable as /2: rebuild with "
        "mg3-release-binding from verified weights and L6 partner files; never edit a /1 file into /2.",
    ),
    SchemaSpec(
        "mg3_release_binding",
        "mg3_release_binding/2",
        "weather.calibration.pooled_residual_model",
        "active",
        "MG-3 release-binding.json written by mg3_release_binding from verified loads: rules (incl. 0712-1), RN-1, "
        "data and code files, states, weights_sha256 (RF-1) and l6_partner {state_sha256, part_sha256, "
        "nowcasts_sha256}, the shape mg3_serve reads.",
        supersedes=("mg3_release_binding/1",),
        migration_notes="/1 bindings carry no l6_partner and an unverified weights sha; /2 refuses them at "
        "mg3_verify_release.",
    ),
)
