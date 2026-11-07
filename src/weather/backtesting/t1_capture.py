"""Pure adapters from retained International CLOB/pin snapshots; never discover or fetch.

Own displayed liquidity must be removed before counterfactual replay adds it
back. Caller supplies actual outstanding sizes at each capture, reconstructed
from acknowledged orders, terminal cancels and confirmed CLOB maker fills.
"""
from copy import deepcopy

from weather.backtesting.t1_types import ONE, ZERO, book_valid, digest, levels, number, source_hash, utc


def captured_book(raw_books, *, condition_id, token_ids, captured_at, observed_at, source_sha256, own=(), token_times=None):
    """Two raw /book replies -> normalized book excluding actual own liquidity.

    own entries are outcome/price/remaining. Each native bid is mirrored on the
    complement's ask by the venue. Never infer the executable ask from a bid.
    An absent own level is evidence inconsistency, not an empty competitor book.
    """
    if len(token_ids) != 2 or len(set(token_ids)) != 2 or not source_sha256:
        raise ValueError('book source or token mapping missing')
    source_hash(source_sha256)
    if utc(observed_at) > utc(captured_at):
        raise ValueError('book observation follows its availability')
    out = {'kind': 'book', 'condition_id': condition_id, 'at': captured_at, 'observed_at': observed_at,
           'source_sha256': source_sha256}
    if token_times is not None:
        out['token_times'] = deepcopy(token_times)
    for outcome, token in zip(('YES', 'NO'), token_ids):
        raw = raw_books[token]
        if str(raw['asset_id']) != token or raw['market'] != condition_id:
            raise ValueError('captured book token mismatch')
        out[outcome] = {side: levels(raw[side]) for side in ('bids', 'asks')}
        out[outcome].update(tick=raw['tick_size'], min_order_size=raw['min_order_size'])
    raw_sides = {outcome: deepcopy(out[outcome]) for outcome in ('YES', 'NO')}
    book_valid(out, now=utc(captured_at), max_age=number((utc(captured_at) - utc(observed_at)).total_seconds()))
    out['acceptance_state_known'] = all('accepting_orders' in raw_books[t] for t in token_ids)
    out['accepting_orders'] = (all(raw_books[t].get('accepting_orders') is True for t in token_ids)
                               if out['acceptance_state_known'] else None)
    for order in own:
        outcome = order['outcome']
        if outcome not in ('YES', 'NO'):
            raise ValueError('unknown own outcome')
        price, size = number(order['price']), number(order['remaining'])
        other = 'NO' if outcome == 'YES' else 'YES'
        for token_outcome, side, p in ((outcome, 'bids', price), (other, 'asks', ONE - price)):
            remaining = size
            for level in out[token_outcome][side]:
                if level['price'] == p:
                    remove = min(remaining, level['size'])
                    level['size'] -= remove
                    remaining -= remove
            if remaining:
                raise ValueError('own size missing from captured book')
            out[token_outcome][side] = [r for r in out[token_outcome][side] if r['size'] > ZERO]
    out['competitor_only'] = True
    out['own_exclusion'] = {'raw_sides': raw_sides, 'raw_sides_sha256': digest(raw_sides),
                            'orders': deepcopy(list(own))}
    return out


