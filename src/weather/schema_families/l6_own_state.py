"""Schema records for the frozen L6 own-model state: ``weather.model.mg_serve_core``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "l6_own_state",
        "l6_own_state/1",
        "weather.model.mg_serve_core",
        "active",
        "Pickled frozen L6 own-model state (schema, the L6 OWN columns, a fitted HGB, provenance), written by "
        "weather.calibration.l6_own_state and loaded only at its bound file sha256 by "
        "mg_serve_core.load_l6_own_state (MG-2 pre-13 arm; Rule B-1 l6_state_sha256).",
    ),
)
