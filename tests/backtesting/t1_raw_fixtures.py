"""Synthetic native raw session fixtures; adapted from T035r1 N4/N5 reproductions."""
from copy import deepcopy
from decimal import Decimal as D
import hashlib
import json

from tests.backtesting.t1_fixtures import at, config, tolerance, attach_activity_prefixes
from tests.backtesting.test_t1_qualification import two_leg_session
from tests.backtesting.test_t1_b024 import native_snapshot
from weather.backtesting.t1_accuracy import accuracy_gate
from weather.backtesting.t1_raw_projection import PROJECTOR, without_lineage
from weather.backtesting.t1_types import canonical, digest

def build_two_leg_raw(root, index, *, separate_redemption=True):
    root.mkdir()
    amount = D('.619048')
    allocation = {'method':'independent_venue_accrual_deltas', 'source_sha256':'a'*64,
        'payment_id':'shared-day-payment', 'day_total':str(2*amount), 'account_day_complete':True,
        'sessions':{'s1':str(amount), 's2':str(amount)}}
    p, journal, r = two_leg_session(index, allocation)
    w = r['wallet']
    offset, cid, sid = (index-1)*400, 'c'+str(index), 's'+str(index)
    tokens = p['conditions'][cid]['token_ids']
    # Native position IDs are decimal wire strings.
    token_map = {tokens[0]:str(index*1000+1), tokens[1]:str(index*1000+2)}
    def rename(value):
        if isinstance(value,dict): return {token_map.get(k,k):rename(v) for k,v in value.items()}
        if isinstance(value,list): return [rename(v) for v in value]
        return token_map.get(value,value) if isinstance(value,str) else value
    p, r = rename(p), rename(r)
    w, tokens = r['wallet'], p['conditions'][cid]['token_ids']
    previous, lines = None, []
    for row in map(json.loads,journal.splitlines()):
        row = rename(row)
        row['previous_sha256'] = previous
        line = canonical(row)
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    journal = b''.join(lines)
    r['journal_sha256'] = hashlib.sha256(journal).hexdigest()
    w['reward_credit'] = str(amount)
    w['end_cash'] = str(D('100.4')+2*amount)
    other = amount + (D('.2') if index == 1 else 0)
    w['other_attributed_cashflows'][0]['amount'] = str(other)
    w['cash_events'][0]['amount'] = str(amount)
    w['cash_events'][1]['amount'] = str(other)
    for row in r['state_checkpoints']:
        if row['id'] == 'cash:shared-day-payment': row['cash'] = str(D(w['start_cash'])+D('.2')+amount)
        if row['id'].startswith('cash:other-session-'): row['cash'] = w['end_cash']
    for read in r['rewards']: read['paid_reward'] = str(amount)
    if separate_redemption:
        p['end'] = p['conditions'][cid]['coverage_end'] = at(offset+307)
        next(e for e in p['events'] if e['kind']=='redemption')['at'] = at(offset+307)
        w['redemptions'][0].update(at=at(offset+307),finalized_at=at(offset+307))
        next(c for c in r['state_checkpoints'] if c['id'].startswith('redemption:'))['at'] = at(offset+307)
    activity = []
    for fill in r['clob']['rows']:
        leg = fill['maker_orders'][0]
        activity.append({'id':fill['id'], 'kind':'BUY', 'at':fill['match_time'], 'status':'CONFIRMED',
            'order_id':leg['order_id'], 'token_id':leg['asset_id'], 'price':leg['price'],
            'size':leg['matched_amount'], 'cash_delta':str(-D(leg['price'])*D(leg['matched_amount']))})
    red = without_lineage(w['redemptions'][0])
    activity.append({k:v for k,v in {**red,'kind':'REDEEM','cash_delta':red['credit']}.items() if k!='credit'})
    for event in w['cash_events']:
        row = {k:v for k,v in {**without_lineage(event),'cash_delta':event['amount']}.items() if k!='amount'}
        if row['kind']=='EXTERNAL': row['session_id'] = w['other_attributed_cashflows'][0]['session_id']
        activity.append(row)
    wallet = {'format':PROJECTOR, 'account_id':r['scope']['account_id'], 'session_id':sid,
        'opening':{'at':p['start'],'cash':w['start_cash'],'positions':w['opening_positions']},
        'terminal':{'at':at(offset+6),'cash':str(D(w['start_cash'])-D('9.8')),'positions':w['terminal_positions']},
        'closing':{'at':w['as_of_utc'],'cash':w['end_cash'],'positions':w['end_positions'],'activity_final':True},
        'activity':activity,'activity_cursor':'LTE=','checkpoints':without_lineage(deepcopy(r['state_checkpoints']))}
    for snap in [wallet[k] for k in ('opening','terminal','closing')] + wallet['checkpoints']:
        native_snapshot(snap)
        for walks in snap['position_walks'].values():
            for walk in walks:
                for page in walk:
                    for row in page['response']['data']: row['condition_id']=cid
    attach_activity_prefixes(wallet, r['state_checkpoints'])
    roles = {'journal':journal, 'wallet':wallet,
        'clob':{'endpoint':r['clob']['endpoint'],'pages':[{'request_cursor':None,'response':{'data':r['clob']['rows'],'next_cursor':'LTE='}}]},
        'settlement':{'resolutions':[{'condition_id':cid,'token_ids':tokens,'status':'FINAL',
            'available_at':at(offset+306),'payout_denominator':'1','payout_numerators':['0','1']}]},
        'redemptions':{'transactions':without_lineage(w['redemptions'])}}
    credit = {'id':'shared-day-payment','at':w['cash_events'][0]['at'],'status':'CONFIRMED',
        'finalized_at':w['cash_events'][0]['at'],'amount':str(2*amount),'sessions':allocation['sessions']}
    for role, read in zip(('reward_d1','reward_d2'), r['rewards']):
        roles[role] = {**{k:read[k] for k in ('account_id','condition_id','reward_day','as_of_utc')},'credits':[credit]}
        read['allocation']['source_sha256'] = digest(credit)
    verified = {}
    for role, data in roles.items():
        path = root/(role+('.jsonl' if role=='journal' else '.json'))
        content = data if isinstance(data,bytes) else canonical(data)
        path.write_bytes(content)
        verified[role] = {'path':path,'sha256':hashlib.sha256(content).hexdigest()}
    w['end_cash_source_sha256'] = verified['wallet']['sha256']
    w['settlement_source_sha256'] = verified['settlement']['sha256']
    next(e for e in p['events'] if e['kind']=='settlement')['source_sha256'] = verified['settlement']['sha256']
    for row in w['cash_events'] + r['state_checkpoints']: row['source_sha256'] = verified['wallet']['sha256']
    for role, read in zip(('reward_d1','reward_d2'), r['rewards']): read['source_sha256'] = verified[role]['sha256']
    report = accuracy_gate(p,config(),journal,r,tolerance())
    return verified,p,r,report


