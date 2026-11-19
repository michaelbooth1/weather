"""F2 proof continuity through typed terminal-read gaps, using inert venues only.

Guards: named terminal facts, all-band result timing, and retry budget semantics.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_controller import MAKER, setup
from tests.market.test_lfc_f2_evidence import runtime_at_controller
from tests.market.test_lfc_f2_repost import campaign_stream
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_reads import TerminalBackfillRefused, account_read_age, terminal_result_time
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_capital import ASSET, SCALE, CapitalBook, native
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('case', ['recovered', 'unreadable', 'wrong_order', 'wrong_quantity'])
def test_postcheck_needs_an_exact_get_for_missing_private_terminal_order(tmp_path, monkeypatch, case):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
        raw = account.raws[0]
        original_read = raw.order
        missing = []

        def order(oid):
            if clock.seconds >= 300 and (not missing or oid == missing[0]):
                if not missing:
                    missing.append(oid)
                raise TimeoutError('synthetic in-band read gap')
            return original_read(oid)

        raw.order = order
        if case == 'wrong_quantity':
            original_verify = controller.verify

            def verify():
                # Independent terminal proof already booked the order. Its
                # missing journal observation still needs an exact later GET.
                ledger.terminal(missing[0], original_read(missing[0]), source='fixture_reconcile')
                return original_verify()

            controller.verify = verify
        controller.run()
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        result = runtime.session_result(account.claim, status, status.finish(success=False), 1)
        assert result['local_money_proof']['complete']
        assert result['local_money_proof']['missing_terminal_orders'] == missing
        runtime.save_result(account.claim, result)
        saved = runtime.saved_result(account.claim)
        assert runtime.state.incidents() == []
        original_hash = file_sha(controller.bands[0].journal.path)
        outcome_hash = file_sha(runtime.state.root / 'results' / (controller.attempt_id + '.json'))
        read = runtime.read_account
        calls = []

        def get(oid):
            calls.append(clock.seconds)
            if case == 'unreadable' or (case == 'recovered' and len(calls) < 3):
                raise TimeoutError('synthetic postcheck transport gap')
            row = original_read(oid)
            if case == 'wrong_order':
                return dict(row, id='unrelated-order')
            if case == 'wrong_quantity':
                return dict(row, size_matched='11')
            return row

        def account_get(*, terminal_order_ids):
            assert terminal_order_ids == missing
            begin = clock.now()
            observations = runtime.read_missing_terminal_orders(SimpleNamespace(order=get), terminal_order_ids)
            packet = read()
            packet['started_at_utc'] = begin.isoformat()
            packet['terminal_orders'] = observations
            return packet

        monkeypatch.setattr(runtime, 'read_account', account_get)
        if case == 'recovered':
            proof = runtime.postcheck(account.claim, saved)
            assert [n - calls[0] for n in calls] == [0, 1, 3]
            assert proof['cleanup_proven'] and proof['money_accounting_complete']
            assert proof['research_evidence_complete'] is False
            invalid = dict(proof)
            invalid.pop('account_read')
            with pytest.raises(StateRefused, match='closeout_terminal_backfill_digest'):
                runtime.state.close(account.claim, invalid, clock.now())
            runtime.state.close(account.claim, proof, clock.now())
            state = AccountState(runtime.state.root.parent, Ledger.open(ledger.path, clock=clock.now))
            state.require_retained_evidence()
            assert state.pending() == [] and state.incidents() == []
        else:
            head = runtime.state.ledger.previous
            with pytest.raises(TerminalBackfillRefused):
                runtime.postcheck(account.claim, saved)
            assert runtime.state.ledger.previous == head and runtime.state.incidents() == []
            assert len(calls) == (3 if case == 'unreadable' else 1)
            calls.clear()
            campaign = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=clock,
                                           control_root=tmp_path / "control")
            assert campaign.pending()
            assert len(calls) == (3 if case == 'unreadable' else 1)
            fault, = runtime.state.incidents()
            calls.clear()
            assert campaign.pending()
            assert calls == [] and runtime.state.incidents() == [fault]
            assert fault['artifact'] == 'private-terminal-backfill'
            assert not (runtime.state.root / 'closed' / (controller.attempt_id + '.json')).exists()
        assert file_sha(controller.bands[0].journal.path) == original_hash
        assert file_sha(runtime.state.root / 'results' / (controller.attempt_id + '.json')) == outcome_hash


def test_owner_auto_redeem_finishes_via_account_proof_and_foreign_notice_still_refuses(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    raw = account.raws[0]
    raw.fixture_directory = tmp_path
    raw.maker = MAKER
    notice = {'event_type': 'auto_redeem', 'proxy_wallet': MAKER,
              'txn_hash': '0x' + '1' * 64, 'condition_id': '0x' + '2' * 64}
    stream = campaign_stream(raw)
    with pytest.raises(RuntimeError, match='unknown_account_event'):
        stream._normalize_event(dict(notice, proxy_wallet='0x' + 'f' * 40))
    with pytest.raises(RuntimeError, match='unknown_account_event'):
        stream._normalize_event(dict(notice, order_id='unexpected-order'))
    marker = stream._normalize_event(notice)
    assert marker[0]['event_type'] == 'account_redemption_notice'
    assert set(marker[0]) == {'event_type', 'raw_event_sha256'}
    raw.events = lambda: marker if clock.seconds >= 12 else []
    result = controller.run()
    assert result['reason'] == 'account_redemption_notice'
    assert result['cleanup_ok'] and result['inventory_proven']
    assert ledger.unresolved_legs() == []
    from weather.market.lfc_campaign_proof import local_money_proof
    local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                              attempt_id=controller.attempt_id, outcome=status.finish(success=True),
                              terminal_backfill=True)
    assert local['complete'] and not local.get('missing_terminal_orders')


@pytest.mark.parametrize(('fields', 'booked', 'verdict'), [
    ({}, False, 'accept'),
    ({'order_id': 'expected', 'id': None}, False, 'accept'),
    ({'orderID': 'expected'}, False, 'accept'),
    ({'orderID': 'expected', 'id': None}, False, 'identity'),
    ({'orderID': 'different'}, False, 'identity'),
    ({'original_size': '21'}, False, 'quantity'),
    ({'original_size': 'bad'}, False, 'quantity'),
    ({'size_matched': '-1'}, False, 'quantity'),
    ({'size_matched': '21'}, False, 'quantity'),
    ({'size_matched': 'bad'}, False, 'quantity'),
    ({'size_matched': None}, False, 'quantity'),
    ({'status': 'LIVE', 'size_matched': '21'}, False, 'quantity'),
    ({'official_order_status': 'LIVE'}, False, 'status'),
    ({'official_order_status': 'cancelled'}, False, 'accept'),
    ({'official_order_status': 'CANCELED', 'status': None}, False, 'accept'),
    ({'size_matched': '1'}, True, 'quantity'),
    ({'status': None, 'size_matched': '1'}, True, 'quantity'),
    ({'status': None}, True, 'retry'),
    ({'status': 'LIVE'}, True, 'status'),
    ({'status': 'LIVE'}, False, 'retry'),
    ({'status': None, 'size_matched': None}, False, 'quantity'),
])
def test_named_sdk_facts_distinguish_pending_from_contradiction(fields, booked, verdict):
    from tests.market.test_lfc_f2_controller import NOW
    from tests.market.test_lfc_pilot import Clock

    oid = 'expected'
    leg = {'order_id': oid, 'token_id': 'yes', 'condition_id': 'condition',
           'size': '20', 'size_matched': '0', 'price': '.40', 'status': 'terminal' if booked else 'open'}
    ledger = SimpleNamespace(by_order={oid: 'intent'}, legs={'intent': leg})
    before = deepcopy(leg)
    clock = Clock(NOW)
    runtime = SimpleNamespace(clock=clock, state=SimpleNamespace(ledger=ledger))
    # Sanitized pinned SDK OpenOrder GET shape (test_re1_sdk_shapes.sdk_order).
    # Sparse GET fields are also accepted when the durable intent binds them.
    good = {'id': oid, 'asset_id': 'yes', 'market': 'condition', 'side': 'BUY', 'price': '.40',
            'status': 'CANCELED', 'original_size': '20', 'size_matched': '0'}
    response = {key: val for key, val in {**good, **fields}.items() if val is not None or key == 'size_matched'}
    get = Mock(side_effect=[response, good])
    if verdict in {'accept', 'retry'}:
        rows = Runtime.read_missing_terminal_orders(runtime, SimpleNamespace(order=get), [oid])
        assert rows[oid]['row'] == (good if verdict == 'retry' else response)
        assert get.call_count == (2 if verdict == 'retry' else 1)
    else:
        with pytest.raises(TerminalBackfillRefused, match='terminal_order_backfill_' + verdict):
            Runtime.read_missing_terminal_orders(runtime, SimpleNamespace(order=get), [oid])
        get.assert_called_once_with(oid)
    assert leg == before


def two_band_backfill(tmp_path, monkeypatch, *, booked):
    controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
    originals = {}
    missing = []
    for raw in account.raws:
        original = raw.order

        # One skipped order per band. The original works for postcheck.
        def for_band(original):
            selected = []
            def read(oid):
                if clock.seconds >= 300:
                    if not selected:
                        selected.append(oid)
                        missing.append(oid)
                        originals[oid] = original
                    if oid == selected[0]:
                        raise TimeoutError('synthetic in-band read gap')
                return original(oid)
            return read

        raw.order = for_band(original)

    finish = controller.finish_band
    def finish_band(band, result):
        finish(band, result)
        clock.sleep(3)

    controller.finish_band = finish_band
    controller.run()
    assert len(missing) == 2
    if booked:
        for oid in missing:
            ledger.terminal(oid, originals[oid](oid), source='fixture_reconcile')
    runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
    result = runtime.session_result(account.claim, status, status.finish(success=False), 1)
    assert result['local_money_proof']['complete']
    assert set(result['local_money_proof']['missing_terminal_orders']) == set(missing)
    clock.sleep(3)
    runtime.save_result(account.claim, result)
    result_at = terminal_result_time(runtime.state.ledger, account.claim['attempt_id'])
    missing.sort(key=lambda oid: ledger.sessions[ledger.legs[ledger.by_order[oid]]['session_id']]['end']['recorded_at_utc'])
    ends = [datetime.fromisoformat(ledger.sessions[ledger.legs[ledger.by_order[oid]]['session_id']]
                                 ['end']['recorded_at_utc']) for oid in missing]
    assert ends[0] < ends[1] < result_at
    return runtime, account.claim, runtime.saved_result(account.claim), clock, result_at, missing, ends, originals


@pytest.mark.parametrize(('frontier', 'bad_index', 'booked'), [
    ('before_own_end', 0, False),
    ('between_band_ends', 0, False),
    ('before_result', 0, False),
    ('before_result', 1, False),
    ('before_result', 1, True),
    ('at_result', None, False),
    ('after_result', None, False),
    ('after_result', None, True),
])
def test_postcheck_stages_every_band_at_the_result_anchor(tmp_path, monkeypatch, frontier, bad_index, booked):
    with account_lease(MAKER, backend=Mutexes()):
        fixture = two_band_backfill(tmp_path, monkeypatch, booked=booked)
        runtime, claim, result, clock, result_at, missing, ends, originals = fixture
        clock.sleep(8)
        times = {'before_own_end': ends[0] - timedelta(seconds=1),
                 'between_band_ends': ends[0] + (ends[1] - ends[0]) / 2,
                 'before_result': ends[1] + (result_at - ends[1]) / 2,
                 'at_result': result_at, 'after_result': result_at + timedelta(seconds=1)}
        read = timed_postcheck_read(runtime, missing, originals,
            [times[frontier] if bad_index is None or index == bad_index else result_at
             for index, oid in enumerate(missing)])
        monkeypatch.setattr(runtime, 'read_account', lambda **kw: read)
        ledger = runtime.state.ledger
        before, legs, head = ledger.path.read_bytes(), deepcopy(ledger.legs), ledger.previous
        if bad_index is not None:
            with pytest.raises(TerminalBackfillRefused, match='terminal_order_backfill_binding'):
                runtime.postcheck(claim, result)
            assert runtime.state.ledger.previous == head
            assert runtime.state.ledger.legs == legs and ledger.path.read_bytes() == before
            assert not list((runtime.state.root / 'postchecks').glob('*.json'))
            return

        proof = runtime.postcheck(claim, result)
        assert proof['cleanup_proven'] and proof['money_accounting_complete']
        assert proof['terminal_backfill_result_at_utc'] == result_at.isoformat()
        tampered = deepcopy(proof)
        tampered['account_read']['started_at_utc'] = ends[0].isoformat()
        tampered['account_read']['terminal_orders'][missing[0]]['started_at_utc'] = ends[0].isoformat()
        tampered['read_sha256'] = digest(tampered['account_read'])
        with pytest.raises(TerminalBackfillRefused, match='terminal_order_backfill_binding'):
            runtime.state.close(claim, tampered, clock.now())

        old_receipt = dict(tampered)
        del old_receipt['terminal_backfill_result_at_utc']
        _, sha, local = runtime.state.retained_result(claim)
        runtime.state.validate_postcheck_binding(old_receipt, sha, local,
                                                 attempt=claim['attempt_id'], closed_at=clock.now())
        with pytest.raises(StateRefused, match='closeout_terminal_backfill_result_anchor'):
            runtime.state.close(claim, old_receipt, clock.now())
        runtime.state.close(claim, proof, clock.now())
        clock.sleep(180)
        state = AccountState(runtime.state.root.parent, Ledger.open(ledger.path, clock=clock.now))
        state.require_retained_evidence()
        assert state.pending() == [] and state.incidents() == []


def timed_postcheck_read(runtime, missing, originals, times):
    packet = runtime.read_account()
    # The outer envelope can start earlier than every named GET, e.g. from a
    # separately cached geography component. Geography is inert in this fixture.
    packet['started_at_utc'] = (min(times) - timedelta(seconds=1)).isoformat()
    packet['terminal_orders'] = {
        oid: {'row': originals[oid](oid), 'started_at_utc': start.isoformat(), 'ended_at_utc': start.isoformat()}
        for oid, start in zip(missing, times)}
    return packet


def test_money_retry_checks_replacement_packet_before_proof(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        fixture = two_band_backfill(tmp_path, monkeypatch, booked=True)
        runtime, claim, result, clock, result_at, missing, ends, originals = fixture
        clock.sleep(8)
        good = timed_postcheck_read(runtime, missing, originals, [result_at, result_at])
        bad = timed_postcheck_read(runtime, missing, originals, [result_at, ends[1]])
        read = Mock(side_effect=[good, bad])
        proof = Mock(return_value={'money_contradiction': True})
        monkeypatch.setattr(runtime, 'read_account', read)
        monkeypatch.setattr(runtime, 'core_proof', proof)
        ledger = runtime.state.ledger
        before, head, legs = ledger.path.read_bytes(), ledger.previous, deepcopy(ledger.legs)
        with pytest.raises(TerminalBackfillRefused, match='terminal_order_backfill_binding'):
            runtime.postcheck(claim, result)
        assert read.call_count == 2 and proof.call_count == 1
        assert runtime.state.ledger.previous == head and runtime.state.ledger.legs == legs
        assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('booked', [True, False])
def test_aged_named_get_vs_fresh_account_components(tmp_path, monkeypatch, booked):
    with account_lease(MAKER, backend=Mutexes()):
        fixture = two_band_backfill(tmp_path, monkeypatch, booked=booked)
        runtime, claim, result, clock, result_at, missing, ends, originals = fixture
        clock.sleep(121)
        packet = timed_postcheck_read(runtime, missing, originals, [result_at, result_at])
        assert account_read_age(packet, clock.now()) == 0
        monkeypatch.setattr(runtime, 'read_account', lambda **kw: packet)
        if booked:
            assert runtime.postcheck(claim, result)['money_accounting_complete']
        else:
            head = runtime.state.ledger.previous
            with pytest.raises(TerminalBackfillRefused, match='terminal_order_backfill_binding'):
                runtime.postcheck(claim, result)
            assert runtime.state.ledger.previous == head


def test_named_get_admitted_before_deadline_may_finish_after_it():
    from tests.market.test_lfc_f2_controller import NOW
    from tests.market.test_lfc_pilot import Clock

    clock = Clock(NOW)
    by_order = {oid: oid for oid in ('one', 'two', 'three')}
    legs = {oid: {'token_id': 'yes', 'condition_id': 'c', 'price': '.40', 'size': '20',
                  'status': 'terminal', 'size_matched': '0'} for oid in by_order}
    runtime = SimpleNamespace(clock=clock, state=SimpleNamespace(ledger=SimpleNamespace(by_order=by_order, legs=legs)))
    admitted = []
    def get(oid):
        admitted.append((oid, clock.seconds))
        clock.sleep(89 if oid == 'one' else 6)
        return {'id': oid, 'size_matched': '0', 'status': 'CANCELED'}

    venue = SimpleNamespace(order=get)
    packet = Runtime.read_missing_terminal_orders(runtime, venue, ['one', 'two'])
    assert admitted == [('one', 0), ('two', 89)]
    assert packet['two']['ended_at_utc'] == (NOW + timedelta(seconds=95)).isoformat()
    clock.seconds = 0
    admitted.clear()
    with pytest.raises(TerminalBackfillRefused, match='terminal_order_backfill_deadline'):
        Runtime.read_missing_terminal_orders(runtime, venue, ['one', 'two', 'three'])
    assert admitted == [('one', 0), ('two', 89)]


def terminal_ledger_snapshot(ledger):
    return (ledger.previous, file_sha(ledger.path), ledger.path.read_bytes(),
            deepcopy(ledger.legs), ledger.L_resting(), CapitalBook(ledger).figures()['resting_reserve_native'])


@pytest.mark.parametrize('packet_case', ['stale_component', 'missing_component', 'malformed_trade', 'valid_matched'])
def test_postcheck_preflights_account_before_writing_pending_terminals(tmp_path, monkeypatch, packet_case):
    with account_lease(MAKER, backend=Mutexes()):
        fixture = two_band_backfill(tmp_path, monkeypatch, booked=False)
        runtime, claim, result, clock, result_at, missing, _, originals = fixture
        clock.sleep(8)
        read = timed_postcheck_read(runtime, missing, originals, [result_at, result_at])
        ledger = runtime.state.ledger
        before = terminal_ledger_snapshot(ledger)
        assert before[-2] > 0 and before[-1] > 0
        assert {leg['order_id'] for leg in ledger.unresolved_legs()} == set(missing)

        filled = missing[0]
        leg = ledger.legs[ledger.by_order[filled]]
        read['terminal_orders'][filled]['row'].update(status='MATCHED', size_matched='1')
        matched_amount = 'unreadable' if packet_case == 'malformed_trade' else '1'
        read['trades'] = [{'id': 'confirmed-own-fill', 'status': 'CONFIRMED',
                           'maker_orders': [{'order_id': filled, 'matched_amount': matched_amount}]}]
        read['positions'] = [{'asset': leg['token_id'], 'size': '1'}]
        cash = CapitalBook(ledger).expected_cash() - native(quantity(leg['price']))
        available = str(quantity(cash) / SCALE)
        read['balances'] = {'available_collateral': available, 'assets': {ASSET: available},
                            'collateral_evidence': {'balance': str(cash)}}

        if packet_case == 'missing_component':
            del read['component_times']['positions']
        if packet_case in {'stale_component', 'valid_matched'}:
            # The packet end and named GETs are still fresh in both cases.
            age = 121 if packet_case == 'stale_component' else 120
            oldest = (clock.now() - timedelta(seconds=age)).isoformat()
            read['started_at_utc'] = oldest
            read['component_times']['trades']['started_at_utc'] = oldest
        monkeypatch.setattr(runtime, 'read_account', lambda **kw: read)

        if packet_case != 'valid_matched':
            error, reason = {
                'stale_component': (TransientPrecheck, 'account_read_stale'),
                'missing_component': (StateRefused, 'account_read_binding'),
                'malformed_trade': (ValueError, 'quantity_unreadable'),
            }[packet_case]
            with pytest.raises(error, match=reason):
                runtime.postcheck(claim, result)
            assert terminal_ledger_snapshot(runtime.state.ledger) == before
            assert not list((runtime.state.root / 'postchecks').glob('*.json'))
            return

        terminal = Ledger.terminal

        def advancing_terminal(self, *args, **kwargs):
            # The preflight's 120-second cut applies to this packet even if
            # appending takes time. Do not re-age it after releasing reserves.
            clock.sleep(1)
            return terminal(self, *args, **kwargs)

        monkeypatch.setattr(Ledger, 'terminal', advancing_terminal)
        proof = runtime.postcheck(claim, result)
        ledger = runtime.state.ledger
        after = terminal_ledger_snapshot(ledger)
        assert proof['cleanup_proven'] and proof['money_accounting_complete']
        assert after[0] != before[0] and after[1] != before[1]
        assert after[2].startswith(before[2]) and after[-2:] == (0, 0)
        assert ledger.legs[ledger.by_order[filled]]['size_matched'] == '1'
        assert {oid for oid in missing if after[3][ledger.by_order[oid]]['status'] == 'terminal'} == set(missing)


@pytest.mark.parametrize(('fields', 'refusal'), [
    ({'asset_id': 'other'}, 'identity'),
    ({'side': 'SELL'}, 'identity'),
    ({'price': '.49'}, 'price'),
    ({'official_order_status': 'LIVE'}, 'status'),
    ({'status': 'LIVE'}, None),
    ({}, None),
])
def test_extra_unresolved_lookup_uses_same_facts_before_first_write(tmp_path, monkeypatch, fields, refusal):
    from tests.market.lfc_campaign_fixtures import private_result
    from tests.market.test_lfc_campaign import NOW, policy_row
    from tests.market.test_lfc_campaign_runtime import account_read, runtime_at
    from weather.market.lfc_campaign_policy import parse_policy

    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        good = {'id': 'o', 'status': 'CANCELED', 'size_matched': '0', 'asset_id': 't', 'side': 'BUY', 'price': '.5'}
        # The private journal has a terminal row while the acknowledged leg
        # remains unresolved in the ledger, so the lookup is not named.
        _, result = private_result(runtime, claim, faults=('terminal_order_unavailable',), terminal_read_gap=True,
                                   extra_rows=({'event': 'terminal_order', 'order': good},))
        assert result['local_money_proof']['complete']
        assert 'missing_terminal_orders' not in result['local_money_proof']
        runtime.save_result(claim, result)
        saved = runtime.saved_result(claim)
        runtime.lease = SimpleNamespace(check=lambda: None)
        read = account_read(runtime)
        stamp = runtime.clock.now().isoformat()
        read['terminal_orders'] = {'o': {
            'row': {**good, **fields}, 'started_at_utc': stamp, 'ended_at_utc': stamp}}
        get = Mock(return_value=read)
        monkeypatch.setattr(runtime, 'read_account', get)
        ledger = runtime.state.ledger
        before = terminal_ledger_snapshot(ledger)
        assert before[-2] > 0 and ledger.legs[ledger.by_order['o']]['status'] == 'open'
        if refusal:
            with pytest.raises(TerminalBackfillRefused, match=f'terminal_order_backfill_{refusal}'):
                runtime.postcheck(claim, saved)
        else:
            proof = runtime.postcheck(claim, saved)
            terminal = fields.get('status') != 'LIVE'
            assert proof['money_accounting_complete'] is terminal
        get.assert_called_once_with()
        after = terminal_ledger_snapshot(runtime.state.ledger)
        if fields:
            assert after == before
        else:
            assert after[0] != before[0] and after[2].startswith(before[2]) and after[-2:] == (0, 0)
