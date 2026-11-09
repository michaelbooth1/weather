"""Offline F3 policy configuration schemas; no capture-loop imports."""
from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec("f3_policy", "f3_policy_v1", "weather.market.f3_types", "active",
               "Pure T5-R simulation policy configuration and reconciled cash contract."),
    SchemaSpec("f3_strata", "f3_strata_v1", "weather.market.f3_types", "active",
               "Predeclared F3 transfer cells, arm cities, regions and geographic clusters."),
    SchemaSpec("f3_nwp_release_schedule", "f3_nwp_release_schedule_v1", "weather.market.f3_types", "active",
               "Offline NWP availability schedule with lengthen-only blackout windows."),
)
