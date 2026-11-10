"""LOW-ASK-1 offline paper input and sealed-receipt schema ownership."""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec("low_ask_inputs", "low_ask_inputs_v1", "backtesting.low_ask", "active",
               "Closed cumulative captured-input manifest; INPUT_CONTRACT.md owns fields."),
    SchemaSpec("low_ask_rows", "low_ask_rows_v1", "backtesting.low_ask", "active",
               "Received-time event, observation, book, heartbeat, resolution and integrity rows."),
    SchemaSpec("low_ask_freeze", "low_ask_freeze_v1", "backtesting.low_ask", "active",
               "Master-bound code/prereg/input-contract/custody and prerequisite freeze."),
    SchemaSpec("low_ask_receipt", "low_ask_receipt_v1", "backtesting.low_ask", "active",
               "Public hashes/coverage only; sealed economic ledger is separate."),
    SchemaSpec("low_ask_calibration", "low_ask_calibration_v1", "backtesting.low_ask_calibration", "active",
               "Synthetic-only arm and aggregate size/power calibration receipts."),
)
