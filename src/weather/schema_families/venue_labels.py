"""Schema family for the venue-label reader (training, evaluation, B/MG-2 label transfer)."""

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
)
