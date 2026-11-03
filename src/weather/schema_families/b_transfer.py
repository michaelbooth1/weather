"""Schema records for Rule B-1's outcome transfer writer: ``weather.calibration.b_transfer``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "b_transfer_sidecar_override",
        "b_transfer_sidecar_override/1",
        "weather.calibration.b_transfer",
        "active",
        "Master's dated, outcome-blind release of R19 coverage-sidecar match flags that are false (master ruling "
        "2026-11-03 on the b_transfer writer, item 4): dated, outcome_blind true, and releases [{date, flag, "
        "reason}]. Each named (date, flag) pair is released; any other false flag holds the transfer. Its sha256 "
        "is pinned in the transfer manifest. No label, price or outcome.",
    ),
    SchemaSpec(
        "b_transfer_refusal",
        "b_transfer_refusal/1",
        "weather.calibration.b_transfer",
        "active",
        "The transfer's post-read refusal record (<out>.refusal.json, mode x): a label read the pre-read R24 "
        "metadata did not predict, or a snapshot no band maps to its label. Per entry date, market and reason "
        "only, never a value; nothing is published and master rules on it.",
    ),
)
