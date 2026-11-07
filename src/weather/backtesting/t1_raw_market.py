"""Verify market/sample projections against precise retained role records.

Consistency is not authority. No midpoint rule or hidden venue sample feed is
qualified by this module merely because a record claims its origin.
"""
from collections import defaultdict

from weather.backtesting.t1_capture import captured_book, captured_print, pin_snapshot
from weather.backtesting.t1_raw_projection import load_role, same, without_lineage
from weather.backtesting.t1_types import ONE, number, digest, utc


def verify_samples(raw, payload, source):
    epochs, population = {}, {}
    for epoch in raw['epochs']:
        key = (epoch['condition_id'], epoch['day'])
        count = number(epoch['active_sample_count'], minimum=ONE)
        if count != count.to_integral_value() or count > 1440 or key in epochs:
            raise ValueError('raw sample epoch denominator invalid or duplicate')
        samples = [utc(value) for value in epoch['sample_times']]
        minutes = [at.replace(second=0, microsecond=0) for at in samples]
        if (len(samples) != count or len(set(minutes)) != len(minutes)
                or any(at.date().isoformat() != key[1] for at in samples)):
            raise ValueError('raw sample population disagrees with denominator/day')
        epochs[key] = count
        for at in samples:
            population[(key[0], at)] = count
    represented = {}
    for event in payload['events']:
        if event['kind'] != 'reward_sample':
            continue
        at = utc(event['at'])
        key = (event['condition_id'], at)
        if key in represented or population.get(key) != number(event['epoch_active_sample_count']):
            raise ValueError('normalized sample disagrees with raw population')
        if event['source_sha256'] != source:
            raise ValueError('sample source hash is not the sample role')
        represented[key] = population[key]
    expected = {k: v for k, v in population.items() if utc(payload['start']) <= k[1] <= utc(payload['end'])}
    if represented != expected:
        raise ValueError('normalized sample projection omitted or invented in-window samples')
    return {'status': 'PASS', 'epochs': len(epochs), 'sample_count': len(population),
            'authority_status': 'NOT QUALIFIED'}


def verify_books(raw, events, source, *, marks=False):
    projected = []
    for capture in raw['captures']:
        book = captured_book(capture['raw_books'], condition_id=capture['condition_id'],
            token_ids=capture['token_ids'], captured_at=capture['captured_at'], observed_at=capture['observed_at'],
            source_sha256=source, own=() if marks else capture['own'], token_times=capture.get('token_times'))
        if not marks:
            book['reward_orders_complete'] = capture.get('native_orders_complete', False)
            if capture.get('native_orders_complete'):
                book['reward_orders'] = capture['native_orders']
        projected.append(book)
    if len(projected) != len(events):
        raise ValueError('raw book capture population differs from projection')
    for expected, actual in zip(projected, events):
        if actual['source_sha256'] != source:
            raise ValueError('book source hash is not its exact raw role')
        for key in ('kind', 'condition_id', 'at', 'observed_at', 'YES', 'NO', 'token_times',
                    'accepting_orders', 'acceptance_state_known', 'competitor_only'):
            if key in expected:
                same(actual.get(key), expected[key], 'book/' + key)
        if not marks:
            same(actual.get('own_exclusion'), expected['own_exclusion'], 'book/own_exclusion')
            same(actual.get('reward_orders_complete', False), expected['reward_orders_complete'], 'book/native_orders_complete')
            if expected['reward_orders_complete']:
                same(actual.get('reward_orders'), expected['reward_orders'], 'book/native_orders')
    return {'status': 'PASS', 'captures': len(projected)}


def verify_prints(raw, payload, source):
    projected = [captured_print(record['row'], captured_at=record['captured_at'],
        condition_id=record['condition_id'], token_ids=payload['conditions'][record['condition_id']]['token_ids'],
        source_sha256=source) for record in raw['prints']]
    same([e for e in payload['events'] if e['kind'] == 'trade'], projected, 'market_state/prints')
    return {'status': 'PASS', 'authority_status': 'NOT QUALIFIED',
            'reason': 'Wire projection verified; exporter-added execution identity/finality/route needs independent proof.'}


def verify_market_roles(verified, payload, receipts):
    results = {}
    operations = {
        'books': lambda raw, sha: verify_books(raw, [e for e in payload['events'] if e['kind'] == 'book'], sha),
        'marks': lambda raw, sha: verify_books(raw, receipts['mark_books'], sha, marks=True),
        'reward_samples': lambda raw, sha: verify_samples(raw, payload, sha),
        'market_state': lambda raw, sha: verify_prints(raw, payload, sha),
    }
    for role, operation in operations.items():
        try:
            results[role] = operation(load_role(verified, role), verified[role]['sha256'])
        except (ValueError, KeyError, TypeError) as exc:
            results[role] = {'status': 'NOT QUALIFIED', 'reason': str(exc)}
    try:
        raw = load_role(verified, 'terms')
        events = [e for e in payload['events'] if e['kind'] == 'terms']
        if len(events) != len(raw['snapshots']):
            raise ValueError('raw terms population differs from projection')
        for event, record in zip(events, raw['snapshots']):
            _, projected = pin_snapshot(record['snapshot'], available_at=record['available_at'], valid_until=record['valid_until'])
            same(without_lineage(event), without_lineage(projected), 'terms')
            if event['source_sha256'] not in (verified['terms']['sha256'], digest(record['snapshot'])):
                raise ValueError('terms source is not its raw record')
        results['terms'] = {'status': 'PASS'}
    except (ValueError, KeyError, TypeError) as exc:
        results['terms'] = {'status': 'NOT QUALIFIED', 'reason': str(exc)}
    try:
        raw = load_role(verified, 'rebates')
        same(without_lineage(payload.get('rebate_pools', {})), without_lineage(raw['condition_days']), 'rebates/condition_days')
        results['rebates'] = {'status': 'PASS'}
    except (ValueError, KeyError, TypeError) as exc:
        results['rebates'] = {'status': 'NOT QUALIFIED', 'reason': str(exc)}
    return {'status': 'PASS' if all(r['status'] == 'PASS' for r in results.values()) else 'NOT QUALIFIED',
            'roles': results, 'midpoint_authority': 'NOT QUALIFIED'}
