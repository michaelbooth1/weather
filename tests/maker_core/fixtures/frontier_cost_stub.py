"""A real recording fill-cost provider over a synthetic toxicity table, for frontier scored-mode gate tests.

A scored frontier run requires exactly ``adapters.RecordingFillCost`` (round 4; a duck-typed provider is refused)
and binds its ``table_digest`` to the registration's ``Toxicity table:`` line. Tests of the other gates pass
``SCORED_COST`` so they reach the gate they test. The table is fitted from the fictional
``toxicity_synthetic`` records; no real table is read.
"""
from maker_core.frontier.adapters import RecordingFillCost
from maker_core.quoting.fill_cost import TableFillCostProvider
from maker_core.replay import toxicity as tx

from .toxicity_synthetic import synthetic_records


def recording_cost(seed=11):
    provider = TableFillCostProvider(tx.fit(*synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=seed),
                                            replicates=100))
    return RecordingFillCost(provider, expected_table_digest=provider.digest)


def _no_context(**_):
    return None


_COST = recording_cost()
STUB_TABLE_DIGEST = _COST.table_digest
SCORED_COST = dict(cost_provider=_COST, context_builder=_no_context)
TOXICITY_LINE = "Toxicity table: `%s`\n" % STUB_TABLE_DIGEST


class DuckTable:
    """Carries a table digest and an ``estimate`` but is not the recording adapter: refused since round 4."""

    def __init__(self, table_digest=STUB_TABLE_DIGEST):
        self.table_digest = table_digest

    def estimate(self, context):
        return None
