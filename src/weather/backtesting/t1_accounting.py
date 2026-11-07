"""Independent receipt accounting for BUY/hold sessions; no simulator imports.

Cash, token quantities and economic value have different clocks. Redemption
changes cash and tokens, never profit a second time. Unknown payouts get zero
value and remain in the population. Receipt positions are mandatory evidence.
"""
from collections import defaultdict

from weather.backtesting.t1_types import ONE, ZERO, decimal_context, number, source_hash, utc


def positions(rows, tokens):
    if set(rows) != set(tokens):
        raise ValueError('position evidence must include both tokens, including zeros')
    return {token: number(rows[token]) for token in tokens}


@decimal_context
def actual_accounts(fills, wallet, tokens, *, yes_payout, session_id, epsilon=ZERO):
    """Use independently exported wallet positions, payout and redemption receipts.

    Opening inventory is deliberately unsupported: the campaign must prove flat
    nonoverlapping capital periods rather than silently replenish a fresh budget.
    Other attributed cash flows reconcile the account but are not policy profit.
    """
    opening = positions(wallet['opening_positions'], tokens)
    terminal = positions(wallet['terminal_positions'], tokens)
    ending = positions(wallet['end_positions'], tokens)
    if (any(opening.values()) or wallet['opening_open_orders'] != []
            or wallet['opening_other_positions'] != [] or wallet['opening_other_open_orders'] != []):
        raise ValueError('flat opening inventory and reservations must be independently proven')
    bought = defaultdict(lambda: ZERO)
    cost = ZERO
    for fill in fills:
        bought[tokens[0 if fill['outcome'] == 'YES' else 1]] += fill['size']
        cost += fill['size'] * fill['price']
    if terminal != {t: bought[t] for t in tokens}:
        raise ValueError('terminal wallet positions disagree with confirmed fills')
    payout = ZERO if yes_payout is None else sum(
        (bought[t] * (yes_payout if i == 0 else ONE - yes_payout) for i, t in enumerate(tokens)), ZERO)
    redeemed, redemption_credit, payment_ids = defaultdict(lambda: ZERO), ZERO, []
    last = utc(wallet['start_as_of_utc'])
    for receipt in wallet['redemptions']:
        source_hash(receipt['source_sha256'])
        if (not receipt['id'] or receipt['id'] in payment_ids or yes_payout is None
                or receipt['session_id'] != session_id or utc(receipt['at']) < last
                or utc(receipt['at']) > utc(wallet['as_of_utc'])):
            raise ValueError('invalid redemption identity, clock or unresolved payout')
        last = utc(receipt['at'])
        quantities = positions(receipt['tokens'], tokens)
        value = sum((quantities[t] * (yes_payout if i == 0 else ONE - yes_payout)
                     for i, t in enumerate(tokens)), ZERO)
        credit = number(receipt['credit'])
        if abs(value - credit) > epsilon:
            raise ValueError('redemption credit disagrees with venue payout fractions')
        for t in tokens:
            redeemed[t] += quantities[t]
        redemption_credit += credit
        payment_ids.append(receipt['id'])
    if ending != {t: bought[t] - redeemed[t] for t in tokens} or any(redeemed[t] > bought[t] for t in tokens):
        raise ValueError('end wallet positions disagree with redeemed quantities')
    fees = number(wallet['maker_fees'])
    operating = number(wallet['operating_cost'])
    rewards, rebates = number(wallet['reward_credit']), number(wallet['rebate_credit'])
    payments = wallet['payment_ids']
    if (set(payments) != {'reward', 'rebate', 'redemption'}
            or rewards > ZERO and not payments['reward'] or rebates > ZERO and not payments['rebate']
            or sorted(payments['redemption']) != sorted(payment_ids)
            or any(len(set(ids)) != len(ids) or any(not key for key in ids) for ids in payments.values())):
        raise ValueError('incentive/redemption credits require unique independently retained payment IDs')
    outside, ids = ZERO, set(payment_ids)
    for flow in wallet['other_attributed_cashflows']:
        if not flow['id'] or flow['id'] in ids or flow['session_id'] == session_id:
            raise ValueError('invalid external wallet cashflow identity')
        source_hash(flow['source_sha256'])
        ids.add(flow['id'])
        outside += number(flow['amount'], minimum=None)
    start_cash = number(wallet['start_cash'])
    cash = start_cash - cost - fees - operating + redemption_credit + rewards + rebates + outside
    remaining_value = payout - redemption_credit
    net = payout - cost - fees - operating + rewards + rebates
    cash_net = redemption_credit - cost - fees - operating + rewards + rebates
    # This second identity uses balances and residual economic assets, not the
    # fill-cost identity above. Both must reconcile to independently read cash.
    balance_net = number(wallet['end_cash']) - start_cash - outside + remaining_value
    completion_gaps = []
    if yes_payout is None and fills:
        completion_gaps.append('unresolved_inventory')
    if remaining_value != ZERO:
        completion_gaps.append('unredeemed_venue_value')
    if any(ending.values()):
        completion_gaps.append('unredeemed_token_positions')
    if wallet.get('cash_followup_complete') is not True or wallet.get('payment_scope_complete') is not True:
        completion_gaps.append('cash_or_payment_followup_incomplete')
    if wallet.get('closing_open_orders') != []:
        completion_gaps.append('closing_reservations_not_proven_empty')
    cash_events = wallet.get('cash_events', [])
    for kind, expected, payment_kind in (('REWARD', rewards, 'reward'), ('REBATE', rebates, 'rebate')):
        credits = [r for r in cash_events if r['kind'] == kind]
        if (sum((number(r['amount']) for r in credits), ZERO) != expected
                or sorted(r['id'] for r in credits) != sorted(payments[payment_kind])):
            completion_gaps.append(kind.lower() + '_payment_timing_not_reconciled')
    for row in [*cash_events, *wallet['redemptions']]:
        if (row.get('status') != 'CONFIRMED' or not row.get('finalized_at')
                or not utc(row['at']) <= utc(row['finalized_at']) <= utc(wallet['as_of_utc'])):
            completion_gaps.append('payment_or_redemption_not_final')
    cash_completion = {'status': 'COMPLETE' if not completion_gaps else 'NOT COMPLETE',
                       'gaps': sorted(set(completion_gaps)), 'net_pnl': cash_net,
                       'as_of_utc': wallet['as_of_utc']}
    return {'cost': cost, 'venue_payout': payout, 'cash_redemptions_pusd': redemption_credit,
            'unredeemed_venue_value': remaining_value, 'cash_available': start_cash - cost - fees - operating + redemption_credit,
            'wallet_end_cash': cash, 'raw_net_pnl': net, 'balance_net_pnl': balance_net,
            'cash_net_pnl': cash_net, 'cash_balance_net_pnl': number(wallet['end_cash']) - start_cash - outside,
            'economic_net_pnl': net, 'completed_cash': cash_completion,
            'maker_fees_pusd': fees, 'operating_cost': operating, 'outside_cash': outside,
            'terminal_positions': terminal, 'end_positions': ending, 'payment_ids': payment_ids,
            'opening_cash': start_cash, 'opening_positions': opening,
            'settlement_complete': yes_payout is not None or not any(bought.values())}


def predicted_positions(fills, tokens, fractions):
    bought = defaultdict(lambda: ZERO)
    for fill in fills:
        bought[tokens[0 if fill['outcome'] == 'YES' else 1]] += fill['size']
    terminal = {t: bought[t] for t in tokens}
    ending = ({t: bought[t] - fractions.get(t, ZERO) for t in tokens} if isinstance(fractions, dict)
              else {t: bought[t] * (ONE - fractions) for t in tokens})
    return terminal, ending
