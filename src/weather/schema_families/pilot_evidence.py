"""Independent public pilot capture/export record envelope."""
from weather.schema_registry_types import SchemaSpec

SCHEMAS = (SchemaSpec(
    name="pilot_validation_evidence", version="pilot_validation_evidence_v2",
    owner="weather.market.pilot_evidence_store", status="active",
    description="Raw public response/frame envelopes, gap journals and chunk receipts.",
    supersedes=("pilot_validation_evidence_v1",),
), SchemaSpec(
    name="pilot_validation_evidence_legacy", version="pilot_validation_evidence_v1",
    owner="weather.market.pilot_evidence_store", status="legacy",
    description="Original unqualified T017 raw envelope; preserved evidence only.",
))
