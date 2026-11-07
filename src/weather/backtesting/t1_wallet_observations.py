"""Bind shared native account observations separately from per-session activity."""
from weather.backtesting.t1_raw_projection import load_role, same
from weather.backtesting.t1_raw_snapshot import collateral, positions, open_orders
from weather.backtesting.t1_types import number, utc


def verify_observations(verified, raw_wallet, receipts, payload, accounts):
    if 'wallet_observations' not in verified:
        return {'status': 'NOT QUALIFIED', 'reason': 'Independent shared wallet observations are missing.'}
    role = verified['wallet_observations']
    raw = load_role(verified, 'wallet_observations')
    wallet, scope = receipts['wallet'], receipts['scope']
    if raw['account_id'] != scope['account_id'] or raw['account_scope_complete'] is not True:
        raise ValueError('shared wallet observation account/scope differs')
    indexed = {s['id']: s for s in raw['snapshots']}
    if len(indexed) != len(raw['snapshots']):
        raise ValueError('shared wallet observation IDs repeat')
    tokens, cid = payload['conditions'][scope['condition_id']]['token_ids'], scope['condition_id']
    expected = {
        'opening': (payload['start'], accounts['opening_cash'], accounts['opening_positions']),
        'period_closing': (payload['end'], accounts['cash_available'], accounts['end_positions']),
        'closing': (wallet['as_of_utc'], wallet['end_cash'], accounts['end_positions']),
    }
    refs = {}
    for kind, (at, cash, holdings) in expected.items():
        ref = wallet[kind + '_observation']
        if ref != {'id': raw_wallet[kind + '_observation_id'], 'source_sha256': role['sha256']}:
            raise ValueError('wallet observation reference differs from its precise shared role')
        observed, inline = indexed[ref['id']], raw_wallet[kind]
        for key in ('at', 'collateral_evidence', 'position_walks', 'order_pages'):
            same(inline[key], observed[key], 'shared_observation/' + kind + '/' + key)
        if utc(observed['at']) != utc(at) or abs(collateral(observed) - number(cash)) > number('.00001'):
            raise ValueError('shared wallet observation clock/cash differs from its financial period')
        native, other = positions(observed, tokens, scope['account_id'], cid)
        same(native, holdings, 'shared_observation/' + kind + '/positions')
        if other or open_orders(observed):
            raise ValueError('flat-period shared observation has other inventory/reservations')
        refs[kind] = ref
    if wallet['end_cash_source_sha256'] != role['sha256']:
        raise ValueError('closing cash must bind the shared observation role, not session activity')
    if wallet['activity_source_sha256'] != verified['wallet']['sha256']:
        raise ValueError('session wallet activity must retain its separate source binding')
    if wallet.get('interperiod_cashflows'):
        raise ValueError('raw interperiod funding changes require an independent movement adapter')
    return {'status': 'PASS', 'references': refs, 'source_sha256': role['sha256']}
