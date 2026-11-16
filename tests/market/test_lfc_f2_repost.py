"""Inert multi-band driver through durable intents and full inventory proof.

Guards: B057 no unproved repost, cooldown, gross UTC-day cap, one sleeve and original evidence retention.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_breadth import cities, NOW
from tests.market.test_lfc_f2_controller import Account, MAKER, Raw, setup
from tests.market.test_lfc_f2_capital import filled
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, native
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_f2_breadth import example_policy, band_day_usage
from weather.market.lfc_f2_reconcile import prove, validate_live
from weather.market.lfc_recording_io import strict_json, write_new
from weather.market.mm_stage2_hold import HoldEnd, digest


def wire_trade(row, condition):
    return {'event_type': 'trade', 'id': 'fill-' + row['id'], 'market': condition,
        'asset_id': row['asset_id'], 'trader_side': 'MAKER', 'status': 'CONFIRMED',
        'maker_orders': [{'order_id': row['id'], 'asset_id': row['asset_id'],
            'maker_address': MAKER, 'side': 'BUY', 'price': row['price'],
            'matched_amount': row['size_matched']}]}


def campaign_stream(raw, *, retain=True):
    from weather.market.lfc_f2_runtime import stream_factory
    from weather.market.re1_attended import SecretGuard
    factory = getattr(raw, 'fixture_stream_factory', stream_factory({}, retain_trade_identity=retain))
    return factory(tokens=raw.memory.tokens, maker_address=MAKER, condition_id=raw.memory.condition,
        known_order_ids=set(raw.memory.orders), guard=SecretGuard(),
        api_key='inert-fixture', secret='inert-fixture', passphrase='inert-fixture',
        journal_path=raw.fixture_directory / 'inert-normalizer.jsonl',
        websocket_factory=lambda *a, **k: pytest.fail('No WebSocket in this fixture'))


def test_official_normalized_trade_identity_is_proved_and_replay_filtered(tmp_path):
    from weather.market.mm_official_adapter import normalize_official_user_event
    from weather.market.lfc_f2_repost import filtered_events
    band = SimpleNamespace(observed_trade_ids=set(), proven_trade_ids={'trade-1'},
        journal=SimpleNamespace(record=lambda *a, **k: None))
    raw = {'event_type': 'trade', 'id': 'trade-1', 'market': 'condition', 'asset_id': 'yes',
        'trader_side': 'MAKER', 'status': 'CONFIRMED', 'maker_orders': [
            {'order_id': 'order-1', 'asset_id': 'yes', 'maker_address': MAKER}]}
    normalized = normalize_official_user_event(raw, maker_address=MAKER,
        condition_id='condition', token_id='yes')
    assert filtered_events(band, normalized) == []
    assert band.observed_trade_ids == {'trade-1'}


@pytest.mark.parametrize('wire_type', ['trade', 'TRADE'])
def test_campaign_pair_stream_retains_exact_wire_trade_identity(tmp_path, wire_type):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    raw = account.raws[0]
    order = {'id': 'order-1', 'asset_id': raw.memory.tokens[0], 'price': '.30', 'size_matched': '20'}
    raw.memory.orders['order-1'] = order
    wire = wire_trade(order, raw.memory.condition)
    wire['event_type'] = wire_type
    normalized = campaign_stream(raw)._normalize_event(wire)
    assert normalized[0]['trade_id'] == 'fill-order-1'
    assert normalized[0]['order_id'] == 'order-1'
    legacy = campaign_stream(raw, retain=False)._normalize_event(wire)
    assert 'trade_id' not in legacy[0]


@pytest.mark.parametrize('event', [
    {'id': 'order-1'}, {}, {'trade_id': 1}, {'trade_id': ''},
    {'trade_id': 'proved', 'payload': {'id': 'different'}},
])
def test_missing_or_conflicting_trade_identity_is_evidence_fault_never_complete(tmp_path, event):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    raw = account.raws[0]
    ordinary = raw.events
    sent = []
    def events():
        rows = ordinary()
        if clock.seconds >= 12 and not sent:
            sent.append(True)
            rows.append(dict(event, official_event_type='trade', event_type='trade',
                             raw_event_sha256=digest(event)))
        return rows
    raw.events = events
    result = controller.run()
    assert sent and controller.bands[0].submits == 2
    assert 'repost_trade_identity_unproven' in controller.bands[0]._evidence_faults
    assert not result['cleanup_ok']
    assert status.finish(success=True)['state'] != 'COMPLETE'


def test_unmatched_payload_identity_cannot_be_confused_with_order_id():
    from weather.market.lfc_f2_repost import filtered_events
    band = SimpleNamespace(observed_trade_ids=set(), proven_trade_ids={'trade-1'},
        journal=SimpleNamespace(record=lambda *a, **k: None))
    event = {'event_type': 'unmatched_trade_event', 'official_event_type': 'trade',
             'payload': {'id': 'trade-1'}, 'id': 'different-order'}
    assert filtered_events(band, [event]) == []
    assert band.observed_trade_ids == {'trade-1'}


class FillingAccount(Account):
    def __init__(self, clock):
        super().__init__(clock)
        self.next_fill = 12
        self.fill_times = []
        self.fills_enabled = True

    def advance(self):
        if self.fills_enabled and self.raws and self.clock.seconds >= self.next_fill:
            raw = self.raws[0]
            rows = [row for row in raw.memory.orders.values() if row['status'] == 'LIVE']
            if rows:
                row = rows[0]
                row.update(status='MATCHED', size_matched=row['original_size'], associate_trades=['fill-' + row['id']])
                self.fill_times.append(self.clock.seconds)
                self.next_fill = self.clock.seconds + 63
        super().advance()


class FundedRaw(Raw):
    maker = MAKER
    def __init__(self, snapshot, directory, **kwargs):
        super().__init__(snapshot, directory, **kwargs)
        self.fixture_directory = directory

    def balances(self):
        spent = sum((Decimal(row['price']) * Decimal(row['size_matched'])
                     for raw in self.account.raws for row in raw.memory.orders.values()), Decimal(0))
        cash = Decimal(300) - spent
        return {'available_collateral': str(cash), 'assets': {ASSET: str(cash)},
                'collateral_evidence': {'balance': str(native(cash))}}

    def events(self):
        emitted = getattr(self, 'emitted', set())
        result = []
        for row in self.memory.orders.values():
            tid = 'fill-' + row['id']
            if Decimal(row['size_matched']) and tid not in emitted:
                emitted.add(tid)
                result.extend(campaign_stream(self)._normalize_event(wire_trade(row, self.memory.condition)))
        self.emitted = emitted
        return result

    def trades(self):
        return [{'id': 'fill-' + row['id'], 'status': 'CONFIRMED', 'maker_orders':
                 [{'order_id': row['id'], 'matched_amount': row['size_matched']} ]}
                for row in self.memory.orders.values() if Decimal(row['size_matched'])]


def fixture(tmp_path, *, k=2, enrolled=False, seconds=300, min_depth=None, policy_row=None):
    policy = deepcopy(policy_row) if policy_row is not None else example_policy()
    if min_depth is not None:
        policy['min_book_depth'] = min_depth
    controller, account, status, ledger, clock = setup(tmp_path, k=k, offset='0.015', policy_row=policy,
        universe_rows=cities(), account_type=FillingAccount, raw_type=FundedRaw, enrolled=enrolled,
        schedule={'max_session_seconds': seconds})
    runtime = object.__new__(Runtime)
    runtime.clock = clock
    runtime.pilot_root = tmp_path
    runtime.state = account.state or SimpleNamespace(maker=MAKER, ledger=ledger, root=tmp_path / 'state')
    if account.state is None:
        runtime.state.save = lambda name, row: write_new(runtime.state.root / name, row)
    def read():
        account.advance()
        when = clock.now().isoformat()
        positions = {}
        for raw in account.raws:
            for row in raw.memory.orders.values():
                if Decimal(row['size_matched']):
                    token = row['asset_id']
                    positions[token] = positions.get(token, Decimal(0)) + Decimal(row['size_matched'])
        start = int(NOW.timestamp())
        return {'schema_version': 'lfc_campaign_account_read_v0.1', 'complete': True, 'errors': [],
            'maker_address': MAKER, 'since': str(start), 'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
            'started_at_utc': when, 'ended_at_utc': when,
            'component_times': {key: {'started_at_utc': when, 'ended_at_utc': when}
                                for key in ('open_orders', 'trades', 'positions', 'balances', 'geography')},
            'open_orders': account.open_orders(), 'balances': account.raws[0].balances(),
            'trades': [row for raw in account.raws for row in raw.trades()],
            'positions': [{'asset': token, 'size': str(size)} for token, size in positions.items()],
            'geography': {'blocked': False}, 'terminal_orders': {leg['order_id']: {
                'row': next(raw for raw in account.raws if leg['order_id'] in raw.memory.orders).order(leg['order_id']),
                'started_at_utc': when, 'ended_at_utc': when} for leg in ledger.unresolved_legs() if leg['order_id']},
            'capital_activity': native_packet(read_activity(MAKER, start, int(clock.now().timestamp()),
                                get=lambda *args: packet(), sleep=lambda _: None))}
    controller.repost_proof = lambda band: prove(runtime, band, read())
    controller.verify = lambda: runtime.core_proof(ledger, read())
    return controller, account, status, ledger, clock, runtime, read


def test_proven_fill_reposts_after_cooldown_then_daily_cap_retires_only_its_band(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=900)
    result = controller.run()
    first = controller.bands[0]
    filled_legs = [ledger.legs[key] for key in ledger.sessions[first.session_id]['legs']
                   if Decimal(ledger.legs[key]['size_matched'])]
    assert len(filled_legs) >= 2 and first.submits == 2 * len(filled_legs), controller.results[first.session_id]
    assert controller.results[first.session_id]['reason'] == 'per_band_daily_filled_cap'
    assert controller.bands[1].submits == 2
    assert account.cancel_all_calls == [900]
    rows = [strict_json(line) for line in first.journal.path.read_bytes().splitlines()]
    proved = [row for row in rows if row['event'] == 'repost_inventory_proven']
    ready = [row for row in rows if row['event'] == 'repost_ready']
    assert len(ready) == len(filled_legs) - 1 and len(proved) >= 2 * len(ready)
    used = band_day_usage(ledger, first.scope['market_id'], '2026-11-11')['filled_native']
    assert used <= 40_000_000 < used + native(first.size * sum(first.reserve_prices()))
    for row in ready:
        prior = [p for p in proved if p['sequence'] < row['sequence']]
        first_proof = next(p for p in prior if p['sequence'] > max(
            [r['sequence'] for r in ready if r['sequence'] < row['sequence']], default=-1))
        from weather.market.mm_stage2_hold import utc
        assert (utc(row['recorded_at_utc']) - utc(first_proof['recorded_at_utc'])).total_seconds() >= 60
    assert result['cleanup_ok'], result
    outcome = status.finish(success=True)
    assert outcome['state'] == 'COMPLETE'
    from weather.market.lfc_campaign_proof import local_money_proof
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id=controller.attempt_id, outcome=outcome)
    assert proof['complete'] and not proof['unknown_submit'], proof


@pytest.mark.parametrize('kind', ['ack', 'private', 'inventory', 'unknown_status'])
def test_unproved_ack_fill_private_or_order_status_never_reposts(tmp_path, kind):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    if kind == 'ack':
        account.unknown_ack_band = 0
    else:
        normal = controller.repost_proof
        def refuse(band):
            if kind == 'inventory':
                return {'inventory_proven': False, 'unknown_submit': False}
            if kind == 'private':
                (band.directory / 'submit-1.ack.json').unlink()
                return normal(band)
            row = read()
            for value in row['terminal_orders'].values():
                value['row']['status'] = 'SOMETHING_NEW'
            return prove(runtime, band, row)
        controller.repost_proof = refuse
    controller.run()
    assert controller.bands[0].submits <= 2
    if kind == 'ack':
        assert ledger.unacknowledged_intents()
    if kind == 'private':
        assert not controller.cleanup_ok


def test_all_cities_share_intent_gate_and_original_hashes(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, k=12)
    account.fills_enabled = False
    result = controller.run()
    assert result['cleanup_ok'] and result['post_count'] == 24, result
    assert ledger.counted_sessions() == 1
    outcome = status.finish(success=True)
    assert len(outcome['bands']) == 12 and len(outcome['evidence_sha256']) == 114
    assert any(name.startswith('band-12/') for name in outcome['evidence_sha256'])
    from weather.market.lfc_campaign_proof import local_money_proof
    assert local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
        attempt_id=controller.attempt_id, outcome=outcome)['complete']
    assert len({row['quote_arm'] for row in ledger.rows if row['event'] == 'leg_intent'}) == 2


def test_twelve_bands_cannot_race_remaining_sleeve_after_a_stale_plan(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, k=12)
    account.fills_enabled = False
    for index in range(10):
        key = 'legacy-' + str(index)
        ledger.record('session_start', session_id=key, counted=True, market_id='toronto')
        ledger.intent(session_id=key, intent_key=key, token_id=key, condition_id='legacy',
                      price='.79', size='20', fee_rate_bps='0')
        ledger.ack(key, key)
        ledger.terminal(key, {'id': key, 'status': 'MATCHED', 'size_matched': '20'}, source='fixture')
        ledger.record('session_end', session_id=key)
    maximum = []
    original = ledger.intent
    def intent(**kwargs):
        result = original(**kwargs)
        maximum.append(CapitalBook(ledger).figures()['charged_native'])
        return result
    ledger.intent = intent
    controller.run()
    assert maximum and max(maximum) <= 300_000_000
    assert any(row['reason'] == 'capital_total_ceiling' for row in controller.results.values())
    assert sum(b.submits for b in controller.bands) < 24


def test_band_twelve_original_loss_remains_sticky_after_reboot(tmp_path):
    from tests.market.test_lfc_campaign import Mutexes
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_campaign_state import AccountState, StateRefused
    from weather.market.lfc_campaign_proof import local_money_proof
    from weather.market.lfc_ledger import Ledger
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, k=12, enrolled=True)
        account.fills_enabled = False
        assert controller.run()['cleanup_ok']
        outcome = status.finish(success=True)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id=controller.attempt_id, outcome=outcome)
        runtime.pilot_root = tmp_path
        result = {'session_id': controller.session_id, 'private_evidence_directory': controller.directory.name,
                  'outcome': outcome, 'local_money_proof': local}
        runtime.save_result(account.claim, result)
        runtime.state.retained_result(account.claim)
        artifact = controller.bands[11].directory / 'submit-1.ack.json'
        artifact.unlink()
        with pytest.raises(StateRefused, match='retained_private_evidence_fault'):
            runtime.state.retained_result(account.claim)
        reboot = AccountState(tmp_path / 'state', Ledger.open(ledger.path, clock=clock.now))
        assert reboot.incidents() and account.claim['local_date'] in reboot.consumed_dates()


@pytest.mark.parametrize('status', ['LIVE', 'UNKNOWN', '', None])
def test_old_order_event_needs_validated_terminal_status_even_after_a_fill_proof(status):
    """B058: terminal status is proved by the ledger, not a delayed WS frame."""
    from weather.market.lfc_f2_repost import filtered_events
    leg = {'session_id': 'band', 'status': 'terminal', 'size_matched': '0', 'size': '20'}
    band = SimpleNamespace(session_id='band', ledger=SimpleNamespace(by_order={'oid': 'key'}, legs={'key': leg}),
                           journal=SimpleNamespace(record=lambda *a, **k: None))
    assert filtered_events(band, [{'id': 'oid', 'status': status, 'size_matched': '0'}]) == []
    assert filtered_events(band, [{'id': 'oid', 'status': 'CANCELED', 'size_matched': '0'}]) == []


def test_buffered_trade_missing_from_complete_read_never_reposts(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=900)
    raw = account.raws[0]
    ordinary = raw.events
    sent = []
    def events():
        rows = ordinary()
        if clock.seconds >= 25 and not sent:
            sent.append(True)
            rows.append({'official_event_type': 'trade', 'event_type': 'trade',
                'condition_id': raw.memory.condition, 'trade_id': 'unproved-trade',
                'raw_event_sha256': digest('unproved-trade')})
        return rows
    raw.events = events
    controller.run()
    first = controller.bands[0]
    assert sent and first.submits == 2
    assert 'unproved-trade' in first.observed_trade_ids
    assert 'repost_inventory_unavailable' in first._evidence_faults


def test_peer_requotes_before_first_fill_and_filled_band_still_reposts(tmp_path, monkeypatch):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=360)
    account.next_fill = 90
    ordinary = account.advance
    def advance():
        if clock.seconds >= 40:
            account.raws[1].memory.public_input['quote_inputs'].update(
                yes_bids=[{'price': '.35', 'size': '300'}], yes_asks=[{'price': '.37', 'size': '300'}],
                no_bids=[{'price': '.63', 'size': '300'}], no_asks=[{'price': '.65', 'size': '300'}])
        ordinary()
    monkeypatch.setattr(account, 'advance', advance)
    result = controller.run()
    first, peer = controller.bands
    assert peer.requotes > 0 and account.fill_times[0] >= 90
    assert first.submits > 2, (result, controller.results)
    assert account.cancel_all_calls == [360]
    rows = [strict_json(line) for line in peer.journal.path.read_bytes().splitlines()]
    terminals = {r['order']['id'] for r in rows if r['event'] == 'terminal_order'}
    assert set(peer.known) <= terminals


def test_peer_private_proof_gap_waits_and_retries_without_account_teardown(tmp_path, monkeypatch):
    from weather.market import lfc_f2_repost
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=300)
    peer = controller.bands[1]
    original = lfc_f2_repost.private_fill_proof
    refused = []
    def private(band, **kwargs):
        if band is peer and not refused:
            refused.append(clock.seconds)
            raise ValueError('synthetic_peer_packet_not_yet_readable')
        return original(band, **kwargs)
    monkeypatch.setattr(lfc_f2_repost, 'private_fill_proof', private)
    result = controller.run()
    assert refused and controller.bands[0].submits > 2
    assert account.cancel_all_calls == [300]
    assert result['cleanup_ok'], result
