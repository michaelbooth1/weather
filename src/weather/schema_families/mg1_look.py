"""Schema records for the MG-1 confirmation look: ``weather.calibration.mg1_look``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "mg1_look_receipt",
        "mg1_look_receipt/1",
        "weather.calibration.mg1_look",
        "active",
        "MG-1's look receipt, written once (mode x) at data/mg1_look/receipt-<mg1_rule_sha256>.json by the "
        "registered MG-1 look entry point: entry point and source sha, rule sha, window, dates scored, the "
        "code-stamped looked_at_utc, completion time, result sha, mg1.py sha, commit, host and body_sha256. "
        "Rule B-1 reads it first and checks it in VOID 5.",
    ),
    SchemaSpec(
        "mg1_look_started",
        "mg1_look_started/1",
        "weather.calibration.mg1_look",
        "active",
        "MG-1 look start marker, written once (mode x) at data/mg1_look/started-<mg1_rule_sha256>.json "
        "immediately before the look's first outcome join; it records looked_at_utc and refuses a second look.",
    ),
)
