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
        "code-stamped looked_at_utc, completion time, result sha, mg1.py sha, commit, host, the R24 label "
        "freeze receipt sha, the raised flags (label_refusal_unpredicted_by_metadata) and body_sha256. "
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
    SchemaSpec(
        "mg1_look_result",
        "mg1_look_result/1",
        "weather.calibration.mg1_look",
        "active",
        "MG-1's single look result (pre-registration sections 4 and 6), written once (mode x) as "
        "mg1_look_result.json under the look's --out and bound by sha256 in the look receipt: counted dates, "
        "outcome-blind VOID checks, the primary 00-16 MG-1 minus served estimate and interval, the decision and "
        "every reported quantity.",
    ),
    SchemaSpec(
        "mg1_countable",
        "mg1_countable/1",
        "weather.calibration.mg1_look",
        "active",
        "The MG-1 look's countable-date list, written once by master (write_countable) before the look: one row "
        "per calendar date from D0 through the 45th promotion-countable date, with per-market promotion_countable "
        "flags over the support (markets; a date counts iff one does, MG-1 Clarification 2 A3) and the "
        "Clarification 1 reporting caveats (null with a text reason allowed). No label or price.",
    ),
    SchemaSpec(
        "mg1_check_keys",
        "mg1_check_keys/1",
        "weather.calibration.mg1_look",
        "active",
        "The MG-1 look's dry pre-stamp check record (main check-keys, master ruling 2026-11-03), written once "
        "(mode x) at its --out for every outcome: verdict pass/held/refused with the reason text, owner constants, "
        "countable and freeze shas, the freeze's through, frozen_at_utc and audit_status, and the label-key "
        "counts. It never stamps, never joins and carries no label, price or outcome.",
    ),
)
