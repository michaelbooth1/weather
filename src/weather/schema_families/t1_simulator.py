"""Offline T1 reports; no capture loop imports this schema family."""
from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec('t1_simulator_report', 't1_simulator_report_v1', 'weather.backtesting.t1_cli', 'active',
               'Explicit-input simulator or pilot accuracy report, code/input hashes and non-verdict status.'),
    SchemaSpec('t1_pinned_lfc_journal', 'mm_stage2_hold_v0.1', 'weather.backtesting.t1_accuracy', 'active',
               'Read-only wire contract of HoldJournal at the task LFC pin; no new journal writer.'),
    SchemaSpec('t1_pinned_lfc_cap_ledger', 'lfc_l_ledger_v0.1', 'weather.backtesting.t1_accuracy', 'active',
               'Read-only Ledger.snapshot wire contract at the task LFC pin; not a cash-balance projection.'),
)
