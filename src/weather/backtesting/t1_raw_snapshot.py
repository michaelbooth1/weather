"""Offline native CLOB collateral and Data API v2 position projection.

The six-decimal collateral conversion and OPEN/REDEEMABLE_LOST page semantics
follow the reviewed F0 source. Sanitized aggregate cash/position fields alone
are not native evidence and cannot qualify.
"""
from weather.backtesting.t1_types import ZERO, number


def collateral(snapshot):
    units = number(snapshot['collateral_evidence']['balance'])
    if units != units.to_integral_value():
        raise ValueError('raw collateral balance must be integer native units')
    amount = units / 1_000_000
    if 'cash' in snapshot and number(snapshot['cash']) != amount:
        raise ValueError('wallet/cash convenience field contradicts native collateral response')
    return amount


def positions(snapshot, tokens, account_id, condition_id):
    walks = snapshot['position_walks']
    if set(walks) != {'OPEN', 'REDEEMABLE_LOST'}:
        raise ValueError('raw position status coverage incomplete')
    merged = {}
    for status, attempts in walks.items():
        previous, accepted = None, None
        for pages in attempts:
            cursor, rows = None, {}
            for page in pages:
                if page['request_cursor'] != cursor:
                    raise ValueError('raw position cursor chain disagrees')
                body = page['response']
                for row in body['data']:
                    token = row['token_id']
                    if (not isinstance(token, str) or not token.isdigit() or token in rows
                            or str(row['proxy_wallet']).lower() != account_id.lower()
                            or not row['condition_id'] or token in tokens and row['condition_id'] != condition_id):
                        raise ValueError('raw native position identity conflicts')
                    rows[token] = number(row['current_size'])
                pagination = body['pagination']
                nxt = pagination['next_cursor']
                if (type(pagination['has_more']) is not bool or pagination['has_more'] != bool(nxt)
                        or nxt is not None and (not isinstance(nxt, str) or not nxt)):
                    raise ValueError('raw position pagination shape conflicts')
                cursor = nxt
            if not pages or cursor is not None:
                raise ValueError('raw position walk does not exhaust native pages')
            if len(pages) == 1 or previous == rows:
                accepted = rows
                break
            previous = rows
        if accepted is None:
            raise ValueError('raw multi-page positions require two agreeing complete walks')
        for token, size in accepted.items():
            if token in merged and merged[token] != size:
                raise ValueError('raw positions disagree between statuses')
            merged[token] = size
    selected = {t: merged.get(t, ZERO) for t in tokens}
    if 'positions' in snapshot:
        if set(snapshot['positions']) != set(tokens) or any(number(snapshot['positions'][t]) != selected[t] for t in tokens):
            raise ValueError('wallet/positions convenience field contradicts native position response')
    other = {t: size for t, size in merged.items() if t not in tokens and size != ZERO}
    return selected, other


def open_orders(snapshot):
    cursor, result = None, []
    for page in snapshot['order_pages']:
        if cursor == 'LTE=' or page['request_cursor'] != cursor:
            raise ValueError('raw open-order cursor chain fails')
        result.extend(page['response']['data'])
        cursor = page['response']['next_cursor']
    if cursor != 'LTE=':
        raise ValueError('raw open-order pages are incomplete')
    ids = [str(row.get('id') or row.get('orderID') or '') for row in result]
    if any(not oid for oid in ids) or len(set(ids)) != len(ids):
        raise ValueError('raw open-order identities invalid')
    return ids
