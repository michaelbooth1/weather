"""Closed in-memory exchange for public-book rehearsals. No live adapter or signer.

Only the public reader can use the network. Each rehearsal replays one captured
book at accelerated time, adding simulated resting size. It measures controller
behavior, not actual visibility, earnings, eligibility, fills or trading readiness.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
import json

from weather.market.mm_geographic_eligibility import PHYSICAL_LOCATION_CONFIRMATION, check_geographic_eligibility
from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as PROFILE
from weather.market.mm_live_lifecycle_probe import _validate_bootstrap_binding
from weather.market.mm_stage2_hold import CONFIRMATION, SCHEMA_VERSION, digest, run_hold_session, utc, write_new
from weather.market.mm_stage2_selection import PublicBooks, validate_selection
from weather.market.reward_quote import _decimal


MAKER = '0x' + '0' * 39 + '1'  # A public fixture label, never a wallet lookup.


class ReplayClock:
    def __init__(self, start):
        self.start, self.seconds = utc(start), 0.0
    def now(self): return self.start + timedelta(seconds=self.seconds)
    def monotonic(self): return self.seconds
    def sleep(self, seconds): self.seconds += seconds


class MemoryVenue:
    def __init__(self, snapshot, root, *, scenario='rest'):
        if scenario not in {'rest', 'fill_first', 'reject_second'}:
            raise ValueError('unknown in-memory exchange scenario')
        self.scenario = scenario
        self.public_input = deepcopy(snapshot)
        self.clock = ReplayClock(snapshot['observed_at_utc'])
        self.root, self.orders, self.beat = Path(root), {}, None
        self.condition, self.tokens = snapshot['condition_id'], tuple(snapshot['token_ids'])

    def advance(self):
        if self.scenario == 'fill_first' and self.clock.seconds >= 12 and self.orders:
            row = next(iter(self.orders.values()))
            row.update(status='MATCHED', size_matched='1', associate_trades=['rehearsal-fill'])

    def snapshot(self, *, checkpoint=lambda: None):
        checkpoint()
        snapshot = deepcopy(self.public_input)
        snapshot['observed_at_utc'] = self.clock.now().isoformat()
        for row in self.orders.values():
            if row['status'] != 'LIVE': continue
            side = 'yes' if row['asset_id'] == self.tokens[0] else 'no'
            other = 'no' if side == 'yes' else 'yes'
            snapshot['quote_inputs'][side + '_bids'].append({'price': row['price'], 'size': row['original_size']})
            snapshot['quote_inputs'][other + '_asks'].append({'price': str(1 - Decimal(row['price'])), 'size': row['original_size']})
        return snapshot

    def geography(self):
        class Response:
            status = 200
            headers = {'Content-Type': 'application/json'}
            def geturl(self): return 'https://polymarket.com/api/geoblock'
            def read(self, _limit): return b'{"blocked":false,"country":"US","region":"","ip":"203.0.113.1"}'
            def close(self): pass
        return check_geographic_eligibility(self.root / 'fixture-geography' / f'{self.clock.seconds}.json',
            confirmation=PHYSICAL_LOCATION_CONFIRMATION, physical_location_eligible=True, no_circumvention=True,
            clock=self.clock.now, opener=lambda *_a, **_k: Response())


class MemoryAdapter:
    """Fake exchange boundary with exact, single-use, two-token constraints.

    This class cannot accept a client, credential, transport, signer or grant.
    The hold controller explicitly rejects it in live mode. Real capability and
    authorization controls are qualified separately against the official adapter.
    """
    supports_trading = False
    sdk_version = 'inert-rehearsal'
    envelope = PROFILE
    maker_address = MAKER

    def __init__(self, venue, token):
        if type(venue) is not MemoryVenue or token not in venue.tokens:
            raise ValueError('rehearsal requires its closed in-memory venue')
        self.client = self.heartbeat_sender = venue
        self.condition_id, self.token_id = venue.condition, token
        self.capability, self.consumed, self.deadline = None, False, None

    def authorize_stage1_lifecycle(self, gate, *, submit_deadline_utc):
        _validate_bootstrap_binding(self, gate)
        if self.capability is not None or gate.get('isolated_pilot_wallet') is not True or 'pilot_capital_mode' in gate:
            raise RuntimeError('rehearsal capability is single-use and isolated')
        self.deadline = utc(submit_deadline_utc)
        if self.client.clock.now() >= self.deadline:
            raise RuntimeError('rehearsal deadline elapsed')
        self.capability = object()
        return self.capability

    def heartbeat(self): self.client.beat = self.client.clock.seconds
    def accept_shared_stage2_heartbeat(self, source):
        if source.client is not self.client or source.token_id == self.token_id or self.client.beat is None:
            raise RuntimeError('rehearsal heartbeat is not shared by the exact pair')
    def user_events(self): return []
    def account_trades(self):
        self.client.advance()
        return [{'id': 'rehearsal-fill'}] if any(r['size_matched'] != '0' for r in self.client.orders.values()) else []
    def open_orders(self):
        self.client.advance()
        return deepcopy([r for r in self.client.orders.values() if r['status'] == 'LIVE'])
    def get_order(self, order_id):
        self.client.advance()
        return deepcopy(self.client.orders[order_id])
    def positions(self): return []
    def position_evidence(self, rows):
        return {'status': 'OBSERVED', 'query_scope': 'exact_maker_condition', 'maker_address': MAKER,
            'condition_id': self.condition_id, 'rows': list(rows), 'http_status': 200, 'response_sha256': digest(rows),
            'request_url': 'https://data-api.polymarket.com/positions?' + urlencode(
                {'user': MAKER, 'market': self.condition_id, 'sizeThreshold': 0, 'limit': 500, 'offset': 0})}
    def refresh_balance_allowance(self): return {'balance': '50000000', 'allowances': {'inert': '100000000'}}
    def refresh_market_rules(self): return deepcopy(self.client.public_input['rules'][self.token_id])

    def place_order(self, order, *, stage1_capability, geographic_eligibility_fresh_until_utc):
        if self.capability is None or stage1_capability is not self.capability or self.consumed:
            raise RuntimeError('rehearsal capability is absent, foreign or spent')
        self.consumed = True
        if self.client.scenario == 'reject_second' and len(self.client.orders) == 1:
            raise RuntimeError('in-memory second-leg rejection')
        now = self.client.clock.now()
        price, size = _decimal(order['price']), _decimal(order['size'])
        rules = self.refresh_market_rules()
        side = 'yes' if self.token_id == self.client.tokens[0] else 'no'
        ask = min(_decimal(r['price']) for r in self.client.public_input['quote_inputs'][side + '_asks'])
        if (order['token_id'] != self.token_id or order['side'] != 'BUY' or order['post_only'] is not True
                or size != 20 or price * size > PROFILE.per_order_pusd or not 0 < price < ask
                or price % _decimal(rules['tick_size']) or size < _decimal(rules['min_order_size'])
                or _decimal(rules['fee_rate_bps']) < 0 or len(self.client.orders) >= 2
                or now >= self.deadline or now >= utc(geographic_eligibility_fresh_until_utc)
                or self.client.beat is None or self.client.clock.seconds - self.client.beat > 7.5):
            raise RuntimeError('rehearsal submit boundary refused')
        oid = f'rehearsal-order-{len(self.client.orders) + 1}'
        self.client.orders[oid] = {'id': oid, 'asset_id': self.token_id, 'market': self.condition_id,
            'maker_address': MAKER, 'side': 'BUY', 'price': str(price), 'original_size': str(size),
            'size_matched': '0', 'status': 'LIVE', 'associate_trades': []}
        return {'order_id': oid}

    def cancel_all(self):
        canceled = []
        for row in self.client.orders.values():
            if row['status'] == 'LIVE': row['status'] = 'CANCELED'; canceled.append(row['id'])
        return {'canceled': canceled, 'not_canceled': {}}


def rehearse_table(table, condition, output_root, *, scenario='rest'):
    """Exercise any eligible row; only the first-ranked row could later be sealed."""
    if table.get('selected_condition_id'):
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        validate_selection(table, expected_sha256=digest(table), condition_id=table['selected_condition_id'],
            token_ids=selected['token_ids'], now=table['created_at_utc'])
    row = next((r for r in table['rows'] if r['condition_id'] == condition and r['eligible']), None)
    root = Path(output_root)
    write_new(root / 'selection.json', table)
    if not table['universe_complete'] or row is None:
        write_new(root / 'bundle.json', {'schema_version': SCHEMA_VERSION, 'kind': 'session',
            'mode': 'rehearsal', 'status': 'REFUSED', 'condition_id': condition, 'selection_sha256': digest(table),
            'reason': 'condition is not in the complete eligible rehearsal table', 'live_evidence': False,
            'simulated_submits': 0, 'grant_file_created': False})
        raise ValueError('condition is not in the complete eligible rehearsal table')
    venue = MemoryVenue(row['snapshot'], root, scenario=scenario)
    adapters = [MemoryAdapter(venue, token) for token in venue.tokens]
    gates = [{'required': True, 'ok': True, 'schema_version': 'mm_platform_bootstrap_v0.6', 'status': 'PASS',
        'platform': 'polymarket_global', 'settlement_unit': 'pUSD', 'token_id': token, 'condition_id': condition,
        'funder_address': MAKER, 'sdk_version': MemoryAdapter.sdk_version, 'isolated_pilot_wallet': True,
        'pilot_wallet_max_funding_usdc': 100, 'requested_budget_usdc': 10,
        'account_snapshot_sha256': digest({'fixture': True, 'token': token}), 'checks': {'inert_fixture': True}, 'missing': []}
        for token in venue.tokens]
    scope = {'profile_sha256': PROFILE.sha256, 'selection_sha256': digest(table), 'condition_id': condition,
        'token_ids': list(venue.tokens), 'maker_address': MAKER,
        'end_at_utc': (venue.clock.now() + timedelta(seconds=125)).isoformat(),
        'public_input_mode': 'single_observation_replay', 'public_input_sha256': digest(row['snapshot']),
        'scenario': scenario,
        'selected_for_live': table['selected_condition_id'] == condition}
    result = run_hold_session(adapters, gates, scope=scope, initial_public=venue.snapshot(), public_reader=venue.snapshot,
        geography_reader=venue.geography, journal_path=root / 'journal.jsonl', prediction_path=root / 'prediction.json',
        confirmation=CONFIRMATION, operator_stop=lambda: False, scoring_reader=lambda ids: dict.fromkeys(ids, True),
        utc_clock=venue.clock.now, monotonic_clock=venue.clock.monotonic, sleeper=venue.clock.sleep, mode='rehearsal')
    if not result['cleanup_ok'] or not result['cancel_acknowledged'] or adapters[0].open_orders():
        raise RuntimeError('NO-GO: rehearsal cancellation did not leave zero orders')
    write_new(root / 'bundle.json', {'schema_version': SCHEMA_VERSION, 'kind': 'session',
        'mode': 'rehearsal', 'status': 'PASS', 'condition_id': condition,
        'selection_sha256': digest(table), 'prediction_sha256': digest(result), 'journal_sha256': result['journal_sha256'],
        'public_input_mode': scope['public_input_mode'], 'scenario': scenario, 'live_evidence': False,
        'simulated_submits': len(venue.orders), 'grant_file_created': False})
    return result


def main(argv=None):
    import argparse
    from weather.paths import data_path
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    rehearsal = commands.add_parser('rehearse')
    rehearsal.add_argument('--condition', required=True)
    rehearsal.add_argument('--out', type=Path)
    rehearsal.add_argument('--scenario', choices=('rest', 'fill_first', 'reject_second'), default='rest')
    rehearsal.add_argument('--public-capture', type=Path, help='replay a complete retained public selection at its captured time')
    collect = commands.add_parser('collect', help='reconcile retained next-day evidence without account access')
    collect.add_argument('--predictions', type=Path, required=True, help='JSON list of prediction/journal paths and exact prediction hashes')
    collect.add_argument('--payment-evidence', type=Path, required=True)
    collect.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'collect':
        from weather.market.mm_stage2_rewards import load_frozen_predictions, verdict
        predictions = load_frozen_predictions(json.loads(args.predictions.read_bytes()), now=datetime.now(timezone.utc))
        result = verdict(predictions, payment_evidence=json.loads(args.payment_evidence.read_bytes()))
        write_new(args.out, result)
        print(json.dumps({'verdict': result['verdict'], 'output': str(args.out)}, sort_keys=True))
        return 0
    table = json.loads(args.public_capture.read_bytes()) if args.public_capture else PublicBooks().selection()
    root = args.out or data_path('research/stage2-hold-rehearsal', datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    result = rehearse_table(table, args.condition, root, scenario=args.scenario)
    print(json.dumps({'mode': result['mode'], 'cleanup_ok': result['cleanup_ok'], 'output_root': str(root),
                      'live_evidence': False, 'grant_file_created': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
