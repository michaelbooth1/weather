"""Independent derived-net identities; component allowances never relax these."""
from weather.backtesting.t1_types import number

CASH_CEILING = '.00001'


def cash_limit(tolerance):
    return min(number(CASH_CEILING), number(tolerance['cash_conservation_absolute']),
               number(tolerance['receipt_reconciliation_absolute']))


def net_checks(simulation, accounts, economics, rewards, rebates, opening_cash, tolerance, completed_cash=None):
    """Recompute formulas and compare net amounts, also at persisted consumption."""
    limit = cash_limit(tolerance)

    def check(predicted, actual):
        predicted, actual = number(predicted, minimum=None), number(actual, minimum=None)
        error = abs(predicted - actual)
        return {'predicted': predicted, 'actual': actual, 'absolute_error': error, 'limit': limit, 'pass': error <= limit}

    s = {k: number(simulation[k], minimum=None) for k in ('cost', 'venue_payout', 'cash_redemptions_pusd',
        'unredeemed_venue_value', 'maker_fees_pusd', 'operating_cost', 'reward_payable', 'rebate_payable',
        'raw_net_pnl', 'economic_net_pnl', 'cash_net_pnl', 'cash_available', 'wallet_end_cash')}
    charges = s['cost'] + s['maker_fees_pusd'] + s['operating_cost']
    income = s['reward_payable'] + s['rebate_payable']
    economic, cash = s['venue_payout'] - charges + income, s['cash_redemptions_pusd'] - charges + income
    a = {k: number(v, minimum=None) for k, v in accounts.items() if k in (
        'cash_net_pnl', 'raw_net_pnl', 'economic_net_pnl', 'cash_balance_net_pnl', 'balance_net_pnl',
        'cost', 'cash_redemptions_pusd', 'venue_payout', 'maker_fees_pusd', 'operating_cost', 'unredeemed_venue_value')}
    actual_charges = a['cost'] + a['maker_fees_pusd'] + a['operating_cost']
    actual_income = number(rewards) + number(rebates)
    checks = {
        'predicted_cash_formula': check(s['cash_net_pnl'], cash),
        'predicted_economic_formula': check(s['raw_net_pnl'], economic),
        'predicted_economic_alias': check(s['economic_net_pnl'], s['raw_net_pnl']),
        'predicted_cash_asset_bridge': check(s['cash_net_pnl'], s['raw_net_pnl'] - s['unredeemed_venue_value']),
        'predicted_proceeds_partition': check(s['venue_payout'], s['cash_redemptions_pusd'] + s['unredeemed_venue_value']),
        'predicted_cash_available': check(s['cash_available'], number(opening_cash) - charges + s['cash_redemptions_pusd']),
        'predicted_wallet_cash': check(s['wallet_end_cash'], number(opening_cash) + cash),
        'actual_cash_formula': check(a['cash_net_pnl'], a['cash_redemptions_pusd'] - actual_charges + actual_income),
        'actual_economic_formula': check(a['raw_net_pnl'], a['venue_payout'] - actual_charges + actual_income),
        'actual_economic_alias': check(a['economic_net_pnl'], a['raw_net_pnl']),
        'actual_cash_balance': check(a['cash_net_pnl'], a['cash_balance_net_pnl']),
        'actual_economic_balance': check(a['raw_net_pnl'], a['balance_net_pnl']),
        'cash_prediction_accuracy': check(s['cash_net_pnl'], a['cash_net_pnl']),
        'economic_prediction_accuracy': check(s['raw_net_pnl'], a['raw_net_pnl']),
    }
    for key in ('cash_net_pnl', 'raw_net_pnl'):
        checks['reported_' + key] = check(economics[key]['predicted'], s[key])
        checks['reported_actual_' + key] = check(economics[key]['actual'], a[key])
    if accounts.get('completed_cash', {}).get('status') == 'COMPLETE':
        checks['completed_cash_economic_identity'] = check(s['cash_net_pnl'], s['raw_net_pnl'])
        checks['actual_completed_cash_economic_identity'] = check(a['cash_net_pnl'], a['raw_net_pnl'])
        checks['completed_cash_alias'] = check(accounts['completed_cash']['net_pnl'], a['cash_net_pnl'])
    completion_matches = completed_cash is None or completed_cash['status'] == accounts['completed_cash']['status']
    if completed_cash is not None:
        checks['reported_completed_cash_alias'] = check(completed_cash['net_pnl'], a['cash_net_pnl'])
    return {'pass': completion_matches and all(m['pass'] for m in checks.values()),
            'completion_status_matches': completion_matches, 'limit': limit, 'metrics': checks}
