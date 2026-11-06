"""Pure adapters from retained International CLOB/pin snapshots; never discover or fetch.

Own displayed liquidity must be removed before counterfactual replay adds it
back. Caller supplies actual outstanding sizes at each capture, reconstructed
from acknowledged orders, terminal cancels and confirmed CLOB maker fills.
"""
from weather.backtesting.t1_types import ONE, ZERO, digest, levels, number, source_hash, utc


def captured_book(raw_books, *, condition_id, token_ids, captured_at, observed_at, source_sha256, own=()):
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
    for outcome, token in zip(('YES', 'NO'), token_ids):
        raw = raw_books[token]
        if str(raw['asset_id']) != token or raw['market'] != condition_id:
            raise ValueError('captured book token mismatch')
        out[outcome] = {side: levels(raw[side]) for side in ('bids', 'asks')}
        out[outcome].update(tick=raw['tick_size'], min_order_size=raw['min_order_size'])
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
    return out


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
             'rate_per_day': values['reward_rate_per_day'], 'source_sha256': source}
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
            'aggressor': row['side'], 'price': row['price'], 'size': row['size'], 'source_sha256': source_sha256}
