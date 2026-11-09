"""Owner B060 sleeve arithmetic, independent of transport and ledger mutation.

Gains can offset losses/costs; they never enlarge the principal-risk ceiling.
Only the capital replay's proved campaign redemption/incentive grants qualify.
"""

GROSS = 'gross'
NET = 'net_of_retained_gains'
BASES = frozenset((GROSS, NET))


def retained_gains(movements, *, profit_pool, unknown):
    """Conservative chronological ownership of eligible gains, in native units.

    All non-campaign outflows consume gains first, regardless of other owner
    cash. A same-second debit may follow any credit, so consume credits first.
    Deposits, unproved labels, accruals and unallocated incentives are excluded.
    The caller passes only unknown outgoing/campaign-redemption blockers;
    unrelated unknown incoming amounts contribute zero without erasing gains.
    """
    cumulative = retained = 0
    for move in sorted(movements, key=lambda m: (m['timestamp'], m['kind'] != 'credit', m['sequence'])):
        if move['kind'] == 'credit':
            cumulative += move.get('proven_campaign_gain_native', 0)
            retained += move.get('proven_campaign_gain_native', 0)
        elif move['kind'] == 'withdraw':
            retained = max(0, retained - move['amount'])
    return cumulative, (0 if unknown else min(retained, cumulative, profit_pool))


def sleeve_charge(*, loss, inventory, resting, costs, available_gains, basis):
    if not isinstance(basis, str) or basis not in BASES:
        raise ValueError('capital_loss_basis')
    offset = min(loss + costs, available_gains) if basis == NET else 0
    return inventory + resting + loss + costs - offset, offset
