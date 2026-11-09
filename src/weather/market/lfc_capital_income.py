"""Amount-local unknown cash and native, condition-scoped campaign income.

Official activity type/condition labels retain the capital rail's existing
source contract. A label alone never proves cash; the existing native receipt
must reconcile the amount before an incentive can contribute any gain.
"""
from weather.market.lfc_ledger_queries import event_rows
from weather.market.mm_stage2_hold import utc


def campaign_income(book, activity, *, native_proven):
    if not native_proven or activity['type'] not in {'REWARD', 'MAKER_REBATE'}:
        return False
    condition = activity['condition_id']
    if not condition or not condition.strip('0x'):
        return False
    # Bind to a prior durable intent, not to a later selection or another
    # wallet's market. A whole-second timestamp cannot prove a same-second
    # reward followed our first quote, so such a payment remains segregated.
    return any(str(row['condition_id']).lower() == condition and
               row['sequence'] < book.activity_sequences[activity['id']] and
               utc(row['recorded_at_utc']).timestamp() < activity['timestamp']
               for row in event_rows(book.ledger, 'leg_intent'))


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
            reasons.add('unknown_incoming_excluded')
    return {'blockers': blockers, 'reasons': sorted(reasons),
            'held_native': None if unbounded else incoming,
            'bounded_native': incoming, 'unbounded_count': unbounded}
