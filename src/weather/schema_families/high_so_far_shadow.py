"""Schema records for the high_so_far parity shadow (lane L8): ``weather.model.observed_running_max``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "metar_running_max_since_midnight",
        "metar_running_max_since_midnight_v1",
        "weather.model.observed_running_max",
        "active",
        "Shadow high_so_far variant: running max of the station and METAR rows since local midnight at the cutoff.",
    ),
)
