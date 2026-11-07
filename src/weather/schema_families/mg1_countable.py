"""Schema records for MG-1 countability, counts-only: ``weather.calibration.mg1_countable`` (R11 Head 2).

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core. The final list it writes is
``mg1_countable/2``, registered by the ``mg1_look`` family (its reader and writer).
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "mg1_countable_report",
        "mg1_countable_report/2",
        "weather.calibration.mg1_countable",
        "active",
        "MG-1 countability report mode (R11 P1/P2), printed to stdout: per calendar date from D0 its status only "
        "(countable, non_countable, pending), the required MG1_LAST, whether the recorded MG1_LAST must move, "
        "each market ledger's sha256, the frozen label receipt sha and the run time. Primary mask: admitted coverage, "
        "closed/one winner and frozen label key (Clarification 4). B015 countability_disclosures gives integer "
        "manual_override admissions and missing_settlement-only exclusions over the first up to 45 counted "
        "dates; countability_disclosure_dates states how many are available. Reporting only. "
        "Nothing per market; no label, price or settlement value.",
    ),
    SchemaSpec(
        "mg1_countable_report_v1_legacy",
        "mg1_countable_report/1",
        "weather.calibration.mg1_countable",
        "legacy",
        "Former promotion-selected countability report; retained for historical artifact identification only.",
    ),
)
