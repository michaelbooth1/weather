"""Schema records for master ruling (b)'s post-look serial-correlation analysis: ``weather.calibration.b_post_look_serial``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "b_post_look_serial",
        "b_post_look_serial_v1",
        "weather.calibration.b_post_look_serial",
        "active",
        "Descriptive post-look serial-correlation report on B's forward per-date data (lag-1 rho, VIF, U_adj "
        "and the fragile labels); it never alters B's verdict.",
    ),
)