def shared_raw_campaign(root):
    """Two native flat periods with separate paid credits on one reward day.

    The first export includes the later session's actual cash/token movements.
    Its boundary observation is exactly the second export's opening observation.
    """
    staged = [build_two_leg_raw(root / str(i), i, separate_redemption=False) for i in (1, 2)]
    amount = D('.619048')
    wallets = [json.loads(v['wallet']['path'].read_bytes()) for v, p, r, report in staged]
    staged[0][1]['end'] = staged[0][1]['conditions']['c1']['coverage_end'] = at(400)
    final_cash = str(D('100.4') + 2 * amount)
    snapshots = []
    for key, original in (('initial', wallets[0]['opening']), ('boundary', wallets[1]['opening']),
                          ('final', wallets[0]['closing'])):
        snapshots.append({'id': key, **{k: deepcopy(original[k]) for k in
            ('at', 'collateral_evidence', 'position_walks', 'order_pages')}})
    end = native_snapshot({'at': staged[1][1]['end'], 'cash': '100.4', 'positions': {}})
    snapshots.append({'id': 'funded-end', **{k: end[k] for k in ('at', 'collateral_evidence', 'position_walks', 'order_pages')}})
    observation_data = {'account_id': 'synthetic-account', 'account_scope_complete': True, 'snapshots': snapshots}
    observation_bytes, observation_hash = canonical(observation_data), digest(observation_data)
    for index, ((verified, p, r, _), raw_wallet) in enumerate(zip(staged, wallets), 1):
        sid, cid = 's' + str(index), 'c' + str(index)
        other = 3 - index
        w = r['wallet']
        own_payment = 'reward-payment-' + sid
        paid_at = '2026-10-13T09:00:0' + str(index - 1) + '+00:00'
        foreign_at = '2026-10-13T09:00:0' + str(other - 1) + '+00:00'
        external = []
        if index == 1:
            external = [
                {'id': 'external-buy-yes-2', 'at': at(404), 'amount': '-4.9', 'token_deltas': {'2001': '10'}},
                {'id': 'external-buy-no-2', 'at': at(404.5), 'amount': '-4.9', 'token_deltas': {'2002': '10'}},
                {'id': 'external-redeem-2', 'at': at(706), 'amount': '10', 'token_deltas': {'2001': '-10', '2002': '-10'}},
            ]
        external.append({'id': 'external-reward-s' + str(other), 'at': foreign_at, 'amount': str(amount)})
        w['other_attributed_cashflows'] = [{'id': f['id'], 'session_id': 's' + str(other),
            'amount': f['amount'], 'source_sha256': 'a' * 64} for f in external]
        w['cash_events'] = [{'id': own_payment, 'kind': 'REWARD', 'at': paid_at, 'finalized_at': paid_at,
            'status': 'CONFIRMED', 'amount': str(amount), 'source_sha256': 'a' * 64}]
        w['cash_events'] += [{'id': f['id'], 'kind': 'EXTERNAL', 'at': f['at'], 'finalized_at': f['at'],
            'status': 'CONFIRMED', 'amount': f['amount'], 'source_sha256': 'a' * 64} for f in external]
        w['cash_events'].sort(key=lambda f: f['at'])
        w['payment_ids']['reward'] = [own_payment]
        credit = {'id': own_payment, 'at': paid_at, 'finalized_at': paid_at, 'status': 'CONFIRMED',
            'amount': str(amount), 'sessions': {sid: str(amount)}}
        allocation = {'method': 'independent_venue_accrual_deltas', 'source_sha256': digest(credit),
            'payment_id': own_payment, 'day_total': str(amount), 'account_day_complete': True,
            'sessions': {sid: str(amount)}}
        for read in r['rewards']:
            read['allocation'] = deepcopy(allocation)
        r['state_checkpoints'][:] = [c for c in r['state_checkpoints'] if not c['id'].startswith('cash:')]
        raw_wallet['activity'][:] = [a for a in raw_wallet['activity'] if a['kind'] in ('BUY', 'REDEEM')]
        for flow in w['cash_events']:
            row = {k: v for k, v in {**without_lineage(flow), 'cash_delta': flow['amount']}.items() if k != 'amount'}
            if flow['kind'] == 'EXTERNAL':
                original = next(f for f in external if f['id'] == flow['id'])
                row.update(session_id='s' + str(other), token_deltas=original.get('token_deltas', {}))
            raw_wallet['activity'].append(row)
        raw_wallet['activity'].sort(key=lambda f: f['at'])
        running = D(w['start_cash']) + D('.2')
        foreign_positions = {}
        raw_wallet['checkpoints'][:] = [c for c in raw_wallet['checkpoints'] if not c['id'].startswith('cash:')]
        for flow in w['cash_events']:
            running += D(flow['amount'])
            point = {'id': 'cash:' + flow['id'], 'at': flow['at'], 'cash': str(running), 'reserved': '0',
                'cost_at_risk': '0', 'positions': deepcopy(w['end_positions']), 'source_sha256': 'a' * 64}
            r['state_checkpoints'].append(deepcopy(point))
            point.pop('source_sha256')
            raw_point = native_snapshot(point)
            if flow['kind'] == 'EXTERNAL':
                for token, delta in next(f for f in external if f['id'] == flow['id']).get('token_deltas', {}).items():
                    foreign_positions[token] = foreign_positions.get(token, D(0)) + D(delta)
            raw_point['position_walks']['OPEN'][0][0]['response']['data'] += [
                {'token_id': token, 'condition_id': 'c2', 'proxy_wallet': 'synthetic-account', 'current_size': str(size)}
                for token, size in foreign_positions.items() if size]
            raw_wallet['checkpoints'].append(raw_point)
        assert running == D(final_cash)
        for key, observation_id in (('opening', 'initial' if index == 1 else 'boundary'),
                                    ('period_closing', 'boundary' if index == 1 else 'funded-end'), ('closing', 'final')):
            raw_wallet[key] = {k: deepcopy(v) for k, v in next(s for s in snapshots if s['id'] == observation_id).items() if k != 'id'}
            raw_wallet[key + '_observation_id'] = observation_id
            w[key + '_observation'] = {'id': observation_id, 'source_sha256': observation_hash}
        raw_wallet['closing']['activity_final'] = True
        attach_activity_prefixes(raw_wallet, r['state_checkpoints'])
        changed = {'wallet': raw_wallet, 'wallet_observations': observation_data}
        for role, read in zip(('reward_d1', 'reward_d2'), r['rewards']):
            changed[role] = {**{k: read[k] for k in ('account_id', 'condition_id', 'reward_day', 'as_of_utc')}, 'credits': [credit]}
        for role, data in changed.items():
            path = root / str(index) / (role + '.json')
            content = observation_bytes if role == 'wallet_observations' else canonical(data)
            path.write_bytes(content)
            verified[role] = {'path': path, 'sha256': digest(data)}
        w['end_cash_source_sha256'], w['activity_source_sha256'] = observation_hash, verified['wallet']['sha256']
        for point in w['cash_events'] + r['state_checkpoints']:
            point['source_sha256'] = verified['wallet']['sha256']
        for role, read in zip(('reward_d1', 'reward_d2'), r['rewards']):
            read['source_sha256'] = verified[role]['sha256']
        staged[index - 1] = (verified, p, r, accuracy_gate(p, config(), verified['journal']['path'], r, tolerance()))
    return staged
