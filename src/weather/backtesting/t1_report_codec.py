"""Typed consumer boundary for persisted CLI session reports.

Decode monetary/quantity fields by schema location. Numeric-looking identity,
hash, timestamp, config and tolerance strings retain their original meaning.
"""
from copy import deepcopy

from weather.backtesting.t1_types import number, source_hash, utc


def metric(value):
    if type(value['pass']) is not bool:
        raise ValueError('report metric pass must be boolean')
    for key in ('predicted', 'actual', 'absolute_error', 'limit'):
        if key in value and value[key] is not None:
            value[key] = number(value[key], minimum=None)
    return value


def decode_session_report(value):
    from weather.backtesting.t1_accuracy import Tolerance

    result = deepcopy(value)
    if (not {'completed_cash', 'joint_error', 'transition_verification', 'accounting_complete', 'net_identities', 'wallet_observations'} <= set(result)
            or 'cash_net_pnl' not in result.get('economics', {})):
        raise ValueError('unsupported persisted session report; regenerate the current accounting schema')
    for key in ('config_sha256', 'tolerance_sha256', 'journal_sha256', 'wallet_end_cash_source_sha256'):
        source_hash(result[key])
    for key in ('period_start', 'period_end', 'wallet_as_of_utc'):
        utc(result[key])
    if utc(result['period_start']) > utc(result['period_end']):
        raise ValueError('report capital period regresses')
    if (type(result['actual_filled_orders']) is not int or result['actual_filled_orders'] < 0
            or type(result['metrics_pass']) is not bool or type(result['synthetic']) is not bool
            or type(result['accounting_complete']) is not bool):
        raise ValueError('report count and status types invalid')
    Tolerance(**result['tolerance'])
    refs = result['wallet_observations']
    if set(refs) != {'opening', 'period_closing', 'closing'}:
        raise ValueError('wallet observation references incomplete')
    if any(refs.values()):
        for ref in refs.values():
            if not ref or not isinstance(ref['id'], str) or not ref['id']:
                raise ValueError('wallet observation ID required')
            source_hash(ref['source_sha256'])
        source_hash(result['wallet_activity_source_sha256'])
    for key in ('rewards', 'rebates'):
        metric(result[key])
    for value in result['economics'].values():
        metric(value)
    for group in result.get('positions', {}).values():
        for value in group.values():
            metric(value)
    for group in result.get('checkpoints', {}).values():
        for value in group.values():
            metric(value)
    for key in ('wallet_end_cash', 'external_reward_accrued'):
        result[key] = number(result[key], minimum=None)
    capital = result['capital_period']
    for key in ('opening_cash', 'closing_cash'):
        capital[key] = number(capital[key], minimum=None)
    for key in ('opening_positions', 'end_positions'):
        capital[key] = {token: number(size) for token, size in capital[key].items()}
    for flow in capital['interperiod_cashflows'] + result['other_attributed_cashflows']:
        flow['amount'] = number(flow['amount'], minimum=None)
    accounts = result['actual_accounts']
    for key in ('cost', 'venue_payout', 'cash_redemptions_pusd', 'unredeemed_venue_value', 'cash_available',
                'wallet_end_cash', 'raw_net_pnl', 'balance_net_pnl', 'maker_fees_pusd', 'operating_cost',
                'outside_cash', 'opening_cash', 'cash_net_pnl', 'cash_balance_net_pnl', 'economic_net_pnl'):
        if key in accounts:
            accounts[key] = number(accounts[key], minimum=None)
    for key in ('terminal_positions', 'end_positions', 'opening_positions'):
        accounts[key] = {token: number(size) for token, size in accounts[key].items()}
    if 'completed_cash' in accounts:
        accounts['completed_cash']['net_pnl'] = number(accounts['completed_cash']['net_pnl'], minimum=None)
    allocation = result['reward_allocation']
    if allocation is not None:
        allocation['day_total'] = number(allocation['day_total'])
        allocation['sessions'] = {sid: number(amount) for sid, amount in allocation['sessions'].items()}
    for key in ('reward_accrued', 'rebate_accrued', 'cost', 'venue_payout', 'cash_net_pnl'):
        if key in result['simulation']:
            result['simulation'][key] = number(result['simulation'][key], minimum=None)
    if 'joint_error' in result:
        for key in ('absolute_error', 'limit'):
            result['joint_error'][key] = number(result['joint_error'][key])
    return result
