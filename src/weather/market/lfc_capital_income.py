"""Amount-local quarantine; an activity condition is not income attribution."""


def campaign_income(book, activity, *, native_proven):
    """No current retained source proves the complete earning-order population.

    v2 activity has neither the earning period nor order-level attribution.
    CLOB earnings have a date, but no binding of that accrual to a paid row;
    CLOB /data/orders is open-only, not complete cancelled-order history.
    Native cash and a prior campaign intent prove neither missing fact. Until
    a supported complete own-order-history proof is supplied, these payments
    remain unknown incoming and contribute zero, never a guessed period or a
    caller's 'complete' boolean. This does not disable redeemed-lot gains.
    """
    return False


def unknown_cash(book):
    blockers, reasons, incoming, unbounded = [], set(), 0, 0
    for key in book.unknown:
        activity = book.activities[key]
        if not book.incoming(activity):
            blockers.append(key); reasons.add('unknown_outgoing_cash')
            continue
        amount = book.incoming_quarantines.get(key, {}).get('amount', activity['cash_native'])
        if amount is None:
            unbounded += 1
        else:
            incoming += amount
        if activity.get('native_redemption') is not None and activity['cash_native'] is not None:
            # A known per-position payout can leave an unrelated owner's
            # inventory unallocated. Only an unproved campaign token blocks G.
            refused_tokens = {str(row['token_id']) for row in book.redemptions[key].get('unallocated', [])}
            campaign_redemption = any(str(lot['token_id']) in refused_tokens for lot in book.lots.values())
        else:
            campaign_redemption = (activity['type'] == 'REDEEM' and any(
                str(lot['condition_id']).lower() == activity['condition_id'] or str(lot['token_id']) == activity['token_id']
                for lot in book.lots.values()))
        if campaign_redemption:
            blockers.append(key); reasons.add('unknown_campaign_redemption')
        elif activity['type'] == 'REDEEM' and not activity['condition_id'].strip('0x'):
            blockers.append(key); reasons.add('unknown_redemption_scope')
        else:
            reasons.add('reward_attribution_unproven' if activity['type'] in {'REWARD', 'MAKER_REBATE'}
                        else 'unknown_incoming_excluded')
            reasons.add('unknown_incoming_excluded')
    return {'blockers': blockers, 'reasons': sorted(reasons),
            'held_native': None if unbounded else incoming,
            'bounded_native': incoming, 'unbounded_count': unbounded}
