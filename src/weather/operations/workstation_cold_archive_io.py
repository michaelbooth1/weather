"""Local archive verification rate for already admitted non-capture workflows.

Production entry points never select this factory. Workstation entry points
prove their assignment and wrapper before calling it; their admission callback
rechecks that authority throughout every read.
"""
from weather.operations.production_cold_archive_stage import _Guard, MIB

READ_BYTES_PER_SECOND = 64 * MIB
NETWORK_BUDGET_BYTES_PER_SECOND = 2 * MIB


class ReadGuard(_Guard):
    MAX_RATE = READ_BYTES_PER_SECOND

    def __init__(self, admission, deadline):
        super().__init__(admission, deadline, READ_BYTES_PER_SECOND)
