"""One-shot public live-path contracts; never credentials, orders or eligibility authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import re
from urllib.parse import urlencode

from weather import http
from weather.operations.live_contract_sources import public_definitions
from weather.paths import config_path


class _BoundedResponse:
    def __init__(self, response, limit=5_000_000):
        self.response, self.limit = response, limit
    def read(self, size=-1):
        raw = self.response.read(min(size, self.limit + 1) if size >= 0 else self.limit + 1)
        if len(raw) > self.limit:
            raise ValueError('public response exceeds probe bound')
        return raw
    def __getattr__(self, name):
        return getattr(self.response, name)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.response.close()


class OneShotPublicOpener:
    """Exact URL/method allowlist, one request each, no redirects or retries."""
    def __init__(self, allowed):
        self.allowed = allowed
        self.seen = set()
        self.statuses = {}
    def __call__(self, request, *, timeout):
        key = (request.get_method(), request.full_url)
        if key not in self.allowed or key in self.seen:
            raise ValueError('request outside the one-shot public contract')
        self.seen.add(key)
        if key[0] == 'POST' and json.loads(request.data) != {
                'jsonrpc': '2.0', 'id': 1, 'method': 'eth_blockNumber', 'params': []}:
            raise ValueError('only eth_blockNumber is allowed')
        if any(any(term in name.lower() for term in ('authorization', 'poly_', 'secret', 'cookie'))
               for name in request.headers):
            raise ValueError('credential header forbidden')
        response = http._OPENER.open(request, timeout=timeout)
        self.statuses[key] = response.status
        if response.status != 200:
            response.close()
            raise ValueError('public status must be 200')
        return _BoundedResponse(response)


def configured_pair(token, condition):
    payload = json.loads(config_path('location_market_events.json').read_text(encoding='utf-8'))
    def walk(value):
        if isinstance(value, dict):
            if value.get('condition_id') == condition:
                yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    def has_token(value):
        if isinstance(value, dict):
            return value.get('token_id') == token or any(has_token(child) for child in value.values())
        if isinstance(value, list):
            return any(has_token(child) for child in value)
        return False
    if not any(has_token(row) for row in walk(payload)):
        raise ValueError('token/condition pair is absent from checked-in configuration')


def run(*, token, condition, public_address):
    configured_pair(token, condition)
    book_url = 'https://clob.polymarket.com/book?' + urlencode({'token_id': token})
    reward_url = 'https://clob.polymarket.com/rewards/markets/' + condition
    positions_url = 'https://data-api.polymarket.com/positions?' + urlencode({
        'user': public_address, 'market': condition, 'sizeThreshold': 0, 'limit': 500, 'offset': 0})
    allowed = {('GET', url) for url in [book_url, reward_url, positions_url, 'https://polymarket.com/api/geoblock']}
    allowed.add(('POST', 'https://polygon.drpc.org'))
    opener = OneShotPublicOpener(allowed)
    source = public_definitions(opener)
    reader = source.PublicBooks(opener=opener)

    def geography():
        value = source.geography()
        return {'blocked': value['blocked'], 'note': 'shape only; not eligibility authority'}

    def rpc():
        value = source.json_read(source.RPC, body={'jsonrpc': '2.0', 'id': 1, 'method': 'eth_blockNumber', 'params': []})
        if (not isinstance(value, dict) or value.get('jsonrpc') != '2.0' or type(value.get('id')) is not int
                or value['id'] != 1 or 'error' in value or not re.fullmatch(r'0x[0-9a-fA-F]+', str(value.get('result')))):
            raise ValueError('invalid eth_blockNumber response')
        return {'block_number': int(value['result'], 16)}

    def book():
        value = reader.get(book_url)
        if value.get('asset_id') != token or value.get('market') != condition:
            raise ValueError('public book token/condition changed')
        if type(value.get('neg_risk')) is not bool:
            raise ValueError('invalid book neg_risk')
        for key in ('tick_size', 'min_order_size'):
            number = Decimal(str(value[key]))
            if not number.is_finite() or number <= 0:
                raise ValueError('invalid book rule')
        for side in ('bids', 'asks'):
            if not isinstance(value.get(side), list):
                raise ValueError('invalid book levels')
            for level in value[side]:
                price, size = Decimal(str(level['price'])), Decimal(str(level['size']))
                if not price.is_finite() or not size.is_finite() or not 0 <= price <= 1 or size < 0:
                    raise ValueError('invalid book price/size')
        return {'bids': len(value['bids']), 'asks': len(value['asks'])}

    def reward():
        value = reader.reward(condition)
        if value is None or source.reward_rate(value, datetime.now(timezone.utc)) <= 0:
            raise ValueError('condition is not currently rewarded')
        return {'condition_id': value['condition_id']}

    def positions():
        value = source.fetch_current_positions(public_address, condition, opener=opener, timeout_seconds=2)
        return {'row_count': value['row_count']}

    rows = []
    for contract, action in [('geoblock', geography), ('polygon_rpc', rpc), ('clob_book', book),
                             ('condition_rewards', reward), ('public_positions', positions)]:
        try:
            details = action()
            row = {'contract': contract, 'status': 'PASS', 'http_status': 200, **details}
        except Exception as exc:
            # No raw geoblock body/IP or public account details in output.
            row = {'contract': contract, 'status': 'FAIL', 'exception': type(exc).__name__,
                   'message': str(exc)[:200]}
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    print(json.dumps({'source_sha256': source.source_sha256, 'requests': len(opener.seen)}, sort_keys=True))
    return int(any(row['status'] == 'FAIL' for row in rows))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token', required=True)
    parser.add_argument('--condition', required=True)
    parser.add_argument('--public-address', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9]{1,78}', args.token):
        parser.error('token must be a decimal token identifier')
    if not re.fullmatch(r'0x[0-9a-f]{64}', args.condition):
        parser.error('condition must be a lowercase 32-byte hex identifier')
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', args.public_address):
        parser.error('public-address must be a 20-byte hex address')
    return run(token=args.token, condition=args.condition, public_address=args.public_address)


if __name__ == '__main__':
    raise SystemExit(main())
