"""Offline T1 reports; no capture loop imports this schema family."""
from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec('t1_simulator_report', 't1_simulator_report_v3', 'weather.backtesting.t1_cli', 'active',
               'Financial component comparisons, partial F0 intake, raw evidence certificate and non-verdict status.'),
    SchemaSpec('t1_pinned_lfc_journal', 'mm_stage2_hold_v0.1', 'weather.backtesting.t1_accuracy', 'active',
               'Read-only wire contract of HoldJournal at the task LFC pin; no new journal writer.'),
    SchemaSpec('t1_pinned_lfc_cap_ledger', 'lfc_l_ledger_v0.1', 'weather.backtesting.t1_accuracy', 'active',
               'Read-only Ledger.snapshot wire contract at the task LFC pin; not a cash-balance projection.'),
    SchemaSpec('t1_pinned_lfc_history_legacy', 'lfc_ledger_v0.1', 'weather.backtesting.t1_provenance', 'active',
               'Read-only legacy ledger history wire version accepted by the reviewed F0 writer.'),
    SchemaSpec('t1_pinned_lfc_history', 'lfc_ledger_v0.2', 'weather.backtesting.t1_provenance', 'active',
               'Read-only ledger history including leg adoption; no live ledger import or mutation.'),
    SchemaSpec('t1_first_book_pair_policy', 'first_book_pair_v1', 'weather.backtesting.t1_policy', 'active',
               'Deterministic fixed-eligibility first-available-book proposal and decision lineage.'),
    SchemaSpec('t1_raw_projection', 't1_raw_projection_v1', 'weather.backtesting.t1_raw_projection', 'active',
               'Role-specific retained raw snapshots, activity and deterministic financial verification receipt.'),
)
