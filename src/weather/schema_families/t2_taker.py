"""Schema records for T2's taker rule (WS-3 early-warning kill-only read and T2, same module sha).

Producer: ``weather.backtesting.t2_taker_rule`` (workstation, research-only, create-only outputs).
Pre-registration: ``docs/research/ws3-early-warning-prereg-2026-11-06.md`` sections 2-3.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "t2_taker_rule_input_manifest",
        "t2_taker_rule_input_manifest_v1",
        "weather.backtesting.t2_taker_rule",
        "active",
        "Written before any settlement is read: module sha256, arms, window, exclusions, latency, every input "
        "path with its sha256, book row counts (read and unusable), per-event decision-row coverage and the "
        "countable-before-settlement reason per market-day.",
    ),
    SchemaSpec(
        "t2_taker_rule_summary",
        "t2_taker_rule_summary_v1",
        "weather.backtesting.t2_taker_rule",
        "active",
        "Per arm: equal-weight mean net pUSD per countable market-day, the two bootstrap bounds and the wider "
        "upper bound U, filled entries and the KILL / NOT_KILLED / UNTESTABLE outcome; skip counts; the paired "
        "arm difference, descriptive only.",
    ),
    SchemaSpec(
        "t2_taker_rule_receipt",
        "t2_taker_rule_receipt_v1",
        "weather.backtesting.t2_taker_rule",
        "active",
        "Create-only single-look receipt: module sha256, start and finish times, the sha256 of every other "
        "output and the per-arm outcomes. A second run into the same folder refuses.",
    ),
)