def verify_own_exclusions(events, commands, fills):
    """Reconstruct private remaining sizes and check exactly one raw subtraction.

    Collection and private-event intervals that overlap are unidentified, never
    resolved using a convenient endpoint. Returns gaps for partial calibration.
    """
    from collections import defaultdict
    from weather.backtesting.t1_rewards import level_map

    gaps = set()
    posts = {c['id']: c for c in commands if c['kind'] == 'post'}
    cancels = {c['id']: c for c in commands if c['kind'] == 'cancel'}
    for event in events:
        if event['kind'] != 'book':
            continue
        manifest = event.get('own_exclusion')
        if manifest is None:
            gaps.add('missing_own_subtraction_manifest')
            continue
        if digest(manifest['raw_sides']) != manifest['raw_sides_sha256']:
            raise ValueError('raw book subtraction hash mismatch')
        left, right = utc(event['observed_at']), utc(event['at'])
        clocks = event.get('token_times')
        if clocks is None:
            gaps.add('missing_per_token_book_collection_clocks')
        else:
            if set(clocks) != {'YES', 'NO'} or any(not left <= utc(c['started_at']) <= utc(c['completed_at']) <= right for c in clocks.values()):
                raise ValueError('per-token book clocks conflict with capture interval')
        book_valid({**event, **manifest['raw_sides'], 'competitor_only': False}, now=right,
                    max_age=number((right - left).total_seconds()))
        expected = {}
        for oid, command in posts.items():
            lower, upper = utc(command['decided_at']), utc(command['arrival_at'])
            if left < utc(command['expires_at']) <= right:
                gaps.add('own_size_uncertain_during_book_collection')
            if left < upper and right >= lower:
                gaps.add('own_size_uncertain_during_book_collection')
            if upper > left or utc(command['expires_at']) <= left:
                continue
            if oid in cancels:
                cancel = cancels[oid]
                if left < utc(cancel['arrival_at']) and right >= utc(cancel['decided_at']):
                    gaps.add('own_size_uncertain_during_book_collection')
                if utc(cancel['arrival_at']) <= left:
                    continue
            remaining = number(command['size'])
            for fill in fills:
                if fill['order_id'] != oid:
                    continue
                if fill['at'] <= right and fill['at_end'] >= left and (fill['at'] != fill['at_end'] or left != right):
                    gaps.add('own_size_uncertain_during_book_collection')
                if fill['at_end'] <= left:
                    remaining -= fill['size']
            if remaining:
                expected[oid] = (command['outcome'], number(command['price']), remaining)
        supplied = {}
        reconstructed = {(o, s): defaultdict(lambda: ZERO, level_map(event, o, s))
                         for o in ('YES', 'NO') for s in ('bids', 'asks')}
        for order in manifest['orders']:
            oid = order.get('order_id')
            if not oid or oid in supplied:
                raise ValueError('own subtraction requires unique private order identities')
            outcome, price, remaining = order['outcome'], number(order['price']), number(order['remaining'])
            supplied[oid] = (outcome, price, remaining)
            other = 'NO' if outcome == 'YES' else 'YES'
            reconstructed[(outcome, 'bids')][price] += remaining
            reconstructed[(other, 'asks')][ONE - price] += remaining
        if supplied != expected:
            raise ValueError('book own subtraction disagrees with private lifecycle')
        raw = manifest['raw_sides']
        for (outcome, side), values in reconstructed.items():
            if dict(values) != level_map(raw, outcome, side):
                raise ValueError('book own liquidity was not subtracted exactly once')
    return sorted(gaps)


def pin_snapshot(snapshot, *, available_at, valid_until, own=()):
    """Pin RE-1/LFC public snapshot -> captured book and captured reward terms.

    Source hashes bind the whole snapshot, including rule/fee fields. valid_until
    is the predeclared freshness bound, not an assertion of future venue terms.
    """
    observed = snapshot['observed_at_utc']  # the pin records batch START, before HTTP reads
    if utc(valid_until) <= utc(available_at) or utc(available_at) < utc(observed):
        raise ValueError('invalid snapshot validity')
    tokens, values = snapshot['token_ids'], snapshot['quote_inputs']
    raw = {token: {'asset_id': token, 'market': snapshot['condition_id'],
                   'bids': values[prefix + '_bids'], 'asks': values[prefix + '_asks'],
                   'tick_size': snapshot['rules'][token]['tick_size'],
                   'min_order_size': snapshot['rules'][token]['min_order_size']}
           for prefix, token in zip(('yes', 'no'), tokens)}
    source = digest(snapshot)
    book = captured_book(raw, condition_id=snapshot['condition_id'], token_ids=tokens,
                         captured_at=available_at, observed_at=observed, source_sha256=source, own=own)
    terms = {'kind': 'terms', 'condition_id': snapshot['condition_id'], 'at': available_at, 'valid_until': valid_until,
             'min_size': values['reward_min_size'], 'max_spread_cents': values['reward_max_spread_cents'],
             'rate_per_day': values['reward_rate_per_day'], 'source_sha256': source,
             'captured_rules': deepcopy(snapshot['rules']), 'fee_evidence': deepcopy(snapshot.get('fee_evidence'))}
    return book, terms


def captured_print(row, *, captured_at, condition_id, token_ids, source_sha256):
    """88a last_trade_price wire row -> execution-time print with receipt lineage."""
    from datetime import datetime, timezone

    if (row['event_type'] != 'last_trade_price' or row['asset_id'] not in token_ids
            or row['side'] not in ('BUY', 'SELL') or not source_sha256):
        raise ValueError('unsupported or ambiguous execution print')
    source_hash(source_sha256)
    traded = datetime.fromtimestamp(int(row['timestamp']) / 1000, timezone.utc)
    if traded > utc(captured_at):
        raise ValueError('execution print captured before trade')
    # Wire last_trade_price lacks an exchange trade ID. An exporter must supply
    # a stable execution ID, reconciling mirrored/retransmitted stream messages.
    if not row.get('execution_id'):
        raise ValueError('deduplicated execution ID required')
    return {'kind': 'trade', 'condition_id': condition_id, 'at': captured_at, 'traded_at': traded.isoformat(),
            'id': row['execution_id'], 'outcome': 'YES' if row['asset_id'] == token_ids[0] else 'NO',
            'aggressor': row['side'], 'price': row['price'], 'size': row['size'], 'source_sha256': source_sha256,
            'status': row.get('status', 'UNKNOWN'), 'execution_route': row.get('execution_route', 'UNKNOWN'),
            **{k: row[k] for k in ('consumption_id', 'route_source_sha256') if k in row}}
