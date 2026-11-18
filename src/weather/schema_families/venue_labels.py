"""Schema family for the venue-label reader (training, evaluation, B/MG-2 label transfer) and the
forward-look label refresh, freeze and audit (``weather.backtesting.venue_label_audit`` and
``weather.backtesting.venue_label_freeze``, R24)."""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "venue_label_record",
        "venue_label_record_v1",
        "weather.backtesting.venue_label_reader",
        "active",
        "One market-date label as the venue resolves it: WU before the venue-rule cutover, the venue "
        "rule (routine METAR, WU fallback) from it, with policy, source, station and input hashes.",
    ),
    SchemaSpec(
        "venue_label_refresh_receipt",
        "venue_label_refresh_receipt_v1",
        "weather.backtesting.venue_label_audit",
        "active",
        "One forward-look label refresh run (R24), data/venue_rule_labels/runs/<utcRunId>/refresh_receipt.json: "
        "window, events and station-config snapshot shas, stations, per-fetch shas and bytes, per-market output, "
        "manifest and WU summary shas, label-source counts and skipped-date counts. No label value.",
    ),
    SchemaSpec(
        "venue_label_freeze_receipt",
        "venue_label_freeze_receipt_v1",
        "weather.backtesting.venue_label_freeze",
        "active",
        "A look-morning label freeze (R24), data/venue_rule_labels/frozen/<look>/freeze_receipt.json: the run and "
        "audit it froze (only an OK audit is frozen), the ignored partial tmp folders, and per market the frozen "
        "CSV, manifest and WU daily summary paths and shas. Written in a tmp folder and renamed once verified "
        "(master 2026-11-03). No label value.",
    ),
    SchemaSpec(
        "venue_label_freeze_recovery_ruling",
        "venue_label_freeze_recovery_ruling_v1",
        "weather.backtesting.venue_label_freeze",
        "active",
        "Master's dated, outcome-blind ruling that releases one defective frozen look folder for recovery "
        "(freeze --recover, master 2026-11-03 item 2(c)): schema_version, dated, outcome_blind true, look_id and "
        "reason. Read, never written, by the module. No label, price or outcome.",
    ),
    SchemaSpec(
        "venue_label_freeze_recovery",
        "venue_label_freeze_recovery_v1",
        "weather.backtesting.venue_label_freeze",
        "active",
        "The record of one freeze recovery, frozen/<look>.void-<utc>/recovery_record.json (mode x): the look id, "
        "the moved and new paths, the defects (no readable receipt, null shas), the ruling path and sha256 and the "
        "time. Written only while no stamp or receipt of the look exists. No label value.",
    ),
    SchemaSpec(
        "venue_label_audit",
        "venue_label_audit_v1",
        "weather.backtesting.venue_label_audit",
        "active",
        "The counts-only audit of one refresh run (R24): STATION_DRIFT rows and per-market counts of label "
        "sources, skipped dates, predicted reader refusals, thin and body-basis rows, Denver KDEN rows and "
        "pre-cutover pass-through mismatches. No label value, bucket or winner.",
    ),
)
