"""A fill-cost provider stand-in that carries a table digest, for frontier scored-mode gate tests.

A scored frontier run refuses the constant stand-in or no provider (``scored_requires_fill_cost_table``) and binds
the provider's ``table_digest`` to the registration's ``Toxicity table:`` line. Tests of the other gates pass
``SCORED_COST`` so they reach the gate they test. It is fictional; no table is read.
"""
STUB_TABLE_DIGEST = "7" * 64


class TableStub:
    table_digest = STUB_TABLE_DIGEST

    def estimate(self, context):
        return None


def _no_context(**_):
    return None


SCORED_COST = dict(cost_provider=TableStub(), context_builder=_no_context)
TOXICITY_LINE = "Toxicity table: `%s`\n" % STUB_TABLE_DIGEST
